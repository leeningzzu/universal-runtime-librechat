from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .acceptance_models import AcceptanceReport, AcceptanceSpec, canonical_json, load_spec, sha256_bytes

_ALLOWED_FIELDS = {
    "integration_version",
    "task_id",
    "project_root",
    "allowed_input_roots",
    "allowed_output_root",
    "validator",
    "validator_context",
    "action_receipt",
    "authority_binding",
    "acceptance_spec",
    "report_root",
    "timeout_seconds",
    "output_budget",
}
_FILE_BINDING_FIELDS = {"path", "sha256"}


class ActionAcceptanceError(ValueError):
    """Raised when a local action cannot be safely delegated to Acceptance."""


@dataclass(frozen=True)
class ExactFileBinding:
    path: Path
    sha256: str


@dataclass(frozen=True)
class ActionAcceptanceSpec:
    source_path: Path
    source_sha256: str
    integration_version: str
    task_id: str
    project_root: Path
    allowed_input_roots: tuple[Path, ...]
    allowed_output_root: Path
    validator: ExactFileBinding
    validator_context: ExactFileBinding
    action_receipt: ExactFileBinding
    authority_binding: ExactFileBinding
    acceptance_spec: ExactFileBinding
    report_root: Path
    timeout_seconds: float
    output_budget: int

    @classmethod
    def from_path(cls, path: str | Path, expected_sha256: str) -> "ActionAcceptanceSpec":
        source = Path(path).resolve()
        source_bytes = source.read_bytes()
        source_sha = sha256_bytes(source_bytes)
        if source_sha != expected_sha256:
            raise ActionAcceptanceError("stale integration spec SHA")
        data = json.loads(source_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            raise ActionAcceptanceError("integration spec must be an object")
        unknown = set(data) - _ALLOWED_FIELDS
        if unknown:
            raise ActionAcceptanceError(f"unknown integration field(s): {sorted(unknown)}")
        missing = _ALLOWED_FIELDS - set(data)
        if missing:
            raise ActionAcceptanceError(f"missing integration field(s): {sorted(missing)}")
        if str(data["integration_version"]) != "1":
            raise ActionAcceptanceError("unsupported integration_version")
        task_id = str(data["task_id"])
        if not task_id:
            raise ActionAcceptanceError("task_id must be non-empty")
        project_root = Path(str(data["project_root"])).resolve()
        if not project_root.is_dir():
            raise ActionAcceptanceError("project_root must be an existing directory")
        roots_raw = data["allowed_input_roots"]
        if not isinstance(roots_raw, list) or not roots_raw:
            raise ActionAcceptanceError("allowed_input_roots must be a non-empty array")
        allowed_input_roots = tuple(Path(str(x)).resolve() for x in roots_raw)
        if any(not p.is_dir() for p in allowed_input_roots):
            raise ActionAcceptanceError("every allowed_input_root must be an existing directory")
        allowed_output_root = Path(str(data["allowed_output_root"])).resolve()
        if not allowed_output_root.is_dir():
            raise ActionAcceptanceError("allowed_output_root must be an existing directory")
        report_root = Path(str(data["report_root"])).resolve()
        if _within(report_root, project_root):
            raise ActionAcceptanceError("report_root must be outside project_root")
        if not _within(report_root, allowed_output_root):
            raise ActionAcceptanceError("report_root must be inside allowed_output_root")
        timeout_seconds = float(data["timeout_seconds"])
        output_budget = int(data["output_budget"])
        if timeout_seconds <= 0 or output_budget < 1:
            raise ActionAcceptanceError("timeout_seconds/output_budget must be positive")

        def bound_file(value: Any) -> ExactFileBinding:
            if not isinstance(value, dict) or set(value) != _FILE_BINDING_FIELDS:
                raise ActionAcceptanceError("file binding must contain exactly path + sha256")
            p = Path(str(value["path"])).resolve()
            if not any(_within(p, root) for root in allowed_input_roots):
                raise ActionAcceptanceError(f"input path is outside allowlist: {p}")
            if not p.is_file():
                raise ActionAcceptanceError(f"input file is missing: {p}")
            expected = str(value["sha256"])
            actual = sha256_bytes(p.read_bytes())
            if actual != expected:
                raise ActionAcceptanceError(f"stale input SHA: {p}")
            return ExactFileBinding(p, expected)

        validator = bound_file(data["validator"])
        validator_context = bound_file(data["validator_context"])
        action_receipt = bound_file(data["action_receipt"])
        authority_binding = bound_file(data["authority_binding"])
        acceptance_spec = bound_file(data["acceptance_spec"])
        if validator.path.suffix.lower() != ".py":
            raise ActionAcceptanceError("validator must be a .py file")
        for item in (validator_context, action_receipt, authority_binding, acceptance_spec):
            if item.path.suffix.lower() != ".json":
                raise ActionAcceptanceError("validator context/receipt/binding/acceptance spec must be .json files")
        return cls(
            source,
            source_sha,
            "1",
            task_id,
            project_root,
            allowed_input_roots,
            allowed_output_root,
            validator,
            validator_context,
            action_receipt,
            authority_binding,
            acceptance_spec,
            report_root,
            timeout_seconds,
            output_budget,
        )


@dataclass
class ActionAcceptanceReport:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.data


def _within(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def _atomic_json(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(value)
    fd, tmp = tempfile.mkstemp(prefix=".action-acceptance-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return sha256_bytes(data)


def _validator_operation(spec: ActionAcceptanceSpec) -> dict[str, Any]:
    from .acceptance_runner import _run, _safe_env

    return _run(
        [
            os.fspath(__import__("sys").executable),
            os.fspath(spec.validator.path),
            os.fspath(spec.action_receipt.path),
            os.fspath(spec.validator_context.path),
            os.fspath(spec.authority_binding.path),
        ],
        spec.project_root,
        spec.timeout_seconds,
        spec.output_budget,
        _safe_env(),
    )


def _run_existing_acceptance(spec: AcceptanceSpec) -> AcceptanceReport:
    from .acceptance_runner import run_acceptance

    return run_acceptance(spec)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActionAcceptanceError(f"expected JSON object: {path}")
    return value


def run_action_acceptance(
    spec_or_path: ActionAcceptanceSpec | str | Path,
    *,
    expected_spec_sha256: str | None = None,
    validator_operation: Callable[[ActionAcceptanceSpec], dict[str, Any]] | None = None,
    acceptance_runner: Callable[[AcceptanceSpec], AcceptanceReport] | None = None,
) -> ActionAcceptanceReport:
    if isinstance(spec_or_path, ActionAcceptanceSpec):
        spec = spec_or_path
        if expected_spec_sha256 is not None and spec.source_sha256 != expected_spec_sha256:
            raise ActionAcceptanceError("stale integration spec SHA")
    else:
        if expected_spec_sha256 is None:
            raise ActionAcceptanceError("expected integration spec SHA is required")
        spec = ActionAcceptanceSpec.from_path(spec_or_path, expected_spec_sha256)
    receipt = _load_json(spec.action_receipt.path)
    if receipt.get("action_id") != spec.task_id:
        raise ActionAcceptanceError("action_receipt action_id does not match task_id")
    if receipt.get("action_kind") != "EXECUTE" or receipt.get("compile_result") != "PASS":
        raise ActionAcceptanceError("only compile-PASS EXECUTE actions may delegate to Acceptance")
    pnm = receipt.get("permission_network_model")
    if not isinstance(pnm, dict) or pnm.get("network_allowed") is not False or pnm.get("model_call_allowed") is not False:
        raise ActionAcceptanceError("first-slice action integration requires network/model deny")

    acceptance = load_spec(spec.acceptance_spec.path)
    if acceptance.task_id != spec.task_id:
        raise ActionAcceptanceError("AcceptanceSpec task_id does not match action task_id")
    if Path(acceptance.project_root).resolve() != spec.project_root:
        raise ActionAcceptanceError("AcceptanceSpec project_root does not match integration project_root")
    if acceptance.network_allowed or acceptance.model_call_allowed:
        raise ActionAcceptanceError("AcceptanceSpec must deny network/model")
    if not acceptance.protected_bindings:
        raise ActionAcceptanceError("AcceptanceSpec requires at least one protected binding")
    if acceptance.report_root is None or not Path(acceptance.report_root).is_absolute():
        raise ActionAcceptanceError("AcceptanceSpec report_root must be absolute")
    if Path(acceptance.report_root).resolve() != spec.report_root:
        raise ActionAcceptanceError("AcceptanceSpec report_root must equal exact external report_root")

    bridge_sha = sha256_bytes(Path(__file__).read_bytes())
    base_integration_fingerprint = sha256_bytes(
        canonical_json(
            {
                "integration_spec_sha256": spec.source_sha256,
                "integration_version": spec.integration_version,
                "task_id": spec.task_id,
                "project_root": str(spec.project_root),
                "report_root": str(spec.report_root),
                "timeout_seconds": spec.timeout_seconds,
                "output_budget": spec.output_budget,
                "bridge_sha256": bridge_sha,
                "validator_sha256": spec.validator.sha256,
                "validator_context_sha256": spec.validator_context.sha256,
                "action_receipt_sha256": spec.action_receipt.sha256,
                "authority_binding_sha256": spec.authority_binding.sha256,
                "acceptance_spec_sha256": spec.acceptance_spec.sha256,
            }
        )
    )

    def result_identity(stage: str, *, acceptance_execution_identity: str | None = None) -> str:
        value: dict[str, Any] = {
            "base_integration_fingerprint": base_integration_fingerprint,
            "stage": stage,
        }
        if acceptance_execution_identity is not None:
            value["acceptance_execution_identity"] = acceptance_execution_identity
        return sha256_bytes(canonical_json(value))

    def result_path(integration_fingerprint: str) -> Path:
        return spec.report_root / f"{integration_fingerprint}.action.result.json"

    def load_replay(
        integration_fingerprint: str,
        expected_report: dict[str, Any],
    ) -> ActionAcceptanceReport | None:
        path = result_path(integration_fingerprint)
        if not path.exists():
            return None
        if not path.is_file():
            raise ActionAcceptanceError("invalid prior integration publication")
        envelope = _load_json(path)
        prior = envelope.get("report")
        prior_receipt = envelope.get("receipt")
        if not isinstance(prior, dict) or not isinstance(prior_receipt, dict):
            raise ActionAcceptanceError("stale or tampered prior integration report")
        actual_report_sha = sha256_bytes(canonical_json(prior))
        expected_identity_fields = (
            "result",
            "task_id",
            "integration_fingerprint",
            "base_integration_fingerprint",
            "integration_spec_sha256",
            "acceptance_execution_identity",
            "acceptance_idempotency_key",
        )
        if any(prior.get(k) != expected_report.get(k) for k in expected_identity_fields):
            raise ActionAcceptanceError("stale or tampered prior integration report")
        if (
            prior_receipt.get("task_id") != spec.task_id
            or prior_receipt.get("integration_fingerprint") != integration_fingerprint
            or prior_receipt.get("base_integration_fingerprint") != base_integration_fingerprint
            or prior_receipt.get("integration_spec_sha256") != spec.source_sha256
            or prior_receipt.get("report_sha256") != actual_report_sha
            or prior_receipt.get("result") != prior.get("result")
            or prior_receipt.get("acceptance_execution_identity") != expected_report.get("acceptance_execution_identity")
            or prior_receipt.get("acceptance_idempotency_key") != expected_report.get("acceptance_idempotency_key")
        ):
            raise ActionAcceptanceError("stale or tampered prior integration report")
        returned = dict(prior)
        returned["idempotent_replay"] = "YES"
        returned["integration_result_path"] = str(path)
        returned["integration_result_sha256"] = sha256_bytes(path.read_bytes())
        returned["integration_report_sha256"] = actual_report_sha
        return ActionAcceptanceReport(returned)

    def persist_new(integration_fingerprint: str, report: dict[str, Any]) -> ActionAcceptanceReport:
        path = result_path(integration_fingerprint)
        replay = load_replay(integration_fingerprint, report)
        if replay is not None:
            return replay
        report_sha = sha256_bytes(canonical_json(report))
        envelope = {
            "report": report,
            "receipt": {
                "task_id": spec.task_id,
                "integration_fingerprint": integration_fingerprint,
                "base_integration_fingerprint": base_integration_fingerprint,
                "integration_spec_sha256": spec.source_sha256,
                "acceptance_execution_identity": report.get("acceptance_execution_identity"),
                "acceptance_idempotency_key": report.get("acceptance_idempotency_key"),
                "report_sha256": report_sha,
                "result": report.get("result"),
            },
        }
        envelope_sha = _atomic_json(path, envelope)
        returned = dict(report)
        returned["integration_result_path"] = str(path)
        returned["integration_result_sha256"] = envelope_sha
        returned["integration_report_sha256"] = report_sha
        return ActionAcceptanceReport(returned)

    validate = validator_operation or _validator_operation
    validation = validate(spec)
    if validation.get("exit_code") != 0 or validation.get("timeout"):
        fingerprint = result_identity("ACTION_COMPILE_VALIDATOR_FAILED")
        return persist_new(
            fingerprint,
            {
                "result": "STOP",
                "reason": "ACTION_COMPILE_VALIDATOR_FAILED",
                "task_id": spec.task_id,
                "integration_fingerprint": fingerprint,
                "base_integration_fingerprint": base_integration_fingerprint,
                "integration_spec_sha256": spec.source_sha256,
                "acceptance_execution_identity": None,
                "acceptance_idempotency_key": None,
                "validator_operation": validation,
                "acceptance_executed": "NO",
            },
        )
    try:
        validator_stdout = json.loads(validation["stdout"]["text"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ActionAcceptanceError("validator stdout is not exact JSON") from exc
    if (
        validator_stdout.get("validation_result") != "PASS"
        or validator_stdout.get("contract_errors")
        or validator_stdout.get("blockers")
    ):
        fingerprint = result_identity("ACTION_COMPILE_NOT_LEGAL")
        return persist_new(
            fingerprint,
            {
                "result": "STOP",
                "reason": "ACTION_COMPILE_NOT_LEGAL",
                "task_id": spec.task_id,
                "integration_fingerprint": fingerprint,
                "base_integration_fingerprint": base_integration_fingerprint,
                "integration_spec_sha256": spec.source_sha256,
                "acceptance_execution_identity": None,
                "acceptance_idempotency_key": None,
                "validator_result": validator_stdout,
                "acceptance_executed": "NO",
            },
        )

    run = acceptance_runner or _run_existing_acceptance
    acceptance_report = run(acceptance).to_dict()
    identity_fields = (
        "idempotency_key",
        "spec_sha256",
        "pre_state_snapshot_sha256",
        "harness_revision_sha256",
        "toolchain_fingerprint_sha256",
    )
    missing_identity = [k for k in identity_fields if not isinstance(acceptance_report.get(k), str) or not acceptance_report.get(k)]
    if missing_identity:
        raise ActionAcceptanceError(f"Acceptance report missing current execution identity field(s): {missing_identity}")
    acceptance_identity_payload = {k: acceptance_report[k] for k in identity_fields}
    acceptance_execution_identity = sha256_bytes(canonical_json(acceptance_identity_payload))
    fingerprint = result_identity(
        "ACCEPTANCE_EXECUTED",
        acceptance_execution_identity=acceptance_execution_identity,
    )
    report = {
        "result": acceptance_report.get("result", "FAIL"),
        "task_id": spec.task_id,
        "integration_fingerprint": fingerprint,
        "base_integration_fingerprint": base_integration_fingerprint,
        "acceptance_execution_identity": acceptance_execution_identity,
        "acceptance_idempotency_key": acceptance_report["idempotency_key"],
        "acceptance_identity": acceptance_identity_payload,
        "bridge_sha256": bridge_sha,
        "integration_spec_sha256": spec.source_sha256,
        "validator_sha256": spec.validator.sha256,
        "validator_context_sha256": spec.validator_context.sha256,
        "action_receipt_sha256": spec.action_receipt.sha256,
        "authority_binding_sha256": spec.authority_binding.sha256,
        "acceptance_spec_sha256": spec.acceptance_spec.sha256,
        "report_root": str(spec.report_root),
        "validator_result": validator_stdout,
        "acceptance_executed": "YES",
        "acceptance_report": acceptance_report,
        "invariants": {
            "RUNTIME_PRODUCT_AUTHORITY_CHANGED": "NO",
            "ACCEPTANCE_HARNESS_IS_NOT_WORKFLOW_AUTHORITY": "YES",
            "NETWORK": "DENY",
            "MODEL_CALL": "DENY",
            "REPORT_ROOT_OUTSIDE_PROJECT": "YES",
            "ACCEPTANCE_CURRENTNESS_DELEGATED_TO_EXISTING_RUNNER": "YES",
            "CHANGED_ACCEPTANCE_EXECUTION_IDENTITY_CREATES_NEW_RESULT_IDENTITY": "YES",
        },
    }
    return persist_new(fingerprint, report)
