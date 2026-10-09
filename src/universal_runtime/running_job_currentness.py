from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.formal_model_job import (
    FormalModelJobLedger,
    canonical_json_bytes,
    canonical_sha256,
)
from universal_runtime.core.human_decision_authority import (
    HumanDecisionAuthority,
    HumanDecisionAuthorityError,
)
from universal_runtime.core.job_authority import JobAuthorityRegistry
from universal_runtime.core.job_pins import JobPackPin


RUNNING_JOB_CURRENTNESS_CONTRACT = "RUNTIME_RUNNING_JOB_PIN_CURRENTNESS_R001"
_INITIAL_SCHEMA = "RUNTIME_JOB_AUTHORITY_INITIAL_JAE_ISSUANCE_SOURCE_RECORD_V1"
_CONTROLLED_SCHEMA = "RUNTIME_JOB_AUTHORITY_CONTROLLED_SUCCESSOR_JAE_ISSUANCE_SOURCE_RECORD_V1"
_FROZEN_SCHEMA = "RUNTIME_S1_GENERAL_CHAT_FROZEN_BINDING_MANIFEST_V1"

_FORMAL_TERMINALS = {
    "RUNTIME_FORMAL_MODEL_RESULT_COMMIT_RECEIPT_V1": (
        "FORMAL_RESULT_COMMIT",
        "formal_result_commit_id",
        "SUCCESS",
    ),
    "RUNTIME_MODEL_ATTEMPT_FAILURE_OUTCOME_RECEIPT_V1": (
        "ATTEMPT_FAILURE_OUTCOME",
        "model_attempt_failure_outcome_receipt_id",
        "FAILURE",
    ),
    "RUNTIME_MODEL_ATTEMPT_CANCELLATION_OUTCOME_RECEIPT_V1": (
        "ATTEMPT_CANCELLATION_OUTCOME",
        "model_attempt_cancellation_outcome_receipt_id",
        "CANCEL",
    ),
}

_FORMAL_TERMINAL_FIELDS = {
    "RUNTIME_FORMAL_MODEL_RESULT_COMMIT_RECEIPT_V1": frozenset(
        {
            "schema",
            "formal_result_commit_id",
            "job_id",
            "job_bundle_sha256",
            "formal_job_execution_binding_sha256",
            "web_formal_job_intake_binding_sha256",
            "job_authority_event_id",
            "job_execution_authority_snapshot_sha256",
            "job_execution_snapshot_registration_sha256",
            "approval_decision_event_id",
            "approval_acceptance_artifact_sha256",
            "model_resolution_sha256",
            "model_execution_grant_sha256",
            "provider_execution_config_sha256",
            "model_attempt_receipt_sha256",
            "model_execution_consumption_receipt_sha256",
            "pre_request_attempt_claim_sha256",
            "result_package_artifact_identity_sha256",
            "result_package_artifact_revision",
            "result_package_artifact_sha256",
            "output_artifacts",
            "assistant_output_binding",
            "assistant_content_sha256",
            "committed_at_utc",
        }
    ),
    "RUNTIME_MODEL_ATTEMPT_FAILURE_OUTCOME_RECEIPT_V1": frozenset(
        {
            "schema",
            "model_attempt_failure_outcome_receipt_id",
            "job_id",
            "job_bundle_sha256",
            "formal_job_execution_binding_sha256",
            "model_execution_grant_sha256",
            "pre_request_attempt_claim_sha256",
            "job_authority_event_id",
            "approval_decision_event_id",
            "model_resolution_sha256",
            "provider_execution_config_sha256",
            "attempt_index",
            "claim_state",
            "failure_stage",
            "failure_code",
            "provider_request_invocation_started",
            "automatic_replay_allowed",
            "failure_observed_at_utc",
        }
    ),
    "RUNTIME_MODEL_ATTEMPT_CANCELLATION_OUTCOME_RECEIPT_V1": frozenset(
        {
            "schema",
            "model_attempt_cancellation_outcome_receipt_id",
            "job_id",
            "job_bundle_sha256",
            "formal_job_execution_binding_sha256",
            "model_execution_grant_sha256",
            "pre_request_attempt_claim_sha256",
            "job_authority_event_id",
            "approval_decision_event_id",
            "model_resolution_sha256",
            "provider_execution_config_sha256",
            "attempt_index",
            "claim_state",
            "cancellation_code",
            "cancellation_winner",
            "provider_request_invocation_started",
            "stream_close_observation",
            "partial_output_persisted",
            "retry_allowed",
            "automatic_replay_allowed",
            "claim_refund_allowed",
            "cancellation_observed_at_utc",
        }
    ),
}

