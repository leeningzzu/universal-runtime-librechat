from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from universal_runtime.devtools.action_delivery_gate import (
    ActionDeliveryGateError,
    ActionDeliveryGateSpec,
    ExactFileBinding,
    _derive_result_state,
    _final_boundary_currentness_lines,
    _write_once_exact_json,
    evaluate_gate,
    requires_pre_delivery_gate,
    _runtime_trust_context_for_tests,
    sha256_bytes,
    validate_ps51_source_text,
)


def _json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": _sha(path)}


def _fixture(
    tmp_path: Path,
    *,
    kind: str = "EXECUTE",
    compile_result: str = "PASS",
    receipt_phase: str = "COMPILE",
    user_action_required: bool | None = None,
    result_state: str = "ABSENT",
    rollback_expected: list[Path] | None = None,
    gate_id: str = "GATE-R002",
    boundary_mutator=None,
    authority_root_override: Path | None = None,
):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    authority_root = authority_root_override or (tmp_path / "runtime-authority")
    for path in (inputs, outputs, authority_root):
        path.mkdir(parents=True, exist_ok=True)
    reports = outputs / "reports"
    trust = _runtime_trust_context_for_tests(authority_root)

    if user_action_required is None:
        user_action_required = kind in {"EXECUTE", "RECOVERY"}

    entrypoint = _text(
        inputs / "stable-entry.ps1",
        "param([string]$ActionSpecPath,[string]$ExpectedActionSpecSha256)\nWrite-Output 'safe'\n",
    )
    action_spec = _json(inputs / "action-spec.json", {"task_id": "TASK-R002"})
    context = _json(inputs / "context.json", {"context_id": "CTX-R002", "schema_revision": "R002"})

    final_result = outputs / "result.zip"
    partial_result = outputs / "result.zip.partial"
    inprogress = outputs / "result.inprogress"
    if result_state == "COMPLETE_VALID":
        final_result.write_bytes(b"VALID-RESULT")
        expected_complete_sha = _sha(final_result)
    elif result_state == "COMPLETE_UNVERIFIED":
        final_result.write_bytes(b"UNVERIFIED")
        expected_complete_sha = None
    elif result_state == "STALE_CONFLICT":
        final_result.write_bytes(b"STALE")
        expected_complete_sha = "1" * 64
    elif result_state == "IN_PROGRESS":
        inprogress.mkdir()
        expected_complete_sha = None
    elif result_state == "INCOMPLETE_RECOVERABLE":
        partial_result.write_bytes(b"PARTIAL")
        expected_complete_sha = None
    else:
        expected_complete_sha = None

    publication_plan = {
        "final_result_path": str(final_result.resolve()),
        "partial_result_path": str(partial_result.resolve()),
        "inprogress_path": str(inprogress.resolve()),
        "expected_complete_sha256": expected_complete_sha,
    }

    rollback_expected = rollback_expected or []
    rollback_plan = {
        "owned_output_roots": [str(outputs.resolve())] if rollback_expected else [],
        "expected_absent_paths": [str(x.resolve()) for x in rollback_expected],
        "implementation": _binding(entrypoint) if rollback_expected else None,
    }

    transport = {"entrypoint": _binding(entrypoint), "action_spec": _binding(action_spec)}
    interaction_text = "Run the one exact action and upload one exact Result ZIP." if user_action_required else "NONE"
    rendered_action = "**下一步**\n" + interaction_text if user_action_required else "NONE"
    interaction_plan = {
        "user_action_required": user_action_required,
        "user_operation_count": 1 if user_action_required else 0,
        "user_next_action_sha256": sha256_bytes(interaction_text.encode("utf-8")),
        "rendered_action_sha256": sha256_bytes(rendered_action.encode("utf-8")),
        "return_target": "EXACT_RESULT_ZIP" if user_action_required else "NONE",
        "file_hunt_required": False,
        "multiline_paste_required": False,
    }

    action = {
        "receipt_phase": receipt_phase,
        "task_id": "TASK-R002",
        "action_id": "ACTION-R002",
        "action_revision": "R002",
        "action_kind": kind,
        "compile_result": compile_result,
        "execution_identity": {"execution_id": "EXEC-R002"},
        "user_action_required": user_action_required,
        "transport": transport,
        "rollback_plan": rollback_plan,
        "failure_evidence": [] if compile_result != "STOP" else ["FIXTURE_STOP"],
    }
    action_path = _json(inputs / "action-receipt.json", action)

    state, state_lines, state_sha = _derive_result_state(publication_plan, outputs)
    state_receipt = {
        "schema_revision": "R002",
        "receipt_id": "STATE-R002",
        "producer_id": "UR_RESULT_STATE_RECONCILER_R002",
        "producer_contract_revision": "R002",
        "action_id": "ACTION-R002",
        "action_revision": "R002",
        "execution_id": "EXEC-R002",
        "state": state,
        "classification_result": "PASS",
        "decision": {
            "ABSENT": "EXECUTE",
            "IN_PROGRESS": "RECOVERY",
            "COMPLETE_UNVERIFIED": "STOP",
            "COMPLETE_VALID": "NO_OP",
            "INCOMPLETE_RECOVERABLE": "RECOVERY",
            "STALE_CONFLICT": "STOP",
        }[state],
        "proof_class": "VALIDATED",
        "currentness_ref": "STATE-CURRENTNESS-R002",
        "currentness_lines": state_lines,
        "currentness_sha256": state_sha,
    }
    state_path = _json(inputs / "state.json", state_receipt)

    interaction = {
        "schema_revision": "R002",
        "receipt_id": "INTERACTION-R002",
        "producer_id": "UR_INTERACTION_COMPILER_R002",
        "producer_contract_revision": "R002",
        "action_id": "ACTION-R002",
        "action_revision": "R002",
        "execution_id": "EXEC-R002",
        "validation_result": "PASS",
        "proof_class": "VALIDATED",
        "user_action_required": user_action_required,
        "user_operation_count": 1 if user_action_required else 0,
        "user_next_action": interaction_text,
        "rendered_action": rendered_action,
        "file_hunt_required": False,
        "multiline_paste_required": False,
        "return_target": "EXACT_RESULT_ZIP" if user_action_required else "NONE",
    }
    interaction_path = _json(inputs / "interaction.json", interaction)

    final_boundary_path = None
    if kind in {"EXECUTE", "RECOVERY"}:
        final_boundary_path = inputs / "final-boundary.json"
        child = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        planned = [
            child,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(entrypoint.resolve()),
            "-ActionSpecPath",
            str(action_spec.resolve()),
            "-ExpectedActionSpecSha256",
            _sha(action_spec),
        ]
        probe = [
            child,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(trust.trusted_ps51_probe.path),
            "-ActionId",
            "ACTION-R002",
            "-ActionRevision",
            "R002",
            "-ExecutionId",
            "EXEC-R002",
            "-TargetScriptPath",
            str(entrypoint.resolve()),
            "-ExpectedTargetScriptSha256",
            _sha(entrypoint),
            "-ActionSpecPath",
            str(action_spec.resolve()),
            "-ExpectedActionSpecSha256",
            _sha(action_spec),
            "-OutputPath",
            str(final_boundary_path.resolve()),
        ]
        host = {
            "proof_class": "OBSERVED",
            "powershell_edition": "Desktop",
            "powershell_major": 5,
            "effective_execution_policy": "Bypass",
            "language_mode": "FullLanguage",
        }
        lines = _final_boundary_currentness_lines(
            action_id="ACTION-R002",
            action_revision="R002",
            execution_id="EXEC-R002",
            host=host,
            entrypoint=type("B", (), {"path": entrypoint.resolve(), "sha256": _sha(entrypoint)})(),
            action_spec=type("B", (), {"path": action_spec.resolve(), "sha256": _sha(action_spec)})(),
            planned_argv=planned,
            probe_contract_argv=probe,
        )
        boundary = {
            "schema_revision": "R002",
            "receipt_id": "BOUNDARY-R002",
            "producer_id": "UR_PS51_FINAL_BOUNDARY_PROBE_R002",
            "producer_contract_revision": "R002",
            "action_id": "ACTION-R002",
            "action_revision": "R002",
            "execution_id": "EXEC-R002",
            "transport_family": "WINDOWS_POWERSHELL_5_1",
            "profile_id": "PS51_SAFE_EXECUTION_PROFILE_R001",
            "validation_result": "PASS",
            "proof_class": "VALIDATED",
            "parser_result": "PASS",
            "ast_safe_subset_result": "PASS",
            "runtime_semantic_fixture_result": "PASS",
            "cardinality": {"zero": "PASS", "one_pscustomobject": "PASS", "many": "PASS"},
            "strict_mode": {"missing_property_expected_failure": "PASS", "member_count_ast_absent": True},
            "host_observation": host,
            "probe_invocation_contract": {"proof_class": "VALIDATED", "argv": probe},
            "planned_action": {"proof_class": "DECLARED", "argv": planned},
            "entrypoint": _binding(entrypoint),
            "action_spec": _binding(action_spec),
            "prohibited_primary_transport": {
                "browser_download_discovery": False,
                "file_picker": False,
                "complex_python_c": False,
                "session_history": False,
                "nested_child_command": False,
                "long_multiline_paste": False,
            },
            "currentness_ref": "PS51-CURRENTNESS-R002",
            "currentness_lines": lines,
            "currentness_sha256": sha256_bytes(("\n".join(lines) + "\n").encode("utf-8")),
        }
        if boundary_mutator:
            boundary_mutator(boundary)
        _json(final_boundary_path, boundary)

    rollback_path = None
    if receipt_phase == "RESULT":
        remaining = [str(x.resolve()) for x in rollback_expected if x.exists()]
        rollback = {
            "schema_revision": "R002",
            "receipt_id": "ROLLBACK-R002",
            "producer_id": "UR_ROLLBACK_READBACK_VALIDATOR_R002",
            "producer_contract_revision": "R002",
            "action_id": "ACTION-R002",
            "action_revision": "R002",
            "execution_id": "EXEC-R002",
            "rollback_state": "READBACK_VALIDATED_COMPLETE" if rollback_expected else "NOT_REQUIRED",
            "attempted": bool(rollback_expected),
            "readback_performed": bool(rollback_expected),
            "owned_output_roots": rollback_plan["owned_output_roots"],
            "expected_absent_paths": rollback_plan["expected_absent_paths"],
            "actual_remaining_paths": remaining,
            "implementation": rollback_plan["implementation"],
            "validation_result": "PASS",
            "proof_class": "VALIDATED",
        }
        rollback_path = _json(inputs / "rollback.json", rollback)

    receipt_bindings = {
        "action_compile_receipt": _sha(action_path),
        "validator_context": _sha(context),
        "state_receipt": _sha(state_path),
        "interaction_receipt": _sha(interaction_path),
        "final_boundary_receipt": _sha(final_boundary_path) if final_boundary_path else None,
        "rollback_receipt": _sha(rollback_path) if rollback_path else None,
    }
    authority = {
        "schema_revision": "R002",
        "binding_id": "AUTH-R002",
        "issuer_id": "UNIVERSAL_RUNTIME_JOB_AUTHORITY",
        "policy_id": "UR_ACTION_DELIVERY_TRUST_POLICY_R002",
        "task_id": "TASK-R002",
        "action_id": "ACTION-R002",
        "action_revision": "R002",
        "execution_id": "EXEC-R002",
        "validator_context_id": "CTX-R002",
        "validator_context_revision": "R002",
        "receipt_bindings": receipt_bindings,
        "transport": transport,
        "interaction_plan": interaction_plan,
        "publication_plan": publication_plan,
        "rollback_plan": rollback_plan,
        "stop_loss": {"current_active": False, "same_gate_failure_count": 0},
    }
    authority_path = _json(authority_root / "authority.json", authority)

    spec_data = {
        "schema_revision": "R002",
        "gate_id": gate_id,
        "task_id": "TASK-R002",
        "receipt_phase": receipt_phase,
        "allowed_input_roots": [str(inputs.resolve())],
        "allowed_output_root": str(outputs.resolve()),
        "report_root": str(reports.resolve()),
        "timeout_seconds": 30,
        "output_budget": 20000,
        "action_compile": {
            "receipt": _binding(action_path),
            "validator_context": _binding(context),
            "authority_binding": _binding(authority_path),
        },
        "state_receipt": _binding(state_path),
        "interaction_receipt": _binding(interaction_path),
        "final_boundary_receipt": _binding(final_boundary_path) if final_boundary_path else None,
        "rollback_receipt": _binding(rollback_path) if rollback_path else None,
    }
    spec_path = _json(tmp_path / "gate-spec.json", spec_data)
    loaded = ActionDeliveryGateSpec.from_path(
        spec_path,
        _sha(spec_path),
        _runtime_context=trust,
    )
    return {
        "spec_path": spec_path,
        "spec": loaded,
        "trust": trust,
        "inputs": inputs,
        "outputs": outputs,
        "authority_root": authority_root,
        "authority_path": authority_path,
        "action_path": action_path,
        "context_path": context,
        "state_path": state_path,
        "interaction_path": interaction_path,
        "final_boundary_path": final_boundary_path,
        "rollback_path": rollback_path,
        "entrypoint": entrypoint,
        "action_spec": action_spec,
        "final_result": final_result,
        "partial_result": partial_result,
        "inprogress": inprogress,
    }


