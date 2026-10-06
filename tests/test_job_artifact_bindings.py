from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError

import pytest

import universal_runtime.core.job_artifact_bindings as bindings_module
from universal_runtime.core.enums import PersistenceClass
from universal_runtime.core.job_artifact_bindings import (
    JobArtifactBindingError,
    JobArtifactBindingPlan,
    assert_job_artifact_binding_current,
    create_job_artifact_binding_plan,
)
from universal_runtime.core.job_permissions import AuthorizedJobLoadPlan
from universal_runtime.core.job_pins import JobPackPin
from universal_runtime.core.load_plan import LoadInput, LoadPlan
from universal_runtime.core.models import ArtifactManifest


SHA_A = "a" * 64
SHA_B = "b" * 64
PACK_SHA = "c" * 64
PERMISSION_SHA = "d" * 64
LOAD_SHA = "e" * 64


def pin(job_id: str = "job-1") -> JobPackPin:
    return JobPackPin(job_id, "academic-paper", "0.1.0", PACK_SHA)


def manifest(
    artifact_id: str = "ELIGIBLE_SET",
    revision: int = 1,
    sha256: str = SHA_A,
) -> ArtifactManifest:
    return ArtifactManifest(
        artifact_id=artifact_id,
        revision=revision,
        sha256=sha256,
        path=f"C:/runtime/artifacts/{artifact_id}.json",
        persistence_class=PersistenceClass.AUDIT,
        created_at="2026-08-19T00:00:00+00:00",
        job_id="producer-job",
        input_fingerprint=None,
        metadata={},
    )


def authorized_load(
    *,
    job_id: str = "job-1",
    pack_id: str = "academic-paper",
    pack_version: str = "0.1.0",
    pack_manifest_sha256: str = PACK_SHA,
    role: str = "current_eligible_study_set",
    expected_sha256: str = SHA_A,
) -> AuthorizedJobLoadPlan:
    plan = LoadPlan.from_inputs(
        plan_id="load-1",
        project_root="C:/runtime",
        allowed_roots=("C:/runtime/artifacts",),
        required_inputs=(
            LoadInput(
                reference="C:/runtime/artifacts/ELIGIBLE_SET.json",
                role=role,
                expected_sha256=expected_sha256,
            ),
        ),
    )
    return AuthorizedJobLoadPlan(
        job_id=job_id,
        pack_id=pack_id,
        pack_version=pack_version,
        pack_manifest_sha256=pack_manifest_sha256,
        permission_plan_sha256=PERMISSION_SHA,
        load_plan_sha256=LOAD_SHA,
        load_plan=plan,
    )


def build_plan(
    *,
    selected_manifest: ArtifactManifest | None = None,
    load: AuthorizedJobLoadPlan | None = None,
):
    return create_job_artifact_binding_plan(
        job_pin=pin(),
        selected={
            "current_eligible_study_set": selected_manifest or manifest(),
        },
        authorized_load=load,
    )


def test_exact_runtime_selected_binding_passes() -> None:
    plan = build_plan()
    current = assert_job_artifact_binding_current(
        plan,
        job_id="job-1",
        role="current_eligible_study_set",
        artifact_id="ELIGIBLE_SET",
        revision=1,
        sha256=SHA_A,
    )
    assert current.role == "current_eligible_study_set"
    assert current.artifact_id == "ELIGIBLE_SET"


def test_binding_plan_fingerprint_is_deterministic_and_role_sorted() -> None:
    first = create_job_artifact_binding_plan(
        job_pin=pin(),
        selected={
            "z_role": manifest("Z", 2, SHA_B),
            "a_role": manifest("A", 1, SHA_A),
        },
    )
    second = create_job_artifact_binding_plan(
        job_pin=pin(),
        selected={
            "a_role": manifest("A", 1, SHA_A),
            "z_role": manifest("Z", 2, SHA_B),
        },
    )
    assert first.binding_plan_sha256 == second.binding_plan_sha256
    assert [item.role for item in first.bindings] == ["a_role", "z_role"]


def test_artifact_id_mismatch_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="artifact_id is not current"):
        assert_job_artifact_binding_current(
            build_plan(),
            job_id="job-1",
            role="current_eligible_study_set",
            artifact_id="OTHER",
            revision=1,
            sha256=SHA_A,
        )


def test_revision_mismatch_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="revision is not current"):
        assert_job_artifact_binding_current(
            build_plan(),
            job_id="job-1",
            role="current_eligible_study_set",
            artifact_id="ELIGIBLE_SET",
            revision=2,
            sha256=SHA_A,
        )


def test_sha_mismatch_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="sha256 is not current"):
        assert_job_artifact_binding_current(
            build_plan(),
            job_id="job-1",
            role="current_eligible_study_set",
            artifact_id="ELIGIBLE_SET",
            revision=1,
            sha256=SHA_B,
        )


def test_missing_role_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="role not found exactly once"):
        assert_job_artifact_binding_current(
            build_plan(),
            job_id="job-1",
            role="current_synthesis_request",
            artifact_id="ELIGIBLE_SET",
            revision=1,
            sha256=SHA_A,
        )


