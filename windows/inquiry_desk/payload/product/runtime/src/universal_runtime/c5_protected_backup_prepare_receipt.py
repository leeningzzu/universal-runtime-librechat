"""C5-only protected backup PREPARE receipt using existing WebContinuity ArtifactStore.

This is not a generic task engine. Starting work and executing the existing
snapshot are deliberately separate. A Runtime crash does not schedule replay,
admit a DELETE, or turn an incomplete backup into a VERIFIED result.
"""
from __future__ import annotations

from hashlib import sha256
from threading import RLock
from typing import Any, Callable
import json
import re
import secrets

_NATIVE = re.compile(r"^[0-9a-f]{24}$", re.I)
_SHA = re.compile(r"^[0-9a-f]{64}$")
_OP_ID = re.compile(r"^C5PREP_[0-9A-F]{64}$")
_SCHEMA = "AIDES_C5_PROTECTED_BACKUP_PREPARE_OPERATION_R001"
_PHASES = frozenset({
    "PREPARING", "BACKUP_VERIFIED", "FAILED_PRE_EFFECT",
    "INTERRUPTED_OR_UNKNOWN",
})
_STOP_PHASES = frozenset({"FAILED_PRE_EFFECT", "INTERRUPTED_OR_UNKNOWN"})
_ALLOWED_ERROR = re.compile(r"^C5_[A-Z0-9_]{1,120}$")


