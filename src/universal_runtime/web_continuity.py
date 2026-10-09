from __future__ import annotations

import codecs
import hashlib
import io
import json
import re
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from universal_runtime.core.artifact_store import ArtifactCurrentnessError, ArtifactStore
from universal_runtime.core.enums import PersistenceClass
from universal_runtime.packs.registry import PackRegistry, PackResolutionError
from universal_runtime.web_conversation_graph import (
    WebConversationGraphError,
    active_ancestry_projection,
    build_active_context_snapshot,
    leaf_event_ids,
    resolve_active_ancestry_ids,
    validate_event_index,
    validate_leaf_head_target,
)

from universal_runtime.core.formal_model_job import (
    FormalModelJobError,
    FormalModelJobLedger,
    legacy_artifact_identity_sha256,
)

BASE_RUNTIME_TREE_SHA256 = "e7984b10db037da0ec5c74077edf2fd50648b5dc37201d7819af5f4683213b66"
WEB_CONTRACT_SHA256 = "adfebd54c2de2847d52485b3e887fcb4797debbb1b19cc2ec74103ef7a563964"
DECODER_ID = "UR_WEB_M001_TEXT_DECODER"
DECODER_REVISION = "R001"
MAX_TEXT_SOURCE_BYTES = 1024 * 1024
PROJECT_HISTORY_CONTEXT_SCHEMA = "RUNTIME_NON_AUTHORITY_PROJECT_HISTORY_CONTEXT_V1"
PROJECT_HISTORY_CONTEXT_AUTHORITY_CLASS = "NON_AUTHORITY_PROJECT_HISTORY"
PROJECT_HISTORY_CONTEXT_SOURCE_CLASS = "RUNTIME_PROJECT_CHAT_HISTORY"
PROJECT_HISTORY_CONTEXT_CURRENTNESS_CLASS = "REQUEST_SNAPSHOT_ONLY"
PROJECT_HISTORY_CONTEXT_PERSISTENCE_CLASS = "JOB_BOUND_WORKING_INPUT"
PROJECT_HISTORY_CONTEXT_MAX_BYTES = 64 * 1024
PROJECT_CONTEXT_POLICY_PROJECT_ONLY = "PROJECT_ONLY"
PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY = "PROJECT_PLUS_GLOBAL_USER_MEMORY"
PROJECT_CONTEXT_POLICY_DEFAULT = PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY
PROJECT_CONTEXT_POLICIES = frozenset(
    {
        PROJECT_CONTEXT_POLICY_PROJECT_ONLY,
        PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY,
    }
)
MACHINE_LOCAL_WORK_REGISTRY_SCHEMA = "UR_RUNTIME_MACHINE_LOCAL_PROJECT_WORK_BINDINGS_R001"
_COMMAND_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_SAFE_LABEL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,200}$")


class WebContinuityError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_json_text(value: Any) -> str:
    return _canonical_json_bytes(value).decode("utf-8")


def _stable_id(prefix: str, *parts: str, length: int = 24) -> str:
    body = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(body).hexdigest()[:length].upper()}"


def _artifact_suffix(stable_id: str) -> str:
    return stable_id.replace("-", "_").upper()


def _validate_command_id(command_id: str) -> str:
    if not isinstance(command_id, str) or _COMMAND_RE.fullmatch(command_id) is None:
        raise WebContinuityError(
            "INVALID_COMMAND_ID",
            "command_id must be 1-160 characters from A-Z/a-z/0-9/._:-",
        )
    return command_id