def test_execute_pass_uses_runtime_owned_validator_and_authority(tmp_path):
    fx = _fixture(tmp_path)
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "PASS"
    assert result["execution_allowed"] is True
    assert result["trusted_validator_id"] == "UR_TRUSTED_ACTION_COMPILE_VALIDATOR_R002"
    assert result["contract_errors"] == []


def test_spec_cannot_select_arbitrary_validator(tmp_path):
    fx = _fixture(tmp_path)
    data = json.loads(fx["spec_path"].read_text())
    arbitrary = _text(fx["inputs"] / "print-pass.py", "print('PASS')\n")
    data["action_compile"]["validator"] = _binding(arbitrary)
    fx["spec_path"].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ActionDeliveryGateError, match="fields mismatch"):
        ActionDeliveryGateSpec.from_path(
            fx["spec_path"], _sha(fx["spec_path"]), _runtime_context=fx["trust"]
        )


def test_authority_binding_must_be_under_runtime_owned_root(tmp_path):
    fx = _fixture(tmp_path)
    data = json.loads(fx["spec_path"].read_text())
    foreign = _json(fx["inputs"] / "authority.json", json.loads(fx["authority_path"].read_text()))
    data["action_compile"]["authority_binding"] = _binding(foreign)
    fx["spec_path"].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ActionDeliveryGateError, match="outside trusted/allowed roots"):
        ActionDeliveryGateSpec.from_path(
            fx["spec_path"], _sha(fx["spec_path"]), _runtime_context=fx["trust"]
        )


