"""Runtime-owned exact-byte contract manifest checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "schemas"
MANIFEST = SCHEMAS / "runtime_contract_manifest.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_manifest(manifest: dict) -> None:
    assert manifest["schema_version"] == 1
    contracts = manifest["contracts"]
    assert "job_bundle" in contracts
    entry = contracts["job_bundle"]
    assert isinstance(entry["path"], str)
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    schemas_root = SCHEMAS.resolve()
    target = (SCHEMAS / entry["path"]).resolve()
    try:
        target.relative_to(schemas_root)
    except ValueError as exc:
        raise AssertionError("manifest path escapes schemas/") from exc
    assert target.is_file()
    assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]


def test_runtime_contract_manifest_owns_exact_job_bundle_bytes() -> None:
    _verify_manifest(_load(MANIFEST))


def test_runtime_contract_manifest_rejects_escape_missing_and_mismatch() -> None:
    manifest = _load(MANIFEST)
    for bad_path in ("..\\outside.json", "C:\\outside.json"):
        candidate = json.loads(json.dumps(manifest))
        candidate["contracts"]["job_bundle"]["path"] = bad_path
        with pytest.raises(AssertionError):
            _verify_manifest(candidate)
    missing = json.loads(json.dumps(manifest))
    missing["contracts"]["job_bundle"]["path"] = "does-not-exist.schema.json"
    with pytest.raises(AssertionError):
        _verify_manifest(missing)
    mismatched = json.loads(json.dumps(manifest))
    mismatched["contracts"]["job_bundle"]["sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        _verify_manifest(mismatched)
