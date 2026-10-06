from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_REVISION = "R002"
TRUST_POLICY_SHA256 = "485665076cd60c963be5e55b13c55ddd4f6ffe9c78336980d1a1cd4654eb93e4"
GATE_RESULT_PASS = "PASS"
GATE_RESULT_STOP = "STOP"
GATE_RESULT_NO_OP = "NO_OP"

_EXECUTABLE_ACTION_KINDS = {"EXECUTE", "RECOVERY"}
_NON_EXECUTABLE_ACTION_KINDS = {"COMPILE_ONLY", "BOUNDED_REVIEW", "PRIOR_ART", "NO_OP"}
_ALLOWED_ACTION_KINDS = _EXECUTABLE_ACTION_KINDS | _NON_EXECUTABLE_ACTION_KINDS
_ALLOWED_PROOF_CLASSES = {"DECLARED", "ATTEMPTED", "OBSERVED", "VALIDATED", "COMMITTED"}
_PROOF_ORDER = {"DECLARED": 1, "ATTEMPTED": 2, "OBSERVED": 3, "VALIDATED": 4, "COMMITTED": 5}
_RESULT_STATES = {
    "ABSENT",
    "IN_PROGRESS",
    "COMPLETE_UNVERIFIED",
    "COMPLETE_VALID",
    "INCOMPLETE_RECOVERABLE",
    "STALE_CONFLICT",
    "QUARANTINED",
}
_STATE_DECISIONS = {
    "ABSENT": "EXECUTE",
    "IN_PROGRESS": "RECOVERY",
    "COMPLETE_UNVERIFIED": "STOP",
    "COMPLETE_VALID": "NO_OP",
    "INCOMPLETE_RECOVERABLE": "RECOVERY",
    "STALE_CONFLICT": "STOP",
    "QUARANTINED": "STOP",
}
_ALLOWED_SPEC_FIELDS = {
    "schema_revision",
    "gate_id",
    "task_id",
    "receipt_phase",
    "allowed_input_roots",
    "allowed_output_root",
    "report_root",
    "timeout_seconds",
    "output_budget",
    "action_compile",
    "state_receipt",
    "interaction_receipt",
    "final_boundary_receipt",
    "rollback_receipt",
}
_BINDING_FIELDS = {"path", "bytes", "sha256"}
_ACTION_COMPILE_FIELDS = {"receipt", "validator_context", "authority_binding"}
_AUTHORITY_FIELDS = {
    "schema_revision",
    "binding_id",
    "issuer_id",
    "policy_id",
    "task_id",
    "action_id",
    "action_revision",
    "execution_id",
    "validator_context_id",
    "validator_context_revision",
    "receipt_bindings",
    "transport",
    "interaction_plan",
    "publication_plan",
    "rollback_plan",
    "stop_loss",
}


class ActionDeliveryGateError(ValueError):
    """Raised when a user-visible action is not legally deliverable."""


@dataclass(frozen=True)
class ExactFileBinding:
    path: Path
    bytes: int
    sha256: str
    snapshot: bytes


@dataclass(frozen=True)
class RuntimeTrustContext:
    candidate_root: Path
    authority_root: Path
    policy: Mapping[str, Any]
    policy_binding: ExactFileBinding
    trusted_validator: ExactFileBinding
    trusted_ps51_probe: ExactFileBinding
    trusted_ps51_contract: ExactFileBinding


