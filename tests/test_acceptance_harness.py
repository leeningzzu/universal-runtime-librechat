from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from universal_runtime.devtools.acceptance_models import AcceptanceSpec, canonical_json, load_spec
from universal_runtime.devtools.acceptance_runner import run_acceptance


def _spec(root: Path, **kw):
    data = {"spec_version": "1", "task_id": "TEST", "mode": "STATIC_ACCEPTANCE", "project_root": str(root), "output_budget": 32}
    data.update(kw)
    return AcceptanceSpec.from_dict(data)


def test_valid_spec_and_unknown_field_rejected(tmp_path):
    s = _spec(tmp_path)
    assert s.network_allowed is False and s.model_call_allowed is False
    with pytest.raises(ValueError): AcceptanceSpec.from_dict({**s.as_dict(), "unexpected": 1})


def test_bad_sha_rejected(tmp_path):
    with pytest.raises(ValueError): _spec(tmp_path, protected_bindings=[{"path": "x", "expected_sha256": "BAD"}])


def test_compile_and_missing_required_file(tmp_path):
    target = tmp_path / "ok.py"; target.write_text("x = 1\n", encoding="utf-8")
    report = run_acceptance(_spec(tmp_path, compile_targets=["ok.py"], protected_bindings=[{"path": "ok.py", "expected_sha256": __import__('hashlib').sha256(target.read_bytes()).hexdigest()}], report_root="reports"))
    assert report.data["result"] == "PASS"
    assert Path(report.data["run_temp_root"]).is_dir()
    assert Path(report.data["pycache_root"]).is_dir()
    assert not (tmp_path / "__pycache__").exists()


def test_pytest_isolation_paths_are_task_local(tmp_path):
    (tmp_path / "nested_test.py").write_text("def test_nested():\n    assert 'ACCEPTANCE_NESTED_OK' == 'ACCEPTANCE_NESTED_OK'\n", encoding="utf-8")
    report = run_acceptance(_spec(tmp_path, pytest={"full_args": ["-q", "nested_test.py::test_nested"]}, report_root="reports"))
    run_root = Path(report.data["run_temp_root"]).parent
    assert str(run_root) in report.data["full_test_result"]["basetemp"]
    assert str(run_root) in report.data["full_test_result"]["cache_dir"]
    assert any(arg.startswith("--basetemp=") for arg in report.data["full_test_result"]["argv"])
    assert report.data["full_test_result"]["stdin"] == "DEVNULL"
    assert report.data["full_test_result"]["shell"] is False


def test_compile_failure_and_budget(tmp_path):
    target = tmp_path / "bad.py"; target.write_text("this is not python !!!", encoding="utf-8")
    report = run_acceptance(_spec(tmp_path, compile_targets=["bad.py"], report_root="reports"))
    assert report.data["result"] == "FAIL"


def test_live_evidence_is_read_only_and_idempotent(tmp_path):
    evidence = tmp_path / "evidence"; evidence.mkdir()
    spec = _spec(tmp_path, live_evidence_checks=[{"path": "evidence", "required": True}], report_root="reports")
    first = run_acceptance(spec); second = run_acceptance(spec)
    assert first.data["result"] == "PASS" and second.data["idempotent_replay"] == "YES"


def test_canonical_json_stable():
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
