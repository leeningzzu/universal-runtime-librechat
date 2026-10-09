from __future__ import annotations

import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .acceptance_models import AcceptanceReport, AcceptanceSpec, canonical_json, load_spec, sha256_bytes
from .acceptance_runner import (
    _harness_revision,
    _junit,
    _now,
    _persist,
    _run,
    _safe_env,
    _snapshot,
    _snapshot_digest,
    _toolchain_fingerprint,
    run_acceptance,
)

HARNESS_PARTITION = ("tests/test_acceptance_harness.py",)
BOOTSTRAP_POLICY = {
    "version": "1",
    "harness_partition": list(HARNESS_PARTITION),
    "runtime_exclusion": "exact_harness_partition_only",
    "phase1_command": "sys.executable -m pytest",
    "phase1_workspace": "flat_sibling_of_hashed_bootstrap_run",
    "stdin": "DEVNULL",
}


def _bootstrap_policy_revision() -> str:
    module_sha = sha256_bytes(Path(__file__).read_bytes())
    schema = Path(__file__).resolve().parents[3] / "schemas" / "bootstrap_acceptance_report.schema.json"
    schema_sha = sha256_bytes(schema.read_bytes()) if schema.exists() else None
    return sha256_bytes(canonical_json({"policy": BOOTSTRAP_POLICY, "module_sha256": module_sha, "schema_sha256": schema_sha}))


