"""E9 Runtime contract identity pin boundary tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from universal_runtime.core.job_pins import JobPinError, JobRuntimeContractPin


ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "schemas"
RUNTIME_CONTRACT_MANIFEST = SCHEMAS / "runtime_contract_manifest.json"


def test_runtime_contract_pin_is_immutable_and_hashes_exact_manifest_bytes(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime_contract_manifest.json"
    raw = b'{"schema_version":1}\n'
    manifest.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()

    pin = JobRuntimeContractPin.from_manifest("job-1", manifest)

    assert pin.to_dict() == {
        "job_id": "job-1",
        "runtime_contract_manifest_sha256": expected,
    }
    assert pin.assert_current(manifest) == expected
    with pytest.raises(dataclasses.FrozenInstanceError):
        pin.runtime_contract_manifest_sha256 = "0" * 64  # type: ignore[misc]


def test_runtime_contract_pin_rejects_invalid_identity_and_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(JobPinError):
        JobRuntimeContractPin("", "a" * 64)
    for bad_sha in ("A" * 64, "a" * 63, "not-a-sha"):
        with pytest.raises(JobPinError):
            JobRuntimeContractPin("job-1", bad_sha)
    with pytest.raises(JobPinError, match="not found"):
        JobRuntimeContractPin.from_manifest("job-1", tmp_path / "missing.json")


def test_runtime_contract_pin_detects_stale_manifest_without_rebinding(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime_contract_manifest.json"
    manifest.write_bytes(b'{"schema_version":1}\n')
    pin = JobRuntimeContractPin.from_manifest("job-1", manifest)
    pinned = pin.runtime_contract_manifest_sha256

    manifest.write_bytes(b'{"schema_version":2}\n')

    with pytest.raises(JobPinError, match="stale"):
        pin.assert_current(manifest)
    assert pin.runtime_contract_manifest_sha256 == pinned


def test_job_bundle_requires_exact_runtime_contract_manifest_sha() -> None:
    schema = json.loads((SCHEMAS / "job_bundle.schema.json").read_text(encoding="utf-8"))
    field = "runtime_contract_manifest_sha256"
    assert field in schema["required"]
    assert schema["properties"][field] == {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }


def test_runtime_contract_manifest_still_owns_exact_job_bundle_bytes() -> None:
    manifest = json.loads(RUNTIME_CONTRACT_MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["contracts"]["job_bundle"]
    target = SCHEMAS / entry["path"]
    assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]