_FAILURE_CODES = {
    "CURRENTNESS_REVALIDATION": "CLAIM_CONSUMED_REQUEST_BLOCKED_STALE",
    "CREDENTIAL_RESOLUTION": "ATTEMPT_CLAIMED_CREDENTIAL_RESOLUTION_FAILED",
    "PROVIDER_REQUEST": "ATTEMPT_CLAIMED_PROVIDER_REQUEST_FAILED",
    "PROVIDER_RESULT_VALIDATION": "ATTEMPT_CLAIMED_PROVIDER_RESULT_VALIDATION_FAILED",
    "RESULT_PERSISTENCE": "ATTEMPT_CLAIMED_RESULT_PERSISTENCE_FAILED",
}

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_RAW_ID_RE = re.compile(r"^RUNTIME_OPAQUE_([0-9A-F]{64})$")


class RunningJobCurrentnessError(ValueError):
    """Fail-closed error for request-scoped running-Job currentness projection."""


def _stable_id(prefix: str, *parts: str, length: int = 24) -> str:
    body = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(body).hexdigest()[:length].upper()}"


def _identity_sha(record_type: str, record_id: str) -> str:
    return hashlib.sha256(f"M002:{record_type}:{record_id}".encode("utf-8")).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError as exc:
        raise RunningJobCurrentnessError(f"cannot inspect authority path: {path}") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _pack_identity(pin: JobPackPin) -> dict[str, Any]:
    return {
        "pack_id": pin.pack_id,
        "pack_version": pin.pack_version,
        "pack_manifest_sha256": pin.pack_manifest_sha256,
        "pack_content_manifest_sha256": pin.pack_content_manifest_sha256,
        "pack_promotion_receipt_sha256": pin.pack_promotion_receipt_sha256,
    }


@dataclass(frozen=True)
class RunningJobPinCurrentnessProjection:
    running_pins: tuple[JobPackPin, ...]
    evidence: dict[str, Any]

    def evidence_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.evidence)).hexdigest()


