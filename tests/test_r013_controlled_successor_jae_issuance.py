
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from universal_runtime.core.artifact_store import ArtifactStore, R009OpaqueArtifactBinding
from universal_runtime.core.job_authority import JobAuthorityRegistry, JobAuthorityError
from universal_runtime.core.human_decision_authority import HumanDecisionAuthority
from universal_runtime.web_general_chat_formal_prepare import GeneralChatFormalPrepareService
from universal_runtime.core.hashing import sha256_bytes


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha(value):
    return sha256_bytes(canonical(value))


def artifact_identity(label: str) -> str:
    return hashlib.sha256(("TEST:" + label).encode("utf-8")).hexdigest()


def persist(store: ArtifactStore, *, job_id: str, label: str, obj: dict) -> R009OpaqueArtifactBinding:
    raw = canonical(obj)
    binding, _manifest = store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
        artifact_identity_sha256=artifact_identity(label),
        artifact_bytes=raw,
        job_id=job_id,
        expected_artifact_sha256=hashlib.sha256(raw).hexdigest(),
    )
    return binding


def make_active_predecessor(tmp_path: Path, *, suffix: str = "1"):
    runtime = tmp_path / "runtime"
    store = ArtifactStore(runtime / "artifacts")
    registry = JobAuthorityRegistry(runtime, store)
    hda = HumanDecisionAuthority(runtime, store, registry)
    job_id = "JOB_TEST_" + suffix
    jae = "JAE_" + suffix * 64
    lineage = hashlib.sha256(("LINEAGE:" + suffix).encode()).hexdigest()
    authority_binding = sha({
        "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
        "job_authority_event_id": jae,
        "job_lineage_identity_sha256": lineage,
    })
    snapshot = {
        "schema": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1",
        "snapshot_revision": 1,
        "job_authority_event_id": jae,
        "job_lineage_identity_sha256": lineage,
        "job_authority_binding_sha256": authority_binding,
    }
    snapshot_binding = persist(
        store, job_id=job_id, label=f"snapshot-{suffix}", obj=snapshot
    )
    jxs = "JXS_" + sha({
        "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
        "job_authority_event_id": jae,
        "snapshot_content_sha256": snapshot_binding.artifact_sha256,
    })
    registration = {
        "schema": "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2",
        "registration_revision": 1,
        "job_authority_event_id": jae,
        "job_authority_binding_sha256": authority_binding,
        "job_execution_authority_snapshot_id": jxs,
        "job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
        "job_execution_authority_snapshot_artifact_identity_sha256":
            snapshot_binding.artifact_identity_sha256,
        "job_execution_authority_snapshot_artifact_revision": snapshot_binding.artifact_revision,
        "job_execution_authority_snapshot_artifact_sha256": snapshot_binding.artifact_sha256,
        "activation_basis": "INITIAL_JOB_CREATION",
        "predecessor_approval_slot_key_sha256": None,
        "predecessor_invalidation_sha256": None,
        "job_transition_intent_sha256": None,
        "state": "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT",
    }
    reg_binding = persist(
        store, job_id=job_id, label=f"registration-{suffix}", obj=registration
    )
    source = registry.register_or_replay_one_active_snapshot_for_jae_v1(
        registration_binding=reg_binding
    )
    assert source["job_authority_event_id"] == jae
    return {
        "runtime": runtime,
        "store": store,
        "registry": registry,
        "hda": hda,
        "job_id": job_id,
        "jae": jae,
        "lineage": lineage,
        "snapshot": snapshot,
        "snapshot_binding": snapshot_binding,
        "jxs": jxs,
        "registration": registration,
        "reg_binding": reg_binding,
    }