def _validate_label(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise WebContinuityError("INVALID_INPUT", f"{field} must be text")
    trimmed = value.strip()
    if _SAFE_LABEL_RE.fullmatch(trimmed) is None:
        raise WebContinuityError("INVALID_INPUT", f"{field} is empty, too long, or contains control characters")
    return trimmed


def _validate_filename(filename: str) -> str:
    filename = _validate_label(filename, "filename")
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise WebContinuityError("INVALID_FILENAME", "filename must be a base name, not a path")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md"}:
        raise WebContinuityError("UNSUPPORTED_TEXT_FORMAT", "M001-A accepts only .txt and .md")
    return filename


def _validate_document_filename(filename: str, input_format: str) -> str:
    filename = _validate_label(filename, "filename")
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise WebContinuityError("INVALID_FILENAME", "filename must be a base name, not a path")
    suffix = Path(filename).suffix.lower()
    expected = ".pdf" if input_format == "pdf" else ".docx" if input_format == "docx" else None
    if expected is None or suffix != expected:
        raise WebContinuityError("DOCUMENT_FILENAME_FORMAT_MISMATCH", "document filename does not match bundle input format")
    return filename


class WebContinuityService:
    """Runtime-owned Web continuity command/projection surface.

    M001 project/chat/source operations remain non-formal Runtime operations. The formal-model
    extension below consumes FormalModelJobLedger only for detached Web intake binding and
    stale-safe result projection; it does not own JobAuthority, HumanDecision, ModelPolicy,
    provider transport, secrets, or formal result commit. RuntimeOperationReceipt remains
    non-formal.
    """

    def __init__(
        self,
        artifact_store: ArtifactStore,
        *,
        base_runtime_tree_sha256: str = BASE_RUNTIME_TREE_SHA256,
        web_contract_sha256: str = WEB_CONTRACT_SHA256,
        pack_registry: PackRegistry | None = None,
        machine_local_state_root: Path | None = None,
    ):
        self.store = artifact_store
        self.base_runtime_tree_sha256 = base_runtime_tree_sha256
        self.web_contract_sha256 = web_contract_sha256
        self.pack_registry = pack_registry
        default_machine_local_root = self.store.root.parent / ".universal_runtime_machine_local"
        self.machine_local_state_root = (
            machine_local_state_root if machine_local_state_root is not None else default_machine_local_root
        ).expanduser().resolve()
        self.machine_local_state_root.mkdir(parents=True, exist_ok=True)
        self._project_local_work_registry_path = (
            self.machine_local_state_root / "project_local_work_bindings.json"
        )
        self._lock = threading.RLock()

    # ---------- exact record helpers ----------

    def _record_exists(self, artifact_id: str) -> bool:
        return self.store.manifest_path(artifact_id, 1).parent.is_dir()

    def _load_current_json(self, artifact_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self._record_exists(artifact_id):
            raise WebContinuityError("NOT_FOUND", f"{artifact_id} not found", status_code=404)
        try:
            manifest = self.store.current_manifest(artifact_id)
        except ArtifactCurrentnessError as exc:
            raise WebContinuityError(
                "STALE_OR_TAMPERED",
                f"{artifact_id} failed currentness validation",
                status_code=409,
            ) from exc
        raw = Path(manifest.path).read_bytes()
        if _sha256_bytes(raw) != manifest.sha256:
            raise WebContinuityError("STALE_OR_TAMPERED", f"{artifact_id} current bytes do not match manifest", status_code=409)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise WebContinuityError("CORRUPT_RUNTIME_RECORD", f"{artifact_id} is not valid canonical JSON", status_code=500) from exc
        if not isinstance(value, dict):
            raise WebContinuityError("CORRUPT_RUNTIME_RECORD", f"{artifact_id} must contain a JSON object", status_code=500)
        return value, self._manifest_binding(manifest)

    @staticmethod
    def _manifest_binding(manifest: Any) -> dict[str, Any]:
        return {
            "artifact_id": manifest.artifact_id,
            "revision": manifest.revision,
            "sha256": manifest.sha256,
        }

    def _persist_json_revision(
        self,
        *,
        artifact_id: str,
        namespace: str,
        record: dict[str, Any],
        revision_field: str | None,
        operation_execution_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        next_revision = self.store.next_revision(artifact_id)
        payload = dict(record)
        if revision_field is not None:
            payload[revision_field] = next_revision
        relative_path = f"web_m001/{namespace}/{artifact_id}/R{next_revision:03d}.json"
        manifest = self.store.persist_exact_text(
            artifact_id=artifact_id,
            relative_path=relative_path,
            text=_canonical_json_text(payload),
            job_id=operation_execution_id,
            persistence_class=PersistenceClass.WORKING,
            input_fingerprint=payload.get("input_fingerprint_sha256"),
            metadata={
                "web_m001": True,
                "formal_job": False,
                "operation_execution_id": operation_execution_id,
            },
        )
        if manifest.revision != next_revision:
            raise WebContinuityError("REVISION_RACE", "Artifact revision changed during M001-A persist", status_code=409)
        return payload, self._manifest_binding(manifest)

    def _persist_text_revision(
        self,
        *,
        artifact_id: str,
        namespace: str,
        text: str,
        operation_execution_id: str,
    ) -> dict[str, Any]:
        next_revision = self.store.next_revision(artifact_id)
        relative_path = f"web_m001/{namespace}/{artifact_id}/R{next_revision:03d}.txt"
        manifest = self.store.persist_exact_text(
            artifact_id=artifact_id,
            relative_path=relative_path,
            text=text,
            job_id=operation_execution_id,
            persistence_class=PersistenceClass.WORKING,
            metadata={
                "web_m001": True,
                "formal_job": False,
                "operation_execution_id": operation_execution_id,
            },
        )
        if manifest.revision != next_revision:
            raise WebContinuityError("REVISION_RACE", "Text revision changed during M001-A persist", status_code=409)
        return self._manifest_binding(manifest)

    def _persist_text_if_changed(
        self,
        *,
        artifact_id: str,
        namespace: str,
        text: str,
        operation_execution_id: str,
    ) -> tuple[dict[str, Any], bool]:
        if self._record_exists(artifact_id):
            current = self.store.current_manifest(artifact_id)
            raw = Path(current.path).read_bytes()
            if _sha256_bytes(raw) != current.sha256:
                raise WebContinuityError("STALE_OR_TAMPERED", f"{artifact_id} text bytes mismatch", status_code=409)
            if raw == text.encode("utf-8"):
                return self._manifest_binding(current), False
        return (
            self._persist_text_revision(
                artifact_id=artifact_id,
                namespace=namespace,
                text=text,
                operation_execution_id=operation_execution_id,
            ),
            True,
        )

    def _load_exact_text_binding(self, binding: dict[str, Any]) -> str:
        try:
            manifest = self.store.assert_current(
                binding["artifact_id"],
                int(binding["revision"]),
                binding["sha256"],
            )
        except (KeyError, TypeError, ValueError, ArtifactCurrentnessError) as exc:
            raise WebContinuityError("STALE_BINDING", "Exact text binding is stale or invalid", status_code=409) from exc
        raw = Path(manifest.path).read_bytes()
        if _sha256_bytes(raw) != binding["sha256"]:
            raise WebContinuityError("STALE_BINDING", "Exact text binding bytes mismatch", status_code=409)
        try:
            return raw.decode("utf-8")
        except UnicodeError as exc:
            raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "Runtime canonical text is not UTF-8", status_code=500) from exc

    def read_project_instructions_current(self, *, project_id: str) -> dict[str, Any]:
        """Read only the exact-current canonical Project Instructions binding and bytes."""
        with self._lock:
            project, project_binding = self._project(project_id)
            instruction_binding = project.get("project_instruction_binding")
            if not isinstance(instruction_binding, dict):
                raise WebContinuityError(
                    "CORRUPT_RUNTIME_RECORD",
                    "Project Instructions binding is missing",
                    status_code=500,
                )
            instructions = self._load_exact_text_binding(instruction_binding)
            if _sha256_bytes(instructions.encode("utf-8")) != instruction_binding.get("sha256"):
                raise WebContinuityError(
                    "STALE_BINDING",
                    "Project Instructions bytes differ from exact binding",
                    status_code=409,
                )
            return {
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "project_binding": dict(project_binding),
                "project_instruction_binding": dict(instruction_binding),
                "project_instructions": instructions,
            }

    def resolve_project_instructions_by_creation_identity(
        self,
        *,
        command_id: str,
        display_name: str,
    ) -> dict[str, Any] | None:
        """Resolve an existing Project without creating it or mutating Runtime state."""
        command_id = _validate_command_id(command_id)
        display_name = _validate_label(display_name, "display_name")
        project_id = _stable_id("PRJ", command_id, display_name)
        with self._lock:
            if not self._record_exists(self._project_artifact_id(project_id)):
                return None
            project, _ = self._project(project_id)
            if (
                project.get("created_by_command_id") != command_id
                or project.get("display_name") != display_name
            ):
                raise WebContinuityError(
                    "PROJECT_IDENTITY_CONFLICT",
                    "derived Project identity exists with different creation provenance",
                    status_code=409,
                )
            return self.read_project_instructions_current(project_id=project_id)

    def _operation_execution_id(self, *, project_id: str, chat_id: str | None, command_id: str) -> str:
        raw = f"UR_WEB_M001_A_V1|{project_id}|{chat_id or '-'}|{command_id}".encode("utf-8")
        return "WEBOP_" + _sha256_bytes(raw)

    def _command_artifact_id(self, command_id: str) -> str:
        return "WEB_COMMAND_" + _sha256_bytes(command_id.encode("utf-8")).upper()

    def _operation_namespace_prefix(self, project_id: str) -> str:
        return "WEB_OPERATION_" + _artifact_suffix(project_id) + "_"

    def _operation_artifact_id(self, project_id: str, command_id: str, command_type: str) -> str:
        return self._operation_namespace_prefix(project_id) + _sha256_bytes(
            f"{command_type}|{command_id}".encode("utf-8")
        ).upper()

    def _command_fingerprint(
        self,
        *,
        command_id: str,
        command_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        return _sha256_bytes(
            _canonical_json_bytes(
                {
                    "command_id": command_id,
                    "command_type": command_type,
                    "scope": scope,
                    "payload": payload,
                    "contract_sha256": self.web_contract_sha256,
                }
            )
        )

    def _load_idempotent_response(self, command_id: str, input_fingerprint: str) -> dict[str, Any] | None:
        artifact_id = self._command_artifact_id(command_id)
        if not self._record_exists(artifact_id):
            return None
        record, _ = self._load_current_json(artifact_id)
        if record.get("input_fingerprint_sha256") != input_fingerprint:
            raise WebContinuityError(
                "IDEMPOTENCY_CONFLICT",
                "command_id was already used with different scope/input",
                status_code=409,
            )
        response = record.get("response")
        if not isinstance(response, dict):
            raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "Command record has no response", status_code=500)
        return response

    def _persist_command_record(
        self,
        *,
        command_id: str,
        command_type: str,
        input_fingerprint: str,
        operation_execution_id: str,
        response: dict[str, Any],
    ) -> None:
        artifact_id = self._command_artifact_id(command_id)
        if self._record_exists(artifact_id):
            existing, _ = self._load_current_json(artifact_id)
            if existing.get("input_fingerprint_sha256") != input_fingerprint:
                raise WebContinuityError("IDEMPOTENCY_CONFLICT", "existing command record conflicts", status_code=409)
            return
        self._persist_json_revision(
            artifact_id=artifact_id,
            namespace="commands",
            record={
                "command_id": command_id,
                "command_type": command_type,
                "input_fingerprint_sha256": input_fingerprint,
                "operation_execution_id": operation_execution_id,
                "formal_job": False,
                "response": response,
                "created_at_utc": _utc_now(),
            },
            revision_field=None,
            operation_execution_id=operation_execution_id,
        )

    def _persist_operation_receipt(
        self,
        *,
        command_id: str,
        command_type: str,
        input_fingerprint: str,
        operation_execution_id: str,
        project_id: str,
        project_revision: int,
        chat_id: str | None,
        chat_revision: int | None,
        source_ref_id: str | None = None,
        source_sha256: str | None = None,
        derivation_sha256: str | None = None,
        produced_artifacts: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation_id = _stable_id("OPR", command_type, command_id, project_id, chat_id or "-")
        artifact_id = self._operation_artifact_id(project_id, command_id, command_type)
        record = {
            "operation_id": operation_id,
            "operation_execution_id": operation_execution_id,
            "command_id": command_id,
            "operation_type": command_type,
            "formal_job": False,
            "runtime_binding": {
                "base_runtime_tree_sha256": self.base_runtime_tree_sha256,
                "web_contract_sha256": self.web_contract_sha256,
                "binding_class": "SOURCE_BOUND_CANDIDATE_BASE",
            },
            "project_id": project_id,
            "project_revision": project_revision,
            "chat_id": chat_id,
            "chat_revision": chat_revision,
            "source_ref_id": source_ref_id,
            "source_artifact_sha256": source_sha256,
            "text_derivation_sha256": derivation_sha256,
            "input_fingerprint_sha256": input_fingerprint,
            "result": "PASS",
            "network_used": False,
            "model_used": False,
            "workspace_grant_used": False,
            "shell_used": False,
            "produced_artifact_bindings": produced_artifacts or [],
            "created_at_utc": _utc_now(),
        }
        if extra:
            record["details"] = extra

        if self._record_exists(artifact_id):
            existing, binding = self._load_current_json(artifact_id)
            if existing.get("input_fingerprint_sha256") != input_fingerprint:
                raise WebContinuityError("IDEMPOTENCY_CONFLICT", "operation receipt conflicts", status_code=409)
            return existing, binding

        return self._persist_json_revision(
            artifact_id=artifact_id,
            namespace="operations",
            record=record,
            revision_field=None,
            operation_execution_id=operation_execution_id,
        )

    # ---------- project / chat ----------

    def _project_artifact_id(self, project_id: str) -> str:
        return "WEB_PROJECT_" + _artifact_suffix(project_id)

    def _chat_artifact_id(self, chat_id: str) -> str:
        return "WEB_CHAT_" + _artifact_suffix(chat_id)

    def _event_artifact_id(self, event_id: str) -> str:
        return "WEB_EVENT_" + _artifact_suffix(event_id)

    def _source_ref_artifact_id(self, source_ref_id: str) -> str:
        return "WEB_SOURCE_REF_" + _artifact_suffix(source_ref_id)

    def _source_lifecycle_artifact_id(self, source_ref_id: str) -> str:
        return "WEB_SOURCE_LIFECYCLE_" + _artifact_suffix(source_ref_id)

    def _instructions_artifact_id(self, project_id: str) -> str:
        return "WEB_PROJECT_INSTRUCTIONS_" + _artifact_suffix(project_id)

    def _project(self, project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        return self._load_current_json(self._project_artifact_id(project_id))

    def _chat(
        self,
        chat_id: str,
        *,
        include_deleted: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        chat, binding = self._load_current_json(self._chat_artifact_id(chat_id))
        if chat.get("lifecycle_state", "ACTIVE") == "DELETED" and not include_deleted:
            raise WebContinuityError(
                "CHAT_DELETED",
                "chat is deleted from the active product surface",
                status_code=410,
            )
        return chat, binding

    def _source_lifecycle(self, source_ref_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        artifact_id = self._source_lifecycle_artifact_id(source_ref_id)
        if not self._record_exists(artifact_id):
            return {
                "source_ref_id": source_ref_id,
                "lifecycle_state": "ACTIVE",
                "lifecycle_revision": 0,
                "delete_semantics": None,
                "privacy_erasure": False,
            }, None
        return self._load_current_json(artifact_id)

    def _source_ref(
        self,
        source_ref_id: str,
        *,
        include_deleted: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        source_ref, binding = self._load_current_json(self._source_ref_artifact_id(source_ref_id))
        lifecycle, _ = self._source_lifecycle(source_ref_id)
        if lifecycle.get("lifecycle_state") == "DELETED" and not include_deleted:
            raise WebContinuityError(
                "SOURCE_DELETED",
                "SourceRef is deleted from active Project/library use",
                status_code=410,
            )
        return source_ref, binding

    def _update_catalog(self, project_id: str, operation_execution_id: str) -> dict[str, Any]:
        artifact_id = "WEB_PROJECT_CATALOG"
        if self._record_exists(artifact_id):
            catalog, binding = self._load_current_json(artifact_id)
            if project_id in catalog.get("project_ids", []):
                return {"catalog": catalog, "binding": binding}
        else:
            catalog = {"project_ids": [], "created_at_utc": _utc_now()}
        project_ids = sorted(set(catalog.get("project_ids", [])) | {project_id})
        updated, binding = self._persist_json_revision(
            artifact_id=artifact_id,
            namespace="catalog",
            record={
                "project_ids": project_ids,
                "updated_at_utc": _utc_now(),
                "authority_class": "RUNTIME_PROJECT_CATALOG",
            },
            revision_field="catalog_revision",
            operation_execution_id=operation_execution_id,
        )
        return {"catalog": updated, "binding": binding}


    def _require_pack_registry(self) -> PackRegistry:
        if self.pack_registry is None:
            raise WebContinuityError(
                "PROJECT_PACK_REGISTRY_UNAVAILABLE",
                "Project Pack binding requires the Runtime promoted Pack registry",
                status_code=503,
            )
        return self.pack_registry

    @staticmethod
    def _project_pack_binding_from_resolved(pack: Any) -> dict[str, str]:
        content_sha = getattr(pack, "content_manifest_sha256", None)
        receipt_sha = getattr(pack, "promotion_receipt_sha256", None)
        if not isinstance(content_sha, str) or not isinstance(receipt_sha, str):
            raise WebContinuityError(
                "PROJECT_PACK_PROMOTION_IDENTITY_INCOMPLETE",
                "Project Pack binding requires a promotion-aware exact Pack identity",
                status_code=409,
            )
        return {
            "pack_id": pack.pack_id,
            "pack_version": pack.version,
            "pack_manifest_sha256": pack.manifest_sha256,
            "pack_content_manifest_sha256": content_sha,
            "pack_promotion_receipt_sha256": receipt_sha,
        }

    def _resolve_project_pack_binding(self, pack_id: str, pack_version: str) -> dict[str, str]:
        pack_id = _validate_label(pack_id, "pack_id")
        pack_version = _validate_label(pack_version, "pack_version")
        try:
            resolved = self._require_pack_registry().resolve_promoted_pack(pack_id, pack_version)
        except PackResolutionError as exc:
            raise WebContinuityError(
                "PROJECT_PACK_NOT_PROMOTED_OR_STALE",
                str(exc),
                status_code=409,
            ) from exc
        return self._project_pack_binding_from_resolved(resolved)

    def _validate_current_project_pack_binding(self, project: dict[str, Any]) -> dict[str, str] | None:
        binding = project.get("project_pack_binding")
        if binding is None:
            return None
        required = {
            "pack_id",
            "pack_version",
            "pack_manifest_sha256",
            "pack_content_manifest_sha256",
            "pack_promotion_receipt_sha256",
        }
        if not isinstance(binding, dict) or set(binding) != required or not all(
            isinstance(binding.get(field), str) and binding.get(field) for field in required
        ):
            raise WebContinuityError(
                "PROJECT_PACK_BINDING_CORRUPT",
                "Project Pack binding is not one exact promoted-Pack identity tuple",
                status_code=409,
            )
        current = self._resolve_project_pack_binding(binding["pack_id"], binding["pack_version"])
        if current != binding:
            raise WebContinuityError(
                "PROJECT_PACK_BINDING_STALE",
                "Project Pack binding no longer matches the exact promoted Pack identity",
                status_code=409,
            )
        return dict(binding)

    def get_project_pack_binding(self, *, project_id: str) -> dict[str, Any]:
        with self._lock:
            project, _ = self._project(project_id)
            binding = self._validate_current_project_pack_binding(project)
            return {
                "schema": "UR_RUNTIME_PROJECT_PACK_BINDING_R001",
                "authority_class": "RUNTIME_PROJECT_AUTHORITY_PROJECTION",
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "binding": binding,
            }

    def bind_project_pack(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        pack_id: str,
        pack_version: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        target_binding = self._resolve_project_pack_binding(pack_id, pack_version)
        payload = {
            "expected_project_revision": expected_project_revision,
            "project_pack_binding": target_binding,
        }
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_PACK_BIND",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            current_binding = self._validate_current_project_pack_binding(project)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=None, command_id=command_id)
            if current_binding == target_binding:
                updated = project
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                action = "NO_OP_ALREADY_BOUND"
                changed = False
            else:
                next_record = dict(project)
                next_record["project_pack_binding"] = target_binding
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "BIND" if current_binding is None else "REBIND"
                changed = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_PACK_BIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding],
                extra={
                    "project_pack_binding_action": action,
                    "project_pack_binding": target_binding,
                    "project_pack_binding_changed": changed,
                    "pack_execution": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "project_pack_binding": target_binding,
                "project_pack_binding_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_PACK_BIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def unbind_project_pack(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        payload = {"expected_project_revision": expected_project_revision}
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_PACK_UNBIND",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            current_binding = self._validate_current_project_pack_binding(project)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=None, command_id=command_id)
            if current_binding is None:
                updated = project
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                action = "NO_OP_ALREADY_UNBOUND"
                changed = False
            else:
                next_record = dict(project)
                next_record.pop("project_pack_binding", None)
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "UNBIND"
                changed = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_PACK_UNBIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding],
                extra={
                    "project_pack_binding_action": action,
                    "previous_project_pack_binding": current_binding,
                    "project_pack_binding_changed": changed,
                    "pack_execution": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "project_pack_binding": None,
                "project_pack_binding_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_PACK_UNBIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    @staticmethod
    def _project_local_work_binding(
        executor: str,
        local_project_root: str,
    ) -> dict[str, str]:
        executor = _validate_label(executor, "executor")
        if executor != "webcodex-local":
            raise WebContinuityError(
                "PROJECT_LOCAL_WORK_EXECUTOR_UNSUPPORTED",
                "Project local work binding currently supports only webcodex-local",
                status_code=409,
            )
        if not isinstance(local_project_root, str) or not local_project_root.strip():
            raise WebContinuityError(
                "INVALID_INPUT",
                "local_project_root must be a non-empty absolute path",
            )
        root = Path(local_project_root).expanduser()
        if not root.is_absolute():
            raise WebContinuityError("INVALID_INPUT", "local_project_root must be absolute")
        return {
            "executor": executor,
            "binding_class": "MACHINE_LOCAL_PROJECT_ROOT",
            "local_project_root": str(root.resolve()),
        }

    @classmethod
    def _legacy_project_local_work_binding(
        cls,
        project: dict[str, Any],
    ) -> dict[str, str] | None:
        binding = project.get("local_work_binding")
        if binding is None:
            return None
        required = {"executor", "binding_class", "local_project_root"}
        if not isinstance(binding, dict) or set(binding) != required:
            raise WebContinuityError(
                "PROJECT_LOCAL_WORK_BINDING_CORRUPT",
                "legacy Project local work binding is not one exact executor/root tuple",
                status_code=409,
            )
        validated = cls._project_local_work_binding(
            binding.get("executor"),
            binding.get("local_project_root"),
        )
        if binding.get("binding_class") != "MACHINE_LOCAL_PROJECT_ROOT":
            raise WebContinuityError(
                "PROJECT_LOCAL_WORK_BINDING_CORRUPT",
                "legacy Project local work binding class is invalid",
                status_code=409,
            )
        return validated

    def _load_machine_local_work_registry(self) -> dict[str, Any]:
        path = self._project_local_work_registry_path
        if not path.exists():
            return {"schema": MACHINE_LOCAL_WORK_REGISTRY_SCHEMA, "bindings": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WebContinuityError(
                "MACHINE_LOCAL_WORK_REGISTRY_CORRUPT",
                "machine-local Project work registry is unreadable",
                status_code=500,
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != MACHINE_LOCAL_WORK_REGISTRY_SCHEMA
            or not isinstance(value.get("bindings"), dict)
        ):
            raise WebContinuityError(
                "MACHINE_LOCAL_WORK_REGISTRY_CORRUPT",
                "machine-local Project work registry shape is invalid",
                status_code=500,
            )
        normalized: dict[str, dict[str, str]] = {}
        for project_id, binding in value["bindings"].items():
            if not isinstance(project_id, str) or not isinstance(binding, dict):
                raise WebContinuityError(
                    "MACHINE_LOCAL_WORK_REGISTRY_CORRUPT",
                    "machine-local Project work registry entry is invalid",
                    status_code=500,
                )
            validated = self._project_local_work_binding(
                binding.get("executor"),
                binding.get("local_project_root"),
            )
            if binding.get("binding_class") != "MACHINE_LOCAL_PROJECT_ROOT":
                raise WebContinuityError(
                    "MACHINE_LOCAL_WORK_REGISTRY_CORRUPT",
                    "machine-local Project work registry binding class is invalid",
                    status_code=500,
                )
            normalized[project_id] = validated
        return {"schema": MACHINE_LOCAL_WORK_REGISTRY_SCHEMA, "bindings": normalized}

    def _write_machine_local_work_registry(self, registry: dict[str, Any]) -> None:
        path = self._project_local_work_registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(_canonical_json_text(registry), encoding="utf-8")
        tmp.replace(path)

    def _machine_local_project_work_binding(self, project_id: str) -> dict[str, str] | None:
        registry = self._load_machine_local_work_registry()
        binding = registry["bindings"].get(project_id)
        return dict(binding) if isinstance(binding, dict) else None

    def _set_machine_local_project_work_binding(
        self,
        project_id: str,
        binding: dict[str, str],
    ) -> None:
        registry = self._load_machine_local_work_registry()
        registry["bindings"][project_id] = dict(binding)
        self._write_machine_local_work_registry(registry)

    def _remove_machine_local_project_work_binding(self, project_id: str) -> bool:
        registry = self._load_machine_local_work_registry()
        if project_id not in registry["bindings"]:
            return False
        registry["bindings"].pop(project_id, None)
        self._write_machine_local_work_registry(registry)
        return True

    @staticmethod
    def _sanitize_machine_local_binding_value(value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"local_work_binding", "previous_local_work_binding"}:
                    result[key] = None
                else:
                    result[key] = WebContinuityService._sanitize_machine_local_binding_value(item)
            return result
        if isinstance(value, list):
            return [WebContinuityService._sanitize_machine_local_binding_value(item) for item in value]
        return value

    def _portable_local_work_command_response(self, response: dict[str, Any]) -> dict[str, Any]:
        sanitized = self._sanitize_machine_local_binding_value(response)
        if not isinstance(sanitized, dict):
            raise WebContinuityError(
                "CORRUPT_RUNTIME_RECORD",
                "sanitized local work response is invalid",
                status_code=500,
            )
        return sanitized

    def _load_local_work_idempotent_response(
        self,
        command_id: str,
        input_fingerprint: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        replay = self._load_idempotent_response(command_id, input_fingerprint)
        if replay is None:
            return None
        replay = dict(replay)
        project = replay.get("project")
        if isinstance(project, dict):
            project = dict(project)
            project.pop("local_work_binding", None)
            replay["project"] = project
        replay["local_work_binding"] = self._machine_local_project_work_binding(project_id)
        return replay

    def _persist_local_work_command_record(
        self,
        *,
        command_id: str,
        command_type: str,
        input_fingerprint: str,
        operation_execution_id: str,
        response: dict[str, Any],
    ) -> None:
        self._persist_command_record(
            command_id=command_id,
            command_type=command_type,
            input_fingerprint=input_fingerprint,
            operation_execution_id=operation_execution_id,
            response=self._portable_local_work_command_response(response),
        )

    def _sanitize_current_project_local_work_records(
        self,
        *,
        project_id: str,
        operation_execution_id: str,
    ) -> dict[str, int]:
        counts = {"commands": 0, "operations": 0}
        for namespace in ("commands", "operations"):
            base = self.store.root / "web_m001" / namespace
            if not base.is_dir():
                continue
            for artifact_dir in sorted(base.iterdir()):
                if not artifact_dir.is_dir():
                    continue
                artifact_id = artifact_dir.name
                if not self._record_exists(artifact_id):
                    continue
                record, _ = self._load_current_json(artifact_id)
                relevant = False
                if namespace == "commands":
                    response = record.get("response")
                    response_project = response.get("project") if isinstance(response, dict) else None
                    relevant = (
                        isinstance(response_project, dict)
                        and response_project.get("project_id") == project_id
                    ) or record.get("command_type") in {
                        "PROJECT_LOCAL_WORK_BIND",
                        "PROJECT_LOCAL_WORK_UNBIND",
                    }
                else:
                    relevant = record.get("project_id") == project_id
                if not relevant:
                    continue
                sanitized = self._sanitize_machine_local_binding_value(record)
                if sanitized == record:
                    continue
                self._persist_json_revision(
                    artifact_id=artifact_id,
                    namespace=namespace,
                    record=sanitized,
                    revision_field=None,
                    operation_execution_id=operation_execution_id,
                )
                counts[namespace] += 1
        return counts

    def get_project_local_work_binding(self, *, project_id: str) -> dict[str, Any]:
        with self._lock:
            project, _ = self._project(project_id)
            binding = self._machine_local_project_work_binding(project_id)
            if binding is None:
                binding = self._legacy_project_local_work_binding(project)
            return {
                "schema": "UR_RUNTIME_PROJECT_LOCAL_WORK_BINDING_R001",
                "authority_class": "RUNTIME_PROJECT_AUTHORITY_PROJECTION",
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "binding": binding,
            }

    def bind_project_local_work(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        executor: str,
        local_project_root: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        target_binding = self._project_local_work_binding(executor, local_project_root)
        payload = {
            "expected_project_revision": expected_project_revision,
            "local_work_binding": target_binding,
        }
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_LOCAL_WORK_BIND",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_local_work_idempotent_response(
                command_id,
                fingerprint,
                project_id,
            )
            if replay is not None:
                return replay
            project, project_binding = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            legacy_binding = self._legacy_project_local_work_binding(project)
            current_binding = self._machine_local_project_work_binding(project_id) or legacy_binding
            op_exec = self._operation_execution_id(
                project_id=project_id,
                chat_id=None,
                command_id=command_id,
            )
            updated = project
            updated_binding = project_binding
            if legacy_binding is not None:
                self._set_machine_local_project_work_binding(project_id, target_binding)
                next_record = dict(project)
                next_record.pop("local_work_binding", None)
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "MIGRATE_LEGACY_AND_BIND"
                changed = True
            elif current_binding == target_binding:
                action = "NO_OP_ALREADY_BOUND"
                changed = False
            else:
                self._set_machine_local_project_work_binding(project_id, target_binding)
                action = "BIND_MACHINE_LOCAL" if current_binding is None else "REBIND_MACHINE_LOCAL"
                changed = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_LOCAL_WORK_BIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding] if legacy_binding is not None else [],
                extra={
                    "local_work_binding_action": action,
                    "machine_local_binding_changed": changed,
                    "machine_local_binding_redacted": True,
                    "executor_invoked": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "local_work_binding": target_binding,
                "local_work_binding_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_local_work_command_record(
                command_id=command_id,
                command_type="PROJECT_LOCAL_WORK_BIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def unbind_project_local_work(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        payload = {"expected_project_revision": expected_project_revision}
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_LOCAL_WORK_UNBIND",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_local_work_idempotent_response(
                command_id,
                fingerprint,
                project_id,
            )
            if replay is not None:
                replay["local_work_binding"] = None
                return replay
            project, project_binding = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            legacy_binding = self._legacy_project_local_work_binding(project)
            current_binding = self._machine_local_project_work_binding(project_id) or legacy_binding
            op_exec = self._operation_execution_id(
                project_id=project_id,
                chat_id=None,
                command_id=command_id,
            )
            updated = project
            updated_binding = project_binding
            if legacy_binding is not None:
                self._remove_machine_local_project_work_binding(project_id)
                next_record = dict(project)
                next_record.pop("local_work_binding", None)
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "MIGRATE_LEGACY_AND_UNBIND"
                changed = True
            elif current_binding is None:
                action = "NO_OP_ALREADY_UNBOUND"
                changed = False
            else:
                self._remove_machine_local_project_work_binding(project_id)
                action = "UNBIND_MACHINE_LOCAL"
                changed = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_LOCAL_WORK_UNBIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding] if legacy_binding is not None else [],
                extra={
                    "local_work_binding_action": action,
                    "machine_local_binding_changed": changed,
                    "machine_local_binding_redacted": True,
                    "executor_invoked": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "local_work_binding": None,
                "local_work_binding_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_local_work_command_record(
                command_id=command_id,
                command_type="PROJECT_LOCAL_WORK_UNBIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def migrate_legacy_project_local_work_binding(
        self,
        *,
        project_id: str,
        expected_project_revision: int,
        migration_id: str,
    ) -> dict[str, Any]:
        migration_id = _validate_command_id(migration_id)
        with self._lock:
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            legacy_binding = self._legacy_project_local_work_binding(project)
            if legacy_binding is None:
                return {
                    "project": project,
                    "binding": self._machine_local_project_work_binding(project_id),
                    "migrated": False,
                    "sanitized_current_records": {"commands": 0, "operations": 0},
                }
            op_exec = self._operation_execution_id(
                project_id=project_id,
                chat_id=None,
                command_id=migration_id,
            )
            self._set_machine_local_project_work_binding(project_id, legacy_binding)
            next_record = dict(project)
            next_record.pop("local_work_binding", None)
            next_record["updated_at_utc"] = _utc_now()
            next_record["last_command_id"] = migration_id
            next_record["last_input_fingerprint_sha256"] = _sha256_bytes(
                _canonical_json_bytes(
                    {
                        "migration": "PROJECT_LOCAL_WORK_MACHINE_RESOLVER_SEPARATION_R001",
                        "project_id": project_id,
                    }
                )
            )
            updated, updated_binding = self._persist_json_revision(
                artifact_id=self._project_artifact_id(project_id),
                namespace="projects",
                record=next_record,
                revision_field="project_revision",
                operation_execution_id=op_exec,
            )
            sanitized_counts = self._sanitize_current_project_local_work_records(
                project_id=project_id,
                operation_execution_id=op_exec,
            )
            return {
                "project": updated,
                "project_binding": updated_binding,
                "binding": dict(legacy_binding),
                "migrated": True,
                "sanitized_current_records": sanitized_counts,
            }

    @staticmethod
    def _validate_project_context_policy_value(context_policy: str) -> str:
        if not isinstance(context_policy, str) or context_policy not in PROJECT_CONTEXT_POLICIES:
            raise WebContinuityError(
                "PROJECT_CONTEXT_POLICY_INVALID",
                "context_policy must be PROJECT_ONLY or PROJECT_PLUS_GLOBAL_USER_MEMORY",
                status_code=400,
            )
        return context_policy
    @staticmethod
    def _validate_current_project_context_policy(
        project: dict[str, Any],
    ) -> tuple[str, bool]:
        explicit = "context_policy" in project
        context_policy = project.get("context_policy", PROJECT_CONTEXT_POLICY_DEFAULT)
        if not isinstance(context_policy, str) or context_policy not in PROJECT_CONTEXT_POLICIES:
            raise WebContinuityError(
                "PROJECT_CONTEXT_POLICY_CORRUPT",
                "Project context policy is missing a supported exact value",
                status_code=409,
            )
        return context_policy, explicit
    def get_project_context_policy(self, *, project_id: str) -> dict[str, Any]:
        with self._lock:
            project, _ = self._project(project_id)
            context_policy, explicit = self._validate_current_project_context_policy(project)
            return {
                "schema": "UR_RUNTIME_PROJECT_CONTEXT_POLICY_R001",
                "authority_class": "RUNTIME_PROJECT_AUTHORITY_PROJECTION",
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "context_policy": context_policy,
                "explicit": explicit,
            }
    def set_project_context_policy(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        context_policy: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        target_policy = self._validate_project_context_policy_value(context_policy)
        payload = {
            "expected_project_revision": expected_project_revision,
            "context_policy": target_policy,
        }
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_CONTEXT_POLICY_SET",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            current_policy, current_explicit = self._validate_current_project_context_policy(project)
            op_exec = self._operation_execution_id(
                project_id=project_id,
                chat_id=None,
                command_id=command_id,
            )
            if current_policy == target_policy:
                updated = project
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                action = "NO_OP_ALREADY_EFFECTIVE"
                changed = False
                explicit = current_explicit
            else:
                next_record = dict(project)
                next_record["context_policy"] = target_policy
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "SET"
                changed = True
                explicit = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_CONTEXT_POLICY_SET",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding],
                extra={
                    "context_policy_action": action,
                    "previous_context_policy": current_policy,
                    "context_policy": target_policy,
                    "context_policy_changed": changed,
                    "model_used": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "context_policy": target_policy,
                "context_policy_explicit": explicit,
                "context_policy_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_CONTEXT_POLICY_SET",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    @staticmethod
    def _project_assistant_profile_binding(
        assistant_profile_id: str,
        assistant_profile_revision: str,
    ) -> dict[str, str]:
        return {
            "assistant_profile_id": _validate_label(assistant_profile_id, "assistant_profile_id"),
            "assistant_profile_revision": _validate_label(
                assistant_profile_revision,
                "assistant_profile_revision",
            ),
        }

    @staticmethod
    def _validate_current_project_assistant_profile_binding(
        project: dict[str, Any],
    ) -> dict[str, str] | None:
        binding = project.get("assistant_profile_binding")
        if binding is None:
            return None
        required = {"assistant_profile_id", "assistant_profile_revision"}
        if not isinstance(binding, dict) or set(binding) != required or not all(
            isinstance(binding.get(field), str) and binding.get(field) for field in required
        ):
            raise WebContinuityError(
                "PROJECT_ASSISTANT_PROFILE_BINDING_CORRUPT",
                "Project assistant profile binding is not one exact logical profile tuple",
                status_code=409,
            )
        return dict(binding)

    def get_project_assistant_profile_binding(self, *, project_id: str) -> dict[str, Any]:
        with self._lock:
            project, _ = self._project(project_id)
            binding = self._validate_current_project_assistant_profile_binding(project)
            return {
                "schema": "UR_RUNTIME_PROJECT_ASSISTANT_PROFILE_BINDING_R001",
                "authority_class": "RUNTIME_PROJECT_AUTHORITY_PROJECTION",
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "binding": binding,
            }

    def bind_project_assistant_profile(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        assistant_profile_id: str,
        assistant_profile_revision: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        target_binding = self._project_assistant_profile_binding(
            assistant_profile_id,
            assistant_profile_revision,
        )
        payload = {
            "expected_project_revision": expected_project_revision,
            "assistant_profile_binding": target_binding,
        }
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_ASSISTANT_PROFILE_BIND",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            current_binding = self._validate_current_project_assistant_profile_binding(project)
            op_exec = self._operation_execution_id(
                project_id=project_id,
                chat_id=None,
                command_id=command_id,
            )
            if current_binding == target_binding:
                updated = project
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                action = "NO_OP_ALREADY_BOUND"
                changed = False
            else:
                next_record = dict(project)
                next_record["assistant_profile_binding"] = target_binding
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "BIND" if current_binding is None else "REBIND"
                changed = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_ASSISTANT_PROFILE_BIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding],
                extra={
                    "assistant_profile_binding_action": action,
                    "assistant_profile_binding": target_binding,
                    "assistant_profile_binding_changed": changed,
                    "model_used": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "assistant_profile_binding": target_binding,
                "assistant_profile_binding_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_ASSISTANT_PROFILE_BIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def unbind_project_assistant_profile(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        payload = {"expected_project_revision": expected_project_revision}
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_ASSISTANT_PROFILE_UNBIND",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            current_binding = self._validate_current_project_assistant_profile_binding(project)
            op_exec = self._operation_execution_id(
                project_id=project_id,
                chat_id=None,
                command_id=command_id,
            )
            if current_binding is None:
                updated = project
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )
                action = "NO_OP_ALREADY_UNBOUND"
                changed = False
            else:
                next_record = dict(project)
                next_record.pop("assistant_profile_binding", None)
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=next_record,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
                action = "UNBIND"
                changed = True
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_ASSISTANT_PROFILE_UNBIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding],
                extra={
                    "assistant_profile_binding_action": action,
                    "previous_assistant_profile_binding": current_binding,
                    "assistant_profile_binding_changed": changed,
                    "model_used": False,
                    "job_created": False,
                },
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "assistant_profile_binding": None,
                "assistant_profile_binding_changed": changed,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_ASSISTANT_PROFILE_UNBIND",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self._record_exists("WEB_PROJECT_CATALOG"):
                return []
            catalog, _ = self._load_current_json("WEB_PROJECT_CATALOG")
            result = []
            for project_id in catalog.get("project_ids", []):
                try:
                    project, _ = self._project(project_id)
                except WebContinuityError:
                    continue
                result.append(
                    {
                        "project_id": project["project_id"],
                        "project_revision": project["project_revision"],
                        "display_name": project["display_name"],
                        "status": project["status"],
                        "updated_at_utc": project["updated_at_utc"],
                    }
                )
            return result

    def create_project(self, *, command_id: str, display_name: str, instructions: str) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        display_name = _validate_label(display_name, "display_name")
        if not isinstance(instructions, str):
            raise WebContinuityError("INVALID_INPUT", "instructions must be text")
        project_id = _stable_id("PRJ", command_id, display_name)
        scope = {"project_id": project_id}
        payload = {"display_name": display_name, "instructions_sha256": _sha256_bytes(instructions.encode("utf-8"))}
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_CREATE",
            scope=scope,
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=None, command_id=command_id)
            project_artifact_id = self._project_artifact_id(project_id)
            if self._record_exists(project_artifact_id):
                project, project_binding = self._project(project_id)
                if project.get("created_by_command_id") != command_id or project.get("creation_fingerprint_sha256") != fingerprint:
                    raise WebContinuityError("IDEMPOTENCY_CONFLICT", "project identity already exists with different input", status_code=409)
            else:
                instruction_binding, _ = self._persist_text_if_changed(
                    artifact_id=self._instructions_artifact_id(project_id),
                    namespace="instructions",
                    text=instructions,
                    operation_execution_id=op_exec,
                )
                project, project_binding = self._persist_json_revision(
                    artifact_id=project_artifact_id,
                    namespace="projects",
                    record={
                        "project_id": project_id,
                        "display_name": display_name,
                        "status": "ACTIVE",
                        "project_instruction_binding": instruction_binding,
                        "chat_ids": [],
                        "source_ref_ids": [],
                        "created_by_command_id": command_id,
                        "creation_fingerprint_sha256": fingerprint,
                        "created_at_utc": _utc_now(),
                        "updated_at_utc": _utc_now(),
                        "last_command_id": command_id,
                        "last_input_fingerprint_sha256": fingerprint,
                    },
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
            self._update_catalog(project_id, op_exec)
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_CREATE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[project_binding, project["project_instruction_binding"]],
            )
            response = {
                "project": project,
                "project_binding": project_binding,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_CREATE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def revise_project_instructions(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        instructions: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        if not isinstance(instructions, str):
            raise WebContinuityError("INVALID_INPUT", "instructions must be text")
        payload = {
            "expected_project_revision": expected_project_revision,
            "instructions_sha256": _sha256_bytes(instructions.encode("utf-8")),
        }
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="PROJECT_INSTRUCTIONS_REVISE",
            scope={"project_id": project_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                if project.get("last_command_id") == command_id and project.get("last_input_fingerprint_sha256") == fingerprint:
                    pass
                else:
                    raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=None, command_id=command_id)
            if project.get("last_command_id") == command_id and project.get("last_input_fingerprint_sha256") == fingerprint:
                updated = project
                updated_binding = self._manifest_binding(self.store.current_manifest(self._project_artifact_id(project_id)))
            else:
                instruction_binding, instruction_changed = self._persist_text_if_changed(
                    artifact_id=self._instructions_artifact_id(project_id),
                    namespace="instructions",
                    text=instructions,
                    operation_execution_id=op_exec,
                )
                if not instruction_changed and project.get("project_instruction_binding") == instruction_binding:
                    updated = project
                    updated_binding = self._manifest_binding(
                        self.store.current_manifest(self._project_artifact_id(project_id))
                    )
                else:
                    next_record = dict(project)
                    next_record["project_instruction_binding"] = instruction_binding
                    next_record["updated_at_utc"] = _utc_now()
                    next_record["last_command_id"] = command_id
                    next_record["last_input_fingerprint_sha256"] = fingerprint
                    updated, updated_binding = self._persist_json_revision(
                        artifact_id=self._project_artifact_id(project_id),
                        namespace="projects",
                        record=next_record,
                        revision_field="project_revision",
                        operation_execution_id=op_exec,
                    )
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="PROJECT_INSTRUCTIONS_REVISE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=updated["project_revision"],
                chat_id=None,
                chat_revision=None,
                produced_artifacts=[updated_binding, updated["project_instruction_binding"]],
            )
            response = {
                "project": updated,
                "project_binding": updated_binding,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="PROJECT_INSTRUCTIONS_REVISE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def create_chat(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        title: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        title = _validate_label(title, "title")
        chat_id = _stable_id("CHT", project_id, command_id, title)
        payload = {"expected_project_revision": expected_project_revision, "title": title}
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_CREATE",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload=payload,
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                if not (project.get("last_command_id") == command_id and project.get("last_input_fingerprint_sha256") == fingerprint):
                    raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            chat_artifact_id = self._chat_artifact_id(chat_id)
            if self._record_exists(chat_artifact_id):
                chat, chat_binding = self._chat(chat_id)
            else:
                chat, chat_binding = self._persist_json_revision(
                    artifact_id=chat_artifact_id,
                    namespace="chats",
                    record={
                        "chat_id": chat_id,
                        "project_id": project_id,
                        "title": title,
                        "mode": "CHAT",
                        "head_event_id": None,
                        "event_ids": [],
                        "parent_chat_id": None,
                        "branch_from_event_id": None,
                        "created_by_command_id": command_id,
                        "created_at_utc": _utc_now(),
                        "updated_at_utc": _utc_now(),
                        "last_command_id": command_id,
                        "last_input_fingerprint_sha256": fingerprint,
                    },
                    revision_field="chat_revision",
                    operation_execution_id=op_exec,
                )
            if chat_id not in project.get("chat_ids", []):
                project_next = dict(project)
                project_next["chat_ids"] = list(project.get("chat_ids", [])) + [chat_id]
                project_next["updated_at_utc"] = _utc_now()
                project_next["last_command_id"] = command_id
                project_next["last_input_fingerprint_sha256"] = fingerprint
                project, project_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=project_next,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
            else:
                project_binding = self._manifest_binding(self.store.current_manifest(self._project_artifact_id(project_id)))
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="CHAT_CREATE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=chat["chat_revision"],
                produced_artifacts=[project_binding, chat_binding],
            )
            response = {
                "project": project,
                "chat": chat,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_CREATE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def rename_chat(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
        title: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        title = _validate_label(title, "title")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_RENAME",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_chat_revision": expected_chat_revision,
                "title": title,
            },
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat["project_id"] != project_id:
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            if chat["chat_revision"] != expected_chat_revision:
                if not (
                    chat.get("last_command_id") == command_id
                    and chat.get("last_input_fingerprint_sha256") == fingerprint
                ):
                    raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            if chat.get("last_command_id") == command_id and chat.get("last_input_fingerprint_sha256") == fingerprint:
                updated = chat
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._chat_artifact_id(chat_id))
                )
            elif chat.get("title") == title:
                updated = chat
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._chat_artifact_id(chat_id))
                )
            else:
                next_record = dict(chat)
                next_record["title"] = title
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._chat_artifact_id(chat_id),
                    namespace="chats",
                    record=next_record,
                    revision_field="chat_revision",
                    operation_execution_id=op_exec,
                )
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="CHAT_RENAME",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=updated["chat_revision"],
                produced_artifacts=[updated_binding],
            )
            response = {
                "chat": updated,
                "chat_binding": updated_binding,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_RENAME",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    @staticmethod
    def _chat_lifecycle_state(chat: dict[str, Any]) -> str:
        state = chat.get("lifecycle_state", "ACTIVE")
        if state not in {"ACTIVE", "ARCHIVED", "DELETED"}:
            raise WebContinuityError(
                "CORRUPT_RUNTIME_RECORD",
                "chat lifecycle_state must be ACTIVE, ARCHIVED, or DELETED",
                status_code=500,
            )
        return state

    def _set_chat_lifecycle(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
        archived: bool,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        command_type = "CHAT_ARCHIVE" if archived else "CHAT_UNARCHIVE"
        target_state = "ARCHIVED" if archived else "ACTIVE"
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type=command_type,
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_chat_revision": expected_chat_revision,
                "target_lifecycle_state": target_state,
            },
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat["project_id"] != project_id:
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            if chat["chat_revision"] != expected_chat_revision:
                if not (
                    chat.get("last_command_id") == command_id
                    and chat.get("last_input_fingerprint_sha256") == fingerprint
                ):
                    raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            current_state = self._chat_lifecycle_state(chat)
            if chat.get("last_command_id") == command_id and chat.get("last_input_fingerprint_sha256") == fingerprint:
                updated = chat
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._chat_artifact_id(chat_id))
                )
            elif current_state == target_state:
                updated = chat
                updated_binding = self._manifest_binding(
                    self.store.current_manifest(self._chat_artifact_id(chat_id))
                )
            else:
                next_record = dict(chat)
                next_record["lifecycle_state"] = target_state
                next_record["archived_at_utc"] = _utc_now() if archived else None
                next_record["updated_at_utc"] = _utc_now()
                next_record["last_command_id"] = command_id
                next_record["last_input_fingerprint_sha256"] = fingerprint
                updated, updated_binding = self._persist_json_revision(
                    artifact_id=self._chat_artifact_id(chat_id),
                    namespace="chats",
                    record=next_record,
                    revision_field="chat_revision",
                    operation_execution_id=op_exec,
                )
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type=command_type,
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=updated["chat_revision"],
                produced_artifacts=[updated_binding],
                extra={"lifecycle_state": self._chat_lifecycle_state(updated)},
            )
            response = {
                "chat": updated,
                "chat_binding": updated_binding,
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

    def archive_chat(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
    ) -> dict[str, Any]:
        return self._set_chat_lifecycle(
            command_id=command_id,
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=expected_chat_revision,
            archived=True,
        )

    def unarchive_chat(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
    ) -> dict[str, Any]:
        return self._set_chat_lifecycle(
            command_id=command_id,
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=expected_chat_revision,
            archived=False,
        )

    def delete_chat(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        command_type = "CHAT_DELETE"
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type=command_type,
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_chat_revision": expected_chat_revision,
                "target_lifecycle_state": "DELETED",
                "delete_semantics": "PRODUCT_SURFACE_DELETE_AUDIT_RETAINED",
            },
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat["project_id"] != project_id:
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            if chat["chat_revision"] != expected_chat_revision:
                raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)

            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            next_record = dict(chat)
            next_record["lifecycle_state"] = "DELETED"
            next_record["deleted_at_utc"] = _utc_now()
            next_record["updated_at_utc"] = _utc_now()
            next_record["last_command_id"] = command_id
            next_record["last_input_fingerprint_sha256"] = fingerprint
            updated, updated_binding = self._persist_json_revision(
                artifact_id=self._chat_artifact_id(chat_id),
                namespace="chats",
                record=next_record,
                revision_field="chat_revision",
                operation_execution_id=op_exec,
            )
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type=command_type,
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=updated["chat_revision"],
                produced_artifacts=[updated_binding],
                extra={
                    "lifecycle_state": "DELETED",
                    "delete_semantics": "PRODUCT_SURFACE_DELETE_AUDIT_RETAINED",
                    "privacy_erasure": False,
                },
            )
            response = {
                "chat": updated,
                "chat_binding": updated_binding,
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

    def append_user_message(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
        content: str,
        related_source_ref_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        if not isinstance(content, str) or content == "":
            raise WebContinuityError("INVALID_INPUT", "content must be non-empty text")
        if related_source_ref_ids is None:
            normalized_source_ref_ids: list[str] = []
        else:
            if not isinstance(related_source_ref_ids, list):
                raise WebContinuityError("INVALID_INPUT", "related_source_ref_ids must be an array")
            normalized_source_ref_ids = []
            seen_source_ref_ids: set[str] = set()
            for value in related_source_ref_ids:
                if not isinstance(value, str) or not value:
                    raise WebContinuityError("INVALID_INPUT", "related_source_ref_ids entries must be non-empty text")
                if value in seen_source_ref_ids:
                    raise WebContinuityError("INVALID_INPUT", "related_source_ref_ids must not contain duplicates")
                seen_source_ref_ids.add(value)
                normalized_source_ref_ids.append(value)
        legacy_payload = {
            "expected_chat_revision": expected_chat_revision,
            "content_sha256": _sha256_bytes(content.encode("utf-8")),
        }
        legacy_fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_APPEND_USER_MESSAGE",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload=legacy_payload,
        )
        fingerprint = (
            self._command_fingerprint(
                command_id=command_id,
                command_type="CHAT_APPEND_USER_MESSAGE",
                scope={"project_id": project_id, "chat_id": chat_id},
                payload={**legacy_payload, "related_source_ref_ids": normalized_source_ref_ids},
            )
            if normalized_source_ref_ids
            else legacy_fingerprint
        )
        with self._lock:
            if normalized_source_ref_ids:
                try:
                    replay = self._load_idempotent_response(command_id, fingerprint)
                except WebContinuityError as exc:
                    if exc.code != "IDEMPOTENCY_CONFLICT":
                        raise
                    # Upgrade compatibility: an exact pre-citation command may already
                    # exist with the legacy fingerprint and an immutable USER event
                    # whose related_source_ref_ids is []. Replay it; never rewrite history.
                    replay = self._load_idempotent_response(command_id, legacy_fingerprint)
            else:
                replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat["project_id"] != project_id:
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            for source_ref_id in normalized_source_ref_ids:
                try:
                    source_ref, _ = self._source_ref(source_ref_id)
                except WebContinuityError as exc:
                    raise WebContinuityError("SOURCE_NOT_BOUND", "related SourceRef does not exist", status_code=404) from exc
                if source_ref.get("project_id") != project_id:
                    raise WebContinuityError("SCOPE_MISMATCH", "related SourceRef belongs to another Project", status_code=409)
            if chat["chat_revision"] != expected_chat_revision:
                if not (chat.get("last_command_id") == command_id and chat.get("last_input_fingerprint_sha256") == fingerprint):
                    raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            event_id = _stable_id("EVT", chat_id, command_id, "USER_MESSAGE")
            event_artifact_id = self._event_artifact_id(event_id)
            if self._record_exists(event_artifact_id):
                event, event_binding = self._load_current_json(event_artifact_id)
            else:
                sequence = len(chat.get("event_ids", [])) + 1
                event, event_binding = self._persist_json_revision(
                    artifact_id=event_artifact_id,
                    namespace="events",
                    record={
                        "event_id": event_id,
                        "chat_id": chat_id,
                        "event_sequence_1_based": sequence,
                        "event_type": "USER_MESSAGE",
                        "actor_class": "USER",
                        "content_sha256": _sha256_bytes(content.encode("utf-8")),
                        "content": content,
                        "parent_event_id": chat.get("head_event_id"),
                        "related_job_id": None,
                        "related_source_ref_ids": list(normalized_source_ref_ids),
                        "created_at_utc": _utc_now(),
                    },
                    revision_field=None,
                    operation_execution_id=op_exec,
                )
            if event_id not in chat.get("event_ids", []):
                chat_next = dict(chat)
                chat_next["event_ids"] = list(chat.get("event_ids", [])) + [event_id]
                chat_next["head_event_id"] = event_id
                chat_next["updated_at_utc"] = _utc_now()
                chat_next["last_command_id"] = command_id
                chat_next["last_input_fingerprint_sha256"] = fingerprint
                chat, chat_binding = self._persist_json_revision(
                    artifact_id=self._chat_artifact_id(chat_id),
                    namespace="chats",
                    record=chat_next,
                    revision_field="chat_revision",
                    operation_execution_id=op_exec,
                )
            else:
                chat_binding = self._manifest_binding(self.store.current_manifest(self._chat_artifact_id(chat_id)))
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="CHAT_APPEND_USER_MESSAGE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=chat["chat_revision"],
                produced_artifacts=[event_binding, chat_binding],
            )
            response = {
                "chat": chat,
                "event": event,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_APPEND_USER_MESSAGE",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    # ---------- conversation branch graph ----------

    def _chat_event_index(
        self,
        chat: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        events: dict[str, dict[str, Any]] = {}
        bindings: dict[str, dict[str, Any]] = {}
        for event_id in chat.get("event_ids", []):
            if not isinstance(event_id, str) or not event_id:
                raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "chat event id must be non-empty text", status_code=500)
            if event_id in events:
                raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "chat event ids contain duplicates", status_code=500)
            event, binding = self._load_current_json(self._event_artifact_id(event_id))
            events[event_id] = event
            bindings[event_id] = binding
        try:
            validate_event_index(chat, events)
        except WebConversationGraphError as exc:
            raise WebContinuityError("CORRUPT_CONVERSATION_GRAPH", f"{exc.code}: {exc.message}", status_code=409) from exc
        return events, bindings

    def get_active_chat_ancestry(self, *, project_id: str, chat_id: str) -> dict[str, Any]:
        """Return one read-only exact active-branch projection; no persistence or model call."""
        with self._lock:
            project, _ = self._project(project_id)
            chat, chat_binding = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            events, bindings = self._chat_event_index(chat)
            try:
                projection = active_ancestry_projection(
                    chat=chat,
                    events_by_id=events,
                    bindings_by_id=bindings,
                )
            except WebConversationGraphError as exc:
                raise WebContinuityError("CORRUPT_CONVERSATION_GRAPH", f"{exc.code}: {exc.message}", status_code=409) from exc
            return {
                "chat": chat,
                "chat_binding": chat_binding,
                "active_ancestry": projection,
                "events": [events[event_id] for event_id in resolve_active_ancestry_ids(chat, events)],
            }

    def build_project_history_context(
        self,
        *,
        project_id: str,
        exclude_chat_id: str | None,
        max_bytes: int = PROJECT_HISTORY_CONTEXT_MAX_BYTES,
    ) -> dict[str, Any]:
        """Build one bounded same-Project history snapshot, optionally excluding one Runtime Chat."""

        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes < 1024
            or max_bytes > PROJECT_HISTORY_CONTEXT_MAX_BYTES
        ):
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_BUDGET_INVALID",
                "project history context max_bytes must be 1024..65536",
                status_code=400,
            )
        resumed = self.resume_project(project_id)
        project = resumed["project"]
        if exclude_chat_id is not None and exclude_chat_id not in project.get("chat_ids", []):
            raise WebContinuityError(
                "SCOPE_MISMATCH",
                "excluded current chat does not belong to project",
                status_code=409,
            )

        candidates: list[dict[str, Any]] = []
        for item in resumed.get("chats", []):
            chat = item.get("chat") if isinstance(item, dict) else None
            if not isinstance(chat, dict):
                continue
            chat_id = chat.get("chat_id")
            if chat_id == exclude_chat_id:
                continue
            if chat.get("project_id") != project_id:
                raise WebContinuityError(
                    "SCOPE_MISMATCH",
                    "project history chat belongs to another Project",
                    status_code=409,
                )
            if self._chat_lifecycle_state(chat) != "ACTIVE":
                continue
            if not isinstance(chat.get("head_event_id"), str) or not chat.get("head_event_id"):
                continue

            event_rows = item.get("events")
            if not isinstance(event_rows, list):
                raise WebContinuityError(
                    "CORRUPT_RUNTIME_RECORD",
                    "project history chat events are unavailable",
                    status_code=500,
                )
            events: dict[str, dict[str, Any]] = {}
            bindings: dict[str, dict[str, Any]] = {}
            for row in event_rows:
                event = row.get("event") if isinstance(row, dict) else None
                binding = row.get("binding") if isinstance(row, dict) else None
                event_id = event.get("event_id") if isinstance(event, dict) else None
                if not isinstance(event_id, str) or not event_id or not isinstance(binding, dict):
                    raise WebContinuityError(
                        "CORRUPT_RUNTIME_RECORD",
                        "project history event/binding is invalid",
                        status_code=500,
                    )
                events[event_id] = event
                bindings[event_id] = binding
            try:
                ancestry = active_ancestry_projection(
                    chat=chat,
                    events_by_id=events,
                    bindings_by_id=bindings,
                )
                active_ids = resolve_active_ancestry_ids(chat, events)
                active_snapshot = build_active_context_snapshot(
                    active_ancestry=ancestry,
                    events=[events[event_id] for event_id in active_ids],
                )
            except WebConversationGraphError as exc:
                raise WebContinuityError(
                    "CORRUPT_CONVERSATION_GRAPH",
                    f"{exc.code}: {exc.message}",
                    status_code=409,
                ) from exc

            messages = [
                {
                    "event_id": message["event_id"],
                    "role": message["role"],
                    "content": message["content"],
                    "content_sha256": message["content_sha256"],
                }
                for message in active_snapshot.get("ordered_messages", [])
            ]
            if not messages:
                continue
            candidates.append(
                {
                    "chat_id": chat_id,
                    "title": chat.get("title", ""),
                    "chat_revision": chat.get("chat_revision"),
                    "head_event_id": chat.get("head_event_id"),
                    "updated_at_utc": chat.get("updated_at_utc", ""),
                    "messages_truncated": False,
                    "messages": messages,
                }
            )

        candidates.sort(
            key=lambda row: (row.get("updated_at_utc", ""), row.get("chat_id", "")),
            reverse=True,
        )
        if not candidates:
            return {
                "project_history_context": None,
                "project_history_context_sha256": None,
                "project_history_context_bytes": 0,
                "selected_chat_count": 0,
                "total_candidate_chat_count": 0,
                "truncated": False,
            }

        def finalized(selected: list[dict[str, Any]], truncated: bool) -> dict[str, Any]:
            return {
                "schema": PROJECT_HISTORY_CONTEXT_SCHEMA,
                "authority_class": PROJECT_HISTORY_CONTEXT_AUTHORITY_CLASS,
                "source_class": PROJECT_HISTORY_CONTEXT_SOURCE_CLASS,
                "currentness_class": PROJECT_HISTORY_CONTEXT_CURRENTNESS_CLASS,
                "persistence_class": PROJECT_HISTORY_CONTEXT_PERSISTENCE_CLASS,
                "project_id": project_id,
                "excluded_chat_id": exclude_chat_id,
                "derived_from_project_revision": project.get("project_revision"),
                "history_order": "RECENT_CHAT_FIRST_MESSAGES_CHRONOLOGICAL",
                "max_bytes": max_bytes,
                "total_candidate_chat_count": len(candidates),
                "selected_chat_count": len(selected),
                "truncated": truncated,
                "chats": selected,
            }

        selected: list[dict[str, Any]] = []
        truncated = False
        for row in candidates:
            candidate = finalized(selected + [row], False)
            if len(_canonical_json_bytes(candidate)) <= max_bytes:
                selected.append(row)
                continue

            truncated = True
            original_messages = list(row["messages"])
            added_trimmed = False
            for start in range(1, len(original_messages)):
                trimmed_row = dict(row)
                trimmed_row["messages"] = original_messages[start:]
                trimmed_row["messages_truncated"] = True
                candidate = finalized(selected + [trimmed_row], True)
                if len(_canonical_json_bytes(candidate)) <= max_bytes:
                    selected.append(trimmed_row)
                    added_trimmed = True
                    break
            if not added_trimmed:
                # The bounded context may legitimately omit an oversized Chat.
                pass
            break

        if len(selected) < len(candidates):
            truncated = True
        context = finalized(selected, truncated)
        raw = _canonical_json_bytes(context)
        if len(raw) > max_bytes:
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_BUDGET_EXCEEDED",
                "bounded project history context exceeds max_bytes",
                status_code=409,
            )
        return {
            "project_history_context": context,
            "project_history_context_sha256": _sha256_bytes(raw),
            "project_history_context_bytes": len(raw),
            "selected_chat_count": len(selected),
            "total_candidate_chat_count": len(candidates),
            "truncated": truncated,
        }

    def validate_project_history_context_current(
        self,
        *,
        project_id: str,
        exclude_chat_id: str | None,
        project_history_context: dict[str, Any] | None,
        project_history_context_sha256: str | None,
    ) -> dict[str, Any] | None:
        """Fail closed when a frozen same-Project history snapshot is stale or cross-scoped."""

        if project_history_context is None and project_history_context_sha256 is None:
            return None
        if not isinstance(project_history_context, dict) or not isinstance(project_history_context_sha256, str):
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_INVALID",
                "project history context and exact SHA are required together",
                status_code=409,
            )
        if (
            project_history_context.get("schema") != PROJECT_HISTORY_CONTEXT_SCHEMA
            or project_history_context.get("authority_class") != PROJECT_HISTORY_CONTEXT_AUTHORITY_CLASS
            or project_history_context.get("source_class") != PROJECT_HISTORY_CONTEXT_SOURCE_CLASS
            or project_history_context.get("currentness_class") != PROJECT_HISTORY_CONTEXT_CURRENTNESS_CLASS
            or project_history_context.get("persistence_class") != PROJECT_HISTORY_CONTEXT_PERSISTENCE_CLASS
            or project_history_context.get("project_id") != project_id
            or project_history_context.get("excluded_chat_id") != exclude_chat_id
        ):
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_SCOPE_MISMATCH",
                "project history context scope/schema mismatch",
                status_code=409,
            )
        raw = _canonical_json_bytes(project_history_context)
        if _sha256_bytes(raw) != project_history_context_sha256:
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_SHA_MISMATCH",
                "project history context canonical SHA differs",
                status_code=409,
            )
        max_bytes = project_history_context.get("max_bytes")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes < 1024
            or max_bytes > PROJECT_HISTORY_CONTEXT_MAX_BYTES
            or len(raw) > max_bytes
        ):
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_BUDGET_INVALID",
                "project history context budget is invalid",
                status_code=409,
            )
        current = self.build_project_history_context(
            project_id=project_id,
            exclude_chat_id=exclude_chat_id,
            max_bytes=max_bytes,
        )
        if (
            current.get("project_history_context_sha256") != project_history_context_sha256
            or current.get("project_history_context") != project_history_context
        ):
            raise WebContinuityError(
                "PROJECT_HISTORY_CONTEXT_STALE",
                "same-Project history changed after request snapshot freeze",
                status_code=409,
            )
        return dict(project_history_context)

    def get_chat_branch_state(self, *, project_id: str, chat_id: str) -> dict[str, Any]:
        """Return active ancestry plus all valid leaf heads for one Chat; read-only."""
        with self._lock:
            project, _ = self._project(project_id)
            chat, chat_binding = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            events, bindings = self._chat_event_index(chat)
            try:
                active_ids = resolve_active_ancestry_ids(chat, events)
                projection = active_ancestry_projection(
                    chat=chat,
                    events_by_id=events,
                    bindings_by_id=bindings,
                )
                leaves = leaf_event_ids(chat, events)
            except WebConversationGraphError as exc:
                raise WebContinuityError("CORRUPT_CONVERSATION_GRAPH", f"{exc.code}: {exc.message}", status_code=409) from exc
            leaf_heads = []
            for event_id in leaves:
                event = events[event_id]
                leaf_heads.append(
                    {
                        "event_id": event_id,
                        "event_sequence_1_based": event.get("event_sequence_1_based"),
                        "event_type": event.get("event_type"),
                        "actor_class": event.get("actor_class"),
                        "content_sha256": event.get("content_sha256"),
                        "active": event_id == chat.get("head_event_id"),
                    }
                )
            return {
                "schema": "WEB_CHAT_BRANCH_STATE_V1",
                "chat": chat,
                "chat_binding": chat_binding,
                "active_ancestry": projection,
                "active_events": [events[event_id] for event_id in active_ids],
                "leaf_heads": leaf_heads,
            }

    def edit_user_message_as_branch(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
        target_user_event_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Append one immutable edited USER sibling and make only that new leaf active."""
        command_id = _validate_command_id(command_id)
        if not isinstance(content, str) or content == "":
            raise WebContinuityError("INVALID_INPUT", "content must be non-empty text")
        if not isinstance(target_user_event_id, str) or not target_user_event_id:
            raise WebContinuityError("INVALID_INPUT", "target_user_event_id required")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_EDIT_USER_MESSAGE_AS_BRANCH",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_chat_revision": expected_chat_revision,
                "target_user_event_id": target_user_event_id,
                "content_sha256": _sha256_bytes(content.encode("utf-8")),
            },
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            if chat.get("chat_revision") != expected_chat_revision:
                raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)
            events, bindings = self._chat_event_index(chat)
            target = events.get(target_user_event_id)
            if target is None:
                raise WebContinuityError("TARGET_EVENT_NOT_FOUND", "target event is not in this chat", status_code=404)
            if target.get("event_type") != "USER_MESSAGE" or target.get("actor_class") != "USER":
                raise WebContinuityError("EDIT_TARGET_NOT_USER", "only a persisted USER_MESSAGE may be edited as a branch", status_code=409)

            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            event_id = _stable_id("EVT", chat_id, command_id, target_user_event_id, "USER_EDIT_BRANCH")
            event_artifact_id = self._event_artifact_id(event_id)
            expected_event = {
                "event_id": event_id,
                "chat_id": chat_id,
                "event_sequence_1_based": len(chat.get("event_ids", [])) + 1,
                "event_type": "USER_MESSAGE",
                "actor_class": "USER",
                "content_sha256": _sha256_bytes(content.encode("utf-8")),
                "content": content,
                "parent_event_id": target.get("parent_event_id"),
                "edited_from_event_id": target_user_event_id,
                "related_job_id": None,
                "related_source_ref_ids": list(target.get("related_source_ref_ids") or []),
            }
            candidate_events = dict(events)
            candidate_events[event_id] = dict(expected_event)
            candidate_chat = dict(chat)
            candidate_chat["event_ids"] = list(chat.get("event_ids", [])) + [event_id]
            candidate_chat["head_event_id"] = event_id
            try:
                validate_event_index(candidate_chat, candidate_events)
                validate_leaf_head_target(candidate_chat, candidate_events, event_id)
                resolve_active_ancestry_ids(candidate_chat, candidate_events)
            except WebConversationGraphError as exc:
                raise WebContinuityError("INVALID_BRANCH_GRAPH", f"{exc.code}: {exc.message}", status_code=409) from exc

            if self._record_exists(event_artifact_id):
                event, event_binding = self._load_current_json(event_artifact_id)
                for key, value in expected_event.items():
                    if event.get(key) != value:
                        raise WebContinuityError("IDEMPOTENCY_CONFLICT", "existing edited branch event conflicts", status_code=409)
            else:
                event_record = dict(expected_event)
                event_record["created_at_utc"] = _utc_now()
                event, event_binding = self._persist_json_revision(
                    artifact_id=event_artifact_id,
                    namespace="events",
                    record=event_record,
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

            chat_next = dict(chat)
            if event_id not in chat_next.get("event_ids", []):
                chat_next["event_ids"] = list(chat.get("event_ids", [])) + [event_id]
            chat_next["head_event_id"] = event_id
            chat_next["updated_at_utc"] = _utc_now()
            chat_next["last_command_id"] = command_id
            chat_next["last_input_fingerprint_sha256"] = fingerprint
            chat, chat_binding = self._persist_json_revision(
                artifact_id=self._chat_artifact_id(chat_id),
                namespace="chats",
                record=chat_next,
                revision_field="chat_revision",
                operation_execution_id=op_exec,
            )
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="CHAT_EDIT_USER_MESSAGE_AS_BRANCH",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=chat["chat_revision"],
                produced_artifacts=[event_binding, chat_binding],
                extra={"target_user_event_id": target_user_event_id, "new_branch_head_event_id": event_id},
            )
            response = {
                "chat": chat,
                "event": event,
                "active_ancestry": self.get_active_chat_ancestry(project_id=project_id, chat_id=chat_id)["active_ancestry"],
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_EDIT_USER_MESSAGE_AS_BRANCH",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def regenerate_successful_assistant_as_branch(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
        target_assistant_event_id: str,
    ) -> dict[str, Any]:
        """Create one fresh USER sibling for a successful ASSISTANT leaf; never replay the predecessor Job."""
        command_id = _validate_command_id(command_id)
        if not isinstance(target_assistant_event_id, str) or not target_assistant_event_id:
            raise WebContinuityError("INVALID_INPUT", "target_assistant_event_id required")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_REGENERATE_USER_BRANCH",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_chat_revision": expected_chat_revision,
                "target_assistant_event_id": target_assistant_event_id,
            },
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)

            exact_recovery = False
            if chat.get("chat_revision") != expected_chat_revision:
                exact_recovery = bool(
                    chat.get("last_command_id") == command_id
                    and chat.get("last_input_fingerprint_sha256") == fingerprint
                )
                if not exact_recovery:
                    raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)

            events, _ = self._chat_event_index(chat)
            target_assistant = events.get(target_assistant_event_id)
            if target_assistant is None:
                raise WebContinuityError("TARGET_EVENT_NOT_FOUND", "target Assistant event is not in this chat", status_code=404)
            if target_assistant.get("event_type") != "ASSISTANT_MESSAGE" or target_assistant.get("actor_class") != "ASSISTANT":
                raise WebContinuityError("REGENERATE_TARGET_NOT_ASSISTANT", "target must be a persisted ASSISTANT_MESSAGE", status_code=409)
            predecessor_job_id = target_assistant.get("related_job_id")
            if not isinstance(predecessor_job_id, str) or not predecessor_job_id:
                raise WebContinuityError("REGENERATE_TARGET_NOT_SUCCESSFUL_FORMAL_ASSISTANT", "target Assistant must bind one predecessor Job", status_code=409)
            try:
                validate_leaf_head_target(chat, events, target_assistant_event_id)
            except WebConversationGraphError as exc:
                raise WebContinuityError("REGENERATE_TARGET_NOT_LEAF", f"{exc.code}: {exc.message}", status_code=409) from exc

            original_user_event_id = target_assistant.get("parent_event_id")
            original_user = events.get(original_user_event_id)
            if (
                original_user is None
                or original_user.get("event_type") != "USER_MESSAGE"
                or original_user.get("actor_class") != "USER"
            ):
                raise WebContinuityError("REGENERATE_PARENT_NOT_USER", "successful Assistant must have one immediate USER_MESSAGE parent", status_code=409)

            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            event_id = _stable_id("EVT", chat_id, command_id, target_assistant_event_id, "USER_REGENERATE_BRANCH")
            event_artifact_id = self._event_artifact_id(event_id)
            expected_event = {
                "event_id": event_id,
                "chat_id": chat_id,
                "event_sequence_1_based": len(chat.get("event_ids", [])) + (0 if event_id in chat.get("event_ids", []) else 1),
                "event_type": "USER_MESSAGE",
                "actor_class": "USER",
                "content_sha256": original_user.get("content_sha256"),
                "content": original_user.get("content"),
                "parent_event_id": original_user.get("parent_event_id"),
                "regenerated_from_user_event_id": original_user_event_id,
                "regenerated_from_assistant_event_id": target_assistant_event_id,
                "related_job_id": None,
                "related_source_ref_ids": list(original_user.get("related_source_ref_ids") or []),
            }
            if not isinstance(expected_event["content"], str) or not expected_event["content"]:
                raise WebContinuityError("REGENERATE_PARENT_CONTENT_INVALID", "original USER_MESSAGE content missing", status_code=409)
            if _sha256_bytes(expected_event["content"].encode("utf-8")) != expected_event["content_sha256"]:
                raise WebContinuityError("REGENERATE_PARENT_CONTENT_TAMPERED", "original USER_MESSAGE content SHA mismatch", status_code=409)

            if not exact_recovery and chat.get("head_event_id") != target_assistant_event_id:
                raise WebContinuityError("REGENERATE_TARGET_NOT_CURRENT_HEAD", "target Assistant must be exact current successful leaf", status_code=409)

            event_exists = self._record_exists(event_artifact_id)
            if event_exists:
                event, event_binding = self._load_current_json(event_artifact_id)
                for key, value in expected_event.items():
                    if event.get(key) != value:
                        raise WebContinuityError("IDEMPOTENCY_CONFLICT", "existing regenerate branch event conflicts", status_code=409)
            else:
                candidate_events = dict(events)
                candidate_events[event_id] = dict(expected_event)
                candidate_chat = dict(chat)
                candidate_chat["event_ids"] = list(chat.get("event_ids", [])) + [event_id]
                candidate_chat["head_event_id"] = event_id
                try:
                    validate_event_index(candidate_chat, candidate_events)
                    validate_leaf_head_target(candidate_chat, candidate_events, event_id)
                    resolve_active_ancestry_ids(candidate_chat, candidate_events)
                except WebConversationGraphError as exc:
                    raise WebContinuityError("INVALID_REGENERATE_BRANCH_GRAPH", f"{exc.code}: {exc.message}", status_code=409) from exc
                event_record = dict(expected_event)
                event_record["created_at_utc"] = _utc_now()
                event, event_binding = self._persist_json_revision(
                    artifact_id=event_artifact_id,
                    namespace="events",
                    record=event_record,
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

            if event_id in chat.get("event_ids", []):
                if chat.get("head_event_id") != event_id:
                    raise WebContinuityError("REGENERATE_RECOVERY_HEAD_CONFLICT", "existing regenerate event is not current head", status_code=409)
                chat_binding = self._manifest_binding(self.store.current_manifest(self._chat_artifact_id(chat_id)))
            else:
                chat_next = dict(chat)
                chat_next["event_ids"] = list(chat.get("event_ids", [])) + [event_id]
                chat_next["head_event_id"] = event_id
                chat_next["updated_at_utc"] = _utc_now()
                chat_next["last_command_id"] = command_id
                chat_next["last_input_fingerprint_sha256"] = fingerprint
                chat, chat_binding = self._persist_json_revision(
                    artifact_id=self._chat_artifact_id(chat_id),
                    namespace="chats",
                    record=chat_next,
                    revision_field="chat_revision",
                    operation_execution_id=op_exec,
                )

            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="CHAT_REGENERATE_USER_BRANCH",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=chat["chat_revision"],
                produced_artifacts=[event_binding, chat_binding],
                extra={
                    "regenerated_from_user_event_id": original_user_event_id,
                    "regenerated_from_assistant_event_id": target_assistant_event_id,
                    "predecessor_job_id": predecessor_job_id,
                    "new_branch_head_event_id": event_id,
                    "predecessor_job_replayed": False,
                },
            )
            response = {
                "chat": chat,
                "event": event,
                "predecessor_user_event": original_user,
                "predecessor_assistant_event": target_assistant,
                "predecessor_job_id": predecessor_job_id,
                "active_ancestry": self.get_active_chat_ancestry(project_id=project_id, chat_id=chat_id)["active_ancestry"],
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_REGENERATE_USER_BRANCH",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def select_chat_head(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        expected_chat_revision: int,
        target_head_event_id: str,
    ) -> dict[str, Any]:
        """Select one already-persisted leaf as the active conversation head."""
        command_id = _validate_command_id(command_id)
        if not isinstance(target_head_event_id, str) or not target_head_event_id:
            raise WebContinuityError("INVALID_INPUT", "target_head_event_id required")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_SELECT_ACTIVE_HEAD",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_chat_revision": expected_chat_revision,
                "target_head_event_id": target_head_event_id,
            },
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            if chat.get("chat_revision") != expected_chat_revision:
                raise WebContinuityError("STALE_CHAT_REVISION", "expected chat revision is stale", status_code=409)
            events, _ = self._chat_event_index(chat)
            try:
                validate_leaf_head_target(chat, events, target_head_event_id)
            except WebConversationGraphError as exc:
                raise WebContinuityError(exc.code, exc.message, status_code=409) from exc

            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            changed = chat.get("head_event_id") != target_head_event_id
            if changed:
                chat_next = dict(chat)
                chat_next["head_event_id"] = target_head_event_id
                chat_next["updated_at_utc"] = _utc_now()
                chat_next["last_command_id"] = command_id
                chat_next["last_input_fingerprint_sha256"] = fingerprint
                chat, chat_binding = self._persist_json_revision(
                    artifact_id=self._chat_artifact_id(chat_id),
                    namespace="chats",
                    record=chat_next,
                    revision_field="chat_revision",
                    operation_execution_id=op_exec,
                )
            else:
                chat_binding = self._manifest_binding(self.store.current_manifest(self._chat_artifact_id(chat_id)))

            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="CHAT_SELECT_ACTIVE_HEAD",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=chat["chat_revision"],
                produced_artifacts=[chat_binding],
                extra={"target_head_event_id": target_head_event_id, "head_changed": changed},
            )
            response = {
                "chat": chat,
                "active_ancestry": self.get_active_chat_ancestry(project_id=project_id, chat_id=chat_id)["active_ancestry"],
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_SELECT_ACTIVE_HEAD",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    # ---------- text ingest ----------

    def _decode_text(self, raw: bytes) -> dict[str, Any]:
        if raw.startswith(codecs.BOM_UTF8):
            selected_encoding = "utf-8-sig"
            bom_status = "UTF8_BOM"
            text = raw.decode("utf-8-sig", errors="strict")
        elif raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
            raise WebContinuityError(
                "ENCODING_SELECTION_REQUIRED",
                "UTF-16 BOM detected; M001-A only accepts UTF-8/UTF-8-BOM without explicit extension",
                status_code=422,
            )
        else:
            selected_encoding = "utf-8"
            bom_status = "NONE"
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise WebContinuityError(
                    "ENCODING_SELECTION_REQUIRED",
                    "strict UTF-8 decode failed; select an explicit allowlisted encoding in a later capability",
                    status_code=422,
                ) from exc

        line_count = len(text.splitlines())
        if text and line_count == 0:
            line_count = 1
        derivation_sha = _sha256_bytes(text.encode("utf-8"))
        return {
            "decoder_id": DECODER_ID,
            "decoder_revision": DECODER_REVISION,
            "selected_encoding": selected_encoding,
            "bom_status": bom_status,
            "decoded_codepoint_count": len(text),
            "line_count": line_count,
            "decoded_text": text,
            "derivation_sha256": derivation_sha,
            "warnings": [],
            "replacements": 0,
        }

    def ingest_text_source(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        filename: str,
        raw_bytes: bytes,
        chat_id: str | None = None,
        role: str = "PROJECT_SOURCE",
        origin_class: str = "PROJECT_UPLOAD",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        filename = _validate_filename(filename)
        if not isinstance(raw_bytes, bytes):
            raise WebContinuityError("INVALID_INPUT", "raw source body must be bytes")
        if len(raw_bytes) > MAX_TEXT_SOURCE_BYTES:
            raise WebContinuityError("SOURCE_TOO_LARGE", f"M001-A source exceeds {MAX_TEXT_SOURCE_BYTES} bytes", status_code=413)
        role = _validate_label(role, "role")
        origin_class = _validate_label(origin_class, "origin_class")
        if provenance is not None and not isinstance(provenance, dict):
            raise WebContinuityError("INVALID_INPUT", "provenance must be an object")
        source_sha = _sha256_bytes(raw_bytes)
        fingerprint_payload = {
            "expected_project_revision": expected_project_revision,
            "filename": filename,
            "role": role,
            "source_sha256": source_sha,
            "source_byte_size": len(raw_bytes),
        }
        if origin_class != "PROJECT_UPLOAD" or provenance is not None:
            fingerprint_payload["origin_class"] = origin_class
            fingerprint_payload["provenance"] = provenance
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="TEXT_SOURCE_INGEST",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload=fingerprint_payload,
        )

        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                if not (project.get("last_command_id") == command_id and project.get("last_input_fingerprint_sha256") == fingerprint):
                    raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)
            if chat_id is not None:
                chat, _ = self._chat(chat_id)
                if chat["project_id"] != project_id:
                    raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)

            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            source_ref_id = _stable_id("SRC", project_id, command_id, source_sha)
            source_ref_artifact_id = self._source_ref_artifact_id(source_ref_id)

            if self._record_exists(source_ref_artifact_id):
                source_ref, source_ref_binding = self._source_ref(source_ref_id)
                if source_ref.get("input_fingerprint_sha256") != fingerprint:
                    raise WebContinuityError("IDEMPOTENCY_CONFLICT", "existing SourceRef conflicts", status_code=409)
                derivation, _ = self._load_current_json(source_ref["derived_projection_binding"]["artifact_id"])
                source_binding = source_ref["source_artifact_binding"]
                ingest_receipt, _ = self._load_current_json(source_ref["ingest_receipt_binding"]["artifact_id"])
            else:
                decode = self._decode_text(raw_bytes)
                source_identity_sha = _sha256_bytes(
                    f"UR_WEB_M001_SOURCE_V1|{project_id}|{command_id}|{source_sha}".encode("utf-8")
                )
                opaque_binding, opaque_manifest = self.store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=source_identity_sha,
                    artifact_bytes=raw_bytes,
                    job_id=op_exec,
                    persistence_class=PersistenceClass.WORKING,
                    expected_artifact_sha256=source_sha,
                )
                _, exact_loaded = self.store.load_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=opaque_binding.artifact_identity_sha256,
                    artifact_revision=opaque_binding.artifact_revision,
                    artifact_sha256=opaque_binding.artifact_sha256,
                )
                if exact_loaded != raw_bytes:
                    raise WebContinuityError("SOURCE_BYTE_MISMATCH", "opaque ArtifactStore reload changed source bytes", status_code=500)

                source_binding = {
                    "artifact_id": opaque_manifest.artifact_id,
                    "artifact_identity_sha256": opaque_binding.artifact_identity_sha256,
                    "revision": opaque_binding.artifact_revision,
                    "sha256": opaque_binding.artifact_sha256,
                    "byte_size": len(raw_bytes),
                    "media_type": "text/markdown" if filename.lower().endswith(".md") else "text/plain",
                }

                derivation_artifact_id = "WEB_TEXT_DERIVATION_" + _artifact_suffix(source_ref_id)
                derivation_record = {
                    "source_sha256": source_sha,
                    **decode,
                    "created_by_command_id": command_id,
                    "input_fingerprint_sha256": fingerprint,
                    "created_at_utc": _utc_now(),
                }
                derivation, derivation_binding = self._persist_json_revision(
                    artifact_id=derivation_artifact_id,
                    namespace="derivations",
                    record=derivation_record,
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

                ingest_receipt_artifact_id = "WEB_TEXT_INGEST_RECEIPT_" + _artifact_suffix(source_ref_id)
                ingest_receipt, ingest_receipt_binding = self._persist_json_revision(
                    artifact_id=ingest_receipt_artifact_id,
                    namespace="ingest_receipts",
                    record={
                        "source_artifact_binding": source_binding,
                        "source_byte_size": len(raw_bytes),
                        "detected_media_type": source_binding["media_type"],
                        "decoder_id": decode["decoder_id"],
                        "decoder_revision": decode["decoder_revision"],
                        "selected_encoding": decode["selected_encoding"],
                        "derivation_artifact_binding": derivation_binding,
                        "derivation_sha256": decode["derivation_sha256"],
                        "replacements": 0,
                        "network_used": False,
                        "model_used": False,
                        "ocr_used": False,
                        "result": "PASS",
                        "warnings": decode["warnings"],
                        "errors": [],
                        "operation_execution_id": op_exec,
                        "formal_job": False,
                        "created_at_utc": _utc_now(),
                    },
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

                source_ref, source_ref_binding = self._persist_json_revision(
                    artifact_id=source_ref_artifact_id,
                    namespace="source_refs",
                    record={
                        "source_ref_id": source_ref_id,
                        "project_id": project_id,
                        "source_artifact_binding": source_binding,
                        "derived_projection_binding": derivation_binding,
                        "ingest_receipt_binding": ingest_receipt_binding,
                        "origin_class": origin_class,
                        "filename": filename,
                        "role": role,
                        **({"provenance": dict(provenance)} if provenance is not None else {}),
                        "created_by_command_id": command_id,
                        "input_fingerprint_sha256": fingerprint,
                        "created_at_utc": _utc_now(),
                    },
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

            if source_ref_id not in project.get("source_ref_ids", []):
                project_next = dict(project)
                project_next["source_ref_ids"] = list(project.get("source_ref_ids", [])) + [source_ref_id]
                project_next["updated_at_utc"] = _utc_now()
                project_next["last_command_id"] = command_id
                project_next["last_input_fingerprint_sha256"] = fingerprint
                project, project_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=project_next,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
            else:
                project_binding = self._manifest_binding(self.store.current_manifest(self._project_artifact_id(project_id)))

            produced = [project_binding, source_ref_binding, source_ref["derived_projection_binding"], source_ref["ingest_receipt_binding"]]
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="TEXT_SOURCE_INGEST",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=None,
                source_ref_id=source_ref_id,
                source_sha256=source_binding["sha256"],
                derivation_sha256=derivation["derivation_sha256"],
                produced_artifacts=produced,
                extra={
                    "filename": filename,
                    "selected_encoding": derivation["selected_encoding"],
                    "line_count": derivation["line_count"],
                    "source_byte_size": source_binding["byte_size"],
                },
            )
            response = {
                "project": project,
                "source_ref": source_ref,
                "text_derivation": derivation,
                "ingest_receipt": ingest_receipt,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="TEXT_SOURCE_INGEST",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response

    def save_chat_output_source(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        filename: str,
        raw_bytes: bytes,
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        filename = _validate_filename(filename)
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise WebContinuityError("INVALID_INPUT", "chat output source must contain bytes")
        if not isinstance(provenance, dict):
            raise WebContinuityError("INVALID_INPUT", "chat output provenance must be an object")
        required = (
            "owner_user_id",
            "librechat_project_id",
            "conversation_id",
            "message_id",
            "parent_message_id",
            "content_sha256",
        )
        for key in required:
            value = provenance.get(key)
            if not isinstance(value, str) or not value:
                raise WebContinuityError("INVALID_INPUT", f"chat output provenance {key} required")
        source_sha = _sha256_bytes(raw_bytes)
        if provenance.get("content_sha256") != source_sha:
            raise WebContinuityError(
                "SOURCE_PROVENANCE_MISMATCH",
                "chat output content SHA mismatch",
                status_code=409,
            )
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="CHAT_OUTPUT_SOURCE_SAVE",
            scope={
                "project_id": project_id,
                "librechat_project_id": provenance["librechat_project_id"],
                "conversation_id": provenance["conversation_id"],
                "message_id": provenance["message_id"],
            },
            payload={
                "filename": filename,
                "source_sha256": source_sha,
                "source_byte_size": len(raw_bytes),
                "provenance": provenance,
            },
        )
        inner_command_id = _stable_id("CMDSRC", command_id, "CHAT_OUTPUT_INGEST")
        source_ref_id = _stable_id("SRC", project_id, inner_command_id, source_sha)
        with self._lock:
            if self._record_exists(self._source_ref_artifact_id(source_ref_id)):
                existing_source_ref, _ = self._source_ref(source_ref_id, include_deleted=True)
                lifecycle, _ = self._source_lifecycle(source_ref_id)
                current_project, _ = self._project(project_id)
                if lifecycle.get("lifecycle_state") == "DELETED":
                    raise WebContinuityError(
                        "SOURCE_DELETED",
                        "Saved chat output was deleted from active Project/library use",
                        status_code=410,
                    )
                if source_ref_id not in current_project.get("source_ref_ids", []):
                    raise WebContinuityError(
                        "SOURCE_NOT_BOUND",
                        "Saved chat output is no longer active in this Project",
                        status_code=409,
                    )
                if existing_source_ref.get("project_id") != project_id:
                    raise WebContinuityError("SCOPE_MISMATCH", "SourceRef project mismatch", status_code=409)
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            if self._record_exists(self._source_ref_artifact_id(source_ref_id)):
                source_ref, _ = self._source_ref(source_ref_id)
                if (
                    source_ref.get("project_id") != project_id
                    or source_ref.get("origin_class") != "CHAT_OUTPUT"
                    or source_ref.get("provenance") != provenance
                    or source_ref.get("source_artifact_binding", {}).get("sha256") != source_sha
                ):
                    raise WebContinuityError(
                        "IDEMPOTENCY_CONFLICT",
                        "existing chat-output SourceRef conflicts",
                        status_code=409,
                    )
                project, _ = self._project(project_id)
                if source_ref_id not in project.get("source_ref_ids", []):
                    raise WebContinuityError(
                        "SOURCE_SAVE_RECOVERY_NOT_ACTIVE",
                        "saved chat output is no longer active in this Project",
                        status_code=409,
                    )
                derivation, _ = self._load_current_json(
                    source_ref["derived_projection_binding"]["artifact_id"]
                )
                ingest_receipt, _ = self._load_current_json(
                    source_ref["ingest_receipt_binding"]["artifact_id"]
                )
                response = {
                    "project": project,
                    "source_ref": source_ref,
                    "text_derivation": derivation,
                    "ingest_receipt": ingest_receipt,
                    "recovered_after_inner_commit": True,
                }
                self._persist_command_record(
                    command_id=command_id,
                    command_type="CHAT_OUTPUT_SOURCE_SAVE",
                    input_fingerprint=fingerprint,
                    operation_execution_id=self._operation_execution_id(
                        project_id=project_id, chat_id=None, command_id=command_id
                    ),
                    response=response,
                )
                return response
            inner = self.ingest_text_source(
                command_id=inner_command_id,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                filename=filename,
                raw_bytes=raw_bytes,
                role="PROJECT_SOURCE",
                origin_class="CHAT_OUTPUT",
                provenance=provenance,
            )
            response = dict(inner)
            response["recovered_after_inner_commit"] = False
            self._persist_command_record(
                command_id=command_id,
                command_type="CHAT_OUTPUT_SOURCE_SAVE",
                input_fingerprint=fingerprint,
                operation_execution_id=self._operation_execution_id(
                    project_id=project_id, chat_id=None, command_id=command_id
                ),
                response=response,
            )
            return response
    def _mutate_project_source_lifecycle(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        source_ref_id: str,
        action: str,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        if action != "REMOVE_FROM_PROJECT":
            raise WebContinuityError("INVALID_INPUT", "only Remove from Project is supported")
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type=f"PROJECT_SOURCE_{action}",
            scope={"project_id": project_id, "source_ref_id": source_ref_id},
            payload={"action": action},
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            source_ref, _ = self._source_ref(source_ref_id, include_deleted=True)
            if source_ref.get("project_id") != project_id:
                raise WebContinuityError("SCOPE_MISMATCH", "SourceRef project mismatch", status_code=409)
            lifecycle, lifecycle_binding = self._source_lifecycle(source_ref_id)
            bound = source_ref_id in project.get("source_ref_ids", [])
            recovery_after_project_commit = (
                not bound
                and project.get("last_command_id") == command_id
                and project.get("last_input_fingerprint_sha256") == fingerprint
            )
            if not bound and not recovery_after_project_commit:
                raise WebContinuityError(
                    "SOURCE_NOT_BOUND",
                    "SourceRef is not bound to this Project",
                    status_code=404,
                )
            if (
                project["project_revision"] != expected_project_revision
                and not recovery_after_project_commit
            ):
                raise WebContinuityError(
                    "STALE_PROJECT_REVISION",
                    "expected project revision is stale",
                    status_code=409,
                )
            op_exec = self._operation_execution_id(
                project_id=project_id, chat_id=None, command_id=command_id
            )
            if bound:
                project_next = dict(project)
                project_next["source_ref_ids"] = [
                    value for value in project.get("source_ref_ids", []) if value != source_ref_id
                ]
                project_next["updated_at_utc"] = _utc_now()
                project_next["last_command_id"] = command_id
                project_next["last_input_fingerprint_sha256"] = fingerprint
                project, project_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=project_next,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
            else:
                project_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )

            lifecycle_state = "REMOVED_FROM_PROJECT"
            lifecycle_record = {
                "source_ref_id": source_ref_id,
                "project_id": project_id,
                "lifecycle_state": lifecycle_state,
                "remove_semantics": "PROJECT_BINDING_REMOVED_SOURCE_BYTES_RETAINED",
                "privacy_erasure": False,
                "created_by_command_id": command_id,
                "updated_at_utc": _utc_now(),
            }
            lifecycle, lifecycle_binding = self._persist_json_revision(
                artifact_id=self._source_lifecycle_artifact_id(source_ref_id),
                namespace="source_lifecycle",
                record=lifecycle_record,
                revision_field="lifecycle_revision",
                operation_execution_id=op_exec,
            )
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type=f"PROJECT_SOURCE_{action}",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=None,
                chat_revision=None,
                source_ref_id=source_ref_id,
                source_sha256=source_ref["source_artifact_binding"]["sha256"],
                derivation_sha256=None,
                produced_artifacts=[project_binding, lifecycle_binding],
                extra={
                    "source_lifecycle_action": action,
                    "lifecycle_state": lifecycle_state,
                    "remove_semantics": lifecycle["remove_semantics"],
                    "privacy_erasure": False,
                },
            )
            response = {
                "project": project,
                "source_ref_id": source_ref_id,
                "lifecycle": lifecycle,
                "lifecycle_binding": lifecycle_binding,
                "operation": receipt,
                "operation_binding": receipt_binding,
                "removed_from_project": True,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type=f"PROJECT_SOURCE_{action}",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response
    def remove_source_from_project(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        source_ref_id: str,
    ) -> dict[str, Any]:
        return self._mutate_project_source_lifecycle(
            command_id=command_id,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            source_ref_id=source_ref_id,
            action="REMOVE_FROM_PROJECT",
        )

    def adopt_document_bundle_source(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        document_bundle_binding: dict[str, Any],
        chat_id: str | None = None,
        role: str = "PROJECT_SOURCE",
    ) -> dict[str, Any]:
        """Adopt a validated document bundle without changing the existing text source-context contract."""
        command_id = _validate_command_id(command_id)
        role = _validate_label(role, "role")
        if not isinstance(document_bundle_binding, dict):
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE_BINDING", "exact document bundle binding required")
        required = ("artifact_id", "artifact_identity_sha256", "revision", "sha256")
        if any(key not in document_bundle_binding for key in required):
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE_BINDING", "document bundle binding incomplete")
        identity = document_bundle_binding.get("artifact_identity_sha256")
        revision = document_bundle_binding.get("revision")
        bundle_sha = document_bundle_binding.get("sha256")
        artifact_id = document_bundle_binding.get("artifact_id")
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE_BINDING", "document bundle identity invalid")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision != 1:
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE_BINDING", "document bundle revision must be 1")
        if not isinstance(bundle_sha, str) or re.fullmatch(r"[0-9a-f]{64}", bundle_sha) is None:
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE_BINDING", "document bundle SHA invalid")
        if artifact_id != "RUNTIME_OPAQUE_" + identity.upper():
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE_BINDING", "document bundle artifact_id/identity mismatch")

        try:
            bundle_manifest, bundle_bytes = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=identity,
                artifact_revision=revision,
                artifact_sha256=bundle_sha,
            )
        except Exception as exc:
            raise WebContinuityError("DOCUMENT_BUNDLE_STALE_OR_TAMPERED", "exact document bundle binding failed", status_code=409) from exc
        if bundle_manifest.artifact_id != artifact_id or _sha256_bytes(bundle_bytes) != bundle_sha:
            raise WebContinuityError("DOCUMENT_BUNDLE_STALE_OR_TAMPERED", "document bundle manifest/bytes mismatch", status_code=409)

        try:
            with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as archive:
                provenance_bytes = archive.read("provenance.json")
                manifest_bytes = archive.read("00_DOCUMENT_BUNDLE_MANIFEST.json")
                markdown_bytes = archive.read("document.md")
                json_bytes = archive.read("document.json")
                provenance = json.loads(provenance_bytes.decode("utf-8"))
                member_manifest = json.loads(manifest_bytes.decode("utf-8"))
                if provenance.get("schema") != "UR_PLANE_C_C1_DOCUMENT_ARTIFACT_PROVENANCE_R001":
                    raise ValueError("unexpected provenance schema")
                input_format = provenance.get("input_format")
                if input_format not in {"pdf", "docx"}:
                    raise ValueError("unsupported input format")
                original_member = "original." + input_format
                expected_names = {
                    "00_DOCUMENT_BUNDLE_MANIFEST.json",
                    original_member,
                    "document.md",
                    "document.json",
                    "provenance.json",
                }
                if set(archive.namelist()) != expected_names:
                    raise ValueError("document bundle closed-world mismatch")
                original_bytes = archive.read(original_member)
        except (KeyError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, ValueError) as exc:
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", "document bundle structure invalid", status_code=409) from exc

        filename = _validate_document_filename(provenance.get("source_filename"), input_format)
        if _sha256_bytes(original_bytes) != provenance.get("input_sha256"):
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", "original SHA mismatch", status_code=409)
        markdown_sha = _sha256_bytes(markdown_bytes)
        json_sha = _sha256_bytes(json_bytes)
        if markdown_sha != provenance.get("markdown_sha256") or json_sha != provenance.get("json_sha256"):
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", "derived SHA mismatch", status_code=409)
        try:
            decoded_text = markdown_bytes.decode("utf-8")
            json.loads(json_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", "derived Markdown/JSON invalid", status_code=409) from exc
        rows = member_manifest.get("members")
        if member_manifest.get("schema") != "UR_PLANE_C_C1_DOCUMENT_ARTIFACT_BUNDLE_MANIFEST_R001" or not isinstance(rows, list):
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", "member manifest invalid", status_code=409)
        row_map = {item.get("path"): item for item in rows if isinstance(item, dict)}
        for name, data in {
            original_member: original_bytes,
            "document.md": markdown_bytes,
            "document.json": json_bytes,
            "provenance.json": provenance_bytes,
        }.items():
            row = row_map.get(name)
            if not isinstance(row, dict) or row.get("bytes") != len(data) or row.get("sha256") != _sha256_bytes(data):
                raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", f"member manifest mismatch: {name}", status_code=409)
        parser_binding = provenance.get("parser_binding")
        if not isinstance(parser_binding, dict):
            raise WebContinuityError("INVALID_DOCUMENT_BUNDLE", "parser provenance missing", status_code=409)

        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="DOCUMENT_BUNDLE_SOURCE_ADOPT",
            scope={"project_id": project_id, "chat_id": chat_id},
            payload={
                "expected_project_revision": expected_project_revision,
                "document_bundle_sha256": bundle_sha,
                "document_input_sha256": provenance["input_sha256"],
                "document_markdown_sha256": markdown_sha,
                "filename": filename,
                "role": role,
            },
        )

        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if project["project_revision"] != expected_project_revision:
                if not (
                    project.get("last_command_id") == command_id
                    and project.get("last_input_fingerprint_sha256") == fingerprint
                ):
                    raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)
            if chat_id is not None:
                chat, _ = self._chat(chat_id)
                if chat["project_id"] != project_id:
                    raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)

            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            source_ref_id = _stable_id("SRC", project_id, command_id, bundle_sha, markdown_sha)
            source_ref_artifact_id = self._source_ref_artifact_id(source_ref_id)

            if self._record_exists(source_ref_artifact_id):
                source_ref, source_ref_binding = self._source_ref(source_ref_id)
                if source_ref.get("input_fingerprint_sha256") != fingerprint:
                    raise WebContinuityError("IDEMPOTENCY_CONFLICT", "existing document SourceRef conflicts", status_code=409)
                derivation, _ = self._load_current_json(source_ref["derived_projection_binding"]["artifact_id"])
                source_binding = source_ref["source_artifact_binding"]
                ingest_receipt, _ = self._load_current_json(source_ref["ingest_receipt_binding"]["artifact_id"])
            else:
                projection_identity = _sha256_bytes(
                    f"UR_WEB_DOCUMENT_SOURCE_PROJECTION_V1|{project_id}|{command_id}|{bundle_sha}|{markdown_sha}".encode("utf-8")
                )
                opaque_binding, opaque_manifest = self.store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=projection_identity,
                    artifact_bytes=markdown_bytes,
                    job_id=op_exec,
                    persistence_class=PersistenceClass.WORKING,
                    expected_artifact_sha256=markdown_sha,
                )
                _, projection_bytes = self.store.load_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=opaque_binding.artifact_identity_sha256,
                    artifact_revision=opaque_binding.artifact_revision,
                    artifact_sha256=opaque_binding.artifact_sha256,
                )
                if projection_bytes != markdown_bytes:
                    raise WebContinuityError("SOURCE_BYTE_MISMATCH", "Markdown projection changed after reload", status_code=500)
                source_binding = {
                    "artifact_id": opaque_manifest.artifact_id,
                    "artifact_identity_sha256": opaque_binding.artifact_identity_sha256,
                    "revision": opaque_binding.artifact_revision,
                    "sha256": opaque_binding.artifact_sha256,
                    "byte_size": len(markdown_bytes),
                    "media_type": "text/markdown",
                }

                derivation_record = {
                    "source_sha256": markdown_sha,
                    "decoder_id": "UR_DOCUMENT_MARKDOWN_PROJECTION",
                    "decoder_revision": "R001",
                    "selected_encoding": "utf-8",
                    "bom_status": "NONE",
                    "decoded_codepoint_count": len(decoded_text),
                    "line_count": decoded_text.count("\n") + 1,
                    "decoded_text": decoded_text,
                    "derivation_sha256": markdown_sha,
                    "warnings": [],
                    "replacements": 0,
                    "origin_document_bundle_binding": dict(document_bundle_binding),
                    "created_by_command_id": command_id,
                    "input_fingerprint_sha256": fingerprint,
                    "created_at_utc": _utc_now(),
                }
                derivation_artifact_id = "WEB_TEXT_DERIVATION_" + _artifact_suffix(source_ref_id)
                derivation, derivation_binding = self._persist_json_revision(
                    artifact_id=derivation_artifact_id,
                    namespace="derivations",
                    record=derivation_record,
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

                receipt_record = {
                    "source_artifact_binding": source_binding,
                    "document_bundle_binding": dict(document_bundle_binding),
                    "document_input_sha256": provenance["input_sha256"],
                    "document_input_format": input_format,
                    "document_original_byte_size": len(original_bytes),
                    "document_markdown_sha256": markdown_sha,
                    "document_json_sha256": json_sha,
                    "parser_binding": dict(parser_binding),
                    "selected_encoding": "utf-8",
                    "derivation_artifact_binding": derivation_binding,
                    "derivation_sha256": markdown_sha,
                    "network_used": False,
                    "model_used": False,
                    "ocr_used": False,
                    "result": "PASS",
                    "warnings": list(provenance.get("warnings") or []),
                    "errors": [],
                    "operation_execution_id": op_exec,
                    "formal_job": False,
                    "created_at_utc": _utc_now(),
                }
                ingest_receipt_artifact_id = "WEB_DOCUMENT_INGEST_RECEIPT_" + _artifact_suffix(source_ref_id)
                ingest_receipt, ingest_receipt_binding = self._persist_json_revision(
                    artifact_id=ingest_receipt_artifact_id,
                    namespace="ingest_receipts",
                    record=receipt_record,
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

                source_ref_record = {
                    "source_ref_id": source_ref_id,
                    "project_id": project_id,
                    "source_artifact_binding": source_binding,
                    "derived_projection_binding": derivation_binding,
                    "ingest_receipt_binding": ingest_receipt_binding,
                    "document_bundle_binding": dict(document_bundle_binding),
                    "origin_class": "PROJECT_DOCUMENT_BUNDLE",
                    "origin_media_type": "application/pdf"
                    if input_format == "pdf"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "origin_input_sha256": provenance["input_sha256"],
                    "filename": filename,
                    "role": role,
                    "created_by_command_id": command_id,
                    "input_fingerprint_sha256": fingerprint,
                    "created_at_utc": _utc_now(),
                }
                source_ref, source_ref_binding = self._persist_json_revision(
                    artifact_id=source_ref_artifact_id,
                    namespace="source_refs",
                    record=source_ref_record,
                    revision_field=None,
                    operation_execution_id=op_exec,
                )

            if source_ref_id not in project.get("source_ref_ids", []):
                project_next = dict(project)
                project_next["source_ref_ids"] = list(project.get("source_ref_ids", [])) + [source_ref_id]
                project_next["updated_at_utc"] = _utc_now()
                project_next["last_command_id"] = command_id
                project_next["last_input_fingerprint_sha256"] = fingerprint
                project, project_binding = self._persist_json_revision(
                    artifact_id=self._project_artifact_id(project_id),
                    namespace="projects",
                    record=project_next,
                    revision_field="project_revision",
                    operation_execution_id=op_exec,
                )
            else:
                project_binding = self._manifest_binding(
                    self.store.current_manifest(self._project_artifact_id(project_id))
                )

            produced = [
                project_binding,
                source_ref_binding,
                source_ref["source_artifact_binding"],
                source_ref["derived_projection_binding"],
                source_ref["ingest_receipt_binding"],
            ]
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="DOCUMENT_BUNDLE_SOURCE_ADOPT",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=None,
                source_ref_id=source_ref_id,
                source_sha256=source_binding["sha256"],
                derivation_sha256=derivation["derivation_sha256"],
                produced_artifacts=produced,
                extra={
                    "filename": filename,
                    "origin_class": "PROJECT_DOCUMENT_BUNDLE",
                    "document_bundle_sha256": bundle_sha,
                    "document_input_sha256": provenance["input_sha256"],
                    "document_input_format": input_format,
                    "projection_media_type": "text/markdown",
                },
            )
            response = {
                "project": project,
                "source_ref": source_ref,
                "text_derivation": derivation,
                "ingest_receipt": ingest_receipt,
                "document_bundle_binding": dict(document_bundle_binding),
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="DOCUMENT_BUNDLE_SOURCE_ADOPT",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response


    def verify_text_source(
        self,
        *,
        command_id: str,
        project_id: str,
        source_ref_id: str,
        chat_id: str | None = None,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        fingerprint = self._command_fingerprint(
            command_id=command_id,
            command_type="TEXT_SOURCE_VERIFY",
            scope={"project_id": project_id, "chat_id": chat_id, "source_ref_id": source_ref_id},
            payload={},
        )
        with self._lock:
            replay = self._load_idempotent_response(command_id, fingerprint)
            if replay is not None:
                return replay
            project, _ = self._project(project_id)
            if source_ref_id not in project.get("source_ref_ids", []):
                raise WebContinuityError("SOURCE_NOT_BOUND", "SourceRef is not bound to this Project", status_code=404)
            source_ref, _ = self._source_ref(source_ref_id)
            if source_ref["project_id"] != project_id:
                raise WebContinuityError("SCOPE_MISMATCH", "SourceRef project mismatch", status_code=409)
            source_binding = source_ref["source_artifact_binding"]
            try:
                _, source_bytes = self.store.load_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=source_binding["artifact_identity_sha256"],
                    artifact_revision=int(source_binding["revision"]),
                    artifact_sha256=source_binding["sha256"],
                )
            except Exception as exc:
                raise WebContinuityError("SOURCE_STALE_OR_TAMPERED", "source exact-byte binding failed", status_code=409) from exc
            if _sha256_bytes(source_bytes) != source_binding["sha256"]:
                raise WebContinuityError("SOURCE_STALE_OR_TAMPERED", "source SHA mismatch", status_code=409)
            derivation, _ = self._load_current_json(source_ref["derived_projection_binding"]["artifact_id"])
            if derivation["source_sha256"] != source_binding["sha256"]:
                raise WebContinuityError("DERIVATION_STALE", "TextDerivation source binding mismatch", status_code=409)
            op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
            receipt, receipt_binding = self._persist_operation_receipt(
                command_id=command_id,
                command_type="TEXT_SOURCE_VERIFY",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                project_id=project_id,
                project_revision=project["project_revision"],
                chat_id=chat_id,
                chat_revision=None,
                source_ref_id=source_ref_id,
                source_sha256=source_binding["sha256"],
                derivation_sha256=derivation["derivation_sha256"],
                produced_artifacts=[],
                extra={
                    "encoding": derivation["selected_encoding"],
                    "line_count": derivation["line_count"],
                    "source_byte_size": len(source_bytes),
                },
            )
            response = {
                "source_ref_id": source_ref_id,
                "source_sha256": source_binding["sha256"],
                "derivation_sha256": derivation["derivation_sha256"],
                "encoding": derivation["selected_encoding"],
                "line_count": derivation["line_count"],
                "formal_job": False,
                "operation": receipt,
                "operation_binding": receipt_binding,
            }
            self._persist_command_record(
                command_id=command_id,
                command_type="TEXT_SOURCE_VERIFY",
                input_fingerprint=fingerprint,
                operation_execution_id=op_exec,
                response=response,
            )
            return response


    # ---------- detached formal-model Web intake / projection ----------

    @staticmethod
    def _require_formal_binding(binding: dict[str, Any], field: str) -> dict[str, Any]:
        if not isinstance(binding, dict):
            raise WebContinuityError("INVALID_FORMAL_BINDING", f"{field} must be an exact binding")
        required = ("artifact_identity_sha256", "artifact_revision", "artifact_sha256")
        if any(key not in binding for key in required):
            raise WebContinuityError("INVALID_FORMAL_BINDING", f"{field} is incomplete")
        identity = binding.get("artifact_identity_sha256")
        revision = binding.get("artifact_revision")
        sha256 = binding.get("artifact_sha256")
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
            raise WebContinuityError("INVALID_FORMAL_BINDING", f"{field}.artifact_identity_sha256 invalid")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise WebContinuityError("INVALID_FORMAL_BINDING", f"{field}.artifact_revision invalid")
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise WebContinuityError("INVALID_FORMAL_BINDING", f"{field}.artifact_sha256 invalid")
        return dict(binding)

    def bind_formal_job_intake(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        initiating_user_event_id: str,
        expected_chat_revision: int,
        expected_head_event_id: str,
        job_id: str,
        job_bundle_binding: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the detached exact Web->FormalJob intake binding.

        The existing USER_MESSAGE is immutable. This method neither creates Job authority nor
        consumes Human approval; it only binds exact current Web turn state to an already
        immutable Runtime JobBundle.
        """
        command_id = _validate_command_id(command_id)
        if not isinstance(project_id, str) or not project_id:
            raise WebContinuityError("INVALID_INPUT", "project_id required")
        if not isinstance(chat_id, str) or not chat_id:
            raise WebContinuityError("INVALID_INPUT", "chat_id required")
        if not isinstance(initiating_user_event_id, str) or not initiating_user_event_id:
            raise WebContinuityError("INVALID_INPUT", "initiating_user_event_id required")
        if not isinstance(job_id, str) or not job_id:
            raise WebContinuityError("INVALID_INPUT", "job_id required")
        if isinstance(expected_chat_revision, bool) or not isinstance(expected_chat_revision, int) or expected_chat_revision < 1:
            raise WebContinuityError("INVALID_INPUT", "expected_chat_revision must be positive")
        if expected_head_event_id != initiating_user_event_id:
            raise WebContinuityError("STALE_CHAT", "formal intake must target initiating USER_MESSAGE head", status_code=409)
        job_bundle_binding = self._require_formal_binding(job_bundle_binding, "job_bundle_binding")
        ledger = FormalModelJobLedger(self.store)

        try:
            job_bundle_record = ledger.load_record(job_bundle_binding)
        except FormalModelJobError as exc:
            raise WebContinuityError("FORMAL_JOB_STALE_OR_TAMPERED", str(exc), status_code=409) from exc
        if job_bundle_record.get("schema") != "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1":
            raise WebContinuityError("INVALID_FORMAL_JOB", "binding is not an immutable JobBundle", status_code=409)
        if job_bundle_record.get("job_id") != job_id:
            raise WebContinuityError("FORMAL_JOB_MISMATCH", "JobBundle belongs to another Job", status_code=409)
        job_bundle_sha256 = job_bundle_record.get("job_bundle_sha256")
        if not isinstance(job_bundle_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", job_bundle_sha256) is None:
            raise WebContinuityError("INVALID_FORMAL_JOB", "JobBundle SHA invalid", status_code=409)

        with self._lock:
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            if chat.get("chat_revision") != expected_chat_revision or chat.get("head_event_id") != expected_head_event_id:
                raise WebContinuityError("STALE_CHAT", "exact Web chat head changed before formal intake", status_code=409)
            event, event_binding = self._load_current_json(self._event_artifact_id(initiating_user_event_id))
            if (
                event.get("event_id") != initiating_user_event_id
                or event.get("chat_id") != chat_id
                or event.get("event_type") != "USER_MESSAGE"
                or event.get("actor_class") != "USER"
                or event.get("content_sha256") is None
            ):
                raise WebContinuityError("INVALID_USER_EVENT", "exact initiating USER_MESSAGE required", status_code=409)
            if event.get("parent_event_id") != job_bundle_record.get("job_bundle", {}).get("initiating_parent_event_id"):
                # Legacy/general-chat JobBundle may not expose this optional helper field; exact
                # user-event binding below remains authoritative when absent.
                if "initiating_parent_event_id" in job_bundle_record.get("job_bundle", {}):
                    raise WebContinuityError("FORMAL_JOB_MISMATCH", "JobBundle parent event differs", status_code=409)
            try:
                intake_record, intake_binding = ledger.persist_intake_binding(
                    project_id=project_id,
                    chat_id=chat_id,
                    initiating_command_id=command_id,
                    initiating_user_event_id=initiating_user_event_id,
                    initiating_user_event_binding=event_binding,
                    initiating_content_sha256=event["content_sha256"],
                    accepted_chat_revision=expected_chat_revision,
                    accepted_head_event_id=expected_head_event_id,
                    parent_event_id=event.get("parent_event_id"),
                    job_id=job_id,
                    job_bundle_sha256=job_bundle_sha256,
                )
            except FormalModelJobError as exc:
                raise WebContinuityError("FORMAL_INTAKE_REJECTED", str(exc), status_code=409) from exc
            return {
                "status": "PASS_WEB_FORMAL_JOB_INTAKE_BINDING_R001",
                "project_id": project_id,
                "chat_id": chat_id,
                "chat": chat,
                "initiating_user_event": event,
                "initiating_user_event_binding": event_binding,
                "intake_binding_record": intake_record,
                "intake_binding": intake_binding,
                "formal_job_executed": False,
                "model_provider_call": False,
                "network_call": False,
            }

    def project_formal_result(
        self,
        *,
        command_id: str,
        project_id: str,
        chat_id: str,
        intake_binding: dict[str, Any],
        formal_result_commit_binding: dict[str, Any],
    ) -> dict[str, Any]:
        """Project one already-committed Runtime formal result into the exact Web chat.

        Projection is not formal-result authority. If the chat moved, the Runtime formal commit
        is preserved and no assistant event is attached to the newer turn.
        """
        command_id = _validate_command_id(command_id)
        intake_binding = self._require_formal_binding(intake_binding, "intake_binding")
        formal_result_commit_binding = self._require_formal_binding(
            formal_result_commit_binding, "formal_result_commit_binding"
        )
        ledger = FormalModelJobLedger(self.store)
        try:
            intake = ledger.load_record(intake_binding)
            formal_result = ledger.load_record(formal_result_commit_binding)
        except FormalModelJobError as exc:
            raise WebContinuityError("FORMAL_RESULT_STALE_OR_TAMPERED", str(exc), status_code=409) from exc
        if intake.get("schema") != "WEB_FORMAL_JOB_INTAKE_BINDING_V1":
            raise WebContinuityError("INVALID_FORMAL_INTAKE", "binding is not Web formal intake", status_code=409)
        if formal_result.get("schema") != "RUNTIME_FORMAL_MODEL_RESULT_COMMIT_RECEIPT_V1":
            raise WebContinuityError("INVALID_FORMAL_RESULT", "binding is not Runtime formal result commit", status_code=409)
        if intake.get("project_id") != project_id or intake.get("chat_id") != chat_id:
            raise WebContinuityError("SCOPE_MISMATCH", "formal intake project/chat mismatch", status_code=409)
        job_id = intake.get("job_id")
        if not isinstance(job_id, str) or not job_id or formal_result.get("job_id") != job_id:
            raise WebContinuityError("FORMAL_JOB_MISMATCH", "formal result job differs from intake", status_code=409)
        if formal_result.get("job_bundle_sha256") != intake.get("job_bundle_sha256"):
            raise WebContinuityError("FORMAL_JOB_MISMATCH", "formal result JobBundle differs from intake", status_code=409)
        if formal_result.get("web_formal_job_intake_binding_sha256") != intake_binding["artifact_sha256"]:
            raise WebContinuityError("FORMAL_INTAKE_MISMATCH", "formal result does not bind exact intake", status_code=409)
        try:
            assistant_text = ledger.load_assistant_output_text(formal_result)
        except FormalModelJobError as exc:
            raise WebContinuityError("FORMAL_OUTPUT_STALE_OR_TAMPERED", str(exc), status_code=409) from exc
        assistant_content_sha256 = _sha256_bytes(assistant_text.encode("utf-8"))
        if assistant_content_sha256 != formal_result.get("assistant_content_sha256"):
            raise WebContinuityError("FORMAL_OUTPUT_MISMATCH", "assistant content differs from formal commit", status_code=409)

        initiating_event_id = intake.get("initiating_user_event_id")
        expected_revision = intake.get("accepted_chat_revision")
        expected_head = intake.get("accepted_head_event_id")
        if initiating_event_id != expected_head:
            raise WebContinuityError("INVALID_FORMAL_INTAKE", "accepted head must be initiating USER_MESSAGE", status_code=409)
        assistant_event_id = _stable_id(
            "EVT",
            chat_id,
            job_id,
            formal_result["formal_result_commit_id"],
            "ASSISTANT_MESSAGE",
        )
        assistant_artifact_id = self._event_artifact_id(assistant_event_id)
        receipt_id = _stable_id(
            "PROJ",
            project_id,
            chat_id,
            intake_binding["artifact_sha256"],
            formal_result_commit_binding["artifact_sha256"],
        )

        with self._lock:
            project, _ = self._project(project_id)
            chat, _ = self._chat(chat_id)
            if chat.get("project_id") != project_id or chat_id not in project.get("chat_ids", []):
                raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
            initiating_event, initiating_binding = self._load_current_json(self._event_artifact_id(initiating_event_id))
            if (
                initiating_event.get("event_id") != initiating_event_id
                or initiating_event.get("event_type") != "USER_MESSAGE"
                or initiating_event.get("chat_id") != chat_id
                or initiating_event.get("content_sha256") != intake.get("initiating_content_sha256")
                or initiating_binding.get("artifact_id") != intake.get("initiating_user_event_artifact_id")
                or initiating_binding.get("revision") != intake.get("initiating_user_event_artifact_revision")
                or initiating_binding.get("sha256") != intake.get("initiating_user_event_artifact_sha256")
            ):
                raise WebContinuityError("FORMAL_INTAKE_STALE_OR_TAMPERED", "initiating USER_MESSAGE differs from exact intake", status_code=409)

            event_exists = self._record_exists(assistant_artifact_id)
            assistant_event = None
            assistant_binding = None
            if event_exists:
                assistant_event, assistant_binding = self._load_current_json(assistant_artifact_id)
                expected_event = {
                    "event_id": assistant_event_id,
                    "chat_id": chat_id,
                    "event_type": "ASSISTANT_MESSAGE",
                    "actor_class": "ASSISTANT",
                    "content_sha256": assistant_content_sha256,
                    "content": assistant_text,
                    "parent_event_id": initiating_event_id,
                    "related_job_id": job_id,
                }
                for key, value in expected_event.items():
                    if assistant_event.get(key) != value:
                        raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "existing assistant projection conflicts", status_code=500)
                expected_sequence = initiating_event.get("event_sequence_1_based") + 1
                if assistant_event.get("event_sequence_1_based") != expected_sequence:
                    raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "existing assistant sequence conflicts", status_code=500)

            already_in_chat = event_exists and assistant_event_id in chat.get("event_ids", [])
            if already_in_chat:
                if chat.get("head_event_id") != assistant_event_id:
                    raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "projected assistant event is not chat head", status_code=500)
                projection_status = "PROJECTED"
                observed_revision = expected_revision
                observed_head = expected_head
                resulting_chat = chat
            else:
                observed_revision = chat.get("chat_revision")
                observed_head = chat.get("head_event_id")
                exact_preprojection = observed_revision == expected_revision and observed_head == expected_head
                if not exact_preprojection:
                    projection_status = "RESULT_COMMITTED_PROJECTION_BLOCKED_STALE_CHAT"
                    resulting_chat = chat
                else:
                    op_exec = self._operation_execution_id(project_id=project_id, chat_id=chat_id, command_id=command_id)
                    if assistant_event is None:
                        assistant_event, assistant_binding = self._persist_json_revision(
                            artifact_id=assistant_artifact_id,
                            namespace="events",
                            record={
                                "event_id": assistant_event_id,
                                "chat_id": chat_id,
                                "event_sequence_1_based": initiating_event["event_sequence_1_based"] + 1,
                                "event_type": "ASSISTANT_MESSAGE",
                                "actor_class": "ASSISTANT",
                                "content_sha256": assistant_content_sha256,
                                "content": assistant_text,
                                "parent_event_id": initiating_event_id,
                                "related_job_id": job_id,
                                "related_source_ref_ids": [],
                                "created_at_utc": _utc_now(),
                            },
                            revision_field=None,
                            operation_execution_id=op_exec,
                        )
                    chat_next = dict(chat)
                    chat_next["event_ids"] = list(chat.get("event_ids", [])) + [assistant_event_id]
                    chat_next["head_event_id"] = assistant_event_id
                    chat_next["updated_at_utc"] = _utc_now()
                    chat_next["last_command_id"] = command_id
                    chat_next["last_input_fingerprint_sha256"] = _sha256_bytes(
                        _canonical_json_bytes(
                            {
                                "command_id": command_id,
                                "formal_result_commit_sha256": formal_result_commit_binding["artifact_sha256"],
                                "intake_binding_sha256": intake_binding["artifact_sha256"],
                            }
                        )
                    )
                    resulting_chat, _ = self._persist_json_revision(
                        artifact_id=self._chat_artifact_id(chat_id),
                        namespace="chats",
                        record=chat_next,
                        revision_field="chat_revision",
                        operation_execution_id=op_exec,
                    )
                    projection_status = "PROJECTED"

            receipt = {
                "schema": "WEB_FORMAL_RESULT_PROJECTION_RECEIPT_V1",
                "projection_receipt_id": receipt_id,
                "project_id": project_id,
                "chat_id": chat_id,
                "web_formal_job_intake_binding_id": intake.get("web_formal_job_intake_binding_id"),
                "web_formal_job_intake_binding_sha256": intake_binding["artifact_sha256"],
                "formal_result_commit_id": formal_result.get("formal_result_commit_id"),
                "formal_result_commit_receipt_sha256": formal_result_commit_binding["artifact_sha256"],
                "job_id": job_id,
                "job_bundle_sha256": intake.get("job_bundle_sha256"),
                "expected_pre_projection_chat_revision": expected_revision,
                "expected_pre_projection_head_event_id": expected_head,
                "observed_pre_projection_chat_revision": observed_revision,
                "observed_pre_projection_head_event_id": observed_head,
                "projection_status": projection_status,
                "projection_command_id": command_id,
                "projected_at_utc": _utc_now(),
            }
            if projection_status == "PROJECTED":
                if assistant_event is None or assistant_binding is None:
                    raise WebContinuityError("CORRUPT_RUNTIME_RECORD", "assistant projection evidence missing", status_code=500)
                receipt.update(
                    {
                        "assistant_event_id": assistant_event_id,
                        "assistant_event_artifact_identity_sha256": legacy_artifact_identity_sha256(
                            assistant_binding["artifact_id"]
                        ),
                        "assistant_event_artifact_revision": assistant_binding["revision"],
                        "assistant_event_artifact_sha256": assistant_binding["sha256"],
                        "assistant_content_sha256": assistant_content_sha256,
                        "assistant_parent_event_id": initiating_event_id,
                        "resulting_chat_revision": resulting_chat["chat_revision"],
                        "resulting_head_event_id": resulting_chat["head_event_id"],
                    }
                )
            try:
                persisted_receipt, receipt_binding, disposition = ledger.persist_projection_receipt_once(
                    job_id=job_id,
                    receipt_id=receipt_id,
                    receipt=receipt,
                )
            except FormalModelJobError as exc:
                raise WebContinuityError("FORMAL_PROJECTION_REJECTED", str(exc), status_code=409) from exc
            return {
                "status": projection_status,
                "formal_result_preserved": True,
                "chat": resulting_chat,
                "assistant_event": assistant_event if projection_status == "PROJECTED" else None,
                "projection_receipt": persisted_receipt,
                "projection_receipt_binding": receipt_binding,
                "projection_disposition": disposition,
            }

    # ---------- resume ----------

    def _project_operation_receipts(self, project_id: str) -> list[dict[str, Any]]:
        """Reproject exact persisted M001-A operation receipts for one Project.

        This is a bounded read-only projection over the existing Runtime ArtifactStore
        manifest namespace.  It is not a second operation store or authoritative index.
        """
        manifest_root = self.store.root / "_manifests"
        if not manifest_root.exists():
            return []
        operations: list[dict[str, Any]] = []
        project_prefix = self._operation_namespace_prefix(project_id)
        for manifest_dir in sorted(manifest_root.glob(project_prefix + "*"), key=lambda p: p.name):
            if not manifest_dir.is_dir():
                continue
            artifact_id = manifest_dir.name
            # Project scoping is resolved from the deterministic Artifact namespace
            # before any currentness read/validation of the operation record.
            record, binding = self._load_current_json(artifact_id)
            if record.get("project_id") != project_id:
                raise WebContinuityError(
                    "CORRUPT_RUNTIME_RECORD",
                    f"{artifact_id} project binding does not match its scoped operation namespace",
                    status_code=500,
                )
            if record.get("formal_job") is not False:
                raise WebContinuityError(
                    "CORRUPT_RUNTIME_RECORD",
                    f"{artifact_id} must remain a non-formal M001-A operation",
                    status_code=500,
                )
            operation_execution_id = record.get("operation_execution_id")
            if not isinstance(operation_execution_id, str) or not operation_execution_id.startswith("WEBOP_"):
                raise WebContinuityError(
                    "CORRUPT_RUNTIME_RECORD",
                    f"{artifact_id} has invalid WEBOP provenance",
                    status_code=500,
                )
            operations.append({"operation": record, "binding": binding})
        operations.sort(
            key=lambda item: (
                item["operation"].get("created_at_utc", ""),
                item["operation"].get("operation_id", ""),
            )
        )
        return operations

    def resume_project(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            project, project_binding = self._project(project_id)
            instructions = self._load_exact_text_binding(project["project_instruction_binding"])
            chats = []
            for chat_id in project.get("chat_ids", []):
                chat, chat_binding = self._chat(chat_id, include_deleted=True)
                if self._chat_lifecycle_state(chat) == "DELETED":
                    continue
                events = []
                for event_id in chat.get("event_ids", []):
                    event, event_binding = self._load_current_json(self._event_artifact_id(event_id))
                    events.append({"event": event, "binding": event_binding})
                chats.append({"chat": chat, "binding": chat_binding, "events": events})
            sources = []
            for source_ref_id in project.get("source_ref_ids", []):
                source_ref, source_ref_binding = self._source_ref(source_ref_id)
                derivation, derivation_binding = self._load_current_json(source_ref["derived_projection_binding"]["artifact_id"])
                ingest_receipt, ingest_binding = self._load_current_json(source_ref["ingest_receipt_binding"]["artifact_id"])
                sources.append(
                    {
                        "source_ref": source_ref,
                        "binding": source_ref_binding,
                        "text_derivation": derivation,
                        "derivation_binding": derivation_binding,
                        "ingest_receipt": ingest_receipt,
                        "ingest_binding": ingest_binding,
                    }
                )
            operations = self._project_operation_receipts(project_id)
            operation_refs = [
                {
                    "operation_id": item["operation"].get("operation_id"),
                    "operation_execution_id": item["operation"].get("operation_execution_id"),
                    "operation_type": item["operation"].get("operation_type"),
                    "binding": item["binding"],
                    "authority_class": "NON_AUTHORITY_PROJECTION_REF",
                }
                for item in operations
            ]
            working_state = {
                "project_id": project_id,
                "authority_class": "NON_AUTHORITY_DERIVED",
                "derived_from_project_revision": project["project_revision"],
                "chat_heads": [
                    {"chat_id": item["chat"]["chat_id"], "head_event_id": item["chat"]["head_event_id"]}
                    for item in chats
                ],
                "source_ref_ids": list(project.get("source_ref_ids", [])),
                "operation_refs": operation_refs,
                "runtime_binding": {
                    "base_runtime_tree_sha256": self.base_runtime_tree_sha256,
                    "web_contract_sha256": self.web_contract_sha256,
                },
                "generated_at_utc": _utc_now(),
            }
            return {
                "project": project,
                "project_binding": project_binding,
                "project_instructions": instructions,
                "chats": chats,
                "sources": sources,
                "operations": operations,
                "project_working_state": working_state,
            }
