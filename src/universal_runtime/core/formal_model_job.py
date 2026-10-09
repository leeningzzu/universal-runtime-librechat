from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from universal_runtime.core.artifact_store import (
    ArtifactStore,
    R009OpaqueArtifactBinding,
    R009OpaqueArtifactError,
)
from universal_runtime.core.enums import PersistenceClass


class FormalModelJobError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_REQUIRED_AUTHORITY_FIELDS = (
    "job_authority_event_id",
    "job_execution_authority_snapshot_id",
    "job_execution_authority_snapshot_sha256",
    "job_execution_authority_snapshot_artifact_identity_sha256",
    "job_execution_authority_snapshot_artifact_revision",
    "job_execution_authority_snapshot_artifact_sha256",
    "job_execution_snapshot_registration_sha256",
    "job_execution_snapshot_registration_artifact_identity_sha256",
    "job_execution_snapshot_registration_artifact_revision",
    "job_execution_snapshot_registration_artifact_sha256",
    "decision_request_event_id",
    "decision_request_identity_sha256",
    "decision_scope_sha256",
    "approval_decision_event_id",
    "approval_decision_event_binding_sha256",
    "approval_acceptance_semantic_sha256",
    "approval_acceptance_artifact_identity_sha256",
    "approval_acceptance_artifact_revision",
    "approval_acceptance_artifact_sha256",
)

_SHA_AUTHORITY_FIELDS = frozenset(
    {
        "job_execution_authority_snapshot_sha256",
        "job_execution_authority_snapshot_artifact_identity_sha256",
        "job_execution_authority_snapshot_artifact_sha256",
        "job_execution_snapshot_registration_sha256",
        "job_execution_snapshot_registration_artifact_identity_sha256",
        "job_execution_snapshot_registration_artifact_sha256",
        "decision_request_identity_sha256",
        "decision_scope_sha256",
        "approval_decision_event_binding_sha256",
        "approval_acceptance_semantic_sha256",
        "approval_acceptance_artifact_identity_sha256",
        "approval_acceptance_artifact_sha256",
    }
)

_ATTEMPT_CLAIM_SOURCE_BOUND_FIELDS = (
    "schema",
    "attempt_claim_id",
    "job_id",
    "job_bundle_sha256",
    "formal_job_execution_binding_sha256",
    "job_model_execution_grant_sha256",
    "job_authority_event_id",
    "job_execution_authority_snapshot_sha256",
    "job_execution_snapshot_registration_sha256",
    "approval_decision_event_id",
    "approval_acceptance_artifact_sha256",
    "model_resolution_sha256",
    "provider_execution_config_sha256",
    "attempt_index",
    "claim_state",
    "consumed_live_attempts",
    "consumed_model_calls",
    "consumed_network_calls",
    "consumed_retries",
    "fallback_consumed",
)


_JOB_BUNDLE_REQUIRED_PROVENANCE_FIELDS = (
    "pack_pin",
    "runtime_contract_pin",
    "model_decision_sha256",
    "model_catalog_revision",
    "model_catalog_sha256",
    "model_resolution_sha256",
    "provider_execution_config_sha256",
    "permission_plan_sha256",
    "load_plan_sha256",
)

_ATTEMPT_CLAIM_GLOBAL_CONSUMPTION_FIELDS = (
    "schema",
    "attempt_claim_id",
    "job_id",
    "job_bundle_sha256",
    "job_model_execution_grant_sha256",
    "job_authority_event_id",
    "job_execution_authority_snapshot_sha256",
    "job_execution_snapshot_registration_sha256",
    "approval_decision_event_id",
    "approval_acceptance_artifact_sha256",
    "model_resolution_sha256",
    "provider_execution_config_sha256",
    "attempt_index",
    "claim_state",
    "consumed_live_attempts",
    "consumed_model_calls",
    "consumed_network_calls",
    "consumed_retries",
    "fallback_consumed",
)


_ATTEMPT_FAILURE_OUTCOME_FIELDS = (
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
)

_ATTEMPT_FAILURE_STAGES = frozenset(
    {
        "CURRENTNESS_REVALIDATION",
        "CREDENTIAL_RESOLUTION",
        "PROVIDER_REQUEST",
        "PROVIDER_RESULT_VALIDATION",
        "RESULT_PERSISTENCE",
    }
)


_ATTEMPT_FAILURE_CODE_BY_STAGE = {
    "CURRENTNESS_REVALIDATION": "CLAIM_CONSUMED_REQUEST_BLOCKED_STALE",
    "CREDENTIAL_RESOLUTION": "ATTEMPT_CLAIMED_CREDENTIAL_RESOLUTION_FAILED",
    "PROVIDER_REQUEST": "ATTEMPT_CLAIMED_PROVIDER_REQUEST_FAILED",
    "PROVIDER_RESULT_VALIDATION": "ATTEMPT_CLAIMED_PROVIDER_RESULT_VALIDATION_FAILED",
    "RESULT_PERSISTENCE": "ATTEMPT_CLAIMED_RESULT_PERSISTENCE_FAILED",
}


_ATTEMPT_CANCELLATION_OUTCOME_FIELDS = (
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
)

_ATTEMPT_CANCELLATION_WINNERS = frozenset({"CANCEL_BEFORE_REQUEST", "CANCEL_ACTIVE_STREAM"})
_ATTEMPT_CANCELLATION_CLOSE_OBSERVATIONS = frozenset(
    {
        "NOT_REQUIRED_BEFORE_REQUEST",
        "RETURNED",
    }
)

_FORMAL_RESULT_SOURCE_BOUND_FIELDS = (
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
)


