from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from universal_runtime.web_continuity import (  # noqa: E402
    WebContinuityService,
    WebContinuityError,
    _validate_command_id,
    _utc_now,
)
from universal_runtime.web_project_memory import ProjectMemoryService  # noqa: E402
from universal_runtime.c5_protected_backup_manifest_census import (  # noqa: E402
    C5ProtectedBackupCensusError,
    protected_backup_manifest_census_sha256,
)

ACTIVE = "ACTIVE"
RETIRE_PENDING = "RETIRE_PENDING"
RETIRED = "RETIRED"


class RetirementWebContinuityService(WebContinuityService):
    """Candidate-only Project retirement owner.

    This subclass changes no Production source. Ordinary WebContinuityService
    operations fail closed while a Project is RETIRE_PENDING or RETIRED.
    Retirement internals may temporarily read those records to invoke the
    existing revision-checked retirement primitives.
    """

    def __init__(self, *args: Any, memory_service: ProjectMemoryService | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.memory_service = memory_service or ProjectMemoryService(self.store)
        self._retirement_internal_depth = 0

    @contextmanager
    def _retirement_access(self):
        self._retirement_internal_depth += 1
        try:
            yield
        finally:
            self._retirement_internal_depth -= 1

    def _project(self, project_id: str, *, include_nonactive: bool = False):
        project, binding = super()._project(project_id)
        status = project.get("status", ACTIVE)
        if (
            status != ACTIVE
            and not include_nonactive
            and self._retirement_internal_depth == 0
        ):
            raise WebContinuityError(
                "PROJECT_NOT_ACTIVE",
                f"Project is not active: {status}",
                status_code=410,
            )
        return project, binding

    @staticmethod
    def _phase_command(retirement_id: str, phase: str) -> str:
        _validate_command_id(retirement_id)
        return _validate_command_id(f"{retirement_id}:{phase}")

    def _raw_project(self, project_id: str):
        return super()._project(project_id)

    def c5_protected_backup_manifest_census_sha256(self) -> str:
        try:
            return protected_backup_manifest_census_sha256()
        except C5ProtectedBackupCensusError as exc:
            raise WebContinuityError(
                "C5_PROTECTED_BACKUP_MANIFEST_CENSUS_INVALID",
                str(exc),
                status_code=409,
            ) from exc

    def _runtime_protected_asset_census_sha256(self) -> str:
        # Ordinary ACTIVE Project/File retirement retains the inherited full-byte
        # census. Only an already-RETIRED Project under the internal forward-
        # recovery fence uses the bounded, exact protected-manifest proof set.
        if self._retirement_internal_depth > 0:
            return self.c5_protected_backup_manifest_census_sha256()
        return super()._runtime_protected_asset_census_sha256()


    def retire_project_source_content(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        source_ref_id: str,
        owner_id: str,
        external_ref_counts: dict[str, Any],
        protected_asset_census_sha256: str | None,
        binding_class: str,
        native_file_ids: list[str],
        source_ref_ids: list[str],
        binding_evidence_sha256: str,
    ) -> dict[str, Any]:
        project, _ = self._raw_project(project_id)
        status = project.get("status", ACTIVE)
        if status != RETIRED:
            return super().retire_project_source_content(
                command_id=command_id,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                source_ref_id=source_ref_id,
                owner_id=owner_id,
                external_ref_counts=external_ref_counts,
                protected_asset_census_sha256=protected_asset_census_sha256,
                binding_class=binding_class,
                native_file_ids=native_file_ids,
                source_ref_ids=source_ref_ids,
                binding_evidence_sha256=binding_evidence_sha256,
            )

        retirement = project.get("retirement")
        inventory = retirement.get("inventory") if isinstance(retirement, dict) else None
        frozen_sources = inventory.get("source_ref_ids") if isinstance(inventory, dict) else None
        current_census = self.c5_protected_backup_manifest_census_sha256()
        exact_scope = (
            isinstance(command_id, str)
            and command_id.startswith("c5-project-source-delete-")
            and project.get("project_revision") == expected_project_revision
            and isinstance(retirement, dict)
            and retirement.get("phase") == "COMMITTED"
            and isinstance(frozen_sources, list)
            and source_ref_id in frozen_sources
            and binding_class == "EXACT_RUNTIME_SOURCE_ONLY"
            and native_file_ids == []
            and source_ref_ids == [source_ref_id]
            and isinstance(owner_id, str)
            and len(owner_id) == 64
            and all(char in "0123456789abcdef" for char in owner_id)
            and isinstance(protected_asset_census_sha256, str)
            and protected_asset_census_sha256 == current_census
            and isinstance(binding_evidence_sha256, str)
            and len(binding_evidence_sha256) == 64
            and all(char in "0123456789abcdef" for char in binding_evidence_sha256)
        )
        if not exact_scope:
            raise WebContinuityError(
                "C5_RETIRED_SOURCE_FORWARD_RECOVERY_SCOPE_INVALID",
                "Retired Project Source cleanup is not bound to the frozen C5 inventory",
                status_code=409,
            )
        with self._retirement_access():
            return super().retire_project_source_content(
                command_id=command_id,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                source_ref_id=source_ref_id,
                owner_id=owner_id,
                external_ref_counts=external_ref_counts,
                protected_asset_census_sha256=current_census,
                binding_class=binding_class,
                native_file_ids=native_file_ids,
                source_ref_ids=source_ref_ids,
                binding_evidence_sha256=binding_evidence_sha256,
            )

    def prepare_project_retirement(
        self,
        *,
        retirement_id: str,
        project_id: str,
        expected_project_revision: int,
    ) -> dict[str, Any]:
        command_id = self._phase_command(retirement_id, "PREPARE")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_RETIRE_PREPARE",
            scope={"project_id": project_id},
            payload={"expected_project_revision": expected_project_revision},
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay

            project, _ = self._raw_project(project_id)
            status = project.get("status", ACTIVE)
            pending = project.get("retirement") if isinstance(project.get("retirement"), dict) else {}
            if status == RETIRE_PENDING and pending.get("retirement_id") == retirement_id:
                binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                return self._finish_phase_receipt(
                    command_id=command_id,
                    command_type="PROJECT_RETIRE_PREPARE",
                    fingerprint=fingerprint,
                    project=project,
                    project_binding=binding,
                    project_id=project_id,
                    extra={"retirement_id": retirement_id, "recovered_after_partial_prepare": True},
                )
            if status != ACTIVE:
                raise WebContinuityError(
                    "PROJECT_NOT_ACTIVE",
                    f"Project retirement prepare requires ACTIVE, got {status}",
                    status_code=409,
                )
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )

            memories = self.memory_service.list_memories(project_id=project_id, include_deleted=True)
            local_work = self._machine_local_project_work_binding(project_id) or self._legacy_project_local_work_binding(project)
            inventory = {
                "memory_items": [
                    {
                        "memory_id": item["memory_id"],
                        "memory_revision": item["memory_revision"],
                        "lifecycle_state": item["lifecycle_state"],
                    }
                    for item in memories.get("memories", [])
                ],
                "source_ref_ids": list(project.get("source_ref_ids", [])),
                "assistant_profile_binding_present": project.get("assistant_profile_binding") is not None,
                "local_work_binding_present": local_work is not None,
            }

            op_exec = self._operation_execution_id(
                project_id=project_id, chat_id=None, command_id=command_id
            )
            next_record = dict(project)
            next_record["status"] = RETIRE_PENDING
            next_record["retirement"] = {
                "retirement_id": retirement_id,
                "phase": "PREPARED",
                "prepared_from_project_revision": expected_project_revision,
                "inventory": inventory,
                "prepared_at_utc": _utc_now(),
            }
            next_record["updated_at_utc"] = _utc_now()
            next_record["last_command_id"] = command_id
            next_record["last_input_fingerprint_sha256"] = fingerprint
            updated, binding = self._persist_json_revision(
                artifact_id=self._project_artifact_id(project_id),
                namespace="projects",
                record=next_record,
                revision_field="project_revision",
                operation_execution_id=op_exec,
            )
            return self._finish_phase_receipt(
                command_id=command_id,
                command_type="PROJECT_RETIRE_PREPARE",
                fingerprint=fingerprint,
                project=updated,
                project_binding=binding,
                project_id=project_id,
                extra={"retirement_id": retirement_id, "inventory": inventory},
            )

    def abort_project_retirement(
        self,
        *,
        retirement_id: str,
        project_id: str,
        reason_code: str = "LIBRECHAT_DELETE_FAILED",
    ) -> dict[str, Any]:
        command_id = self._phase_command(retirement_id, "ABORT")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_RETIRE_ABORT",
            scope={"project_id": project_id},
            payload={"reason_code": reason_code},
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._raw_project(project_id)
            retirement = project.get("retirement") if isinstance(project.get("retirement"), dict) else {}
            if (
                project.get("status", ACTIVE) != RETIRE_PENDING
                or retirement.get("retirement_id") != retirement_id
                or retirement.get("phase") != "PREPARED"
            ):
                raise WebContinuityError(
                    "PROJECT_RETIREMENT_STATE_CONFLICT",
                    "Project retirement can be aborted only from PREPARED",
                    status_code=409,
                )
            op_exec = self._operation_execution_id(
                project_id=project_id, chat_id=None, command_id=command_id
            )
            next_record = dict(project)
            next_record["status"] = ACTIVE
            next_retirement = dict(retirement)
            next_retirement.update(
                {
                    "phase": "ABORTED",
                    "abort_reason_code": reason_code,
                    "aborted_at_utc": _utc_now(),
                }
            )
            next_record["retirement"] = next_retirement
            next_record["updated_at_utc"] = _utc_now()
            next_record["last_command_id"] = command_id
            next_record["last_input_fingerprint_sha256"] = fingerprint
            updated, binding = self._persist_json_revision(
                artifact_id=self._project_artifact_id(project_id),
                namespace="projects",
                record=next_record,
                revision_field="project_revision",
                operation_execution_id=op_exec,
            )
            return self._finish_phase_receipt(
                command_id=command_id,
                command_type="PROJECT_RETIRE_ABORT",
                fingerprint=fingerprint,
                project=updated,
                project_binding=binding,
                project_id=project_id,
                extra={"retirement_id": retirement_id, "abort_reason_code": reason_code},
            )

    def confirm_librechat_deleted(
        self,
        *,
        retirement_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        command_id = self._phase_command(retirement_id, "LIBRECHAT_DELETED")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_RETIRE_LIBRECHAT_DELETED",
            scope={"project_id": project_id},
            payload={"retirement_id": retirement_id},
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._raw_project(project_id)
            retirement = project.get("retirement") if isinstance(project.get("retirement"), dict) else {}
            if (
                project.get("status") != RETIRE_PENDING
                or retirement.get("retirement_id") != retirement_id
                or retirement.get("phase") not in {"PREPARED", "LIBRECHAT_DELETED"}
            ):
                raise WebContinuityError(
                    "PROJECT_RETIREMENT_STATE_CONFLICT",
                    "LibreChat deletion confirmation requires PREPARED retirement",
                    status_code=409,
                )
            if retirement.get("phase") == "LIBRECHAT_DELETED":
                binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                return self._finish_phase_receipt(
                    command_id=command_id,
                    command_type="PROJECT_RETIRE_LIBRECHAT_DELETED",
                    fingerprint=fingerprint,
                    project=project,
                    project_binding=binding,
                    project_id=project_id,
                    extra={"retirement_id": retirement_id, "recovered_confirmation": True},
                )

            op_exec = self._operation_execution_id(
                project_id=project_id, chat_id=None, command_id=command_id
            )
            next_record = dict(project)
            next_retirement = dict(retirement)
            next_retirement.update(
                {
                    "phase": "LIBRECHAT_DELETED",
                    "librechat_deleted_at_utc": _utc_now(),
                }
            )
            next_record["retirement"] = next_retirement
            next_record["updated_at_utc"] = _utc_now()
            next_record["last_command_id"] = command_id
            next_record["last_input_fingerprint_sha256"] = fingerprint
            updated, binding = self._persist_json_revision(
                artifact_id=self._project_artifact_id(project_id),
                namespace="projects",
                record=next_record,
                revision_field="project_revision",
                operation_execution_id=op_exec,
            )
            return self._finish_phase_receipt(
                command_id=command_id,
                command_type="PROJECT_RETIRE_LIBRECHAT_DELETED",
                fingerprint=fingerprint,
                project=updated,
                project_binding=binding,
                project_id=project_id,
                extra={"retirement_id": retirement_id},
            )

    def commit_project_retirement(
        self,
        *,
        retirement_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        command_id = self._phase_command(retirement_id, "COMMIT")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_RETIRE_COMMIT",
            scope={"project_id": project_id},
            payload={"retirement_id": retirement_id},
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay

            project, _ = self._raw_project(project_id)
            retirement = project.get("retirement") if isinstance(project.get("retirement"), dict) else {}
            if project.get("status") == RETIRED and retirement.get("retirement_id") == retirement_id:
                instruction_binding = project.get("project_instruction_binding")
                if not isinstance(instruction_binding, dict) or (
                    self._load_exact_text_binding(instruction_binding) != ""
                ):
                    raise WebContinuityError(
                        "C5_RETIRED_PROJECT_INSTRUCTIONS_NOT_CLEARED",
                        "Retired Project still references active Instructions", status_code=409
                    )

                binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                return self._finish_phase_receipt(
                    command_id=command_id,
                    command_type="PROJECT_RETIRE_COMMIT",
                    fingerprint=fingerprint,
                    project=project,
                    project_binding=binding,
                    project_id=project_id,
                    extra={"retirement_id": retirement_id, "recovered_after_partial_commit": True},
                )
            if (
                project.get("status") != RETIRE_PENDING
                or retirement.get("retirement_id") != retirement_id
                or retirement.get("phase") != "LIBRECHAT_DELETED"
            ):
                raise WebContinuityError(
                    "PROJECT_RETIREMENT_STATE_CONFLICT",
                    "Project commit requires confirmed LibreChat deletion",
                    status_code=409,
                )

        # Existing primitives each own their own lock/receipt/idempotency.
        with self._retirement_access():
            memories = self.memory_service.list_memories(project_id=project_id, include_deleted=True)
            # Existing revisioned Project Instructions owner; do not create a
            # parallel notes backend or silently retire still-active content.
            project, _ = self._raw_project(project_id)
            instruction_binding = project.get("project_instruction_binding")
            if not isinstance(instruction_binding, dict):
                raise WebContinuityError(
                    "C5_PROJECT_INSTRUCTIONS_CURRENT_BINDING_MISSING",
                    "Project Instructions binding cannot be confirmed", status_code=409
                )
            if self._load_exact_text_binding(instruction_binding) != "":
                self.revise_project_instructions(
                    command_id=self._phase_command(retirement_id, "INSTRUCTIONS"),
                    project_id=project_id,
                    expected_project_revision=project["project_revision"],
                    instructions="",
                )
            project, _ = self._raw_project(project_id)
            current_binding = project.get("project_instruction_binding")
            if not isinstance(current_binding, dict) or (
                self._load_exact_text_binding(current_binding) != ""
            ):
                raise WebContinuityError(
                    "C5_PROJECT_INSTRUCTIONS_READBACK_NOT_EMPTY",
                    "Project current Instructions not cleared", status_code=409
                )

            for item in memories.get("memories", []):
                if item.get("lifecycle_state") == "DELETED":
                    continue
                self.memory_service.delete_memory(
                    command_id=self._phase_command(retirement_id, f"MEM.{item['memory_id']}"),
                    project_id=project_id,
                    memory_id=item["memory_id"],
                    expected_memory_revision=item["memory_revision"],
                )

            while True:
                project, _ = self._raw_project(project_id)
                source_ids = list(project.get("source_ref_ids", []))
                if not source_ids:
                    break
                source_ref_id = source_ids[0]
                self.remove_source_from_project(
                    command_id=self._phase_command(retirement_id, f"SRC.{source_ref_id}"),
                    project_id=project_id,
                    expected_project_revision=project["project_revision"],
                    source_ref_id=source_ref_id,
                )

            project, _ = self._raw_project(project_id)
            self.unbind_project_assistant_profile(
                command_id=self._phase_command(retirement_id, "ASSISTANT"),
                project_id=project_id,
                expected_project_revision=project["project_revision"],
            )

            project, _ = self._raw_project(project_id)
            self.unbind_project_local_work(
                command_id=self._phase_command(retirement_id, "LOCALWORK"),
                project_id=project_id,
                expected_project_revision=project["project_revision"],
            )

        with self._lock:
            project, _ = self._raw_project(project_id)
            retirement = project.get("retirement") if isinstance(project.get("retirement"), dict) else {}
            if project.get("status") != RETIRE_PENDING or retirement.get("retirement_id") != retirement_id:
                raise WebContinuityError(
                    "PROJECT_RETIREMENT_STATE_CONFLICT",
                    "Project retirement state changed during commit",
                    status_code=409,
                )
            op_exec = self._operation_execution_id(
                project_id=project_id, chat_id=None, command_id=command_id
            )
            next_record = dict(project)
            next_record["status"] = RETIRED
            instruction_binding = project.get("project_instruction_binding")
            if not isinstance(instruction_binding, dict) or (
                self._load_exact_text_binding(instruction_binding) != ""
            ):
                raise WebContinuityError(
                    "C5_RETIREMENT_FINAL_INSTRUCTIONS_NOT_EMPTY",
                    "Current Project Instructions were not cleared", status_code=409
                )

            next_retirement = dict(retirement)
            next_retirement.update(
                {
                    "phase": "COMMITTED",
                    "committed_at_utc": _utc_now(),
                }
            )
            next_record["retirement"] = next_retirement
            next_record["retired_at_utc"] = _utc_now()
            next_record["updated_at_utc"] = _utc_now()
            next_record["last_command_id"] = command_id
            next_record["last_input_fingerprint_sha256"] = fingerprint
            updated, binding = self._persist_json_revision(
                artifact_id=self._project_artifact_id(project_id),
                namespace="projects",
                record=next_record,
                revision_field="project_revision",
                operation_execution_id=op_exec,
            )
            return self._finish_phase_receipt(
                command_id=command_id,
                command_type="PROJECT_RETIRE_COMMIT",
                fingerprint=fingerprint,
                project=updated,
                project_binding=binding,
                project_id=project_id,
                extra={
                    "retirement_id": retirement_id,
                    "project_status": RETIRED,
                    "source_bytes_retained": True,
                    "audit_retained": True,
                },
            )

    def _finish_phase_receipt(
        self,
        *,
        command_id: str,
        command_type: str,
        fingerprint: str,
        project: dict[str, Any],
        project_binding: dict[str, Any],
        project_id: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        op_exec = self._operation_execution_id(
            project_id=project_id, chat_id=None, command_id=command_id
        )
        receipt, receipt_binding = self._persist_operation_receipt(
            command_id=command_id,
            command_type=command_type,
            input_fingerprint=fingerprint,
            operation_execution_id=op_exec,
            project_id=project_id,
            project_revision=project["project_revision"],
            chat_id=None,
            chat_revision=None,
            produced_artifacts=[project_binding],
            extra=extra,
        )
        response = {
            "project": project,
            "project_binding": project_binding,
            "retirement_id": extra.get("retirement_id"),
            "operation": receipt,
            "operation_binding": receipt_binding,
        }
        self._persist_command_record(
            command_id=command_id,
            command_type=command_type,
            input_fingerprint=fingerprint,
            operation_execution_id=op_exec,
            response=response,
        )
        return response
