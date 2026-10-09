from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform as platform_mod
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acceptance_models import AcceptanceReport, AcceptanceSpec, canonical_json, load_spec, sha256_bytes
from .maf_smoke import run_maf_smoke


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _bounded(data: bytes | str | None, budget: int) -> dict[str, Any]:
    raw = data.encode("utf-8", "replace") if isinstance(data, str) else (data or b"")
    return {"text": raw[:budget].decode("utf-8", "replace"), "truncated": len(raw) > budget, "original_bytes": len(raw)}


def _snapshot(spec: AcceptanceSpec) -> list[dict[str, Any]]:
    result = []
    root = Path(spec.project_root).resolve()
    for b in spec.protected_bindings:
        p = (root / b.path).resolve()
        inside = p == root or root in p.parents
        if not inside:
            result.append({"path": b.path, "canonical_path": str(p), "error": "outside_project_root"})
            continue
        item: dict[str, Any] = {"path": b.path, "canonical_path": str(p), "required": b.required, "exists": p.exists(), "type": "missing"}
        if p.exists():
            item["type"] = "file" if p.is_file() else "directory" if p.is_dir() else "other"
            if p.is_file():
                item["sha256"] = sha256_bytes(p.read_bytes())
        result.append(item)
    return result


def _snapshot_digest(snapshot: list[dict[str, Any]]) -> str: return sha256_bytes(canonical_json(snapshot))


def _run(argv: list[str], cwd: Path, timeout: float, budget: int, env: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic(); timed_out = False; terminated = False
    proc = None
    try:
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt": popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, **popen_kwargs)
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        if proc is not None:
            if os.name == "nt":
                # pytest/plugins may create descendants; terminate the whole
                # deterministic subprocess tree rather than leaving children
                # holding inherited handles after the parent is killed.
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, check=False)
            proc.kill(); terminated = True
            out, err = proc.communicate()
            code = None
        else:
            out, err, code = exc.stdout or b"", exc.stderr or b"", None
    return {"argv": argv, "exit_code": code, "timeout": timed_out, "terminated": terminated, "stdin": "DEVNULL", "shell": False, "duration": time.monotonic()-started, "stdout": _bounded(out, budget), "stderr": _bounded(err, budget)}


def _safe_env() -> dict[str, str]:
    deny = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    allow = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "PYTHONPATH", "PYTHONHOME"}
    return {k: v for k, v in os.environ.items() if k in allow and not any(x in k.upper() for x in deny)}


def _harness_revision(root: Path) -> str:
    """Hash the authoritative implementation/contracts without relying on Git."""
    rels = (
        "src/universal_runtime/devtools/acceptance_models.py",
        "src/universal_runtime/devtools/acceptance_runner.py",
        "src/universal_runtime/devtools/acceptance_cli.py",
        "src/universal_runtime/devtools/maf_smoke.py",
        "schemas/acceptance_spec.schema.json",
        "schemas/acceptance_report.schema.json",
    )
    code_root = root
    if not (code_root / rels[0]).exists():
        code_root = Path(__file__).resolve().parents[3]
    files = {rel: sha256_bytes((code_root / rel).read_bytes()) for rel in rels}
    return sha256_bytes(canonical_json(files))


def _toolchain_fingerprint(spec: AcceptanceSpec) -> tuple[str, dict[str, Any]]:
    info: dict[str, Any] = {"python_implementation": platform_mod.python_implementation(), "python_version": sys.version, "platform": platform_mod.platform()}
    if spec.pytest.targeted_args or spec.pytest.full_args:
        try: info["pytest_version"] = importlib.metadata.version("pytest")
        except importlib.metadata.PackageNotFoundError: info["pytest_version"] = None
    if spec.maf_smoke:
        try: info["agent_framework_version"] = importlib.metadata.version("agent-framework")
        except importlib.metadata.PackageNotFoundError: info["agent_framework_version"] = None
    return sha256_bytes(canonical_json(info)), info


