"""R010 minimum owner-local Job Authority source implementation candidate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
import uuid

from .artifact_store import ArtifactStore, R009OpaqueArtifactBinding
from .hashing import sha256_bytes


class JobAuthorityError(ValueError):
    pass


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JAE_RE = re.compile(r"^JAE_[0-9a-f]{64}$")
_JXS_RE = re.compile(r"^JXS_[0-9a-f]{64}$")
_ADE_RE = re.compile(r"^ADE_[0-9a-f]{64}$")
_ALLOWED_BRANCH_CODES = {
    "DRE_ISSUANCE_SELECTED",
    "PRE_DRE_SUPERSESSION_SELECTED",
    "PRE_DRE_CANCEL_SELECTED",
}
_V2_CONTROLLED = {"CONTROLLED_SUCCESSOR_AFTER_PREDECESSOR_INVALIDATION"}
_V3_CONTROLLED = {
    "CONTROLLED_SUCCESSOR_AFTER_PRE_DRE_SUPERSESSION",
    "CONTROLLED_SUCCESSOR_AFTER_DRE_NON_APPROVAL_TERMINAL",
}
_ALLOWED_INTENT_SCHEMAS = {
    "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
    "RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2",
}
_CONTROLLED_SUCCESSOR_REOPEN_CODES = {
    "CONTROLLED_REOPEN_MATERIAL_INPUT_CHANGE",
    "CONTROLLED_REOPEN_RUNTIME_MIGRATION",
}
_CONTROLLED_SUCCESSOR_ISSUANCE_STAGES = {
    "ACTIVE_PREDECESSOR_NO_DRE",
    "DRE_PENDING_NO_TERMINAL_DECISION",
    "APPROVED_SLOT_UNCLAIMED",
}

_ALLOWED_PREAPP_STAGES = {
    "ACTIVE_PREDECESSOR_NO_DRE",
    "DRE_PENDING_NO_TERMINAL_DECISION",
}


_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")

_V3_FIELDS = frozenset({
    "schema",
    "snapshot_decision_request_key_sha256",
    "decision_request_event_id",
    "job_authority_event_id",
    "job_execution_authority_snapshot_id",
    "job_execution_authority_snapshot_sha256",
    "job_execution_authority_snapshot_artifact_identity_sha256",
    "job_execution_authority_snapshot_artifact_revision",
    "job_execution_authority_snapshot_artifact_sha256",
    "job_execution_snapshot_registration_sha256",
    "job_execution_snapshot_registration_artifact_identity_sha256",
    "job_execution_snapshot_registration_artifact_revision",
    "job_execution_snapshot_registration_artifact_sha256",
    "decision_request_content_sha256",
    "decision_request_content_artifact_identity_sha256",
    "decision_request_content_artifact_revision",
    "decision_request_content_artifact_sha256",
    "decision_scope_sha256",
    "live_attempts_max",
    "model_calls_max",
    "network_calls_max",
    "retries_max",
    "fallback_allowed",
})

_REG_V2_FIELDS = frozenset({
    "schema","registration_revision","job_authority_event_id","job_authority_binding_sha256",
    "job_execution_authority_snapshot_id","job_execution_authority_snapshot_sha256",
    "job_execution_authority_snapshot_artifact_identity_sha256",
    "job_execution_authority_snapshot_artifact_revision",
    "job_execution_authority_snapshot_artifact_sha256",
    "activation_basis","predecessor_approval_slot_key_sha256","predecessor_invalidation_sha256",
    "job_transition_intent_sha256","state",
})

_REG_V3_FIELDS = frozenset({
    "schema","registration_revision","job_authority_event_id","job_authority_binding_sha256",
    "job_execution_authority_snapshot_id","job_execution_authority_snapshot_sha256",
    "job_execution_authority_snapshot_artifact_identity_sha256",
    "job_execution_authority_snapshot_artifact_revision",
    "job_execution_authority_snapshot_artifact_sha256","activation_basis",
    "predecessor_job_authority_event_id","predecessor_job_execution_authority_snapshot_id",
    "predecessor_job_execution_authority_snapshot_sha256",
    "predecessor_job_execution_snapshot_registration_sha256",
    "preapproval_branch_key_sha256","preapproval_branch_selection_semantic_sha256",
    "preapproval_branch_selection_artifact_identity_sha256",
    "preapproval_branch_selection_artifact_revision","preapproval_branch_selection_artifact_sha256",
    "preapproval_transition_intent_sha256","preapproval_transition_intent_artifact_identity_sha256",
    "preapproval_transition_intent_artifact_revision","preapproval_transition_intent_artifact_sha256",
    "predecessor_decision_request_event_id","predecessor_decision_request_identity_sha256",
    "predecessor_nonapproval_terminal_binding_sha256",
    "predecessor_nonapproval_terminal_artifact_identity_sha256",
    "predecessor_nonapproval_terminal_artifact_revision",
    "predecessor_nonapproval_terminal_artifact_sha256",
    "predecessor_approval_slot_key_sha256","predecessor_invalidation_sha256","state",
})

_PREAPP_INTENT_V1_FIELDS = frozenset({
    "schema","predecessor_stage","transition_code","predecessor_job_authority_event_id",
    "predecessor_job_execution_authority_snapshot_id","predecessor_job_execution_authority_snapshot_sha256",
    "predecessor_job_execution_snapshot_registration_sha256","predecessor_decision_request_event_id",
    "predecessor_decision_request_identity_sha256","successor_job_authority_event_id",
    "successor_job_authority_binding_sha256","successor_job_execution_authority_snapshot_id",
    "successor_job_execution_authority_snapshot_sha256",
    "successor_job_execution_authority_snapshot_artifact_identity_sha256",
    "successor_job_execution_authority_snapshot_artifact_revision",
    "successor_job_execution_authority_snapshot_artifact_sha256",
    "successor_preparation_state","successor_activation_required",
})

_APPROVAL_DECISION_V3_FIELDS = frozenset({
    "schema","approval_decision_event_id","job_authority_event_id","job_execution_authority_snapshot_id",
    "job_execution_authority_snapshot_sha256","job_execution_authority_snapshot_artifact_identity_sha256",
    "job_execution_authority_snapshot_artifact_revision","job_execution_authority_snapshot_artifact_sha256",
    "job_execution_snapshot_registration_sha256","decision_request_event_id",
    "snapshot_decision_request_key_sha256","decision_request_identity_sha256","decision_request_content_sha256",
    "decision_request_content_artifact_identity_sha256","decision_request_content_artifact_revision",
    "decision_request_content_artifact_sha256","human_action_receipt_sha256",
    "human_action_receipt_artifact_identity_sha256","human_action_receipt_artifact_revision",
    "human_action_receipt_artifact_sha256","decision_scope_sha256","decision_code",
    "live_attempts_max","model_calls_max","network_calls_max","retries_max","fallback_allowed",
})

_BRANCH_V2_FIELDS = frozenset({
    "schema","preapproval_branch_key_sha256","branch_code",
    "predecessor_job_authority_event_id","predecessor_job_execution_authority_snapshot_id",
    "predecessor_job_execution_authority_snapshot_sha256",
    "predecessor_job_execution_snapshot_registration_sha256",
    "snapshot_decision_request_key_sha256","decision_request_event_id",
    "decision_request_identity_sha256","request_recovery_mode","decision_request_binding_v3",
})

_BRANCH_V1_FIELDS = frozenset({
    "schema","preapproval_branch_key_sha256","branch_code",
    "predecessor_job_authority_event_id","predecessor_job_execution_authority_snapshot_id",
    "predecessor_job_execution_authority_snapshot_sha256",
    "predecessor_job_execution_snapshot_registration_sha256",
    "snapshot_decision_request_key_sha256","decision_request_event_id",
    "decision_request_identity_sha256","decision_request_content_sha256",
    "preapproval_transition_intent_sha256",
    "preapproval_transition_intent_artifact_identity_sha256",
    "preapproval_transition_intent_artifact_revision",
    "preapproval_transition_intent_artifact_sha256",
    "successor_job_authority_event_id","successor_job_execution_authority_snapshot_id",
    "successor_job_execution_authority_snapshot_sha256",
    "successor_job_execution_authority_snapshot_artifact_identity_sha256",
    "successor_job_execution_authority_snapshot_artifact_revision",
    "successor_job_execution_authority_snapshot_artifact_sha256",
})

_JOB_SOURCE_FIELDS = {
    "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_SOURCE_RECORD_V1": frozenset({
        "schema",
        "source_record_revision",
        "lineage_namespace",
        "job_id",
        "job_bundle_sha256",
        "job_bundle_artifact_identity_sha256",
        "job_bundle_artifact_revision",
        "job_bundle_artifact_sha256",
        "web_formal_job_intake_binding_sha256",
        "web_formal_job_intake_artifact_identity_sha256",
        "web_formal_job_intake_artifact_revision",
        "web_formal_job_intake_artifact_sha256",
        "input_set_sha256",
        "input_set_artifact_identity_sha256",
        "input_set_artifact_revision",
        "input_set_artifact_sha256",
        "job_lineage_identity_sha256",
        "job_authority_event_id",
        "state",
        "committed_at_utc",
    }),
    "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","controlled_successor_jae_issuance_key_sha256",
        "transition_intent_schema","transition_stage","transition_code",
        "predecessor_job_authority_event_id","predecessor_job_execution_authority_snapshot_id",
        "predecessor_job_execution_authority_snapshot_sha256",
        "predecessor_job_execution_snapshot_registration_sha256",
        "predecessor_snapshot_artifact_identity_sha256","predecessor_snapshot_artifact_revision",
        "predecessor_snapshot_artifact_sha256",
        "predecessor_registration_artifact_identity_sha256","predecessor_registration_artifact_revision",
        "predecessor_registration_artifact_sha256",
        "stage_anchor_sha256",
        "preapproval_branch_key_sha256","preapproval_branch_selection_semantic_sha256",
        "preapproval_branch_selection_artifact_identity_sha256",
        "preapproval_branch_selection_artifact_revision","preapproval_branch_selection_artifact_sha256",
        "predecessor_decision_request_event_id","predecessor_decision_request_identity_sha256",
        "predecessor_approval_decision_event_id","predecessor_approval_slot_key_sha256",
        "predecessor_approval_artifact_identity_sha256","predecessor_approval_artifact_revision",
        "predecessor_approval_artifact_sha256",
        "job_lineage_identity_sha256","successor_job_authority_event_id","state","committed_at_utc",
    }),
    "RUNTIME_JOB_AUTHORITY_REGISTRATION_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","job_authority_event_id","job_execution_authority_snapshot_id",
        "job_execution_authority_snapshot_sha256","registration_sha256",
        "registration_artifact_identity_sha256","registration_artifact_revision",
        "registration_artifact_sha256","state","committed_at_utc",
    }),
    "RUNTIME_JOB_AUTHORITY_PREAPPROVAL_BRANCH_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","preapproval_branch_key_sha256","branch_code",
        "branch_selection_semantic_sha256","branch_artifact_identity_sha256",
        "branch_artifact_revision","branch_artifact_sha256","committed_at_utc",
    }),
    "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","successor_job_authority_event_id",
        "successor_job_execution_authority_snapshot_id","successor_job_execution_authority_snapshot_sha256",
        "successor_snapshot_artifact_identity_sha256","successor_snapshot_artifact_revision",
        "successor_snapshot_artifact_sha256","transition_intent_schema","transition_intent_sha256",
        "transition_intent_artifact_identity_sha256","transition_intent_artifact_revision",
        "transition_intent_artifact_sha256","state","committed_at_utc",
    }),
    "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V2": frozenset({
        "schema","source_record_revision","successor_job_authority_event_id",
        "controlled_successor_jae_issuance_key_sha256",
        "controlled_successor_jae_issuance_source_record_sha256",
        "successor_job_execution_authority_snapshot_id","successor_job_execution_authority_snapshot_sha256",
        "successor_snapshot_artifact_identity_sha256","successor_snapshot_artifact_revision",
        "successor_snapshot_artifact_sha256","transition_intent_schema","transition_intent_sha256",
        "transition_intent_artifact_identity_sha256","transition_intent_artifact_revision",
        "transition_intent_artifact_sha256","state","committed_at_utc",
    }),
    "RUNTIME_JOB_AUTHORITY_APPROVAL_EXECUTION_SLOT_TERMINAL_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","approval_slot_key_sha256",
        "job_authority_event_id","approval_decision_event_id","terminal_outcome",
        "attempt_claim_id","formal_job_execution_binding_sha256",
        "job_model_execution_grant_sha256",
        "successor_job_authority_event_id","successor_job_execution_authority_snapshot_id",
        "successor_job_execution_authority_snapshot_sha256","job_transition_intent_sha256",
        "invalidation_reason_code","state","committed_at_utc",
    }),
}


def _exact_fields(obj: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(obj)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise JobAuthorityError(f"{label} exact field-set mismatch missing={missing} extra={extra}")


def _validate_preapproval_transition_stage_matrix(
    intent: dict[str, Any],
    *,
    expected_stage: str | None = None,
    expected_dre_event_id: str | None = None,
    expected_dre_identity_sha256: str | None = None,
    label: str = "preapproval transition intent",
) -> str:
    _exact_fields(intent, _PREAPP_INTENT_V1_FIELDS, label)
    if intent.get("schema") != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1":
        raise JobAuthorityError(f"{label} schema mismatch")

    stage = intent.get("predecessor_stage")
    if stage not in _ALLOWED_PREAPP_STAGES:
        raise JobAuthorityError(f"{label} predecessor_stage invalid")

    if expected_stage is not None and stage != expected_stage:
        raise JobAuthorityError(f"{label} stage mismatch expected={expected_stage} actual={stage}")

    dre_event = intent.get("predecessor_decision_request_event_id")
    dre_identity = intent.get("predecessor_decision_request_identity_sha256")

    if stage == "ACTIVE_PREDECESSOR_NO_DRE":
        if dre_event is not None or dre_identity is not None:
            raise JobAuthorityError(f"{label} ACTIVE_PREDECESSOR_NO_DRE requires null DRE fields")
        if expected_dre_event_id is not None or expected_dre_identity_sha256 is not None:
            raise JobAuthorityError(f"{label} ACTIVE_PREDECESSOR_NO_DRE conflicts with selected DRE evidence")
    else:
        if not isinstance(dre_event, str) or re.fullmatch(r"DRE_[0-9a-f]{64}", dre_event) is None:
            raise JobAuthorityError(f"{label} DRE_PENDING requires exact predecessor DRE")
        _sha(dre_identity, f"{label} predecessor DRE identity")
        if (expected_dre_event_id is None) != (expected_dre_identity_sha256 is None):
            raise JobAuthorityError(f"{label} expected DRE evidence mixed nullability")
        if expected_dre_event_id is not None:
            if dre_event != expected_dre_event_id or dre_identity != expected_dre_identity_sha256:
                raise JobAuthorityError(f"{label} predecessor DRE does not exact-bind selected DRE evidence")

    return stage


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _lex(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError as exc:
        raise JobAuthorityError(f"cannot lstat path: {path}") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_chain(root: Path, target: Path) -> None:
    root = _lex(root)
    target = _lex(target)
    if not _inside(target, root):
        raise JobAuthorityError("path escapes Job Authority root")
    current = root
    if current.exists() and _reparse(current):
        raise JobAuthorityError("Job Authority root is redirected")
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and _reparse(current):
            raise JobAuthorityError(f"reparse/symlink path forbidden: {current}")


def _sha(v: Any, name: str) -> str:
    if not isinstance(v, str) or _SHA256_RE.fullmatch(v) is None:
        raise JobAuthorityError(f"{name} must be lowercase 64-hex")
    return v


def _jae(v: Any) -> str:
    if not isinstance(v, str) or _JAE_RE.fullmatch(v) is None:
        raise JobAuthorityError("JAE is invalid")
    return v


def _jxs(v: Any) -> str:
    if not isinstance(v, str) or _JXS_RE.fullmatch(v) is None:
        raise JobAuthorityError("JXS is invalid")
    return v


def _json(data: bytes, label: str) -> dict[str, Any]:
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise JobAuthorityError(f"{label} is not JSON") from exc
    if not isinstance(obj, dict) or _canonical(obj) != data:
        raise JobAuthorityError(f"{label} is not exact canonical JSON")
    return obj


class JobAuthorityRegistry:
    def __init__(self, runtime_authority_data_root: Path, artifact_store: ArtifactStore):
        self.runtime_authority_data_root = _lex(runtime_authority_data_root)
        self.artifact_store = artifact_store
        self.root = self.runtime_authority_data_root / "_authoritative" / "job_authority_registry"

    def _ensure_root(self) -> None:
        self.runtime_authority_data_root.mkdir(parents=True, exist_ok=True)
        _safe_chain(self.runtime_authority_data_root, self.runtime_authority_data_root)
        self.root.parent.mkdir(parents=True, exist_ok=True)
        _safe_chain(self.runtime_authority_data_root, self.root.parent)
        self.root.mkdir(parents=True, exist_ok=True)
        _safe_chain(self.runtime_authority_data_root, self.root)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._ensure_root()
        path = self.root / ".job_authority.lock"
        if path.exists() and _reparse(path):
            raise JobAuthorityError("Job Authority lock is redirected")
        with open(path, "a+b") as fh:
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b"\0")
                fh.flush()
                os.fsync(fh.fileno())
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _registration_path(self, jae: str) -> Path:
        return self.root / "registrations" / f"{_jae(jae)}.json"

    def _branch_path(self, key: str) -> Path:
        return self.root / "preapproval_branches" / f"{_sha(key, 'branch key')}.json"

    def _claim_path(self, successor_jae: str) -> Path:
        return self.root / "successor_lineage_claims" / f"{_jae(successor_jae)}.json"

    def _initial_issuance_path(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not job_id:
            raise JobAuthorityError("initial issuance job_id must be non-empty")
        key = sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_KEY_V1",
            "lineage_namespace": "RUNTIME_S1_GENERAL_CHAT_JOB_LINEAGE_IDENTITY_V1",
            "job_id": job_id,
        }))
        return self.root / "initial_jae_issuances" / f"{key}.json"

    def _controlled_successor_issuance_path(self, issuance_key_sha256: str) -> Path:
        return self.root / "controlled_successor_jae_issuances" / (
            f"{_sha(issuance_key_sha256, 'controlled successor issuance key')}.json"
        )

    def _approval_execution_slot_terminal_path(self, approval_slot_key_sha256: str) -> Path:
        return self.root / "approval_execution_slot_terminals" / (
            f"{_sha(approval_slot_key_sha256, 'approval execution slot key')}.json"
        )

    def _safe_parent(self, final: Path) -> None:
        self._ensure_root()
        if not _inside(_lex(final), _lex(self.root)):
            raise JobAuthorityError("source record escapes Job Authority root")
        _safe_chain(self.root, final.parent)
        final.parent.mkdir(parents=True, exist_ok=True)
        _safe_chain(self.root, final.parent)

    def _temp(self, final: Path, data: bytes) -> Path:
        self._safe_parent(final)
        temp = final.parent / f".{final.name}.tmp-{uuid.uuid4().hex}"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=True) as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        if temp.read_bytes() != data:
            raise JobAuthorityError("temp read-back mismatch")
        return temp

    @staticmethod
    def _publish_absent(temp: Path, final: Path) -> None:
        if final.exists():
            raise FileExistsError(str(final))
        if os.name == "nt":
            os.rename(temp, final)
        else:
            os.link(temp, final)
            temp.unlink()

    def _path_state(self, final: Path, *, label: str) -> str:
        root = _lex(self.root)
        final_abs = _lex(final)
        if not _inside(final_abs, root):
            raise JobAuthorityError(f"{label} escapes Job Authority root")
        if not root.exists():
            return "ABSENT"
        _safe_chain(root, root)
        parent = final_abs.parent
        if parent.exists():
            _safe_chain(root, parent)
        if not os.path.lexists(final_abs):
            return "ABSENT"
        if _reparse(final_abs):
            raise JobAuthorityError(f"{label} is redirected")
        if not final_abs.is_file():
            raise JobAuthorityError(f"{label} is not a regular file")
        return "PRESENT"

    @staticmethod
    def _validate_source_record(record: dict[str, Any], *, expected_schema: str, label: str) -> None:
        expected = _JOB_SOURCE_FIELDS.get(expected_schema)
        if expected is None:
            raise JobAuthorityError(f"unsupported source schema: {expected_schema}")
        _exact_fields(record, expected, label)
        if record.get("schema") != expected_schema or record.get("source_record_revision") != 1:
            raise JobAuthorityError(f"{label} schema/revision mismatch")
        ts = record.get("committed_at_utc")
        if not isinstance(ts, str) or _TIMESTAMP_RE.fullmatch(ts) is None:
            raise JobAuthorityError(f"{label} committed_at_utc is invalid")

    def _commit_locked(self, final: Path, semantic: dict[str, Any]) -> dict[str, Any]:
        schema = semantic.get("schema")
        expected = _JOB_SOURCE_FIELDS.get(schema)
        if expected is None:
            raise JobAuthorityError("unsupported Job Authority source schema")
        _exact_fields(semantic, frozenset(expected - {"committed_at_utc"}), "Job Authority semantic candidate")
        if semantic.get("source_record_revision") != 1:
            raise JobAuthorityError("Job Authority semantic source_record_revision mismatch")

        state = self._path_state(final, label="Job Authority source destination")
        if state == "PRESENT":
            stored = _json(final.read_bytes(), "stored Job Authority record")
            self._validate_source_record(stored, expected_schema=schema, label="stored Job Authority record")
            compare = dict(stored)
            compare.pop("committed_at_utc")
            if compare != semantic:
                raise JobAuthorityError("Job Authority first-writer conflict")
            return stored

        record = dict(semantic)
        record["committed_at_utc"] = _utc_now()
        self._validate_source_record(record, expected_schema=schema, label="new Job Authority record")
        data = _canonical(record)
        temp = self._temp(final, data)
        try:
            self._publish_absent(temp, final)
        except (FileExistsError, OSError):
            temp.unlink(missing_ok=True)
            if self._path_state(final, label="raced Job Authority destination") != "PRESENT":
                raise
            stored = _json(final.read_bytes(), "raced Job Authority record")
            self._validate_source_record(stored, expected_schema=schema, label="raced Job Authority record")
            compare = dict(stored)
            compare.pop("committed_at_utc")
            if compare != semantic:
                raise JobAuthorityError("Job Authority first-writer conflict")
            return stored
        stored_bytes = final.read_bytes()
        if stored_bytes != data or sha256_bytes(stored_bytes) != sha256_bytes(data):
            raise JobAuthorityError("Job Authority final read-back mismatch")
        return record

    def _source(self, final: Path, schema: str, label: str) -> dict[str, Any]:
        if self._path_state(final, label=label) != "PRESENT":
            raise JobAuthorityError(f"{label} is absent")
        obj = _json(final.read_bytes(), label)
        self._validate_source_record(obj, expected_schema=schema, label=label)
        return obj

    def _artifact_json_with_manifest(
        self,
        binding: R009OpaqueArtifactBinding,
        label: str,
    ) -> tuple[Any, dict[str, Any]]:
        manifest, data = self.artifact_store.load_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=binding.artifact_identity_sha256,
            artifact_revision=binding.artifact_revision,
            artifact_sha256=binding.artifact_sha256,
        )
        return manifest, _json(data, label)

    def _artifact_json(self, binding: R009OpaqueArtifactBinding, label: str) -> dict[str, Any]:
        _m, data = self.artifact_store.load_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=binding.artifact_identity_sha256,
            artifact_revision=binding.artifact_revision,
            artifact_sha256=binding.artifact_sha256,
        )
        return _json(data, label)

    @staticmethod
    def _initial_lineage_sha256(
        *,
        job_id: str,
        intake_sha256: str,
        input_set_sha256: str,
    ) -> str:
        return sha256_bytes(_canonical({
            "namespace": "RUNTIME_S1_GENERAL_CHAT_JOB_LINEAGE_IDENTITY_V1",
            "job_id": job_id,
            "web_formal_job_intake_binding_sha256": intake_sha256,
            "input_set_sha256": input_set_sha256,
        }))

    @staticmethod
    def _require_initial_input_set_matches_intake(
        *,
        input_set: dict[str, Any],
        intake: dict[str, Any],
    ) -> None:
        if input_set.get("schema") != "RUNTIME_S1_GENERAL_CHAT_INPUT_SET_V1":
            raise JobAuthorityError("initial issuance input-set schema mismatch")
        exact_pairs = (
            ("project_id", "project_id"),
            ("chat_id", "chat_id"),
            ("initiating_user_event_id", "initiating_user_event_id"),
            ("initiating_user_event_artifact_id", "initiating_user_event_artifact_id"),
            ("initiating_user_event_artifact_identity_sha256", "initiating_user_event_artifact_identity_sha256"),
            ("initiating_user_event_artifact_revision", "initiating_user_event_artifact_revision"),
            ("initiating_user_event_artifact_sha256", "initiating_user_event_artifact_sha256"),
            ("initiating_content_sha256", "initiating_content_sha256"),
            ("accepted_chat_revision", "accepted_chat_revision"),
            ("accepted_head_event_id", "accepted_head_event_id"),
        )
        for input_key, intake_key in exact_pairs:
            if input_set.get(input_key) != intake.get(intake_key):
                raise JobAuthorityError(f"initial issuance input-set/intake mismatch: {input_key}")
        event_artifact_id = input_set.get("initiating_user_event_artifact_id")
        event_identity = input_set.get("initiating_user_event_artifact_identity_sha256")
        if not isinstance(event_artifact_id, str) or not event_artifact_id:
            raise JobAuthorityError("initial issuance event artifact id invalid")
        expected_identity = sha256_bytes(("LEGACY_ARTIFACT_ID:" + event_artifact_id).encode("utf-8"))
        if event_identity != expected_identity:
            raise JobAuthorityError("initial issuance event artifact identity does not recompute")

    @staticmethod
    def _require_initial_source_context_matches_job_bundle(
        *,
        input_set: dict[str, Any],
        job_bundle: dict[str, Any],
    ) -> None:
        source = input_set.get("library_source_context")
        job_source_keys = (
            "source_context_sha256",
            "source_context_artifact_identity_sha256",
            "source_context_artifact_revision",
            "source_context_artifact_sha256",
            "source_ref_id",
            "source_artifact_identity_sha256",
            "source_artifact_revision",
            "source_artifact_sha256",
            "source_derivation_sha256",
            "source_load_plan_sha256",
            "source_permission_plan_sha256",
            "source_job_artifact_binding_plan_sha256",
            "source_predecessor_capability_pin_sha256",
        )
        if source is None:
            if any(job_bundle.get(key) is not None for key in job_source_keys):
                raise JobAuthorityError("initial issuance JobBundle/source input-set mismatch")
            return
        if not isinstance(source, dict):
            raise JobAuthorityError("initial issuance library source context invalid")
        context_binding = source.get("source_context_artifact_binding")
        if not isinstance(context_binding, dict):
            raise JobAuthorityError("initial issuance source-context Artifact binding missing")
        exact_pairs = {
            "source_context_sha256": job_bundle.get("source_context_sha256"),
            "source_ref_id": job_bundle.get("source_ref_id"),
            "source_artifact_identity_sha256": job_bundle.get("source_artifact_identity_sha256"),
            "source_artifact_revision": job_bundle.get("source_artifact_revision"),
            "source_artifact_sha256": job_bundle.get("source_artifact_sha256"),
            "derivation_sha256": job_bundle.get("source_derivation_sha256"),
            "source_load_plan_sha256": job_bundle.get("source_load_plan_sha256"),
            "source_permission_plan_sha256": job_bundle.get("source_permission_plan_sha256"),
            "source_job_artifact_binding_plan_sha256": job_bundle.get("source_job_artifact_binding_plan_sha256"),
            "source_predecessor_capability_pin_sha256": job_bundle.get("source_predecessor_capability_pin_sha256"),
        }
        for input_key, expected in exact_pairs.items():
            if expected is None or source.get(input_key) != expected:
                raise JobAuthorityError(f"initial issuance source input-set/JobBundle mismatch: {input_key}")
        context_pairs = {
            "artifact_identity_sha256": job_bundle.get("source_context_artifact_identity_sha256"),
            "artifact_revision": job_bundle.get("source_context_artifact_revision"),
            "artifact_sha256": job_bundle.get("source_context_artifact_sha256"),
        }
        for key, expected in context_pairs.items():
            if expected is None or context_binding.get(key) != expected:
                raise JobAuthorityError(f"initial issuance source-context Artifact mismatch: {key}")
        if source.get("source_context_sha256") != context_binding.get("artifact_sha256"):
            raise JobAuthorityError("initial issuance source-context semantic/Artifact SHA mismatch")
        if source.get("question_sha256") != input_set.get("initiating_content_sha256"):
            raise JobAuthorityError("initial issuance source question differs from initiating content")

    def _validate_initial_issuance_evidence(
        self,
        *,
        job_bundle_binding: R009OpaqueArtifactBinding,
        web_formal_job_intake_binding: R009OpaqueArtifactBinding,
        input_set_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        job_manifest, job_record = self._artifact_json_with_manifest(
            job_bundle_binding, "initial issuance JobBundle Artifact"
        )
        intake_manifest, intake = self._artifact_json_with_manifest(
            web_formal_job_intake_binding, "initial issuance Web intake Artifact"
        )
        input_manifest, input_set = self._artifact_json_with_manifest(
            input_set_binding, "initial issuance input-set Artifact"
        )

        if job_record.get("schema") != "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1":
            raise JobAuthorityError("initial issuance JobBundle schema mismatch")
        job_id = job_record.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise JobAuthorityError("initial issuance JobBundle job_id invalid")
        if job_manifest.job_id != job_id:
            raise JobAuthorityError("initial issuance JobBundle manifest job mismatch")
        expected_job_bundle_identity = sha256_bytes(
            f"M002:JOB_BUNDLE:{job_id}".encode("utf-8")
        )
        if job_bundle_binding.artifact_identity_sha256 != expected_job_bundle_identity:
            raise JobAuthorityError(
                "initial issuance JobBundle is not the producer-authoritative Artifact identity"
            )
        job_bundle = job_record.get("job_bundle")
        if not isinstance(job_bundle, dict) or job_bundle.get("job_id") != job_id:
            raise JobAuthorityError("initial issuance nested JobBundle job mismatch")
        computed_job_bundle_sha = sha256_bytes(_canonical(job_bundle))
        if job_record.get("job_bundle_sha256") != computed_job_bundle_sha:
            raise JobAuthorityError("initial issuance JobBundle semantic SHA does not recompute")

        if intake.get("schema") != "WEB_FORMAL_JOB_INTAKE_BINDING_V1":
            raise JobAuthorityError("initial issuance intake schema mismatch")
        if intake.get("job_id") != job_id or intake_manifest.job_id != job_id:
            raise JobAuthorityError("initial issuance intake job mismatch")
        if intake.get("job_bundle_sha256") != computed_job_bundle_sha:
            raise JobAuthorityError("initial issuance intake JobBundle SHA mismatch")
        intake_id_parts = (
            intake.get("project_id"),
            intake.get("chat_id"),
            intake.get("initiating_user_event_id"),
            job_id,
        )
        if any(not isinstance(value, str) or not value for value in intake_id_parts):
            raise JobAuthorityError("initial issuance intake identity inputs invalid")
        intake_body = "\x1f".join(intake_id_parts).encode("utf-8")
        expected_intake_record_id = (
            "INTAKE_" + sha256_bytes(intake_body)[:24].upper()
        )
        if intake.get("web_formal_job_intake_binding_id") != expected_intake_record_id:
            raise JobAuthorityError(
                "initial issuance intake record id does not recompute from authoritative producer inputs"
            )
        expected_intake_identity = sha256_bytes(
            f"M002:WEB_INTAKE:{expected_intake_record_id}".encode("utf-8")
        )
        if web_formal_job_intake_binding.artifact_identity_sha256 != expected_intake_identity:
            raise JobAuthorityError(
                "initial issuance intake is not the producer-authoritative Artifact identity"
            )

        if input_manifest.job_id != job_id:
            raise JobAuthorityError("initial issuance input-set manifest job mismatch")
        expected_input_set_identity = sha256_bytes(_canonical({
            "namespace": "UR_S1_PHASE_A_ARTIFACT_ID_V1",
            "kind": "JOB_LINEAGE_INPUT_SET",
            "job_id": job_id,
        }))
        if input_set_binding.artifact_identity_sha256 != expected_input_set_identity:
            raise JobAuthorityError(
                "initial issuance input-set is not the producer-authoritative Artifact identity"
            )

        self._require_initial_input_set_matches_intake(input_set=input_set, intake=intake)
        self._require_initial_source_context_matches_job_bundle(
            input_set=input_set,
            job_bundle=job_bundle,
        )

        lineage_sha = self._initial_lineage_sha256(
            job_id=job_id,
            intake_sha256=web_formal_job_intake_binding.artifact_sha256,
            input_set_sha256=input_set_binding.artifact_sha256,
        )
        return {
            "job_id": job_id,
            "job_bundle_sha256": computed_job_bundle_sha,
            "job_bundle_artifact_identity_sha256": job_bundle_binding.artifact_identity_sha256,
            "job_bundle_artifact_revision": job_bundle_binding.artifact_revision,
            "job_bundle_artifact_sha256": job_bundle_binding.artifact_sha256,
            "web_formal_job_intake_binding_sha256": web_formal_job_intake_binding.artifact_sha256,
            "web_formal_job_intake_artifact_identity_sha256": web_formal_job_intake_binding.artifact_identity_sha256,
            "web_formal_job_intake_artifact_revision": web_formal_job_intake_binding.artifact_revision,
            "web_formal_job_intake_artifact_sha256": web_formal_job_intake_binding.artifact_sha256,
            "input_set_sha256": input_set_binding.artifact_sha256,
            "input_set_artifact_identity_sha256": input_set_binding.artifact_identity_sha256,
            "input_set_artifact_revision": input_set_binding.artifact_revision,
            "input_set_artifact_sha256": input_set_binding.artifact_sha256,
            "job_lineage_identity_sha256": lineage_sha,
        }

    def _load_all_controlled_successor_issuance_sources_locked(self) -> list[dict[str, Any]]:
        parent = self.root / "controlled_successor_jae_issuances"
        if not parent.exists():
            return []
        _safe_chain(self.root, parent)
        rows: list[dict[str, Any]] = []
        for path in sorted(parent.iterdir(), key=lambda p: p.name):
            if _reparse(path):
                raise JobAuthorityError("controlled successor issuance source destination is redirected")
            if not path.is_file() or path.suffix != ".json":
                raise JobAuthorityError(
                    "controlled successor issuance source directory contains unexpected entry"
                )
            row = self._source(
                path,
                "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_SOURCE_RECORD_V1",
                "controlled successor JAE issuance source",
            )
            expected_path = self._controlled_successor_issuance_path(
                row["controlled_successor_jae_issuance_key_sha256"]
            )
            if _lex(path) != _lex(expected_path):
                raise JobAuthorityError("controlled successor issuance source path/key mismatch")
            rows.append(row)
        return rows

    def _controlled_successor_issuance_source_by_jae_locked(
        self,
        successor_job_authority_event_id: str,
    ) -> dict[str, Any]:
        successor_jae = _jae(successor_job_authority_event_id)
        matches = [
            row
            for row in self._load_all_controlled_successor_issuance_sources_locked()
            if row["successor_job_authority_event_id"] == successor_jae
        ]
        if len(matches) != 1:
            raise JobAuthorityError(
                "controlled successor JAE must bind exactly one owner issuance source"
            )
        return matches[0]

    @staticmethod
    def _controlled_successor_issuance_key(
        *,
        transition_intent_schema: str,
        predecessor_job_authority_event_id: str,
        predecessor_job_execution_authority_snapshot_id: str,
        predecessor_job_execution_authority_snapshot_sha256: str,
        predecessor_job_execution_snapshot_registration_sha256: str,
        transition_stage: str,
        stage_anchor_sha256: str,
    ) -> str:
        if transition_intent_schema not in _ALLOWED_INTENT_SCHEMAS:
            raise JobAuthorityError("controlled successor issuance transition schema invalid")
        _jae(predecessor_job_authority_event_id)
        _jxs(predecessor_job_execution_authority_snapshot_id)
        _sha(predecessor_job_execution_authority_snapshot_sha256, "predecessor snapshot SHA")
        _sha(predecessor_job_execution_snapshot_registration_sha256, "predecessor registration SHA")
        if transition_stage not in _CONTROLLED_SUCCESSOR_ISSUANCE_STAGES:
            raise JobAuthorityError("controlled successor issuance transition stage invalid")
        _sha(stage_anchor_sha256, "controlled successor issuance stage anchor")
        return sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_KEY_V1",
            "transition_intent_schema": transition_intent_schema,
            "predecessor_job_authority_event_id": predecessor_job_authority_event_id,
            "predecessor_job_execution_authority_snapshot_id": predecessor_job_execution_authority_snapshot_id,
            "predecessor_job_execution_authority_snapshot_sha256": predecessor_job_execution_authority_snapshot_sha256,
            "predecessor_job_execution_snapshot_registration_sha256": predecessor_job_execution_snapshot_registration_sha256,
            "transition_stage": transition_stage,
            "stage_anchor_sha256": stage_anchor_sha256,
        }))

    def _controlled_successor_predecessor_evidence(
        self,
        *,
        predecessor_job_authority_event_id: str,
    ) -> dict[str, Any]:
        predecessor_jae = _jae(predecessor_job_authority_event_id)
        reg_source, reg, reg_binding = self.load_exact_active_registration_source_by_jae_v1(
            job_authority_event_id=predecessor_jae
        )
        snapshot_binding = R009OpaqueArtifactBinding(
            reg["job_execution_authority_snapshot_artifact_identity_sha256"],
            reg["job_execution_authority_snapshot_artifact_revision"],
            reg["job_execution_authority_snapshot_artifact_sha256"],
        )
        snapshot, computed_jxs = self._validate_snapshot(snapshot_binding, predecessor_jae)
        if (
            computed_jxs != reg_source["job_execution_authority_snapshot_id"]
            or snapshot_binding.artifact_sha256
            != reg_source["job_execution_authority_snapshot_sha256"]
            or reg_binding.artifact_sha256 != reg_source["registration_sha256"]
        ):
            raise JobAuthorityError("controlled successor predecessor active source mismatch")
        lineage_sha = _sha(
            snapshot.get("job_lineage_identity_sha256"),
            "controlled successor predecessor lineage SHA",
        )
        expected_authority_binding = sha256_bytes(_canonical({
            "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
            "job_authority_event_id": predecessor_jae,
            "job_lineage_identity_sha256": lineage_sha,
        }))
        if snapshot.get("job_authority_binding_sha256") != expected_authority_binding:
            raise JobAuthorityError(
                "controlled successor predecessor authority binding does not recompute"
            )
        branch_key = sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_PREAPPROVAL_BRANCH_KEY_V1",
            "predecessor_job_authority_event_id": predecessor_jae,
            "predecessor_job_execution_authority_snapshot_id": computed_jxs,
            "predecessor_job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
            "predecessor_job_execution_snapshot_registration_sha256": reg_binding.artifact_sha256,
        }))
        return {
            "predecessor_job_authority_event_id": predecessor_jae,
            "predecessor_job_execution_authority_snapshot_id": computed_jxs,
            "predecessor_job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
            "predecessor_job_execution_snapshot_registration_sha256": reg_binding.artifact_sha256,
            "predecessor_snapshot_artifact_identity_sha256": snapshot_binding.artifact_identity_sha256,
            "predecessor_snapshot_artifact_revision": snapshot_binding.artifact_revision,
            "predecessor_snapshot_artifact_sha256": snapshot_binding.artifact_sha256,
            "predecessor_registration_artifact_identity_sha256": reg_binding.artifact_identity_sha256,
            "predecessor_registration_artifact_revision": reg_binding.artifact_revision,
            "predecessor_registration_artifact_sha256": reg_binding.artifact_sha256,
            "job_lineage_identity_sha256": lineage_sha,
            "preapproval_branch_key_sha256": branch_key,
        }

    @staticmethod
    def _require_exact_pending_human_decision_request_v1(
        *,
        human_decision_authority: Any,
        decision_request_event_id: str,
        decision_request_identity_sha256: str,
        preapproval_branch_key_sha256: str,
        branch_source: dict[str, Any],
        branch_binding: R009OpaqueArtifactBinding,
        branch: dict[str, Any],
    ) -> dict[str, Any]:
        if human_decision_authority is None:
            raise JobAuthorityError(
                "DRE-pending controlled successor requires HumanDecisionAuthority currentness evidence"
            )
        try:
            request_source = human_decision_authority.load_exact_request_source(
                decision_request_event_id
            )
        except Exception as exc:
            raise JobAuthorityError(
                "DRE-pending controlled successor exact HumanDecision request source is unavailable"
            ) from exc

        if (
            request_source.get("decision_request_event_id")
            != decision_request_event_id
            or request_source.get("decision_request_identity_sha256")
            != decision_request_identity_sha256
            or request_source.get("preapproval_branch_key_sha256")
            != preapproval_branch_key_sha256
            or request_source.get("preapproval_branch_selection_semantic_sha256")
            != branch_source["branch_selection_semantic_sha256"]
            or request_source.get("preapproval_branch_selection_artifact_identity_sha256")
            != branch_binding.artifact_identity_sha256
            or request_source.get("preapproval_branch_selection_artifact_revision")
            != branch_binding.artifact_revision
            or request_source.get("preapproval_branch_selection_artifact_sha256")
            != branch_binding.artifact_sha256
            or request_source.get("decision_request_binding_v3")
            != branch.get("decision_request_binding_v3")
        ):
            raise JobAuthorityError(
                "DRE-pending controlled successor HumanDecision request source/branch mismatch"
            )

        try:
            terminal = human_decision_authority.load_exact_terminal_source(
                decision_request_event_id
            )
        except Exception as exc:
            if (
                exc.__class__.__name__ == "HumanDecisionAuthorityError"
                and str(exc) == "terminal source absent"
            ):
                return request_source
            raise JobAuthorityError(
                "DRE-pending controlled successor terminal absence cannot be proven"
            ) from exc

        if isinstance(terminal, dict):
            raise JobAuthorityError(
                "DRE-pending controlled successor terminal source already exists"
            )
        raise JobAuthorityError(
            "DRE-pending controlled successor terminal absence cannot be proven"
        )

    def _controlled_successor_stage_anchor(
        self,
        *,
        predecessor: dict[str, Any],
        transition_intent_schema: str,
        transition_stage: str,
        approval_decision_event_binding: R009OpaqueArtifactBinding | None,
        human_decision_authority: Any | None,
    ) -> dict[str, Any]:
        branch_key = predecessor["preapproval_branch_key_sha256"]
        null_branch = {
            "preapproval_branch_key_sha256": None,
            "preapproval_branch_selection_semantic_sha256": None,
            "preapproval_branch_selection_artifact_identity_sha256": None,
            "preapproval_branch_selection_artifact_revision": None,
            "preapproval_branch_selection_artifact_sha256": None,
            "predecessor_decision_request_event_id": None,
            "predecessor_decision_request_identity_sha256": None,
        }
        null_approval = {
            "predecessor_approval_decision_event_id": None,
            "predecessor_approval_slot_key_sha256": None,
            "predecessor_approval_artifact_identity_sha256": None,
            "predecessor_approval_artifact_revision": None,
            "predecessor_approval_artifact_sha256": None,
        }

        if transition_stage == "ACTIVE_PREDECESSOR_NO_DRE":
            if transition_intent_schema != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1":
                raise JobAuthorityError("pre-DRE controlled successor requires preapproval transition V1")
            if approval_decision_event_binding is not None or human_decision_authority is not None:
                raise JobAuthorityError("pre-DRE controlled successor forbids approval evidence")
            if self._path_state(self._branch_path(branch_key), label="pre-DRE branch destination") != "ABSENT":
                self.load_exact_preapproval_branch_by_key_v1(
                    preapproval_branch_key_sha256=branch_key
                )
                raise JobAuthorityError("ACTIVE_PREDECESSOR_NO_DRE requires branch destination absent")
            return {
                "stage_anchor_sha256": branch_key,
                **null_branch,
                **null_approval,
            }

        if transition_stage == "DRE_PENDING_NO_TERMINAL_DECISION":
            if transition_intent_schema != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1":
                raise JobAuthorityError("DRE-pending controlled successor requires preapproval transition V1")
            if approval_decision_event_binding is not None:
                raise JobAuthorityError("DRE-pending controlled successor forbids approval binding")
            branch_source, branch, branch_binding = self.load_exact_preapproval_branch_by_key_v1(
                preapproval_branch_key_sha256=branch_key
            )
            if branch_source["branch_code"] != "DRE_ISSUANCE_SELECTED":
                raise JobAuthorityError("DRE-pending controlled successor requires DRE_ISSUANCE_SELECTED")
            dre_event = branch.get("decision_request_event_id")
            if not isinstance(dre_event, str) or re.fullmatch(r"DRE_[0-9a-f]{64}", dre_event) is None:
                raise JobAuthorityError("DRE-pending controlled successor DRE invalid")
            dre_identity = _sha(
                branch.get("decision_request_identity_sha256"),
                "DRE-pending controlled successor request identity",
            )
            self._require_exact_pending_human_decision_request_v1(
                human_decision_authority=human_decision_authority,
                decision_request_event_id=dre_event,
                decision_request_identity_sha256=dre_identity,
                preapproval_branch_key_sha256=branch_key,
                branch_source=branch_source,
                branch_binding=branch_binding,
                branch=branch,
            )
            stage_anchor = sha256_bytes(_canonical({
                "namespace": "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_DRE_STAGE_ANCHOR_V1",
                "preapproval_branch_key_sha256": branch_key,
                "branch_selection_semantic_sha256": branch_source["branch_selection_semantic_sha256"],
                "branch_artifact_identity_sha256": branch_binding.artifact_identity_sha256,
                "branch_artifact_revision": branch_binding.artifact_revision,
                "branch_artifact_sha256": branch_binding.artifact_sha256,
                "decision_request_event_id": dre_event,
                "decision_request_identity_sha256": dre_identity,
            }))
            return {
                "stage_anchor_sha256": stage_anchor,
                "preapproval_branch_key_sha256": branch_key,
                "preapproval_branch_selection_semantic_sha256": branch_source[
                    "branch_selection_semantic_sha256"
                ],
                "preapproval_branch_selection_artifact_identity_sha256": branch_binding.artifact_identity_sha256,
                "preapproval_branch_selection_artifact_revision": branch_binding.artifact_revision,
                "preapproval_branch_selection_artifact_sha256": branch_binding.artifact_sha256,
                "predecessor_decision_request_event_id": dre_event,
                "predecessor_decision_request_identity_sha256": dre_identity,
                **null_approval,
            }

        if transition_stage != "APPROVED_SLOT_UNCLAIMED":
            raise JobAuthorityError("controlled successor transition stage invalid")
        if transition_intent_schema != "RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2":
            raise JobAuthorityError("approved-slot controlled successor requires controlled reopen intent V2")
        if approval_decision_event_binding is None or human_decision_authority is None:
            raise JobAuthorityError("approved-slot controlled successor requires exact Human approval source evidence")

        approval = self._artifact_json(
            approval_decision_event_binding,
            "approved-slot approval decision Artifact",
        )
        _exact_fields(approval, _APPROVAL_DECISION_V3_FIELDS, "approved-slot approval decision")
        if (
            approval.get("schema") != "RUNTIME_APPROVAL_DECISION_EVENT_BINDING_V3"
            or approval.get("decision_code") != "APPROVED"
            or approval.get("job_authority_event_id")
            != predecessor["predecessor_job_authority_event_id"]
            or approval.get("job_execution_authority_snapshot_id")
            != predecessor["predecessor_job_execution_authority_snapshot_id"]
            or approval.get("job_execution_authority_snapshot_sha256")
            != predecessor["predecessor_job_execution_authority_snapshot_sha256"]
            or approval.get("job_execution_authority_snapshot_artifact_identity_sha256")
            != predecessor["predecessor_snapshot_artifact_identity_sha256"]
            or approval.get("job_execution_authority_snapshot_artifact_revision")
            != predecessor["predecessor_snapshot_artifact_revision"]
            or approval.get("job_execution_authority_snapshot_artifact_sha256")
            != predecessor["predecessor_snapshot_artifact_sha256"]
            or approval.get("job_execution_snapshot_registration_sha256")
            != predecessor["predecessor_job_execution_snapshot_registration_sha256"]
        ):
            raise JobAuthorityError("approved-slot approval evidence does not bind exact predecessor")

        ade = approval.get("approval_decision_event_id")
        if not isinstance(ade, str) or _ADE_RE.fullmatch(ade) is None:
            raise JobAuthorityError("approved-slot ADE invalid")
        terminal = human_decision_authority.load_exact_terminal_source(
            approval["decision_request_event_id"]
        )
        if (
            terminal.get("terminal_decision_code") != "APPROVED"
            or terminal.get("approval_decision_event_id") != ade
            or terminal.get("approval_decision_event_artifact_identity_sha256")
            != approval_decision_event_binding.artifact_identity_sha256
            or terminal.get("approval_decision_event_artifact_revision")
            != approval_decision_event_binding.artifact_revision
            or terminal.get("approval_decision_event_artifact_sha256")
            != approval_decision_event_binding.artifact_sha256
        ):
            raise JobAuthorityError("approved-slot Human source does not bind exact approval evidence")

        slot_key = sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_SCOPED_APPROVAL_CONSUMPTION_SLOT_V1",
            "job_authority_binding_sha256": sha256_bytes(_canonical({
                "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
                "job_authority_event_id": predecessor["predecessor_job_authority_event_id"],
                "job_lineage_identity_sha256": predecessor["job_lineage_identity_sha256"],
            })),
            "approval_decision_event_id": ade,
        }))
        stage_anchor = sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_APPROVED_SLOT_STAGE_ANCHOR_V1",
            "predecessor_approval_slot_key_sha256": slot_key,
            "approval_decision_event_id": ade,
            "approval_decision_event_artifact_identity_sha256":
                approval_decision_event_binding.artifact_identity_sha256,
            "approval_decision_event_artifact_revision":
                approval_decision_event_binding.artifact_revision,
            "approval_decision_event_artifact_sha256":
                approval_decision_event_binding.artifact_sha256,
        }))
        return {
            "stage_anchor_sha256": stage_anchor,
            **null_branch,
            "predecessor_approval_decision_event_id": ade,
            "predecessor_approval_slot_key_sha256": slot_key,
            "predecessor_approval_artifact_identity_sha256":
                approval_decision_event_binding.artifact_identity_sha256,
            "predecessor_approval_artifact_revision":
                approval_decision_event_binding.artifact_revision,
            "predecessor_approval_artifact_sha256":
                approval_decision_event_binding.artifact_sha256,
        }

    def _validate_controlled_successor_issuance_source(
        self,
        source: dict[str, Any],
    ) -> None:
        self._validate_source_record(
            source,
            expected_schema="RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_SOURCE_RECORD_V1",
            label="controlled successor JAE issuance source",
        )
        if source.get("state") != "CONTROLLED_SUCCESSOR_JOB_AUTHORITY_EVENT_ISSUED":
            raise JobAuthorityError("controlled successor issuance state invalid")
        _sha(
            source.get("controlled_successor_jae_issuance_key_sha256"),
            "controlled successor issuance key",
        )
        _jae(source.get("successor_job_authority_event_id"))
        _sha(source.get("job_lineage_identity_sha256"), "controlled successor lineage")
        recomputed_key = self._controlled_successor_issuance_key(
            transition_intent_schema=source["transition_intent_schema"],
            predecessor_job_authority_event_id=source["predecessor_job_authority_event_id"],
            predecessor_job_execution_authority_snapshot_id=
                source["predecessor_job_execution_authority_snapshot_id"],
            predecessor_job_execution_authority_snapshot_sha256=
                source["predecessor_job_execution_authority_snapshot_sha256"],
            predecessor_job_execution_snapshot_registration_sha256=
                source["predecessor_job_execution_snapshot_registration_sha256"],
            transition_stage=source["transition_stage"],
            stage_anchor_sha256=source["stage_anchor_sha256"],
        )
        if recomputed_key != source["controlled_successor_jae_issuance_key_sha256"]:
            raise JobAuthorityError("controlled successor issuance key does not recompute")

    def _mint_unique_controlled_successor_jae_locked(
        self,
        initial_sources: list[dict[str, Any]],
        controlled_sources: list[dict[str, Any]],
    ) -> str:
        occupied = {
            row["job_authority_event_id"]
            for row in initial_sources
        } | {
            row["successor_job_authority_event_id"]
            for row in controlled_sources
        }
        for _ in range(32):
            candidate = "JAE_" + secrets.token_hex(32)
            if candidate in occupied:
                continue
            if self._path_state(
                self._registration_path(candidate),
                label="candidate controlled successor JAE registration",
            ) == "PRESENT":
                continue
            if self._path_state(
                self._claim_path(candidate),
                label="candidate controlled successor JAE lineage claim",
            ) == "PRESENT":
                continue
            return candidate
        raise JobAuthorityError("unable to mint unique opaque controlled successor JAE")

    def _approval_slot_key_for_active_authority_v1(
        self,
        *,
        job_authority_event_id: str,
        approval_decision_event_id: str,
    ) -> str:
        jae = _jae(job_authority_event_id)
        if not isinstance(approval_decision_event_id, str) or _ADE_RE.fullmatch(approval_decision_event_id) is None:
            raise JobAuthorityError("approval decision event id invalid")
        active_source, registration, _registration_binding = (
            self.load_exact_active_registration_source_by_jae_v1(
                job_authority_event_id=jae
            )
        )
        snapshot_binding = R009OpaqueArtifactBinding(
            registration["job_execution_authority_snapshot_artifact_identity_sha256"],
            registration["job_execution_authority_snapshot_artifact_revision"],
            registration["job_execution_authority_snapshot_artifact_sha256"],
        )
        snapshot, computed_jxs = self._validate_snapshot(snapshot_binding, jae)
        if (
            active_source.get("job_execution_authority_snapshot_id") != computed_jxs
            or registration.get("job_execution_authority_snapshot_id") != computed_jxs
            or active_source.get("job_execution_authority_snapshot_sha256")
            != snapshot_binding.artifact_sha256
        ):
            raise JobAuthorityError("approval slot active authority changed")
        lineage = _sha(snapshot.get("job_lineage_identity_sha256"), "approval slot lineage")
        authority_binding_sha = sha256_bytes(_canonical({
            "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
            "job_authority_event_id": jae,
            "job_lineage_identity_sha256": lineage,
        }))
        return sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_SCOPED_APPROVAL_CONSUMPTION_SLOT_V1",
            "job_authority_binding_sha256": authority_binding_sha,
            "approval_decision_event_id": approval_decision_event_id,
        }))

    def load_exact_approval_execution_slot_terminal_v1(
        self,
        *,
        approval_slot_key_sha256: str,
    ) -> dict[str, Any]:
        path = self._approval_execution_slot_terminal_path(approval_slot_key_sha256)
        terminal = self._source(
            path,
            "RUNTIME_JOB_AUTHORITY_APPROVAL_EXECUTION_SLOT_TERMINAL_SOURCE_RECORD_V1",
            "approval execution slot terminal",
        )
        if (
            terminal.get("approval_slot_key_sha256") != approval_slot_key_sha256
            or terminal.get("state") != "TERMINAL"
        ):
            raise JobAuthorityError("approval execution slot terminal binding/state mismatch")
        outcome = terminal.get("terminal_outcome")
        if outcome == "ATTEMPT_CLAIMED":
            if (
                not isinstance(terminal.get("attempt_claim_id"), str)
                or not terminal["attempt_claim_id"]
                or terminal.get("successor_job_authority_event_id") is not None
                or terminal.get("successor_job_execution_authority_snapshot_id") is not None
                or terminal.get("successor_job_execution_authority_snapshot_sha256") is not None
                or terminal.get("job_transition_intent_sha256") is not None
                or terminal.get("invalidation_reason_code") is not None
            ):
                raise JobAuthorityError("attempt slot terminal field matrix invalid")
            _sha(terminal.get("formal_job_execution_binding_sha256"), "attempt slot execution binding")
            _sha(terminal.get("job_model_execution_grant_sha256"), "attempt slot grant binding")
        elif outcome == "INVALIDATED_BEFORE_ATTEMPT_NO_EXECUTION":
            if (
                terminal.get("attempt_claim_id") is not None
                or terminal.get("formal_job_execution_binding_sha256") is not None
                or terminal.get("job_model_execution_grant_sha256") is not None
                or terminal.get("invalidation_reason_code")
                != "STALE_EXECUTION_AUTHORITY_CURRENT_RUNTIME_SOURCE_CHANGE"
            ):
                raise JobAuthorityError("invalidation slot terminal field matrix invalid")
            _jae(terminal.get("successor_job_authority_event_id"))
            _jxs(terminal.get("successor_job_execution_authority_snapshot_id"))
            _sha(
                terminal.get("successor_job_execution_authority_snapshot_sha256"),
                "invalidation successor snapshot SHA",
            )
            _sha(terminal.get("job_transition_intent_sha256"), "invalidation transition SHA")
        else:
            raise JobAuthorityError("approval execution slot terminal outcome invalid")
        return terminal

    @staticmethod
    def _approval_execution_slot_terminal_sha256(terminal: dict[str, Any]) -> str:
        return sha256_bytes(_canonical(terminal))

    def claim_or_replay_approval_execution_slot_attempt_v1(
        self,
        *,
        job_authority_event_id: str,
        approval_decision_event_id: str,
        attempt_claim_id: str,
        formal_job_execution_binding_sha256: str,
        job_model_execution_grant_sha256: str,
    ) -> dict[str, Any]:
        if not isinstance(attempt_claim_id, str) or not attempt_claim_id:
            raise JobAuthorityError("attempt claim id required")
        execution_sha = _sha(
            formal_job_execution_binding_sha256,
            "formal job execution binding SHA",
        )
        grant_sha = _sha(
            job_model_execution_grant_sha256,
            "job model execution grant SHA",
        )
        jae = _jae(job_authority_event_id)
        ade = approval_decision_event_id
        if not isinstance(ade, str) or _ADE_RE.fullmatch(ade) is None:
            raise JobAuthorityError("approval decision event id invalid")

        with self._lock():
            slot_key = self._approval_slot_key_for_active_authority_v1(
                job_authority_event_id=jae,
                approval_decision_event_id=ade,
            )
            path = self._approval_execution_slot_terminal_path(slot_key)
            state = self._path_state(path, label="approval execution slot terminal destination")
            if state == "PRESENT":
                terminal = self.load_exact_approval_execution_slot_terminal_v1(
                    approval_slot_key_sha256=slot_key
                )
                if terminal["terminal_outcome"] != "ATTEMPT_CLAIMED":
                    raise JobAuthorityError(
                        "APPROVAL_EXECUTION_SLOT_INVALIDATED_BEFORE_ATTEMPT"
                    )
                if (
                    terminal["job_authority_event_id"] != jae
                    or terminal["approval_decision_event_id"] != ade
                    or terminal["attempt_claim_id"] != attempt_claim_id
                    or terminal["formal_job_execution_binding_sha256"] != execution_sha
                    or terminal["job_model_execution_grant_sha256"] != grant_sha
                ):
                    raise JobAuthorityError("approval execution slot attempt first-writer conflict")
                return {
                    "status": "ATTEMPT_SLOT_TERMINAL_REPLAY",
                    "disposition": "EXISTS",
                    "approval_slot_key_sha256": slot_key,
                    "terminal_source_sha256":
                        self._approval_execution_slot_terminal_sha256(terminal),
                    "terminal": terminal,
                }

            semantic = {
                "schema":
                    "RUNTIME_JOB_AUTHORITY_APPROVAL_EXECUTION_SLOT_TERMINAL_SOURCE_RECORD_V1",
                "source_record_revision": 1,
                "approval_slot_key_sha256": slot_key,
                "job_authority_event_id": jae,
                "approval_decision_event_id": ade,
                "terminal_outcome": "ATTEMPT_CLAIMED",
                "attempt_claim_id": attempt_claim_id,
                "formal_job_execution_binding_sha256": execution_sha,
                "job_model_execution_grant_sha256": grant_sha,
                "successor_job_authority_event_id": None,
                "successor_job_execution_authority_snapshot_id": None,
                "successor_job_execution_authority_snapshot_sha256": None,
                "job_transition_intent_sha256": None,
                "invalidation_reason_code": None,
                "state": "TERMINAL",
            }
            terminal = self._commit_locked(path, semantic)
            return {
                "status": "ATTEMPT_SLOT_TERMINAL_COMMITTED",
                "disposition": "CREATED",
                "approval_slot_key_sha256": slot_key,
                "terminal_source_sha256":
                    self._approval_execution_slot_terminal_sha256(terminal),
                "terminal": terminal,
            }

    def invalidate_or_replay_approval_execution_slot_before_attempt_v1(
        self,
        *,
        predecessor_job_authority_event_id: str,
        predecessor_approval_decision_event_id: str,
        expected_predecessor_approval_slot_key_sha256: str,
        successor_job_authority_event_id: str,
        successor_job_execution_authority_snapshot_id: str,
        successor_job_execution_authority_snapshot_sha256: str,
        job_transition_intent_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        predecessor_jae = _jae(predecessor_job_authority_event_id)
        ade = predecessor_approval_decision_event_id
        if not isinstance(ade, str) or _ADE_RE.fullmatch(ade) is None:
            raise JobAuthorityError("predecessor approval decision event id invalid")
        expected_slot = _sha(
            expected_predecessor_approval_slot_key_sha256,
            "expected predecessor approval slot",
        )
        successor_jae = _jae(successor_job_authority_event_id)
        successor_jxs = _jxs(successor_job_execution_authority_snapshot_id)
        successor_sha = _sha(
            successor_job_execution_authority_snapshot_sha256,
            "successor snapshot SHA",
        )
        transition = self._artifact_json(
            job_transition_intent_binding,
            "approved-slot recovery transition intent",
        )
        if (
            transition.get("schema") != "RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2"
            or transition.get("transition_code") != "CONTROLLED_REOPEN_RUNTIME_MIGRATION"
            or transition.get("predecessor_job_authority_event_id") != predecessor_jae
            or transition.get("predecessor_approval_decision_event_id") != ade
            or transition.get("predecessor_approval_slot_key_sha256") != expected_slot
            or transition.get("successor_job_authority_event_id") != successor_jae
            or transition.get("successor_job_execution_authority_snapshot_id") != successor_jxs
            or transition.get("successor_job_execution_authority_snapshot_sha256") != successor_sha
            or transition.get("successor_activation_required") is not True
        ):
            raise JobAuthorityError("approved-slot recovery transition exact binding mismatch")
        transition_sha = job_transition_intent_binding.artifact_sha256

        with self._lock():
            current_slot = self._approval_slot_key_for_active_authority_v1(
                job_authority_event_id=predecessor_jae,
                approval_decision_event_id=ade,
            )
            if current_slot != expected_slot:
                raise JobAuthorityError("predecessor approval slot currentness mismatch")
            path = self._approval_execution_slot_terminal_path(current_slot)
            state = self._path_state(path, label="approval execution slot terminal destination")
            if state == "PRESENT":
                terminal = self.load_exact_approval_execution_slot_terminal_v1(
                    approval_slot_key_sha256=current_slot
                )
                if terminal["terminal_outcome"] == "ATTEMPT_CLAIMED":
                    raise JobAuthorityError(
                        "APPROVAL_EXECUTION_SLOT_ATTEMPT_ALREADY_WON"
                    )
                if (
                    terminal["job_authority_event_id"] != predecessor_jae
                    or terminal["approval_decision_event_id"] != ade
                    or terminal["successor_job_authority_event_id"] != successor_jae
                    or terminal["successor_job_execution_authority_snapshot_id"] != successor_jxs
                    or terminal["successor_job_execution_authority_snapshot_sha256"] != successor_sha
                    or terminal["job_transition_intent_sha256"] != transition_sha
                ):
                    raise JobAuthorityError("approval execution slot invalidation first-writer conflict")
                return {
                    "status": "APPROVAL_SLOT_INVALIDATION_REPLAY",
                    "disposition": "EXISTS",
                    "approval_slot_key_sha256": current_slot,
                    "terminal_source_sha256":
                        self._approval_execution_slot_terminal_sha256(terminal),
                    "terminal": terminal,
                }

            semantic = {
                "schema":
                    "RUNTIME_JOB_AUTHORITY_APPROVAL_EXECUTION_SLOT_TERMINAL_SOURCE_RECORD_V1",
                "source_record_revision": 1,
                "approval_slot_key_sha256": current_slot,
                "job_authority_event_id": predecessor_jae,
                "approval_decision_event_id": ade,
                "terminal_outcome": "INVALIDATED_BEFORE_ATTEMPT_NO_EXECUTION",
                "attempt_claim_id": None,
                "formal_job_execution_binding_sha256": None,
                "job_model_execution_grant_sha256": None,
                "successor_job_authority_event_id": successor_jae,
                "successor_job_execution_authority_snapshot_id": successor_jxs,
                "successor_job_execution_authority_snapshot_sha256": successor_sha,
                "job_transition_intent_sha256": transition_sha,
                "invalidation_reason_code":
                    "STALE_EXECUTION_AUTHORITY_CURRENT_RUNTIME_SOURCE_CHANGE",
                "state": "TERMINAL",
            }
            terminal = self._commit_locked(path, semantic)
            return {
                "status": "APPROVAL_SLOT_INVALIDATED_BEFORE_ATTEMPT",
                "disposition": "CREATED",
                "approval_slot_key_sha256": current_slot,
                "terminal_source_sha256":
                    self._approval_execution_slot_terminal_sha256(terminal),
                "terminal": terminal,
            }

    def _validate_v2_invalidation_terminal_for_registration_locked(
        self,
        reg: dict[str, Any],
    ) -> dict[str, Any]:
        slot_key = _sha(
            reg.get("predecessor_approval_slot_key_sha256"),
            "V2 predecessor approval slot",
        )
        terminal = self.load_exact_approval_execution_slot_terminal_v1(
            approval_slot_key_sha256=slot_key
        )
        if terminal.get("terminal_outcome") != "INVALIDATED_BEFORE_ATTEMPT_NO_EXECUTION":
            raise JobAuthorityError("V2 activation requires invalidated approval execution slot")
        terminal_sha = self._approval_execution_slot_terminal_sha256(terminal)
        if (
            terminal_sha != reg.get("predecessor_invalidation_sha256")
            or terminal.get("successor_job_authority_event_id")
            != reg.get("job_authority_event_id")
            or terminal.get("successor_job_execution_authority_snapshot_id")
            != reg.get("job_execution_authority_snapshot_id")
            or terminal.get("successor_job_execution_authority_snapshot_sha256")
            != reg.get("job_execution_authority_snapshot_sha256")
            or terminal.get("job_transition_intent_sha256")
            != reg.get("job_transition_intent_sha256")
        ):
            raise JobAuthorityError("V2 activation invalidation source exact binding mismatch")
        return terminal

    def issue_or_replay_one_controlled_successor_job_authority_event_v1(
        self,
        *,
        predecessor_job_authority_event_id: str,
        transition_intent_schema: str,
        transition_stage: str,
        transition_code: str,
        approval_decision_event_binding: R009OpaqueArtifactBinding | None = None,
        human_decision_authority: Any | None = None,
    ) -> dict[str, Any]:
        if transition_code not in _CONTROLLED_SUCCESSOR_REOPEN_CODES:
            if transition_code == "CONTROLLED_CANCEL":
                raise JobAuthorityError("CONTROLLED_CANCEL_MUST_NOT_ISSUE_SUCCESSOR_JAE")
            raise JobAuthorityError("controlled successor transition code invalid")
        predecessor = self._controlled_successor_predecessor_evidence(
            predecessor_job_authority_event_id=predecessor_job_authority_event_id
        )
        anchor = self._controlled_successor_stage_anchor(
            predecessor=predecessor,
            transition_intent_schema=transition_intent_schema,
            transition_stage=transition_stage,
            approval_decision_event_binding=approval_decision_event_binding,
            human_decision_authority=human_decision_authority,
        )
        issuance_key = self._controlled_successor_issuance_key(
            transition_intent_schema=transition_intent_schema,
            predecessor_job_authority_event_id=
                predecessor["predecessor_job_authority_event_id"],
            predecessor_job_execution_authority_snapshot_id=
                predecessor["predecessor_job_execution_authority_snapshot_id"],
            predecessor_job_execution_authority_snapshot_sha256=
                predecessor["predecessor_job_execution_authority_snapshot_sha256"],
            predecessor_job_execution_snapshot_registration_sha256=
                predecessor["predecessor_job_execution_snapshot_registration_sha256"],
            transition_stage=transition_stage,
            stage_anchor_sha256=anchor["stage_anchor_sha256"],
        )
        path = self._controlled_successor_issuance_path(issuance_key)

        def semantic_for(successor_jae: str) -> dict[str, Any]:
            return {
                "schema":
                    "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_SOURCE_RECORD_V1",
                "source_record_revision": 1,
                "controlled_successor_jae_issuance_key_sha256": issuance_key,
                "transition_intent_schema": transition_intent_schema,
                "transition_stage": transition_stage,
                "transition_code": transition_code,
                "predecessor_job_authority_event_id":
                    predecessor["predecessor_job_authority_event_id"],
                "predecessor_job_execution_authority_snapshot_id":
                    predecessor["predecessor_job_execution_authority_snapshot_id"],
                "predecessor_job_execution_authority_snapshot_sha256":
                    predecessor["predecessor_job_execution_authority_snapshot_sha256"],
                "predecessor_job_execution_snapshot_registration_sha256":
                    predecessor["predecessor_job_execution_snapshot_registration_sha256"],
                "predecessor_snapshot_artifact_identity_sha256":
                    predecessor["predecessor_snapshot_artifact_identity_sha256"],
                "predecessor_snapshot_artifact_revision":
                    predecessor["predecessor_snapshot_artifact_revision"],
                "predecessor_snapshot_artifact_sha256":
                    predecessor["predecessor_snapshot_artifact_sha256"],
                "predecessor_registration_artifact_identity_sha256":
                    predecessor["predecessor_registration_artifact_identity_sha256"],
                "predecessor_registration_artifact_revision":
                    predecessor["predecessor_registration_artifact_revision"],
                "predecessor_registration_artifact_sha256":
                    predecessor["predecessor_registration_artifact_sha256"],
                "stage_anchor_sha256": anchor["stage_anchor_sha256"],
                "preapproval_branch_key_sha256":
                    anchor["preapproval_branch_key_sha256"],
                "preapproval_branch_selection_semantic_sha256":
                    anchor["preapproval_branch_selection_semantic_sha256"],
                "preapproval_branch_selection_artifact_identity_sha256":
                    anchor["preapproval_branch_selection_artifact_identity_sha256"],
                "preapproval_branch_selection_artifact_revision":
                    anchor["preapproval_branch_selection_artifact_revision"],
                "preapproval_branch_selection_artifact_sha256":
                    anchor["preapproval_branch_selection_artifact_sha256"],
                "predecessor_decision_request_event_id":
                    anchor["predecessor_decision_request_event_id"],
                "predecessor_decision_request_identity_sha256":
                    anchor["predecessor_decision_request_identity_sha256"],
                "predecessor_approval_decision_event_id":
                    anchor["predecessor_approval_decision_event_id"],
                "predecessor_approval_slot_key_sha256":
                    anchor["predecessor_approval_slot_key_sha256"],
                "predecessor_approval_artifact_identity_sha256":
                    anchor["predecessor_approval_artifact_identity_sha256"],
                "predecessor_approval_artifact_revision":
                    anchor["predecessor_approval_artifact_revision"],
                "predecessor_approval_artifact_sha256":
                    anchor["predecessor_approval_artifact_sha256"],
                "job_lineage_identity_sha256": predecessor["job_lineage_identity_sha256"],
                "successor_job_authority_event_id": successor_jae,
                "state": "CONTROLLED_SUCCESSOR_JOB_AUTHORITY_EVENT_ISSUED",
            }

        with self._lock():
            predecessor2 = self._controlled_successor_predecessor_evidence(
                predecessor_job_authority_event_id=predecessor_job_authority_event_id
            )
            if transition_stage == "APPROVED_SLOT_UNCLAIMED":
                if approval_decision_event_binding is None:
                    raise JobAuthorityError("approved-slot controlled successor approval binding disappeared")
                self._artifact_json(
                    approval_decision_event_binding,
                    "approved-slot approval decision Artifact under Job lock",
                )
                anchor2 = anchor
            else:
                anchor2 = self._controlled_successor_stage_anchor(
                    predecessor=predecessor2,
                    transition_intent_schema=transition_intent_schema,
                    transition_stage=transition_stage,
                    approval_decision_event_binding=approval_decision_event_binding,
                    human_decision_authority=human_decision_authority,
                )
            if predecessor2 != predecessor or anchor2 != anchor:
                raise JobAuthorityError("controlled successor issuance evidence changed before commit")

            initial_sources = self._load_all_initial_issuance_sources_locked()
            controlled_sources = self._load_all_controlled_successor_issuance_sources_locked()
            state = self._path_state(path, label="controlled successor issuance destination")
            if state == "ABSENT" and transition_stage == "APPROVED_SLOT_UNCLAIMED":
                slot_key = anchor2["predecessor_approval_slot_key_sha256"]
                terminal_path = self._approval_execution_slot_terminal_path(slot_key)
                if self._path_state(
                    terminal_path,
                    label="approved-slot terminal before successor issuance",
                ) == "PRESENT":
                    terminal = self.load_exact_approval_execution_slot_terminal_v1(
                        approval_slot_key_sha256=slot_key
                    )
                    raise JobAuthorityError(
                        "APPROVED_SLOT_SUCCESSOR_ISSUANCE_DENIED_TERMINAL_EXISTS:"
                        + str(terminal.get("terminal_outcome"))
                    )
            if state == "PRESENT":
                stored = self._source(
                    path,
                    "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_SOURCE_RECORD_V1",
                    "controlled successor JAE issuance source",
                )
                self._validate_controlled_successor_issuance_source(stored)
                if any(
                    row["job_authority_event_id"] == stored["successor_job_authority_event_id"]
                    for row in initial_sources
                ):
                    raise JobAuthorityError(
                        "CONTROLLED_SUCCESSOR_ISSUANCE_DENIED_INITIAL_JAE_ALREADY_ISSUED"
                    )
                compare = dict(stored)
                compare.pop("committed_at_utc")
                expected = semantic_for(stored["successor_job_authority_event_id"])
                if compare != expected:
                    raise JobAuthorityError("controlled successor JAE issuance first-writer conflict")
                return stored

            successor_jae = self._mint_unique_controlled_successor_jae_locked(
                initial_sources,
                controlled_sources,
            )
            return self._commit_locked(path, semantic_for(successor_jae))

    def _load_all_initial_issuance_sources_locked(self) -> list[dict[str, Any]]:
        parent = self.root / "initial_jae_issuances"
        if not parent.exists():
            return []
        _safe_chain(self.root, parent)
        rows: list[dict[str, Any]] = []
        for path in sorted(parent.iterdir(), key=lambda p: p.name):
            if _reparse(path):
                raise JobAuthorityError("initial issuance source destination is redirected")
            if not path.is_file() or path.suffix != ".json":
                raise JobAuthorityError("initial issuance source directory contains unexpected entry")
            rows.append(self._source(
                path,
                "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_SOURCE_RECORD_V1",
                "initial JAE issuance source",
            ))
        return rows

    def _mint_unique_initial_jae_locked(self, existing_sources: list[dict[str, Any]]) -> str:
        existing_jaes = {row["job_authority_event_id"] for row in existing_sources}
        existing_jaes.update(
            row["successor_job_authority_event_id"]
            for row in self._load_all_controlled_successor_issuance_sources_locked()
        )
        for _ in range(32):
            candidate = "JAE_" + secrets.token_hex(32)
            if candidate in existing_jaes:
                continue
            if self._path_state(self._registration_path(candidate), label="candidate initial JAE registration") == "PRESENT":
                continue
            if self._path_state(self._claim_path(candidate), label="candidate initial JAE successor claim") == "PRESENT":
                continue
            return candidate
        raise JobAuthorityError("unable to mint unique opaque initial JAE")

    def issue_or_replay_one_initial_job_authority_event_v1(
        self,
        *,
        job_bundle_binding: R009OpaqueArtifactBinding,
        web_formal_job_intake_binding: R009OpaqueArtifactBinding,
        input_set_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        first = self._validate_initial_issuance_evidence(
            job_bundle_binding=job_bundle_binding,
            web_formal_job_intake_binding=web_formal_job_intake_binding,
            input_set_binding=input_set_binding,
        )
        job_id = first["job_id"]
        path = self._initial_issuance_path(job_id)

        with self._lock():
            second = self._validate_initial_issuance_evidence(
                job_bundle_binding=job_bundle_binding,
                web_formal_job_intake_binding=web_formal_job_intake_binding,
                input_set_binding=input_set_binding,
            )
            if second != first:
                raise JobAuthorityError("initial issuance evidence changed before commit")

            existing_sources = self._load_all_initial_issuance_sources_locked()
            for row in existing_sources:
                if (
                    row["job_lineage_identity_sha256"] == second["job_lineage_identity_sha256"]
                    and row["job_id"] != job_id
                ):
                    raise JobAuthorityError("initial lineage root already bound to another job_id")

            state = self._path_state(path, label="initial JAE issuance destination")
            if state == "PRESENT":
                stored = self._source(
                    path,
                    "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_SOURCE_RECORD_V1",
                    "initial JAE issuance source",
                )
                controlled_sources = self._load_all_controlled_successor_issuance_sources_locked()
                if any(
                    row["successor_job_authority_event_id"] == stored["job_authority_event_id"]
                    for row in controlled_sources
                ):
                    raise JobAuthorityError(
                        "INITIAL_JAE_ISSUANCE_DENIED_CONTROLLED_SUCCESSOR_JAE_ALREADY_ISSUED"
                    )
                compare = dict(stored)
                compare.pop("committed_at_utc")
                expected_replay = {
                    "schema": "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_SOURCE_RECORD_V1",
                    "source_record_revision": 1,
                    "lineage_namespace": "RUNTIME_S1_GENERAL_CHAT_JOB_LINEAGE_IDENTITY_V1",
                    **second,
                    "job_authority_event_id": stored["job_authority_event_id"],
                    "state": "INITIAL_JOB_AUTHORITY_EVENT_ISSUED",
                }
                if compare != expected_replay:
                    raise JobAuthorityError("initial JAE issuance first-writer conflict")
                return stored

            jae = self._mint_unique_initial_jae_locked(existing_sources)
            semantic = {
                "schema": "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_SOURCE_RECORD_V1",
                "source_record_revision": 1,
                "lineage_namespace": "RUNTIME_S1_GENERAL_CHAT_JOB_LINEAGE_IDENTITY_V1",
                **second,
                "job_authority_event_id": jae,
                "state": "INITIAL_JOB_AUTHORITY_EVENT_ISSUED",
            }
            return self._commit_locked(path, semantic)

    def register_or_replay_one_initial_snapshot_for_issued_jae_v1(
        self,
        *,
        registration_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        _reg_manifest, reg_artifact = self._artifact_json_with_manifest(
            registration_binding,
            "issued-initial registration Artifact",
        )
        semantic, reg = self._validate_registration(registration_binding)
        if reg_artifact != reg:
            raise JobAuthorityError("issued-initial registration Artifact changed during validation")
        if (
            reg.get("schema") != "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
            or reg.get("activation_basis") != "INITIAL_JOB_CREATION"
        ):
            raise JobAuthorityError(
                "ISSUED_INITIAL_REGISTRATION_REQUIRES_V2_INITIAL_JOB_CREATION"
            )
        jae = semantic["job_authority_event_id"]

        with self._lock():
            reg_manifest2, reg_artifact2 = self._artifact_json_with_manifest(
                registration_binding,
                "issued-initial registration Artifact under Job lock",
            )
            semantic2, reg2 = self._validate_registration(registration_binding)
            if (
                semantic2 != semantic
                or reg2 != reg
                or reg_artifact2 != reg_artifact
            ):
                raise JobAuthorityError(
                    "issued-initial registration evidence changed before commit"
                )

            matches = [
                row
                for row in self._load_all_initial_issuance_sources_locked()
                if row["job_authority_event_id"] == jae
            ]
            if len(matches) != 1:
                raise JobAuthorityError(
                    "INITIAL_REGISTRATION_REQUIRES_EXACT_OWNER_ISSUANCE_SOURCE"
                )
            issuance = matches[0]
            if reg_manifest2.job_id != issuance["job_id"]:
                raise JobAuthorityError(
                    "issued-initial registration Artifact job differs from issuance source"
                )

            claim_state = self._path_state(
                self._claim_path(jae),
                label="issued-initial successor lineage claim destination",
            )
            if claim_state == "PRESENT":
                self.load_exact_successor_lineage_claim_v1(jae)
                raise JobAuthorityError("SUCCESSOR_INITIAL_REGISTRATION_BYPASS_DENIED")
            controlled_sources = self._load_all_controlled_successor_issuance_sources_locked()
            if any(
                row["successor_job_authority_event_id"] == jae
                for row in controlled_sources
            ):
                raise JobAuthorityError("SUCCESSOR_INITIAL_REGISTRATION_BYPASS_DENIED")

            snapshot_binding = R009OpaqueArtifactBinding(
                reg2["job_execution_authority_snapshot_artifact_identity_sha256"],
                reg2["job_execution_authority_snapshot_artifact_revision"],
                reg2["job_execution_authority_snapshot_artifact_sha256"],
            )
            snapshot, jxs = self._validate_snapshot(snapshot_binding, jae)
            if jxs != reg2["job_execution_authority_snapshot_id"]:
                raise JobAuthorityError(
                    "issued-initial registration JXS differs from exact snapshot"
                )
            if (
                snapshot.get("job_lineage_identity_sha256")
                != issuance["job_lineage_identity_sha256"]
            ):
                raise JobAuthorityError(
                    "issued-initial snapshot lineage differs from issuance source"
                )
            if snapshot.get("input_set_sha256") != issuance["input_set_sha256"]:
                raise JobAuthorityError(
                    "issued-initial snapshot input-set differs from issuance source"
                )
            expected_authority_binding_sha = sha256_bytes(_canonical({
                "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
                "job_authority_event_id": jae,
                "job_lineage_identity_sha256": issuance["job_lineage_identity_sha256"],
            }))
            if reg2.get("job_authority_binding_sha256") != expected_authority_binding_sha:
                raise JobAuthorityError(
                    "issued-initial registration authority binding differs from issuance source"
                )
            if snapshot.get("job_authority_binding_sha256") != expected_authority_binding_sha:
                raise JobAuthorityError(
                    "issued-initial snapshot authority binding differs from issuance source"
                )
            return self._commit_locked(self._registration_path(jae), semantic2)

    def _validate_snapshot(self, binding: R009OpaqueArtifactBinding, expected_jae: str) -> tuple[dict[str, Any], str]:
        snapshot = self._artifact_json(binding, "snapshot Artifact")
        if snapshot.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1":
            raise JobAuthorityError("snapshot schema mismatch")
        if snapshot.get("job_authority_event_id") != expected_jae:
            raise JobAuthorityError("snapshot JAE mismatch")
        jxs = "JXS_" + sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
            "job_authority_event_id": expected_jae,
            "snapshot_content_sha256": binding.artifact_sha256,
        }))
        return snapshot, jxs

    def _validate_registration(self, binding: R009OpaqueArtifactBinding) -> tuple[dict[str, Any], dict[str, Any]]:
        reg = self._artifact_json(binding, "registration Artifact")
        schema = reg.get("schema")
        if schema == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2":
            _exact_fields(reg, _REG_V2_FIELDS, "V2 registration")
        elif schema == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V3":
            _exact_fields(reg, _REG_V3_FIELDS, "V3 registration")
        else:
            raise JobAuthorityError("registration schema invalid")
        if reg.get("registration_revision") != 1 or reg.get("state") != "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT":
            raise JobAuthorityError("registration revision/state invalid")

        jae = _jae(reg.get("job_authority_event_id"))
        snap_binding = R009OpaqueArtifactBinding(
            reg.get("job_execution_authority_snapshot_artifact_identity_sha256"),
            reg.get("job_execution_authority_snapshot_artifact_revision"),
            reg.get("job_execution_authority_snapshot_artifact_sha256"),
        )
        _snapshot, computed_jxs = self._validate_snapshot(snap_binding, jae)
        if (
            reg.get("job_execution_authority_snapshot_id") != computed_jxs
            or reg.get("job_execution_authority_snapshot_sha256") != snap_binding.artifact_sha256
        ):
            raise JobAuthorityError("registration snapshot binding mismatch")

        activation = reg.get("activation_basis")
        if schema.endswith("_V2"):
            if activation == "INITIAL_JOB_CREATION":
                if (
                    reg.get("predecessor_approval_slot_key_sha256") is not None
                    or reg.get("predecessor_invalidation_sha256") is not None
                    or reg.get("job_transition_intent_sha256") is not None
                ):
                    raise JobAuthorityError("INITIAL_JOB_CREATION V2 predecessor fields must be null")
            elif activation in _V2_CONTROLLED:
                _sha(reg.get("predecessor_approval_slot_key_sha256"), "predecessor approval slot")
                _sha(reg.get("predecessor_invalidation_sha256"), "predecessor invalidation")
                _sha(reg.get("job_transition_intent_sha256"), "job transition intent")
            else:
                raise JobAuthorityError("V2 activation_basis invalid")
        else:
            if activation not in _V3_CONTROLLED:
                raise JobAuthorityError("V3 activation_basis invalid")
            _jae(reg.get("predecessor_job_authority_event_id"))
            _jxs(reg.get("predecessor_job_execution_authority_snapshot_id"))
            _sha(reg.get("predecessor_job_execution_authority_snapshot_sha256"), "predecessor snapshot SHA")
            _sha(reg.get("predecessor_job_execution_snapshot_registration_sha256"), "predecessor registration SHA")
            _sha(reg.get("preapproval_branch_key_sha256"), "preapproval branch key")
            _sha(reg.get("preapproval_branch_selection_semantic_sha256"), "branch semantic SHA")
            R009OpaqueArtifactBinding(
                reg.get("preapproval_branch_selection_artifact_identity_sha256"),
                reg.get("preapproval_branch_selection_artifact_revision"),
                reg.get("preapproval_branch_selection_artifact_sha256"),
            )
            _sha(reg.get("preapproval_transition_intent_sha256"), "preapproval transition intent")
            R009OpaqueArtifactBinding(
                reg.get("preapproval_transition_intent_artifact_identity_sha256"),
                reg.get("preapproval_transition_intent_artifact_revision"),
                reg.get("preapproval_transition_intent_artifact_sha256"),
            )
            if reg.get("predecessor_approval_slot_key_sha256") is not None or reg.get("predecessor_invalidation_sha256") is not None:
                raise JobAuthorityError("V3 approval-slot/invalidation fields must be null")
            dre_fields = (
                reg.get("predecessor_decision_request_event_id"),
                reg.get("predecessor_decision_request_identity_sha256"),
                reg.get("predecessor_nonapproval_terminal_binding_sha256"),
                reg.get("predecessor_nonapproval_terminal_artifact_identity_sha256"),
                reg.get("predecessor_nonapproval_terminal_artifact_revision"),
                reg.get("predecessor_nonapproval_terminal_artifact_sha256"),
            )
            if activation == "CONTROLLED_SUCCESSOR_AFTER_PRE_DRE_SUPERSESSION":
                if any(v is not None for v in dre_fields):
                    raise JobAuthorityError("pre-DRE successor DRE/terminal fields must be null")
            else:
                if any(v is None for v in dre_fields):
                    raise JobAuthorityError("DRE-pending successor requires all DRE/terminal fields")
                _dre = reg.get("predecessor_decision_request_event_id")
                if not isinstance(_dre, str) or re.fullmatch(r"DRE_[0-9a-f]{64}", _dre) is None:
                    raise JobAuthorityError("predecessor DRE invalid")
                _sha(reg.get("predecessor_decision_request_identity_sha256"), "predecessor request identity")
                _sha(reg.get("predecessor_nonapproval_terminal_binding_sha256"), "nonapproval terminal binding")
                R009OpaqueArtifactBinding(
                    reg.get("predecessor_nonapproval_terminal_artifact_identity_sha256"),
                    reg.get("predecessor_nonapproval_terminal_artifact_revision"),
                    reg.get("predecessor_nonapproval_terminal_artifact_sha256"),
                )

        semantic = {
            "schema": "RUNTIME_JOB_AUTHORITY_REGISTRATION_SOURCE_RECORD_V1",
            "source_record_revision": 1,
            "job_authority_event_id": jae,
            "job_execution_authority_snapshot_id": computed_jxs,
            "job_execution_authority_snapshot_sha256": snap_binding.artifact_sha256,
            "registration_sha256": binding.artifact_sha256,
            "registration_artifact_identity_sha256": binding.artifact_identity_sha256,
            "registration_artifact_revision": 1,
            "registration_artifact_sha256": binding.artifact_sha256,
            "state": "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT",
        }
        return semantic, reg

    def load_exact_successor_lineage_claim_v1(self, successor_job_authority_event_id: str) -> dict[str, Any]:
        path = self._claim_path(successor_job_authority_event_id)
        if self._path_state(path, label="successor lineage claim") != "PRESENT":
            raise JobAuthorityError("successor lineage claim is absent")
        claim = _json(path.read_bytes(), "successor lineage claim")
        schema = claim.get("schema")
        if schema not in {
            "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V1",
            "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V2",
        }:
            raise JobAuthorityError("successor lineage claim schema invalid")
        self._validate_source_record(
            claim,
            expected_schema=schema,
            label="successor lineage claim",
        )
        if (
            claim.get("successor_job_authority_event_id") != successor_job_authority_event_id
            or claim.get("state") != "PREPARED_NON_EXECUTION_ELIGIBLE"
        ):
            raise JobAuthorityError("successor lineage claim binding/state mismatch")
        if schema.endswith("_V2"):
            _sha(
                claim.get("controlled_successor_jae_issuance_key_sha256"),
                "claim controlled successor issuance key",
            )
            _sha(
                claim.get("controlled_successor_jae_issuance_source_record_sha256"),
                "claim controlled successor issuance source SHA",
            )
        _jxs(claim.get("successor_job_execution_authority_snapshot_id"))
        _sha(claim.get("successor_job_execution_authority_snapshot_sha256"), "claim successor snapshot SHA")
        R009OpaqueArtifactBinding(
            claim.get("successor_snapshot_artifact_identity_sha256"),
            claim.get("successor_snapshot_artifact_revision"),
            claim.get("successor_snapshot_artifact_sha256"),
        )
        if claim.get("transition_intent_schema") not in _ALLOWED_INTENT_SCHEMAS:
            raise JobAuthorityError("successor lineage claim transition schema invalid")
        _sha(claim.get("transition_intent_sha256"), "claim transition intent SHA")
        R009OpaqueArtifactBinding(
            claim.get("transition_intent_artifact_identity_sha256"),
            claim.get("transition_intent_artifact_revision"),
            claim.get("transition_intent_artifact_sha256"),
        )
        return claim

    def _validate_issuance_for_transition_intent(
        self,
        *,
        intent: dict[str, Any],
        successor_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        successor_jae = _jae(intent.get("successor_job_authority_event_id"))
        with self._lock():
            source = self._controlled_successor_issuance_source_by_jae_locked(successor_jae)
        self._validate_controlled_successor_issuance_source(source)

        if (
            source["transition_intent_schema"] != intent.get("schema")
            or source["transition_code"] != intent.get("transition_code")
            or source["predecessor_job_authority_event_id"]
            != intent.get("predecessor_job_authority_event_id")
            or source["job_lineage_identity_sha256"]
            != successor_snapshot.get("job_lineage_identity_sha256")
        ):
            raise JobAuthorityError("successor transition does not bind owner-issued successor JAE source")

        if intent.get("schema") == "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1":
            stage = _validate_preapproval_transition_stage_matrix(intent)
            if source["transition_stage"] != stage:
                raise JobAuthorityError("successor issuance/preapproval stage mismatch")
            if (
                source["predecessor_job_execution_authority_snapshot_id"]
                != intent.get("predecessor_job_execution_authority_snapshot_id")
                or source["predecessor_job_execution_authority_snapshot_sha256"]
                != intent.get("predecessor_job_execution_authority_snapshot_sha256")
                or source["predecessor_job_execution_snapshot_registration_sha256"]
                != intent.get("predecessor_job_execution_snapshot_registration_sha256")
                or source["predecessor_decision_request_event_id"]
                != intent.get("predecessor_decision_request_event_id")
                or source["predecessor_decision_request_identity_sha256"]
                != intent.get("predecessor_decision_request_identity_sha256")
            ):
                raise JobAuthorityError("successor issuance/preapproval predecessor tuple mismatch")
        else:
            if source["transition_stage"] != "APPROVED_SLOT_UNCLAIMED":
                raise JobAuthorityError("approved-slot transition requires approved-slot successor issuance")
            if (
                source["predecessor_job_execution_authority_snapshot_id"]
                != intent.get("predecessor_job_execution_authority_snapshot_id")
                or source["predecessor_approval_decision_event_id"]
                != intent.get("predecessor_approval_decision_event_id")
                or source["predecessor_approval_slot_key_sha256"]
                != intent.get("predecessor_approval_slot_key_sha256")
            ):
                raise JobAuthorityError("successor issuance/approved-slot predecessor tuple mismatch")

        expected_authority_binding_sha = sha256_bytes(_canonical({
            "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
            "job_authority_event_id": successor_jae,
            "job_lineage_identity_sha256": source["job_lineage_identity_sha256"],
        }))
        if successor_snapshot.get("job_authority_binding_sha256") != expected_authority_binding_sha:
            raise JobAuthorityError("successor snapshot authority binding does not bind owner-issued JAE")
        return source

    def claim_or_replay_one_transition_bound_successor_lineage_v1(
        self,
        *,
        transition_intent_binding: R009OpaqueArtifactBinding,
        successor_snapshot_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        intent = self._artifact_json(transition_intent_binding, "transition-intent Artifact")
        if intent.get("schema") == "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1":
            _validate_preapproval_transition_stage_matrix(intent)
        elif intent.get("schema") != "RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2":
            raise JobAuthorityError("transition-intent schema invalid")
        if intent.get("successor_activation_required") is not True:
            raise JobAuthorityError("cancel/null-successor intent cannot create lineage claim")
        successor_jae = _jae(intent.get("successor_job_authority_event_id"))
        successor_jxs = _jxs(intent.get("successor_job_execution_authority_snapshot_id"))
        successor_sha = _sha(intent.get("successor_job_execution_authority_snapshot_sha256"), "successor snapshot SHA")
        successor_snapshot, computed_jxs = self._validate_snapshot(
            successor_snapshot_binding,
            successor_jae,
        )
        issuance_source = self._validate_issuance_for_transition_intent(
            intent=intent,
            successor_snapshot=successor_snapshot,
        )
        issuance_source_sha = sha256_bytes(_canonical(issuance_source))
        if (
            successor_jxs != computed_jxs
            or successor_sha != successor_snapshot_binding.artifact_sha256
            or intent.get("successor_job_execution_authority_snapshot_artifact_identity_sha256") != successor_snapshot_binding.artifact_identity_sha256
            or intent.get("successor_job_execution_authority_snapshot_artifact_revision") != 1
            or intent.get("successor_job_execution_authority_snapshot_artifact_sha256") != successor_snapshot_binding.artifact_sha256
        ):
            raise JobAuthorityError("successor lineage claim tuple mismatch")

        semantic = {
            "schema": "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V2",
            "source_record_revision": 1,
            "successor_job_authority_event_id": successor_jae,
            "controlled_successor_jae_issuance_key_sha256":
                issuance_source["controlled_successor_jae_issuance_key_sha256"],
            "controlled_successor_jae_issuance_source_record_sha256": issuance_source_sha,
            "successor_job_execution_authority_snapshot_id": successor_jxs,
            "successor_job_execution_authority_snapshot_sha256": successor_sha,
            "successor_snapshot_artifact_identity_sha256": successor_snapshot_binding.artifact_identity_sha256,
            "successor_snapshot_artifact_revision": 1,
            "successor_snapshot_artifact_sha256": successor_snapshot_binding.artifact_sha256,
            "transition_intent_schema": intent["schema"],
            "transition_intent_sha256": transition_intent_binding.artifact_sha256,
            "transition_intent_artifact_identity_sha256": transition_intent_binding.artifact_identity_sha256,
            "transition_intent_artifact_revision": 1,
            "transition_intent_artifact_sha256": transition_intent_binding.artifact_sha256,
            "state": "PREPARED_NON_EXECUTION_ELIGIBLE",
        }

        with self._lock():
            intent2 = self._artifact_json(transition_intent_binding, "transition intent under Job lock")
            snapshot2, jxs2 = self._validate_snapshot(successor_snapshot_binding, successor_jae)
            issuance_source2 = self._controlled_successor_issuance_source_by_jae_locked(
                successor_jae
            )
            if (
                intent2 != intent
                or snapshot2 != successor_snapshot
                or jxs2 != successor_jxs
                or issuance_source2 != issuance_source
            ):
                raise JobAuthorityError("lineage-claim evidence changed before commit")
            initial_sources = self._load_all_initial_issuance_sources_locked()
            for row in initial_sources:
                if row["job_authority_event_id"] == successor_jae:
                    raise JobAuthorityError(
                        "SUCCESSOR_LINEAGE_CLAIM_DENIED_INITIAL_JAE_ALREADY_ISSUED"
                    )
            reg_state = self._path_state(self._registration_path(successor_jae), label="successor registration destination")
            if reg_state == "PRESENT":
                self._registration_source(successor_jae)
                raise JobAuthorityError("SUCCESSOR_LINEAGE_CLAIM_DENIED_INITIAL_REGISTRATION_ALREADY_EXISTS")
            claim_path = self._claim_path(successor_jae)
            if self._path_state(claim_path, label="successor lineage claim destination") == "PRESENT":
                existing_claim = self.load_exact_successor_lineage_claim_v1(successor_jae)
                if existing_claim.get("schema") == "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V1":
                    raise JobAuthorityError(
                        "LEGACY_SUCCESSOR_LINEAGE_CLAIM_V1_READ_ONLY_NOT_WRITABLE_OR_REPLAYABLE"
                    )
            return self._commit_locked(claim_path, semantic)

    def _validate_controlled_claim(self, reg: dict[str, Any]) -> dict[str, Any]:
        jae = reg["job_authority_event_id"]
        claim = self.load_exact_successor_lineage_claim_v1(jae)
        if claim.get("schema") != "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V2":
            raise JobAuthorityError(
                "LEGACY_SUCCESSOR_LINEAGE_CLAIM_V1_READ_ONLY_NOT_ACTIVATABLE"
            )
        if (
            claim["successor_job_execution_authority_snapshot_id"] != reg["job_execution_authority_snapshot_id"]
            or claim["successor_job_execution_authority_snapshot_sha256"] != reg["job_execution_authority_snapshot_sha256"]
            or claim["successor_snapshot_artifact_identity_sha256"] != reg["job_execution_authority_snapshot_artifact_identity_sha256"]
            or claim["successor_snapshot_artifact_revision"] != reg["job_execution_authority_snapshot_artifact_revision"]
            or claim["successor_snapshot_artifact_sha256"] != reg["job_execution_authority_snapshot_artifact_sha256"]
        ):
            raise JobAuthorityError("controlled successor registration snapshot does not match lineage claim")
        if reg["schema"].endswith("_V2"):
            if claim["transition_intent_schema"] != "RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2":
                raise JobAuthorityError("V2 controlled successor requires approved-slot lineage claim")
            if claim["transition_intent_sha256"] != reg.get("job_transition_intent_sha256"):
                raise JobAuthorityError("V2 controlled successor transition SHA does not match lineage claim")
        else:
            if claim["transition_intent_schema"] != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1":
                raise JobAuthorityError("V3 controlled successor requires preapproval lineage claim")
            if (
                claim["transition_intent_sha256"] != reg.get("preapproval_transition_intent_sha256")
                or claim["transition_intent_artifact_identity_sha256"] != reg.get("preapproval_transition_intent_artifact_identity_sha256")
                or claim["transition_intent_artifact_revision"] != reg.get("preapproval_transition_intent_artifact_revision")
                or claim["transition_intent_artifact_sha256"] != reg.get("preapproval_transition_intent_artifact_sha256")
            ):
                raise JobAuthorityError("V3 controlled successor transition tuple does not match lineage claim")
        return claim

    def register_or_replay_one_active_snapshot_for_jae_v1(
        self,
        *,
        registration_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        semantic, reg = self._validate_registration(registration_binding)
        jae = semantic["job_authority_event_id"]
        if reg["schema"].endswith("_V3"):
            raise JobAuthorityError("V3 controlled successor requires ACTIVATE_OR_REPLAY_EXACT_PREAPPROVAL_SUCCESSOR_V1")

        with self._lock():
            semantic2, reg2 = self._validate_registration(registration_binding)
            if semantic2 != semantic or reg2 != reg:
                raise JobAuthorityError("registration evidence changed before commit")
            if reg2["activation_basis"] == "INITIAL_JOB_CREATION":
                successor_issuances = [
                    row
                    for row in self._load_all_controlled_successor_issuance_sources_locked()
                    if row["successor_job_authority_event_id"] == jae
                ]
                if successor_issuances:
                    if len(successor_issuances) != 1:
                        raise JobAuthorityError(
                            "INITIAL_REGISTRATION_DENIED_AMBIGUOUS_CONTROLLED_SUCCESSOR_ISSUANCE"
                        )
                    raise JobAuthorityError(
                        "SUCCESSOR_INITIAL_REGISTRATION_BYPASS_DENIED"
                    )
                claim_state = self._path_state(self._claim_path(jae), label="successor lineage claim destination")
                if claim_state == "PRESENT":
                    self.load_exact_successor_lineage_claim_v1(jae)
                    raise JobAuthorityError("SUCCESSOR_INITIAL_REGISTRATION_BYPASS_DENIED")
            else:
                self._validate_controlled_claim(reg2)
                if (
                    reg2.get("schema") == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
                    and reg2.get("activation_basis")
                    == "CONTROLLED_SUCCESSOR_AFTER_PREDECESSOR_INVALIDATION"
                ):
                    self._validate_v2_invalidation_terminal_for_registration_locked(reg2)
            return self._commit_locked(self._registration_path(jae), semantic2)

    def _registration_source(self, jae: str) -> dict[str, Any]:
        src = self._source(
            self._registration_path(jae),
            "RUNTIME_JOB_AUTHORITY_REGISTRATION_SOURCE_RECORD_V1",
            "active registration source",
        )
        if src.get("job_authority_event_id") != jae:
            raise JobAuthorityError("registration source JAE mismatch")
        return src

    def load_exact_active_registration_source_by_jae_v1(
        self,
        *,
        job_authority_event_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], R009OpaqueArtifactBinding]:
        jae = _jae(job_authority_event_id)
        source = self._registration_source(jae)
        binding = R009OpaqueArtifactBinding(
            source["registration_artifact_identity_sha256"],
            source["registration_artifact_revision"],
            source["registration_artifact_sha256"],
        )
        expected, reg = self._validate_registration(binding)
        compare = dict(source)
        compare.pop("committed_at_utc")
        if expected != compare:
            raise JobAuthorityError("active registration source/Artifact mismatch")
        return source, reg, binding

    def _branch_semantic(self, branch: dict[str, Any], binding: R009OpaqueArtifactBinding) -> dict[str, Any]:
        key = _sha(branch.get("preapproval_branch_key_sha256"), "branch key")
        code = branch.get("branch_code")
        if code not in _ALLOWED_BRANCH_CODES:
            raise JobAuthorityError("branch code invalid")

        expected_key = sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_PREAPPROVAL_BRANCH_KEY_V1",
            "predecessor_job_authority_event_id": branch.get("predecessor_job_authority_event_id"),
            "predecessor_job_execution_authority_snapshot_id": branch.get("predecessor_job_execution_authority_snapshot_id"),
            "predecessor_job_execution_authority_snapshot_sha256": branch.get("predecessor_job_execution_authority_snapshot_sha256"),
            "predecessor_job_execution_snapshot_registration_sha256": branch.get("predecessor_job_execution_snapshot_registration_sha256"),
        }))
        if key != expected_key:
            raise JobAuthorityError("preapproval branch key does not recompute")

        if code == "DRE_ISSUANCE_SELECTED":
            _exact_fields(branch, _BRANCH_V2_FIELDS, "DRE V2 branch")
            v3 = branch.get("decision_request_binding_v3")
            if not isinstance(v3, dict):
                raise JobAuthorityError("DRE branch missing complete V3")
            _exact_fields(v3, _V3_FIELDS, "complete V3 request binding")
            if v3.get("schema") != "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_BINDING_V3":
                raise JobAuthorityError("complete V3 schema mismatch")

            snapshot_binding = R009OpaqueArtifactBinding(
                v3["job_execution_authority_snapshot_artifact_identity_sha256"],
                v3["job_execution_authority_snapshot_artifact_revision"],
                v3["job_execution_authority_snapshot_artifact_sha256"],
            )
            registration_binding = R009OpaqueArtifactBinding(
                v3["job_execution_snapshot_registration_artifact_identity_sha256"],
                v3["job_execution_snapshot_registration_artifact_revision"],
                v3["job_execution_snapshot_registration_artifact_sha256"],
            )
            request_binding = R009OpaqueArtifactBinding(
                v3["decision_request_content_artifact_identity_sha256"],
                v3["decision_request_content_artifact_revision"],
                v3["decision_request_content_artifact_sha256"],
            )
            _snapshot, computed_jxs = self._validate_snapshot(snapshot_binding, _jae(v3["job_authority_event_id"]))
            _expected_reg_source, registration = self._validate_registration(registration_binding)
            request_content = self._artifact_json(request_binding, "request-content Artifact")
            if (
                computed_jxs != v3["job_execution_authority_snapshot_id"]
                or snapshot_binding.artifact_sha256 != v3["job_execution_authority_snapshot_sha256"]
                or registration_binding.artifact_sha256 != v3["job_execution_snapshot_registration_sha256"]
                or registration["job_authority_event_id"] != v3["job_authority_event_id"]
                or registration["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
                or registration["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
                or request_binding.artifact_sha256 != v3["decision_request_content_sha256"]
            ):
                raise JobAuthorityError("DRE branch exact Artifact/V3 binding mismatch")
            expected_content_fields = {
                "schema","job_authority_event_id","job_execution_authority_snapshot_id",
                "job_execution_authority_snapshot_sha256","requested_decision_code","live_attempts_max",
                "model_calls_max","network_calls_max","retries_max","fallback_allowed",
            }
            _exact_fields(request_content, frozenset(expected_content_fields), "request-content semantic")
            if (
                request_content["schema"] != "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_CONTENT_SEMANTIC_V1"
                or request_content["job_authority_event_id"] != v3["job_authority_event_id"]
                or request_content["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
                or request_content["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
                or request_content["requested_decision_code"] != "APPROVE_ONE_LIVE_ATTEMPT"
                or request_content["live_attempts_max"] != 1 or v3["live_attempts_max"] != 1
                or request_content["model_calls_max"] != 1 or v3["model_calls_max"] != 1
                or request_content["network_calls_max"] != 1 or v3["network_calls_max"] != 1
                or request_content["retries_max"] != 0 or v3["retries_max"] != 0
                or request_content["fallback_allowed"] is not False or v3["fallback_allowed"] is not False
            ):
                raise JobAuthorityError("DRE request-content/V3 mismatch")

            request_key = sha256_bytes(_canonical({
                "namespace": "RUNTIME_LIVE_EXECUTION_ONE_REQUEST_PER_ACTIVE_SNAPSHOT_V1",
                "job_authority_event_id": v3["job_authority_event_id"],
                "job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
                "job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
                "job_execution_snapshot_registration_sha256": v3["job_execution_snapshot_registration_sha256"],
            }))
            identity = sha256_bytes(_canonical(v3))
            pairs = {
                "snapshot_decision_request_key_sha256": request_key,
                "decision_request_event_id": "DRE_" + request_key,
                "decision_request_identity_sha256": identity,
                "predecessor_job_authority_event_id": v3["job_authority_event_id"],
                "predecessor_job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
                "predecessor_job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
                "predecessor_job_execution_snapshot_registration_sha256": v3["job_execution_snapshot_registration_sha256"],
            }
            for field, expected in pairs.items():
                if branch[field] != expected:
                    raise JobAuthorityError(f"DRE branch/V3 mismatch: {field}")
            if v3["snapshot_decision_request_key_sha256"] != request_key:
                raise JobAuthorityError("complete V3 request key mismatch")
            if branch["request_recovery_mode"] != "INLINE_COMPLETE_REQUEST_BINDING_V3":
                raise JobAuthorityError("DRE branch recovery mode mismatch")

        else:
            _exact_fields(branch, _BRANCH_V1_FIELDS, "pre-DRE V1 branch")
            if branch.get("schema") != "RUNTIME_JOB_PREAPPROVAL_BRANCH_SELECTION_SEMANTIC_V1":
                raise JobAuthorityError("transition/cancel branch must use V1")
            intent_binding = R009OpaqueArtifactBinding(
                branch["preapproval_transition_intent_artifact_identity_sha256"],
                branch["preapproval_transition_intent_artifact_revision"],
                branch["preapproval_transition_intent_artifact_sha256"],
            )
            intent = self._artifact_json(intent_binding, "preapproval transition-intent Artifact")
            _validate_preapproval_transition_stage_matrix(
                intent,
                expected_stage="ACTIVE_PREDECESSOR_NO_DRE",
                label="preapproval branch transition intent",
            )
            if (
                intent["schema"] != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1"
                or branch["preapproval_transition_intent_sha256"] != intent_binding.artifact_sha256
                or intent["predecessor_job_authority_event_id"] != branch["predecessor_job_authority_event_id"]
                or intent["predecessor_job_execution_authority_snapshot_id"] != branch["predecessor_job_execution_authority_snapshot_id"]
                or intent["predecessor_job_execution_authority_snapshot_sha256"] != branch["predecessor_job_execution_authority_snapshot_sha256"]
                or intent["predecessor_job_execution_snapshot_registration_sha256"] != branch["predecessor_job_execution_snapshot_registration_sha256"]
            ):
                raise JobAuthorityError("transition/cancel branch intent binding mismatch")
            if code == "PRE_DRE_CANCEL_SELECTED":
                if (
                    intent["transition_code"] != "CONTROLLED_CANCEL"
                    or intent["successor_activation_required"] is not False
                    or any(branch[f] is not None for f in (
                        "successor_job_authority_event_id","successor_job_execution_authority_snapshot_id",
                        "successor_job_execution_authority_snapshot_sha256",
                        "successor_job_execution_authority_snapshot_artifact_identity_sha256",
                        "successor_job_execution_authority_snapshot_artifact_revision",
                        "successor_job_execution_authority_snapshot_artifact_sha256"))
                ):
                    raise JobAuthorityError("cancel branch matrix mismatch")
            else:
                if (
                    intent["transition_code"] not in {"CONTROLLED_REOPEN_MATERIAL_INPUT_CHANGE","CONTROLLED_REOPEN_RUNTIME_MIGRATION"}
                    or intent["successor_activation_required"] is not True
                ):
                    raise JobAuthorityError("supersession branch intent mismatch")
                successor_binding = R009OpaqueArtifactBinding(
                    branch["successor_job_execution_authority_snapshot_artifact_identity_sha256"],
                    branch["successor_job_execution_authority_snapshot_artifact_revision"],
                    branch["successor_job_execution_authority_snapshot_artifact_sha256"],
                )
                _succ, succ_jxs = self._validate_snapshot(successor_binding, _jae(branch["successor_job_authority_event_id"]))
                if (
                    succ_jxs != branch["successor_job_execution_authority_snapshot_id"]
                    or successor_binding.artifact_sha256 != branch["successor_job_execution_authority_snapshot_sha256"]
                    or intent["successor_job_authority_event_id"] != branch["successor_job_authority_event_id"]
                    or intent["successor_job_execution_authority_snapshot_id"] != branch["successor_job_execution_authority_snapshot_id"]
                    or intent["successor_job_execution_authority_snapshot_sha256"] != branch["successor_job_execution_authority_snapshot_sha256"]
                    or intent["successor_job_execution_authority_snapshot_artifact_identity_sha256"] != branch["successor_job_execution_authority_snapshot_artifact_identity_sha256"]
                    or intent["successor_job_execution_authority_snapshot_artifact_revision"] != branch["successor_job_execution_authority_snapshot_artifact_revision"]
                    or intent["successor_job_execution_authority_snapshot_artifact_sha256"] != branch["successor_job_execution_authority_snapshot_artifact_sha256"]
                ):
                    raise JobAuthorityError("supersession branch successor mismatch")

        return {
            "schema": "RUNTIME_JOB_AUTHORITY_PREAPPROVAL_BRANCH_SOURCE_RECORD_V1",
            "source_record_revision": 1,
            "preapproval_branch_key_sha256": key,
            "branch_code": code,
            "branch_selection_semantic_sha256": binding.artifact_sha256,
            "branch_artifact_identity_sha256": binding.artifact_identity_sha256,
            "branch_artifact_revision": 1,
            "branch_artifact_sha256": binding.artifact_sha256,
        }

    def select_or_replay_one_preapproval_branch_for_active_registration_v2(
        self,
        *,
        branch_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        branch = self._artifact_json(branch_binding, "preapproval branch Artifact")
        semantic = self._branch_semantic(branch, branch_binding)
        jae = _jae(branch.get("predecessor_job_authority_event_id"))
        active = self._registration_source(jae)
        if (
            active["job_execution_authority_snapshot_id"] != branch.get("predecessor_job_execution_authority_snapshot_id")
            or active["job_execution_authority_snapshot_sha256"] != branch.get("predecessor_job_execution_authority_snapshot_sha256")
            or active["registration_sha256"] != branch.get("predecessor_job_execution_snapshot_registration_sha256")
        ):
            raise JobAuthorityError("branch does not bind exact active registration")
        with self._lock():
            branch2 = self._artifact_json(branch_binding, "branch under Job lock")
            semantic2 = self._branch_semantic(branch2, branch_binding)
            active2 = self._registration_source(jae)
            if (
                active2["job_execution_authority_snapshot_id"] != branch2.get("predecessor_job_execution_authority_snapshot_id")
                or active2["job_execution_authority_snapshot_sha256"] != branch2.get("predecessor_job_execution_authority_snapshot_sha256")
                or active2["registration_sha256"] != branch2.get("predecessor_job_execution_snapshot_registration_sha256")
            ):
                raise JobAuthorityError("active registration changed before branch commit")
            return self._commit_locked(self._branch_path(semantic2["preapproval_branch_key_sha256"]), semantic2)

    def load_exact_preapproval_branch_by_key_v1(
        self,
        *,
        preapproval_branch_key_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any], R009OpaqueArtifactBinding]:
        source = self._source(
            self._branch_path(preapproval_branch_key_sha256),
            "RUNTIME_JOB_AUTHORITY_PREAPPROVAL_BRANCH_SOURCE_RECORD_V1",
            "preapproval branch source",
        )
        if source["preapproval_branch_key_sha256"] != preapproval_branch_key_sha256:
            raise JobAuthorityError("branch source key mismatch")
        binding = R009OpaqueArtifactBinding(
            source["branch_artifact_identity_sha256"],
            source["branch_artifact_revision"],
            source["branch_artifact_sha256"],
        )
        branch = self._artifact_json(binding, "exact branch Artifact")
        expected = self._branch_semantic(branch, binding)
        compare = dict(source)
        compare.pop("committed_at_utc", None)
        if expected != compare:
            raise JobAuthorityError("branch source/Artifact mismatch")
        return source, branch, binding

    def activate_or_replay_exact_preapproval_successor_v1(
        self,
        *,
        successor_registration_binding: R009OpaqueArtifactBinding,
        human_decision_authority: Any | None = None,
    ) -> dict[str, Any]:
        semantic, reg = self._validate_registration(successor_registration_binding)
        if reg.get("schema") != "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V3":
            raise JobAuthorityError("preapproval successor activation requires V3 registration")
        self._validate_controlled_claim(reg)

        transition_binding = R009OpaqueArtifactBinding(
            reg["preapproval_transition_intent_artifact_identity_sha256"],
            reg["preapproval_transition_intent_artifact_revision"],
            reg["preapproval_transition_intent_artifact_sha256"],
        )
        transition = self._artifact_json(transition_binding, "preapproval transition-intent Artifact")
        if reg["activation_basis"] == "CONTROLLED_SUCCESSOR_AFTER_PRE_DRE_SUPERSESSION":
            _validate_preapproval_transition_stage_matrix(
                transition,
                expected_stage="ACTIVE_PREDECESSOR_NO_DRE",
                label="pre-DRE successor transition intent",
            )
        else:
            _validate_preapproval_transition_stage_matrix(
                transition,
                expected_stage="DRE_PENDING_NO_TERMINAL_DECISION",
                expected_dre_event_id=reg["predecessor_decision_request_event_id"],
                expected_dre_identity_sha256=reg["predecessor_decision_request_identity_sha256"],
                label="DRE-pending successor transition intent",
            )
        if (
            transition["schema"] != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1"
            or transition_binding.artifact_sha256 != reg["preapproval_transition_intent_sha256"]
            or transition["successor_job_authority_event_id"] != reg["job_authority_event_id"]
            or transition["successor_job_execution_authority_snapshot_id"] != reg["job_execution_authority_snapshot_id"]
            or transition["successor_job_execution_authority_snapshot_sha256"] != reg["job_execution_authority_snapshot_sha256"]
        ):
            raise JobAuthorityError("V3 registration transition-intent binding mismatch")

        branch_source, branch, branch_binding = self.load_exact_preapproval_branch_by_key_v1(
            preapproval_branch_key_sha256=reg["preapproval_branch_key_sha256"]
        )
        if (
            branch_source["branch_selection_semantic_sha256"] != reg["preapproval_branch_selection_semantic_sha256"]
            or branch_binding.artifact_identity_sha256 != reg["preapproval_branch_selection_artifact_identity_sha256"]
            or branch_binding.artifact_revision != reg["preapproval_branch_selection_artifact_revision"]
            or branch_binding.artifact_sha256 != reg["preapproval_branch_selection_artifact_sha256"]
            or branch["predecessor_job_authority_event_id"] != reg["predecessor_job_authority_event_id"]
            or branch["predecessor_job_execution_authority_snapshot_id"] != reg["predecessor_job_execution_authority_snapshot_id"]
            or branch["predecessor_job_execution_authority_snapshot_sha256"] != reg["predecessor_job_execution_authority_snapshot_sha256"]
            or branch["predecessor_job_execution_snapshot_registration_sha256"] != reg["predecessor_job_execution_snapshot_registration_sha256"]
        ):
            raise JobAuthorityError("V3 registration predecessor branch binding mismatch")

        human_request = None
        human_terminal = None
        if reg["activation_basis"] == "CONTROLLED_SUCCESSOR_AFTER_PRE_DRE_SUPERSESSION":
            if branch_source["branch_code"] != "PRE_DRE_SUPERSESSION_SELECTED":
                raise JobAuthorityError("pre-DRE activation requires PRE_DRE_SUPERSESSION_SELECTED")
            if (
                branch.get("successor_job_authority_event_id") != reg["job_authority_event_id"]
                or branch.get("successor_job_execution_authority_snapshot_id") != reg["job_execution_authority_snapshot_id"]
                or branch.get("successor_job_execution_authority_snapshot_sha256") != reg["job_execution_authority_snapshot_sha256"]
                or branch.get("successor_job_execution_authority_snapshot_artifact_identity_sha256")
                != reg["job_execution_authority_snapshot_artifact_identity_sha256"]
                or branch.get("successor_job_execution_authority_snapshot_artifact_revision")
                != reg["job_execution_authority_snapshot_artifact_revision"]
                or branch.get("successor_job_execution_authority_snapshot_artifact_sha256")
                != reg["job_execution_authority_snapshot_artifact_sha256"]
                or branch.get("preapproval_transition_intent_sha256") != reg["preapproval_transition_intent_sha256"]
                or branch.get("preapproval_transition_intent_artifact_identity_sha256")
                != reg["preapproval_transition_intent_artifact_identity_sha256"]
                or branch.get("preapproval_transition_intent_artifact_revision")
                != reg["preapproval_transition_intent_artifact_revision"]
                or branch.get("preapproval_transition_intent_artifact_sha256")
                != reg["preapproval_transition_intent_artifact_sha256"]
            ):
                raise JobAuthorityError("pre-DRE successor branch/registration mismatch")
        else:
            if branch_source["branch_code"] != "DRE_ISSUANCE_SELECTED":
                raise JobAuthorityError("DRE-pending activation requires DRE_ISSUANCE_SELECTED branch")
            if human_decision_authority is None:
                raise JobAuthorityError("DRE-pending activation requires exact Human Decision source reader")
            human_request = human_decision_authority.load_exact_request_source(
                reg["predecessor_decision_request_event_id"]
            )
            human_terminal = human_decision_authority.load_exact_terminal_source(
                reg["predecessor_decision_request_event_id"]
            )
            if (
                human_request["decision_request_event_id"] != reg["predecessor_decision_request_event_id"]
                or human_request["decision_request_identity_sha256"] != reg["predecessor_decision_request_identity_sha256"]
                or human_request["preapproval_branch_key_sha256"] != reg["preapproval_branch_key_sha256"]
                or human_terminal["terminal_decision_code"] != "SUPERSEDED_FOR_CONTROLLED_REOPEN"
                or human_terminal["decision_request_identity_sha256"] != reg["predecessor_decision_request_identity_sha256"]
                or human_terminal["non_approval_terminal_binding_sha256"] != reg["predecessor_nonapproval_terminal_binding_sha256"]
                or human_terminal["non_approval_terminal_artifact_identity_sha256"] != reg["predecessor_nonapproval_terminal_artifact_identity_sha256"]
                or human_terminal["non_approval_terminal_artifact_revision"] != reg["predecessor_nonapproval_terminal_artifact_revision"]
                or human_terminal["non_approval_terminal_artifact_sha256"] != reg["predecessor_nonapproval_terminal_artifact_sha256"]
            ):
                raise JobAuthorityError("DRE-pending Human source evidence mismatch")
            terminal_binding = R009OpaqueArtifactBinding(
                reg["predecessor_nonapproval_terminal_artifact_identity_sha256"],
                reg["predecessor_nonapproval_terminal_artifact_revision"],
                reg["predecessor_nonapproval_terminal_artifact_sha256"],
            )
            terminal = self._artifact_json(terminal_binding, "non-approval terminal Artifact")
            if (
                terminal.get("schema") != "RUNTIME_NON_APPROVAL_TERMINAL_HUMAN_DECISION_BINDING_V1"
                or terminal.get("terminal_decision_code") != "SUPERSEDED_FOR_CONTROLLED_REOPEN"
                or terminal.get("decision_request_event_id") != reg["predecessor_decision_request_event_id"]
                or terminal.get("decision_request_identity_sha256") != reg["predecessor_decision_request_identity_sha256"]
                or terminal.get("preapproval_transition_intent_sha256") != reg["preapproval_transition_intent_sha256"]
                or terminal.get("successor_job_authority_event_id") != reg["job_authority_event_id"]
                or terminal.get("successor_job_execution_authority_snapshot_id") != reg["job_execution_authority_snapshot_id"]
                or terminal.get("successor_job_execution_authority_snapshot_sha256") != reg["job_execution_authority_snapshot_sha256"]
                or terminal.get("successor_job_execution_authority_snapshot_artifact_identity_sha256")
                != reg["job_execution_authority_snapshot_artifact_identity_sha256"]
                or terminal.get("successor_job_execution_authority_snapshot_artifact_revision")
                != reg["job_execution_authority_snapshot_artifact_revision"]
                or terminal.get("successor_job_execution_authority_snapshot_artifact_sha256")
                != reg["job_execution_authority_snapshot_artifact_sha256"]
            ):
                raise JobAuthorityError("DRE-pending non-approval terminal Artifact mismatch")

        # Job lock begins only after all Human source reads have completed.
        with self._lock():
            semantic2, reg2 = self._validate_registration(successor_registration_binding)
            if semantic2 != semantic or reg2 != reg:
                raise JobAuthorityError("successor registration evidence changed before commit")
            self._validate_controlled_claim(reg2)
            branch_source2, branch2, branch_binding2 = self.load_exact_preapproval_branch_by_key_v1(
                preapproval_branch_key_sha256=reg2["preapproval_branch_key_sha256"]
            )
            if branch_source2 != branch_source or branch2 != branch or branch_binding2 != branch_binding:
                raise JobAuthorityError("Job-owned predecessor branch evidence changed before activation")
            return self._commit_locked(self._registration_path(reg2["job_authority_event_id"]), semantic2)

