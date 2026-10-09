"""Focused E8A deterministic logical model policy contract tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from universal_runtime.core.model_policy import (
    MODEL_POLICY_REVISION,
    ModelDecisionRequest,
    ModelPolicyError,
    ModelSelectionMode,
    ReasoningLevel,
    RiskLevel,
    TaskKind,
    TaskRequirement,
    select_model_profile,
)


def requirement(kind: TaskKind, reasoning: ReasoningLevel = ReasoningLevel.LOW, risk: RiskLevel = RiskLevel.LOW) -> TaskRequirement:
    return TaskRequirement(kind, reasoning, risk)


def choose(task: TaskRequirement, mode: ModelSelectionMode, **kwargs: object):
    return select_model_profile(ModelDecisionRequest(task, mode, **kwargs))


def test_auto_low_risk_extract_is_extract_fast() -> None:
    assert choose(requirement(TaskKind.EXTRACT), ModelSelectionMode.AUTO_RECOMMENDED).selected_profile == "extract_fast"


def test_high_reasoning_extract_cannot_use_extract_fast() -> None:
    task = requirement(TaskKind.EXTRACT, ReasoningLevel.HIGH)
    assert choose(task, ModelSelectionMode.AUTO_RECOMMENDED).selected_profile == "reason_high"
    assert choose(task, ModelSelectionMode.COST_PRIORITY).selected_profile == "reason_high"


def test_audit_and_write_are_fixed_profiles() -> None:
    assert choose(requirement(TaskKind.AUDIT), ModelSelectionMode.AUTO_RECOMMENDED).selected_profile == "audit_high"
    assert choose(requirement(TaskKind.WRITE), ModelSelectionMode.AUTO_RECOMMENDED).selected_profile == "write_main"


def test_general_is_reason_high_under_auto_and_cost() -> None:
    task = requirement(TaskKind.GENERAL)
    assert choose(task, ModelSelectionMode.AUTO_RECOMMENDED).selected_profile == "reason_high"
    assert choose(task, ModelSelectionMode.COST_PRIORITY).selected_profile == "reason_high"


def test_quality_priority_picks_highest_quality_eligible_profile() -> None:
    task = requirement(TaskKind.EXTRACT)
    assert choose(task, ModelSelectionMode.QUALITY_PRIORITY).selected_profile == "audit_high"


def test_allowed_profiles_constrain_selection() -> None:
    task = requirement(TaskKind.EXTRACT)
    decision = choose(task, ModelSelectionMode.AUTO_RECOMMENDED, allowed_profiles=("reason_high", "audit_high"))
    assert decision.selected_profile == "reason_high"
    assert decision.eligible_profiles == ("reason_high", "audit_high")


def test_user_selected_profile_accepts_legal_choice_and_rejects_invalid_choices() -> None:
    task = requirement(TaskKind.EXTRACT)
    decision = choose(task, ModelSelectionMode.USER_SELECTED_PROFILE, user_selected_profile="reason_high")
    assert decision.selected_profile == "reason_high"
    with pytest.raises(ModelPolicyError):
        choose(task, ModelSelectionMode.USER_SELECTED_PROFILE, user_selected_profile="unknown")
    with pytest.raises(ModelPolicyError):
        choose(task, ModelSelectionMode.USER_SELECTED_PROFILE, allowed_profiles=("extract_fast",), user_selected_profile="reason_high")
    with pytest.raises(ModelPolicyError):
        choose(requirement(TaskKind.WRITE), ModelSelectionMode.USER_SELECTED_PROFILE, user_selected_profile="reason_high")


def test_missing_or_stray_user_selection_fails_closed() -> None:
    with pytest.raises(ModelPolicyError):
        choose(requirement(TaskKind.WRITE), ModelSelectionMode.USER_SELECTED_PROFILE)
    with pytest.raises(ModelPolicyError):
        choose(requirement(TaskKind.WRITE), ModelSelectionMode.AUTO_RECOMMENDED, user_selected_profile="write_main")


def test_no_eligible_profile_fails_closed() -> None:
    with pytest.raises(ModelPolicyError):
        choose(requirement(TaskKind.WRITE), ModelSelectionMode.AUTO_RECOMMENDED, allowed_profiles=("reason_high",))
    with pytest.raises(ModelPolicyError):
        choose(requirement(TaskKind.WRITE), ModelSelectionMode.AUTO_RECOMMENDED, allowed_profiles=("not_known",))


def test_decision_is_immutable_and_hash_is_stable_lowercase_exact_sha() -> None:
    decision = choose(requirement(TaskKind.EXTRACT), ModelSelectionMode.AUTO_RECOMMENDED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.selected_profile = "audit_high"  # type: ignore[misc]
    payload = decision.to_dict()
    digest_payload = {key: value for key, value in payload.items() if key != "decision_sha256"}
    expected = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    assert decision.policy_revision == MODEL_POLICY_REVISION
    assert decision.decision_sha256 == expected
    assert decision.decision_sha256 == decision.decision_sha256.lower()
    assert decision.decision_sha256 == choose(requirement(TaskKind.EXTRACT), ModelSelectionMode.AUTO_RECOMMENDED).decision_sha256


def test_contract_is_provider_neutral_and_job_bundle_binds_policy_evidence() -> None:
    decision = choose(requirement(TaskKind.GENERAL), ModelSelectionMode.AUTO_RECOMMENDED)
    assert set(decision.to_dict()) == {
        "policy_revision", "selection_mode", "selected_profile", "eligible_profiles", "decision_reason", "decision_sha256",
    }
    assert not any("provider" in field or field == "model" for field in decision.to_dict())
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "job_bundle.schema.json").read_text(encoding="utf-8"))
    for field in ("model_profile", "model_selection_mode", "model_policy_revision", "model_decision_sha256"):
        assert field in schema["required"]
    assert schema["properties"]["model_profile"]["type"] == "string"


def test_no_live_model_or_network_call_is_required() -> None:
    assert select_model_profile(ModelDecisionRequest(requirement(TaskKind.REASON), ModelSelectionMode.COST_PRIORITY)).selected_profile == "reason_high"
