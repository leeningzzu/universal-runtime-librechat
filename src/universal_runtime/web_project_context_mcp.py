from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from universal_runtime.web_project_semantic_search import ProjectSemanticSearchAdapter

_LIBRECHAT_PROJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_PROJECT_DISPLAY_NAME = "LibreChat Project Context"
_PROJECT_SCOPE: ContextVar[str | None] = ContextVar("librechat_project_scope", default=None)


class LibreChatProjectScopeMiddleware:
    """Bind LibreChat's trusted request-scoped Project header to one MCP request."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        token = None
        if scope.get("type") == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            token = _PROJECT_SCOPE.set(headers.get("x-librechat-project-id"))
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                _PROJECT_SCOPE.reset(token)


def _require_librechat_project_id() -> str:
    value = (_PROJECT_SCOPE.get() or "").strip()
    if not value:
        raise RuntimeError("LIBRECHAT_PROJECT_SCOPE_REQUIRED")
    if _LIBRECHAT_PROJECT_ID_RE.fullmatch(value) is None:
        raise RuntimeError("LIBRECHAT_PROJECT_SCOPE_INVALID")
    return value.lower()


def _binding_command_id(librechat_project_id: str) -> str:
    digest = hashlib.sha256(librechat_project_id.encode("utf-8")).hexdigest()[:28]
    return f"final-shell-project-by-librechat-project-{digest}"


def _resolve_runtime_project(service: Any, librechat_project_id: str) -> dict[str, Any]:
    resolved = service.resolve_project_instructions_by_creation_identity(
        command_id=_binding_command_id(librechat_project_id),
        display_name=_PROJECT_DISPLAY_NAME,
    )
    if not isinstance(resolved, dict):
        raise RuntimeError("RUNTIME_PROJECT_SCOPE_MISSING")
    project_id = resolved.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise RuntimeError("RUNTIME_PROJECT_SCOPE_INVALID")
    return resolved


def create_project_context_mcp(
    *,
    runtime_root: Path,
    service_getter: Callable[[], Any],
) -> tuple[FastMCP, Any]:
    """Create a read-only request-scoped MCP server over existing Runtime Project context."""

    mcp = FastMCP(
        "Runtime Project Context",
        instructions=(
            "Use these tools for facts, Project Sources, prior Project discussion, Project-specific "
            "instructions, and the optional Project-local work binding. Project scope is supplied by LibreChat "
            "and cannot be selected by the model. Before any Local Action provider access/effect, call "
            "project_local_work_binding. If binding is null, do not invoke local canonical work and do not guess. "
            "Treat binding.executor as the current selected provider identity and binding.local_project_root as "
            "machine-local resolution only. Use only a currently exposed provider/tool surface whose exact provider "
            "identity matches binding.executor; provider-specific invocation instructions belong to that provider "
            "surface, not this Project Context server. If no matching provider surface is exposed, stop as unavailable. "
            "Never treat a Runtime PRJ_* project id, raw provider session/project handle, or local path as portable Project identity."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["host.docker.internal:*", "127.0.0.1:*", "localhost:*"],
        ),
    )

    def current_scope() -> tuple[Any, str, dict[str, Any]]:
        service = service_getter()
        librechat_project_id = _require_librechat_project_id()
        resolved = _resolve_runtime_project(service, librechat_project_id)
        return service, resolved["project_id"], resolved

    @mcp.tool()
    def project_instructions() -> dict[str, Any]:
        """Read exact current Project Instructions and provenance for this Project."""
        _, _, resolved = current_scope()
        return {
            "project_id": resolved["project_id"],
            "project_revision": resolved.get("project_revision"),
            "project_instruction_binding": resolved.get("project_instruction_binding"),
            "project_instructions": resolved.get("project_instructions", ""),
        }

    @mcp.tool()
    def project_local_work_binding() -> dict[str, Any]:
        """Read the optional machine-local Local Action provider binding for this Project."""
        service, project_id, _ = current_scope()
        return service.get_project_local_work_binding(project_id=project_id)

    @mcp.tool()
    def project_source_search(query: str, top_k: int = 3) -> dict[str, Any]:
        """Search current Project Sources with Runtime's existing local source retrieval."""
        service, project_id, _ = current_scope()
        return ProjectSemanticSearchAdapter(
            runtime_root=runtime_root,
            service=service,
        ).search(project_id=project_id, query=query, top_k=top_k)

    @mcp.tool()
    def project_recent_history(max_bytes: int = 16384) -> dict[str, Any]:
        """Read bounded recent same-Project history; Native Agent chat itself is not a Runtime Chat."""
        service, project_id, _ = current_scope()
        return service.build_project_history_context(
            project_id=project_id,
            exclude_chat_id=None,
            max_bytes=max_bytes,
        )

    return mcp, LibreChatProjectScopeMiddleware(mcp.streamable_http_app())