@dataclass(frozen=True)
class ActionDeliveryGateSpec:
    source_path: Path
    source_sha256: str
    source_snapshot: bytes
    gate_id: str
    task_id: str
    receipt_phase: str
    allowed_input_roots: tuple[Path, ...]
    allowed_output_root: Path
    report_root: Path
    timeout_seconds: float
    output_budget: int
    runtime_trust: RuntimeTrustContext
    action_compile_receipt: ExactFileBinding
    validator_context: ExactFileBinding
    authority_binding: ExactFileBinding
    state_receipt: ExactFileBinding
    interaction_receipt: ExactFileBinding
    final_boundary_receipt: ExactFileBinding | None
    rollback_receipt: ExactFileBinding | None
    entrypoint: ExactFileBinding | None
    action_spec: ExactFileBinding | None
    rollback_implementation: ExactFileBinding | None

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        expected_sha256: str,
        *,
        _runtime_context: RuntimeTrustContext | None = None,
    ) -> "ActionDeliveryGateSpec":
        trust = _runtime_context or load_runtime_trust_context()
        _assert_binding_current(trust.policy_binding, "TRUST_POLICY")
        _assert_binding_current(trust.trusted_validator, "TRUSTED_VALIDATOR")
        _assert_binding_current(trust.trusted_ps51_probe, "TRUSTED_PS51_PROBE")
        _assert_binding_current(trust.trusted_ps51_contract, "TRUSTED_PS51_CONTRACT")

        source = Path(path).resolve()
        source_snapshot = source.read_bytes()
        actual_sha = sha256_bytes(source_snapshot)
        if actual_sha != expected_sha256:
            raise ActionDeliveryGateError(
                f"stale gate spec SHA: expected={expected_sha256} actual={actual_sha}"
            )
        raw = _json_object(source_snapshot, "gate spec")
        _require_exact_fields(raw, _ALLOWED_SPEC_FIELDS, "gate spec")
        if raw["schema_revision"] != SCHEMA_REVISION:
            raise ActionDeliveryGateError("unsupported gate schema_revision")

        gate_id = _nonempty(raw["gate_id"], "gate_id")
        pattern = str(trust.policy["report_gate_id_pattern"])
        if re.fullmatch(pattern, gate_id) is None:
            raise ActionDeliveryGateError("gate_id is not a filename-safe identifier")
        task_id = _nonempty(raw["task_id"], "task_id")
        receipt_phase = str(raw["receipt_phase"])
        if receipt_phase not in {"COMPILE", "RESULT"}:
            raise ActionDeliveryGateError("receipt_phase must be COMPILE or RESULT")

        roots_raw = raw["allowed_input_roots"]
        if not isinstance(roots_raw, list) or not roots_raw:
            raise ActionDeliveryGateError("allowed_input_roots must be a non-empty array")
        input_roots = tuple(Path(str(x)).resolve() for x in roots_raw)
        if any(not x.is_dir() for x in input_roots):
            raise ActionDeliveryGateError("every allowed_input_root must exist")
        output_root = Path(str(raw["allowed_output_root"])).resolve()
        if not output_root.is_dir():
            raise ActionDeliveryGateError("allowed_output_root must exist")
        report_root = Path(str(raw["report_root"])).resolve()
        if not _within(report_root, output_root):
            raise ActionDeliveryGateError("report_root must be inside allowed_output_root")
        if any(_paths_overlap(output_root, root) for root in input_roots):
            raise ActionDeliveryGateError("allowed_output_root must be disjoint from allowed_input_roots")
        if _paths_overlap(output_root, trust.authority_root):
            raise ActionDeliveryGateError("allowed_output_root must be disjoint from trusted authority root")
        timeout_seconds = float(raw["timeout_seconds"])
        output_budget = int(raw["output_budget"])
        if timeout_seconds <= 0 or output_budget < 1:
            raise ActionDeliveryGateError("timeout_seconds/output_budget must be positive")

        action_compile = raw["action_compile"]
        if not isinstance(action_compile, dict):
            raise ActionDeliveryGateError("action_compile must be an object")
        _require_exact_fields(action_compile, _ACTION_COMPILE_FIELDS, "action_compile")

        def bind_input(value: Any, label: str, *, nullable: bool = False) -> ExactFileBinding | None:
            return _capture_binding(value, label, input_roots, nullable=nullable)

        receipt = bind_input(action_compile["receipt"], "action_compile.receipt")
        context = bind_input(action_compile["validator_context"], "action_compile.validator_context")
        authority = _capture_binding(
            action_compile["authority_binding"],
            "action_compile.authority_binding",
            (trust.authority_root,),
        )
        state = bind_input(raw["state_receipt"], "state_receipt")
        interaction = bind_input(raw["interaction_receipt"], "interaction_receipt")
        final_boundary = bind_input(
            raw["final_boundary_receipt"], "final_boundary_receipt", nullable=True
        )
        rollback = bind_input(raw["rollback_receipt"], "rollback_receipt", nullable=True)
        assert receipt and context and authority and state and interaction
        for item, label in (
            (receipt, "action_compile.receipt"),
            (context, "action_compile.validator_context"),
            (authority, "action_compile.authority_binding"),
            (state, "state_receipt"),
            (interaction, "interaction_receipt"),
        ):
            if item.path.suffix.lower() != ".json":
                raise ActionDeliveryGateError(f"{label} must be a .json file")
        if final_boundary and final_boundary.path.suffix.lower() != ".json":
            raise ActionDeliveryGateError("final_boundary_receipt must be a .json file")
        if rollback and rollback.path.suffix.lower() != ".json":
            raise ActionDeliveryGateError("rollback_receipt must be a .json file")

        authority_data = _json_object(authority.snapshot, "authority binding")
        _require_exact_fields(authority_data, _AUTHORITY_FIELDS, "authority binding")
        trusted_authority = trust.policy["trusted_authority"]
        if authority_data["schema_revision"] != trusted_authority["schema_revision"]:
            raise ActionDeliveryGateError("authority binding schema revision mismatch")
        if authority_data["issuer_id"] != trusted_authority["issuer_id"]:
            raise ActionDeliveryGateError("authority binding issuer is not Runtime-owned")
        if authority_data["policy_id"] != trust.policy["policy_id"]:
            raise ActionDeliveryGateError("authority binding trust policy mismatch")
        if authority_data["task_id"] != task_id:
            raise ActionDeliveryGateError("authority binding task_id mismatch")

        receipt_bindings = authority_data["receipt_bindings"]
        if not isinstance(receipt_bindings, dict):
            raise ActionDeliveryGateError("authority receipt_bindings must be an object")
        actual_bindings = {
            "action_compile_receipt": receipt.sha256,
            "validator_context": context.sha256,
            "state_receipt": state.sha256,
            "interaction_receipt": interaction.sha256,
            "final_boundary_receipt": final_boundary.sha256 if final_boundary else None,
            "rollback_receipt": rollback.sha256 if rollback else None,
        }
        if receipt_bindings != actual_bindings:
            raise ActionDeliveryGateError("receipt bindings do not match Runtime authority")

        action_data = _json_object(receipt.snapshot, "action compile receipt")
        authority_identity = {
            "action_id": authority_data["action_id"],
            "action_revision": authority_data["action_revision"],
            "execution_id": authority_data["execution_id"],
        }
        if action_data.get("action_id") != authority_identity["action_id"]:
            raise ActionDeliveryGateError("action receipt action_id mismatch authority")
        if action_data.get("action_revision") != authority_identity["action_revision"]:
            raise ActionDeliveryGateError("action receipt action_revision mismatch authority")
        if action_data.get("execution_identity", {}).get("execution_id") != authority_identity["execution_id"]:
            raise ActionDeliveryGateError("action receipt execution_id mismatch authority")

        transport = authority_data["transport"]
        if not isinstance(transport, dict) or set(transport) != {"entrypoint", "action_spec"}:
            raise ActionDeliveryGateError("authority transport must contain entrypoint + action_spec")
        entrypoint = bind_input(transport["entrypoint"], "authority.transport.entrypoint", nullable=True)
        action_spec = bind_input(transport["action_spec"], "authority.transport.action_spec", nullable=True)
        if action_data.get("transport") != transport:
            raise ActionDeliveryGateError("action receipt transport does not match Runtime authority")

        rollback_plan = authority_data["rollback_plan"]
        if not isinstance(rollback_plan, dict):
            raise ActionDeliveryGateError("rollback_plan must be an object")
        expected_absent_value = rollback_plan.get("expected_absent_paths")
        if not isinstance(expected_absent_value, list):
            raise ActionDeliveryGateError("rollback_plan.expected_absent_paths must be an array")
        rollback_impl_value = rollback_plan.get("implementation")
        rollback_requires_implementation = receipt_phase == "RESULT" and bool(expected_absent_value)
        if rollback_requires_implementation and rollback_impl_value is None:
            raise ActionDeliveryGateError(
                "ROLLBACK_REQUIRED_PLAN_REQUIRES_IMPLEMENTATION_BINDING"
            )
        rollback_implementation = bind_input(
            rollback_impl_value,
            "authority.rollback_plan.implementation",
            nullable=not rollback_requires_implementation,
        )

        return cls(
            source_path=source,
            source_sha256=actual_sha,
            source_snapshot=source_snapshot,
            gate_id=gate_id,
            task_id=task_id,
            receipt_phase=receipt_phase,
            allowed_input_roots=input_roots,
            allowed_output_root=output_root,
            report_root=report_root,
            timeout_seconds=timeout_seconds,
            output_budget=output_budget,
            runtime_trust=trust,
            action_compile_receipt=receipt,
            validator_context=context,
            authority_binding=authority,
            state_receipt=state,
            interaction_receipt=interaction,
            final_boundary_receipt=final_boundary,
            rollback_receipt=rollback,
            entrypoint=entrypoint,
            action_spec=action_spec,
            rollback_implementation=rollback_implementation,
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _load_runtime_trust_context_with_authority_root(authority_root: Path) -> RuntimeTrustContext:
    module_path = Path(__file__).resolve()
    candidate_root = module_path.parents[3].resolve()
    policy_path = module_path.with_name("action_delivery_trust_policy_r002.json")
    policy_binding = _capture_exact_path(policy_path, TRUST_POLICY_SHA256, "trust policy")
    policy = _json_object(policy_binding.snapshot, "trust policy")
    if policy.get("schema_revision") != SCHEMA_REVISION:
        raise ActionDeliveryGateError("trust policy schema revision mismatch")
    authority_root = authority_root.resolve()
    if not authority_root.is_dir():
        raise ActionDeliveryGateError(f"trusted authority root is missing: {authority_root}")

    validator_policy = policy["trusted_action_compile_validator"]
    validator_path = (candidate_root / validator_policy["relative_path"]).resolve()
    trusted_validator = _capture_exact_path(
        validator_path,
        str(validator_policy["sha256"]),
        "trusted action compile validator",
        expected_bytes=int(validator_policy["bytes"]),
    )
    probe_policy = policy["trusted_ps51_probe"]
    probe_path = (candidate_root / probe_policy["relative_path"]).resolve()
    contract_path = (candidate_root / probe_policy["contract_relative_path"]).resolve()
    trusted_probe = _capture_exact_path(
        probe_path,
        str(probe_policy["sha256"]),
        "trusted PS51 probe",
        expected_bytes=int(probe_policy["bytes"]),
    )
    trusted_contract = _capture_exact_path(
        contract_path,
        str(probe_policy["contract_sha256"]),
        "trusted PS51 probe contract",
        expected_bytes=int(probe_policy["contract_bytes"]),
    )
    return RuntimeTrustContext(
        candidate_root=candidate_root,
        authority_root=authority_root,
        policy=MappingProxyType(policy),
        policy_binding=policy_binding,
        trusted_validator=trusted_validator,
        trusted_ps51_probe=trusted_probe,
        trusted_ps51_contract=trusted_contract,
    )


def load_runtime_trust_context() -> RuntimeTrustContext:
    module_path = Path(__file__).resolve()
    policy_path = module_path.with_name("action_delivery_trust_policy_r002.json")
    policy_binding = _capture_exact_path(policy_path, TRUST_POLICY_SHA256, "trust policy")
    policy = _json_object(policy_binding.snapshot, "trust policy")
    authority = policy.get("authority_root")
    if not isinstance(authority, dict) or authority.get("mode") != "EXACT_WINDOWS_RUNTIME_DATA_ROOT":
        raise ActionDeliveryGateError("trusted authority-root contract is invalid")
    if os.name != "nt":
        raise ActionDeliveryGateError("public Action Delivery Gate requires the exact Windows Runtime authority root")
    return _load_runtime_trust_context_with_authority_root(Path(str(authority["windows_path"])))


def _runtime_trust_context_for_tests(authority_root: str | Path) -> RuntimeTrustContext:
    """Use the exact package trust policy with a test-only authority root.

    The public CLI exposes no authority-root override. This helper is confined to
    deterministic tests and cannot make a user-supplied gate spec authoritative.
    """

    root = Path(authority_root).resolve()
    if not root.is_dir():
        raise ActionDeliveryGateError("test authority root must exist")
    return _load_runtime_trust_context_with_authority_root(root)


def requires_pre_delivery_gate(*, action_kind: str, user_action_required: bool) -> bool:
    if action_kind not in _ALLOWED_ACTION_KINDS:
        raise ActionDeliveryGateError(f"unsupported action_kind: {action_kind}")
    return user_action_required or action_kind in _EXECUTABLE_ACTION_KINDS


def expected_decision_for_state(state: str) -> str:
    try:
        return _STATE_DECISIONS[state]
    except KeyError as exc:
        raise ActionDeliveryGateError(f"unsupported result state: {state}") from exc


def _powershell_code_surface(text: str) -> str:
    out: list[str] = []
    i = 0
    state = "CODE"
    line_start = True
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "CODE":
            if ch == "#":
                state = "LINE_COMMENT"
                out.append(" ")
            elif ch == "<" and nxt == "#":
                state = "BLOCK_COMMENT"
                out.extend((" ", " "))
                i += 1
            elif ch == "@" and nxt in {"'", '"'}:
                state = "SINGLE_HERE" if nxt == "'" else "DOUBLE_HERE"
                out.extend((" ", " "))
                i += 1
            elif ch == "'":
                state = "SINGLE"
                out.append(" ")
            elif ch == '"':
                state = "DOUBLE"
                out.append(" ")
            else:
                out.append(ch)
            line_start = ch in "\r\n"
        elif state == "LINE_COMMENT":
            if ch in "\r\n":
                state = "CODE"
                out.append(ch)
                line_start = True
            else:
                out.append(" ")
        elif state == "BLOCK_COMMENT":
            if ch == "#" and nxt == ">":
                out.extend((" ", " "))
                i += 1
                state = "CODE"
            else:
                out.append(ch if ch in "\r\n" else " ")
        elif state == "SINGLE":
            if ch == "'" and nxt == "'":
                out.extend((" ", " "))
                i += 1
            elif ch == "'":
                out.append(" ")
                state = "CODE"
            else:
                out.append(ch if ch in "\r\n" else " ")
        elif state == "DOUBLE":
            if ch == "`" and nxt:
                out.extend((" ", " "))
                i += 1
            elif ch == '"':
                out.append(" ")
                state = "CODE"
            else:
                out.append(ch if ch in "\r\n" else " ")
        else:
            marker = "'@" if state == "SINGLE_HERE" else '"@'
            if line_start and text.startswith(marker, i):
                out.extend((" ", " "))
                i += 1
                state = "CODE"
                line_start = False
            else:
                out.append(ch if ch in "\r\n" else " ")
                line_start = ch in "\r\n"
        i += 1
    return "".join(out)


def validate_ps51_source_text(text: str) -> list[str]:
    """Conservative static preflight; the canonical PS Parser AST probe remains required."""

    code = _powershell_code_surface(text)
    lowered = code.lower()
    errors: list[str] = []
    checks = (
        (r"\bpython(?:\.exe)?\s+-c\b", "COMPLEX_PYTHON_C_TRANSPORT_REJECTED"),
        (r"\bopenfiledialog\b", "FILE_PICKER_PRIMARY_ENTRY_REJECTED"),
        (r"\bget-history\b", "SESSION_HISTORY_DEPENDENCY_REJECTED"),
        (r"\.showdialog\s*\(", "FILE_PICKER_PRIMARY_ENTRY_REJECTED"),
        (r"\$home[\\/]+downloads\b", "DOWNLOAD_DISCOVERY_PRIMARY_ENTRY_REJECTED"),
        (r"join-path\s+\$home\s+downloads\b", "DOWNLOAD_DISCOVERY_PRIMARY_ENTRY_REJECTED"),
        (r"\bpowershell(?:\.exe)?\b[^\r\n]*\s-command\b", "NESTED_CHILD_COMMAND_REJECTED"),
        (r"&\s*\$[a-z_][a-z0-9_]*\b", "DYNAMIC_PARENT_SESSION_SCRIPT_EXECUTION_REJECTED"),
    )
    for pattern, error_code in checks:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            errors.append(error_code)
    # Reject every executable member/property Count shape. This covers $items.Count,
    # $obj.Children.Count, parenthesized pipelines and newline-separated property chains.
    if re.search(
        r"(?:\$[a-z_][a-z0-9_]*|\)|\])(?:\s*\.\s*[a-z_][a-z0-9_]*)*\s*\.\s*count\b",
        lowered,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        errors.append("PS51_MEMBER_COUNT_REJECTED")
    return sorted(set(errors))


def _assert_binding_current(binding: ExactFileBinding, label: str) -> None:
    if not binding.path.is_file():
        raise ActionDeliveryGateError(f"POST_BINDING_FILE_MISSING:{label}:{binding.path}")
    current = binding.path.read_bytes()
    actual_sha = sha256_bytes(current)
    if len(current) != binding.bytes or actual_sha != binding.sha256:
        raise ActionDeliveryGateError(
            f"POST_BINDING_MUTATION_REJECTED:{label}:EXPECTED={binding.sha256}:ACTUAL={actual_sha}"
        )


def _revalidate_spec_bindings(spec: ActionDeliveryGateSpec) -> None:
    bindings: list[tuple[str, ExactFileBinding | None]] = [
        ("GATE_SPEC", ExactFileBinding(spec.source_path, len(spec.source_snapshot), spec.source_sha256, spec.source_snapshot)),
        ("TRUST_POLICY", spec.runtime_trust.policy_binding),
        ("TRUSTED_VALIDATOR", spec.runtime_trust.trusted_validator),
        ("TRUSTED_PS51_PROBE", spec.runtime_trust.trusted_ps51_probe),
        ("TRUSTED_PS51_CONTRACT", spec.runtime_trust.trusted_ps51_contract),
        ("ACTION_COMPILE_RECEIPT", spec.action_compile_receipt),
        ("VALIDATOR_CONTEXT", spec.validator_context),
        ("AUTHORITY_BINDING", spec.authority_binding),
        ("STATE_RECEIPT", spec.state_receipt),
        ("INTERACTION_RECEIPT", spec.interaction_receipt),
        ("FINAL_BOUNDARY_RECEIPT", spec.final_boundary_receipt),
        ("ROLLBACK_RECEIPT", spec.rollback_receipt),
        ("ENTRYPOINT", spec.entrypoint),
        ("ACTION_SPEC", spec.action_spec),
        ("ROLLBACK_IMPLEMENTATION", spec.rollback_implementation),
    ]
    for label, binding in bindings:
        if binding is not None:
            _assert_binding_current(binding, label)


def _run_trusted_validator(spec: ActionDeliveryGateSpec) -> dict[str, Any]:
    validator = spec.runtime_trust.trusted_validator
    _assert_binding_current(validator, "TRUSTED_VALIDATOR")
    namespace: dict[str, Any] = {
        "__name__": "universal_runtime.devtools._trusted_action_compile_validator_r002_snapshot",
        "__file__": str(validator.path),
    }
    exec(compile(validator.snapshot, str(validator.path), "exec"), namespace, namespace)
    evaluator = namespace.get("evaluate_snapshots")
    if not callable(evaluator):
        raise ActionDeliveryGateError("trusted validator snapshot lacks evaluate_snapshots")
    result = evaluator(
        spec.action_compile_receipt.snapshot,
        spec.validator_context.snapshot,
        spec.authority_binding.snapshot,
    )
    if not isinstance(result, dict) or result.get("validation_result") != "PASS":
        raise ActionDeliveryGateError(f"TRUSTED_ACTION_COMPILE_VALIDATOR_NOT_PASS:{result}")
    if result.get("contract_errors") or result.get("blockers"):
        raise ActionDeliveryGateError("trusted action compile validator returned findings")
    return result


def _derive_result_state(plan: Mapping[str, Any], output_root: Path) -> tuple[str, list[str], str]:
    required = {"final_result_path", "partial_result_path", "inprogress_path", "expected_complete_sha256"}
    _require_exact_fields(plan, required, "publication_plan")
    paths = {
        key: Path(str(plan[key])).resolve()
        for key in ("final_result_path", "partial_result_path", "inprogress_path")
    }
    for key, path in paths.items():
        if not _within(path, output_root):
            raise ActionDeliveryGateError(f"PUBLICATION_PATH_OUTSIDE_OUTPUT_ROOT:{key}:{path}")
    if len({os.path.normcase(str(x)) for x in paths.values()}) != 3:
        raise ActionDeliveryGateError("publication paths must be distinct")
    final_exists = paths["final_result_path"].is_file()
    partial_exists = paths["partial_result_path"].exists()
    inprogress_exists = paths["inprogress_path"].exists()
    final_sha = sha256_file(paths["final_result_path"]) if final_exists else "NONE"
    expected_sha = plan["expected_complete_sha256"]
    if expected_sha is not None and not _is_sha256(str(expected_sha)):
        raise ActionDeliveryGateError("expected_complete_sha256 is invalid")
    if final_exists and (partial_exists or inprogress_exists):
        state = "STALE_CONFLICT"
    elif final_exists and expected_sha is None:
        state = "COMPLETE_UNVERIFIED"
    elif final_exists and final_sha == expected_sha:
        state = "COMPLETE_VALID"
    elif final_exists:
        state = "STALE_CONFLICT"
    elif partial_exists:
        state = "INCOMPLETE_RECOVERABLE"
    elif inprogress_exists:
        state = "IN_PROGRESS"
    else:
        state = "ABSENT"
    lines = [
        f"final_result_path={paths['final_result_path']}",
        f"final_exists={str(final_exists).lower()}",
        f"final_sha256={final_sha}",
        f"partial_result_path={paths['partial_result_path']}",
        f"partial_exists={str(partial_exists).lower()}",
        f"inprogress_path={paths['inprogress_path']}",
        f"inprogress_exists={str(inprogress_exists).lower()}",
        f"derived_state={state}",
    ]
    digest = sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return state, lines, digest


def _validate_state_receipt(
    data: Mapping[str, Any],
    authority: Mapping[str, Any],
    output_root: Path,
) -> tuple[str, list[str]]:
    required = {
        "schema_revision",
        "receipt_id",
        "producer_id",
        "producer_contract_revision",
        "action_id",
        "action_revision",
        "execution_id",
        "state",
        "classification_result",
        "decision",
        "proof_class",
        "currentness_ref",
        "currentness_lines",
        "currentness_sha256",
    }
    errors: list[str] = []
    try:
        _require_exact_fields(data, required, "state receipt")
        trusted = authority["_trusted_receipt_producers"]["state"]
        if data["schema_revision"] != "R002":
            errors.append("STATE_RECEIPT_SCHEMA_REVISION_MISMATCH")
        if data["producer_id"] != trusted["producer_id"]:
            errors.append("STATE_RECEIPT_UNTRUSTED_PRODUCER")
        if data["producer_contract_revision"] != trusted["contract_revision"]:
            errors.append("STATE_RECEIPT_PRODUCER_REVISION_MISMATCH")
        for field in ("action_id", "action_revision", "execution_id"):
            if data[field] != authority[field]:
                errors.append(f"STATE_RECEIPT_{field.upper()}_MISMATCH")
        state, lines, digest = _derive_result_state(authority["publication_plan"], output_root)
        if data["state"] != state:
            errors.append("RESULT_STATE_NOT_DERIVED_FROM_FILESYSTEM")
        decision = expected_decision_for_state(state)
        if data["decision"] != decision:
            errors.append("RESULT_STATE_DECISION_MISMATCH")
        if data["classification_result"] != "PASS":
            errors.append("RESULT_STATE_CLASSIFICATION_NOT_PASS")
        if data["currentness_lines"] != lines:
            errors.append("RESULT_STATE_CURRENTNESS_LINES_MISMATCH")
        if data["currentness_sha256"] != digest:
            errors.append("RESULT_STATE_CURRENTNESS_SHA_MISMATCH")
        if _PROOF_ORDER.get(str(data["proof_class"]), 0) < _PROOF_ORDER["VALIDATED"]:
            errors.append("RESULT_STATE_REQUIRES_VALIDATED_PROOF")
        return decision, sorted(set(errors))
    except (KeyError, ActionDeliveryGateError, TypeError, ValueError) as exc:
        return "STOP", [f"STATE_RECEIPT_VALIDATION_ERROR:{exc}"]


def _validate_interaction_receipt(data: Mapping[str, Any], authority: Mapping[str, Any]) -> list[str]:
    required = {
        "schema_revision",
        "receipt_id",
        "producer_id",
        "producer_contract_revision",
        "action_id",
        "action_revision",
        "execution_id",
        "validation_result",
        "proof_class",
        "user_action_required",
        "user_operation_count",
        "user_next_action",
        "rendered_action",
        "file_hunt_required",
        "multiline_paste_required",
        "return_target",
    }
    errors: list[str] = []
    try:
        _require_exact_fields(data, required, "interaction receipt")
        trusted = authority["_trusted_receipt_producers"]["interaction"]
        plan = authority["interaction_plan"]
        if data["schema_revision"] != "R002":
            errors.append("INTERACTION_RECEIPT_SCHEMA_REVISION_MISMATCH")
        if data["producer_id"] != trusted["producer_id"]:
            errors.append("INTERACTION_RECEIPT_UNTRUSTED_PRODUCER")
        if data["producer_contract_revision"] != trusted["contract_revision"]:
            errors.append("INTERACTION_RECEIPT_PRODUCER_REVISION_MISMATCH")
        for field in ("action_id", "action_revision", "execution_id"):
            if data[field] != authority[field]:
                errors.append(f"INTERACTION_RECEIPT_{field.upper()}_MISMATCH")
        if data["validation_result"] != "PASS":
            errors.append("INTERACTION_VALIDATION_NOT_PASS")
        if _PROOF_ORDER.get(str(data["proof_class"]), 0) < _PROOF_ORDER["VALIDATED"]:
            errors.append("INTERACTION_REQUIRES_VALIDATED_PROOF")
        if bool(data["user_action_required"]) != bool(plan["user_action_required"]):
            errors.append("INTERACTION_USER_ACTION_REQUIRED_MISMATCH_AUTHORITY")
        if int(data["user_operation_count"]) != int(plan["user_operation_count"]):
            errors.append("INTERACTION_OPERATION_COUNT_MISMATCH_AUTHORITY")
        if sha256_bytes(str(data["user_next_action"]).encode("utf-8")) != plan["user_next_action_sha256"]:
            errors.append("USER_NEXT_ACTION_SHA_MISMATCH_AUTHORITY")
        if sha256_bytes(str(data["rendered_action"]).encode("utf-8")) != plan["rendered_action_sha256"]:
            errors.append("RENDERED_ACTION_SHA_MISMATCH_AUTHORITY")
        for field in ("return_target", "file_hunt_required", "multiline_paste_required"):
            if data[field] != plan[field]:
                errors.append(f"INTERACTION_{field.upper()}_MISMATCH_AUTHORITY")
        if plan["user_action_required"]:
            if int(data["user_operation_count"]) != 1:
                errors.append("USER_ACTION_REQUIRES_EXACTLY_ONE_OPERATION")
            if not str(data["user_next_action"]).strip() or str(data["user_next_action"]).strip().upper() == "NONE":
                errors.append("USER_NEXT_ACTION_REQUIRED")
            if data["file_hunt_required"]:
                errors.append("USER_FILE_HUNT_REJECTED")
            if data["multiline_paste_required"]:
                errors.append("MULTILINE_PASTE_PRIMARY_ENTRY_REJECTED")
        else:
            if int(data["user_operation_count"]) != 0 or str(data["user_next_action"]).strip().upper() != "NONE":
                errors.append("NO_USER_ACTION_REQUIRES_EXPLICIT_NONE_AND_ZERO_OPERATIONS")
        return sorted(set(errors))
    except (KeyError, ActionDeliveryGateError, TypeError, ValueError) as exc:
        return [f"INTERACTION_RECEIPT_VALIDATION_ERROR:{exc}"]


def _binding_dict(binding: ExactFileBinding) -> dict[str, Any]:
    return {"path": str(binding.path), "bytes": binding.bytes, "sha256": binding.sha256}


def _final_boundary_currentness_lines(
    *,
    action_id: str,
    action_revision: str,
    execution_id: str,
    host: Mapping[str, Any],
    entrypoint: ExactFileBinding,
    action_spec: ExactFileBinding,
    planned_argv: list[str],
    probe_contract_argv: list[str],
) -> list[str]:
    return [
        f"action_id={action_id}",
        f"action_revision={action_revision}",
        f"execution_id={execution_id}",
        f"powershell_edition={host['powershell_edition']}",
        f"powershell_major={host['powershell_major']}",
        f"effective_execution_policy={host['effective_execution_policy']}",
        f"language_mode={host['language_mode']}",
        f"target_script_path={entrypoint.path}",
        f"target_script_sha256={entrypoint.sha256}",
        f"action_spec_path={action_spec.path}",
        f"action_spec_sha256={action_spec.sha256}",
        f"planned_action_argv={chr(31).join(planned_argv)}",
        f"probe_invocation_contract={chr(31).join(probe_contract_argv)}",
    ]


def _validate_final_boundary_receipt(
    data: Mapping[str, Any],
    spec: ActionDeliveryGateSpec,
    authority: Mapping[str, Any],
) -> list[str]:
    required = {
        "schema_revision",
        "receipt_id",
        "producer_id",
        "producer_contract_revision",
        "action_id",
        "action_revision",
        "execution_id",
        "transport_family",
        "profile_id",
        "validation_result",
        "proof_class",
        "parser_result",
        "ast_safe_subset_result",
        "runtime_semantic_fixture_result",
        "cardinality",
        "strict_mode",
        "host_observation",
        "probe_invocation_contract",
        "planned_action",
        "entrypoint",
        "action_spec",
        "prohibited_primary_transport",
        "currentness_ref",
        "currentness_lines",
        "currentness_sha256",
    }
    errors: list[str] = []
    try:
        _require_exact_fields(data, required, "final boundary receipt")
        if spec.entrypoint is None or spec.action_spec is None:
            return ["EXECUTABLE_ACTION_REQUIRES_ENTRYPOINT_AND_ACTION_SPEC"]
        probe_policy = spec.runtime_trust.policy["trusted_ps51_probe"]
        if data["schema_revision"] != "R002":
            errors.append("FINAL_BOUNDARY_SCHEMA_REVISION_MISMATCH")
        if data["producer_id"] != probe_policy["producer_id"]:
            errors.append("FINAL_BOUNDARY_UNTRUSTED_PRODUCER")
        if data["producer_contract_revision"] != probe_policy["producer_contract_revision"]:
            errors.append("FINAL_BOUNDARY_PRODUCER_REVISION_MISMATCH")
        for field in ("action_id", "action_revision", "execution_id"):
            if data[field] != authority[field]:
                errors.append(f"FINAL_BOUNDARY_{field.upper()}_MISMATCH")
        if data["transport_family"] != "WINDOWS_POWERSHELL_5_1":
            errors.append("FINAL_BOUNDARY_TRANSPORT_FAMILY_MISMATCH")
        if data["profile_id"] != "PS51_SAFE_EXECUTION_PROFILE_R001":
            errors.append("PS51_PROFILE_BINDING_MISMATCH")
        if data["validation_result"] != "PASS":
            errors.append("FINAL_BOUNDARY_VALIDATION_NOT_PASS")
        if _PROOF_ORDER.get(str(data["proof_class"]), 0) < _PROOF_ORDER["VALIDATED"]:
            errors.append("FINAL_BOUNDARY_REQUIRES_VALIDATED_PROOF")
        for field in ("parser_result", "ast_safe_subset_result", "runtime_semantic_fixture_result"):
            if data[field] != "PASS":
                errors.append(f"FINAL_BOUNDARY_{field.upper()}_NOT_PASS")
        cardinality = data["cardinality"]
        _require_exact_fields(cardinality, {"zero", "one_pscustomobject", "many"}, "cardinality")
        if any(cardinality[x] != "PASS" for x in cardinality):
            errors.append("PS51_ZERO_ONE_MANY_NOT_PASS")
        strict = data["strict_mode"]
        _require_exact_fields(strict, {"missing_property_expected_failure", "member_count_ast_absent"}, "strict_mode")
        if strict["missing_property_expected_failure"] != "PASS":
            errors.append("STRICTMODE_MISSING_PROPERTY_FIXTURE_NOT_PASS")
        if strict["member_count_ast_absent"] is not True:
            errors.append("PS51_MEMBER_COUNT_AST_NOT_PROVEN_ABSENT")

        host = data["host_observation"]
        _require_exact_fields(
            host,
            {
                "proof_class",
                "powershell_edition",
                "powershell_major",
                "effective_execution_policy",
                "language_mode",
            },
            "host_observation",
        )
        if host["proof_class"] != "OBSERVED":
            errors.append("HOST_OBSERVATION_PROOF_CLASS_MISMATCH")
        if host["powershell_edition"] != "Desktop" or int(host["powershell_major"]) != 5:
            errors.append("WINDOWS_POWERSHELL_5_DESKTOP_REQUIRED")
        if host["effective_execution_policy"] != "Bypass":
            errors.append("PS51_CHILD_EXECUTION_POLICY_NOT_BYPASS")
        if host["language_mode"] != "FullLanguage":
            errors.append("PS51_CHILD_LANGUAGE_MODE_NOT_FULLLANGUAGE")

        probe = data["probe_invocation_contract"]
        planned = data["planned_action"]
        _require_exact_fields(probe, {"proof_class", "argv"}, "probe_invocation_contract")
        _require_exact_fields(planned, {"proof_class", "argv"}, "planned_action")
        if probe["proof_class"] != "VALIDATED":
            errors.append("PROBE_INVOCATION_CONTRACT_NOT_VALIDATED")
        if planned["proof_class"] != "DECLARED":
            errors.append("PLANNED_ACTION_MUST_REMAIN_DECLARED")
        probe_argv = probe["argv"]
        planned_argv = planned["argv"]
        if not isinstance(probe_argv, list) or not isinstance(planned_argv, list):
            errors.append("PS51_ARGV_NOT_ARRAY")
            return sorted(set(errors))
        if not probe_argv or not str(probe_argv[0]).lower().endswith("powershell.exe"):
            errors.append("PS51_PROBE_EXECUTABLE_MISMATCH")
            return sorted(set(errors))
        child = str(probe_argv[0])
        expected_prefix = [child, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
        expected_planned = expected_prefix + [
            str(spec.entrypoint.path),
            "-ActionSpecPath",
            str(spec.action_spec.path),
            "-ExpectedActionSpecSha256",
            spec.action_spec.sha256,
        ]
        expected_probe = expected_prefix + [
            str(spec.runtime_trust.trusted_ps51_probe.path),
            "-ActionId",
            authority["action_id"],
            "-ActionRevision",
            authority["action_revision"],
            "-ExecutionId",
            authority["execution_id"],
            "-TargetScriptPath",
            str(spec.entrypoint.path),
            "-ExpectedTargetScriptSha256",
            spec.entrypoint.sha256,
            "-ActionSpecPath",
            str(spec.action_spec.path),
            "-ExpectedActionSpecSha256",
            spec.action_spec.sha256,
            "-OutputPath",
            str(spec.final_boundary_receipt.path),
        ]
        if planned_argv != expected_planned:
            errors.append("PLANNED_ACTION_ARGV_NOT_COMPLETE_OR_EXACT")
        if probe_argv != expected_probe:
            errors.append("PROBE_INVOCATION_CONTRACT_NOT_CANONICAL")
        if data["entrypoint"] != _binding_dict(spec.entrypoint):
            errors.append("FINAL_BOUNDARY_ENTRYPOINT_MISMATCH")
        if data["action_spec"] != _binding_dict(spec.action_spec):
            errors.append("FINAL_BOUNDARY_ACTION_SPEC_MISMATCH")
        source_errors = validate_ps51_source_text(spec.entrypoint.snapshot.decode("utf-8", errors="replace"))
        errors.extend(source_errors)

        prohibited = data["prohibited_primary_transport"]
        required_prohibitions = {
            "browser_download_discovery",
            "file_picker",
            "complex_python_c",
            "session_history",
            "nested_child_command",
            "long_multiline_paste",
        }
        _require_exact_fields(prohibited, required_prohibitions, "prohibited_primary_transport")
        if any(prohibited[x] is not False for x in required_prohibitions):
            errors.append("PROHIBITED_PRIMARY_TRANSPORT_PRESENT")

        lines = _final_boundary_currentness_lines(
            action_id=authority["action_id"],
            action_revision=authority["action_revision"],
            execution_id=authority["execution_id"],
            host=host,
            entrypoint=spec.entrypoint,
            action_spec=spec.action_spec,
            planned_argv=expected_planned,
            probe_contract_argv=expected_probe,
        )
        digest = sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        if data["currentness_lines"] != lines:
            errors.append("FINAL_BOUNDARY_CURRENTNESS_LINES_MISMATCH")
        if data["currentness_sha256"] != digest:
            errors.append("FINAL_BOUNDARY_CURRENTNESS_SHA_MISMATCH")
        return sorted(set(errors))
    except (KeyError, TypeError, ValueError, ActionDeliveryGateError) as exc:
        return [f"FINAL_BOUNDARY_VALIDATION_ERROR:{exc}"]


def _validate_rollback_receipt(
    data: Mapping[str, Any],
    spec: ActionDeliveryGateSpec,
    authority: Mapping[str, Any],
) -> list[str]:
    required = {
        "schema_revision",
        "receipt_id",
        "producer_id",
        "producer_contract_revision",
        "action_id",
        "action_revision",
        "execution_id",
        "rollback_state",
        "attempted",
        "readback_performed",
        "owned_output_roots",
        "expected_absent_paths",
        "actual_remaining_paths",
        "implementation",
        "validation_result",
        "proof_class",
    }
    errors: list[str] = []
    try:
        _require_exact_fields(data, required, "rollback receipt")
        trusted = authority["_trusted_receipt_producers"]["rollback"]
        plan = authority["rollback_plan"]
        if data["schema_revision"] != "R002":
            errors.append("ROLLBACK_SCHEMA_REVISION_MISMATCH")
        if data["producer_id"] != trusted["producer_id"]:
            errors.append("ROLLBACK_UNTRUSTED_PRODUCER")
        if data["producer_contract_revision"] != trusted["contract_revision"]:
            errors.append("ROLLBACK_PRODUCER_REVISION_MISMATCH")
        for field in ("action_id", "action_revision", "execution_id"):
            if data[field] != authority[field]:
                errors.append(f"ROLLBACK_{field.upper()}_MISMATCH")
        owned_roots = [Path(str(x)).resolve() for x in plan["owned_output_roots"]]
        expected_paths = [Path(str(x)).resolve() for x in plan["expected_absent_paths"]]
        if any(not _within(root, spec.allowed_output_root) for root in owned_roots):
            errors.append("ROLLBACK_OWNED_ROOT_OUTSIDE_ALLOWED_OUTPUT_ROOT")
        for path in expected_paths:
            if not _within(path, spec.allowed_output_root) or not any(_within(path, root) for root in owned_roots):
                errors.append("ROLLBACK_PATH_OUTSIDE_ACTION_OWNED_OUTPUT_ROOT")
        if data["owned_output_roots"] != [str(x) for x in owned_roots]:
            errors.append("ROLLBACK_OWNED_ROOT_SET_MISMATCH_PLAN")
        if data["expected_absent_paths"] != [str(x) for x in expected_paths]:
            errors.append("ROLLBACK_PATH_SET_MISMATCH_PLAN")
        if expected_paths and spec.rollback_implementation is None:
            errors.append("ROLLBACK_REQUIRED_PLAN_REQUIRES_IMPLEMENTATION_BINDING")
        expected_impl = _binding_dict(spec.rollback_implementation) if spec.rollback_implementation else None
        if data["implementation"] != expected_impl:
            errors.append("ROLLBACK_IMPLEMENTATION_MISMATCH_PLAN")
        actual_remaining = [str(x) for x in expected_paths if x.exists()]
        if data["actual_remaining_paths"] != actual_remaining:
            errors.append("ROLLBACK_READBACK_NOT_DERIVED_FROM_FILESYSTEM")
        if not expected_paths:
            if data["rollback_state"] != "NOT_REQUIRED":
                errors.append("ROLLBACK_EMPTY_PLAN_MUST_BE_NOT_REQUIRED")
            if data["attempted"] or data["readback_performed"]:
                errors.append("ROLLBACK_NOT_REQUIRED_CANNOT_CLAIM_ATTEMPT")
        else:
            if data["rollback_state"] != "READBACK_VALIDATED_COMPLETE":
                errors.append("ROLLBACK_REQUIRED_PLAN_REQUIRES_READBACK_COMPLETE_STATE")
            if data["attempted"] is not True or data["readback_performed"] is not True:
                errors.append("ROLLBACK_COMPLETE_REQUIRES_ATTEMPT_AND_READBACK")
            if actual_remaining:
                errors.append("ROLLBACK_COMPLETE_REQUIRES_ZERO_REMAINING_PATHS")
        if data["validation_result"] != "PASS":
            errors.append("ROLLBACK_VALIDATION_NOT_PASS")
        if _PROOF_ORDER.get(str(data["proof_class"]), 0) < _PROOF_ORDER["VALIDATED"]:
            errors.append("ROLLBACK_REQUIRES_VALIDATED_PROOF")
        return sorted(set(errors))
    except (KeyError, TypeError, ValueError, ActionDeliveryGateError) as exc:
        return [f"ROLLBACK_RECEIPT_VALIDATION_ERROR:{exc}"]


def evaluate_gate(spec: ActionDeliveryGateSpec) -> dict[str, Any]:
    _revalidate_spec_bindings(spec)
    authority = _json_object(spec.authority_binding.snapshot, "authority binding")
    authority = dict(authority)
    authority["_trusted_receipt_producers"] = spec.runtime_trust.policy["trusted_receipt_producers"]
    validator_result = _run_trusted_validator(spec)
    action = _json_object(spec.action_compile_receipt.snapshot, "action compile receipt")
    state = _json_object(spec.state_receipt.snapshot, "state receipt")
    interaction = _json_object(spec.interaction_receipt.snapshot, "interaction receipt")
    final_boundary = (
        _json_object(spec.final_boundary_receipt.snapshot, "final boundary receipt")
        if spec.final_boundary_receipt is not None
        else None
    )
    rollback = (
        _json_object(spec.rollback_receipt.snapshot, "rollback receipt")
        if spec.rollback_receipt is not None
        else None
    )

    errors: list[str] = []
    action_kind = str(action.get("action_kind"))
    compile_result = str(action.get("compile_result"))
    if str(action.get("receipt_phase")) != spec.receipt_phase:
        errors.append("ACTION_COMPILE_RECEIPT_PHASE_MISMATCH")
    if action_kind not in _ALLOWED_ACTION_KINDS:
        errors.append("ACTION_KIND_INVALID")
    required_gate = requires_pre_delivery_gate(
        action_kind=action_kind, user_action_required=bool(action.get("user_action_required"))
    )
    state_decision, state_errors = _validate_state_receipt(state, authority, spec.allowed_output_root)
    errors.extend(state_errors)
    errors.extend(_validate_interaction_receipt(interaction, authority))

    if action_kind in _EXECUTABLE_ACTION_KINDS:
        if final_boundary is None:
            errors.append("EXECUTABLE_ACTION_REQUIRES_FINAL_BOUNDARY_RECEIPT")
        else:
            errors.extend(_validate_final_boundary_receipt(final_boundary, spec, authority))
    elif final_boundary is not None:
        errors.append("NON_EXECUTABLE_ACTION_MUST_NOT_CARRY_FINAL_BOUNDARY_RECEIPT")

    if compile_result == "PASS":
        if action_kind == "EXECUTE" and state_decision != "EXECUTE":
            errors.append("EXECUTE_ACTION_CONFLICTS_WITH_STATE_DECISION")
        if action_kind == "RECOVERY" and state_decision != "RECOVERY":
            errors.append("RECOVERY_ACTION_CONFLICTS_WITH_STATE_DECISION")
        if action_kind == "NO_OP":
            errors.append("NO_OP_ACTION_REQUIRES_NO_OP_COMPILE_RESULT")
    elif compile_result == "NO_OP":
        if action_kind != "NO_OP":
            errors.append("NO_OP_COMPILE_RESULT_REQUIRES_NO_OP_ACTION")
        if state_decision != "NO_OP":
            errors.append("NO_OP_COMPILE_RESULT_REQUIRES_COMPLETE_VALID_STATE")
    elif compile_result == "STOP":
        errors.append("STOP_ACTION_COMPILE_RECEIPT_CANNOT_EMIT_USER_ACTION")
    else:
        errors.append("COMPILE_RESULT_INVALID")

    rollback_errors: list[str] = []
    if spec.receipt_phase == "RESULT":
        if rollback is None:
            errors.append("RESULT_PHASE_REQUIRES_ROLLBACK_RECEIPT")
        else:
            rollback_errors = _validate_rollback_receipt(rollback, spec, authority)
            errors.extend(rollback_errors)
    elif rollback is not None:
        errors.append("COMPILE_PHASE_MUST_NOT_CARRY_ROLLBACK_RECEIPT")

    if errors:
        gate_result = GATE_RESULT_STOP
        execution_allowed = False
    elif compile_result == "NO_OP":
        gate_result = GATE_RESULT_NO_OP
        execution_allowed = False
    else:
        gate_result = GATE_RESULT_PASS
        execution_allowed = action_kind in _EXECUTABLE_ACTION_KINDS

    return {
        "schema_revision": SCHEMA_REVISION,
        "gate_id": spec.gate_id,
        "task_id": spec.task_id,
        "receipt_phase": spec.receipt_phase,
        "gate_result": gate_result,
        "execution_allowed": execution_allowed,
        "action_kind": action_kind,
        "compile_result": compile_result,
        "requires_pre_delivery_gate": required_gate,
        "action_compile_validator_result": validator_result.get("validation_result"),
        "trusted_validator_id": validator_result.get("trusted_validator_id"),
        "state_decision": state_decision,
        "contract_errors": sorted(set(errors)),
        "rollback_errors": rollback_errors,
        "user_action_required": bool(interaction.get("user_action_required")),
        "user_next_action": str(interaction.get("user_next_action", "NONE")),
        "rendered_action_sha256": sha256_bytes(str(interaction.get("rendered_action", "")).encode("utf-8")),
        "source_bindings": _source_bindings(spec),
        "static_proof_ceiling": "NO_WINDOWS_RUNTIME_OR_CONTROLLER_NON_BYPASS_PROOF",
    }


def run_action_delivery_gate(path: str | Path, expected_spec_sha256: str) -> dict[str, Any]:
    spec = ActionDeliveryGateSpec.from_path(path, expected_spec_sha256)
    try:
        result = evaluate_gate(spec)
    except Exception as exc:
        result = {
            "schema_revision": SCHEMA_REVISION,
            "gate_id": spec.gate_id,
            "task_id": spec.task_id,
            "receipt_phase": spec.receipt_phase,
            "gate_result": GATE_RESULT_STOP,
            "execution_allowed": False,
            "action_kind": "UNKNOWN",
            "compile_result": "STOP",
            "requires_pre_delivery_gate": True,
            "action_compile_validator_result": "FAIL",
            "trusted_validator_id": spec.runtime_trust.policy["trusted_action_compile_validator"]["validator_id"],
            "state_decision": "STOP",
            "contract_errors": [f"GATE_EVALUATION_ERROR:{type(exc).__name__}:{exc}"],
            "rollback_errors": [],
            "user_action_required": False,
            "user_next_action": "NONE",
            "rendered_action_sha256": None,
            "source_bindings": _source_bindings(spec),
            "static_proof_ceiling": "NO_WINDOWS_RUNTIME_OR_CONTROLLER_NON_BYPASS_PROOF",
        }
    report_path = (spec.report_root / f"{spec.gate_id}.{spec.source_sha256}.action-delivery-gate.json").resolve()
    if not _within(report_path, spec.report_root):
        raise ActionDeliveryGateError("ACTION_GATE_REPORT_PATH_ESCAPES_REPORT_ROOT")
    report_sha, publication = _write_once_exact_json(report_path, result)
    result = dict(result)
    result["report_path"] = str(report_path)
    result["report_sha256"] = report_sha
    result["report_publication"] = publication
    return result


def _source_bindings(spec: ActionDeliveryGateSpec) -> dict[str, str | None]:
    return {
        "gate_spec_sha256": spec.source_sha256,
        "trust_policy_sha256": spec.runtime_trust.policy_binding.sha256,
        "trusted_validator_sha256": spec.runtime_trust.trusted_validator.sha256,
        "trusted_ps51_probe_sha256": spec.runtime_trust.trusted_ps51_probe.sha256,
        "trusted_ps51_contract_sha256": spec.runtime_trust.trusted_ps51_contract.sha256,
        "action_compile_receipt_sha256": spec.action_compile_receipt.sha256,
        "validator_context_sha256": spec.validator_context.sha256,
        "authority_binding_sha256": spec.authority_binding.sha256,
        "state_receipt_sha256": spec.state_receipt.sha256,
        "interaction_receipt_sha256": spec.interaction_receipt.sha256,
        "final_boundary_receipt_sha256": spec.final_boundary_receipt.sha256 if spec.final_boundary_receipt else None,
        "rollback_receipt_sha256": spec.rollback_receipt.sha256 if spec.rollback_receipt else None,
        "entrypoint_sha256": spec.entrypoint.sha256 if spec.entrypoint else None,
        "action_spec_sha256": spec.action_spec.sha256 if spec.action_spec else None,
        "rollback_implementation_sha256": spec.rollback_implementation.sha256 if spec.rollback_implementation else None,
    }


def _write_once_exact_json(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(value)
    expected_sha = sha256_bytes(data)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    created = False
    try:
        try:
            fd = os.open(path, flags, 0o600)
            created = True
        except FileExistsError:
            existing = path.read_bytes()
            if existing != data:
                raise ActionDeliveryGateError(
                    f"ACTION_GATE_REPORT_STALE_CONFLICT:{path}:"
                    f"EXISTING={sha256_bytes(existing)}:REQUESTED={expected_sha}"
                )
            return expected_sha, "REUSED_EXISTING_EXACT"
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            if created:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise
        readback = path.read_bytes()
        if readback != data:
            raise ActionDeliveryGateError("ACTION_GATE_REPORT_READBACK_MISMATCH")
        return expected_sha, "CREATED_EXCLUSIVE_AND_READBACK_VALIDATED"
    finally:
        pass


def _capture_binding(
    value: Any,
    label: str,
    roots: tuple[Path, ...],
    *,
    nullable: bool = False,
) -> ExactFileBinding | None:
    if value is None:
        if nullable:
            return None
        raise ActionDeliveryGateError(f"{label} cannot be null")
    if not isinstance(value, dict):
        raise ActionDeliveryGateError(f"{label} must be a file binding")
    _require_exact_fields(value, _BINDING_FIELDS, label)
    path = Path(str(value["path"])).resolve()
    if not any(_within(path, root) for root in roots):
        raise ActionDeliveryGateError(f"{label} is outside trusted/allowed roots: {path}")
    if not path.is_file():
        raise ActionDeliveryGateError(f"{label} is missing: {path}")
    snapshot = path.read_bytes()
    expected_bytes = int(value["bytes"])
    expected_sha = str(value["sha256"]).lower()
    if expected_bytes <= 0 or len(snapshot) != expected_bytes:
        raise ActionDeliveryGateError(f"{label} byte mismatch")
    if not _is_sha256(expected_sha) or sha256_bytes(snapshot) != expected_sha:
        raise ActionDeliveryGateError(f"{label} SHA mismatch")
    return ExactFileBinding(path, expected_bytes, expected_sha, snapshot)


def _capture_exact_path(
    path: Path,
    expected_sha: str,
    label: str,
    *,
    expected_bytes: int | None = None,
) -> ExactFileBinding:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ActionDeliveryGateError(f"{label} missing: {resolved}")
    snapshot = resolved.read_bytes()
    if expected_bytes is not None and len(snapshot) != expected_bytes:
        raise ActionDeliveryGateError(f"{label} byte mismatch")
    if sha256_bytes(snapshot) != expected_sha:
        raise ActionDeliveryGateError(f"{label} SHA mismatch")
    return ExactFileBinding(resolved, len(snapshot), expected_sha, snapshot)


def _json_object(snapshot: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(snapshot.decode("utf-8"))
    except Exception as exc:
        raise ActionDeliveryGateError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ActionDeliveryGateError(f"{label} must be a JSON object")
    return value


def _within(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def _paths_overlap(a: Path, b: Path) -> bool:
    return _within(a, b) or _within(b, a)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _nonempty(value: Any, label: str) -> str:
    text = str(value)
    if not text:
        raise ActionDeliveryGateError(f"{label} must be non-empty")
    return text


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        raise ActionDeliveryGateError(
            f"{label} fields mismatch; missing={sorted(missing)} unknown={sorted(unknown)}"
        )