@pytest.mark.parametrize(
    "key",
    [
        "action_path",
        "context_path",
        "state_path",
        "interaction_path",
        "final_boundary_path",
        "authority_path",
        "entrypoint",
        "action_spec",
    ],
)
def test_every_consumed_binding_rejects_post_binding_mutation(tmp_path, key):
    fx = _fixture(tmp_path)
    path = fx[key]
    assert path is not None
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ActionDeliveryGateError, match="POST_BINDING_MUTATION_REJECTED"):
        evaluate_gate(fx["spec"])


def test_trusted_validator_snapshot_rejects_post_binding_mutation(tmp_path):
    fx = _fixture(tmp_path)
    original = fx["spec"].runtime_trust.trusted_validator
    copy = tmp_path / "trusted-validator-copy.py"
    copy.write_bytes(original.snapshot)
    binding = ExactFileBinding(copy, len(original.snapshot), original.sha256, original.snapshot)
    trust = replace(fx["spec"].runtime_trust, trusted_validator=binding)
    spec = replace(fx["spec"], runtime_trust=trust)
    copy.write_bytes(copy.read_bytes() + b"\n")
    with pytest.raises(ActionDeliveryGateError, match="POST_BINDING_MUTATION_REJECTED"):
        evaluate_gate(spec)


