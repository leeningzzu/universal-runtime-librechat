"""Small, deterministic Runtime-owned Gate Candidate promotion boundary."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .enums import PersistenceClass
from .hashing import sha256_bytes
from .routing import RouteAction, RouteDecision


class PromotionError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovalEvidence:
    approval_id: str
    approver_id: str
    job_id: str
    artifact_id: str
    revision: int | str
    candidate_sha256: str
    reviewed_sha256: str
    approved: bool


@dataclass(frozen=True)
class PromotionRequest:
    route: RouteDecision
    candidate_path: Path
    candidate_manifest_path: Path
    approval: ApprovalEvidence


@dataclass(frozen=True)
class PromotionReceipt:
    promotion_id: str
    source_job_id: str
    source_artifact_id: str
    source_revision: int | str
    source_sha256: str
    reviewed_sha256: str
    approval_id: str
    approver_id: str
    approval_bound_sha256: str
    authoritative_artifact_sha256: str
    persistence_class: str
    provenance: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


class PromotionAuthority:
    """Promotes one exact candidate into an immutable per-promotion bundle."""
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.authority_root = self.root / "_authoritative"
        self.authority_root.mkdir(parents=True, exist_ok=True)

    def _identity(self, request: PromotionRequest) -> str:
        a = request.approval
        # The approval identity names the logical authority transition.  Its
        # payload is checked against the persisted receipt on retry, so a
        # reused identity with different bytes fails closed rather than
        # creating a second authoritative record.
        binding = {"job_id": a.job_id, "artifact_id": a.artifact_id,
                   "revision": a.revision, "approval_id": a.approval_id}
        return hashlib.sha256(_canonical(binding)).hexdigest()

    def _validate(self, request: PromotionRequest) -> bytes:
        route, approval = request.route, request.approval
        if route.action is not RouteAction.GATE_CANDIDATE or not route.advance_permitted:
            raise PromotionError("promotion requires an exact Gate Candidate route")
        if not approval.approved:
            raise PromotionError("explicit approval is required")
        if not all(isinstance(getattr(approval, k), str) and getattr(approval, k) for k in ("approval_id", "approver_id", "job_id", "artifact_id", "candidate_sha256", "reviewed_sha256")):
            raise PromotionError("approval evidence is incomplete")
        if approval.artifact_id != route.artifact_id or approval.revision != route.revision:
            raise PromotionError("approval candidate binding mismatch")
        if approval.reviewed_sha256 != route.reviewed_sha256 or approval.candidate_sha256 != route.reviewed_sha256:
            raise PromotionError("approval SHA binding mismatch")
        candidate = Path(request.candidate_path)
        manifest_path = Path(request.candidate_manifest_path)
        if not candidate.is_file() or not manifest_path.is_file():
            raise PromotionError("candidate or manifest is missing")
        data = candidate.read_bytes()
        actual_sha = sha256_bytes(data)
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if raw.get("artifact_id") != route.artifact_id or raw.get("revision") != route.revision or raw.get("sha256") != actual_sha:
            raise PromotionError("current candidate manifest binding mismatch")
        if actual_sha != approval.candidate_sha256 or actual_sha != route.reviewed_sha256:
            raise PromotionError("candidate bytes do not match reviewed SHA")
        return data

    def promote(self, request: PromotionRequest, *, fail_before_commit: bool = False) -> PromotionReceipt:
        data = self._validate(request)
        identity = self._identity(request)
        final = self.authority_root / identity
        receipt_path = final / "receipt.json"
        if final.exists():
            if not receipt_path.is_file():
                raise PromotionError("conflicting incomplete promotion record")
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if existing.get("promotion_id") != identity or any(existing.get(k) != v for k, v in {
                "source_job_id": request.approval.job_id,
                "source_artifact_id": request.route.artifact_id,
                "source_revision": request.route.revision,
                "source_sha256": sha256_bytes(data),
                "reviewed_sha256": request.route.reviewed_sha256,
                "approval_id": request.approval.approval_id,
                "approval_bound_sha256": request.approval.candidate_sha256,
            }.items()):
                raise PromotionError("conflicting duplicate promotion")
            return PromotionReceipt(**existing)
        tmp = self.authority_root / (f".staging-{identity}-{uuid.uuid4().hex}")
        try:
            tmp.mkdir()
            (tmp / "artifact").write_bytes(data)
            manifest = {"artifact_id": request.route.artifact_id, "revision": request.route.revision, "sha256": sha256_bytes(data), "persistence_class": PersistenceClass.AUTHORITATIVE.value}
            (tmp / "manifest.json").write_bytes(_canonical(manifest))
            receipt = PromotionReceipt(identity, request.approval.job_id, request.route.artifact_id, request.route.revision, sha256_bytes(data), request.route.reviewed_sha256, request.approval.approval_id, request.approval.approver_id, request.approval.candidate_sha256, sha256_bytes(data), PersistenceClass.AUTHORITATIVE.value, {"candidate_path": str(request.candidate_path), "candidate_manifest_path": str(request.candidate_manifest_path)})
            (tmp / "receipt.json").write_bytes(_canonical(receipt.model_dump()))
            if fail_before_commit:
                raise PromotionError("injected pre-commit failure")
            os.replace(tmp, final)
            return receipt
        except Exception:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            raise


def promote(request: PromotionRequest, root: Path) -> PromotionReceipt:
    return PromotionAuthority(root).promote(request)


__all__ = ["ApprovalEvidence", "PromotionRequest", "PromotionReceipt", "PromotionError", "PromotionAuthority", "promote"]
