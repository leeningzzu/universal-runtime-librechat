from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.web_continuity import WebContinuityService
from universal_runtime.web_project_context_mcp import (
    _binding_command_id,
    create_project_context_mcp,
)


def _rpc(client: TestClient, rpc_id: int, method: str, params: dict, headers: dict[str, str]) -> dict:
    response = client.post(
        "/ctx/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params},
    )
    assert response.status_code == 200
    return response.json()


def _tool_text(client: TestClient, rpc_id: int, name: str, arguments: dict, headers: dict[str, str]) -> dict:
    body = _rpc(
        client,
        rpc_id,
        "tools/call",
        {"name": name, "arguments": arguments},
        headers,
    )
    assert body["result"]["isError"] is False
    return json.loads(body["result"]["content"][0]["text"])


def test_native_agent_project_context_mcp_reuses_existing_project_history_and_scope(tmp_path):
    service = WebContinuityService(ArtifactStore(tmp_path / "artifacts"))
    librechat_project_id = "a" * 24
    created = service.create_project(
        command_id=_binding_command_id(librechat_project_id),
        display_name="LibreChat Project Context",
        instructions="When asked, return INSTRUCTION_CTX_PASS.",
    )
    project = created["project"]

    first = service.create_chat(
        command_id="mcp-history-chat-1",
        project_id=project["project_id"],
        expected_project_revision=project["project_revision"],
        title="First",
    )
    project = first["project"]
    first_message = service.append_user_message(
        command_id="mcp-history-message-1",
        project_id=project["project_id"],
        chat_id=first["chat"]["chat_id"],
        expected_chat_revision=first["chat"]["chat_revision"],
        content="HISTORY-FIRST-R001",
    )

    second = service.create_chat(
        command_id="mcp-history-chat-2",
        project_id=project["project_id"],
        expected_project_revision=project["project_revision"],
        title="Second",
    )
    second_message = service.append_user_message(
        command_id="mcp-history-message-2",
        project_id=project["project_id"],
        chat_id=second["chat"]["chat_id"],
        expected_chat_revision=second["chat"]["chat_revision"],
        content="HISTORY-SECOND-R001",
    )

    all_history = service.build_project_history_context(
        project_id=project["project_id"],
        exclude_chat_id=None,
        max_bytes=65536,
    )
    all_blob = json.dumps(all_history, ensure_ascii=False)
    assert "HISTORY-FIRST-R001" in all_blob
    assert "HISTORY-SECOND-R001" in all_blob
    assert all_history["project_history_context"]["excluded_chat_id"] is None

    old_semantics = service.build_project_history_context(
        project_id=project["project_id"],
        exclude_chat_id=first_message["chat"]["chat_id"],
        max_bytes=65536,
    )
    old_blob = json.dumps(old_semantics, ensure_ascii=False)
    assert "HISTORY-FIRST-R001" not in old_blob
    assert "HISTORY-SECOND-R001" in old_blob
    assert old_semantics["project_history_context"]["excluded_chat_id"] == first_message["chat"]["chat_id"]

    mcp, mcp_asgi = create_project_context_mcp(
        runtime_root=tmp_path,
        service_getter=lambda: service,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/ctx", mcp_asgi)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "host": "localhost:8000",
        "x-librechat-project-id": librechat_project_id,
    }

    with TestClient(app) as client:
        initialized = _rpc(
            client,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "project-context-test", "version": "1"},
            },
            headers,
        )
        assert initialized["result"]["protocolVersion"]
        server_instructions = initialized["result"].get("instructions", "")
        assert "WebCodex" not in server_instructions
        assert "binding.executor" in server_instructions
        assert "Local Action provider" in server_instructions

        tools = _rpc(client, 2, "tools/list", {}, headers)
        assert sorted(tool["name"] for tool in tools["result"]["tools"]) == [
            "project_instructions",
            "project_local_work_binding",
            "project_recent_history",
            "project_source_search",
        ]

        instructions = _tool_text(client, 3, "project_instructions", {}, headers)
        assert "INSTRUCTION_CTX_PASS" in instructions["project_instructions"]


        current_project = service.resume_project(project["project_id"])["project"]
        bound = service.bind_project_local_work(
            command_id="mcp-local-work-binding-1",
            project_id=project["project_id"],
            expected_project_revision=current_project["project_revision"],
            executor="webcodex-local",
            local_project_root=str(tmp_path.resolve()),
        )
        local_work = _tool_text(client, 6, "project_local_work_binding", {}, headers)
        assert local_work["binding"] == bound["local_work_binding"]
        assert local_work["binding"]["executor"] == "webcodex-local"
        assert local_work["binding"]["local_project_root"] == str(tmp_path.resolve())

        recent = _tool_text(
            client,
            4,
            "project_recent_history",
            {"max_bytes": 65536},
            headers,
        )
        recent_blob = json.dumps(recent, ensure_ascii=False)
        assert "HISTORY-FIRST-R001" in recent_blob
        assert "HISTORY-SECOND-R001" in recent_blob

        invalid_headers = dict(headers)
        invalid_headers["x-librechat-project-id"] = "not-a-project"
        invalid = _rpc(client, 5, "tools/call", {"name": "project_instructions", "arguments": {}}, invalid_headers)
        assert invalid["result"]["isError"] is True

    assert second_message["chat"]["chat_id"] == second["chat"]["chat_id"]
