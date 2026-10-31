"""Deterministic, provider-neutral logical model profile policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json


class ModelPolicyError(ValueError):
    """Raised when a model policy request cannot be satisfied safely."""


class TaskKind(str, Enum):
    EXTRACT = "EXTRACT"
    WRITE = "WRITE"
    REASON = "REASON"
    AUDIT = "AUDIT"
    GENERAL = "GENERAL"


class ReasoningLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ModelSelectionMode(str, Enum):
    AUTO_RECOMMENDED = "AUTO_RECOMMENDED"
    COST_PRIORITY = "COST_PRIORITY"
    QUALITY_PRIORITY = "QUALITY_PRIORITY"
    USER_SELECTED_PROFILE = "USER_SELECTED_PROFILE"


@dataclass(frozen=True)
class TaskRequirement:
    task_kind: TaskKind
    reasoning_level: ReasoningLevel
    risk_level: RiskLevel
    structured_output: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task_kind, TaskKind):
            raise ModelPolicyError("task_kind must be a TaskKind")
        if not isinstance(self.reasoning_level, ReasoningLevel):
            raise ModelPolicyError("reasoning_level must be a ReasoningLevel")
        if not isinstance(self.risk_level, RiskLevel):
            raise ModelPolicyError("risk_level must be a RiskLevel")
        if not isinstance(self.structured_output, bool):
            raise ModelPolicyError("structured_output must be a bool")


@dataclass(frozen=True)
class ModelDecisionRequest:
    task: TaskRequirement
    selection_mode: ModelSelectionMode
    allowed_profiles: tuple[str, ...] = ()
    user_selected_profile: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskRequirement):
            raise ModelPolicyError("task must be a TaskRequirement")
        if not isinstance(self.selection_mode, ModelSelectionMode):
            raise ModelPolicyError("selection_mode must be a ModelSelectionMode")
        if not isinstance(self.allowed_profiles, tuple) or any(
            not isinstance(profile, str) or not profile for profile in self.allowed_profiles
        ):
            raise ModelPolicyError("allowed_profiles must be a tuple of non-empty strings")
        if self.user_selected_profile is not None and (
            not isinstance(self.user_selected_profile, str) or not self.user_selected_profile
        ):
            raise ModelPolicyError("user_selected_profile must be a non-empty string or None")
        if self.selection_mode is ModelSelectionMode.USER_SELECTED_PROFILE:
            if not self.user_selected_profile:
                raise ModelPolicyError("USER_SELECTED_PROFILE requires a user_selected_profile")
        elif self.user_selected_profile is not None:
            raise ModelPolicyError("non-user selection modes reject a stray user_selected_profile")


@dataclass(frozen=True)
class ModelDecision:
    policy_revision: str
    selection_mode: ModelSelectionMode
    selected_profile: str
    eligible_profiles: tuple[str, ...]
    decision_reason: str
    decision_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_revision": self.policy_revision,
            "selection_mode": self.selection_mode.value,
            "selected_profile": self.selected_profile,
            "eligible_profiles": list(self.eligible_profiles),
            "decision_reason": self.decision_reason,
            "decision_sha256": self.decision_sha256,
        }


MODEL_POLICY_REVISION = "E8_MODEL_POLICY_V0_R001"

_KNOWN_PROFILES = ("extract_fast", "write_main", "reason_high", "audit_high")
_BASE_ELIGIBILITY = {
    TaskKind.EXTRACT: ("extract_fast", "reason_high", "audit_high"),
    TaskKind.WRITE: ("write_main",),
    TaskKind.REASON: ("reason_high", "audit_high"),
    TaskKind.AUDIT: ("audit_high",),
    TaskKind.GENERAL: ("reason_high", "audit_high"),
}
_COST_ORDER = {profile: index for index, profile in enumerate(_KNOWN_PROFILES)}
_QUALITY_ORDER = tuple(reversed(_KNOWN_PROFILES))


def _canonical_decision_payload(
    *,
    policy_revision: str,
    selection_mode: ModelSelectionMode,
    selected_profile: str,
    eligible_profiles: tuple[str, ...],
    decision_reason: str,
) -> dict[str, object]:
    return {
        "decision_reason": decision_reason,
        "eligible_profiles": list(eligible_profiles),
        "policy_revision": policy_revision,
        "selected_profile": selected_profile,
        "selection_mode": selection_mode.value,
    }


def select_model_profile(request: ModelDecisionRequest) -> ModelDecision:
    """Select one legal logical profile without inspecting environment state."""
    if not isinstance(request, ModelDecisionRequest):
        raise ModelPolicyError("request must be a ModelDecisionRequest")

    requested = set(request.allowed_profiles) if request.allowed_profiles else set(_KNOWN_PROFILES)
    unknown = requested - set(_KNOWN_PROFILES)
    if unknown:
        raise ModelPolicyError(f"unknown allowed profile: {sorted(unknown)[0]}")

    eligible = list(_BASE_ELIGIBILITY[request.task.task_kind])
    if request.task.reasoning_level is ReasoningLevel.HIGH or request.task.risk_level is RiskLevel.HIGH:
        eligible = [profile for profile in eligible if profile != "extract_fast"]
    eligible = [profile for profile in _KNOWN_PROFILES if profile in eligible and profile in requested]
    if not eligible:
        raise ModelPolicyError("no eligible logical profile remains after policy constraints")

    mode = request.selection_mode
    if mode is ModelSelectionMode.USER_SELECTED_PROFILE:
        selected = request.user_selected_profile
        if selected not in eligible:
            raise ModelPolicyError("user-selected profile is unknown, disallowed, or ineligible")
        reason = "user-selected legal logical profile"
    elif mode in (ModelSelectionMode.AUTO_RECOMMENDED, ModelSelectionMode.COST_PRIORITY):
        selected = min(eligible, key=_COST_ORDER.__getitem__)
        reason = "lowest-cost eligible logical profile"
    elif mode is ModelSelectionMode.QUALITY_PRIORITY:
        selected = next(profile for profile in _QUALITY_ORDER if profile in eligible)
        reason = "highest-quality eligible logical profile"
    else:  # pragma: no cover - enum validation makes this unreachable
        raise ModelPolicyError("unsupported selection mode")

    payload = _canonical_decision_payload(
        policy_revision=MODEL_POLICY_REVISION,
        selection_mode=mode,
        selected_profile=selected,
        eligible_profiles=tuple(eligible),
        decision_reason=reason,
    )
    decision_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return ModelDecision(
        policy_revision=MODEL_POLICY_REVISION,
        selection_mode=mode,
        selected_profile=selected,
        eligible_profiles=tuple(eligible),
        decision_reason=reason,
        decision_sha256=decision_sha256,
    )
