from __future__ import annotations

import json
from typing import Any, Mapping

ALLOWED_ACTION_KINDS = {"EXECUTE", "RECOVERY", "COMPILE_ONLY", "BOUNDED_REVIEW", "PRIOR_ART", "NO_OP"}
ALLOWED_COMPILE_RESULTS = {"PASS", "STOP", "NO_OP"}


def _object(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def evaluate_snapshots(
    receipt_bytes: bytes,
    context_bytes: bytes,
    authority_binding_bytes: bytes,
) -> dict[str, Any]:
    """Evaluate exact immutable snapshots selected by the Runtime-owned delivery gate.

    This module is itself pinned by the gate trust policy. It does not accept a caller-
    selected validator path and does not read any path after exact binding.
    """

    receipt = _object(receipt_bytes, "action receipt")
    context = _object(context_bytes, "validator context")
    authority = _object(authority_binding_bytes, "authority binding")
    errors: list[str] = []
    blockers: list[str] = []

    def error(code: str) -> None:
        errors.append(code)

    def block(code: str) -> None:
        blockers.append(code)

    if context.get("context_id") != authority.get("validator_context_id"):
        error("VALIDATOR_CONTEXT_ID_MISMATCH_AUTHORITY")
    if context.get("schema_revision") != authority.get("validator_context_revision"):
        error("VALIDATOR_CONTEXT_REVISION_MISMATCH_AUTHORITY")

    for field in ("action_id", "action_revision", "task_id"):
        if receipt.get(field) != authority.get(field):
            error(f"ACTION_RECEIPT_{field.upper()}_MISMATCH_AUTHORITY")
    execution_id = receipt.get("execution_identity", {}).get("execution_id")
    if execution_id != authority.get("execution_id"):
        error("ACTION_RECEIPT_EXECUTION_ID_MISMATCH_AUTHORITY")

    kind = receipt.get("action_kind")
    result = receipt.get("compile_result")
    if kind not in ALLOWED_ACTION_KINDS:
        error("ACTION_KIND_INVALID")
    if result not in ALLOWED_COMPILE_RESULTS:
        error("COMPILE_RESULT_INVALID")
    if receipt.get("receipt_phase") not in {"COMPILE", "RESULT"}:
        error("RECEIPT_PHASE_INVALID")

    if kind in {"EXECUTE", "RECOVERY"}:
        if result != "PASS":
            block("EXECUTABLE_ACTION_REQUIRES_COMPILE_PASS")
        stop_loss = authority.get("stop_loss")
        if not isinstance(stop_loss, Mapping):
            error("AUTHORITY_STOP_LOSS_MISSING")
        elif stop_loss.get("current_active") is True:
            block("SOURCE_BOUND_ACTIVE_STOP_LOSS_EXECUTION_PROHIBITED")
        transport = receipt.get("transport")
        if not isinstance(transport, Mapping):
            error("EXECUTABLE_ACTION_TRANSPORT_MISSING")
        elif transport != authority.get("transport"):
            error("ACTION_TRANSPORT_MISMATCH_AUTHORITY")
    if kind == "NO_OP" and result != "NO_OP":
        error("NO_OP_ACTION_REQUIRES_NO_OP_RESULT")
    if result == "NO_OP" and kind != "NO_OP":
        error("NO_OP_RESULT_REQUIRES_NO_OP_ACTION")
    if result == "PASS" and receipt.get("failure_evidence"):
        error("PASS_CANNOT_HAVE_FAILURE_EVIDENCE")
    if result == "STOP" and not receipt.get("failure_evidence"):
        error("STOP_REQUIRES_FAILURE_EVIDENCE")

    if bool(receipt.get("user_action_required")) != bool(authority.get("interaction_plan", {}).get("user_action_required")):
        error("USER_ACTION_REQUIRED_MISMATCH_AUTHORITY")
    if receipt.get("rollback_plan") != authority.get("rollback_plan"):
        error("ROLLBACK_PLAN_MISMATCH_AUTHORITY")

    return {
        "validation_result": "PASS" if not errors and not blockers else "FAIL",
        "contract_errors": sorted(set(errors)),
        "blockers": sorted(set(blockers)),
        "trusted_validator_id": "UR_TRUSTED_ACTION_COMPILE_VALIDATOR_R002",
    }