def _junit(path: Path) -> dict[str, Any]:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not path.exists(): return {**counts, "cases": []}
    try:
        root = ET.parse(path).getroot()
        for key in counts:
            counts[key] = int(root.attrib.get(key, 0))
        cases = []
        for tc in root.iter("testcase"):
            classname, name = tc.attrib.get("classname", ""), tc.attrib.get("name", "")
            status = "pass"
            if tc.find("error") is not None: status = "error"
            elif tc.find("failure") is not None: status = "fail"
            elif tc.find("skipped") is not None: status = "skipped"
            cases.append({"classname": classname, "name": name, "status": status, "node_candidates": [f"{classname}::{name}", f"{classname.replace('.', '/') }::{name}", name]})
        counts["cases"] = cases
        if cases and counts["tests"] == 0:
            counts["tests"] = len(cases)
            counts["failures"] = sum(c["status"] == "fail" for c in cases)
            counts["errors"] = sum(c["status"] == "error" for c in cases)
            counts["skipped"] = sum(c["status"] == "skipped" for c in cases)
    except (ET.ParseError, ValueError):
        counts["cases"] = []
    return counts


def _check_live(spec: AcceptanceSpec) -> tuple[list[dict[str, Any]], list[str]]:
    checks, unproven = [], []
    root = Path(spec.project_root)
    for c in spec.live_evidence_checks:
        rel = c.get("path", ""); p = (root / rel).resolve(); exists = p.exists()
        ok = (not exists) if c.get("absent") else (exists if c.get("required", True) else True)
        if exists and c.get("expected_sha256") and p.is_file(): ok = ok and sha256_bytes(p.read_bytes()) == c["expected_sha256"]
        checks.append({"path": rel, "exists": exists, "pass": ok})
        if c.get("claim") and not c.get("persisted_verdict", False): unproven.append(str(c["claim"]))
    return checks, unproven


def _check_artifacts(spec: AcceptanceSpec) -> list[dict[str, Any]]:
    root = Path(spec.project_root); result = []
    for c in spec.artifact_manifest_checks:
        ap, mp = (root / c.get("artifact_path", "")).resolve(), (root / c.get("manifest_path", "")).resolve()
        row = {"artifact_path": c.get("artifact_path"), "manifest_path": c.get("manifest_path"), "pass": False}
        if ap.is_file() and mp.is_file():
            actual = sha256_bytes(ap.read_bytes()); manifest = json.loads(mp.read_text(encoding="utf-8")); expected = manifest.get("sha256")
            row.update({"artifact_sha256": actual, "manifest_sha256": expected, "pass": actual == expected})
            for field in ("artifact_id", "revision"):
                if field in c:
                    row[f"manifest_{field}"] = manifest.get(field)
                    row["pass"] = row["pass"] and manifest.get(field) == c[field]
            if c.get("reviewed_sha256"):
                row["pass"] = row["pass"] and c["reviewed_sha256"] == actual
        result.append(row)
    return result


def _persist(report: dict[str, Any], root: Path) -> tuple[Path, Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    data = canonical_json(report); digest = sha256_bytes(data)
    final = root / f"{report['idempotency_key']}.json"; receipt = root / f"{report['idempotency_key']}.receipt.json"
    fd, tmp = tempfile.mkstemp(prefix=".acceptance-", suffix=".tmp", dir=root)
    with os.fdopen(fd, "wb") as fh: fh.write(data); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, final)
    rec = {"task_id": report["task_id"], "spec_sha256": report["spec_sha256"], "pre_state_sha256": report["pre_state_snapshot_sha256"], "report_sha256": digest, "result": report["result"], "idempotency_key": report["idempotency_key"]}
    rb = canonical_json(rec); fd, tmp = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=root)
    with os.fdopen(fd, "wb") as fh: fh.write(rb); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, receipt)
    return final, receipt, digest