def test_trusted_probe_and_contract_reject_post_binding_mutation(tmp_path):
    fx = _fixture(tmp_path)
    for field in ("trusted_ps51_probe", "trusted_ps51_contract"):
        original = getattr(fx["spec"].runtime_trust, field)
        copy = tmp_path / f"{field}.copy"
        copy.write_bytes(original.snapshot)
        binding = ExactFileBinding(copy, len(original.snapshot), original.sha256, original.snapshot)
        trust = replace(fx["spec"].runtime_trust, **{field: binding})
        spec = replace(fx["spec"], runtime_trust=trust)
        copy.write_bytes(copy.read_bytes() + b"\n")
        with pytest.raises(ActionDeliveryGateError, match="POST_BINDING_MUTATION_REJECTED"):
            evaluate_gate(spec)



def test_arbitrary_noncanonical_final_boundary_producer_is_rejected(tmp_path):
    def mutate(boundary):
        boundary["producer_id"] = "ARBITRARY_PRINT_PASS_PRODUCER"

    fx = _fixture(tmp_path, boundary_mutator=mutate)
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "STOP"
    assert "FINAL_BOUNDARY_UNTRUSTED_PRODUCER" in result["contract_errors"]


def test_planned_action_argv_must_bind_action_spec_path_and_sha(tmp_path):
    def mutate(boundary):
        boundary["planned_action"]["argv"] = boundary["planned_action"]["argv"][:7]

    fx = _fixture(tmp_path, boundary_mutator=mutate)
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "STOP"
    assert "PLANNED_ACTION_ARGV_NOT_COMPLETE_OR_EXACT" in result["contract_errors"]