def select_dre_branch(state: dict, *, publish_request: bool = True):
    store = state["store"]
    registry = state["registry"]
    jae = state["jae"]
    jxs = state["jxs"]
    snap = state["snapshot_binding"]
    reg = state["reg_binding"]
    job_id = state["job_id"]

    request_content = {
        "schema": "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_CONTENT_SEMANTIC_V1",
        "job_authority_event_id": jae,
        "job_execution_authority_snapshot_id": jxs,
        "job_execution_authority_snapshot_sha256": snap.artifact_sha256,
        "requested_decision_code": "APPROVE_ONE_LIVE_ATTEMPT",
        "live_attempts_max": 1,
        "model_calls_max": 1,
        "network_calls_max": 1,
        "retries_max": 0,
        "fallback_allowed": False,
    }
    request_binding = persist(
        store, job_id=job_id, label="request-content", obj=request_content
    )
    request_key = sha({
        "namespace": "RUNTIME_LIVE_EXECUTION_ONE_REQUEST_PER_ACTIVE_SNAPSHOT_V1",
        "job_authority_event_id": jae,
        "job_execution_authority_snapshot_id": jxs,
        "job_execution_authority_snapshot_sha256": snap.artifact_sha256,
        "job_execution_snapshot_registration_sha256": reg.artifact_sha256,
    })
    dre = "DRE_" + request_key
    v3 = {
        "schema": "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_BINDING_V3",
        "snapshot_decision_request_key_sha256": request_key,
        "decision_request_event_id": dre,
        "job_authority_event_id": jae,
        "job_execution_authority_snapshot_id": jxs,
        "job_execution_authority_snapshot_sha256": snap.artifact_sha256,
        "job_execution_authority_snapshot_artifact_identity_sha256":
            snap.artifact_identity_sha256,
        "job_execution_authority_snapshot_artifact_revision": snap.artifact_revision,
        "job_execution_authority_snapshot_artifact_sha256": snap.artifact_sha256,
        "job_execution_snapshot_registration_sha256": reg.artifact_sha256,
        "job_execution_snapshot_registration_artifact_identity_sha256":
            reg.artifact_identity_sha256,
        "job_execution_snapshot_registration_artifact_revision": reg.artifact_revision,
        "job_execution_snapshot_registration_artifact_sha256": reg.artifact_sha256,
        "decision_request_content_sha256": request_binding.artifact_sha256,
        "decision_request_content_artifact_identity_sha256":
            request_binding.artifact_identity_sha256,
        "decision_request_content_artifact_revision": request_binding.artifact_revision,
        "decision_request_content_artifact_sha256": request_binding.artifact_sha256,
        "decision_scope_sha256": snap.artifact_sha256,
        "live_attempts_max": 1,
        "model_calls_max": 1,
        "network_calls_max": 1,
        "retries_max": 0,
        "fallback_allowed": False,
    }
    identity = sha(v3)
    branch_key = sha({
        "namespace": "RUNTIME_JOB_PREAPPROVAL_BRANCH_KEY_V1",
        "predecessor_job_authority_event_id": jae,
        "predecessor_job_execution_authority_snapshot_id": jxs,
        "predecessor_job_execution_authority_snapshot_sha256": snap.artifact_sha256,
        "predecessor_job_execution_snapshot_registration_sha256": reg.artifact_sha256,
    })
    branch = {
        "schema": "RUNTIME_JOB_PREAPPROVAL_DRE_BRANCH_SELECTION_SEMANTIC_V2",
        "preapproval_branch_key_sha256": branch_key,
        "branch_code": "DRE_ISSUANCE_SELECTED",
        "predecessor_job_authority_event_id": jae,
        "predecessor_job_execution_authority_snapshot_id": jxs,
        "predecessor_job_execution_authority_snapshot_sha256": snap.artifact_sha256,
        "predecessor_job_execution_snapshot_registration_sha256": reg.artifact_sha256,
        "snapshot_decision_request_key_sha256": request_key,
        "decision_request_event_id": dre,
        "decision_request_identity_sha256": identity,
        "request_recovery_mode": "INLINE_COMPLETE_REQUEST_BINDING_V3",
        "decision_request_binding_v3": v3,
    }
    branch_binding = persist(store, job_id=job_id, label="dre-branch", obj=branch)
    source = registry.select_or_replay_one_preapproval_branch_for_active_registration_v2(
        branch_binding=branch_binding
    )
    assert source["branch_code"] == "DRE_ISSUANCE_SELECTED"
    request_source = None
    if publish_request:
        request_source = state["hda"].issue_or_replay_one_decision_request_for_selected_active_snapshot_v3(
            preapproval_branch_key_sha256=branch_key
        )
        assert request_source["decision_request_event_id"] == dre
        assert request_source["decision_request_identity_sha256"] == identity
    return {
        "branch": branch,
        "branch_binding": branch_binding,
        "branch_source": source,
        "branch_key": branch_key,
        "dre": dre,
        "dre_identity": identity,
        "request_source": request_source,
    }