class C5PrepareStop(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise C5PrepareStop(code)


def _counters(value: Any) -> dict[str, int]:
    _need(isinstance(value, dict) and set(value) == {"insert", "update", "delete"},
          "C5_PREPARE_COUNTER_SHAPE_INVALID")
    _need(all(type(value[k]) is int and 0 <= value[k] <= 2**53 - 1
              for k in ("insert", "update", "delete")),
          "C5_PREPARE_COUNTER_VALUE_INVALID")
    return {key: value[key] for key in ("insert", "update", "delete")}


def _counters_at_or_after(later: dict[str, int], earlier: dict[str, int]) -> bool:
    return all(later[key] >= earlier[key] for key in ("insert", "update", "delete"))


def _ident(owner_id: str, project_id: str) -> str:
    _need(isinstance(owner_id, str) and _NATIVE.fullmatch(owner_id) is not None
          and isinstance(project_id, str) and _NATIVE.fullmatch(project_id) is not None,
          "C5_PREPARE_OWNER_PROJECT_INVALID")
    return sha256(("C5_PREPARE_R001|" + owner_id + "|" + project_id)
                  .encode("utf-8")).hexdigest().upper()


def _operation_id(scope_id: str, generation: int) -> str:
    return "C5PREP_" + sha256(
        ("C5_PREPARE_OPERATION_R001|" + scope_id + "|" + str(generation))
        .encode("utf-8")
    ).hexdigest().upper()


def _safe_record(value: Any, owner: str, project: str, scope: str,
                 binding: dict | None = None) -> dict:
    _need(isinstance(value, dict)
          and value.get("schema") == _SCHEMA
          and value.get("projectId") == project
          and value.get("ownerId") == owner
          and value.get("scopeIdentity") == scope
          and value.get("phase") in _PHASES
          and type(value.get("generation")) is int
          and 1 <= value["generation"] <= 2**31
          and type(value.get("recordRevision")) is int
          and value["recordRevision"] > 0
          and value.get("operationId") == _operation_id(scope, value["generation"])
          and isinstance(value.get("fenceSha256"), str)
          and _SHA.fullmatch(value["fenceSha256"]) is not None
          and type(value.get("runtimeGeneration")) is str
          and bool(value["runtimeGeneration"])
          and isinstance(value.get("backup"), (dict, type(None)))
          and isinstance(value.get("lastFailureCode"), (str, type(None))),
          "C5_PREPARE_RECEIPT_INVALID")
    _counters(value.get("mongoWriteCountersBefore"))
    if binding is not None:
        _need(value["recordRevision"] == binding.get("revision"),
              "C5_PREPARE_RECEIPT_MANIFEST_REVISION_MISMATCH")
    if value["phase"] == "BACKUP_VERIFIED":
        backup = value.get("backup")
        _need(isinstance(backup, dict)
              and set(backup) in ({"backupId", "backupManifestSha256",
                                   "protectedUserAssetsSha256", "mongoWriteCounters"},
                                  {"backupId", "backupManifestSha256",
                                   "protectedUserAssetsSha256", "mongoWriteCounters",
                                   "semanticCurrentnessVerified"})
              and type(backup.get("semanticCurrentnessVerified", False)) is bool
              and isinstance(backup["backupId"], str)
              and re.fullmatch(r"C5_R001_[A-Za-z0-9_]{8,128}", backup["backupId"]) is not None
              and isinstance(backup["backupManifestSha256"], str)
              and _SHA.fullmatch(backup["backupManifestSha256"]) is not None
              and isinstance(backup["protectedUserAssetsSha256"], str)
              and _SHA.fullmatch(backup["protectedUserAssetsSha256"]) is not None
              and (backup.get("semanticCurrentnessVerified") is True
                   or _counters_at_or_after(
                       _counters(backup["mongoWriteCounters"]),
                       _counters(value["mongoWriteCountersBefore"]))),
              "C5_PREPARE_VERIFIED_BACKUP_ATTESTATION_INVALID")
    else:
        _need(value["backup"] is None, "C5_PREPARE_UNVERIFIED_BACKUP_CLAIM")
    code = value["lastFailureCode"]
    if code is not None:
        _need(_ALLOWED_ERROR.fullmatch(code) is not None,
              "C5_PREPARE_UNSAFE_FAILURE_CODE")
    return value


class C5ProtectedBackupPrepareReceipt:
    """One durable C5 operation slot per real native Project + authenticated owner.

    Reuses the canonical WebContinuityService._persist_json_revision and its
    ArtifactStore current-manifest checks; it introduces no other database.

    A producer must call begin once after native owner authorization and then
    schedule existing first-party snapshot work. Pollers can never start work.
    """

    def __init__(self, *, service: Any,
                 verify_native_owner: Callable[..., dict],
                 verify_current_backup: Callable[..., dict],
                 verify_semantic_current_backup: Callable[..., bool] | None = None):
        _need(all(callable(getattr(service, name, None)) for name in
                  ("_persist_json_revision", "_load_current_json", "_record_exists",
                   "_operation_execution_id")),
              "C5_PREPARE_EXISTING_ARTIFACTSTORE_REQUIRED")
        _need(callable(verify_native_owner) and callable(verify_current_backup),
              "C5_PREPARE_FIRST_PARTY_OWNER_CALLBACK_REQUIRED")
        _need(hasattr(service, "_lock"), "C5_PREPARE_EXISTING_RUNTIME_LOCK_REQUIRED")
        self.service = service
        self.verify_native_owner = verify_native_owner
        self.verify_current_backup = verify_current_backup
        self.verify_semantic_current_backup = verify_semantic_current_backup
        self.runtime_generation = secrets.token_hex(16)
        self._lock = RLock()

    def _scope(self, owner_id: str, project_id: str) -> tuple[str, str]:
        scope = _ident(owner_id, project_id)
        authorized = self.verify_native_owner(owner_id=owner_id,
                                              project_id=project_id)
        _need(isinstance(authorized, dict)
              and authorized.get("owned") is True
              and authorized.get("ownerId") == owner_id
              and authorized.get("projectId") == project_id,
              "C5_PREPARE_NATIVE_OWNER_UNVERIFIED")
        return scope, "C5_PREPARE_" + scope

    def _load(self, artifact_id: str, owner_id: str, project_id: str,
              scope: str) -> dict | None:
        if not self.service._record_exists(artifact_id):
            return None
        record, binding = self.service._load_current_json(artifact_id)
        return _safe_record(record, owner_id, project_id, scope, binding)

    def _save(self, artifact_id: str, owner_id: str, project_id: str,
              scope: str, payload: dict, previous: dict | None) -> dict:
        prior = self._load(artifact_id, owner_id, project_id, scope)
        _need((prior is None and previous is None) or (
            prior is not None and previous is not None
            and prior["recordRevision"] == previous["recordRevision"]
            and prior["operationId"] == previous["operationId"]),
            "C5_PREPARE_STALE_REVISION")
        operation = self.service._operation_execution_id(
            project_id=project_id, chat_id=None,
            command_id="C5_PROTECTED_PREPARE_" + scope[:40],
        )
        saved, binding = self.service._persist_json_revision(
            artifact_id=artifact_id, namespace="c5_protected_prepare",
            record=payload, revision_field="recordRevision",
            operation_execution_id=operation,
        )
        return _safe_record(saved, owner_id, project_id, scope, binding)

    def _interrupt_stale(self, artifact_id: str, actor: str, project: str,
                         scope: str, row: dict | None) -> dict | None:
        if (row is not None and row["phase"] == "PREPARING" and
                row["runtimeGeneration"] != self.runtime_generation):
            updated = dict(row, phase="INTERRUPTED_OR_UNKNOWN", backup=None,
                           lastFailureCode="C5_PREPARE_PREVIOUS_PROCESS_INTERRUPTED")
            return self._save(artifact_id, actor, project, scope, updated, row)
        return row

    def _current_verified(self, row: dict) -> bool:
        if row["phase"] != "BACKUP_VERIFIED":
            return False
        try:
            verified = self.verify_current_backup()
            backup = row["backup"]
            return (
                isinstance(verified, dict)
                and verified.get("backup_id") == backup["backupId"]
                and verified.get("manifest_sha256") == backup["backupManifestSha256"]
                and verified.get("user_assets_sha256") ==
                    backup["protectedUserAssetsSha256"]
                and _counters(verified.get("mongo_write_counter")) ==
                    backup["mongoWriteCounters"]
            )
        except (RuntimeError, KeyError, ValueError, TypeError):
            return False

    def start(self, *, owner_id: str, project_id: str, counters: dict,
              explicit_confirmed: bool, fence_sha256: str,
              manual_retry: bool = False,
              previous_worker_absent: bool = False) -> dict:
        _need(explicit_confirmed is True, "C5_PREPARE_EXPLICIT_CONFIRMATION_REQUIRED")
        _need(isinstance(fence_sha256, str) and _SHA.fullmatch(fence_sha256) is not None,
              "C5_PREPARE_FENCE_SHA_REQUIRED")
        observed = _counters(counters)
        with self._lock, self.service._lock:
            scope, aid = self._scope(owner_id, project_id)
            old = self._interrupt_stale(
                aid, owner_id, project_id, scope,
                self._load(aid, owner_id, project_id, scope))
            if old is not None:
                if old["phase"] == "PREPARING":
                    _need(old["fenceSha256"] == fence_sha256,
                          "C5_PREPARE_FENCE_CHANGED_DURING_WORK")
                    _need(_counters_at_or_after(
                              observed, old["mongoWriteCountersBefore"]),
                          "C5_PREPARE_INPUT_REGRESSED_DURING_WORK")
                    return self.present(old)
                if old["phase"] == "BACKUP_VERIFIED":
                    # BACKUP_VERIFIED proves the immutable backup itself, not
                    # current live Mongo state. Global opcounters may advance
                    # because unrelated first-party maintenance writes or
                    # write-then-restore activity leave the protected semantic
                    # state byte-identical. Keep the same-fence operation and
                    # defer live currentness to the existing point-of-effect
                    # semantic admission owner.
                    if (self._current_verified(old)
                            and old["fenceSha256"] == fence_sha256):
                        return self.present(old)
                    # A new explicit user-owned fence may rebind only through a
                    # fresh PREPARING generation. Its worker reopens the exact
                    # backup and performs semantic currentness before deciding
                    # whether a new 450+ MiB snapshot is actually required.
                    _need(manual_retry is True and previous_worker_absent is True,
                          "C5_PREPARE_MANUAL_RETRY_AND_ORPHAN_ABSENCE_REQUIRED")
                else:
                    _need(manual_retry is True and previous_worker_absent is True,
                          "C5_PREPARE_MANUAL_RETRY_AND_ORPHAN_ABSENCE_REQUIRED")
            else:
                _need(manual_retry is False, "C5_PREPARE_UNNECESSARY_RETRY")
            generation = 1 if old is None else old["generation"] + 1
            _need(generation < 2**31, "C5_PREPARE_GENERATION_EXHAUSTED")
            payload = {
                "schema": _SCHEMA, "scopeIdentity": scope,
                "fenceSha256": fence_sha256,
                "ownerId": owner_id, "projectId": project_id,
                "operationId": _operation_id(scope, generation),
                "generation": generation,
                "runtimeGeneration": self.runtime_generation,
                "phase": "PREPARING",
                "mongoWriteCountersBefore": observed,
                "backup": None, "lastFailureCode": None,
            }
            return self.present(
                self._save(aid, owner_id, project_id, scope, payload, old)
            )

    def latest(self, *, owner_id: str, project_id: str) -> dict:
        # Authenticated, native-owned READ of the current C5 operation. Does
        # NOT schedule work or authorize DELETE. Works after browser reload.
        with self._lock, self.service._lock:
            scope, aid = self._scope(owner_id, project_id)
            row = self._interrupt_stale(
                aid, owner_id, project_id, scope,
                self._load(aid, owner_id, project_id, scope))
            if row is None:
                return {
                    "schema": _SCHEMA,
                    "operationId": None,
                    "phase": "NOT_STARTED",
                    "recordRevision": 0,
                    "backupVerified": False,
                    "retryAutomatically": False,
                    "lastFailureCode": None,
                }
            if row["phase"] == "BACKUP_VERIFIED" and not self._current_verified(row):
                unsafe = dict(row, phase="INTERRUPTED_OR_UNKNOWN",
                              backup=None,
                              lastFailureCode="C5_PREPARE_BACKUP_LOST_CURRENTNESS")
                row = self._save(aid, owner_id, project_id, scope, unsafe, row)
            return self.present(row)

    def poll(self, *, owner_id: str, project_id: str,
             operation_id: str) -> dict:
        _need(isinstance(operation_id, str) and
              _OP_ID.fullmatch(operation_id) is not None,
              "C5_PREPARE_OPERATION_ID_INVALID")
        with self._lock, self.service._lock:
            scope, aid = self._scope(owner_id, project_id)
            row = self._interrupt_stale(
                aid, owner_id, project_id, scope,
                self._load(aid, owner_id, project_id, scope))
            _need(row is not None and row["operationId"] == operation_id,
                  "C5_PREPARE_OPERATION_NOT_FOUND")
            if row["phase"] == "BACKUP_VERIFIED" and not self._current_verified(row):
                unsafe = dict(row, phase="INTERRUPTED_OR_UNKNOWN",
                              backup=None,
                              lastFailureCode="C5_PREPARE_BACKUP_LOST_CURRENTNESS")
                row = self._save(aid, owner_id, project_id, scope, unsafe, row)
            return self.present(row)

    def finalize(self, *, owner_id: str, project_id: str,
                 operation_id: str, backup_id: str,
                 backup_manifest_sha256: str,
                 protected_user_assets_sha256: str,
                 counters: dict) -> dict:
        # The existing first-party owner independently reopens current manifest
        # and archive digest; a caller-provided ready=True is never sufficient.
        with self._lock, self.service._lock:
            scope, aid = self._scope(owner_id, project_id)
            row = self._load(aid, owner_id, project_id, scope)
            _need(row is not None and row["phase"] == "PREPARING"
                  and row["runtimeGeneration"] == self.runtime_generation
                  and row["operationId"] == operation_id,
                  "C5_PREPARE_FINALIZATION_OPERATION_NOT_CURRENT")
            current = self.verify_current_backup()
            proposed_counters = _counters(counters)
            basic_current = bool(
                isinstance(current, dict)
                and current.get("backup_id") == backup_id
                and current.get("manifest_sha256") == backup_manifest_sha256
                and current.get("user_assets_sha256") == protected_user_assets_sha256
                and _counters(current.get("mongo_write_counter")) == proposed_counters
            )
            _need(basic_current, "C5_PREPARE_BACKUP_CURRENTNESS_UNVERIFIED")
            counters_cover_start = _counters_at_or_after(
                proposed_counters, row["mongoWriteCountersBefore"])
            semantic_current = False
            if not counters_cover_start:
                _need(callable(self.verify_semantic_current_backup) and
                      self.verify_semantic_current_backup(
                          backup=current,
                          observed_counters=row["mongoWriteCountersBefore"],
                      ) is True,
                      "C5_PREPARE_BACKUP_SEMANTIC_CURRENTNESS_UNVERIFIED")
                semantic_current = True
            proposed = {"backupId": backup_id,
                        "backupManifestSha256": backup_manifest_sha256,
                        "protectedUserAssetsSha256": protected_user_assets_sha256,
                        "mongoWriteCounters": proposed_counters,
                        "semanticCurrentnessVerified": semantic_current}
            updated = dict(row, phase="BACKUP_VERIFIED", backup=proposed,
                           lastFailureCode=None)
            return self.present(self._save(aid, owner_id, project_id, scope,
                                           updated, row))

    def fail(self, *, owner_id: str, project_id: str,
             operation_id: str, error_code: str, uncertain: bool) -> dict:
        _need(isinstance(error_code, str) and _ALLOWED_ERROR.fullmatch(error_code),
              "C5_PREPARE_UNSAFE_FAILURE_CODE")
        with self._lock, self.service._lock:
            scope, aid = self._scope(owner_id, project_id)
            row = self._load(aid, owner_id, project_id, scope)
            _need(row is not None and row["phase"] == "PREPARING"
                  and row["runtimeGeneration"] == self.runtime_generation
                  and row["operationId"] == operation_id,
                  "C5_PREPARE_FAILURE_OPERATION_NOT_CURRENT")
            next_phase = ("INTERRUPTED_OR_UNKNOWN" if uncertain
                          else "FAILED_PRE_EFFECT")
            updated = dict(row, phase=next_phase, backup=None,
                           lastFailureCode=error_code)
            return self.present(self._save(aid, owner_id, project_id, scope,
                                           updated, row))

    @staticmethod
    def present(record: dict) -> dict:
        # Only identity/phase/revision, not actor, local paths, secret or backup bytes.
        return {"schema": _SCHEMA, "operationId": record["operationId"],
                "phase": record["phase"], "recordRevision": record["recordRevision"],
                "backupVerified": record["phase"] == "BACKUP_VERIFIED",
                "retryAutomatically": False,
                "lastFailureCode": record["lastFailureCode"]}