def test_final_boundary_currentness_is_recomputed(tmp_path):
    def mutate(boundary):
        boundary["currentness_sha256"] = "0" * 64

    fx = _fixture(tmp_path, boundary_mutator=mutate)
    result = evaluate_gate(fx["spec"])
    assert "FINAL_BOUNDARY_CURRENTNESS_SHA_MISMATCH" in result["contract_errors"]


@pytest.mark.parametrize(
    "source",
    [
        "$items.Count\n",
        "$obj.Children.Count\n",
        "($items | Where-Object { $_ })\n.Count\n",
        "$array[0].Count\n",
    ],
)
def test_ps51_member_count_shapes_are_rejected(source):
    assert "PS51_MEMBER_COUNT_REJECTED" in validate_ps51_source_text(source)


@pytest.mark.parametrize(
    "source",
    [
        "# $items.Count\nWrite-Output 'ok'\n",
        "Write-Output '$items.Count'\n",
        "@'\n$obj.Children.Count\n'@\nWrite-Output 'ok'\n",
        '@"\n($items).Count\n"@\nWrite-Output "ok"\n',
    ],
)
def test_ps51_comments_strings_and_here_strings_do_not_false_block(source):
    assert validate_ps51_source_text(source) == []


@pytest.mark.parametrize("gate_id", ["../escape", r"C:\absolute", "A/B", "..", "lowercase"])
def test_gate_id_path_traversal_or_unsafe_identifier_is_rejected(tmp_path, gate_id):
    fx = _fixture(tmp_path)
    data = json.loads(fx["spec_path"].read_text())
    data["gate_id"] = gate_id
    fx["spec_path"].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ActionDeliveryGateError, match="filename-safe"):
        ActionDeliveryGateSpec.from_path(
            fx["spec_path"], _sha(fx["spec_path"]), _runtime_context=fx["trust"]
        )


