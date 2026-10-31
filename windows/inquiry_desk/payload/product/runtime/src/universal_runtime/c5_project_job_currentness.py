"""C5 scoped *read-only* Job membership via existing Runtime immutable owners.

Reuse the current JobAuthority initial JAE -> exact immutable formal intake
and input-set provenance; never infer Project membership from Job IDs, capability
IDs, process counts or a synthetic pending disposition.

This is one factual input to C5 admission. It never grants writer ownership,
backup readiness, active-model cancellation or deletion permission.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from universal_runtime.running_job_currentness import (
    RunningJobPinCurrentnessProjection,
    RunningJobPinCurrentnessProjector,
    RUNNING_JOB_CURRENTNESS_CONTRACT,
)
from universal_runtime.core.formal_model_job import FormalModelJobError


_PROJECT = re.compile(r"^PRJ_[A-Za-z0-9_]{8,128}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class C5ProjectJobCurrentnessStop(RuntimeError):
    pass


def _require(valid: bool, code: str) -> None:
    if not valid:
        raise C5ProjectJobCurrentnessStop(code)


def _exact_binding(source: dict[str, Any], prefix: str) -> dict[str, Any]:
    value = {
        "artifact_identity_sha256": source.get(prefix + "_artifact_identity_sha256"),
        "artifact_revision": source.get(prefix + "_artifact_revision"),
        "artifact_sha256": source.get(prefix + "_artifact_sha256"),
    }
    _require(
        isinstance(value["artifact_identity_sha256"], str)
        and bool(_SHA.fullmatch(value["artifact_identity_sha256"]))
        and type(value["artifact_revision"]) is int
        and value["artifact_revision"] >= 1
        and isinstance(value["artifact_sha256"], str)
        and bool(_SHA.fullmatch(value["artifact_sha256"])),
        "C5_JOB_EXACT_INTAKE_ARTIFACT_BINDING_INVALID",
    )
    return value


def _source_identity(sources: list[dict[str, Any]]) -> str:
    fingerprints = [
        (item.get("job_id"), item.get("job_authority_event_id"),
         item.get("web_formal_job_intake_artifact_sha256"),
         item.get("input_set_artifact_sha256"))
        for item in sources
    ]
    return sha256(
        json.dumps(fingerprints, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


def project_scoped_job_facts(
    *,
    target_project_id: str,
    initial_sources: list[dict[str, Any]],
    projection: RunningJobPinCurrentnessProjection,
    formal_ledger: Any,
    job_authority: Any,
) -> dict[str, Any]:
    """Consume a fully validated first-party Runtime projection, never grant effect."""
    _require(
        isinstance(target_project_id, str) and bool(_PROJECT.fullmatch(target_project_id)),
        "C5_CURRENT_TARGET_LOGICAL_PROJECT_ID_INVALID",
    )
    _require(isinstance(projection, RunningJobPinCurrentnessProjection),
             "C5_EXACT_RUNTIME_JOB_CURRENTNESS_PROJECTION_REQUIRED")
    _require(isinstance(initial_sources, list), "C5_EXACT_INITIAL_JOB_SOURCES_REQUIRED")
    e = projection.evidence
    _require(isinstance(e, dict), "C5_CURRENT_RUNNING_JOB_EVIDENCE_UNAVAILABLE")
    _require(
        e.get("schema_revision") == RUNNING_JOB_CURRENTNESS_CONTRACT and
        e.get("source_authority") ==
            "JOB_AUTHORITY_PLUS_FORMAL_MODEL_JOB_PLUS_HUMAN_DECISION",
        "C5_JOB_FIRST_PARTY_CURRENTNESS_SCHEMA_NOT_CONFIRMED",
    )

    labels = (
        ("running_jobs", "running_job_count"),
        ("orphaned_nonexecutable_jobs", "orphaned_nonexecutable_job_count"),
        ("terminal_jobs", "terminal_job_count"),
    )
    rows: dict[str, list[dict[str, Any]]] = {}
    for key, count_key in labels:
        items = e.get(key)
        _require(isinstance(items, list) and
                 type(e.get(count_key)) is int and
                 e[count_key] == len(items) and
                 all(isinstance(item, dict) for item in items),
                 "C5_EXACT_JOB_CURRENTNESS_ROWS_INCOMPLETE")
        rows[key] = items
    _require(len(projection.running_pins) == len(rows["running_jobs"]),
             "C5_RUNNING_PIN_MEMBERSHIP_NOT_EXACT")
    _require(type(e.get("initial_job_count")) is int and
             e["initial_job_count"] == len(initial_sources),
             "C5_INITIAL_JOB_AUTHORITY_MEMBERSHIP_CHANGED")
    _require(callable(getattr(formal_ledger, "load_record", None)) and
             callable(getattr(job_authority, "_require_initial_input_set_matches_intake", None)),
             "C5_FIRST_PARTY_JOB_PROVENANCE_READER_UNAVAILABLE")


    # The first-party Runtime projector classifies historical terminal and
    # formally nonexecutable records. Those cannot grant new execution and
    # need neither old Intake SHA nor JAE provenance repair to admit an
    # unrelated Project. Still bind all current Job IDs uniquely, and inspect
    # every potentially runnable Job against exact native Intake below.
    initial_by_job: dict[str, dict[str, Any]] = {}
    for record in initial_sources:
        _require(isinstance(record, dict), "C5_JOB_INITIAL_SOURCE_MALFORMED")
        job_id = record.get("job_id")
        _require(isinstance(job_id, str) and bool(job_id)
                 and job_id not in initial_by_job,
                 "C5_JOB_INITIAL_SOURCE_DUPLICATED_OR_UNSCOPED")
        initial_by_job[job_id] = record

    seen: set[str] = set()
    target_formally_nonterminal = 0
    protected_historical_orphans = 0
    for row_class, _ in labels:
        for row in rows[row_class]:
            job = row.get("job_id")
            initial = initial_by_job.get(job) if isinstance(job, str) else None
            _require(initial is not None and job not in seen,
                     "C5_JOB_CURRENT_TO_INITIAL_SCOPE_NOT_PROVEN")
            seen.add(job)
            if row_class == "orphaned_nonexecutable_jobs":
                _require(
                    row.get("disposition") == "ORPHANED_NONEXECUTABLE"
                    and row.get("reason_code") == "R009OpaqueArtifactError",
                    "C5_NONEXECUTABLE_HISTORY_CLASS_NOT_EXACT",
                )
                # Retain protected original history; missing Intake does not
                # imply a new execution grant or justify a Project ID guess.
                protected_historical_orphans += 1
                continue
            if row_class == "terminal_jobs":
                # This formal terminal is already validated by the projector.
                continue

            # Only potentially executable Jobs need exact JAE/Intake/source
            # binding; malformed historical terminal SHA must not block P1.
            _require(
                isinstance(initial.get("job_authority_event_id"), str)
                and bool(initial["job_authority_event_id"])
                and row.get("initial_job_authority_event_id")
                    == initial["job_authority_event_id"],
                "C5_JOB_CURRENT_TO_INITIAL_SCOPE_NOT_PROVEN",
            )
            intake_binding = _exact_binding(initial, "web_formal_job_intake")
            input_binding = _exact_binding(initial, "input_set")
            _require(
                intake_binding["artifact_sha256"]
                    == initial.get("web_formal_job_intake_binding_sha256")
                and input_binding["artifact_sha256"]
                    == initial.get("input_set_sha256"),
                "C5_CURRENT_EXECUTABLE_INITIAL_BINDING_DISAGREES",
            )
            try:
                intake = formal_ledger.load_record(intake_binding)
                input_set = formal_ledger.load_record(input_binding)
            except FormalModelJobError as exc:
                raise C5ProjectJobCurrentnessStop(
                    "C5_CURRENT_EXECUTABLE_JOB_INTAKE_UNVERIFIED"
                ) from exc
            _require(
                isinstance(intake, dict)
                and intake.get("schema") == "WEB_FORMAL_JOB_INTAKE_BINDING_V1"
                and intake.get("job_id") == job
                and intake.get("job_bundle_sha256") ==
                    initial.get("job_bundle_sha256"),
                "C5_CURRENT_EXECUTABLE_JOB_INTAKE_IDENTITY_CHANGED",
            )
            project = intake.get("project_id")
            _require(
                isinstance(project, str) and bool(_PROJECT.fullmatch(project)),
                "C5_CURRENT_EXECUTABLE_JOB_PROJECT_UNPROVEN",
            )
            try:
                job_authority._require_initial_input_set_matches_intake(
                    input_set=input_set, intake=intake,
                )
            except Exception as exc:
                raise C5ProjectJobCurrentnessStop(
                    "C5_RUNTIME_INTAKE_PROVENANCE_NOT_MATCHED"
                ) from exc
            if project == target_project_id:
                target_formally_nonterminal += 1

    _require(seen == set(initial_by_job),
             "C5_JOB_INITIAL_LINEAGE_NOT_FULLY_CLASSIFIED")
    return {
        "schema": "AIDES_C5_PROJECT_JOB_SCOPE_FROM_NATIVE_AUTHORITY_R001",
        "source": "RUNTIME_JOB_AUTHORITY_FORMAL_INTAKE_INPUT_SET_CURRENTNESS",
        "logical_project_id": target_project_id,
        "initial_membership_sha256": _source_identity(initial_sources),
        "running_projection_sha256": projection.evidence_sha256(),
        # Formal pending is not necessarily a currently running OS process.
        # Conservatively hold target-owned pending until a first-party
        # executor-effect fence positively excludes write/replay effects.
        "project_active_pinned_jobs": target_formally_nonterminal,
        "project_unresolved_nonexecutable_jobs": 0,
        "project_terminal_history_scope": "NOT_EVALUATED_NOT_DELETE_RELEVANT",
        "global_active_pinned_jobs": len(rows["running_jobs"]),
        "global_unresolved_jobs": len(rows["orphaned_nonexecutable_jobs"]),
        "protected_nonexecutable_history_without_project_scope":
            protected_historical_orphans,
        "unscoped_historical_job_project_ids": "NOT_RECOVERABLE_DO_NOT_INFER",
        "scope_verified": True,
        "project_effect_safe_from_job_history": target_formally_nonterminal == 0,
        "writer_exclusivity_proven": False,
        "backup_restore_proven": False,
        "delete_permitted": False,
    }


def read_current_project_job_scope(*, project_id: str, job_authority: Any,
                                   formal_ledger: Any) -> dict[str, Any]:
    """Use current installed first-party projector twice to detect job races."""
    owner = RunningJobPinCurrentnessProjector(
        job_authority=job_authority, formal_ledger=formal_ledger
    )
    initial = owner._initial_sources()
    projection = owner.project()
    facts = project_scoped_job_facts(
        target_project_id=project_id, initial_sources=initial,
        projection=projection, formal_ledger=formal_ledger,
        job_authority=job_authority
    )
    # This does not stop other writers. It rejects source admission when Job
    # currentness changes during the read, then requires a point-of-effect
    # fresh read as part of the separately approved C5 writer/backup fence.
    latest = owner.project()
    _require(latest.evidence_sha256() == facts["running_projection_sha256"] and
             _source_identity(owner._initial_sources()) == facts["initial_membership_sha256"],
             "C5_RUNTIME_JOB_CURRENTNESS_CHANGED_WHILE_READING")
    return facts
