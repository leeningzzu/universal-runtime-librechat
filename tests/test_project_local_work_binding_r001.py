from __future__ import annotations

import json

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.web_continuity import WebContinuityError, WebContinuityService
from universal_runtime import webapp


def _service(tmp_path: Path) -> WebContinuityService:
    return WebContinuityService(
        ArtifactStore(tmp_path / "artifacts"),
        machine_local_state_root=tmp_path / "machine-local",
    )


def _project(service: WebContinuityService) -> dict:
    return service.create_project(
        command_id="project-local-work-binding-fixture",
        display_name="Local Work Binding Fixture",
        instructions="Use exact local work binding.",
    )["project"]


def test_local_work_binding_revision_noop_replay_and_unbind(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = _project(service)
    root = str((tmp_path / "local-project").resolve())

    first = service.bind_project_local_work(
        command_id="bind-local-work",
        project_id=project["project_id"],
        expected_project_revision=1,
        executor="webcodex-local",
        local_project_root=root,
    )
    assert first["project"]["project_revision"] == 1
    assert "local_work_binding" not in first["project"]
    assert first["local_work_binding"] == {
        "executor": "webcodex-local",
        "binding_class": "MACHINE_LOCAL_PROJECT_ROOT",
        "local_project_root": root,
    }
    assert first["operation"]["details"]["executor_invoked"] is False
    assert first["operation"]["details"]["job_created"] is False

    noop = service.bind_project_local_work(
        command_id="bind-local-work-noop",
        project_id=project["project_id"],
        expected_project_revision=1,
        executor="webcodex-local",
        local_project_root=root,
    )
    replay = service.bind_project_local_work(
        command_id="bind-local-work-noop",
        project_id=project["project_id"],
        expected_project_revision=1,
        executor="webcodex-local",
        local_project_root=root,
    )
    assert noop["project"]["project_revision"] == 1
    assert noop["local_work_binding_changed"] is False
    assert noop["operation"]["details"]["local_work_binding_action"] == "NO_OP_ALREADY_BOUND"
    assert replay == noop

    unbound = service.unbind_project_local_work(
        command_id="unbind-local-work",
        project_id=project["project_id"],
        expected_project_revision=1,
    )
    assert unbound["project"]["project_revision"] == 1
    assert unbound["local_work_binding"] is None
    assert "local_work_binding" not in unbound["project"]



def test_local_work_binding_is_machine_local_not_artifact_persisted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = _project(service)
    root = str((tmp_path / "local-project").resolve())

    bound = service.bind_project_local_work(
        command_id="machine-local-only-bind",
        project_id=project["project_id"],
        expected_project_revision=1,
        executor="webcodex-local",
        local_project_root=root,
    )
    assert bound["project"]["project_revision"] == 1
    assert "local_work_binding" not in bound["project"]
    assert (
        service.get_project_local_work_binding(project_id=project["project_id"])["binding"]
        == bound["local_work_binding"]
    )

    artifact_blob = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "artifacts").rglob("*.json")
    )
    assert root not in artifact_blob
    assert "webcodex-local" not in artifact_blob
    registry = tmp_path / "machine-local" / "project_local_work_bindings.json"
    assert registry.is_file()
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    registry_binding = registry_payload["bindings"][project["project_id"]]
    assert registry_binding["local_project_root"] == root
    assert registry_binding["executor"] == "webcodex-local"


def test_legacy_local_work_binding_migration_sanitizes_current_records(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = _project(service)
    root = str((tmp_path / "legacy-local-project").resolve())
    op_exec = service._operation_execution_id(
        project_id=project["project_id"],
        chat_id=None,
        command_id="legacy-fixture",
    )
    legacy_project = dict(project)
    legacy_project["local_work_binding"] = {
        "executor": "webcodex-local",
        "binding_class": "MACHINE_LOCAL_PROJECT_ROOT",
        "local_project_root": root,
    }
    legacy_project, _ = service._persist_json_revision(
        artifact_id=service._project_artifact_id(project["project_id"]),
        namespace="projects",
        record=legacy_project,
        revision_field="project_revision",
        operation_execution_id=op_exec,
    )
    assert legacy_project["project_revision"] == 2

    migrated = service.migrate_legacy_project_local_work_binding(
        project_id=project["project_id"],
        expected_project_revision=2,
        migration_id="migrate-machine-local-binding",
    )
    assert migrated["migrated"] is True
    assert migrated["project"]["project_revision"] == 3
    assert "local_work_binding" not in migrated["project"]
    assert migrated["binding"]["local_project_root"] == root
    current = service.get_project_local_work_binding(project_id=project["project_id"])
    assert current["binding"]["local_project_root"] == root

    current_project, _ = service._project(project["project_id"])
    assert "local_work_binding" not in current_project
    registry_payload = json.loads(
        (tmp_path / "machine-local" / "project_local_work_bindings.json").read_text(encoding="utf-8")
    )
    registry_binding = registry_payload["bindings"][project["project_id"]]
    assert registry_binding["local_project_root"] == root
    assert registry_binding["executor"] == "webcodex-local"

def test_local_work_binding_stale_and_invalid_executor_fail_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = _project(service)
    root = str(tmp_path.resolve())

    with pytest.raises(WebContinuityError) as invalid:
        service.bind_project_local_work(
            command_id="bad-executor",
            project_id=project["project_id"],
            expected_project_revision=1,
            executor="other-executor",
            local_project_root=root,
        )
    assert invalid.value.code == "PROJECT_LOCAL_WORK_EXECUTOR_UNSUPPORTED"

    service.bind_project_local_work(
        command_id="valid-bind",
        project_id=project["project_id"],
        expected_project_revision=1,
        executor="webcodex-local",
        local_project_root=root,
    )
    with pytest.raises(WebContinuityError) as stale:
        service.unbind_project_local_work(
            command_id="stale-unbind",
            project_id=project["project_id"],
            expected_project_revision=0,
        )
    assert stale.value.code == "STALE_PROJECT_REVISION"


def test_local_work_binding_web_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    project = _project(service)
    monkeypatch.setattr(webapp, "_SERVICE", service)
    client = TestClient(webapp.app)
    root = str(tmp_path.resolve())

    before = client.get(f"/api/web/projects/{project['project_id']}/local-work-binding")
    assert before.status_code == 200
    assert before.json()["binding"] is None

    bound = client.put(
        f"/api/web/projects/{project['project_id']}/local-work-binding",
        json={
            "command_id": "api-bind-local-work",
            "expected_project_revision": 1,
            "executor": "webcodex-local",
            "local_project_root": root,
        },
    )
    assert bound.status_code == 200
    assert bound.json()["local_work_binding"]["local_project_root"] == root
    assert bound.json()["project"]["project_revision"] == 1

    unbound = client.request(
        "DELETE",
        f"/api/web/projects/{project['project_id']}/local-work-binding",
        json={"command_id": "api-unbind-local-work", "expected_project_revision": 1},
    )
    assert unbound.status_code == 200
    assert unbound.json()["local_work_binding"] is None