_JOB_BUNDLE_FORBIDDEN_PRE_GRANT_KEYS = frozenset(
    {
        "job_model_execution_grant_sha256",
        "formal_job_execution_binding_sha256",
        "pre_request_attempt_claim_sha256",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stable_id(prefix: str, *parts: str, length: int = 24) -> str:
    body = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(body).hexdigest()[:length].upper()}"


def _identity_sha(record_type: str, record_id: str) -> str:
    return hashlib.sha256(f"M002:{record_type}:{record_id}".encode("utf-8")).hexdigest()


def legacy_artifact_identity_sha256(artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or not artifact_id:
        raise FormalModelJobError("INVALID_BINDING", "legacy artifact_id must be non-empty")
    return hashlib.sha256(f"LEGACY_ARTIFACT_ID:{artifact_id}".encode("utf-8")).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _require_sha(value: Any, name: str) -> str:
    if not _is_sha(value):
        raise FormalModelJobError("INVALID_SHA", f"{name} must be lowercase 64-hex")
    return value


def _require_non_empty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise FormalModelJobError("INVALID_INPUT", f"{name} must be non-empty text")
    return value


def _require_revision(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FormalModelJobError("INVALID_INPUT", f"{name} must be a positive integer")
    return value


def _binding_dict(binding: R009OpaqueArtifactBinding) -> dict[str, Any]:
    return {
        "artifact_identity_sha256": binding.artifact_identity_sha256,
        "artifact_revision": binding.artifact_revision,
        "artifact_sha256": binding.artifact_sha256,
    }


def _binding_obj(value: dict[str, Any]) -> R009OpaqueArtifactBinding:
    if not isinstance(value, dict):
        raise FormalModelJobError("INVALID_BINDING", "binding must be an object")
    try:
        return R009OpaqueArtifactBinding(
            artifact_identity_sha256=value["artifact_identity_sha256"],
            artifact_revision=value["artifact_revision"],
            artifact_sha256=value["artifact_sha256"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FormalModelJobError("INVALID_BINDING", "binding is incomplete or invalid") from exc


def _legacy_binding(value: dict[str, Any]) -> tuple[str, int, str]:
    if not isinstance(value, dict):
        raise FormalModelJobError("INVALID_BINDING", "legacy binding must be an object")
    artifact_id = _require_non_empty(value.get("artifact_id"), "artifact_id")
    revision = _require_revision(value.get("revision"), "revision")
    artifact_sha = _require_sha(value.get("sha256"), "sha256")
    return artifact_id, revision, artifact_sha


def _find_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _JOB_BUNDLE_FORBIDDEN_PRE_GRANT_KEYS:
                return key
            nested = _find_forbidden_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_forbidden_key(item)
            if nested is not None:
                return nested
    return None


_EXECUTION_AUTHORITY_FIELDS = (
    "job_authority_event_id",
    "job_execution_authority_snapshot_sha256",
    "job_execution_snapshot_registration_sha256",
    "approval_decision_event_id",
    "approval_acceptance_artifact_sha256",
)


def _assert_exact_fields(
    left: dict[str, Any],
    right: dict[str, Any],
    fields: tuple[str, ...],
    *,
    code: str,
    label: str,
) -> None:
    for field in fields:
        if left.get(field) != right.get(field):
            raise FormalModelJobError(code, f"{label} mismatch at {field}")


def _assert_authority_tuple(record: dict[str, Any], authority_binding: dict[str, Any]) -> None:
    if not isinstance(authority_binding, dict):
        raise FormalModelJobError("INVALID_AUTHORITY_BINDING", "authority_binding must be an object")
    _assert_exact_fields(
        record,
        authority_binding,
        _REQUIRED_AUTHORITY_FIELDS,
        code="AUTHORITY_BINDING_MISMATCH",
        label="authority tuple",
    )


def _validate_job_bundle_provenance(job_id: str, job_bundle: dict[str, Any]) -> None:
    for field in _JOB_BUNDLE_REQUIRED_PROVENANCE_FIELDS:
        if field not in job_bundle:
            raise FormalModelJobError(
                "JOB_BUNDLE_REQUIRED_PROVENANCE_MISSING",
                f"job_bundle missing required provenance field: {field}",
            )

    pack_pin = job_bundle["pack_pin"]
    if not isinstance(pack_pin, dict):
        raise FormalModelJobError("INVALID_PACK_PIN", "pack_pin must be an object")
    if pack_pin.get("job_id") != job_id:
        raise FormalModelJobError("INVALID_PACK_PIN", "pack_pin.job_id mismatch")
    _require_non_empty(pack_pin.get("pack_id"), "pack_pin.pack_id")
    _require_non_empty(pack_pin.get("pack_version"), "pack_pin.pack_version")
    _require_sha(pack_pin.get("pack_manifest_sha256"), "pack_pin.pack_manifest_sha256")
    content_sha = pack_pin.get("pack_content_manifest_sha256")
    promotion_sha = pack_pin.get("pack_promotion_receipt_sha256")
    if (content_sha is None) != (promotion_sha is None):
        raise FormalModelJobError(
            "INVALID_PACK_PIN",
            "promotion-aware Pack pin SHA fields must be present together",
        )
    if content_sha is not None:
        _require_sha(content_sha, "pack_pin.pack_content_manifest_sha256")
        _require_sha(promotion_sha, "pack_pin.pack_promotion_receipt_sha256")

    runtime_pin = job_bundle["runtime_contract_pin"]
    if not isinstance(runtime_pin, dict):
        raise FormalModelJobError(
            "INVALID_RUNTIME_CONTRACT_PIN",
            "runtime_contract_pin must be an object",
        )
    if runtime_pin.get("job_id") != job_id:
        raise FormalModelJobError(
            "INVALID_RUNTIME_CONTRACT_PIN",
            "runtime_contract_pin.job_id mismatch",
        )
    _require_sha(
        runtime_pin.get("runtime_contract_manifest_sha256"),
        "runtime_contract_pin.runtime_contract_manifest_sha256",
    )

    _require_sha(job_bundle["model_decision_sha256"], "model_decision_sha256")
    _require_non_empty(job_bundle["model_catalog_revision"], "model_catalog_revision")
    _require_sha(job_bundle["model_catalog_sha256"], "model_catalog_sha256")
    _require_sha(job_bundle["model_resolution_sha256"], "model_resolution_sha256")
    _require_sha(
        job_bundle["provider_execution_config_sha256"],
        "provider_execution_config_sha256",
    )
    _require_sha(job_bundle["permission_plan_sha256"], "permission_plan_sha256")
    _require_sha(job_bundle["load_plan_sha256"], "load_plan_sha256")




class FormalModelJobLedger:
    """Deterministic Runtime ledger for the reviewed M002 contract slice.

    It does not choose a Pack, own budgets, resolve secrets, or call a provider.
    """

    def __init__(self, artifact_store: ArtifactStore, *, job_authority: Any | None = None):
        self.store = artifact_store
        self.job_authority = job_authority

    def _persist_immutable(
        self,
        *,
        record_type: str,
        record_id: str,
        job_id: str,
        record: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw = canonical_json_bytes(record)
        identity = _identity_sha(record_type, record_id)
        try:
            binding, _manifest = self.store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=identity,
                artifact_bytes=raw,
                job_id=job_id,
                persistence_class=PersistenceClass.WORKING,
                expected_artifact_sha256=hashlib.sha256(raw).hexdigest(),
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("PERSIST_FAIL_CLOSED", str(exc)) from exc
        return record, _binding_dict(binding)

    def _create_once(
        self,
        *,
        record_type: str,
        record_id: str,
        job_id: str,
        record: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        raw = canonical_json_bytes(record)
        identity = _identity_sha(record_type, record_id)
        try:
            binding, _manifest, disposition, existing_bytes = (
                self.store.create_once_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=identity,
                    artifact_bytes=raw,
                    job_id=job_id,
                    persistence_class=PersistenceClass.WORKING,
                )
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("PERSIST_FAIL_CLOSED", str(exc)) from exc

        if disposition == "EXISTS":
            try:
                existing = json.loads(existing_bytes.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise FormalModelJobError("CORRUPT_EXISTING_RECORD", "existing record is invalid") from exc
            if not isinstance(existing, dict):
                raise FormalModelJobError("CORRUPT_EXISTING_RECORD", "existing record must be an object")
            return existing, _binding_dict(binding), disposition

        return record, _binding_dict(binding), disposition

    def _persist_immutable_source_bound(
        self,
        *,
        record_type: str,
        record_id: str,
        job_id: str,
        record: dict[str, Any],
        source_binding: R009OpaqueArtifactBinding,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw = canonical_json_bytes(record)
        identity = _identity_sha(record_type, record_id)
        try:
            source_manifest, _source_raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=source_binding.artifact_identity_sha256,
                artifact_revision=source_binding.artifact_revision,
                artifact_sha256=source_binding.artifact_sha256,
            )
            if source_manifest.job_id != job_id:
                raise R009OpaqueArtifactError(
                    "R009 exact source Artifact job binding mismatch"
                )
            binding, _manifest = self.store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=identity,
                artifact_bytes=raw,
                job_id=job_id,
                persistence_class=PersistenceClass.WORKING,
                expected_artifact_sha256=hashlib.sha256(raw).hexdigest(),
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("STALE_OR_TAMPERED", str(exc)) from exc
        return record, _binding_dict(binding)

    def _create_once_source_bound(
        self,
        *,
        record_type: str,
        record_id: str,
        job_id: str,
        record: dict[str, Any],
        source_binding: R009OpaqueArtifactBinding,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        raw = canonical_json_bytes(record)
        identity = _identity_sha(record_type, record_id)
        try:
            source_manifest, _source_raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=source_binding.artifact_identity_sha256,
                artifact_revision=source_binding.artifact_revision,
                artifact_sha256=source_binding.artifact_sha256,
            )
            if source_manifest.job_id != job_id:
                raise R009OpaqueArtifactError(
                    "R009 exact source Artifact job binding mismatch"
                )
            binding, _manifest, disposition, existing_bytes = (
                self.store.create_once_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=identity,
                    artifact_bytes=raw,
                    job_id=job_id,
                    persistence_class=PersistenceClass.WORKING,
                )
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("STALE_OR_TAMPERED", str(exc)) from exc

        if disposition == "EXISTS":
            try:
                existing = json.loads(existing_bytes.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise FormalModelJobError(
                    "CORRUPT_EXISTING_RECORD",
                    "existing record is invalid",
                ) from exc
            if not isinstance(existing, dict):
                raise FormalModelJobError(
                    "CORRUPT_EXISTING_RECORD",
                    "existing record must be an object",
                )
            return existing, _binding_dict(binding), disposition

        return record, _binding_dict(binding), disposition

    def load_record(self, binding: dict[str, Any]) -> dict[str, Any]:
        b = _binding_obj(binding)
        try:
            _manifest, raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=b.artifact_identity_sha256,
                artifact_revision=b.artifact_revision,
                artifact_sha256=b.artifact_sha256,
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("STALE_OR_TAMPERED", str(exc)) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FormalModelJobError("CORRUPT_RECORD", "record is not canonical JSON") from exc
        if not isinstance(value, dict):
            raise FormalModelJobError("CORRUPT_RECORD", "record must be an object")
        return value

    def persist_job_bundle(
        self,
        *,
        job_id: str,
        job_bundle: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        job_id = _require_non_empty(job_id, "job_id")
        if not isinstance(job_bundle, dict):
            raise FormalModelJobError("INVALID_JOB_BUNDLE", "job_bundle must be an object")
        if job_bundle.get("job_id") != job_id:
            raise FormalModelJobError("JOB_ID_MISMATCH", "job_bundle.job_id mismatch")

        forbidden = _find_forbidden_key(job_bundle)
        if forbidden is not None:
            raise FormalModelJobError(
                "JOB_BUNDLE_GRANT_CYCLE",
                f"immutable JobBundle must not contain pre-request field: {forbidden}",
            )

        _validate_job_bundle_provenance(job_id, job_bundle)

        record = {
            "schema": "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1",
            "job_id": job_id,
            "job_bundle": job_bundle,
            "job_bundle_sha256": canonical_sha256(job_bundle),
        }
        return self._persist_immutable(
            record_type="JOB_BUNDLE",
            record_id=job_id,
            job_id=job_id,
            record=record,
        )

    def persist_intake_binding(
        self,
        *,
        project_id: str,
        chat_id: str,
        initiating_command_id: str,
        initiating_user_event_id: str,
        initiating_user_event_binding: dict[str, Any],
        initiating_content_sha256: str,
        accepted_chat_revision: int,
        accepted_head_event_id: str,
        parent_event_id: str | None,
        job_id: str,
        job_bundle_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _require_sha(job_bundle_sha256, "job_bundle_sha256")
        _require_sha(initiating_content_sha256, "initiating_content_sha256")
        artifact_id, artifact_revision, artifact_sha = _legacy_binding(initiating_user_event_binding)
        record_id = _stable_id("INTAKE", project_id, chat_id, initiating_user_event_id, job_id)
        record = {
            "schema": "WEB_FORMAL_JOB_INTAKE_BINDING_V1",
            "web_formal_job_intake_binding_id": record_id,
            "project_id": project_id,
            "chat_id": chat_id,
            "initiating_command_id": initiating_command_id,
            "initiating_user_event_id": initiating_user_event_id,
            "initiating_user_event_artifact_id": artifact_id,
            "initiating_user_event_artifact_identity_sha256": legacy_artifact_identity_sha256(artifact_id),
            "initiating_user_event_artifact_revision": artifact_revision,
            "initiating_user_event_artifact_sha256": artifact_sha,
            "initiating_content_sha256": initiating_content_sha256,
            "accepted_chat_revision": accepted_chat_revision,
            "accepted_head_event_id": accepted_head_event_id,
            "parent_event_id": parent_event_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
        }
        return self._persist_immutable(
            record_type="WEB_INTAKE",
            record_id=record_id,
            job_id=job_id,
            record=record,
        )

    def persist_model_execution_grant(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        job_bundle_binding: dict[str, Any],
        authority_binding: dict[str, Any],
        authority_budget: dict[str, Any],
        approval_budget: dict[str, Any],
        model_resolution_sha256: str,
        provider_execution_config_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _require_sha(job_bundle_sha256, "job_bundle_sha256")
        _require_sha(model_resolution_sha256, "model_resolution_sha256")
        _require_sha(provider_execution_config_sha256, "provider_execution_config_sha256")

        job_bundle_record = self.load_record(job_bundle_binding)
        if job_bundle_record.get("schema") != "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1":
            raise FormalModelJobError("INVALID_JOB_BUNDLE", "binding is not an immutable JobBundle")
        if job_bundle_record.get("job_id") != job_id:
            raise FormalModelJobError("JOB_ID_MISMATCH", "JobBundle binding job mismatch")
        if job_bundle_record.get("job_bundle_sha256") != job_bundle_sha256:
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "Grant does not use exact committed JobBundle")
        committed_bundle = job_bundle_record.get("job_bundle")
        if not isinstance(committed_bundle, dict):
            raise FormalModelJobError("CORRUPT_RECORD", "JobBundle payload is missing")
        if committed_bundle.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError(
                "MODEL_RESOLUTION_MISMATCH",
                "Grant model resolution differs from exact JobBundle",
            )
        if committed_bundle.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError(
                "PROVIDER_CONFIG_MISMATCH",
                "Grant provider config differs from exact JobBundle",
            )
        if not isinstance(authority_binding, dict):
            raise FormalModelJobError("INVALID_AUTHORITY_BINDING", "authority_binding must be an object")

        for field in _REQUIRED_AUTHORITY_FIELDS:
            if field not in authority_binding:
                raise FormalModelJobError("INVALID_AUTHORITY_BINDING", f"missing {field}")
            if field in _SHA_AUTHORITY_FIELDS:
                _require_sha(authority_binding[field], field)
            elif field.endswith("_revision"):
                _require_revision(authority_binding[field], field)
            else:
                _require_non_empty(authority_binding[field], field)

        required_limits = {
            "live_attempts_max": 1,
            "model_calls_max": 1,
            "network_calls_max": 1,
            "retries_max": 0,
            "fallback_allowed": False,
        }
        for label, source in (("authority_budget", authority_budget), ("approval_budget", approval_budget)):
            if not isinstance(source, dict):
                raise FormalModelJobError("INVALID_BUDGET", f"{label} must be an object")
            for key, needed in required_limits.items():
                if key not in source:
                    raise FormalModelJobError("INVALID_BUDGET", f"{label} missing {key}")
                value = source[key]
                if key == "fallback_allowed":
                    if value is not False:
                        raise FormalModelJobError(
                            "BUDGET_NOT_FIRST_SLICE_ELIGIBLE",
                            f"{label}.fallback_allowed must be false",
                        )
                else:
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise FormalModelJobError("INVALID_BUDGET", f"{label}.{key} must be integer")
                    if key == "retries_max":
                        if value != 0:
                            raise FormalModelJobError(
                                "BUDGET_NOT_FIRST_SLICE_ELIGIBLE",
                                f"{label}.retries_max must be 0",
                            )
                    elif value < needed:
                        raise FormalModelJobError(
                            "BUDGET_TOO_NARROW",
                            f"{label}.{key} is below the one-attempt grant",
                        )

        grant_id = _stable_id("GRANT", job_id, job_bundle_sha256, model_resolution_sha256)
        record = {
            "schema": "RUNTIME_JOB_MODEL_EXECUTION_GRANT_V1",
            "job_model_execution_grant_id": grant_id,
            "authority_role": "DERIVED_CONSUMPTION_GRANT_ONLY",
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "job_bundle_binding_sha256": job_bundle_binding["artifact_sha256"],
            **{field: authority_binding[field] for field in _REQUIRED_AUTHORITY_FIELDS},
            "model_resolution_sha256": model_resolution_sha256,
            "provider_execution_config_sha256": provider_execution_config_sha256,
            "consumer_limits": {
                "live_attempts_limit": 1,
                "model_calls_limit": 1,
                "network_calls_limit": 1,
                "retries_limit": 0,
                "fallback_allowed": False,
            },
        }
        return self._persist_immutable(
            record_type="MODEL_GRANT",
            record_id=grant_id,
            job_id=job_id,
            record=record,
        )

    def persist_execution_binding(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        intake_binding: dict[str, Any],
        grant_binding: dict[str, Any],
        provider_execution_config_sha256: str,
        authority_binding: dict[str, Any],
        model_resolution_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        intake = self.load_record(intake_binding)
        grant = self.load_record(grant_binding)

        if intake.get("job_id") != job_id or grant.get("job_id") != job_id:
            raise FormalModelJobError("JOB_ID_MISMATCH", "intake/grant job mismatch")
        if intake.get("job_bundle_sha256") != job_bundle_sha256:
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "intake does not bind exact JobBundle")
        if grant.get("job_bundle_sha256") != job_bundle_sha256:
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "grant does not bind exact JobBundle")
        if grant.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError("MODEL_RESOLUTION_MISMATCH", "grant model resolution mismatch")
        if grant.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError("PROVIDER_CONFIG_MISMATCH", "grant provider config mismatch")

        # The detached execution binding must consume the SAME exact
        # Authority/Human-Approval tuple already source-bound into the Grant.
        _assert_authority_tuple(grant, authority_binding)

        binding_id = _stable_id(
            "EXECBIND",
            job_id,
            job_bundle_sha256,
            intake_binding["artifact_sha256"],
            grant_binding["artifact_sha256"],
            provider_execution_config_sha256,
            model_resolution_sha256,
        )
        record = {
            "schema": "RUNTIME_FORMAL_JOB_EXECUTION_BINDING_V1",
            "formal_job_execution_binding_id": binding_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "web_formal_job_intake_binding_sha256": intake_binding["artifact_sha256"],
            "job_model_execution_grant_sha256": grant_binding["artifact_sha256"],
            "provider_execution_config_sha256": provider_execution_config_sha256,
            "job_authority_event_id": grant["job_authority_event_id"],
            "job_execution_authority_snapshot_sha256": grant[
                "job_execution_authority_snapshot_sha256"
            ],
            "job_execution_snapshot_registration_sha256": grant[
                "job_execution_snapshot_registration_sha256"
            ],
            "approval_decision_event_id": grant["approval_decision_event_id"],
            "approval_acceptance_artifact_sha256": grant[
                "approval_acceptance_artifact_sha256"
            ],
            "model_resolution_sha256": model_resolution_sha256,
        }
        return self._persist_immutable(
            record_type="EXECUTION_BINDING",
            record_id=binding_id,
            job_id=job_id,
            record=record,
        )

    def claim_attempt(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        execution_binding: dict[str, Any],
        grant_binding: dict[str, Any],
        authority_binding: dict[str, Any],
        model_resolution_sha256: str,
        provider_execution_config_sha256: str,
        claimed_at_utc: str | None = None,
    ) -> dict[str, Any]:
        execution = self.load_record(execution_binding)
        grant = self.load_record(grant_binding)

        if execution.get("job_id") != job_id or grant.get("job_id") != job_id:
            raise FormalModelJobError("JOB_ID_MISMATCH", "execution/grant job mismatch")
        if execution.get("job_bundle_sha256") != job_bundle_sha256:
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "execution does not bind exact JobBundle")
        if grant.get("job_bundle_sha256") != job_bundle_sha256:
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "grant does not bind exact JobBundle")
        if execution.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "execution does not bind exact Grant")
        if execution.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError("MODEL_RESOLUTION_MISMATCH", "execution model resolution mismatch")
        if grant.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError("MODEL_RESOLUTION_MISMATCH", "grant model resolution mismatch")
        if execution.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError("PROVIDER_CONFIG_MISMATCH", "execution provider config mismatch")
        if grant.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError("PROVIDER_CONFIG_MISMATCH", "grant provider config mismatch")

        _assert_authority_tuple(grant, authority_binding)
        _assert_exact_fields(
            execution,
            grant,
            _EXECUTION_AUTHORITY_FIELDS,
            code="AUTHORITY_BINDING_MISMATCH",
            label="execution/grant authority tuple",
        )

        claim_id = _stable_id("CLAIM", job_id, grant_binding["artifact_sha256"], "1")

        if self.job_authority is None:
            raise FormalModelJobError(
                "APPROVAL_SLOT_AUTHORITY_REQUIRED",
                "claim_attempt requires exact JobAuthority approval-slot terminal dependency",
            )
        try:
            slot_terminal = self.job_authority.claim_or_replay_approval_execution_slot_attempt_v1(
                job_authority_event_id=execution["job_authority_event_id"],
                approval_decision_event_id=execution["approval_decision_event_id"],
                attempt_claim_id=claim_id,
                formal_job_execution_binding_sha256=execution_binding["artifact_sha256"],
                job_model_execution_grant_sha256=grant_binding["artifact_sha256"],
            )
        except BaseException as exc:
            raise FormalModelJobError(
                "APPROVAL_SLOT_TERMINAL_REJECTED",
                str(exc),
            ) from exc

        if slot_terminal.get("disposition") != "CREATED":
            return {
                "status": "ATTEMPT_SLOT_ALREADY_TERMINAL_NO_AUTOMATIC_REPLAY",
                "may_issue_provider_request": False,
                "claim": None,
                "claim_binding": None,
                "approval_slot_terminal": slot_terminal,
            }

        record = {
            "schema": "RUNTIME_MODEL_ATTEMPT_CLAIM_V1",
            "attempt_claim_id": claim_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "formal_job_execution_binding_sha256": execution_binding["artifact_sha256"],
            "job_model_execution_grant_sha256": grant_binding["artifact_sha256"],
            "job_authority_event_id": execution["job_authority_event_id"],
            "job_execution_authority_snapshot_sha256": execution[
                "job_execution_authority_snapshot_sha256"
            ],
            "job_execution_snapshot_registration_sha256": execution[
                "job_execution_snapshot_registration_sha256"
            ],
            "approval_decision_event_id": execution["approval_decision_event_id"],
            "approval_acceptance_artifact_sha256": execution[
                "approval_acceptance_artifact_sha256"
            ],
            "model_resolution_sha256": execution["model_resolution_sha256"],
            "provider_execution_config_sha256": execution["provider_execution_config_sha256"],
            "attempt_index": 1,
            "claim_state": "CLAIMED_CONSUMED",
            "consumed_live_attempts": 1,
            "consumed_model_calls": 1,
            "consumed_network_calls": 1,
            "consumed_retries": 0,
            "fallback_consumed": False,
            "claimed_at_utc": claimed_at_utc or utc_now(),
        }
        existing_or_new, binding, disposition = self._create_once(
            record_type="ATTEMPT_CLAIM",
            record_id=claim_id,
            job_id=job_id,
            record=record,
        )
        _assert_exact_fields(
            existing_or_new,
            record,
            _ATTEMPT_CLAIM_GLOBAL_CONSUMPTION_FIELDS,
            code="CLAIM_CONFLICT",
            label="attempt grant-consumption claim",
        )
        if not isinstance(existing_or_new.get("claimed_at_utc"), str) or not existing_or_new["claimed_at_utc"]:
            raise FormalModelJobError(
                "CORRUPT_EXISTING_RECORD",
                "attempt claim is missing its original claimed_at_utc",
            )

        if disposition != "CREATED":
            raise FormalModelJobError(
                "ATTEMPT_RECORD_PREEXISTS_NEW_SLOT_TERMINAL",
                "approval-slot ATTEMPT terminal was newly committed but FormalModelJob attempt record already existed",
            )

        return {
            "status": "NEWLY_COMMITTED_CLAIM",
            "may_issue_provider_request": True,
            "claim": existing_or_new,
            "claim_binding": binding,
            "approval_slot_terminal": slot_terminal,
        }

    def persist_assistant_output(self, *, job_id: str, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(text, str) or text == "":
            raise FormalModelJobError("INVALID_OUTPUT", "assistant output must be non-empty text")
        raw = text.encode("utf-8")
        output_sha = hashlib.sha256(raw).hexdigest()
        output_id = _stable_id("OUT", job_id, output_sha)
        identity = _identity_sha("ASSISTANT_OUTPUT", output_id)
        try:
            binding, _manifest = self.store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=identity,
                artifact_bytes=raw,
                job_id=job_id,
                persistence_class=PersistenceClass.WORKING,
                expected_artifact_sha256=output_sha,
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("PERSIST_FAIL_CLOSED", str(exc)) from exc
        return {
            "output_id": output_id,
            "content_sha256": output_sha,
            "binding": _binding_dict(binding),
        }, _binding_dict(binding)

    def persist_claimed_attempt_failure_outcome(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        execution_binding: dict[str, Any],
        grant_binding: dict[str, Any],
        claim_binding: dict[str, Any],
        model_resolution_sha256: str,
        provider_execution_config_sha256: str,
        failure_stage: str,
        failure_code: str,
        provider_request_invocation_started: bool,
        failure_observed_at_utc: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist one non-secret failure observation for a consumed first attempt."""
        execution = self.load_record(execution_binding)
        grant = self.load_record(grant_binding)
        claim = self.load_record(claim_binding)

        if any(item.get("job_id") != job_id for item in (execution, grant, claim)):
            raise FormalModelJobError("JOB_ID_MISMATCH", "failure outcome evidence job mismatch")
        if any(item.get("job_bundle_sha256") != job_bundle_sha256 for item in (execution, grant, claim)):
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "failure outcome JobBundle mismatch")
        if execution.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "execution does not bind exact Grant")
        if claim.get("formal_job_execution_binding_sha256") != execution_binding["artifact_sha256"]:
            raise FormalModelJobError("EXECUTION_BINDING_MISMATCH", "claim does not bind exact execution")
        if claim.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "claim does not bind exact Grant")
        if claim.get("attempt_index") != 1 or claim.get("claim_state") != "CLAIMED_CONSUMED":
            raise FormalModelJobError("CLAIM_STATE_INVALID", "failure outcome requires consumed attempt 1")

        for owner, label in ((execution, "execution"), (grant, "grant"), (claim, "claim")):
            if owner.get("model_resolution_sha256") != model_resolution_sha256:
                raise FormalModelJobError(
                    "MODEL_RESOLUTION_MISMATCH",
                    f"failure outcome {label} model resolution mismatch",
                )
            if owner.get("provider_execution_config_sha256") != provider_execution_config_sha256:
                raise FormalModelJobError(
                    "PROVIDER_CONFIG_MISMATCH",
                    f"failure outcome {label} provider config mismatch",
                )

        if failure_stage not in _ATTEMPT_FAILURE_STAGES:
            raise FormalModelJobError("FAILURE_STAGE_INVALID", "failure_stage is not allowlisted")
        failure_code = _require_non_empty(failure_code, "failure_code")
        expected_failure_code = _ATTEMPT_FAILURE_CODE_BY_STAGE[failure_stage]
        if failure_code != expected_failure_code:
            raise FormalModelJobError(
                "FAILURE_CODE_NOT_ALLOWLISTED",
                "failure_code must equal the Runtime-owned fixed code for failure_stage",
            )
        if not isinstance(provider_request_invocation_started, bool):
            raise FormalModelJobError(
                "INVALID_INPUT",
                "provider_request_invocation_started must be boolean",
            )

        receipt_id = _stable_id("ATTEMPTFAIL", job_id, claim_binding["artifact_sha256"])
        record = {
            "schema": "RUNTIME_MODEL_ATTEMPT_FAILURE_OUTCOME_RECEIPT_V1",
            "model_attempt_failure_outcome_receipt_id": receipt_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "formal_job_execution_binding_sha256": execution_binding["artifact_sha256"],
            "model_execution_grant_sha256": grant_binding["artifact_sha256"],
            "pre_request_attempt_claim_sha256": claim_binding["artifact_sha256"],
            "job_authority_event_id": execution["job_authority_event_id"],
            "approval_decision_event_id": execution["approval_decision_event_id"],
            "model_resolution_sha256": model_resolution_sha256,
            "provider_execution_config_sha256": provider_execution_config_sha256,
            "attempt_index": 1,
            "claim_state": "CLAIMED_CONSUMED",
            "failure_stage": failure_stage,
            "failure_code": failure_code,
            "provider_request_invocation_started": provider_request_invocation_started,
            "automatic_replay_allowed": False,
            "failure_observed_at_utc": failure_observed_at_utc or utc_now(),
        }

        existing, binding, _disposition = self._create_once(
            record_type="ATTEMPT_FAILURE_OUTCOME",
            record_id=receipt_id,
            job_id=job_id,
            record=record,
        )
        _assert_exact_fields(
            existing,
            record,
            _ATTEMPT_FAILURE_OUTCOME_FIELDS,
            code="ATTEMPT_FAILURE_OUTCOME_CONFLICT",
            label="claimed attempt failure outcome",
        )
        if not isinstance(existing.get("failure_observed_at_utc"), str) or not existing["failure_observed_at_utc"]:
            raise FormalModelJobError(
                "CORRUPT_EXISTING_RECORD",
                "attempt failure outcome is missing failure_observed_at_utc",
            )
        return existing, binding

    def persist_claimed_attempt_cancellation_outcome(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        execution_binding: dict[str, Any],
        grant_binding: dict[str, Any],
        claim_binding: dict[str, Any],
        model_resolution_sha256: str,
        provider_execution_config_sha256: str,
        cancellation_winner: str,
        provider_request_invocation_started: bool,
        stream_close_observation: str,
        cancellation_observed_at_utc: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist the one narrow non-secret consumed-claim user-cancellation outcome."""
        execution = self.load_record(execution_binding)
        grant = self.load_record(grant_binding)
        claim = self.load_record(claim_binding)

        if any(item.get("job_id") != job_id for item in (execution, grant, claim)):
            raise FormalModelJobError("JOB_ID_MISMATCH", "cancellation outcome evidence job mismatch")
        if any(item.get("job_bundle_sha256") != job_bundle_sha256 for item in (execution, grant, claim)):
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "cancellation outcome JobBundle mismatch")
        if execution.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "execution does not bind exact Grant")
        if claim.get("formal_job_execution_binding_sha256") != execution_binding["artifact_sha256"]:
            raise FormalModelJobError("EXECUTION_BINDING_MISMATCH", "claim does not bind exact execution")
        if claim.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "claim does not bind exact Grant")
        if claim.get("attempt_index") != 1 or claim.get("claim_state") != "CLAIMED_CONSUMED":
            raise FormalModelJobError("CLAIM_STATE_INVALID", "cancellation outcome requires consumed attempt 1")

        for owner, label in ((execution, "execution"), (grant, "grant"), (claim, "claim")):
            if owner.get("model_resolution_sha256") != model_resolution_sha256:
                raise FormalModelJobError(
                    "MODEL_RESOLUTION_MISMATCH",
                    f"cancellation outcome {label} model resolution mismatch",
                )
            if owner.get("provider_execution_config_sha256") != provider_execution_config_sha256:
                raise FormalModelJobError(
                    "PROVIDER_CONFIG_MISMATCH",
                    f"cancellation outcome {label} provider config mismatch",
                )

        if cancellation_winner not in _ATTEMPT_CANCELLATION_WINNERS:
            raise FormalModelJobError(
                "CANCELLATION_WINNER_INVALID",
                "cancellation_winner is not allowlisted",
            )
        if not isinstance(provider_request_invocation_started, bool):
            raise FormalModelJobError(
                "INVALID_INPUT",
                "provider_request_invocation_started must be boolean",
            )
        if stream_close_observation not in _ATTEMPT_CANCELLATION_CLOSE_OBSERVATIONS:
            raise FormalModelJobError(
                "CANCELLATION_CLOSE_OBSERVATION_INVALID",
                "confirmed cancellation requires fixed local close observation",
            )
        if cancellation_winner == "CANCEL_BEFORE_REQUEST":
            if provider_request_invocation_started or stream_close_observation != "NOT_REQUIRED_BEFORE_REQUEST":
                raise FormalModelJobError(
                    "CANCELLATION_PHASE_CONFLICT",
                    "cancel-before-request must have request count zero and no close requirement",
                )
        else:
            if not provider_request_invocation_started or stream_close_observation != "RETURNED":
                raise FormalModelJobError(
                    "CANCELLATION_PHASE_CONFLICT",
                    "active-stream cancellation requires a started provider invocation and returned close",
                )

        receipt_id = _stable_id("ATTEMPTCANCEL", job_id, claim_binding["artifact_sha256"])
        record = {
            "schema": "RUNTIME_MODEL_ATTEMPT_CANCELLATION_OUTCOME_RECEIPT_V1",
            "model_attempt_cancellation_outcome_receipt_id": receipt_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "formal_job_execution_binding_sha256": execution_binding["artifact_sha256"],
            "model_execution_grant_sha256": grant_binding["artifact_sha256"],
            "pre_request_attempt_claim_sha256": claim_binding["artifact_sha256"],
            "job_authority_event_id": execution["job_authority_event_id"],
            "approval_decision_event_id": execution["approval_decision_event_id"],
            "model_resolution_sha256": model_resolution_sha256,
            "provider_execution_config_sha256": provider_execution_config_sha256,
            "attempt_index": 1,
            "claim_state": "CLAIMED_CONSUMED",
            "cancellation_code": "ATTEMPT_CLAIMED_CANCELLED_BY_USER",
            "cancellation_winner": cancellation_winner,
            "provider_request_invocation_started": provider_request_invocation_started,
            "stream_close_observation": stream_close_observation,
            "partial_output_persisted": False,
            "retry_allowed": False,
            "automatic_replay_allowed": False,
            "claim_refund_allowed": False,
            "cancellation_observed_at_utc": cancellation_observed_at_utc or utc_now(),
        }

        existing, binding, _disposition = self._create_once(
            record_type="ATTEMPT_CANCELLATION_OUTCOME",
            record_id=receipt_id,
            job_id=job_id,
            record=record,
        )
        _assert_exact_fields(
            existing,
            record,
            _ATTEMPT_CANCELLATION_OUTCOME_FIELDS,
            code="ATTEMPT_CANCELLATION_OUTCOME_CONFLICT",
            label="claimed attempt cancellation outcome",
        )
        if (
            not isinstance(existing.get("cancellation_observed_at_utc"), str)
            or not existing["cancellation_observed_at_utc"]
        ):
            raise FormalModelJobError(
                "CORRUPT_EXISTING_RECORD",
                "attempt cancellation outcome is missing cancellation_observed_at_utc",
            )
        return existing, binding

    def persist_model_attempt_receipt(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        execution_binding: dict[str, Any],
        grant_binding: dict[str, Any],
        claim_binding: dict[str, Any],
        request_payload_sha256: str,
        response_payload_sha256: str,
        started_at_utc: str,
        finished_at_utc: str,
        transport_status: str = "SYNTHETIC_SUCCESS",
        transport_evidence_sha256: str | None = None,
        transport_retries_observed: int = 0,
        fallback_observed: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        execution = self.load_record(execution_binding)
        grant = self.load_record(grant_binding)
        claim = self.load_record(claim_binding)

        if any(item.get("job_id") != job_id for item in (execution, grant, claim)):
            raise FormalModelJobError("JOB_ID_MISMATCH", "attempt evidence job mismatch")
        if any(item.get("job_bundle_sha256") != job_bundle_sha256 for item in (execution, grant, claim)):
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "attempt evidence JobBundle mismatch")
        if execution.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "execution does not bind exact Grant")
        if claim.get("formal_job_execution_binding_sha256") != execution_binding["artifact_sha256"]:
            raise FormalModelJobError("EXECUTION_BINDING_MISMATCH", "claim does not bind exact execution")
        if claim.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "claim does not bind exact Grant")
        if claim.get("attempt_index") != 1 or claim.get("claim_state") != "CLAIMED_CONSUMED":
            raise FormalModelJobError("CLAIM_STATE_INVALID", "attempt claim is not the consumed first attempt")

        _require_sha(request_payload_sha256, "request_payload_sha256")
        _require_sha(response_payload_sha256, "response_payload_sha256")
        _require_non_empty(started_at_utc, "started_at_utc")
        _require_non_empty(finished_at_utc, "finished_at_utc")
        if transport_status not in ("SYNTHETIC_SUCCESS", "LIVE_SUCCESS"):
            raise FormalModelJobError(
                "TRANSPORT_STATUS_INVALID",
                "transport_status is not allowlisted",
            )
        if isinstance(transport_retries_observed, bool) or transport_retries_observed != 0:
            raise FormalModelJobError(
                "RETRY_FORBIDDEN",
                "first slice requires zero transport retries",
            )
        if fallback_observed is not False:
            raise FormalModelJobError(
                "FALLBACK_FORBIDDEN",
                "first slice forbids fallback",
            )
        if transport_status == "LIVE_SUCCESS":
            _require_sha(transport_evidence_sha256, "transport_evidence_sha256")
        elif transport_evidence_sha256 is not None:
            raise FormalModelJobError(
                "SYNTHETIC_TRANSPORT_EVIDENCE_FORBIDDEN",
                "synthetic attempt must not masquerade as authentic transport evidence",
            )

        receipt_id = _stable_id("ATTEMPT", job_id, execution_binding["artifact_sha256"], "1")
        record = {
            "schema": "RUNTIME_MODEL_ATTEMPT_RECEIPT_V1",
            "model_attempt_receipt_id": receipt_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "formal_job_execution_binding_sha256": execution_binding["artifact_sha256"],
            "model_execution_grant_sha256": grant_binding["artifact_sha256"],
            "pre_request_attempt_claim_sha256": claim_binding["artifact_sha256"],
            "attempt_index": 1,
            "model_resolution_sha256": execution["model_resolution_sha256"],
            "provider_execution_config_sha256": execution["provider_execution_config_sha256"],
            "request_payload_sha256": request_payload_sha256,
            "response_payload_sha256": response_payload_sha256,
            "transport_status": transport_status,
            "transport_retries_observed": transport_retries_observed,
            "fallback_observed": fallback_observed,
            "started_at_utc": started_at_utc,
            "finished_at_utc": finished_at_utc,
        }
        if transport_status == "LIVE_SUCCESS":
            record["transport_evidence_sha256"] = transport_evidence_sha256
        return self._persist_immutable(
            record_type="MODEL_ATTEMPT",
            record_id=receipt_id,
            job_id=job_id,
            record=record,
        )

    def persist_consumption_receipt(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        grant_binding: dict[str, Any],
        claim_binding: dict[str, Any],
        attempt_binding: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        grant = self.load_record(grant_binding)
        claim = self.load_record(claim_binding)
        attempt = self.load_record(attempt_binding)

        if any(item.get("job_id") != job_id for item in (grant, claim, attempt)):
            raise FormalModelJobError("JOB_ID_MISMATCH", "consumption evidence job mismatch")
        if any(item.get("job_bundle_sha256") != job_bundle_sha256 for item in (grant, claim, attempt)):
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "consumption evidence JobBundle mismatch")
        if claim.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "claim does not bind exact Grant")
        if attempt.get("model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "attempt does not bind exact Grant")
        if attempt.get("pre_request_attempt_claim_sha256") != claim_binding["artifact_sha256"]:
            raise FormalModelJobError("CLAIM_MISMATCH", "attempt does not bind exact claim")
        if attempt.get("attempt_index", 1) != 1:
            raise FormalModelJobError("ATTEMPT_INDEX_INVALID", "first slice permits only attempt 1")

        receipt_id = _stable_id("CONSUME", job_id, claim_binding["artifact_sha256"])
        record = {
            "schema": "RUNTIME_JOB_MODEL_EXECUTION_CONSUMPTION_RECEIPT_V1",
            "model_execution_consumption_receipt_id": receipt_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "grant_sha256": grant_binding["artifact_sha256"],
            "pre_request_attempt_claim_sha256": claim_binding["artifact_sha256"],
            "attempt_index": 1,
            "model_calls_consumed": 1,
            "network_calls_consumed": 1,
            "transport_retries_observed": 0,
            "fallback_observed": False,
            "model_attempt_receipt_sha256": attempt_binding["artifact_sha256"],
        }
        return self._persist_immutable(
            record_type="MODEL_CONSUMPTION",
            record_id=receipt_id,
            job_id=job_id,
            record=record,
        )

    def persist_formal_result_commit(
        self,
        *,
        job_id: str,
        job_bundle_sha256: str,
        execution_binding: dict[str, Any],
        grant_binding: dict[str, Any],
        claim_binding: dict[str, Any],
        attempt_binding: dict[str, Any],
        consumption_binding: dict[str, Any],
        assistant_output_binding: dict[str, Any],
        authority_binding: dict[str, Any],
        model_resolution_sha256: str,
        provider_execution_config_sha256: str,
        committed_at_utc: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        execution = self.load_record(execution_binding)
        grant = self.load_record(grant_binding)
        claim = self.load_record(claim_binding)
        attempt = self.load_record(attempt_binding)
        consumption = self.load_record(consumption_binding)

        records = (execution, grant, claim, attempt, consumption)
        if any(item.get("job_id") != job_id for item in records):
            raise FormalModelJobError("JOB_ID_MISMATCH", "formal result evidence job mismatch")
        if any(item.get("job_bundle_sha256") != job_bundle_sha256 for item in records):
            raise FormalModelJobError("JOB_BUNDLE_MISMATCH", "formal result evidence JobBundle mismatch")

        if execution.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "execution does not bind exact Grant")
        if claim.get("formal_job_execution_binding_sha256") != execution_binding["artifact_sha256"]:
            raise FormalModelJobError("EXECUTION_BINDING_MISMATCH", "claim does not bind exact execution")
        if claim.get("job_model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "claim does not bind exact Grant")
        if attempt.get("formal_job_execution_binding_sha256") != execution_binding["artifact_sha256"]:
            raise FormalModelJobError("EXECUTION_BINDING_MISMATCH", "attempt does not bind exact execution")
        if attempt.get("model_execution_grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "attempt does not bind exact Grant")
        if attempt.get("pre_request_attempt_claim_sha256") != claim_binding["artifact_sha256"]:
            raise FormalModelJobError("CLAIM_MISMATCH", "attempt does not bind exact claim")
        if consumption.get("grant_sha256") != grant_binding["artifact_sha256"]:
            raise FormalModelJobError("GRANT_MISMATCH", "consumption does not bind exact Grant")
        if consumption.get("pre_request_attempt_claim_sha256") != claim_binding["artifact_sha256"]:
            raise FormalModelJobError("CLAIM_MISMATCH", "consumption does not bind exact claim")
        if consumption.get("model_attempt_receipt_sha256") != attempt_binding["artifact_sha256"]:
            raise FormalModelJobError("ATTEMPT_MISMATCH", "consumption does not bind exact attempt")

        _assert_authority_tuple(grant, authority_binding)
        _assert_exact_fields(
            execution,
            grant,
            _EXECUTION_AUTHORITY_FIELDS,
            code="AUTHORITY_BINDING_MISMATCH",
            label="execution/grant authority tuple",
        )
        if execution.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError("MODEL_RESOLUTION_MISMATCH", "execution model resolution mismatch")
        if grant.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError("MODEL_RESOLUTION_MISMATCH", "grant model resolution mismatch")
        if claim.get("model_resolution_sha256") != model_resolution_sha256:
            raise FormalModelJobError("MODEL_RESOLUTION_MISMATCH", "claim model resolution mismatch")
        if execution.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError("PROVIDER_CONFIG_MISMATCH", "execution provider config mismatch")
        if grant.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError("PROVIDER_CONFIG_MISMATCH", "grant provider config mismatch")
        if claim.get("provider_execution_config_sha256") != provider_execution_config_sha256:
            raise FormalModelJobError("PROVIDER_CONFIG_MISMATCH", "claim provider config mismatch")

        output_binding = _binding_obj(assistant_output_binding)

        expected_output_id = _stable_id("OUT", job_id, output_binding.artifact_sha256)
        expected_output_identity = _identity_sha("ASSISTANT_OUTPUT", expected_output_id)
        if output_binding.artifact_identity_sha256 != expected_output_identity:
            raise FormalModelJobError(
                "OUTPUT_BINDING_MISMATCH",
                "assistant output binding is not the exact expected assistant-output identity",
            )

        try:
            output_manifest, output_raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=output_binding.artifact_identity_sha256,
                artifact_revision=output_binding.artifact_revision,
                artifact_sha256=output_binding.artifact_sha256,
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("STALE_OR_TAMPERED", str(exc)) from exc

        if output_manifest.job_id != job_id:
            raise FormalModelJobError(
                "OUTPUT_JOB_MISMATCH",
                "assistant output Artifact belongs to a different job",
            )

        actual_output_sha256 = hashlib.sha256(output_raw).hexdigest()
        if actual_output_sha256 != output_binding.artifact_sha256:
            raise FormalModelJobError(
                "OUTPUT_SHA_MISMATCH",
                "assistant output Artifact bytes do not match the exact output binding",
            )

        if not output_raw:
            raise FormalModelJobError("INVALID_OUTPUT", "assistant output Artifact is empty")
        try:
            output_text = output_raw.decode("utf-8")
        except UnicodeError as exc:
            raise FormalModelJobError(
                "INVALID_OUTPUT_ENCODING",
                "assistant output Artifact is not UTF-8",
            ) from exc
        if output_text == "":
            raise FormalModelJobError("INVALID_OUTPUT", "assistant output Artifact is empty")

        if attempt.get("response_payload_sha256") != actual_output_sha256:
            raise FormalModelJobError(
                "RESPONSE_OUTPUT_MISMATCH",
                "formal assistant output does not match ModelAttemptReceipt response payload",
            )

        result_package_id = _stable_id(
            "RESULTPKG",
            job_id,
            attempt_binding["artifact_sha256"],
            output_binding.artifact_sha256,
        )
        result_package_record = {
            "schema": "RUNTIME_RESULT_PACKAGE_V1",
            "result_package_id": result_package_id,
            "job_id": job_id,
            "status": "PASS",
            "model_attempt_receipt_sha256": attempt_binding["artifact_sha256"],
            "output_artifacts": [
                {
                    "kind": "assistant_text",
                    "artifact_identity_sha256": output_binding.artifact_identity_sha256,
                    "artifact_revision": output_binding.artifact_revision,
                    "artifact_sha256": output_binding.artifact_sha256,
                    "content_sha256": actual_output_sha256,
                }
            ],
        }
        result_package, result_package_binding = self._persist_immutable_source_bound(
            record_type="RESULT_PACKAGE",
            record_id=result_package_id,
            job_id=job_id,
            record=result_package_record,
            source_binding=output_binding,
        )

        commit_id = _stable_id(
            "RESULT",
            job_id,
            execution_binding["artifact_sha256"],
            grant_binding["artifact_sha256"],
            claim_binding["artifact_sha256"],
            attempt_binding["artifact_sha256"],
            consumption_binding["artifact_sha256"],
            result_package_binding["artifact_sha256"],
        )
        record = {
            "schema": "RUNTIME_FORMAL_MODEL_RESULT_COMMIT_RECEIPT_V1",
            "formal_result_commit_id": commit_id,
            "job_id": job_id,
            "job_bundle_sha256": job_bundle_sha256,
            "formal_job_execution_binding_sha256": execution_binding["artifact_sha256"],
            "web_formal_job_intake_binding_sha256": execution[
                "web_formal_job_intake_binding_sha256"
            ],
            "job_authority_event_id": execution["job_authority_event_id"],
            "job_execution_authority_snapshot_sha256": execution[
                "job_execution_authority_snapshot_sha256"
            ],
            "job_execution_snapshot_registration_sha256": execution[
                "job_execution_snapshot_registration_sha256"
            ],
            "approval_decision_event_id": execution["approval_decision_event_id"],
            "approval_acceptance_artifact_sha256": execution[
                "approval_acceptance_artifact_sha256"
            ],
            "model_resolution_sha256": execution["model_resolution_sha256"],
            "model_execution_grant_sha256": grant_binding["artifact_sha256"],
            "provider_execution_config_sha256": execution[
                "provider_execution_config_sha256"
            ],
            "model_attempt_receipt_sha256": attempt_binding["artifact_sha256"],
            "model_execution_consumption_receipt_sha256": consumption_binding[
                "artifact_sha256"
            ],
            "pre_request_attempt_claim_sha256": claim_binding["artifact_sha256"],
            "result_package_artifact_identity_sha256": result_package_binding[
                "artifact_identity_sha256"
            ],
            "result_package_artifact_revision": result_package_binding[
                "artifact_revision"
            ],
            "result_package_artifact_sha256": result_package_binding[
                "artifact_sha256"
            ],
            "output_artifacts": result_package["output_artifacts"],
            "assistant_output_binding": _binding_dict(output_binding),
            "assistant_content_sha256": actual_output_sha256,
            "committed_at_utc": committed_at_utc or utc_now(),
        }

        existing_or_new, commit_binding, disposition = self._create_once_source_bound(
            record_type="FORMAL_RESULT_COMMIT",
            record_id=commit_id,
            job_id=job_id,
            record=record,
            source_binding=output_binding,
        )
        _assert_exact_fields(
            existing_or_new,
            record,
            _FORMAL_RESULT_SOURCE_BOUND_FIELDS,
            code="FORMAL_RESULT_CONFLICT",
            label="formal result commit",
        )
        if not isinstance(existing_or_new.get("committed_at_utc"), str) or not existing_or_new[
            "committed_at_utc"
        ]:
            raise FormalModelJobError(
                "CORRUPT_EXISTING_RECORD",
                "formal result commit is missing committed_at_utc",
            )
        return existing_or_new, commit_binding

    def load_assistant_output_text(self, formal_result_commit: dict[str, Any]) -> str:
        binding = _binding_obj(formal_result_commit.get("assistant_output_binding"))
        try:
            _manifest, raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=binding.artifact_identity_sha256,
                artifact_revision=binding.artifact_revision,
                artifact_sha256=binding.artifact_sha256,
            )
        except R009OpaqueArtifactError as exc:
            raise FormalModelJobError("STALE_OR_TAMPERED", str(exc)) from exc
        if hashlib.sha256(raw).hexdigest() != formal_result_commit.get("assistant_content_sha256"):
            raise FormalModelJobError("OUTPUT_SHA_MISMATCH", "assistant output does not match formal commit")
        try:
            return raw.decode("utf-8")
        except UnicodeError as exc:
            raise FormalModelJobError("INVALID_OUTPUT_ENCODING", "assistant output is not UTF-8") from exc

    def persist_projection_receipt_once(
        self,
        *,
        job_id: str,
        receipt_id: str,
        receipt: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        existing_or_new, binding, disposition = self._create_once(
            record_type="WEB_PROJECTION_RECEIPT",
            record_id=receipt_id,
            job_id=job_id,
            record=receipt,
        )
        if set(existing_or_new) != set(receipt):
            raise FormalModelJobError(
                "PROJECTION_RECEIPT_CONFLICT",
                "existing projection receipt field set differs from replay proposal",
            )
        stable_fields = tuple(sorted(key for key in receipt if key != "projected_at_utc"))
        _assert_exact_fields(
            existing_or_new,
            receipt,
            stable_fields,
            code="PROJECTION_RECEIPT_CONFLICT",
            label="projection receipt",
        )
        projected_at = existing_or_new.get("projected_at_utc")
        if not isinstance(projected_at, str) or not projected_at:
            raise FormalModelJobError(
                "CORRUPT_EXISTING_RECORD",
                "projection receipt is missing projected_at_utc",
            )
        return existing_or_new, binding, disposition