def build_successor_snapshot_and_intent(state: dict, issuance: dict, dre: dict):
    store = state["store"]
    job_id = state["job_id"]
    successor_jae = issuance["successor_job_authority_event_id"]
    lineage = issuance["job_lineage_identity_sha256"]
    authority_binding = sha({
        "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
        "job_authority_event_id": successor_jae,
        "job_lineage_identity_sha256": lineage,
    })
    successor_snapshot = {
        "schema": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1",
        "snapshot_revision": 1,
        "job_authority_event_id": successor_jae,
        "job_lineage_identity_sha256": lineage,
        "job_authority_binding_sha256": authority_binding,
    }
    successor_binding = persist(
        store, job_id=job_id, label="successor-snapshot", obj=successor_snapshot
    )
    successor_jxs = "JXS_" + sha({
        "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
        "job_authority_event_id": successor_jae,
        "snapshot_content_sha256": successor_binding.artifact_sha256,
    })
    intent = {
        "schema": "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        "predecessor_stage": "DRE_PENDING_NO_TERMINAL_DECISION",
        "transition_code": "CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        "predecessor_job_authority_event_id": state["jae"],
        "predecessor_job_execution_authority_snapshot_id": state["jxs"],
        "predecessor_job_execution_authority_snapshot_sha256":
            state["snapshot_binding"].artifact_sha256,
        "predecessor_job_execution_snapshot_registration_sha256":
            state["reg_binding"].artifact_sha256,
        "predecessor_decision_request_event_id": dre["dre"],
        "predecessor_decision_request_identity_sha256": dre["dre_identity"],
        "successor_job_authority_event_id": successor_jae,
        "successor_job_authority_binding_sha256": authority_binding,
        "successor_job_execution_authority_snapshot_id": successor_jxs,
        "successor_job_execution_authority_snapshot_sha256":
            successor_binding.artifact_sha256,
        "successor_job_execution_authority_snapshot_artifact_identity_sha256":
            successor_binding.artifact_identity_sha256,
        "successor_job_execution_authority_snapshot_artifact_revision":
            successor_binding.artifact_revision,
        "successor_job_execution_authority_snapshot_artifact_sha256":
            successor_binding.artifact_sha256,
        "successor_preparation_state": "PREPARED_NON_EXECUTION_ELIGIBLE",
        "successor_activation_required": True,
    }
    intent_binding = persist(store, job_id=job_id, label="transition-intent", obj=intent)
    return successor_snapshot, successor_binding, intent, intent_binding


def test_dre_pending_issuance_replay_and_transition_code_conflict(tmp_path):
    state = make_active_predecessor(tmp_path)
    dre = select_dre_branch(state)
    registry = state["registry"]

    first = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        human_decision_authority=state["hda"],
    )
    second = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        human_decision_authority=state["hda"],
    )
    assert second == first
    assert first["successor_job_authority_event_id"].startswith("JAE_")
    assert first["predecessor_decision_request_event_id"] == dre["dre"]
    assert first["predecessor_decision_request_identity_sha256"] == dre["dre_identity"]

    with pytest.raises(JobAuthorityError, match="first-writer conflict"):
        registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
            predecessor_job_authority_event_id=state["jae"],
            transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
            transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
            transition_code="CONTROLLED_REOPEN_MATERIAL_INPUT_CHANGE",
            human_decision_authority=state["hda"],
        )


def test_controlled_cancel_cannot_issue_successor_jae(tmp_path):
    state = make_active_predecessor(tmp_path)
    with pytest.raises(JobAuthorityError, match="CONTROLLED_CANCEL_MUST_NOT_ISSUE_SUCCESSOR_JAE"):
        state["registry"].issue_or_replay_one_controlled_successor_job_authority_event_v1(
            predecessor_job_authority_event_id=state["jae"],
            transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
            transition_stage="ACTIVE_PREDECESSOR_NO_DRE",
            transition_code="CONTROLLED_CANCEL",
        )