class RunningJobPinCurrentnessProjector:
    """Compose current running Job pins from existing immutable Runtime authorities.

    No Job registry is created. Historical JobAuthority sources are classified
    request-by-request. A Job is a running pin only when its current activated
    authority remains exactly executable and no exact terminal evidence proves
    the Job terminal.
    """

    def __init__(
        self,
        *,
        job_authority: JobAuthorityRegistry,
        formal_ledger: FormalModelJobLedger,
    ):
        if not isinstance(job_authority, JobAuthorityRegistry):
            raise RunningJobCurrentnessError("JobAuthority source surface is unavailable")
        if not isinstance(formal_ledger, FormalModelJobLedger):
            raise RunningJobCurrentnessError("FormalModelJob surface is unavailable")
        if formal_ledger.store.root != job_authority.artifact_store.root:
            raise RunningJobCurrentnessError(
                "JobAuthority and FormalModelJob must share the exact ArtifactStore root"
            )
        self.job_authority = job_authority
        self.formal_ledger = formal_ledger
        self.store = formal_ledger.store
        self.human = HumanDecisionAuthority(
            job_authority.runtime_authority_data_root,
            self.store,
            job_authority,
        )

    @staticmethod
    def _exact_source_directory(parent: Path, *, label: str) -> list[Path]:
        if not parent.exists():
            return []
        if not parent.is_dir() or _is_reparse_or_symlink(parent):
            raise RunningJobCurrentnessError(f"{label} is unavailable or redirected")
        rows: list[Path] = []
        for path in sorted(parent.iterdir(), key=lambda item: item.name):
            if _is_reparse_or_symlink(path) or not path.is_file() or path.suffix != ".json":
                raise RunningJobCurrentnessError(f"{label} contains an unexpected entry")
            rows.append(path)
        return rows

    def _initial_sources(self) -> list[dict[str, Any]]:
        parent = self.job_authority.root / "initial_jae_issuances"
        rows: list[dict[str, Any]] = []
        seen_jobs: set[str] = set()
        seen_jaes: set[str] = set()
        for path in self._exact_source_directory(parent, label="initial JobAuthority source namespace"):
            try:
                source = self.job_authority._source(
                    path,
                    _INITIAL_SCHEMA,
                    "running Job initial JAE issuance source",
                )
            except Exception as exc:
                raise RunningJobCurrentnessError(
                    "initial JobAuthority source cannot be validated"
                ) from exc
            job_id = source.get("job_id")
            jae = source.get("job_authority_event_id")
            if (
                source.get("state") != "INITIAL_JOB_AUTHORITY_EVENT_ISSUED"
                or not isinstance(job_id, str)
                or not job_id
                or not isinstance(jae, str)
                or not jae
                or job_id in seen_jobs
                or jae in seen_jaes
            ):
                raise RunningJobCurrentnessError(
                    "initial JobAuthority source identity/state is invalid or duplicated"
                )
            expected_path = self.job_authority._initial_issuance_path(job_id)
            if path.resolve() != expected_path.resolve():
                raise RunningJobCurrentnessError(
                    "initial JobAuthority source path/key mismatch"
                )
            seen_jobs.add(job_id)
            seen_jaes.add(jae)
            rows.append(source)
        return rows

    def _controlled_successors(self) -> dict[str, dict[str, Any]]:
        parent = self.job_authority.root / "controlled_successor_jae_issuances"
        by_predecessor: dict[str, dict[str, Any]] = {}
        seen_successors: set[str] = set()
        for path in self._exact_source_directory(
            parent,
            label="controlled successor JobAuthority source namespace",
        ):
            try:
                source = self.job_authority._source(
                    path,
                    _CONTROLLED_SCHEMA,
                    "running Job controlled successor issuance source",
                )
            except Exception as exc:
                raise RunningJobCurrentnessError(
                    "controlled successor JobAuthority source cannot be validated"
                ) from exc
            predecessor = source.get("predecessor_job_authority_event_id")
            successor = source.get("successor_job_authority_event_id")
            key = source.get("controlled_successor_jae_issuance_key_sha256")
            if (
                source.get("state") != "CONTROLLED_SUCCESSOR_JOB_AUTHORITY_EVENT_ISSUED"
                or not isinstance(predecessor, str)
                or not predecessor
                or not isinstance(successor, str)
                or not successor
                or predecessor in by_predecessor
                or successor in seen_successors
            ):
                raise RunningJobCurrentnessError(
                    "controlled successor lineage is invalid or ambiguous"
                )
            expected_path = self.job_authority._controlled_successor_issuance_path(key)
            if path.resolve() != expected_path.resolve():
                raise RunningJobCurrentnessError(
                    "controlled successor source path/key mismatch"
                )
            by_predecessor[predecessor] = source
            seen_successors.add(successor)
        return by_predecessor

    def _current_activated_jae(
        self,
        *,
        initial_source: dict[str, Any],
        successors: dict[str, dict[str, Any]],
    ) -> tuple[str, list[str]]:
        current = initial_source["job_authority_event_id"]
        lineage = initial_source.get("job_lineage_identity_sha256")
        chain = [current]
        seen = {current}
        while current in successors:
            source = successors[current]
            if source.get("job_lineage_identity_sha256") != lineage:
                raise RunningJobCurrentnessError(
                    "controlled successor lineage differs from initial Job lineage"
                )
            successor = source["successor_job_authority_event_id"]
            if successor in seen:
                raise RunningJobCurrentnessError("controlled successor lineage cycle")
            registration_path = self.job_authority._registration_path(successor)
            try:
                registration_state = self.job_authority._path_state(
                    registration_path,
                    label="controlled successor registration source",
                )
            except Exception as exc:
                raise RunningJobCurrentnessError(
                    "controlled successor registration source state is unavailable"
                ) from exc
            if registration_state == "ABSENT":
                break
            # A committed successor registration source marks activation. Exact
            # Artifact validity is checked separately by the execution gate.
            try:
                self.job_authority._registration_source(successor)
            except Exception as exc:
                raise RunningJobCurrentnessError(
                    "controlled successor registration source is corrupt"
                ) from exc
            current = successor
            chain.append(current)
            seen.add(current)
        return current, chain

    def _recover_current_pin(
        self,
        *,
        job_id: str,
        current_jae: str,
        active_source: dict[str, Any],
        registration: dict[str, Any],
        registration_binding: Any,
    ) -> tuple[JobPackPin, dict[str, Any]]:
        snapshot_binding = {
            "artifact_identity_sha256": registration[
                "job_execution_authority_snapshot_artifact_identity_sha256"
            ],
            "artifact_revision": registration[
                "job_execution_authority_snapshot_artifact_revision"
            ],
            "artifact_sha256": registration[
                "job_execution_authority_snapshot_artifact_sha256"
            ],
        }
        snapshot = self.formal_ledger.load_record(snapshot_binding)
        if (
            snapshot.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1"
            or snapshot.get("job_authority_event_id") != current_jae
            or active_source.get("job_execution_authority_snapshot_sha256")
            != snapshot_binding["artifact_sha256"]
        ):
            raise RunningJobCurrentnessError(
                "current JobAuthority registration/snapshot exact binding disagrees"
            )
        frozen_binding = {
            "artifact_identity_sha256": snapshot.get(
                "frozen_binding_manifest_artifact_identity_sha256"
            ),
            "artifact_revision": snapshot.get(
                "frozen_binding_manifest_artifact_revision"
            ),
            "artifact_sha256": snapshot.get(
                "frozen_binding_manifest_artifact_sha256"
            ),
        }
        frozen = self.formal_ledger.load_record(frozen_binding)
        if (
            frozen.get("schema") != _FROZEN_SCHEMA
            or frozen.get("job_id") != job_id
        ):
            raise RunningJobCurrentnessError(
                "current frozen binding manifest does not bind exact Job"
            )
        pin_payload = frozen.get("pack_pin")
        if not isinstance(pin_payload, dict):
            raise RunningJobCurrentnessError("current frozen manifest Pack pin is missing")
        if snapshot.get("pack_pin_sha256") != canonical_sha256(pin_payload):
            raise RunningJobCurrentnessError(
                "current authority snapshot Pack pin SHA differs from frozen manifest"
            )
        try:
            pin = JobPackPin(**pin_payload)
        except Exception as exc:
            raise RunningJobCurrentnessError(
                "current frozen manifest Pack pin is invalid"
            ) from exc
        if pin.job_id != job_id:
            raise RunningJobCurrentnessError(
                "current frozen manifest Pack pin Job identity mismatch"
            )
        if (
            pin.pack_content_manifest_sha256 is None
            or pin.pack_promotion_receipt_sha256 is None
        ):
            raise RunningJobCurrentnessError(
                "running Job Pack pin lacks promotion-aware exact identity"
            )
        return pin, {
            "registration_source_sha256": hashlib.sha256(
                canonical_json_bytes(active_source)
            ).hexdigest(),
            "registration_artifact_identity_sha256":
                registration_binding.artifact_identity_sha256,
            "registration_artifact_sha256": registration_binding.artifact_sha256,
            "snapshot_artifact_identity_sha256":
                snapshot_binding["artifact_identity_sha256"],
            "snapshot_artifact_sha256": snapshot_binding["artifact_sha256"],
            "frozen_manifest_artifact_identity_sha256":
                frozen_binding["artifact_identity_sha256"],
            "frozen_manifest_artifact_sha256": frozen_binding["artifact_sha256"],
        }

    @staticmethod
    def _formal_terminal_identity(record: dict[str, Any]) -> tuple[str, str] | None:
        spec = _FORMAL_TERMINALS.get(record.get("schema"))
        if spec is None:
            return None
        record_type, id_field, disposition = spec
        expected_fields = _FORMAL_TERMINAL_FIELDS.get(record.get("schema"))
        if expected_fields is None or frozenset(record) != expected_fields:
            return None
        record_id = record.get(id_field)
        job_id = record.get("job_id")
        bundle_sha = record.get("job_bundle_sha256")
        jae = record.get("job_authority_event_id")
        if (
            not isinstance(record_id, str)
            or not record_id
            or not isinstance(job_id, str)
            or not job_id
            or not _is_sha(bundle_sha)
            or not isinstance(jae, str)
            or not jae
        ):
            return None
        if disposition == "SUCCESS":
            sha_fields = (
                "formal_job_execution_binding_sha256",
                "web_formal_job_intake_binding_sha256",
                "job_execution_authority_snapshot_sha256",
                "job_execution_snapshot_registration_sha256",
                "approval_acceptance_artifact_sha256",
                "model_resolution_sha256",
                "model_execution_grant_sha256",
                "provider_execution_config_sha256",
                "model_attempt_receipt_sha256",
                "model_execution_consumption_receipt_sha256",
                "pre_request_attempt_claim_sha256",
                "result_package_artifact_identity_sha256",
                "result_package_artifact_sha256",
                "assistant_content_sha256",
            )
            if (
                any(not _is_sha(record.get(field)) for field in sha_fields)
                or record.get("result_package_artifact_revision") != 1
                or not isinstance(record.get("output_artifacts"), list)
                or not isinstance(record.get("assistant_output_binding"), dict)
                or not isinstance(record.get("committed_at_utc"), str)
                or not record.get("committed_at_utc")
            ):
                return None
            output_binding = record["assistant_output_binding"]
            if (
                set(output_binding)
                != {"artifact_identity_sha256", "artifact_revision", "artifact_sha256"}
                or not _is_sha(output_binding.get("artifact_identity_sha256"))
                or output_binding.get("artifact_revision") != 1
                or not _is_sha(output_binding.get("artifact_sha256"))
            ):
                return None
            parts = (
                record["formal_job_execution_binding_sha256"],
                record["model_execution_grant_sha256"],
                record["pre_request_attempt_claim_sha256"],
                record["model_attempt_receipt_sha256"],
                record["model_execution_consumption_receipt_sha256"],
                record["result_package_artifact_sha256"],
            )
            expected_id = _stable_id("RESULT", job_id, *parts)
        elif disposition == "FAILURE":
            claim_sha = record.get("pre_request_attempt_claim_sha256")
            failure_stage = record.get("failure_stage")
            if (
                not _is_sha(claim_sha)
                or any(
                    not _is_sha(record.get(field))
                    for field in (
                        "formal_job_execution_binding_sha256",
                        "model_execution_grant_sha256",
                        "model_resolution_sha256",
                        "provider_execution_config_sha256",
                    )
                )
                or record.get("attempt_index") != 1
                or record.get("claim_state") != "CLAIMED_CONSUMED"
                or _FAILURE_CODES.get(failure_stage) != record.get("failure_code")
                or not isinstance(record.get("provider_request_invocation_started"), bool)
                or record.get("automatic_replay_allowed") is not False
                or not isinstance(record.get("failure_observed_at_utc"), str)
                or not record.get("failure_observed_at_utc")
            ):
                return None
            expected_id = _stable_id("ATTEMPTFAIL", job_id, claim_sha)
        else:
            claim_sha = record.get("pre_request_attempt_claim_sha256")
            winner = record.get("cancellation_winner")
            started = record.get("provider_request_invocation_started")
            close = record.get("stream_close_observation")
            if (
                not _is_sha(claim_sha)
                or any(
                    not _is_sha(record.get(field))
                    for field in (
                        "formal_job_execution_binding_sha256",
                        "model_execution_grant_sha256",
                        "model_resolution_sha256",
                        "provider_execution_config_sha256",
                    )
                )
                or record.get("attempt_index") != 1
                or record.get("claim_state") != "CLAIMED_CONSUMED"
                or record.get("cancellation_code")
                != "ATTEMPT_CLAIMED_CANCELLED_BY_USER"
                or winner not in {"CANCEL_BEFORE_REQUEST", "CANCEL_ACTIVE_STREAM"}
                or not isinstance(started, bool)
                or (
                    winner == "CANCEL_BEFORE_REQUEST"
                    and (started or close != "NOT_REQUIRED_BEFORE_REQUEST")
                )
                or (
                    winner == "CANCEL_ACTIVE_STREAM"
                    and (not started or close != "RETURNED")
                )
                or record.get("partial_output_persisted") is not False
                or record.get("retry_allowed") is not False
                or record.get("automatic_replay_allowed") is not False
                or record.get("claim_refund_allowed") is not False
                or not isinstance(record.get("cancellation_observed_at_utc"), str)
                or not record.get("cancellation_observed_at_utc")
            ):
                return None
            expected_id = _stable_id("ATTEMPTCANCEL", job_id, claim_sha)
        if record_id != expected_id:
            return None
        return _identity_sha(record_type, record_id), disposition

    def _exact_formal_terminals(
        self,
    ) -> dict[str, list[dict[str, Any]]]:
        content_root = self.store.root / "_r009_opaque_r001"
        manifest_root = self.store.root / "_manifests"
        by_job: dict[str, list[dict[str, Any]]] = {}
        if not content_root.exists():
            return by_job
        if (
            not content_root.is_dir()
            or _is_reparse_or_symlink(content_root)
            or (manifest_root.exists() and _is_reparse_or_symlink(manifest_root))
        ):
            raise RunningJobCurrentnessError(
                "FormalModelJob ArtifactStore terminal namespace is redirected"
            )
        for directory in sorted(content_root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir() or _is_reparse_or_symlink(directory):
                continue
            match = _RAW_ID_RE.fullmatch(directory.name)
            if match is None:
                continue
            identity = match.group(1).lower()
            manifest_path = manifest_root / directory.name / "R001.json"
            content_path = directory / "CONTENT.bin"
            if not manifest_path.is_file() or not content_path.is_file():
                continue
            try:
                manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                artifact_sha = manifest_payload.get("sha256")
                if not _is_sha(artifact_sha):
                    continue
                manifest, data = self.store.load_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=identity,
                    artifact_revision=1,
                    artifact_sha256=artifact_sha,
                )
                record = json.loads(data.decode("utf-8"))
                if not isinstance(record, dict) or canonical_json_bytes(record) != data:
                    continue
            except Exception:
                continue
            expected = self._formal_terminal_identity(record)
            if expected is None:
                continue
            expected_identity, disposition = expected
            if identity != expected_identity or manifest.job_id != record.get("job_id"):
                continue
            by_job.setdefault(record["job_id"], []).append(
                {
                    "disposition": disposition,
                    "schema": record["schema"],
                    "job_bundle_sha256": record["job_bundle_sha256"],
                    "job_authority_event_id": record["job_authority_event_id"],
                    "artifact_identity_sha256": identity,
                    "artifact_sha256": artifact_sha,
                }
            )
        return by_job

    def _human_sources_by_jae(self) -> dict[str, list[dict[str, Any]]]:
        parent = self.human.root / "requests"
        result: dict[str, list[dict[str, Any]]] = {}
        if not parent.exists():
            return result
        if not parent.is_dir() or _is_reparse_or_symlink(parent):
            raise RunningJobCurrentnessError(
                "HumanDecision request source namespace is unavailable or redirected"
            )
        for path in sorted(parent.iterdir(), key=lambda item: item.name):
            if _is_reparse_or_symlink(path) or not path.is_file() or path.suffix != ".json":
                raise RunningJobCurrentnessError(
                    "HumanDecision request source namespace contains an unexpected entry"
                )
            dre = path.stem
            try:
                request = self.human.load_exact_request_source(dre)
            except Exception:
                # A broken request cannot prove terminality; keeping the Job
                # running is the safe uninstall disposition.
                continue
            v3 = request.get("decision_request_binding_v3")
            jae = v3.get("job_authority_event_id") if isinstance(v3, dict) else None
            if isinstance(jae, str) and jae:
                result.setdefault(jae, []).append(request)
        return result

    def _terminal_disposition(
        self,
        *,
        job_id: str,
        current_jae: str,
        job_bundle_sha256: str,
        formal_terminals: dict[str, list[dict[str, Any]]],
        human_requests: dict[str, list[dict[str, Any]]],
        has_prepared_successor: bool,
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        formal = [
            item
            for item in formal_terminals.get(job_id, [])
            if item["job_bundle_sha256"] == job_bundle_sha256
            and item["job_authority_event_id"] == current_jae
        ]
        dispositions = sorted({item["disposition"] for item in formal})
        if len(dispositions) == 1:
            return True, f"FORMAL_{dispositions[0]}", formal
        if len(dispositions) > 1:
            return False, "AMBIGUOUS_FORMAL_TERMINAL_EVIDENCE_KEEP_RUNNING", formal

        requests = human_requests.get(current_jae, [])
        if len(requests) > 1:
            return False, "AMBIGUOUS_HUMAN_REQUESTS_KEEP_RUNNING", []
        if not requests:
            return False, "NO_EXACT_TERMINAL_KEEP_RUNNING", []
        request = requests[0]
        dre = request["decision_request_event_id"]
        try:
            terminal = self.human.load_exact_terminal_source(dre)
        except HumanDecisionAuthorityError as exc:
            if str(exc) == "terminal source absent":
                return False, "HUMAN_DECISION_PENDING_KEEP_RUNNING", []
            return False, "HUMAN_TERMINAL_UNPROVEN_KEEP_RUNNING", []
        code = terminal.get("terminal_decision_code")
        if code in {"REJECTED", "REVOKED_FOR_CONTROLLED_CANCEL"}:
            return True, f"HUMAN_{code}", [
                {
                    "decision_request_event_id": dre,
                    "terminal_decision_code": code,
                    "terminal_source_sha256": hashlib.sha256(
                        canonical_json_bytes(terminal)
                    ).hexdigest(),
                }
            ]
        if code == "SUPERSEDED_FOR_CONTROLLED_REOPEN":
            if not has_prepared_successor:
                return False, "SUPERSEDED_WITHOUT_SUCCESSOR_KEEP_RUNNING", []
            return True, "HUMAN_SUPERSEDED_FOR_CONTROLLED_REOPEN", [
                {
                    "decision_request_event_id": dre,
                    "terminal_decision_code": code,
                    "terminal_source_sha256": hashlib.sha256(
                        canonical_json_bytes(terminal)
                    ).hexdigest(),
                }
            ]
        if code == "APPROVED":
            return False, "HUMAN_APPROVED_NO_FORMAL_TERMINAL_KEEP_RUNNING", []
        return False, "UNKNOWN_HUMAN_TERMINAL_KEEP_RUNNING", []

    def project(self) -> RunningJobPinCurrentnessProjection:
        initial_sources = self._initial_sources()
        successors = self._controlled_successors()
        formal_terminals = self._exact_formal_terminals()
        human_requests = self._human_sources_by_jae()

        running: list[JobPackPin] = []
        running_rows: list[dict[str, Any]] = []
        terminal_rows: list[dict[str, Any]] = []
        orphan_rows: list[dict[str, Any]] = []

        for initial in initial_sources:
            job_id = initial["job_id"]
            current_jae, chain = self._current_activated_jae(
                initial_source=initial,
                successors=successors,
            )
            try:
                active_source, registration, registration_binding = (
                    self.job_authority.load_exact_active_registration_source_by_jae_v1(
                        job_authority_event_id=current_jae
                    )
                )
            except Exception as exc:
                orphan_rows.append(
                    {
                        "job_id": job_id,
                        "initial_job_authority_event_id":
                            initial["job_authority_event_id"],
                        "current_job_authority_event_id": current_jae,
                        "lineage_chain": chain,
                        "disposition": "ORPHANED_NONEXECUTABLE",
                        "reason_code": exc.__class__.__name__,
                    }
                )
                continue

            try:
                pin, authority_evidence = self._recover_current_pin(
                    job_id=job_id,
                    current_jae=current_jae,
                    active_source=active_source,
                    registration=registration,
                    registration_binding=registration_binding,
                )
            except Exception as exc:
                raise RunningJobCurrentnessError(
                    f"executable Job Pack pin cannot be proven: {job_id}"
                ) from exc

            job_bundle_sha = initial.get("job_bundle_sha256")
            if not _is_sha(job_bundle_sha):
                raise RunningJobCurrentnessError(
                    "initial JobAuthority source JobBundle SHA is invalid"
                )
            terminal, disposition, terminal_evidence = self._terminal_disposition(
                job_id=job_id,
                current_jae=current_jae,
                job_bundle_sha256=job_bundle_sha,
                formal_terminals=formal_terminals,
                human_requests=human_requests,
                has_prepared_successor=current_jae in successors,
            )
            row = {
                "job_id": job_id,
                "initial_job_authority_event_id": initial["job_authority_event_id"],
                "current_job_authority_event_id": current_jae,
                "lineage_chain": chain,
                "pack_pin": pin.to_dict(),
                "pack_identity": _pack_identity(pin),
                "authority_evidence": authority_evidence,
                "disposition": disposition,
                "terminal_evidence": terminal_evidence,
            }
            if terminal:
                terminal_rows.append(row)
            else:
                running.append(pin)
                running_rows.append(row)

        running.sort(key=lambda item: item.job_id)
        running_rows.sort(key=lambda item: item["job_id"])
        terminal_rows.sort(key=lambda item: item["job_id"])
        orphan_rows.sort(key=lambda item: item["job_id"])
        evidence = {
            "schema_revision": RUNNING_JOB_CURRENTNESS_CONTRACT,
            "source_authority":
                "JOB_AUTHORITY_PLUS_FORMAL_MODEL_JOB_PLUS_HUMAN_DECISION",
            "initial_job_count": len(initial_sources),
            "running_job_count": len(running_rows),
            "terminal_job_count": len(terminal_rows),
            "orphaned_nonexecutable_job_count": len(orphan_rows),
            "running_jobs": running_rows,
            "terminal_jobs": terminal_rows,
            "orphaned_nonexecutable_jobs": orphan_rows,
        }
        return RunningJobPinCurrentnessProjection(
            running_pins=tuple(running),
            evidence=evidence,
        )