def test_duplicate_role_construction_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="duplicate artifact binding role"):
        create_job_artifact_binding_plan(
            job_pin=pin(),
            selected=(
                ("current_eligible_study_set", manifest()),
                ("current_eligible_study_set", manifest("OTHER", 2, SHA_B)),
            ),
        )


@pytest.mark.parametrize(
    ("revision", "sha256"),
    [
        (0, SHA_A),
        (-1, SHA_A),
        (True, SHA_A),
        (1, "A" * 64),
        (1, "0" * 63),
    ],
)
def test_malformed_candidate_binding_fails_closed(revision: object, sha256: str) -> None:
    with pytest.raises(JobArtifactBindingError):
        assert_job_artifact_binding_current(
            build_plan(),
            job_id="job-1",
            role="current_eligible_study_set",
            artifact_id="ELIGIBLE_SET",
            revision=revision,  # type: ignore[arg-type]
            sha256=sha256,
        )


def test_wrong_job_id_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="job_id does not match"):
        assert_job_artifact_binding_current(
            build_plan(),
            job_id="job-2",
            role="current_eligible_study_set",
            artifact_id="ELIGIBLE_SET",
            revision=1,
            sha256=SHA_A,
        )


def test_authorized_load_identity_mismatch_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="does not match the exact JobPackPin"):
        build_plan(load=authorized_load(job_id="other-job"))


def test_authorized_load_role_sha_mismatch_fails_closed() -> None:
    with pytest.raises(JobArtifactBindingError, match="authorized_load SHA does not match"):
        build_plan(load=authorized_load(expected_sha256=SHA_B))


def test_authorized_load_matching_role_preserves_existing_fingerprints() -> None:
    plan = build_plan(load=authorized_load())
    assert plan.permission_plan_sha256 == PERMISSION_SHA
    assert plan.load_plan_sha256 == LOAD_SHA


def test_plan_change_a_to_b_changes_fingerprint_and_old_a_fails_against_b() -> None:
    old = build_plan(selected_manifest=manifest("ELIGIBLE_SET", 1, SHA_A))
    new = build_plan(selected_manifest=manifest("ELIGIBLE_SET", 2, SHA_B))
    assert old.binding_plan_sha256 != new.binding_plan_sha256
    with pytest.raises(JobArtifactBindingError, match="revision is not current"):
        assert_job_artifact_binding_current(
            new,
            job_id="job-1",
            role="current_eligible_study_set",
            artifact_id="ELIGIBLE_SET",
            revision=1,
            sha256=SHA_A,
        )


def test_plan_is_frozen_and_query_revalidates_fingerprint() -> None:
    plan = build_plan()
    with pytest.raises(FrozenInstanceError):
        plan.job_id = "other"  # type: ignore[misc]

    object.__setattr__(plan, "binding_plan_sha256", "0" * 64)
    with pytest.raises(JobArtifactBindingError, match="does not match plan content"):
        assert_job_artifact_binding_current(
            plan,
            job_id="job-1",
            role="current_eligible_study_set",
            artifact_id="ELIGIBLE_SET",
            revision=1,
            sha256=SHA_A,
        )


def test_direct_forged_plan_with_wrong_fingerprint_is_rejected() -> None:
    good = build_plan()
    with pytest.raises(JobArtifactBindingError, match="does not match plan content"):
        JobArtifactBindingPlan(
            job_id=good.job_id,
            pack_id=good.pack_id,
            pack_version=good.pack_version,
            pack_manifest_sha256=good.pack_manifest_sha256,
            permission_plan_sha256=good.permission_plan_sha256,
            load_plan_sha256=good.load_plan_sha256,
            bindings=good.bindings,
            binding_plan_sha256="0" * 64,
        )


def test_constructor_requires_exact_runtime_artifact_manifest() -> None:
    with pytest.raises(JobArtifactBindingError, match="exact Runtime ArtifactManifest"):
        create_job_artifact_binding_plan(
            job_pin=pin(),
            selected={"current_eligible_study_set": object()},  # type: ignore[dict-item]
        )


def test_module_does_not_depend_on_artifactstore_latest_promotion_or_io() -> None:
    source = inspect.getsource(bindings_module)
    tree = ast.parse(source)

    forbidden_import_fragments = {
        "artifact_store",
        "promotion",
        "socket",
        "requests",
    }
    forbidden_symbols = {
        "ArtifactStore",
        "PromotionAuthority",
    }
    forbidden_calls = {
        "current_manifest",
        "next_revision",
        "glob",
        "open",
        "read_bytes",
        "write_bytes",
    }

    imported = set()
    referenced_symbols = set()
    called = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            referenced_symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced_symbols.add(node.attr)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    assert not any(
        fragment in imported_name.lower()
        for imported_name in imported
        for fragment in forbidden_import_fragments
    )
    assert forbidden_symbols.isdisjoint(referenced_symbols)
    assert forbidden_calls.isdisjoint(called)