def test_pre_dre_issuance_uses_recomputed_branch_key_and_requires_absence(tmp_path):
    state = make_active_predecessor(tmp_path)
    registry = state["registry"]
    issued = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="ACTIVE_PREDECESSOR_NO_DRE",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
    )
    expected_branch_key = sha({
        "namespace": "RUNTIME_JOB_PREAPPROVAL_BRANCH_KEY_V1",
        "predecessor_job_authority_event_id": state["jae"],
        "predecessor_job_execution_authority_snapshot_id": state["jxs"],
        "predecessor_job_execution_authority_snapshot_sha256":
            state["snapshot_binding"].artifact_sha256,
        "predecessor_job_execution_snapshot_registration_sha256":
            state["reg_binding"].artifact_sha256,
    })
    assert issued["stage_anchor_sha256"] == expected_branch_key
    assert issued["preapproval_branch_key_sha256"] is None


def test_lineage_claim_requires_owner_issued_jae_and_binds_issuance_source(tmp_path):
    state = make_active_predecessor(tmp_path)
    dre = select_dre_branch(state)
    registry = state["registry"]
    issuance = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        human_decision_authority=state["hda"],
    )
    _snapshot, successor_binding, _intent, intent_binding = build_successor_snapshot_and_intent(
        state, issuance, dre
    )
    claim = registry.claim_or_replay_one_transition_bound_successor_lineage_v1(
        transition_intent_binding=intent_binding,
        successor_snapshot_binding=successor_binding,
    )
    assert claim["schema"] == "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V2"
    assert (
        claim["controlled_successor_jae_issuance_key_sha256"]
        == issuance["controlled_successor_jae_issuance_key_sha256"]
    )
    assert claim["controlled_successor_jae_issuance_source_record_sha256"] == sha256_bytes(
        canonical(issuance)
    )


def test_caller_selected_successor_jae_without_owner_issuance_is_rejected(tmp_path):
    state = make_active_predecessor(tmp_path)
    dre = select_dre_branch(state)
    store = state["store"]
    registry = state["registry"]
    fake_jae = "JAE_" + "f" * 64
    lineage = state["lineage"]
    authority_binding = sha({
        "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
        "job_authority_event_id": fake_jae,
        "job_lineage_identity_sha256": lineage,
    })
    snapshot = {
        "schema": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1",
        "snapshot_revision": 1,
        "job_authority_event_id": fake_jae,
        "job_lineage_identity_sha256": lineage,
        "job_authority_binding_sha256": authority_binding,
    }
    successor_binding = persist(
        store, job_id=state["job_id"], label="fake-successor-snapshot", obj=snapshot
    )
    jxs = "JXS_" + sha({
        "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
        "job_authority_event_id": fake_jae,
        "snapshot_content_sha256": successor_binding.artifact_sha256,
    })
    intent = {
        "schema": "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        "predecessor_stage": "DRE_PENDING_NO_TERMINAL_DECISION",
        "transition_code": "CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        "predecessor_job_authority_event_id": state["jae"],
        "predecessor_job_execution_authority_snapshot_id": state["jxs"],
        "predecessor_job_execution_authority_snapshot_sha256":
            state["snapshot_binding"].artifact_sha256,
        "predecessor_job_execution_snapshot_registration_sha256":
            state["reg_binding"].artifact_sha256,
        "predecessor_decision_request_event_id": dre["dre"],
        "predecessor_decision_request_identity_sha256": dre["dre_identity"],
        "successor_job_authority_event_id": fake_jae,
        "successor_job_authority_binding_sha256": authority_binding,
        "successor_job_execution_authority_snapshot_id": jxs,
        "successor_job_execution_authority_snapshot_sha256":
            successor_binding.artifact_sha256,
        "successor_job_execution_authority_snapshot_artifact_identity_sha256":
            successor_binding.artifact_identity_sha256,
        "successor_job_execution_authority_snapshot_artifact_revision":
            successor_binding.artifact_revision,
        "successor_job_execution_authority_snapshot_artifact_sha256":
            successor_binding.artifact_sha256,
        "successor_preparation_state": "PREPARED_NON_EXECUTION_ELIGIBLE",
        "successor_activation_required": True,
    }
    intent_binding = persist(
        store, job_id=state["job_id"], label="fake-transition-intent", obj=intent
    )
    with pytest.raises(JobAuthorityError, match="exactly one owner issuance source"):
        registry.claim_or_replay_one_transition_bound_successor_lineage_v1(
            transition_intent_binding=intent_binding,
            successor_snapshot_binding=successor_binding,
        )