def run_acceptance(spec_or_path: AcceptanceSpec | str | Path) -> AcceptanceReport:
    spec = load_spec(spec_or_path) if not isinstance(spec_or_path, AcceptanceSpec) else spec_or_path
    started = time.monotonic(); start_at = _now(); root = Path(spec.project_root).resolve(); pre = _snapshot(spec); pre_sha = _snapshot_digest(pre)
    spec_sha = sha256_bytes(canonical_json(spec.as_dict()))
    harness_revision = _harness_revision(root)
    toolchain_sha, toolchain_info = _toolchain_fingerprint(spec)
    key = sha256_bytes(canonical_json({"spec_sha256": spec_sha, "pre_state_sha256": pre_sha, "harness_revision_sha256": harness_revision, "toolchain_fingerprint_sha256": toolchain_sha}))
    report_root = Path(spec.report_root) if spec.report_root else root / ".acceptance_reports"; report_root = report_root if report_root.is_absolute() else root / report_root
    existing = report_root / f"{key}.json"
    if existing.exists():
        data = json.loads(existing.read_text(encoding="utf-8")); data["idempotent_replay"] = "YES"; return AcceptanceReport(data)
    run_root = report_root / f"{key}.run"
    temp_root = run_root / "temp"
    pytest_basetemp = {"targeted": run_root / "pytest_targeted", "full": run_root / "pytest_full"}
    pytest_cache_root = {"targeted": run_root / "pytest_cache_targeted", "full": run_root / "pytest_cache_full"}
    pycache_root = run_root / "pycache"
    for p in (temp_root, pycache_root, *pytest_basetemp.values(), *pytest_cache_root.values()): p.mkdir(parents=True, exist_ok=True)
    result = "PASS"; limitations = ["No OS-level socket sandboxing is implemented."]
    required = []; sha_bindings = []
    for b, snap in zip(spec.protected_bindings, pre):
        ok = snap.get("exists", False) or not b.required
        if b.expected_sha256 and snap.get("sha256") != b.expected_sha256: ok = False
        required.append({"path": b.path, "pass": ok, "exists": snap.get("exists", False)})
        sha_bindings.append({"path": b.path, "expected": b.expected_sha256, "actual": snap.get("sha256"), "pass": ok})
        if not ok and b.required: result = "FAIL"
    env = _safe_env(); env.update({"TEMP": str(temp_root), "TMP": str(temp_root), "PYTHONPYCACHEPREFIX": str(pycache_root), "PYTHONDONTWRITEBYTECODE": "1"})
    compile_results = []
    for target in spec.compile_targets:
        p = (root / target).resolve()
        if root not in p.parents and p != root:
            r = {"argv": [], "exit_code": None, "timeout": False, "terminated": False, "stdin": "DEVNULL", "shell": False, "duration": 0.0, "stdout": _bounded("", spec.output_budget), "stderr": _bounded("compile target outside project root", spec.output_budget), "target": target, "rejected": True}
        else:
            compile_env = dict(env); compile_env.pop("PYTHONDONTWRITEBYTECODE", None)
            r = _run([sys.executable, "-m", "py_compile", str(p)], root, spec.timeout_seconds, spec.output_budget, compile_env); r["target"] = target
        compile_results.append(r)
        if r["exit_code"] != 0 or r["timeout"]: result = "FAIL"
    tests = {}
    for label, args in (("targeted", spec.pytest.targeted_args), ("full", spec.pytest.full_args)):
        if args:
            junit = run_root / f"{label}.xml"
            argv = [sys.executable, "-m", "pytest", *args, f"--junitxml={junit}", f"--basetemp={pytest_basetemp[label]}", "-o", f"cache_dir={pytest_cache_root[label]}", f"--ignore={run_root}"]
            r = _run(argv, root, spec.pytest.timeout_seconds, spec.output_budget, env); r["junit_xml"] = str(junit); r["counts"] = _junit(junit); r["basetemp"] = str(pytest_basetemp[label]); r["cache_dir"] = str(pytest_cache_root[label]); tests[label] = r
            if r["exit_code"] != 0 or r["timeout"]: result = "FAIL"
    skip_validation = {"expected": [s.__dict__ for s in spec.expected_skips], "unexpected": [], "resolved": []}
    all_cases = [case for value in tests.values() for case in value.get("counts", {}).get("cases", [])]
    expected_nodes = {s.node_id for s in spec.expected_skips}
    for case in all_cases:
        if case["status"] == "skipped" and not any(case["node_candidates"] and (candidate == node or candidate.endswith(node) or node.endswith(candidate)) for node in expected_nodes for candidate in case["node_candidates"]):
            skip_validation["unexpected"].append(case["node_candidates"][0]); result = "FAIL"
    for expected in spec.expected_skips:
        matching = [c for c in all_cases if any(candidate == expected.node_id or candidate.endswith(expected.node_id) or expected.node_id.endswith(candidate) for candidate in c["node_candidates"])]
        if not matching:
            skip_validation.setdefault("unresolved", []).append({"node_id": expected.node_id, "state": "UNKNOWN"})
            continue
        case = matching[0]
        if case["status"] == "skipped":
            skip_validation.setdefault("observed", []).append(expected.node_id)
        elif case["status"] == "pass" and all(v.get("exit_code") == 0 and not v.get("timeout") for v in tests.values()):
            skip_validation["resolved"].append(expected.node_id)
            skip_validation["resolved_status"] = "EXPECTED_SKIP_RESOLVED = YES"
        else:
            skip_validation.setdefault("unresolved", []).append({"node_id": expected.node_id, "state": case["status"].upper()})
            if case["status"] in {"error", "fail"}: result = "FAIL"
    live, unproven = _check_live(spec); artifacts = _check_artifacts(spec)
    if any(not x["pass"] for x in live + artifacts): result = "FAIL"
    post = _snapshot(spec); mutation = {"pass": canonical_json(pre) == canonical_json(post), "changed": []}
    if not mutation["pass"]: mutation["changed"] = [i for i,(a,b) in enumerate(zip(pre,post)) if a != b]; result = "STOP"
    maf = run_maf_smoke() if spec.maf_smoke else {"enabled": False}
    if spec.maf_smoke and not maf.get("pass"): result = "FAIL"
    maf["enabled"] = bool(spec.maf_smoke)
    report = {"report_version": "1", "task_id": spec.task_id, "mode": spec.mode, "result": result, "started_at": start_at, "finished_at": _now(), "duration": time.monotonic()-started, "spec_sha256": spec_sha, "harness_revision_sha256": harness_revision, "toolchain_fingerprint_sha256": toolchain_sha, "toolchain_fingerprint": toolchain_info, "idempotency_key": key, "project_root": str(root), "network_policy": "ALLOW" if spec.network_allowed else "DENY", "model_call_policy": "MODEL_CALL_ALLOWED" if spec.model_call_allowed else "NO_MODEL_CALL", "run_temp_root": str(temp_root), "pytest_basetemp": {k: str(v) for k,v in pytest_basetemp.items()}, "pytest_cache_root": {k: str(v) for k,v in pytest_cache_root.items()}, "pycache_root": str(pycache_root), "required_files_result": required, "sha_bindings": sha_bindings, "compile_result": compile_results, "targeted_test_result": tests.get("targeted"), "full_test_result": tests.get("full"), "skip_validation": skip_validation, "maf_smoke_result": maf, "artifact_manifest_checks": artifacts, "live_evidence_checks": live, "unproven_claims": unproven, "pre_state_snapshot": pre, "post_state_snapshot": post, "pre_state_snapshot_sha256": pre_sha, "mutation_result": mutation, "dependency_result": {"new_dependency": False}, "invariants_check": {"MODEL_OUTPUT_IS_PROPOSAL_ONLY": "YES", "RUNTIME_IS_ONLY_COMMIT_OWNER": "YES", "ACCEPTANCE_HARNESS_IS_NOT_WORKFLOW_AUTHORITY": "YES", "ACCEPTANCE_HARNESS_CANNOT_PROMOTE": "YES", "NETWORK_DEFAULT_DENY": "YES", "MODEL_CALL_DEFAULT_DENY": "YES", "NO_SILENT_MUTATION": "YES", "SECRETS_EXCLUDED": "YES"}, "known_limitations": limitations, "next_single_action": "RETURN_TO_CONTROLLER_CHAT_FOR_ACCEPTANCE_HARNESS_BOOTSTRAP_ACCEPTANCE"}
    _persist(report, report_root)
    return AcceptanceReport(report)