def _atomic_json(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(value)
    fd, tmp = tempfile.mkstemp(prefix=".bootstrap-", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)
    return sha256_bytes(data)


def _receipt(report_path: Path, report: dict[str, Any], root: Path) -> tuple[Path, str]:
    report_sha = sha256_bytes(report_path.read_bytes())
    receipt_path = report_path.with_suffix(".receipt.json")
    receipt = {"task_id": report["task_id"], "spec_sha256": report["spec_sha256"], "pre_state_sha256": report["pre_state_sha256"], "harness_revision_sha256": report["harness_revision_sha256"], "bootstrap_policy_revision": report["bootstrap_policy_revision"], "report_sha256": report_sha, "result": report["result"], "idempotency_key": report["idempotency_key"]}
    return receipt_path, _atomic_json(receipt_path, receipt)


def _phase1_workspace(run_root: Path) -> Path:
    key_prefix = run_root.name.split(".", 1)[0][:12]
    workspace = run_root.parent / f".phase1-{key_prefix}"
    workspace.mkdir(parents=False, exist_ok=False)
    return workspace


def _phase1(spec: AcceptanceSpec, run_root: Path) -> tuple[dict[str, Any], Path, str]:
    workspace = _phase1_workspace(run_root)
    temp_root, cache_root, pycache_root, basetemp = (workspace / x for x in ("temp", "pytest_cache", "pycache", "pytest_basetemp"))
    for p in (temp_root, cache_root, pycache_root, basetemp): p.mkdir(parents=True, exist_ok=True)
    env = _safe_env(); env.update({"TEMP": str(temp_root), "TMP": str(temp_root), "PYTHONPYCACHEPREFIX": str(pycache_root), "PYTHONDONTWRITEBYTECODE": "1"})
    junit = run_root / "harness_self_test.xml"
    argv = [os.fspath(__import__("sys").executable), "-m", "pytest", "-q", HARNESS_PARTITION[0], f"--junitxml={junit}", f"--basetemp={basetemp}", "-o", f"cache_dir={cache_root}", f"--ignore={run_root}"]
    operation = _run(argv, Path(spec.project_root), spec.pytest.timeout_seconds, spec.output_budget, env)
    counts = _junit(junit)
    passed = bool(operation["exit_code"] == 0 and not operation["timeout"] and counts["tests"] > 0 and counts["failures"] == 0 and counts["errors"] == 0)
    result = {"result": "PASS" if passed else "FAIL", "argv": argv, "cwd": str(Path(spec.project_root).resolve()), "environment_policy": "minimal-secret-filtered-task-local", "timeout_seconds": spec.pytest.timeout_seconds, "operation": operation, "junit_xml": str(junit), "counts": counts, "phase1_workspace": str(workspace), "run_temp_root": str(temp_root), "pytest_basetemp": str(basetemp), "pytest_cache_root": str(cache_root), "pycache_root": str(pycache_root)}
    receipt_path = run_root / "harness_self_test.receipt.json"
    receipt_sha = _atomic_json(receipt_path, {"phase": "HARNESS_SELF_TEST", "result": result["result"], "report_sha256": sha256_bytes(canonical_json(result)), "counts": counts})
    result["receipt_path"] = str(receipt_path); result["receipt_sha256"] = receipt_sha
    return result, receipt_path, receipt_sha


def _reject_arbitrary_exclusions(spec: AcceptanceSpec) -> bool:
    args = (*spec.pytest.targeted_args, *spec.pytest.full_args)
    return any(a == "--ignore" or a.startswith("--ignore=") or a == "--deselect" or a.startswith("--deselect=") for a in args)


def run_bootstrap(spec_or_path: AcceptanceSpec | str | Path) -> AcceptanceReport:
    spec = load_spec(spec_or_path) if not isinstance(spec_or_path, AcceptanceSpec) else spec_or_path
    root = Path(spec.project_root).resolve(); pre = _snapshot(spec); pre_sha = _snapshot_digest(pre)
    spec_sha = sha256_bytes(canonical_json(spec.as_dict())); harness_revision = _harness_revision(root); toolchain_sha, toolchain = _toolchain_fingerprint(spec)
    policy_revision = _bootstrap_policy_revision()
    key = sha256_bytes(canonical_json({"spec_sha256": spec_sha, "pre_state_sha256": pre_sha, "harness_revision_sha256": harness_revision, "toolchain_fingerprint_sha256": toolchain_sha, "bootstrap_policy_revision": policy_revision}))
    report_root = Path(spec.report_root) if spec.report_root else root / ".acceptance_reports"; report_root = report_root if report_root.is_absolute() else root / report_root
    report_path = report_root / f"{key}.bootstrap.json"
    if report_path.exists():
        data = __import__("json").loads(report_path.read_text(encoding="utf-8")); data["idempotent_replay"] = "YES"; return AcceptanceReport(data)
    started = time.monotonic(); run_root = report_root / f"{key}.bootstrap.run"; run_root.mkdir(parents=True, exist_ok=True)
    if _reject_arbitrary_exclusions(spec):
        phase1 = {"result": "FAIL", "reason": "arbitrary test exclusion is forbidden", "counts": {"tests": 0, "failures": 1, "errors": 0, "skipped": 0}}
        phase1_receipt_sha = _atomic_json(run_root / "harness_self_test.receipt.json", phase1)
    else:
        phase1, _, phase1_receipt_sha = _phase1(spec, run_root)
    runtime_report = None; runtime_sha = None
    if phase1["result"] == "PASS":
        exclusion = f"--ignore={HARNESS_PARTITION[0]}"
        pytest_cfg = replace(spec.pytest, targeted_args=tuple(spec.pytest.targeted_args) + (exclusion,), full_args=tuple(spec.pytest.full_args) + (exclusion,))
        runtime_spec = replace(spec, pytest=pytest_cfg, report_root=str(report_root / "runtime"))
        runtime_report = run_acceptance(runtime_spec).to_dict()
        runtime_path = Path(runtime_spec.report_root) / f"{runtime_report['idempotency_key']}.json"
        if runtime_path.exists(): runtime_sha = sha256_bytes(runtime_path.read_bytes())
    else:
        runtime_report = {"result": "NOT_RUN", "reason": "HARNESS_SELF_TEST failed; Runtime Acceptance was not executed"}
    self_counts = phase1.get("counts", {}); runtime_counts = (runtime_report or {}).get("full_test_result", {}).get("counts", {})
    combined = {k: int(self_counts.get(k, 0)) + int(runtime_counts.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
    combined["passed"] = combined["tests"] - combined["failures"] - combined["errors"] - combined["skipped"]
    runtime_ok = runtime_report.get("result") == "PASS"
    result = "PASS" if phase1["result"] == "PASS" and runtime_ok else "FAIL"
    expected_exclusion = f"--ignore={HARNESS_PARTITION[0]}"
    runtime_argv = (runtime_report.get("full_test_result") or {}).get("argv", [])
    runtime_ignores = [a for a in runtime_argv if a.startswith("--ignore=")]
    partition_pass = phase1["result"] == "PASS" and expected_exclusion in runtime_ignores and all(a == expected_exclusion or a.endswith(".run") for a in runtime_ignores)
    if not partition_pass: result = "FAIL"
    report = {"report_version": "1", "task_id": spec.task_id, "spec_sha256": spec_sha, "pre_state_sha256": pre_sha, "harness_revision_sha256": harness_revision, "toolchain_fingerprint_sha256": toolchain_sha, "toolchain_fingerprint": toolchain, "bootstrap_policy_revision": policy_revision, "idempotency_key": key, "started_at": _now(), "finished_at": _now(), "duration": time.monotonic() - started, "project_root": str(root), "harness_self_test_result": phase1["result"], "harness_self_test": phase1, "harness_self_test_receipt_sha256": phase1_receipt_sha, "harness_self_tests_excluded_from_runtime_subprocess": "YES", "harness_self_tests_already_verified": "YES" if phase1["result"] == "PASS" else "NO", "runtime_test_exclusion_reason": "BOOTSTRAP_PARTITION_ALREADY_VERIFIED", "runtime_acceptance_result": runtime_report.get("result"), "runtime_acceptance_report_sha256": runtime_sha, "runtime_acceptance": runtime_report, "partition_integrity": {"harness_partition": list(HARNESS_PARTITION), "runtime_exclusion": expected_exclusion, "runtime_argv_ignores": runtime_ignores, "pass": partition_pass}, "self_test_collected": self_counts.get("tests", 0), "self_test_passed": self_counts.get("tests", 0) - self_counts.get("failures", 0) - self_counts.get("errors", 0) - self_counts.get("skipped", 0), "self_test_failed": self_counts.get("failures", 0) + self_counts.get("errors", 0), "self_test_skipped": self_counts.get("skipped", 0), "runtime_collected": runtime_counts.get("tests", 0), "runtime_passed": runtime_counts.get("tests", 0) - runtime_counts.get("failures", 0) - runtime_counts.get("errors", 0) - runtime_counts.get("skipped", 0), "runtime_failed": runtime_counts.get("failures", 0) + runtime_counts.get("errors", 0), "runtime_skipped": runtime_counts.get("skipped", 0), "combined_totals": combined, "network_policy": "DENY", "model_call_policy": "NO_MODEL_CALL", "protected_mutation": runtime_report.get("mutation_result", {"pass": phase1["result"] == "PASS"}), "result": result, "next_single_action": "RETURN_TO_CONTROLLER_CHAT_FOR_TWO_LAYER_BOOTSTRAP_ACCEPTANCE"}
    report_sha = _atomic_json(report_path, report); receipt_path, receipt_sha = _receipt(report_path, report, report_root); report["report_sha256"] = report_sha; report["receipt_sha256"] = receipt_sha
    return AcceptanceReport(report)