def test_initial_jae_mint_skips_controlled_successor_issuance_collision(tmp_path, monkeypatch):
    state = make_active_predecessor(tmp_path)
    registry = state["registry"]
    issuance = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="ACTIVE_PREDECESSOR_NO_DRE",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
    )
    first_suffix = issuance["successor_job_authority_event_id"][4:]
    values = iter([first_suffix, "e" * 64])
    monkeypatch.setattr("universal_runtime.core.job_authority.secrets.token_hex", lambda _n: next(values))
    with registry._lock():
        minted = registry._mint_unique_initial_jae_locked([])
    assert minted == "JAE_" + "e" * 64


class FakeApprovedHDA:
    def __init__(self, *, dre: str, ade: str, approval_binding: R009OpaqueArtifactBinding):
        self.dre = dre
        self.ade = ade
        self.binding = approval_binding

    def load_exact_terminal_source(self, decision_request_event_id: str):
        assert decision_request_event_id == self.dre
        return {
            "terminal_decision_code": "APPROVED",
            "approval_decision_event_id": self.ade,
            "approval_decision_event_artifact_identity_sha256":
                self.binding.artifact_identity_sha256,
            "approval_decision_event_artifact_revision":
                self.binding.artifact_revision,
            "approval_decision_event_artifact_sha256":
                self.binding.artifact_sha256,
        }


def test_approved_slot_issuance_binds_exact_approval_source(tmp_path):
    state = make_active_predecessor(tmp_path)
    store = state["store"]
    registry = state["registry"]

    dre = "DRE_" + "b" * 64
    ade = "ADE_" + "c" * 64
    filler = "d" * 64
    approval = {
        "schema": "RUNTIME_APPROVAL_DECISION_EVENT_BINDING_V3",
        "approval_decision_event_id": ade,
        "job_authority_event_id": state["jae"],
        "job_execution_authority_snapshot_id": state["jxs"],
        "job_execution_authority_snapshot_sha256":
            state["snapshot_binding"].artifact_sha256,
        "job_execution_authority_snapshot_artifact_identity_sha256":
            state["snapshot_binding"].artifact_identity_sha256,
        "job_execution_authority_snapshot_artifact_revision":
            state["snapshot_binding"].artifact_revision,
        "job_execution_authority_snapshot_artifact_sha256":
            state["snapshot_binding"].artifact_sha256,
        "job_execution_snapshot_registration_sha256":
            state["reg_binding"].artifact_sha256,
        "decision_request_event_id": dre,
        "snapshot_decision_request_key_sha256": filler,
        "decision_request_identity_sha256": filler,
        "decision_request_content_sha256": filler,
        "decision_request_content_artifact_identity_sha256": filler,
        "decision_request_content_artifact_revision": 1,
        "decision_request_content_artifact_sha256": filler,
        "human_action_receipt_sha256": filler,
        "human_action_receipt_artifact_identity_sha256": filler,
        "human_action_receipt_artifact_revision": 1,
        "human_action_receipt_artifact_sha256": filler,
        "decision_scope_sha256": state["snapshot_binding"].artifact_sha256,
        "decision_code": "APPROVED",
        "live_attempts_max": 1,
        "model_calls_max": 1,
        "network_calls_max": 1,
        "retries_max": 0,
        "fallback_allowed": False,
    }
    approval_binding = persist(
        store,
        job_id=state["job_id"],
        label="approval-decision",
        obj=approval,
    )
    hda = FakeApprovedHDA(
        dre=dre,
        ade=ade,
        approval_binding=approval_binding,
    )
    issued = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2",
        transition_stage="APPROVED_SLOT_UNCLAIMED",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        approval_decision_event_binding=approval_binding,
        human_decision_authority=hda,
    )
    expected_slot = sha({
        "namespace": "RUNTIME_JOB_SCOPED_APPROVAL_CONSUMPTION_SLOT_V1",
        "job_authority_binding_sha256": state["snapshot"]["job_authority_binding_sha256"],
        "approval_decision_event_id": ade,
    })
    assert issued["predecessor_approval_slot_key_sha256"] == expected_slot
    assert issued["predecessor_approval_decision_event_id"] == ade
    assert issued["predecessor_approval_artifact_sha256"] == approval_binding.artifact_sha256


