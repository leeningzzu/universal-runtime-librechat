"""C5 existing Runtime webapp thin route composition, no separate App or DB.

Production-shaped candidate: calls current _service() and existing installed-aware
retirement primitives. No fixture auth header or mutable test injection.
"""
from __future__ import annotations

from typing import Callable
import hmac
import os

from fastapi import FastAPI, HTTPException, Request

from universal_runtime.web_continuity import (
    WebContinuityError, _stable_id, _validate_command_id, _validate_label,
)
# Historical JobAuthority is not a SourceRef/Memory read dependency.
# Current target-Project executable Jobs remain a separate C5 effect owner.

def install_project_retirement_routes(app: FastAPI, get_service: Callable):
    def require_existing_adapter_proxy(request: Request) -> None:
        expected = os.environ.get("UR_RUNTIME_PROXY_KEY", "")
        if not expected:
            raise HTTPException(status_code=503, detail={"code": "RUNTIME_PROXY_KEY_NOT_CONFIGURED"})
        supplied = request.headers.get("x-ur-runtime-proxy", "")
        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=401, detail={"code": "RUNTIME_ADAPTER_AUTH_REQUIRED"})

    def report(error: WebContinuityError) -> None:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error

    @app.get("/api/web/project-retirement/resolve")
    def project_retirement_resolve(request: Request, command_id: str, display_name: str):
        require_existing_adapter_proxy(request)
        service = get_service()
        try:
            command_id = _validate_command_id(command_id)
            display_name = _validate_label(display_name, "display_name")
            project_id = _stable_id("PRJ", command_id, display_name)
            if not service._record_exists(service._project_artifact_id(project_id)):
                memories = service.memory_service.list_memories(
                    project_id=project_id, include_deleted=True,
                )
                prior_create = service._record_exists(
                    service._command_artifact_id(command_id)
                )
                receipts = service._project_operation_receipts(project_id)
                work = service._machine_local_project_work_binding(project_id)
                if (
                    prior_create or memories["state_revision"] != 0 or
                    receipts or work is not None
                ):
                    raise WebContinuityError(
                        "RUNTIME_PROJECT_ORPHAN_STATE",
                        "Related Runtime state exists without a canonical Project",
                        status_code=409,
                    )
                return {
                    "found": False, "native_only_verified": True,
                    "project_id": project_id,
                }
            project, _ = service._raw_project(project_id)
            if (
                project.get("created_by_command_id") != command_id
                or project.get("display_name") != display_name
            ):
                raise WebContinuityError(
                    "PROJECT_IDENTITY_CONFLICT",
                    "Project creation provenance mismatch", status_code=409,
                )
            return {
                "found": True,
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "status": project.get("status", "ACTIVE"),
                "retirement": project.get("retirement"),
            }
        except WebContinuityError as error:
            report(error)

    @app.post("/api/web/projects/{project_id}/retirement/{action}")
    async def retire_project(project_id: str, action: str, request: Request):
        require_existing_adapter_proxy(request)
        if action not in {"prepare", "confirm", "abort", "commit"}:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ACTION"})
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("retirement_id"), str):
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST"})
        retirement_id = payload["retirement_id"]
        service = get_service()
        try:
            if action == "prepare":
                expected = payload.get("expected_project_revision")
                if not isinstance(expected, int) or isinstance(expected, bool):
                    raise HTTPException(status_code=400, detail={"code": "REVISION_REQUIRED"})
                return service.prepare_project_retirement(
                    retirement_id=retirement_id,
                    project_id=project_id,
                    expected_project_revision=expected,
                )
            if action == "confirm":
                return service.confirm_librechat_deleted(
                    retirement_id=retirement_id, project_id=project_id,
                )
            if action == "abort":
                if payload.get("reason_code") != "LIBRECHAT_DELETE_FAILED":
                    raise HTTPException(status_code=400, detail={"code": "ABORT_REASON_INVALID"})
                return service.abort_project_retirement(
                    retirement_id=retirement_id,
                    project_id=project_id,
                    reason_code="LIBRECHAT_DELETE_FAILED",
                )
            return service.commit_project_retirement(
                retirement_id=retirement_id, project_id=project_id,
            )
        except WebContinuityError as error:
            report(error)


    @app.get("/api/web/projects/{project_id}/c5-reference-inventory")
    def c5_reference_inventory(project_id: str, request: Request):
        """Read current native-bound Runtime SourceRef + Memory owner, even RETIRED.

        Normal resume_project() intentionally disallows retired Projects; use
        existing _raw_project, _source_ref and memory_service with one owner lock.
        Project-scoped metadata only; NEVER transmit memory text/source contents,
        claim FileID or Blob exclusivity, or change any retirement state.
        """
        require_existing_adapter_proxy(request)
        service = get_service()
        try:
            with service._lock:
                project, _ = service._raw_project(project_id)
                if project.get("project_id") != project_id:
                    raise WebContinuityError(
                        "C5_PROJECT_SCOPE_CHANGED", "canonical project changed", status_code=409
                    )
                status = project.get("status", "ACTIVE")
                instruction_binding = project.get("project_instruction_binding")
                if not isinstance(instruction_binding, dict):
                    raise WebContinuityError(
                        "C5_INSTRUCTIONS_BINDING_INVALID",
                        "Canonical Instructions binding unavailable", status_code=409
                    )
                current_instructions = service._load_exact_text_binding(instruction_binding)
                current_instructions_empty = current_instructions == ""
                if status == "RETIRED" and not current_instructions_empty:
                    raise WebContinuityError(
                        "C5_RETIRED_INSTRUCTIONS_STILL_PRESENT",
                        "Retired Project retains current Instructions", status_code=409
                    )

                if status not in {"ACTIVE", "RETIRE_PENDING", "RETIRED"}:
                    raise WebContinuityError(
                        "C5_PROJECT_STATUS_UNSUPPORTED", "unknown project state", status_code=409
                    )
                source_ids = project.get("source_ref_ids")
                if not isinstance(source_ids, list) or len(source_ids) > 20000 or len(set(source_ids)) != len(source_ids):
                    raise WebContinuityError(
                        "C5_SOURCE_REFERENCE_GRAPH_INVALID", "invalid source references", status_code=409
                    )
                sources = []
                for source_id in source_ids:
                    ref, binding = service._source_ref(source_id)
                    if ref.get("project_id") != project_id or ref.get("source_ref_id") != source_id:
                        raise WebContinuityError(
                            "C5_SOURCE_REFERENCE_OWNER_INVALID", "cross-project source", status_code=409
                        )
                    artifact = ref.get("source_artifact_binding")
                    if not isinstance(artifact, dict) or not isinstance(artifact.get("sha256"), str):
                        raise WebContinuityError(
                            "C5_SOURCE_ARTIFACT_BINDING_INVALID", "source identity unavailable", status_code=409
                        )
                    provenance = ref.get("provenance")
                    sources.append({
                        "source_ref": {
                            "project_id": project_id,
                            "source_ref_id": source_id,
                            "origin_class": ref.get("origin_class"),
                            "source_artifact_binding": {"sha256": artifact["sha256"]},
                            "provenance": {
                                "conversation_id": provenance.get("conversation_id")
                            } if isinstance(provenance, dict) else None,
                        },
                        "binding": {"revision": binding.get("revision")},
                    })
                memory = service.memory_service.list_memories(
                    project_id=project_id, include_deleted=False
                )
                if memory.get("project_id") != project_id:
                    raise WebContinuityError(
                        "C5_MEMORY_PROJECT_SCOPE_INVALID", "foreign memory owner", status_code=409
                    )
                current_memories = [{
                    "project_id": project_id,
                    "memory_id": item["memory_id"],
                    "memory_revision": item["memory_revision"],
                    "lifecycle_state": item["lifecycle_state"],
                } for item in memory["memories"]]
                after, _ = service._raw_project(project_id)
                if (after.get("project_revision") != project.get("project_revision")
                    or after.get("status", "ACTIVE") != status
                    or after.get("source_ref_ids") != source_ids):
                    raise WebContinuityError(
                        "C5_RUNTIME_REFERENCE_READ_STALE", "project changed while reading", status_code=409
                    )
                memory_again = service.memory_service.list_memories(
                    project_id=project_id, include_deleted=False
                )
                if memory_again["state_revision"] != memory["state_revision"]:
                    raise WebContinuityError(
                        "C5_RUNTIME_MEMORY_READ_STALE", "memory changed while reading", status_code=409
                    )
                # Do not scan the 113 global historical JAE records to read
                # Project Source/Memory. Point-of-effect admission separately
                # establishes current target Job, writer and backup safety.
                final_project, _ = service._raw_project(project_id)
                if (
                    final_project.get("project_revision") != project.get("project_revision")
                    or final_project.get("status", "ACTIVE") != status
                    or final_project.get("source_ref_ids") != source_ids
                ):
                    raise WebContinuityError(
                        "C5_RUNTIME_PROJECT_CHANGED_AFTER_REFERENCE_READ",
                        "Project changed after Source/Memory read",
                        status_code=409,
                    )
                return {
                    "project": {
                        "project_id": project_id,
                        "project_revision": project["project_revision"],
                        "status": status,
                        "source_ref_ids": source_ids,
                    },
                    "sources": sources,

                    "instructions": {"current_empty": current_instructions_empty},
                    "memory": {
                        "schema": memory["schema"],
                        "project_id": project_id,
                        "state_revision": memory["state_revision"],
                        "memories": current_memories,
                    },
                }
        except WebContinuityError as error:
            report(error)
