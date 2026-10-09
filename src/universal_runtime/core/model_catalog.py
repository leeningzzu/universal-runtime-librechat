"""Runtime-owned, versioned model catalog and concrete model resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable

from .model_policy import ModelDecision


class ModelCatalogError(ValueError):
    """Raised when catalog data or a resolution request is unsafe or invalid."""


class ModelCatalogStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    PROMOTED = "PROMOTED"


class ModelUpdateMode(str, Enum):
    STRICT_PIN = "STRICT_PIN"
    LATEST_PROMOTED_AT_TASK_BOUNDARY = "LATEST_PROMOTED_AT_TASK_BOUNDARY"


_KNOWN_PROFILES = frozenset(("extract_fast", "write_main", "reason_high", "audit_high"))
_SHA256_RE = "0123456789abcdef"


def _canonical_sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_non_empty_string(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ModelCatalogError(f"{field} must be a non-empty string")


def _require_non_negative_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelCatalogError(f"{field} must be a non-negative integer")


@dataclass(frozen=True)
class ModelCatalogEntry:
    entry_id: str
    provider: str
    model: str
    eligible_profiles: tuple[str, ...]
    status: ModelCatalogStatus
    promotion_order: int
    cost_rank: int
    quality_rank: int
    latency_rank: int

    def __post_init__(self) -> None:
        _require_non_empty_string(self.entry_id, "entry_id")
        _require_non_empty_string(self.provider, "provider")
        _require_non_empty_string(self.model, "model")
        if not isinstance(self.eligible_profiles, tuple) or not self.eligible_profiles:
            raise ModelCatalogError("eligible_profiles must be a non-empty tuple")
        if any(not isinstance(profile, str) or not profile for profile in self.eligible_profiles):
            raise ModelCatalogError("eligible_profiles must contain non-empty strings")
        unknown = set(self.eligible_profiles) - _KNOWN_PROFILES
        if unknown:
            raise ModelCatalogError(f"unknown eligible logical profile: {sorted(unknown)[0]}")
        if len(set(self.eligible_profiles)) != len(self.eligible_profiles):
            raise ModelCatalogError("eligible_profiles must not contain duplicates")
        if not isinstance(self.status, ModelCatalogStatus):
            raise ModelCatalogError("status must be a ModelCatalogStatus")
        for field in ("promotion_order", "cost_rank", "quality_rank", "latency_rank"):
            _require_non_negative_int(getattr(self, field), field)

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "provider": self.provider,
            "model": self.model,
            "eligible_profiles": list(self.eligible_profiles),
            "status": self.status.value,
            "promotion_order": self.promotion_order,
            "cost_rank": self.cost_rank,
            "quality_rank": self.quality_rank,
            "latency_rank": self.latency_rank,
        }


@dataclass(frozen=True)
class ModelCatalog:
    catalog_revision: str
    entries: tuple[ModelCatalogEntry, ...]
    catalog_sha256: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.catalog_revision, "catalog_revision")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ModelCatalogError("entries must be a non-empty tuple")
        if any(not isinstance(entry, ModelCatalogEntry) for entry in self.entries):
            raise ModelCatalogError("entries must contain ModelCatalogEntry values")
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(set(entry_ids)) != len(entry_ids):
            raise ModelCatalogError("duplicate entry_id in catalog")
        if entry_ids != sorted(entry_ids):
            raise ModelCatalogError("entries must be sorted by entry_id")
        if (
            not isinstance(self.catalog_sha256, str)
            or len(self.catalog_sha256) != 64
            or any(char not in _SHA256_RE for char in self.catalog_sha256)
        ):
            raise ModelCatalogError("catalog_sha256 must be lowercase 64-hex")
        if self.catalog_sha256 != _canonical_sha(self._payload_without_sha()):
            raise ModelCatalogError("catalog_sha256 does not match catalog contents")

    def _payload_without_sha(self) -> dict[str, object]:
        return {
            "catalog_revision": self.catalog_revision,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def create(cls, catalog_revision: str, entries: Iterable[ModelCatalogEntry]) -> "ModelCatalog":
        _require_non_empty_string(catalog_revision, "catalog_revision")
        materialized = tuple(entries)
        if not materialized:
            raise ModelCatalogError("catalog requires at least one entry")
        if any(not isinstance(entry, ModelCatalogEntry) for entry in materialized):
            raise ModelCatalogError("entries must contain ModelCatalogEntry values")
        ids = [entry.entry_id for entry in materialized]
        if len(set(ids)) != len(ids):
            raise ModelCatalogError("duplicate entry_id in catalog")
        ordered = tuple(sorted(materialized, key=lambda entry: entry.entry_id))
        payload = {
            "catalog_revision": catalog_revision,
            "entries": [entry.to_dict() for entry in ordered],
        }
        return cls(catalog_revision, ordered, _canonical_sha(payload))

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_revision": self.catalog_revision,
            "entries": [entry.to_dict() for entry in self.entries],
            "catalog_sha256": self.catalog_sha256,
        }

    def promoted_entries_for_profile(self, profile_id: str) -> tuple[ModelCatalogEntry, ...]:
        _require_non_empty_string(profile_id, "profile_id")
        if profile_id not in _KNOWN_PROFILES:
            raise ModelCatalogError(f"unknown logical profile: {profile_id}")
        return tuple(
            entry
            for entry in self.entries
            if entry.status is ModelCatalogStatus.PROMOTED and profile_id in entry.eligible_profiles
        )


@dataclass(frozen=True)
class ModelResolutionRequest:
    decision: ModelDecision
    update_mode: ModelUpdateMode
    pinned_entry_id: str | None = None
    user_selected_entry_id: str | None = None
    allowed_providers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ModelDecision):
            raise ModelCatalogError("decision must be a ModelDecision")
        if not isinstance(self.update_mode, ModelUpdateMode):
            raise ModelCatalogError("update_mode must be a ModelUpdateMode")
        for field, value in (("pinned_entry_id", self.pinned_entry_id), ("user_selected_entry_id", self.user_selected_entry_id)):
            if value is not None:
                _require_non_empty_string(value, field)
        if not isinstance(self.allowed_providers, tuple) or any(
            not isinstance(provider, str) or not provider for provider in self.allowed_providers
        ):
            raise ModelCatalogError("allowed_providers must be a tuple of non-empty strings")
        if self.update_mode is ModelUpdateMode.STRICT_PIN:
            if self.pinned_entry_id is None and self.user_selected_entry_id is None:
                raise ModelCatalogError("STRICT_PIN requires pinned_entry_id or user_selected_entry_id")
        elif self.pinned_entry_id is not None and self.user_selected_entry_id is None:
            raise ModelCatalogError(
                "LATEST_PROMOTED_AT_TASK_BOUNDARY rejects a stray pinned_entry_id"
            )


@dataclass(frozen=True)
class ResolvedModelExecution:
    model_policy_revision: str
    model_decision_sha256: str
    selected_profile: str
    catalog_revision: str
    catalog_sha256: str
    update_mode: ModelUpdateMode
    model_entry_id: str
    provider: str
    model: str
    resolution_reason: str
    resolution_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "model_policy_revision",
            "model_decision_sha256",
            "selected_profile",
            "catalog_revision",
            "catalog_sha256",
            "model_entry_id",
            "provider",
            "model",
            "resolution_reason",
        ):
            _require_non_empty_string(getattr(self, field), field)
        if not isinstance(self.update_mode, ModelUpdateMode):
            raise ModelCatalogError("update_mode must be a ModelUpdateMode")
        for field in ("model_decision_sha256", "catalog_sha256", "resolution_sha256"):
            value = getattr(self, field)
            if len(value) != 64 or any(char not in _SHA256_RE for char in value):
                raise ModelCatalogError(f"{field} must be lowercase 64-hex")
        if self.selected_profile not in _KNOWN_PROFILES:
            raise ModelCatalogError(f"unknown logical profile: {self.selected_profile}")
        if self.resolution_sha256 != _canonical_sha(self._payload_without_sha()):
            raise ModelCatalogError("resolution_sha256 does not match resolution contents")

    def _payload_without_sha(self) -> dict[str, object]:
        return {
            "model_policy_revision": self.model_policy_revision,
            "model_decision_sha256": self.model_decision_sha256,
            "selected_profile": self.selected_profile,
            "catalog_revision": self.catalog_revision,
            "catalog_sha256": self.catalog_sha256,
            "update_mode": self.update_mode.value,
            "model_entry_id": self.model_entry_id,
            "provider": self.provider,
            "model": self.model,
            "resolution_reason": self.resolution_reason,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload_without_sha(), "resolution_sha256": self.resolution_sha256}


def resolve_model_execution(
    request: ModelResolutionRequest, catalog: ModelCatalog
) -> ResolvedModelExecution:
    """Resolve one immutable concrete model without environment or network access."""
    if not isinstance(request, ModelResolutionRequest):
        raise ModelCatalogError("request must be a ModelResolutionRequest")
    if not isinstance(catalog, ModelCatalog):
        raise ModelCatalogError("catalog must be a ModelCatalog")

    profile = request.decision.selected_profile
    candidates = list(catalog.promoted_entries_for_profile(profile))
    if request.allowed_providers:
        allowed = set(request.allowed_providers)
        candidates = [entry for entry in candidates if entry.provider in allowed]
    by_id = {entry.entry_id: entry for entry in candidates}

    if request.user_selected_entry_id is not None:
        selected = by_id.get(request.user_selected_entry_id)
        if selected is None:
            raise ModelCatalogError("user-selected concrete model is not legal")
        reason = "user-selected legal promoted concrete model"
    elif request.update_mode is ModelUpdateMode.STRICT_PIN:
        selected = by_id.get(request.pinned_entry_id or "")
        if selected is None:
            raise ModelCatalogError("pinned concrete model is not legal")
        reason = "strict pinned concrete model"
    else:
        if not candidates:
            raise ModelCatalogError("no promoted eligible concrete model remains")
        selected = sorted(
            candidates,
            key=lambda entry: (
                -entry.promotion_order,
                -entry.quality_rank,
                entry.cost_rank,
                entry.latency_rank,
                entry.entry_id,
            ),
        )[0]
        reason = "latest promoted eligible model at task boundary"

    payload = {
        "model_policy_revision": request.decision.policy_revision,
        "model_decision_sha256": request.decision.decision_sha256,
        "selected_profile": profile,
        "catalog_revision": catalog.catalog_revision,
        "catalog_sha256": catalog.catalog_sha256,
        "update_mode": request.update_mode.value,
        "model_entry_id": selected.entry_id,
        "provider": selected.provider,
        "model": selected.model,
        "resolution_reason": reason,
    }
    return ResolvedModelExecution(
        **{**payload, "update_mode": request.update_mode},
        resolution_sha256=_canonical_sha(payload),
    )