def test_controlled_successor_mint_skips_existing_initial_jae(tmp_path, monkeypatch):
    state = make_active_predecessor(tmp_path)
    registry = state["registry"]
    initial_source = {
        "job_authority_event_id": "JAE_" + "9" * 64,
    }
    values = iter(["9" * 64, "8" * 64])
    monkeypatch.setattr(
        "universal_runtime.core.job_authority.secrets.token_hex",
        lambda _n: next(values),
    )
    with registry._lock():
        minted = registry._mint_unique_controlled_successor_jae_locked(
            [initial_source],
            [],
        )
    assert minted == "JAE_" + "8" * 64


class TerminalPresentHDA:
    def __init__(self, delegate, dre: str):
        self.delegate = delegate
        self.dre = dre

    def load_exact_request_source(self, decision_request_event_id: str):
        return self.delegate.load_exact_request_source(decision_request_event_id)

    def load_exact_terminal_source(self, decision_request_event_id: str):
        assert decision_request_event_id == self.dre
        return {
            "decision_request_event_id": decision_request_event_id,
            "terminal_decision_code": "REJECTED",
        }


def test_dre_pending_requires_real_request_source_and_rejects_post_terminal(tmp_path):
    state = make_active_predecessor(tmp_path)
    dre = select_dre_branch(state, publish_request=False)
    registry = state["registry"]

    with pytest.raises(
        JobAuthorityError,
        match="exact HumanDecision request source is unavailable",
    ):
        registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
            predecessor_job_authority_event_id=state["jae"],
            transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
            transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
            transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
            human_decision_authority=state["hda"],
        )

    request_source = state["hda"].issue_or_replay_one_decision_request_for_selected_active_snapshot_v3(
        preapproval_branch_key_sha256=dre["branch_key"]
    )
    assert request_source["decision_request_event_id"] == dre["dre"]

    issued = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        human_decision_authority=state["hda"],
    )
    assert issued["predecessor_decision_request_event_id"] == dre["dre"]

    with pytest.raises(
        JobAuthorityError,
        match="terminal source already exists",
    ):
        registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
            predecessor_job_authority_event_id=state["jae"],
            transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
            transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
            transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
            human_decision_authority=TerminalPresentHDA(state["hda"], dre["dre"]),
        )