def test_atomic_create_if_absent_never_overwrites_conflicting_writer(tmp_path):
    path = tmp_path / "report.json"
    outcomes: list[str] = []
    failures: list[str] = []

    def writer(value):
        try:
            _, status = _write_once_exact_json(path, value)
            outcomes.append(status)
        except ActionDeliveryGateError as exc:
            failures.append(str(exc))

    a = threading.Thread(target=writer, args=({"value": "A"},))
    b = threading.Thread(target=writer, args=({"value": "B"},))
    a.start(); b.start(); a.join(); b.join()
    assert path.is_file()
    assert len(outcomes) == 1
    assert len(failures) == 1
    assert "STALE_CONFLICT" in failures[0]


def test_valid_existing_result_is_no_op(tmp_path):
    fx = _fixture(
        tmp_path,
        kind="NO_OP",
        compile_result="NO_OP",
        user_action_required=False,
        result_state="COMPLETE_VALID",
    )
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "NO_OP"
    assert result["state_decision"] == "NO_OP"
    assert result["user_next_action"] == "NONE"


@pytest.mark.parametrize("state", ["IN_PROGRESS", "INCOMPLETE_RECOVERABLE"])
def test_partial_state_blocks_execute_and_routes_recovery(tmp_path, state):
    fx = _fixture(tmp_path, result_state=state)
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "STOP"
    assert result["state_decision"] == "RECOVERY"
    assert "EXECUTE_ACTION_CONFLICTS_WITH_STATE_DECISION" in result["contract_errors"]


def test_recovery_action_matches_partial_state(tmp_path):
    fx = _fixture(tmp_path, kind="RECOVERY", result_state="INCOMPLETE_RECOVERABLE")
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "PASS"
    assert result["state_decision"] == "RECOVERY"


def test_rollback_readback_is_bound_to_exact_action_owned_plan(tmp_path):
    absent = tmp_path / "outputs" / "owned-transient"
    fx = _fixture(tmp_path, receipt_phase="RESULT", rollback_expected=[absent])
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "PASS"
    assert result["rollback_errors"] == []


def test_rollback_remaining_path_rejects_completion(tmp_path):
    remaining = tmp_path / "outputs" / "owned-transient"
    remaining.parent.mkdir(parents=True, exist_ok=True)
    remaining.write_text("still here", encoding="utf-8")
    fx = _fixture(tmp_path, receipt_phase="RESULT", rollback_expected=[remaining])
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "STOP"
    assert "ROLLBACK_COMPLETE_REQUIRES_ZERO_REMAINING_PATHS" in result["rollback_errors"]


def test_rollback_path_outside_owned_output_root_is_rejected(tmp_path):
    outside = tmp_path / "outside" / "transient"
    fx = _fixture(tmp_path, receipt_phase="RESULT", rollback_expected=[outside])
    result = evaluate_gate(fx["spec"])
    assert result["gate_result"] == "STOP"
    assert "ROLLBACK_PATH_OUTSIDE_ACTION_OWNED_OUTPUT_ROOT" in result["rollback_errors"]



@pytest.mark.parametrize("implementation_shape", ["null", "missing"])
def test_required_rollback_plan_requires_exact_implementation_binding(tmp_path, implementation_shape):
    absent = tmp_path / "outputs" / "owned-transient"
    fx = _fixture(tmp_path, receipt_phase="RESULT", rollback_expected=[absent])

    action = json.loads((fx["inputs"] / "action-receipt.json").read_text())
    authority = json.loads(fx["authority_path"].read_text())
    rollback = json.loads(fx["rollback_path"].read_text())

    if implementation_shape == "null":
        action["rollback_plan"]["implementation"] = None
        authority["rollback_plan"]["implementation"] = None
    else:
        action["rollback_plan"].pop("implementation", None)
        authority["rollback_plan"].pop("implementation", None)
    rollback["implementation"] = None

    action_path = fx["inputs"] / "action-receipt.json"
    action_path.write_text(json.dumps(action, sort_keys=True), encoding="utf-8")
    fx["rollback_path"].write_text(json.dumps(rollback, sort_keys=True), encoding="utf-8")

    authority["receipt_bindings"]["action_compile_receipt"] = _sha(action_path)
    authority["receipt_bindings"]["rollback_receipt"] = _sha(fx["rollback_path"])
    fx["authority_path"].write_text(json.dumps(authority, sort_keys=True), encoding="utf-8")

    spec_data = json.loads(fx["spec_path"].read_text())
    spec_data["action_compile"]["receipt"] = _binding(action_path)
    spec_data["action_compile"]["authority_binding"] = _binding(fx["authority_path"])
    spec_data["rollback_receipt"] = _binding(fx["rollback_path"])
    fx["spec_path"].write_text(json.dumps(spec_data), encoding="utf-8")

    with pytest.raises(
        ActionDeliveryGateError,
        match="ROLLBACK_REQUIRED_PLAN_REQUIRES_IMPLEMENTATION_BINDING",
    ):
        ActionDeliveryGateSpec.from_path(
            fx["spec_path"], _sha(fx["spec_path"]), _runtime_context=fx["trust"]
        )

