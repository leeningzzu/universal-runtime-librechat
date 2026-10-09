from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from universal_runtime.core.job_permissions import (
    AuthorizedJobLoadPlan,
    JobFilesystemPermissionPlan,
    JobPermissionError,
)
from universal_runtime.core.job_pins import JobPackPin
from universal_runtime.core.load_plan import LoadInput, LoadPlan
from universal_runtime.core.file_resolver import FileResolver
from universal_runtime.prompts.reference_loader import PromptReferenceError, PromptReferenceLoader


ROOT = Path(__file__).parents[1]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pin(job_id: str = "job-1") -> JobPackPin:
    return JobPackPin(job_id, "fixture", "1.0.0", "a" * 64)


def plan(root: Path, reference: str, expected: str | None, *, allowed_roots: tuple[str, ...] | None = None, required: bool = True) -> LoadPlan:
    return LoadPlan.from_inputs(
        plan_id="load-1",
        project_root=str(root),
        allowed_roots=allowed_roots or (str(root),),
        required_inputs=(LoadInput(reference=reference, role="prompt", expected_sha256=expected, required=required),),
    )


def test_exact_pin_binding_and_immutability(tmp_path: Path) -> None:
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [tmp_path, tmp_path])
    assert permission.job_id == "job-1"
    assert permission.pack_id == "fixture"
    assert permission.pack_version == "1.0.0"
    assert permission.pack_manifest_sha256 == "a" * 64
    assert permission.allowed_read_roots == (str(tmp_path.resolve()),)
    with pytest.raises(Exception):
        permission.job_id = "other"  # type: ignore[misc]


def test_pack_permission_strings_are_not_filesystem_grants(tmp_path: Path) -> None:
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [])
    with pytest.raises(PermissionError):
        permission.require_read(tmp_path / "prompt.md")


def test_roots_are_absolute_canonical_and_traversal_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [root / ".", root])
    assert permission.allowed_read_roots == (str(root.resolve()),)
    with pytest.raises(JobPermissionError):
        JobFilesystemPermissionPlan.from_job_pin(pin(), ["relative-root"])
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(JobPermissionError):
        permission.authorize_load_plan(pin(), plan(root, str(outside / "x.md"), "a" * 64))


def test_load_plan_roots_must_be_job_subset(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [root])
    with pytest.raises(JobPermissionError):
        permission.authorize_load_plan(pin(), plan(root, str(root / "x.md"), "a" * 64, allowed_roots=(str(outside),)))


def test_input_must_be_inside_both_scopes(tmp_path: Path) -> None:
    grant = tmp_path / "grant"; load = grant / "load"; outside = tmp_path / "outside"
    load.mkdir(parents=True); outside.mkdir()
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [grant])
    with pytest.raises(JobPermissionError):
        permission.authorize_load_plan(pin(), plan(grant, str(outside / "x.md"), "a" * 64, allowed_roots=(str(load),)))
    narrow = JobFilesystemPermissionPlan.from_job_pin(pin(), [load])
    with pytest.raises(JobPermissionError):
        narrow.authorize_load_plan(pin(), plan(grant, str(grant / "x.md"), "a" * 64, allowed_roots=(str(load),)))


def test_concrete_input_requires_lowercase_exact_sha(tmp_path: Path) -> None:
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [tmp_path])
    for expected in (None, "A" * 64, "0" * 63, "not-a-sha"):
        with pytest.raises(JobPermissionError):
            permission.authorize_load_plan(pin(), plan(tmp_path, str(tmp_path / "x.md"), expected))


def test_authorized_binding_fingerprints_are_stable_and_immutable(tmp_path: Path) -> None:
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [tmp_path])
    authorized = permission.authorize_load_plan(pin(), plan(tmp_path, str(tmp_path / "x.md"), "a" * 64))
    assert isinstance(authorized, AuthorizedJobLoadPlan)
    assert len(authorized.permission_plan_sha256) == 64
    assert len(authorized.load_plan_sha256) == 64
    assert authorized.permission_plan_sha256 == permission.fingerprint()
    with pytest.raises(Exception):
        authorized.load_plan = authorized.load_plan  # type: ignore[misc]


def test_wrong_pin_fails_closed(tmp_path: Path) -> None:
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [tmp_path])
    with pytest.raises(JobPermissionError):
        permission.authorize_load_plan(JobPackPin("job-2", "fixture", "1.0.0", "a" * 64), plan(tmp_path, "x.md", "a" * 64))
    with pytest.raises(JobPermissionError):
        permission.assert_matches_pin(JobPackPin("job-1", "fixture", "2.0.0", "a" * 64))


def test_loader_still_checks_sha_after_authorization(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"
    original = b"original\n"
    path.write_bytes(original)
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [tmp_path])
    authorized = permission.authorize_load_plan(pin(), plan(tmp_path, str(path), sha(original)))
    path.write_bytes(b"mutated\n")
    with pytest.raises(PromptReferenceError, match="SHA-256 mismatch"):
        PromptReferenceLoader(FileResolver([tmp_path])).load(str(path), sha(original), plan=authorized.load_plan)


def test_successful_existing_loader_integration(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"; data = b"valid\n"; path.write_bytes(data)
    permission = JobFilesystemPermissionPlan.from_job_pin(pin(), [tmp_path])
    authorized = permission.authorize_load_plan(pin(), plan(tmp_path, str(path), sha(data)))
    loaded = PromptReferenceLoader(FileResolver([tmp_path])).load(str(path), sha(data), plan=authorized.load_plan)
    assert loaded.content == "valid\n"


def test_job_bundle_schema_contract() -> None:
    schema = json.loads((ROOT / "schemas" / "job_bundle.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["permissions"]["required"] == ["read_roots"]
    assert schema["properties"]["permissions"]["properties"]["read_roots"]["uniqueItems"] is True
    for field in ("permission_plan_sha256", "load_plan_sha256"):
        assert field in schema["required"]
        assert schema["properties"][field]["pattern"] == "^[0-9a-f]{64}$"
