"""Aides C5 full Project-delete durable receipt owner — isolated candidate.

Reuses exact current WebContinuityService ArtifactStore manifest/revision machinery,
not a new database, Notes platform or generic task engine. Candidate-only:
Production must provide an admitted owner/Project resolver and current writer fence;
this class neither creates those proofs nor alters Runtime current app routes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Callable

from universal_runtime.web_continuity import WebContinuityService, WebContinuityError

_C5_SCHEMA = "C5_PROJECT_CASCADE_R001"
_SNAPSHOT_SCHEMA = "C5_PROJECT_DELETE_DURABLE_SNAPSHOT_R001"
_FILE_SEAL_SCHEMA = "C5_NATIVE_FILE_SEAL_R001"
_LEGACY_CORRECTION_SCHEMA = "C5_LEGACY_PROJECT_DELETE_PLAN_CORRECTION_R001"
_PHASES = {"PREPARED", "CASCADE_PENDING", "PARTIAL_OR_BLOCKED", "COMPLETE"}
_PROJECT_RE = re.compile(r"^[0-9a-f]{24}$", re.I)
_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_REF_RE = re.compile(r"^SRC_[A-Z0-9]{8,64}$")
_MAX_IDS = 20000
_MAX_PATHS = 8


class C5ReceiptStop(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _scope_ok(v: Any) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 256


def _binding(
    verifier: Callable[..., Any],
    *,
    librechat_project_id: str,
    owner_id: str,
    runtime_project_id: str,
) -> None:
    proof = verifier(
        librechat_project_id=librechat_project_id,
        owner_id=owner_id,
        runtime_project_id=runtime_project_id,
    )
    if not isinstance(proof, dict) or (
        proof.get("authoritative") is not True
        or proof.get("librechat_project_id") != librechat_project_id
        or proof.get("owner_id") != owner_id
        or proof.get("runtime_project_id") != runtime_project_id
    ):
        raise C5ReceiptStop("C5_OWNER_PROJECT_LOGICAL_BINDING_UNPROVEN")


def _exact_keys(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _plan_sha256(plan: dict[str, Any]) -> str:
    canonical = {
        "projectId": plan["projectId"],
        "ownerId": plan["ownerId"],
        "revision": plan["revision"],
        "chats": list(plan["chats"]),
        "exclusive": [
            {
                "id": row["id"],
                "bytes": row["bytes"],
                **({"nativeChatAnchor": True} if row.get("nativeChatAnchor") is True else {}),
            }
            for row in plan["exclusive"]
        ],
        "retained": [{"id": row["id"]} for row in plan["retained"]],
    }
    payload = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _assert_plan_shape(plan: Any, project_id: str, owner_id: str) -> None:
    if (
        not isinstance(plan, dict)
        or plan.get("projectId") != project_id
        or plan.get("ownerId") != owner_id
        or type(plan.get("revision")) is not int
        or plan["revision"] < 1
        or _HEX_RE.fullmatch(str(plan.get("planSha256", ""))) is None
        or not isinstance(plan.get("chats"), list)
        or not isinstance(plan.get("exclusive"), list)
        or not isinstance(plan.get("retained"), list)
        or len(plan["chats"]) > _MAX_IDS
        or len(plan["exclusive"]) > _MAX_IDS
        or len(plan["retained"]) > _MAX_IDS
    ):
        raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN")
    ids: list[str] = []
    for chat_id in plan["chats"]:
        if not _scope_ok(chat_id):
            raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN_CHAT")
    if len(set(plan["chats"])) != len(plan["chats"]):
        raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN_CHAT_DUPLICATE")
    for row in plan["exclusive"]:
        allowed = {"id", "bytes"}
        if isinstance(row, dict) and row.get("nativeChatAnchor") is True:
            allowed.add("nativeChatAnchor")
        if (
            not _exact_keys(row, allowed)
            or not _scope_ok(row.get("id"))
            or type(row.get("bytes")) is not int
            or row["bytes"] < 0
        ):
            raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN_EXCLUSIVE")
        ids.append(row["id"])
    for row in plan["retained"]:
        if not _exact_keys(row, {"id"}) or not _scope_ok(row.get("id")):
            raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN_RETAINED")
        ids.append(row["id"])
    if len(set(ids)) != len(ids):
        raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN_FILE_DUPLICATE")
    if _plan_sha256(plan) != plan["planSha256"]:
        raise C5ReceiptStop("C5_INVALID_RECEIPT_PLAN_DIGEST")


def _assert_snapshot(
    snapshot: Any, plan: dict[str, Any], project_id: str, owner_id: str,
) -> None:
    keys = {
        "schema", "projectId", "ownerId", "planSha256", "runtimeSources",
        "protectedAssetCensusSha256", "files", "snapshotSha256",
    }
    if (
        not _exact_keys(snapshot, keys)
        or snapshot.get("schema") != _SNAPSHOT_SCHEMA
        or snapshot.get("projectId") != project_id
        or snapshot.get("ownerId") != owner_id
        or snapshot.get("planSha256") != plan.get("planSha256")
        or _HEX_RE.fullmatch(
            str(snapshot.get("protectedAssetCensusSha256", ""))
        ) is None
        or _HEX_RE.fullmatch(str(snapshot.get("snapshotSha256", ""))) is None
        or not isinstance(snapshot.get("runtimeSources"), list)
        or not isinstance(snapshot.get("files"), list)
        or len(snapshot["runtimeSources"]) > _MAX_IDS
        or len(snapshot["files"]) > _MAX_IDS
    ):
        raise C5ReceiptStop("C5_DURABLE_DELETE_SNAPSHOT_INVALID")
    source_ids: list[str] = []
    for row in snapshot["runtimeSources"]:
        if (
            not _exact_keys(row, {"source_ref_id", "source_sha256"})
            or _SOURCE_REF_RE.fullmatch(str(row.get("source_ref_id", ""))) is None
            or _HEX_RE.fullmatch(str(row.get("source_sha256", ""))) is None
        ):
            raise C5ReceiptStop("C5_DURABLE_RUNTIME_SOURCE_SNAPSHOT_INVALID")
        source_ids.append(row["source_ref_id"])
    if len(set(source_ids)) != len(source_ids):
        raise C5ReceiptStop("C5_DURABLE_RUNTIME_SOURCE_SNAPSHOT_DUPLICATE")

    expected = {
        **{row["id"]: "EXCLUSIVE" for row in plan["exclusive"]},
        **{row["id"]: "RETAINED" for row in plan["retained"]},
    }
    seen: set[str] = set()
    seal_keys = {
        "schema", "rowPresent", "ownedTargetStorage", "messageOnlyTargetOwned",
        "knownMissingOriginal", "bytes", "logicalPaths", "source",
        "vectorDeleteRequired", "vectorOwnerAvailable", "codeEnvDeleteRequired",
        "codeEnvOwnerAvailable", "unsupportedStorage", "refs",
    }
    bool_keys = {
        "rowPresent", "ownedTargetStorage", "messageOnlyTargetOwned",
        "knownMissingOriginal", "vectorDeleteRequired", "vectorOwnerAvailable",
        "codeEnvDeleteRequired", "codeEnvOwnerAvailable", "unsupportedStorage",
    }
    for row in snapshot["files"]:
        if (
            not _exact_keys(row, {"id", "classification", "retentionReason", "seal"})
            or not _scope_ok(row.get("id"))
            or row.get("classification") not in {"EXCLUSIVE", "RETAINED"}
            or expected.get(row["id"]) != row["classification"]
            or row["id"] in seen
        ):
            raise C5ReceiptStop("C5_DURABLE_FILE_SNAPSHOT_INVALID")
        seen.add(row["id"])
        if row["classification"] == "EXCLUSIVE":
            if row.get("retentionReason") is not None:
                raise C5ReceiptStop("C5_DURABLE_EXCLUSIVE_RETENTION_CONFLICT")
        elif not _scope_ok(row.get("retentionReason")):
            raise C5ReceiptStop("C5_DURABLE_RETAINED_REASON_INVALID")
        seal = row.get("seal")
        if (
            not _exact_keys(seal, seal_keys)
            or seal.get("schema") != _FILE_SEAL_SCHEMA
            or any(type(seal.get(key)) is not bool for key in bool_keys)
            or type(seal.get("bytes")) is not int
            or seal["bytes"] < 0
            or not isinstance(seal.get("logicalPaths"), list)
            or len(seal["logicalPaths"]) > _MAX_PATHS
            or len(set(seal["logicalPaths"])) != len(seal["logicalPaths"])
            or not isinstance(seal.get("refs"), list)
            or len(seal["refs"]) > _MAX_IDS
            or seal.get("source") is not None and not _scope_ok(seal.get("source"))
            or seal["messageOnlyTargetOwned"] and seal["rowPresent"]
            or seal["messageOnlyTargetOwned"] and not seal["ownedTargetStorage"]
            or seal["knownMissingOriginal"] and
               (seal["rowPresent"] or len(seal["logicalPaths"]) != 0)
        ):
            raise C5ReceiptStop("C5_DURABLE_FILE_SEAL_INVALID")
        prefixes = (f"/uploads/{owner_id}/", f"/images/{owner_id}/")
        if any(
            not isinstance(value, str) or len(value) > 2048
            or "\x00" in value or ".." in value.split("/")
            or not value.startswith(prefixes)
            for value in seal["logicalPaths"]
        ):
            raise C5ReceiptStop("C5_DURABLE_FILE_SEAL_PATH_INVALID")
        refs: list[tuple[str, str]] = []
        for ref in seal["refs"]:
            if (
                not _exact_keys(ref, {"kind", "id"})
                or not _scope_ok(ref.get("kind"))
                or not _scope_ok(ref.get("id"))
            ):
                raise C5ReceiptStop("C5_DURABLE_FILE_SEAL_REFERENCE_INVALID")
            refs.append((ref["kind"], ref["id"]))
        if len(set(refs)) != len(refs):
            raise C5ReceiptStop("C5_DURABLE_FILE_SEAL_REFERENCE_DUPLICATE")
    if seen != set(expected):
        raise C5ReceiptStop("C5_DURABLE_FILE_SNAPSHOT_PLAN_MISMATCH")
    body = dict(snapshot)
    body.pop("snapshotSha256")
    if _canonical_sha256(body) != snapshot["snapshotSha256"]:
        raise C5ReceiptStop("C5_DURABLE_DELETE_SNAPSHOT_DIGEST_MISMATCH")


def _assert_legacy_correction(value: Any) -> None:
    keys = {
        "schema", "priorPlanSha256", "correctedPlanSha256",
        "priorReceiptRevision", "evidenceSha256",
    }
    if (
        not _exact_keys(value, keys)
        or value.get("schema") != _LEGACY_CORRECTION_SCHEMA
        or _HEX_RE.fullmatch(str(value.get("priorPlanSha256", ""))) is None
        or _HEX_RE.fullmatch(str(value.get("correctedPlanSha256", ""))) is None
        or _HEX_RE.fullmatch(str(value.get("evidenceSha256", ""))) is None
        or type(value.get("priorReceiptRevision")) is not int
        or value["priorReceiptRevision"] < 1
    ):
        raise C5ReceiptStop("C5_LEGACY_DELETE_PLAN_CORRECTION_INVALID")


def _assert_receipt(record: dict[str, Any], project_id: str, owner_id: str) -> None:
    if (
        not isinstance(record, dict)
        or record.get("schema") != _C5_SCHEMA
        or record.get("projectId") != project_id
        or record.get("ownerId") != owner_id
        or record.get("phase") not in _PHASES
        or not isinstance(record.get("deletedChats"), list)
        or not isinstance(record.get("deletedFiles"), list)
        or len(record["deletedChats"]) > _MAX_IDS
        or len(record["deletedFiles"]) > _MAX_IDS
        or len(set(record["deletedChats"])) != len(record["deletedChats"])
        or len(set(record["deletedFiles"])) != len(record["deletedFiles"])
        or any(not _scope_ok(x) for x in record["deletedChats"] + record["deletedFiles"])
    ):
        raise C5ReceiptStop("C5_INVALID_RECEIPT_RECORD")
    _assert_plan_shape(record.get("plan"), project_id, owner_id)
    retired = record.get("retiredSources")
    if retired is not None and (
        not isinstance(retired, list)
        or len(retired) > _MAX_IDS
        or len(set(retired)) != len(retired)
        or any(_SOURCE_REF_RE.fullmatch(str(value)) is None for value in retired)
    ):
        raise C5ReceiptStop("C5_RETIRED_SOURCE_RECEIPT_INVALID")
    snapshot = record.get("durableSnapshot")
    if snapshot is not None:
        _assert_snapshot(snapshot, record["plan"], project_id, owner_id)
        source_ids = {row["source_ref_id"] for row in snapshot["runtimeSources"]}
        if retired is None or not set(retired).issubset(source_ids):
            raise C5ReceiptStop("C5_RETIRED_SOURCE_NOT_IN_DURABLE_SNAPSHOT")
    correction = record.get("legacyPlanCorrection")
    if correction is not None:
        _assert_legacy_correction(correction)


class C5ProjectCascadeReceiptOwner:
    def __init__(
        self,
        *,
        service: WebContinuityService,
        librechat_project_id: str,
        owner_id: str,
        runtime_project_id: str,
        verify_project_owner_binding: Callable[..., Any],
        admitted_effect_writer: Callable[..., Any],
    ):
        if (
            not _scope_ok(owner_id)
            or not _scope_ok(runtime_project_id)
            or _PROJECT_RE.fullmatch(librechat_project_id or "") is None
        ):
            raise C5ReceiptStop("C5_RECEIPT_IDENTITY_INVALID")
        if not callable(verify_project_owner_binding) or not callable(admitted_effect_writer):
            raise C5ReceiptStop("C5_MISSING_RUNTIME_AUTHORITY_CONSUMER")
        self.service = service
        self.project_id = librechat_project_id
        self.owner_id = owner_id
        self.runtime_project_id = runtime_project_id
        self.verify_binding = verify_project_owner_binding
        self.effect_writer = admitted_effect_writer
        digest = sha256(
            ("AIDES_C5|" + owner_id + "|" + librechat_project_id +
             "|" + runtime_project_id).encode("utf-8")
        ).hexdigest().upper()
        self.artifact_id = "C5_PROJECT_CASCADE_" + digest
        self._assert_owner()

    def _assert_owner(self) -> None:
        _binding(
            self.verify_binding,
            librechat_project_id=self.project_id,
            owner_id=self.owner_id,
            runtime_project_id=self.runtime_project_id,
        )
        # Existing canonical record must be present, even after retirement.
        if not self.service._record_exists(
            self.service._project_artifact_id(self.runtime_project_id)
        ):
            raise C5ReceiptStop("C5_CANONICAL_RUNTIME_PROJECT_NOT_FOUND")
        record, _ = self.service._load_current_json(
            self.service._project_artifact_id(self.runtime_project_id)
        )
        if record.get("project_id") != self.runtime_project_id:
            raise C5ReceiptStop("C5_CANONICAL_RUNTIME_PROJECT_MISMATCH")

    def load(self) -> dict[str, Any] | None:
        with self.service._lock:
            self._assert_owner()
            if not self.service._record_exists(self.artifact_id):
                return None
            record, binding = self.service._load_current_json(self.artifact_id)
            if (
                record.get("runtimeProjectId") != self.runtime_project_id
                or record.get("ownerId") != self.owner_id
                or record.get("projectId") != self.project_id
                or record.get("schema") != _C5_SCHEMA
                or binding.get("revision") != record.get("c5_receipt_revision")
            ):
                raise C5ReceiptStop("C5_CROSS_OWNER_OR_TAMPERED_RECEIPT")
            _assert_receipt(record, self.project_id, self.owner_id)
            return record

    def persist(self, receipt: dict[str, Any]) -> dict[str, Any]:
        with self.service._lock:
            self._assert_owner()
            _assert_receipt(receipt, self.project_id, self.owner_id)
            admitted = self.effect_writer(
                librechat_project_id=self.project_id,
                owner_id=self.owner_id,
                runtime_project_id=self.runtime_project_id,
                phase=receipt["phase"],
            )
            if not (
                isinstance(admitted, dict)
                and admitted.get("authorized") is True
                and admitted.get("exclusive_writer") is True
                and admitted.get("protected_backup_ready") is True
                and admitted.get("active_pinned_jobs") == 0
            ):
                raise C5ReceiptStop("C5_WRITER_JOB_BACKUP_FENCE_NOT_PROVEN")

            prior = self.load()
            wanted = receipt.get("c5_receipt_revision", 0)
            if not isinstance(wanted, int) or isinstance(wanted, bool):
                raise C5ReceiptStop("C5_EXPECTED_RECEIPT_REVISION_INVALID")
            snapshot = receipt.get("durableSnapshot")
            retired_sources = receipt.get("retiredSources")
            if prior is None:
                if wanted != 0 or receipt["phase"] != "PREPARED":
                    raise C5ReceiptStop("C5_INITIAL_RECEIPT_PREPARE_REQUIRED")
                if snapshot is None or retired_sources != []:
                    raise C5ReceiptStop("C5_INITIAL_DURABLE_SNAPSHOT_REQUIRED")
                if receipt.get("legacyPlanCorrection") is not None:
                    raise C5ReceiptStop("C5_NEW_RECEIPT_CANNOT_CLAIM_LEGACY_CORRECTION")
            else:
                if wanted != prior["c5_receipt_revision"]:
                    raise C5ReceiptStop("C5_STALE_RECEIPT_REVISION")
                plan_changed = prior["plan"] != receipt["plan"]
                prior_snapshot = prior.get("durableSnapshot")
                correction = receipt.get("legacyPlanCorrection")
                if plan_changed or (prior_snapshot is None and snapshot is not None):
                    if (
                        prior_snapshot is not None
                        or prior.get("phase") != "PARTIAL_OR_BLOCKED"
                        or prior.get("c5Confirmed") is not True
                        or prior.get("nativeEffectOutcomeUnknown") is True
                        or correction is None
                    ):
                        raise C5ReceiptStop("C5_PLAN_CHANGED_AFTER_PREPARE")
                    _assert_legacy_correction(correction)
                    if (
                        correction["priorPlanSha256"] != prior["plan"]["planSha256"]
                        or correction["correctedPlanSha256"] != receipt["plan"]["planSha256"]
                        or correction["priorReceiptRevision"] != prior["c5_receipt_revision"]
                        or snapshot is None
                        or retired_sources is None
                    ):
                        raise C5ReceiptStop("C5_LEGACY_DELETE_PLAN_CORRECTION_SCOPE_MISMATCH")
                else:
                    if plan_changed:
                        raise C5ReceiptStop("C5_PLAN_CHANGED_AFTER_PREPARE")
                    if prior_snapshot is not None and snapshot != prior_snapshot:
                        raise C5ReceiptStop("C5_DURABLE_DELETE_SNAPSHOT_CHANGED")
                    if prior.get("legacyPlanCorrection") != correction:
                        raise C5ReceiptStop("C5_LEGACY_DELETE_PLAN_CORRECTION_CHANGED")
                if prior["phase"] == "COMPLETE" and receipt["phase"] != "COMPLETE":
                    raise C5ReceiptStop("C5_COMPLETED_RECEIPT_CANNOT_REOPEN")
                for field in ("deletedChats", "deletedFiles"):
                    if not set(prior[field]).issubset(receipt[field]):
                        raise C5ReceiptStop("C5_DELETION_RECEIPT_REGRESSION")
                if not set(prior.get("retiredSources", [])).issubset(
                    receipt.get("retiredSources", [])
                ):
                    raise C5ReceiptStop("C5_RETIRED_SOURCE_RECEIPT_REGRESSION")
                if prior.get("c5Confirmed") is True and receipt.get("c5Confirmed") is not True:
                    raise C5ReceiptStop("C5_NATIVE_RETIREMENT_CONFIRMATION_LOST")
            payload = dict(receipt)
            payload["runtimeProjectId"] = self.runtime_project_id
            # Native revisioned persist, exact manifest currentness and SHA.
            op_exec = self.service._operation_execution_id(
                project_id=self.runtime_project_id,
                chat_id=None,
                command_id="C5_CASCADE_RECEIPT_" + self.artifact_id[-36:],
            )
            record, binding = self.service._persist_json_revision(
                artifact_id=self.artifact_id,
                namespace="project_cascade_receipts",
                record=payload,
                revision_field="c5_receipt_revision",
                operation_execution_id=op_exec,
            )
            if record["c5_receipt_revision"] != binding["revision"]:
                raise C5ReceiptStop("C5_RECEIPT_STORE_REVISION_MISMATCH")
            return {
                "durable": True,
                "projectId": self.project_id,
                "ownerId": self.owner_id,
                "revision": binding["revision"],
                "sha256": binding["sha256"],
            }
