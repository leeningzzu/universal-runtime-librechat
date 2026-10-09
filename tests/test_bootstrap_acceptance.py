from __future__ import annotations

from pathlib import Path

from universal_runtime.devtools import bootstrap_acceptance as boot
from universal_runtime.devtools.acceptance_models import AcceptanceSpec


def _spec(tmp_path: Path) -> AcceptanceSpec:
    return AcceptanceSpec.from_dict({"spec_version": "1", "task_id": "BOOT_TEST", "mode": "STATIC_ACCEPTANCE", "project_root": str(tmp_path), "report_root": "reports"})


def test_bootstrap_partition_is_exact():
    assert boot.HARNESS_PARTITION == ("tests/test_acceptance_harness.py",)
    assert boot.BOOTSTRAP_POLICY["runtime_exclusion"] == "exact_harness_partition_only"


def test_phase1_failure_blocks_runtime(tmp_path, monkeypatch):
    called = {"runtime": False}
    monkeypatch.setattr(boot, "_phase1", lambda spec, root: ({"result": "FAIL", "counts": {"tests": 1, "failures": 1, "errors": 0, "skipped": 0}}, root / "receipt.json", "a" * 64))
    monkeypatch.setattr(boot, "run_acceptance", lambda spec: called.__setitem__("runtime", True))
    report = boot.run_bootstrap(_spec(tmp_path))
    assert report.data["result"] == "FAIL"
    assert report.data["runtime_acceptance_result"] == "NOT_RUN"
    assert called["runtime"] is False


def test_arbitrary_exclusion_rejected(tmp_path):
    spec = AcceptanceSpec.from_dict({"spec_version": "1", "task_id": "BOOT_TEST", "mode": "STATIC_ACCEPTANCE", "project_root": str(tmp_path), "pytest": {"full_args": ["--ignore=tests/other.py"]}})
    assert boot._reject_arbitrary_exclusions(spec) is True

def test_phase1_workspace_is_flat_sibling_of_hashed_run(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    report_root = tmp_path / "reports"
    run_root = report_root / (("a" * 64) + ".bootstrap.run")
    run_root.mkdir(parents=True)

    def fake_run(argv, cwd, timeout, budget, env):
        return {
            "argv": argv,
            "exit_code": 1,
            "timeout": False,
            "terminated": False,
            "stdin": "DEVNULL",
            "shell": False,
            "duration": 0.0,
            "stdout": {"text": "", "truncated": False, "original_bytes": 0},
            "stderr": {"text": "", "truncated": False, "original_bytes": 0},
        }

    monkeypatch.setattr(boot, "_run", fake_run)
    phase1, _, _ = boot._phase1(spec, run_root)
    workspace = Path(phase1["phase1_workspace"])

    assert workspace.parent == report_root
    assert workspace.name == ".phase1-" + ("a" * 12)
    assert run_root not in workspace.parents
    assert str(workspace) in phase1["pytest_basetemp"]
    assert str(workspace) in phase1["pytest_cache_root"]
    assert str(workspace) in phase1["pycache_root"]


def test_phase1_workspace_collision_fails_closed(tmp_path):
    report_root = tmp_path / "reports"
    run_root = report_root / (("b" * 64) + ".bootstrap.run")
    run_root.mkdir(parents=True)
    first = boot._phase1_workspace(run_root)
    assert first.is_dir()
    with __import__("pytest").raises(FileExistsError):
        boot._phase1_workspace(run_root)