def test_untrusted_rollback_producer_is_rejected(tmp_path):
    absent = tmp_path / "outputs" / "owned-transient"
    fx = _fixture(tmp_path, receipt_phase="RESULT", rollback_expected=[absent])
    data = json.loads(fx["rollback_path"].read_text())
    data["producer_id"] = "SELF_AUTHORED"
    # Rebind the changed receipt through a new Runtime authority revision, proving that
    # producer trust is independently enforced and not satisfied by exact SHA alone.
    fx["rollback_path"].write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    authority = json.loads(fx["authority_path"].read_text())
    authority["receipt_bindings"]["rollback_receipt"] = _sha(fx["rollback_path"])
    fx["authority_path"].write_text(json.dumps(authority, sort_keys=True), encoding="utf-8")
    spec_data = json.loads(fx["spec_path"].read_text())
    spec_data["action_compile"]["authority_binding"] = _binding(fx["authority_path"])
    spec_data["rollback_receipt"] = _binding(fx["rollback_path"])
    fx["spec_path"].write_text(json.dumps(spec_data), encoding="utf-8")
    loaded = ActionDeliveryGateSpec.from_path(
        fx["spec_path"], _sha(fx["spec_path"]), _runtime_context=fx["trust"]
    )
    result = evaluate_gate(loaded)
    assert "ROLLBACK_UNTRUSTED_PRODUCER" in result["rollback_errors"]


def test_ordinary_non_executable_no_user_action_does_not_require_gate():
    assert requires_pre_delivery_gate(action_kind="BOUNDED_REVIEW", user_action_required=False) is False
    assert requires_pre_delivery_gate(action_kind="EXECUTE", user_action_required=False) is True
    assert requires_pre_delivery_gate(action_kind="NO_OP", user_action_required=False) is False


def test_trust_policy_and_canonical_probe_are_exact_bound(tmp_path):
    authority = tmp_path / "authority"
    authority.mkdir()
    trust = _runtime_trust_context_for_tests(authority)
    assert trust.policy["policy_id"] == "UR_ACTION_DELIVERY_TRUST_POLICY_R002"
    assert trust.trusted_validator.sha256 == trust.policy["trusted_action_compile_validator"]["sha256"]
    assert trust.trusted_ps51_probe.sha256 == trust.policy["trusted_ps51_probe"]["sha256"]


def test_action_compile_receipt_transport_must_equal_runtime_authority(tmp_path):
    fx = _fixture(tmp_path)
    action = json.loads((fx["inputs"] / "action-receipt.json").read_text())
    action["transport"]["action_spec"]["sha256"] = "f" * 64
    (fx["inputs"] / "action-receipt.json").write_text(json.dumps(action), encoding="utf-8")
    # Update only spec binding; Runtime authority remains unchanged.
    spec_data = json.loads(fx["spec_path"].read_text())
    spec_data["action_compile"]["receipt"] = _binding(fx["inputs"] / "action-receipt.json")
    fx["spec_path"].write_text(json.dumps(spec_data), encoding="utf-8")
    with pytest.raises(ActionDeliveryGateError, match="receipt bindings do not match Runtime authority"):
        ActionDeliveryGateSpec.from_path(
            fx["spec_path"], _sha(fx["spec_path"]), _runtime_context=fx["trust"]
        )
