"""R010 minimum owner-local Human Decision Authority source implementation candidate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
import uuid

from .artifact_store import ArtifactStore, R009OpaqueArtifactBinding
from .hashing import sha256_bytes
from .job_authority import JobAuthorityRegistry


class HumanDecisionAuthorityError(ValueError):
    pass


_DRE_RE = re.compile(r"^DRE_[0-9a-f]{64}$")
_TERMINALS = {
    "APPROVED",
    "REJECTED",
    "SUPERSEDED_FOR_CONTROLLED_REOPEN",
    "REVOKED_FOR_CONTROLLED_CANCEL",
}
_NONAPP_ACTION = {
    "REJECTED": "REJECT",
    "SUPERSEDED_FOR_CONTROLLED_REOPEN": "SUPERSEDE_FOR_CONTROLLED_REOPEN",
    "REVOKED_FOR_CONTROLLED_CANCEL": "REVOKE_FOR_CONTROLLED_CANCEL",
}


_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")

_V3_FIELDS = frozenset({
    "schema","snapshot_decision_request_key_sha256","decision_request_event_id","job_authority_event_id",
    "job_execution_authority_snapshot_id","job_execution_authority_snapshot_sha256",
    "job_execution_authority_snapshot_artifact_identity_sha256","job_execution_authority_snapshot_artifact_revision",
    "job_execution_authority_snapshot_artifact_sha256","job_execution_snapshot_registration_sha256",
    "job_execution_snapshot_registration_artifact_identity_sha256",
    "job_execution_snapshot_registration_artifact_revision","job_execution_snapshot_registration_artifact_sha256",
    "decision_request_content_sha256","decision_request_content_artifact_identity_sha256",
    "decision_request_content_artifact_revision","decision_request_content_artifact_sha256",
    "decision_scope_sha256","live_attempts_max","model_calls_max","network_calls_max","retries_max","fallback_allowed",
})

_ACTION_APPROVE_FIELDS = frozenset({
    "schema","decision_request_event_id","decision_request_identity_sha256",
    "decision_request_content_sha256","decision_scope_sha256","actor_authority_identity_sha256","action_code",
})

_ACTION_NONAPP_FIELDS = frozenset({
    "schema","decision_request_event_id","decision_request_identity_sha256",
    "decision_request_content_sha256","decision_scope_sha256","actor_authority_identity_sha256",
    "action_code","preapproval_transition_intent_sha256",
})

_APPROVAL_V3_FIELDS = frozenset({
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

_ACCEPTANCE_FIELDS = frozenset({
    "schema","approval_decision_event_id","approval_decision_event_binding_sha256","job_authority_event_id",
    "job_execution_authority_snapshot_id","job_execution_authority_snapshot_sha256",
    "job_execution_snapshot_registration_sha256","decision_request_event_id","decision_request_identity_sha256",
    "human_action_receipt_sha256","decision_scope_sha256","decision_code",
    "live_attempts_max","model_calls_max","network_calls_max","retries_max","fallback_allowed",
})

_NONAPP_TERMINAL_FIELDS = frozenset({
    "schema","job_authority_event_id","job_execution_authority_snapshot_id","job_execution_authority_snapshot_sha256",
    "job_execution_snapshot_registration_sha256","decision_request_event_id","decision_request_identity_sha256",
    "decision_request_content_sha256","decision_scope_sha256","human_action_receipt_sha256",
    "human_action_receipt_artifact_identity_sha256","human_action_receipt_artifact_revision",
    "human_action_receipt_artifact_sha256","terminal_decision_code","preapproval_transition_intent_sha256",
    "preapproval_transition_intent_artifact_identity_sha256","preapproval_transition_intent_artifact_revision",
    "preapproval_transition_intent_artifact_sha256","successor_job_authority_event_id",
    "successor_job_execution_authority_snapshot_id","successor_job_execution_authority_snapshot_sha256",
    "successor_job_execution_authority_snapshot_artifact_identity_sha256",
    "successor_job_execution_authority_snapshot_artifact_revision",
    "successor_job_execution_authority_snapshot_artifact_sha256",
})

_HUMAN_SOURCE_FIELDS = {
    "RUNTIME_HUMAN_DECISION_REQUEST_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","decision_request_event_id","decision_request_identity_sha256",
        "decision_request_preapproval_binding_sha256","preapproval_branch_key_sha256",
        "preapproval_branch_selection_semantic_sha256","preapproval_branch_selection_artifact_identity_sha256",
        "preapproval_branch_selection_artifact_revision","preapproval_branch_selection_artifact_sha256",
        "decision_request_binding_v3","committed_at_utc",
    }),
    "RUNTIME_HUMAN_DECISION_TERMINAL_SOURCE_RECORD_V1": frozenset({
        "schema","source_record_revision","decision_request_event_id","decision_request_identity_sha256",
        "terminal_decision_code","human_action_receipt_sha256","human_action_receipt_artifact_identity_sha256",
        "human_action_receipt_artifact_revision","human_action_receipt_artifact_sha256",
        "approval_decision_event_id","approval_decision_event_binding_sha256",
        "approval_decision_event_artifact_identity_sha256","approval_decision_event_artifact_revision",
        "approval_decision_event_artifact_sha256","approval_acceptance_semantic_sha256",
        "approval_acceptance_artifact_identity_sha256","approval_acceptance_artifact_revision",
        "approval_acceptance_artifact_sha256","non_approval_terminal_binding_sha256",
        "non_approval_terminal_artifact_identity_sha256","non_approval_terminal_artifact_revision",
        "non_approval_terminal_artifact_sha256","committed_at_utc",
    }),
    "RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_SOURCE_V1": frozenset({
        "schema","source_record_revision","actor_authority_identity_sha256",
        "identity_class","use_scope","derivation_class",
        "represents_real_person_identity","provides_authentication",
        "provides_authorization","grants_permission","committed_at_utc",
    }),
}


def _exact_fields(obj: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(obj)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise HumanDecisionAuthorityError(f"{label} exact field-set mismatch missing={missing} extra={extra}")


def _sha64(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise HumanDecisionAuthorityError(f"{label} must be lowercase 64-hex")
    return value


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
        raise HumanDecisionAuthorityError(f"cannot lstat path: {path}") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_chain(root: Path, target: Path) -> None:
    root = _lex(root)
    target = _lex(target)
    if not _inside(target, root):
        raise HumanDecisionAuthorityError("path escapes Human Decision root")
    current = root
    if current.exists() and _reparse(current):
        raise HumanDecisionAuthorityError("Human Decision root redirected")
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and _reparse(current):
            raise HumanDecisionAuthorityError(f"reparse/symlink path forbidden: {current}")


def _dre(v: Any) -> str:
    if not isinstance(v, str) or _DRE_RE.fullmatch(v) is None:
        raise HumanDecisionAuthorityError("DRE invalid")
    return v


def _json(data: bytes, label: str) -> dict[str, Any]:
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HumanDecisionAuthorityError(f"{label} not JSON") from exc
    if not isinstance(obj, dict) or _canonical(obj) != data:
        raise HumanDecisionAuthorityError(f"{label} not exact canonical JSON")
    return obj


class HumanDecisionAuthority:
    def __init__(self, runtime_authority_data_root: Path, artifact_store: ArtifactStore, job_authority: JobAuthorityRegistry):
        self.runtime_authority_data_root = _lex(runtime_authority_data_root)
        self.artifact_store = artifact_store
        self.job_authority = job_authority
        self.root = self.runtime_authority_data_root / "_authoritative" / "human_decision_authority"

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
        path = self.root / ".human_decision.lock"
        if path.exists() and _reparse(path):
            raise HumanDecisionAuthorityError("Human Decision lock redirected")
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

    def _request_path(self, dre: str) -> Path:
        return self.root / "requests" / f"{_dre(dre)}.json"

    def _terminal_path(self, dre: str) -> Path:
        return self.root / "terminals" / f"{_dre(dre)}.json"

    def _local_single_user_actor_identity_path(self) -> Path:
        return self.root / "actor_identities" / "local_single_user_v1.json"

    def _safe_parent(self, final: Path) -> None:
        self._ensure_root()
        if not _inside(_lex(final), _lex(self.root)):
            raise HumanDecisionAuthorityError("source record escapes Human Decision root")
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
            raise HumanDecisionAuthorityError("temp read-back mismatch")
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
            raise HumanDecisionAuthorityError(f"{label} escapes Human Decision root")
        if not root.exists():
            return "ABSENT"
        _safe_chain(root, root)
        parent = final_abs.parent
        if parent.exists():
            _safe_chain(root, parent)
        if not os.path.lexists(final_abs):
            return "ABSENT"
        if _reparse(final_abs):
            raise HumanDecisionAuthorityError(f"{label} is redirected")
        if not final_abs.is_file():
            raise HumanDecisionAuthorityError(f"{label} is not a regular file")
        return "PRESENT"

    @staticmethod
    def _validate_source_record(record: dict[str, Any], *, expected_schema: str, label: str) -> None:
        expected = _HUMAN_SOURCE_FIELDS.get(expected_schema)
        if expected is None:
            raise HumanDecisionAuthorityError(f"unsupported source schema: {expected_schema}")
        _exact_fields(record, expected, label)
        if record.get("schema") != expected_schema or record.get("source_record_revision") != 1:
            raise HumanDecisionAuthorityError(f"{label} schema/revision mismatch")
        ts = record.get("committed_at_utc")
        if not isinstance(ts, str) or _TIMESTAMP_RE.fullmatch(ts) is None:
            raise HumanDecisionAuthorityError(f"{label} committed_at_utc invalid")
        if expected_schema == "RUNTIME_HUMAN_DECISION_REQUEST_SOURCE_RECORD_V1":
            v3 = record.get("decision_request_binding_v3")
            if not isinstance(v3, dict):
                raise HumanDecisionAuthorityError("request source V3 is not an object")
            _exact_fields(v3, _V3_FIELDS, "request source complete V3")
        elif expected_schema == "RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_SOURCE_V1":
            _sha64(record.get("actor_authority_identity_sha256"), "local opaque actor authority identity")
            if (
                record.get("identity_class") != "LOCAL_SINGLE_USER_OPAQUE"
                or record.get("use_scope") != "EXPLICIT_HUMAN_DECISION_ACTION_IDENTITY_BINDING_ONLY"
                or record.get("derivation_class") != "RUNTIME_RANDOM_LOCAL_OPAQUE_NOT_PERSONAL_DATA_DERIVED"
                or record.get("represents_real_person_identity") is not False
                or record.get("provides_authentication") is not False
                or record.get("provides_authorization") is not False
                or record.get("grants_permission") is not False
            ):
                raise HumanDecisionAuthorityError("local opaque actor identity semantic ceiling mismatch")

    def _commit_locked(self, final: Path, semantic: dict[str, Any]) -> dict[str, Any]:
        schema = semantic.get("schema")
        expected = _HUMAN_SOURCE_FIELDS.get(schema)
        if expected is None:
            raise HumanDecisionAuthorityError("unsupported Human Decision source schema")
        _exact_fields(semantic, frozenset(expected - {"committed_at_utc"}), "Human Decision semantic candidate")
        if semantic.get("source_record_revision") != 1:
            raise HumanDecisionAuthorityError("Human Decision semantic source_record_revision mismatch")

        state = self._path_state(final, label="Human Decision source destination")
        if state == "PRESENT":
            stored = _json(final.read_bytes(), "stored Human Decision record")
            self._validate_source_record(stored, expected_schema=schema, label="stored Human Decision record")
            compare = dict(stored)
            compare.pop("committed_at_utc")
            if compare != semantic:
                raise HumanDecisionAuthorityError("Human Decision first-writer conflict")
            return stored

        record = dict(semantic)
        record["committed_at_utc"] = _utc_now()
        self._validate_source_record(record, expected_schema=schema, label="new Human Decision record")
        data = _canonical(record)
        temp = self._temp(final, data)
        try:
            self._publish_absent(temp, final)
        except (FileExistsError, OSError):
            temp.unlink(missing_ok=True)
            if self._path_state(final, label="raced Human Decision destination") != "PRESENT":
                raise
            stored = _json(final.read_bytes(), "raced Human Decision record")
            self._validate_source_record(stored, expected_schema=schema, label="raced Human Decision record")
            compare = dict(stored)
            compare.pop("committed_at_utc")
            if compare != semantic:
                raise HumanDecisionAuthorityError("Human Decision first-writer conflict")
            return stored
        stored_bytes = final.read_bytes()
        if stored_bytes != data or sha256_bytes(stored_bytes) != sha256_bytes(data):
            raise HumanDecisionAuthorityError("Human Decision final read-back mismatch")
        return record

    def _artifact_json(self, binding: R009OpaqueArtifactBinding, label: str) -> dict[str, Any]:
        _m, data = self.artifact_store.load_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=binding.artifact_identity_sha256,
            artifact_revision=binding.artifact_revision,
            artifact_sha256=binding.artifact_sha256,
        )
        return _json(data, label)

    @staticmethod
    def _binding(v3: dict[str, Any], prefix: str) -> R009OpaqueArtifactBinding:
        return R009OpaqueArtifactBinding(
            v3[f"{prefix}_artifact_identity_sha256"],
            v3[f"{prefix}_artifact_revision"],
            v3[f"{prefix}_artifact_sha256"],
        )

    def _validate_v3_artifacts_only(self, v3: dict[str, Any]) -> tuple[R009OpaqueArtifactBinding, R009OpaqueArtifactBinding, R009OpaqueArtifactBinding]:
        _exact_fields(v3, _V3_FIELDS, "complete V3 request binding")
        if v3.get("schema") != "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_BINDING_V3":
            raise HumanDecisionAuthorityError("complete V3 schema mismatch")
        sb = self._binding(v3, "job_execution_authority_snapshot")
        rb = self._binding(v3, "job_execution_snapshot_registration")
        cb = self._binding(v3, "decision_request_content")
        snapshot = self._artifact_json(sb, "snapshot Artifact")
        registration = self._artifact_json(rb, "registration Artifact")
        content = self._artifact_json(cb, "request-content Artifact")
        computed_jxs = "JXS_" + sha256_bytes(_canonical({
            "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
            "job_authority_event_id": v3["job_authority_event_id"],
            "snapshot_content_sha256": sb.artifact_sha256,
        }))
        if (
            snapshot.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1"
            or snapshot.get("job_authority_event_id") != v3["job_authority_event_id"]
            or computed_jxs != v3["job_execution_authority_snapshot_id"]
            or sb.artifact_sha256 != v3["job_execution_authority_snapshot_sha256"]
            or rb.artifact_sha256 != v3["job_execution_snapshot_registration_sha256"]
            or registration.get("job_authority_event_id") != v3["job_authority_event_id"]
            or registration.get("job_execution_authority_snapshot_id") != v3["job_execution_authority_snapshot_id"]
            or registration.get("job_execution_authority_snapshot_sha256") != v3["job_execution_authority_snapshot_sha256"]
            or cb.artifact_sha256 != v3["decision_request_content_sha256"]
        ):
            raise HumanDecisionAuthorityError("complete V3 Artifact tuple mismatch")
        expected_content_fields = frozenset({
            "schema","job_authority_event_id","job_execution_authority_snapshot_id",
            "job_execution_authority_snapshot_sha256","requested_decision_code","live_attempts_max",
            "model_calls_max","network_calls_max","retries_max","fallback_allowed",
        })
        _exact_fields(content, expected_content_fields, "request-content semantic")
        if (
            content["schema"] != "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_CONTENT_SEMANTIC_V1"
            or content["job_authority_event_id"] != v3["job_authority_event_id"]
            or content["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
            or content["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
            or content["requested_decision_code"] != "APPROVE_ONE_LIVE_ATTEMPT"
            or content["live_attempts_max"] != 1 or v3["live_attempts_max"] != 1
            or content["model_calls_max"] != 1 or v3["model_calls_max"] != 1
            or content["network_calls_max"] != 1 or v3["network_calls_max"] != 1
            or content["retries_max"] != 0 or v3["retries_max"] != 0
            or content["fallback_allowed"] is not False or v3["fallback_allowed"] is not False
            or v3["decision_scope_sha256"] != v3["job_execution_authority_snapshot_sha256"]
        ):
            raise HumanDecisionAuthorityError("request-content/V3 semantic mismatch")
        request_key = sha256_bytes(_canonical({
            "namespace": "RUNTIME_LIVE_EXECUTION_ONE_REQUEST_PER_ACTIVE_SNAPSHOT_V1",
            "job_authority_event_id": v3["job_authority_event_id"],
            "job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
            "job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
            "job_execution_snapshot_registration_sha256": v3["job_execution_snapshot_registration_sha256"],
        }))
        if (
            v3["snapshot_decision_request_key_sha256"] != request_key
            or v3["decision_request_event_id"] != "DRE_" + request_key
        ):
            raise HumanDecisionAuthorityError("request key/DRE mismatch")
        return sb, rb, cb

    def _validate_request_chain(self, key: str):
        source, branch, branch_binding = self.job_authority.load_exact_preapproval_branch_by_key_v1(
            preapproval_branch_key_sha256=key
        )
        if (
            branch.get("schema") != "RUNTIME_JOB_PREAPPROVAL_DRE_BRANCH_SELECTION_SEMANTIC_V2"
            or branch.get("branch_code") != "DRE_ISSUANCE_SELECTED"
        ):
            raise HumanDecisionAuthorityError("selected branch is not DRE V2")
        v3 = branch.get("decision_request_binding_v3")
        if not isinstance(v3, dict):
            raise HumanDecisionAuthorityError("branch missing complete V3")
        self._validate_v3_artifacts_only(v3)
        identity = sha256_bytes(_canonical(v3))
        if branch.get("decision_request_identity_sha256") != identity:
            raise HumanDecisionAuthorityError("V3 identity mismatch")

        active_source, active_reg, active_binding = self.job_authority.load_exact_active_registration_source_by_jae_v1(
            job_authority_event_id=v3["job_authority_event_id"]
        )
        if (
            active_source["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
            or active_source["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
            or active_source["registration_sha256"] != v3["job_execution_snapshot_registration_sha256"]
            or active_binding.artifact_identity_sha256 != v3["job_execution_snapshot_registration_artifact_identity_sha256"]
            or active_binding.artifact_revision != v3["job_execution_snapshot_registration_artifact_revision"]
            or active_binding.artifact_sha256 != v3["job_execution_snapshot_registration_artifact_sha256"]
            or active_reg["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
        ):
            raise HumanDecisionAuthorityError("exact active-registration source/V3 mismatch")

        preapproval = {
            "schema": "RUNTIME_DECISION_REQUEST_EVENT_PREAPPROVAL_BINDING_V1",
            "decision_request_event_id": v3["decision_request_event_id"],
            "decision_request_identity_sha256": identity,
            "preapproval_branch_key_sha256": key,
            "preapproval_branch_selection_semantic_sha256": source["branch_selection_semantic_sha256"],
            "preapproval_branch_selection_artifact_identity_sha256": branch_binding.artifact_identity_sha256,
            "preapproval_branch_selection_artifact_revision": 1,
            "preapproval_branch_selection_artifact_sha256": branch_binding.artifact_sha256,
        }
        return source, branch_binding, v3, identity, sha256_bytes(_canonical(preapproval)), active_source

    def issue_or_replay_one_decision_request_for_selected_active_snapshot_v3(self, *, preapproval_branch_key_sha256: str):
        source, bb, v3, identity, preapproval_sha, active_source = self._validate_request_chain(preapproval_branch_key_sha256)
        semantic = {
            "schema": "RUNTIME_HUMAN_DECISION_REQUEST_SOURCE_RECORD_V1",
            "source_record_revision": 1,
            "decision_request_event_id": v3["decision_request_event_id"],
            "decision_request_identity_sha256": identity,
            "decision_request_preapproval_binding_sha256": preapproval_sha,
            "preapproval_branch_key_sha256": preapproval_branch_key_sha256,
            "preapproval_branch_selection_semantic_sha256": source["branch_selection_semantic_sha256"],
            "preapproval_branch_selection_artifact_identity_sha256": bb.artifact_identity_sha256,
            "preapproval_branch_selection_artifact_revision": 1,
            "preapproval_branch_selection_artifact_sha256": bb.artifact_sha256,
            "decision_request_binding_v3": v3,
        }
        # No Job Authority call is permitted after Human lock acquisition.
        with self._lock():
            self._validate_v3_artifacts_only(v3)
            return self._commit_locked(self._request_path(v3["decision_request_event_id"]), semantic)

    def load_exact_request_source(self, decision_request_event_id: str) -> dict[str, Any]:
        final = self._request_path(decision_request_event_id)
        if self._path_state(final, label="request source") != "PRESENT":
            raise HumanDecisionAuthorityError("request source absent")
        record = _json(final.read_bytes(), "request source")
        self._validate_source_record(
            record,
            expected_schema="RUNTIME_HUMAN_DECISION_REQUEST_SOURCE_RECORD_V1",
            label="request source",
        )
        if record["decision_request_event_id"] != decision_request_event_id:
            raise HumanDecisionAuthorityError("request source DRE mismatch")
        v3 = record["decision_request_binding_v3"]
        self._validate_v3_artifacts_only(v3)
        if (
            sha256_bytes(_canonical(v3)) != record["decision_request_identity_sha256"]
            or v3["decision_request_event_id"] != decision_request_event_id
        ):
            raise HumanDecisionAuthorityError("request source complete V3 binding mismatch")
        return record

    def load_exact_terminal_source(self, decision_request_event_id: str) -> dict[str, Any]:
        final = self._terminal_path(decision_request_event_id)
        if self._path_state(final, label="terminal source") != "PRESENT":
            raise HumanDecisionAuthorityError("terminal source absent")
        record = _json(final.read_bytes(), "terminal source")
        self._validate_source_record(
            record,
            expected_schema="RUNTIME_HUMAN_DECISION_TERMINAL_SOURCE_RECORD_V1",
            label="terminal source",
        )
        if record["decision_request_event_id"] != decision_request_event_id:
            raise HumanDecisionAuthorityError("terminal source DRE mismatch")
        return record

    def load_exact_local_single_user_opaque_actor_identity_v1(self) -> dict[str, Any]:
        final = self._local_single_user_actor_identity_path()
        if self._path_state(final, label="local opaque actor identity source") != "PRESENT":
            raise HumanDecisionAuthorityError("local opaque actor identity source absent")
        record = _json(final.read_bytes(), "local opaque actor identity source")
        self._validate_source_record(
            record,
            expected_schema="RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_SOURCE_V1",
            label="local opaque actor identity source",
        )
        return record

    def load_or_mint_local_single_user_opaque_actor_identity_v1(self) -> dict[str, Any]:
        """Return the one Runtime-owned local opaque actor identity, minting once if absent.

        This identity exists only to bind explicit Human Decision actions. It is
        not a real-person identity, authentication credential, authorization,
        permission grant, Chat/Project identity, OS account identity, or Runtime
        execution identity.
        """
        final = self._local_single_user_actor_identity_path()
        with self._lock():
            if self._path_state(final, label="local opaque actor identity source") == "PRESENT":
                record = _json(final.read_bytes(), "local opaque actor identity source")
                self._validate_source_record(
                    record,
                    expected_schema="RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_SOURCE_V1",
                    label="local opaque actor identity source",
                )
                return record

            actor_authority_identity_sha256 = sha256_bytes(
                b"RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_V1\x00" + os.urandom(32)
            )
            semantic = {
                "schema": "RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_SOURCE_V1",
                "source_record_revision": 1,
                "actor_authority_identity_sha256": actor_authority_identity_sha256,
                "identity_class": "LOCAL_SINGLE_USER_OPAQUE",
                "use_scope": "EXPLICIT_HUMAN_DECISION_ACTION_IDENTITY_BINDING_ONLY",
                "derivation_class": "RUNTIME_RANDOM_LOCAL_OPAQUE_NOT_PERSONAL_DATA_DERIVED",
                "represents_real_person_identity": False,
                "provides_authentication": False,
                "provides_authorization": False,
                "grants_permission": False,
            }
            return self._commit_locked(final, semantic)

    def produce_and_commit_or_replay_one_approved_terminal_for_request_v1(
        self,
        *,
        decision_request_event_id: str,
        actor_authority_identity_sha256: str,
    ) -> dict[str, Any]:
        """Owner-local producer for one explicit APPROVE terminal.

        The R009 artifacts are deterministic staging inputs to the existing
        terminal consumer. HumanDecisionAuthority remains the sole terminal
        source commit owner.
        """
        _sha64(actor_authority_identity_sha256, "actor authority identity")
        request = self.load_exact_request_source(decision_request_event_id)
        v3 = request["decision_request_binding_v3"]

        request_content_binding = R009OpaqueArtifactBinding(
            v3["decision_request_content_artifact_identity_sha256"],
            v3["decision_request_content_artifact_revision"],
            v3["decision_request_content_artifact_sha256"],
        )
        request_manifest, _request_content_bytes = (
            self.artifact_store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=request_content_binding.artifact_identity_sha256,
                artifact_revision=request_content_binding.artifact_revision,
                artifact_sha256=request_content_binding.artifact_sha256,
            )
        )
        job_id = request_manifest.job_id
        if not isinstance(job_id, str) or not job_id:
            raise HumanDecisionAuthorityError(
                "decision request content Artifact does not bind a job_id"
            )

        request_identity = request["decision_request_identity_sha256"]

        def approval_artifact_identity(role: str) -> str:
            return sha256_bytes(_canonical({
                "namespace": "RUNTIME_HUMAN_DECISION_APPROVAL_PRODUCER_ARTIFACT_ID_V1",
                "role": role,
                "decision_request_identity_sha256": request_identity,
            }))

        action = {
            "schema": "RUNTIME_EXPLICIT_HUMAN_ACTION_RECEIPT_SEMANTIC_V1",
            "decision_request_event_id": decision_request_event_id,
            "decision_request_identity_sha256": request_identity,
            "decision_request_content_sha256": v3["decision_request_content_sha256"],
            "decision_scope_sha256": v3["decision_scope_sha256"],
            "actor_authority_identity_sha256": actor_authority_identity_sha256,
            "action_code": "APPROVE",
        }
        action_bytes = _canonical(action)
        action_binding, _action_manifest = (
            self.artifact_store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=approval_artifact_identity("HUMAN_ACTION_RECEIPT"),
                artifact_bytes=action_bytes,
                job_id=job_id,
                expected_artifact_sha256=sha256_bytes(action_bytes),
            )
        )

        approval_decision_event_id = "ADE_" + sha256_bytes(_canonical({
            "namespace": "RUNTIME_APPROVAL_DECISION_EVENT_ID_V1",
            "job_authority_event_id": v3["job_authority_event_id"],
            "decision_request_identity_sha256": request_identity,
        }))
        approval = {
            "schema": "RUNTIME_APPROVAL_DECISION_EVENT_BINDING_V3",
            "approval_decision_event_id": approval_decision_event_id,
            "job_authority_event_id": v3["job_authority_event_id"],
            "job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
            "job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
            "job_execution_authority_snapshot_artifact_identity_sha256": v3[
                "job_execution_authority_snapshot_artifact_identity_sha256"
            ],
            "job_execution_authority_snapshot_artifact_revision": v3[
                "job_execution_authority_snapshot_artifact_revision"
            ],
            "job_execution_authority_snapshot_artifact_sha256": v3[
                "job_execution_authority_snapshot_artifact_sha256"
            ],
            "job_execution_snapshot_registration_sha256": v3[
                "job_execution_snapshot_registration_sha256"
            ],
            "decision_request_event_id": decision_request_event_id,
            "snapshot_decision_request_key_sha256": v3[
                "snapshot_decision_request_key_sha256"
            ],
            "decision_request_identity_sha256": request_identity,
            "decision_request_content_sha256": v3["decision_request_content_sha256"],
            "decision_request_content_artifact_identity_sha256": v3[
                "decision_request_content_artifact_identity_sha256"
            ],
            "decision_request_content_artifact_revision": v3[
                "decision_request_content_artifact_revision"
            ],
            "decision_request_content_artifact_sha256": v3[
                "decision_request_content_artifact_sha256"
            ],
            "human_action_receipt_sha256": action_binding.artifact_sha256,
            "human_action_receipt_artifact_identity_sha256": (
                action_binding.artifact_identity_sha256
            ),
            "human_action_receipt_artifact_revision": action_binding.artifact_revision,
            "human_action_receipt_artifact_sha256": action_binding.artifact_sha256,
            "decision_scope_sha256": v3["decision_scope_sha256"],
            "decision_code": "APPROVED",
            "live_attempts_max": 1,
            "model_calls_max": 1,
            "network_calls_max": 1,
            "retries_max": 0,
            "fallback_allowed": False,
        }
        approval_bytes = _canonical(approval)
        approval_binding, _approval_manifest = (
            self.artifact_store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=approval_artifact_identity(
                    "APPROVAL_DECISION_EVENT"
                ),
                artifact_bytes=approval_bytes,
                job_id=job_id,
                expected_artifact_sha256=sha256_bytes(approval_bytes),
            )
        )

        acceptance = {
            "schema": "RUNTIME_LIVE_EXECUTION_APPROVAL_ACCEPTANCE_SEMANTIC_V1",
            "approval_decision_event_id": approval_decision_event_id,
            "approval_decision_event_binding_sha256": approval_binding.artifact_sha256,
            "job_authority_event_id": v3["job_authority_event_id"],
            "job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
            "job_execution_authority_snapshot_sha256": v3[
                "job_execution_authority_snapshot_sha256"
            ],
            "job_execution_snapshot_registration_sha256": v3[
                "job_execution_snapshot_registration_sha256"
            ],
            "decision_request_event_id": decision_request_event_id,
            "decision_request_identity_sha256": request_identity,
            "human_action_receipt_sha256": action_binding.artifact_sha256,
            "decision_scope_sha256": v3["decision_scope_sha256"],
            "decision_code": "APPROVED",
            "live_attempts_max": 1,
            "model_calls_max": 1,
            "network_calls_max": 1,
            "retries_max": 0,
            "fallback_allowed": False,
        }
        acceptance_bytes = _canonical(acceptance)
        acceptance_binding, _acceptance_manifest = (
            self.artifact_store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=approval_artifact_identity(
                    "APPROVAL_ACCEPTANCE"
                ),
                artifact_bytes=acceptance_bytes,
                job_id=job_id,
                expected_artifact_sha256=sha256_bytes(acceptance_bytes),
            )
        )

        terminal_source = self.commit_or_replay_one_terminal_human_decision_for_request_v2(
            decision_request_event_id=decision_request_event_id,
            terminal_decision_code="APPROVED",
            human_action_receipt_binding=action_binding,
            approval_decision_event_binding=approval_binding,
            approval_acceptance_binding=acceptance_binding,
        )
        return {
            "terminal_source": terminal_source,
            "human_action_receipt_binding": action_binding,
            "approval_decision_event_binding": approval_binding,
            "approval_acceptance_binding": acceptance_binding,
        }

    def commit_or_replay_one_terminal_human_decision_for_request_v2(
        self,
        *,
        decision_request_event_id: str,
        terminal_decision_code: str,
        human_action_receipt_binding: R009OpaqueArtifactBinding,
        approval_decision_event_binding: R009OpaqueArtifactBinding | None = None,
        approval_acceptance_binding: R009OpaqueArtifactBinding | None = None,
        non_approval_terminal_binding: R009OpaqueArtifactBinding | None = None,
    ):
        if terminal_decision_code not in _TERMINALS:
            raise HumanDecisionAuthorityError("terminal code invalid")
        request = self.load_exact_request_source(decision_request_event_id)
        v3 = request["decision_request_binding_v3"]
        action = self._artifact_json(human_action_receipt_binding, "human action Artifact")

        if terminal_decision_code == "APPROVED":
            _exact_fields(action, _ACTION_APPROVE_FIELDS, "APPROVE human action")
            _sha64(action.get("actor_authority_identity_sha256"), "actor authority identity")
            if (
                action["schema"] != "RUNTIME_EXPLICIT_HUMAN_ACTION_RECEIPT_SEMANTIC_V1"
                or action["action_code"] != "APPROVE"
                or action["decision_request_event_id"] != decision_request_event_id
                or action["decision_request_identity_sha256"] != request["decision_request_identity_sha256"]
                or action["decision_request_content_sha256"] != v3["decision_request_content_sha256"]
                or action["decision_scope_sha256"] != v3["decision_scope_sha256"]
                or approval_decision_event_binding is None
                or approval_acceptance_binding is None
                or non_approval_terminal_binding is not None
            ):
                raise HumanDecisionAuthorityError("APPROVED human action/request mismatch")

            approval = self._artifact_json(approval_decision_event_binding, "approval Artifact")
            acceptance = self._artifact_json(approval_acceptance_binding, "acceptance Artifact")
            _exact_fields(approval, _APPROVAL_V3_FIELDS, "approval V3")
            _exact_fields(acceptance, _ACCEPTANCE_FIELDS, "approval acceptance")
            expected_ade = "ADE_" + sha256_bytes(_canonical({
                "namespace": "RUNTIME_APPROVAL_DECISION_EVENT_ID_V1",
                "job_authority_event_id": v3["job_authority_event_id"],
                "decision_request_identity_sha256": request["decision_request_identity_sha256"],
            }))
            if (
                approval["approval_decision_event_id"] != expected_ade
                or approval["job_authority_event_id"] != v3["job_authority_event_id"]
                or approval["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
                or approval["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
                or approval["job_execution_authority_snapshot_artifact_identity_sha256"] != v3["job_execution_authority_snapshot_artifact_identity_sha256"]
                or approval["job_execution_authority_snapshot_artifact_revision"] != v3["job_execution_authority_snapshot_artifact_revision"]
                or approval["job_execution_authority_snapshot_artifact_sha256"] != v3["job_execution_authority_snapshot_artifact_sha256"]
                or approval["job_execution_snapshot_registration_sha256"] != v3["job_execution_snapshot_registration_sha256"]
                or approval["decision_request_event_id"] != decision_request_event_id
                or approval["snapshot_decision_request_key_sha256"] != v3["snapshot_decision_request_key_sha256"]
                or approval["decision_request_identity_sha256"] != request["decision_request_identity_sha256"]
                or approval["decision_request_content_sha256"] != v3["decision_request_content_sha256"]
                or approval["decision_request_content_artifact_identity_sha256"] != v3["decision_request_content_artifact_identity_sha256"]
                or approval["decision_request_content_artifact_revision"] != v3["decision_request_content_artifact_revision"]
                or approval["decision_request_content_artifact_sha256"] != v3["decision_request_content_artifact_sha256"]
                or approval["human_action_receipt_sha256"] != human_action_receipt_binding.artifact_sha256
                or approval["human_action_receipt_artifact_identity_sha256"] != human_action_receipt_binding.artifact_identity_sha256
                or approval["human_action_receipt_artifact_revision"] != human_action_receipt_binding.artifact_revision
                or approval["human_action_receipt_artifact_sha256"] != human_action_receipt_binding.artifact_sha256
                or approval["decision_scope_sha256"] != v3["decision_scope_sha256"]
                or approval["decision_code"] != "APPROVED"
                or approval["live_attempts_max"] != 1 or approval["model_calls_max"] != 1
                or approval["network_calls_max"] != 1 or approval["retries_max"] != 0
                or approval["fallback_allowed"] is not False
            ):
                raise HumanDecisionAuthorityError("approval V3 exact binding mismatch")
            if (
                acceptance["approval_decision_event_id"] != expected_ade
                or acceptance["approval_decision_event_binding_sha256"] != approval_decision_event_binding.artifact_sha256
                or acceptance["job_authority_event_id"] != v3["job_authority_event_id"]
                or acceptance["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
                or acceptance["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
                or acceptance["job_execution_snapshot_registration_sha256"] != v3["job_execution_snapshot_registration_sha256"]
                or acceptance["decision_request_event_id"] != decision_request_event_id
                or acceptance["decision_request_identity_sha256"] != request["decision_request_identity_sha256"]
                or acceptance["human_action_receipt_sha256"] != human_action_receipt_binding.artifact_sha256
                or acceptance["decision_scope_sha256"] != v3["decision_scope_sha256"]
                or acceptance["decision_code"] != "APPROVED"
                or acceptance["live_attempts_max"] != 1 or acceptance["model_calls_max"] != 1
                or acceptance["network_calls_max"] != 1 or acceptance["retries_max"] != 0
                or acceptance["fallback_allowed"] is not False
            ):
                raise HumanDecisionAuthorityError("approval acceptance exact binding mismatch")

            semantic = {
                "schema": "RUNTIME_HUMAN_DECISION_TERMINAL_SOURCE_RECORD_V1",
                "source_record_revision": 1,
                "decision_request_event_id": decision_request_event_id,
                "decision_request_identity_sha256": request["decision_request_identity_sha256"],
                "terminal_decision_code": "APPROVED",
                "human_action_receipt_sha256": human_action_receipt_binding.artifact_sha256,
                "human_action_receipt_artifact_identity_sha256": human_action_receipt_binding.artifact_identity_sha256,
                "human_action_receipt_artifact_revision": 1,
                "human_action_receipt_artifact_sha256": human_action_receipt_binding.artifact_sha256,
                "approval_decision_event_id": expected_ade,
                "approval_decision_event_binding_sha256": approval_decision_event_binding.artifact_sha256,
                "approval_decision_event_artifact_identity_sha256": approval_decision_event_binding.artifact_identity_sha256,
                "approval_decision_event_artifact_revision": 1,
                "approval_decision_event_artifact_sha256": approval_decision_event_binding.artifact_sha256,
                "approval_acceptance_semantic_sha256": approval_acceptance_binding.artifact_sha256,
                "approval_acceptance_artifact_identity_sha256": approval_acceptance_binding.artifact_identity_sha256,
                "approval_acceptance_artifact_revision": 1,
                "approval_acceptance_artifact_sha256": approval_acceptance_binding.artifact_sha256,
                "non_approval_terminal_binding_sha256": None,
                "non_approval_terminal_artifact_identity_sha256": None,
                "non_approval_terminal_artifact_revision": None,
                "non_approval_terminal_artifact_sha256": None,
            }

        else:
            _exact_fields(action, _ACTION_NONAPP_FIELDS, "non-approval human action")
            _sha64(action.get("actor_authority_identity_sha256"), "actor authority identity")
            if (
                action["schema"] != "RUNTIME_EXPLICIT_HUMAN_NON_APPROVAL_ACTION_RECEIPT_SEMANTIC_V1"
                or action["action_code"] != _NONAPP_ACTION[terminal_decision_code]
                or action["decision_request_event_id"] != decision_request_event_id
                or action["decision_request_identity_sha256"] != request["decision_request_identity_sha256"]
                or action["decision_request_content_sha256"] != v3["decision_request_content_sha256"]
                or action["decision_scope_sha256"] != v3["decision_scope_sha256"]
                or approval_decision_event_binding is not None
                or approval_acceptance_binding is not None
                or non_approval_terminal_binding is None
            ):
                raise HumanDecisionAuthorityError("non-approval human action/request mismatch")

            nonapp = self._artifact_json(non_approval_terminal_binding, "non-approval terminal Artifact")
            _exact_fields(nonapp, _NONAPP_TERMINAL_FIELDS, "non-approval terminal binding")
            if (
                nonapp["schema"] != "RUNTIME_NON_APPROVAL_TERMINAL_HUMAN_DECISION_BINDING_V1"
                or nonapp["job_authority_event_id"] != v3["job_authority_event_id"]
                or nonapp["job_execution_authority_snapshot_id"] != v3["job_execution_authority_snapshot_id"]
                or nonapp["job_execution_authority_snapshot_sha256"] != v3["job_execution_authority_snapshot_sha256"]
                or nonapp["job_execution_snapshot_registration_sha256"] != v3["job_execution_snapshot_registration_sha256"]
                or nonapp["decision_request_event_id"] != decision_request_event_id
                or nonapp["decision_request_identity_sha256"] != request["decision_request_identity_sha256"]
                or nonapp["decision_request_content_sha256"] != v3["decision_request_content_sha256"]
                or nonapp["decision_scope_sha256"] != v3["decision_scope_sha256"]
                or nonapp["human_action_receipt_sha256"] != human_action_receipt_binding.artifact_sha256
                or nonapp["human_action_receipt_artifact_identity_sha256"] != human_action_receipt_binding.artifact_identity_sha256
                or nonapp["human_action_receipt_artifact_revision"] != 1
                or nonapp["human_action_receipt_artifact_sha256"] != human_action_receipt_binding.artifact_sha256
                or nonapp["terminal_decision_code"] != terminal_decision_code
            ):
                raise HumanDecisionAuthorityError("non-approval terminal exact binding mismatch")

            transition_fields = (
                "preapproval_transition_intent_sha256",
                "preapproval_transition_intent_artifact_identity_sha256",
                "preapproval_transition_intent_artifact_revision",
                "preapproval_transition_intent_artifact_sha256",
            )
            successor_fields = (
                "successor_job_authority_event_id","successor_job_execution_authority_snapshot_id",
                "successor_job_execution_authority_snapshot_sha256",
                "successor_job_execution_authority_snapshot_artifact_identity_sha256",
                "successor_job_execution_authority_snapshot_artifact_revision",
                "successor_job_execution_authority_snapshot_artifact_sha256",
            )
            if terminal_decision_code == "REJECTED":
                if action["preapproval_transition_intent_sha256"] is not None:
                    raise HumanDecisionAuthorityError("REJECT action transition intent must be null")
                if any(nonapp[f] is not None for f in transition_fields + successor_fields):
                    raise HumanDecisionAuthorityError("REJECTED terminal transition/successor fields must be null")
            else:
                if any(nonapp[f] is None for f in transition_fields):
                    raise HumanDecisionAuthorityError("transition terminal requires exact transition intent")
                transition_binding = R009OpaqueArtifactBinding(
                    nonapp["preapproval_transition_intent_artifact_identity_sha256"],
                    nonapp["preapproval_transition_intent_artifact_revision"],
                    nonapp["preapproval_transition_intent_artifact_sha256"],
                )
                transition = self._artifact_json(transition_binding, "non-approval transition-intent Artifact")
                if (
                    nonapp["preapproval_transition_intent_sha256"] != transition_binding.artifact_sha256
                    or action["preapproval_transition_intent_sha256"] != transition_binding.artifact_sha256
                    or transition.get("schema") != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1"
                ):
                    raise HumanDecisionAuthorityError("non-approval transition intent mismatch")
                if terminal_decision_code == "REVOKED_FOR_CONTROLLED_CANCEL":
                    if transition.get("transition_code") != "CONTROLLED_CANCEL":
                        raise HumanDecisionAuthorityError("REVOKED terminal requires controlled cancel")
                    if any(nonapp[f] is not None for f in successor_fields):
                        raise HumanDecisionAuthorityError("REVOKED terminal successor fields must be null")
                else:
                    if transition.get("transition_code") not in {"CONTROLLED_REOPEN_MATERIAL_INPUT_CHANGE","CONTROLLED_REOPEN_RUNTIME_MIGRATION"}:
                        raise HumanDecisionAuthorityError("SUPERSEDED terminal requires controlled reopen")
                    if any(nonapp[f] is None for f in successor_fields):
                        raise HumanDecisionAuthorityError("SUPERSEDED terminal requires exact successor")
                    successor_binding = R009OpaqueArtifactBinding(
                        nonapp["successor_job_execution_authority_snapshot_artifact_identity_sha256"],
                        nonapp["successor_job_execution_authority_snapshot_artifact_revision"],
                        nonapp["successor_job_execution_authority_snapshot_artifact_sha256"],
                    )
                    successor = self._artifact_json(successor_binding, "non-approval successor snapshot Artifact")
                    if (
                        successor.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1"
                        or successor.get("job_authority_event_id") != nonapp["successor_job_authority_event_id"]
                        or nonapp["successor_job_execution_authority_snapshot_sha256"] != successor_binding.artifact_sha256
                        or transition.get("successor_job_authority_event_id") != nonapp["successor_job_authority_event_id"]
                        or transition.get("successor_job_execution_authority_snapshot_id") != nonapp["successor_job_execution_authority_snapshot_id"]
                        or transition.get("successor_job_execution_authority_snapshot_sha256") != nonapp["successor_job_execution_authority_snapshot_sha256"]
                    ):
                        raise HumanDecisionAuthorityError("SUPERSEDED terminal successor mismatch")

            semantic = {
                "schema": "RUNTIME_HUMAN_DECISION_TERMINAL_SOURCE_RECORD_V1",
                "source_record_revision": 1,
                "decision_request_event_id": decision_request_event_id,
                "decision_request_identity_sha256": request["decision_request_identity_sha256"],
                "terminal_decision_code": terminal_decision_code,
                "human_action_receipt_sha256": human_action_receipt_binding.artifact_sha256,
                "human_action_receipt_artifact_identity_sha256": human_action_receipt_binding.artifact_identity_sha256,
                "human_action_receipt_artifact_revision": 1,
                "human_action_receipt_artifact_sha256": human_action_receipt_binding.artifact_sha256,
                "approval_decision_event_id": None,
                "approval_decision_event_binding_sha256": None,
                "approval_decision_event_artifact_identity_sha256": None,
                "approval_decision_event_artifact_revision": None,
                "approval_decision_event_artifact_sha256": None,
                "approval_acceptance_semantic_sha256": None,
                "approval_acceptance_artifact_identity_sha256": None,
                "approval_acceptance_artifact_revision": None,
                "approval_acceptance_artifact_sha256": None,
                "non_approval_terminal_binding_sha256": non_approval_terminal_binding.artifact_sha256,
                "non_approval_terminal_artifact_identity_sha256": non_approval_terminal_binding.artifact_identity_sha256,
                "non_approval_terminal_artifact_revision": 1,
                "non_approval_terminal_artifact_sha256": non_approval_terminal_binding.artifact_sha256,
            }

        # No Job Authority call occurs inside the Human Decision lock.
        with self._lock():
            request2 = self.load_exact_request_source(decision_request_event_id)
            if request2["decision_request_identity_sha256"] != request["decision_request_identity_sha256"]:
                raise HumanDecisionAuthorityError("request changed before terminal commit")
            self._artifact_json(human_action_receipt_binding, "human action under Human lock")
            if terminal_decision_code == "APPROVED":
                self._artifact_json(approval_decision_event_binding, "approval under Human lock")
                self._artifact_json(approval_acceptance_binding, "acceptance under Human lock")
            else:
                self._artifact_json(non_approval_terminal_binding, "non-approval terminal under Human lock")
            return self._commit_locked(self._terminal_path(decision_request_event_id), semantic)