def test_initial_registration_rejects_successor_issuance_before_lineage_claim(tmp_path):
    state = make_active_predecessor(tmp_path)
    registry = state["registry"]
    store = state["store"]

    issuance = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="ACTIVE_PREDECESSOR_NO_DRE",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
    )
    successor_jae = issuance["successor_job_authority_event_id"]
    lineage = issuance["job_lineage_identity_sha256"]
    authority_binding = sha({
        "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
        "job_authority_event_id": successor_jae,
        "job_lineage_identity_sha256": lineage,
    })
    snapshot = {
        "schema": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1",
        "snapshot_revision": 1,
        "job_authority_event_id": successor_jae,
        "job_lineage_identity_sha256": lineage,
        "job_authority_binding_sha256": authority_binding,
    }
    snapshot_binding = persist(
        store,
        job_id=state["job_id"],
        label="successor-as-illegal-initial-snapshot",
        obj=snapshot,
    )
    jxs = "JXS_" + sha({
        "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
        "job_authority_event_id": successor_jae,
        "snapshot_content_sha256": snapshot_binding.artifact_sha256,
    })
    registration = {
        "schema": "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2",
        "registration_revision": 1,
        "job_authority_event_id": successor_jae,
        "job_authority_binding_sha256": authority_binding,
        "job_execution_authority_snapshot_id": jxs,
        "job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
        "job_execution_authority_snapshot_artifact_identity_sha256":
            snapshot_binding.artifact_identity_sha256,
        "job_execution_authority_snapshot_artifact_revision":
            snapshot_binding.artifact_revision,
        "job_execution_authority_snapshot_artifact_sha256":
            snapshot_binding.artifact_sha256,
        "activation_basis": "INITIAL_JOB_CREATION",
        "predecessor_approval_slot_key_sha256": None,
        "predecessor_invalidation_sha256": None,
        "job_transition_intent_sha256": None,
        "state": "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT",
    }
    reg_binding = persist(
        store,
        job_id=state["job_id"],
        label="illegal-successor-initial-registration",
        obj=registration,
    )
    with pytest.raises(
        JobAuthorityError,
        match="SUCCESSOR_INITIAL_REGISTRATION_BYPASS_DENIED",
    ):
        registry.register_or_replay_one_active_snapshot_for_jae_v1(
            registration_binding=reg_binding
        )


def test_web_pre_dre_delegation_suppresses_hda_but_dre_pending_delegates_it():
    class FakeRegistry:
        def __init__(self):
            self.calls = []

        def issue_or_replay_one_controlled_successor_job_authority_event_v1(self, **kwargs):
            self.calls.append(kwargs)
            return kwargs

    fake_registry = FakeRegistry()
    sentinel_hda = object()

    class FakeService:
        job_authority = fake_registry
        human_decision = sentinel_hda

    GeneralChatFormalPrepareService.issue_or_replay_controlled_successor_job_authority_event_v1(
        FakeService(),
        predecessor_job_authority_event_id="JAE_" + "1" * 64,
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="ACTIVE_PREDECESSOR_NO_DRE",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
    )
    assert fake_registry.calls[-1]["human_decision_authority"] is None

    GeneralChatFormalPrepareService.issue_or_replay_controlled_successor_job_authority_event_v1(
        FakeService(),
        predecessor_job_authority_event_id="JAE_" + "1" * 64,
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
    )
    assert fake_registry.calls[-1]["human_decision_authority"] is sentinel_hda


def test_historical_v1_successor_claim_is_loadable_but_read_only_for_activation(tmp_path):
    state = make_active_predecessor(tmp_path)
    dre = select_dre_branch(state)
    registry = state["registry"]

    issuance = registry.issue_or_replay_one_controlled_successor_job_authority_event_v1(
        predecessor_job_authority_event_id=state["jae"],
        transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
        transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
        transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
        human_decision_authority=state["hda"],
    )
    _snapshot, successor_binding, _intent, intent_binding = build_successor_snapshot_and_intent(
        state, issuance, dre
    )
    claim_v2 = registry.claim_or_replay_one_transition_bound_successor_lineage_v1(
        transition_intent_binding=intent_binding,
        successor_snapshot_binding=successor_binding,
    )
    claim_v1 = dict(claim_v2)
    claim_v1["schema"] = "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V1"
    claim_v1.pop("controlled_successor_jae_issuance_key_sha256")
    claim_v1.pop("controlled_successor_jae_issuance_source_record_sha256")
    claim_path = registry._claim_path(issuance["successor_job_authority_event_id"])
    claim_path.write_bytes(canonical(claim_v1))

    loaded = registry.load_exact_successor_lineage_claim_v1(
        issuance["successor_job_authority_event_id"]
    )
    assert loaded["schema"] == "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V1"

    with pytest.raises(
        JobAuthorityError,
        match="LEGACY_SUCCESSOR_LINEAGE_CLAIM_V1_READ_ONLY_NOT_ACTIVATABLE",
    ):
        registry._validate_controlled_claim({
            "job_authority_event_id": issuance["successor_job_authority_event_id"]
        })
