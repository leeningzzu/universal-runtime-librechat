"""Narrow ArtifactStore-backed content retirement for an exclusively owned Project Source.

This is NOT a generic garbage collector. All caller proof must originate from
the existing Runtime/LibreChat ownership and currentness consumers. Immutable
source identity, SHA and non-content audit metadata remain; content does not.
Each mutation is one explicit user-approved effect and is never auto-retried.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from universal_runtime.core.artifact_store import (
    ArtifactStore,
    ArtifactCurrentnessError,
    R009OpaqueArtifactError,
    _r009_assert_no_reparse_chain,
    _r009_flush_parent_directory,
    _r009_is_reparse_or_symlink,
)

from universal_runtime.core.models import ArtifactManifest

_RE = re.compile(r"^[A-Z0-9_]+$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_INTENT = "PERMANENT_CONTENT_ERASURE_INTENT_R001.json"
_COMPLETE = "PERMANENT_CONTENT_ERASURE_COMPLETE_R001.json"

class SourceRetirementStop(ValueError):
    """No irreversible effect is permitted on an unknown/incomplete state."""

def _stop(reason: str) -> None:
    raise SourceRetirementStop(reason)

def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _require_noncontent_audit_proof(proof: dict[str, Any], source_id: str, project_id: str) -> None:
    if not isinstance(proof, dict) or proof.get("source_ref_id") != source_id or proof.get("project_id") != project_id:
        _stop("SOURCE_RETIREMENT_IDENTITY_UNPROVEN")
    # All read families must be covered; missing/None means UNKNOWN, not zero.
    counts = proof.get("exclusive_ref_counts")
    expected = {"current_projects", "current_chat", "other_source_refs", "jobs",
                "agents", "assistants", "shared_links", "native_other_files",
                "protected_rollbacks", "external_consumers"}
    if not isinstance(counts, dict) or set(counts) != expected or any(
        isinstance(v, bool) or type(v) is not int or v != 0 for v in counts.values()
    ):
        _stop("SOURCE_RETIREMENT_EXCLUSIVE_REFERENCES_NOT_PROVEN")
    if proof.get("coverage_complete") is not True or proof.get("source_detached") is not True or proof.get("manual_user_confirmed") is not True:
        _stop("SOURCE_RETIREMENT_LEGALITY_OR_EXPLICIT_CONSENT_NOT_PROVEN")
    for k in (
        "command_id", "owner_id", "protected_asset_census_sha256",
        "binding_evidence_sha256", "runtime_source_consumer_evidence_sha256",
    ):
        if not isinstance(proof.get(k), str) or not proof[k]:
            _stop("SOURCE_RETIREMENT_OWNER_OR_PROVENANCE_UNPROVEN")
    if any(
        _SHA.fullmatch(proof[key]) is None
        for key in (
            "protected_asset_census_sha256", "binding_evidence_sha256",
            "runtime_source_consumer_evidence_sha256",
        )
    ):
        _stop("SOURCE_RETIREMENT_PROTECTED_ASSET_OR_BINDING_EVIDENCE_INVALID")
    binding_class = proof.get("binding_class")
    native_file_ids = proof.get("native_file_ids")
    source_ref_ids = proof.get("source_ref_ids")
    if binding_class not in {
        "EXACT_NATIVE_FILE_SOURCE_REF", "EXACT_LEGACY_COHORT_SET", "EXACT_RUNTIME_SOURCE_ONLY",
    }:
        _stop("SOURCE_RETIREMENT_BINDING_CLASS_INVALID")
    if not isinstance(native_file_ids, list) or not isinstance(source_ref_ids, list):
        _stop("SOURCE_RETIREMENT_NATIVE_SOURCE_BINDING_SET_INVALID")
    if (
        any(not isinstance(x, str) or not x for x in native_file_ids + source_ref_ids)
        or len(set(native_file_ids)) != len(native_file_ids)
        or len(set(source_ref_ids)) != len(source_ref_ids)
        or source_id not in source_ref_ids
        or len(source_ref_ids) > 32
    ):
        _stop("SOURCE_RETIREMENT_NATIVE_SOURCE_BINDING_SET_INVALID")
    if binding_class == "EXACT_RUNTIME_SOURCE_ONLY":
        if native_file_ids or source_ref_ids != [source_id] or proof.get("source_only_identity_verified") is not True:
            _stop("SOURCE_RETIREMENT_SOURCE_ONLY_IDENTITY_INVALID")
    else:
        if proof.get("canonical_native_file_binding_verified") is not True:
            _stop("SOURCE_RETIREMENT_NATIVE_FILE_ID_PROVENANCE_MISSING")
        if not native_file_ids or len(native_file_ids) != len(source_ref_ids) or len(native_file_ids) > 32:
            _stop("SOURCE_RETIREMENT_NATIVE_SOURCE_BINDING_SET_INVALID")
        if binding_class == "EXACT_NATIVE_FILE_SOURCE_REF" and (
            len(native_file_ids) != 1 or source_ref_ids != [source_id]
        ):
            _stop("SOURCE_RETIREMENT_EXACT_BINDING_CARDINALITY_INVALID")

def _exact_source_targets(store: ArtifactStore, source: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = source.get("source_ref_id")
    if not isinstance(source_id, str) or _RE.fullmatch(source_id) is None:
        _stop("SOURCE_RETIREMENT_SOURCE_ID_INVALID")
    result = []
    for key in ("source_artifact_binding", "document_bundle_binding"):
        binding = source.get(key)
        if binding is None:
            if key == "source_artifact_binding": _stop("SOURCE_RETIREMENT_SOURCE_BINDING_MISSING")
            continue
        if not isinstance(binding, dict) or set(("artifact_identity_sha256", "artifact_id", "sha256", "revision")) - set(binding):
            _stop("SOURCE_RETIREMENT_OPAQUE_BINDING_INCOMPLETE")
        identity, digest = binding["artifact_identity_sha256"], binding["sha256"]
        if not isinstance(identity, str) or _SHA.fullmatch(identity) is None or not isinstance(digest, str) or _SHA.fullmatch(digest) is None:
            _stop("SOURCE_RETIREMENT_OPAQUE_IDENTITY_INVALID")
        if binding["artifact_id"] != "RUNTIME_OPAQUE_" + identity.upper() or binding["revision"] != 1:
            _stop("SOURCE_RETIREMENT_OPAQUE_REVISION_DRIFT")
        rawid, path, manifest = store._r009_exact_paths(identity)
        # Exact R009 preflight, no user-controlled path.
        try:
            store._load_exact_r009_manifest(raw_id=rawid, content_path=path, manifest_path=manifest,
                                            expected_sha256=digest, expected_job_id=None, expected_persistence=None)
        except (R009OpaqueArtifactError, OSError, ValueError) as exc:
            raise SourceRetirementStop("SOURCE_RETIREMENT_R009_CURRENTNESS_OR_RETIREMENT_MARKER_UNKNOWN") from exc
        data = path.read_bytes()
        if _sha(data) != digest:
            _stop("SOURCE_RETIREMENT_OPAQUE_SHA_CHANGED")
        result.append({"kind": "R009", "id": rawid, "path": path, "sha": digest, "size": len(data)})
    derived = source.get("derived_projection_binding")
    target_id = "WEB_TEXT_DERIVATION_" + source_id
    if not isinstance(derived, dict) or derived.get("artifact_id") != target_id or derived.get("revision") != 1:
        _stop("SOURCE_RETIREMENT_DERIVATION_BINDING_INVALID")
    digest = derived.get("sha256")
    if not isinstance(digest, str) or _SHA.fullmatch(digest) is None:
        _stop("SOURCE_RETIREMENT_DERIVATION_SHA_INVALID")
    try:
        manifest = store.current_manifest(target_id)
    except (ArtifactCurrentnessError, OSError, ValueError) as exc:
        raise SourceRetirementStop("SOURCE_RETIREMENT_DERIVATION_CURRENTNESS_UNKNOWN") from exc
    expected = store.root / "web_m001" / "derivations" / target_id / "R001.json"
    if Path(manifest.path) != expected.resolve() or manifest.revision != 1 or manifest.sha256 != digest:
        _stop("SOURCE_RETIREMENT_DERIVATION_PATH_OR_HASH_DRIFT")
    data = expected.read_bytes()
    try:
        record = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise SourceRetirementStop("SOURCE_RETIREMENT_DERIVATION_SCHEMA_UNKNOWN") from exc
    if not isinstance(record, dict) or not isinstance(record.get("decoded_text"), str) or record.get("source_sha256") != source.get("source_artifact_binding", {}).get("sha256"):
        _stop("SOURCE_RETIREMENT_DERIVATION_OWNER_OR_CONTENT_UNKNOWN")
    result.append({"kind": "DERIVATION", "id": target_id, "path": expected, "sha": digest, "size": len(data)})
    # Existing Runtime stores idempotent command responses with decoded source text.
    # The command artifact identity is a canonical SHA256 of the original command_id,
    # NOT an inferred filename, byte SHA or nearest-timestamp match.
    command_id = source.get("created_by_command_id")
    if not isinstance(command_id, str) or not command_id:
        _stop("SOURCE_RETIREMENT_CANONICAL_COMMAND_BINDING_MISSING")
    command_artifact_id = "WEB_COMMAND_" + _sha(command_id.encode("utf8")).upper()
    try:
        cmd_manifest = store.current_manifest(command_artifact_id)
    except (ArtifactCurrentnessError, OSError, ValueError) as exc:
        raise SourceRetirementStop("SOURCE_RETIREMENT_COMMAND_CURRENTNESS_UNKNOWN") from exc
    command_path = store.root / "web_m001" / "commands" / command_artifact_id / "R001.json"
    if (
        Path(cmd_manifest.path) != command_path.resolve()
        or cmd_manifest.revision != 1
        or _r009_is_reparse_or_symlink(command_path)
    ):
        _stop("SOURCE_RETIREMENT_COMMAND_IDENTITY_OR_PATH_DRIFT")
    try:
        command_data = command_path.read_bytes()
        command = json.loads(command_data)
    except (OSError, ValueError, UnicodeError) as exc:
        raise SourceRetirementStop("SOURCE_RETIREMENT_COMMAND_SCHEMA_UNKNOWN") from exc
    response = command.get("response", {})
    if (
        not isinstance(response, dict)
        or command.get("command_id") != command_id
        or command.get("command_type") not in {
            "DOCUMENT_BUNDLE_SOURCE_ADOPT", "TEXT_SOURCE_INGEST",
            "CHAT_OUTPUT_SOURCE_SAVE",
        }
        or not isinstance(response.get("source_ref"), dict)
        or response["source_ref"].get("source_ref_id") != source_id
        or not isinstance(response.get("text_derivation"), dict)
        or not isinstance(response["text_derivation"].get("decoded_text"), str)
        or _sha(response["text_derivation"]["decoded_text"].encode("utf8")) != source["source_artifact_binding"]["sha256"]
        or _sha(command_data) != cmd_manifest.sha256
    ):
        _stop("SOURCE_RETIREMENT_COMMAND_CONTENT_OR_SOURCE_ID_MISMATCH")
    result.append({
        "kind": "COMMAND_RESPONSE",
        "id": command_artifact_id,
        "path": command_path,
        "sha": cmd_manifest.sha256,
        "size": len(command_data),
    })
    if len(result) not in (3,4) or len({row["id"] for row in result}) != len(result):
        _stop("SOURCE_RETIREMENT_CLOSURE_COUNT_DRIFT")
    return result


def _source_record_target_ids(source: dict[str, Any]) -> set[str]:
    source_id = source.get("source_ref_id")
    command_id = source.get("created_by_command_id")
    if not isinstance(source_id, str) or _RE.fullmatch(source_id) is None:
        _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_SOURCE_ID_INVALID")
    if not isinstance(command_id, str) or not command_id:
        _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_COMMAND_ID_MISSING")
    ids: set[str] = set()
    for key in ("source_artifact_binding", "document_bundle_binding", "derived_projection_binding"):
        binding = source.get(key)
        if binding is None and key == "document_bundle_binding":
            continue
        if not isinstance(binding, dict) or not isinstance(binding.get("artifact_id"), str):
            _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_BINDING_UNKNOWN")
        ids.add(binding["artifact_id"])
    ids.add("WEB_COMMAND_" + _sha(command_id.encode("utf8")).upper())
    if len(ids) not in (3, 4):
        _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_TARGET_COUNT_DRIFT")
    return ids


def _active_source_target_owners(store: ArtifactStore) -> dict[str, set[str]]:
    source_root = store.root / "web_m001" / "source_refs"
    if not source_root.is_dir() or _r009_is_reparse_or_symlink(source_root):
        _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_ROOT_UNKNOWN")
    owners: dict[str, set[str]] = {}
    saw_source_record = False
    saw_active_source = False
    for folder in sorted(source_root.iterdir(), key=lambda p: p.name):
        if not folder.is_dir() or _r009_is_reparse_or_symlink(folder):
            _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_ENTRY_UNKNOWN")
        artifact_id = folder.name
        if not artifact_id.startswith("WEB_SOURCE_REF_"):
            _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_NAMESPACE_DRIFT")
        saw_source_record = True
        intent = store._manifest_dir(artifact_id) / _INTENT
        complete = store._manifest_dir(artifact_id) / _COMPLETE
        if intent.exists() and not complete.exists():
            _stop("SOURCE_RETIREMENT_GLOBAL_PARTIAL_HISTORY_STOP")
        if complete.exists():
            continue
        try:
            manifest = store.current_manifest(artifact_id)
        except (ArtifactCurrentnessError, OSError, ValueError) as exc:
            raise SourceRetirementStop("SOURCE_RETIREMENT_REFERENCE_INDEX_CURRENTNESS_UNKNOWN") from exc
        expected = source_root / artifact_id / f"R{manifest.revision:03d}.json"
        if Path(manifest.path) != expected.resolve() or _r009_is_reparse_or_symlink(expected):
            _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_PATH_DRIFT")
        try:
            record = json.loads(expected.read_text("utf8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise SourceRetirementStop("SOURCE_RETIREMENT_REFERENCE_INDEX_SCHEMA_UNKNOWN") from exc
        source_id = record.get("source_ref_id")
        if artifact_id != "WEB_SOURCE_REF_" + str(source_id):
            _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_IDENTITY_MISMATCH")
        saw_active_source = True
        for target_id in _source_record_target_ids(record):
            owners.setdefault(target_id, set()).add(source_id)
    if not saw_source_record:
        _stop("SOURCE_RETIREMENT_REFERENCE_INDEX_EMPTY_UNKNOWN")
    # An empty owner map is valid only when every known SourceRef has a complete
    # content-retirement receipt. Candidate projection and manual replay need it.
    if not saw_active_source:
        return {}
    return owners


def _partition_targets_by_source_ownership(
    store: ArtifactStore, source_id: str, targets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    owners = _active_source_target_owners(store)
    retired: list[dict[str, Any]] = []
    shared: list[dict[str, Any]] = []
    for item in targets:
        current = owners.get(item["id"])
        if not current or source_id not in current:
            _stop("SOURCE_RETIREMENT_TARGET_OWNER_INDEX_MISMATCH")
        row = {**item, "source_ref_owners": sorted(current)}
        if len(current) == 1:
            retired.append(row)
        else:
            shared.append(row)
    if not retired:
        _stop("SOURCE_RETIREMENT_NO_EXCLUSIVE_CONTENT_TARGETS")
    return retired, shared

def list_project_source_retirement_candidates(
    store: ArtifactStore,
    *,
    project_id: str,
    active_source_ref_ids: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(store, ArtifactStore) or not isinstance(project_id, str) or not project_id:
        _stop("SOURCE_RETIREMENT_CANDIDATE_SCOPE_INVALID")
    if (
        not isinstance(active_source_ref_ids, list)
        or any(not isinstance(value, str) or not value for value in active_source_ref_ids)
        or len(set(active_source_ref_ids)) != len(active_source_ref_ids)
    ):
        _stop("SOURCE_RETIREMENT_CANDIDATE_ACTIVE_SOURCE_SET_INVALID")
    active = set(active_source_ref_ids)
    owners = _active_source_target_owners(store)
    source_root = store.root / "web_m001" / "source_refs"
    result: list[dict[str, Any]] = []
    for folder in sorted(source_root.iterdir(), key=lambda p: p.name):
        artifact_id = folder.name
        if not artifact_id.startswith("WEB_SOURCE_REF_"):
            _stop("SOURCE_RETIREMENT_CANDIDATE_SOURCE_NAMESPACE_DRIFT")
        source_id = artifact_id.removeprefix("WEB_SOURCE_REF_")
        if _RE.fullmatch(source_id) is None:
            _stop("SOURCE_RETIREMENT_CANDIDATE_SOURCE_ID_INVALID")
        manifest_dir = store._manifest_dir(artifact_id)
        intent = manifest_dir / _INTENT
        complete = manifest_dir / _COMPLETE
        if intent.exists() != complete.exists():
            _stop("SOURCE_RETIREMENT_CANDIDATE_PARTIAL_HISTORY_STOP")
        retired = complete.exists()
        try:
            if retired:
                manifest_path = store.manifest_path(artifact_id, 1)
                manifest = ArtifactManifest.model_validate_json(manifest_path.read_text("utf8"))
                path = source_root / artifact_id / "R001.json"
                if (
                    manifest.artifact_id != artifact_id
                    or manifest.revision != 1
                    or store._resolved_manifest_target(manifest.path) != path.resolve()
                    or _r009_is_reparse_or_symlink(manifest_path)
                    or _r009_is_reparse_or_symlink(path)
                    or _sha(path.read_bytes()) != manifest.sha256
                ):
                    _stop("SOURCE_RETIREMENT_CANDIDATE_RETIRED_SOURCE_RECORD_DRIFT")
                completed = json.loads(complete.read_text("utf8"))
                native_binding = completed.get("native_binding")
                if (
                    completed.get("state") != "COMPLETED"
                    or completed.get("source_ref_id") != artifact_id.removeprefix("WEB_SOURCE_REF_")
                    or not isinstance(completed.get("retired_payload_count"), int)
                    or not isinstance(completed.get("retained_shared_payload_count"), int)
                    or not isinstance(native_binding, dict)
                    or native_binding.get("binding_class") not in {
                        "EXACT_NATIVE_FILE_SOURCE_REF", "EXACT_LEGACY_COHORT_SET", "EXACT_RUNTIME_SOURCE_ONLY",
                    }
                    or not isinstance(native_binding.get("native_file_ids"), list)
                    or not isinstance(native_binding.get("source_ref_ids"), list)
                    or source_id not in native_binding.get("source_ref_ids", [])
                    or not isinstance(native_binding.get("binding_evidence_sha256"), str)
                    or _SHA.fullmatch(native_binding["binding_evidence_sha256"]) is None
                ):
                    _stop("SOURCE_RETIREMENT_CANDIDATE_COMPLETION_RECEIPT_UNKNOWN")
            else:
                manifest = store.current_manifest(artifact_id)
                path = source_root / artifact_id / f"R{manifest.revision:03d}.json"
                completed = None
            record = json.loads(path.read_text("utf8"))
        except SourceRetirementStop:
            raise
        except (ArtifactCurrentnessError, OSError, ValueError, UnicodeError) as exc:
            raise SourceRetirementStop("SOURCE_RETIREMENT_CANDIDATE_CURRENTNESS_UNKNOWN") from exc
        if record.get("project_id") != project_id:
            continue
        record_source_id = record.get("source_ref_id")
        if record_source_id != source_id or artifact_id != "WEB_SOURCE_REF_" + str(record_source_id):
            _stop("SOURCE_RETIREMENT_CANDIDATE_SOURCE_ID_MISMATCH")
        filename = record.get("filename")
        source_binding = record.get("source_artifact_binding")
        binding_sha = source_binding.get("sha256") if isinstance(source_binding, dict) else None
        binding_media_type = source_binding.get("media_type") if isinstance(source_binding, dict) else None
        digest = record.get("origin_input_sha256") or binding_sha
        media_type = record.get("origin_media_type") or binding_media_type
        if (
            not isinstance(filename, str) or not filename
            or not isinstance(digest, str) or _SHA.fullmatch(digest) is None
            or not isinstance(media_type, str) or not media_type
        ):
            _stop("SOURCE_RETIREMENT_CANDIDATE_PRESENTATION_UNKNOWN")
        original_bytes = source_binding.get("byte_size") if isinstance(source_binding, dict) else None
        if isinstance(original_bytes, bool) or type(original_bytes) is not int or original_bytes < 1:
            _stop("SOURCE_RETIREMENT_CANDIDATE_ORIGINAL_BYTE_SIZE_UNKNOWN")
        target_ids = _source_record_target_ids(record)
        if retired:
            if source_id in active:
                _stop("SOURCE_RETIREMENT_CANDIDATE_RETIRED_SOURCE_STILL_ACTIVE")
            shared_count = completed["retained_shared_payload_count"]
        else:
            shared_count = sum(1 for target_id in target_ids if len(owners.get(target_id, set())) > 1)
        result.append({
            "source_ref_id": source_id,
            "filename": filename,
            "origin_input_sha256": digest,
            "origin_media_type": media_type,
            "origin_input_byte_size": original_bytes,
            "active_project_binding": source_id in active,
            "created_at_utc": record.get("created_at_utc"),
            "content_artifact_count": len(target_ids),
            "shared_content_artifact_count": shared_count,
            "retirement_state": (
                "CONTENT_RETIRED" if retired
                else "ACTIVE" if source_id in active
                else "DETACHED_RETAINED"
            ),
            "completed_native_binding": (
                {
                    "binding_class": completed["native_binding"]["binding_class"],
                    "native_file_ids": list(completed["native_binding"]["native_file_ids"]),
                    "source_ref_ids": list(completed["native_binding"]["source_ref_ids"]),
                    "binding_evidence_sha256": completed["native_binding"]["binding_evidence_sha256"],
                }
                if retired else None
            ),
        })
    unknown_active = active - {row["source_ref_id"] for row in result}
    if unknown_active:
        _stop("SOURCE_RETIREMENT_CANDIDATE_ACTIVE_SOURCE_MISSING")
    return result


def prepare_source_content_retirement(store: ArtifactStore, source: dict[str, Any],
                                      proof: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed no-write plan; avoids claiming a FileID->Source link by filename/SHA."""
    if not isinstance(store, ArtifactStore) or not isinstance(source, dict):
        _stop("SOURCE_RETIREMENT_STORE_OR_SOURCE_INVALID")
    source_id = source.get("source_ref_id")
    project_id = source.get("project_id")
    if not isinstance(source_id, str) or not isinstance(project_id, str) or not project_id:
        _stop("SOURCE_RETIREMENT_SOURCE_PROJECT_ID_INVALID")
    if source.get("origin_class") not in (
        "PROJECT_DOCUMENT_BUNDLE", "PROJECT_UPLOAD",
        "PROJECT_UPLOAD_NATIVE_AND_RUNTIME", "CHAT_OUTPUT",
    ):
        _stop("SOURCE_RETIREMENT_ORIGIN_CLASS_OUT_OF_SCOPE")
    _require_noncontent_audit_proof(proof, source_id, project_id)
    all_targets = _exact_source_targets(store, source)
    targets, shared_targets = _partition_targets_by_source_ownership(store, source_id, all_targets)
    audit_id = "WEB_SOURCE_REF_" + source_id
    audit_dir = store._manifest_dir(audit_id)
    if not audit_dir.is_dir() or (audit_dir / _INTENT).exists() or (audit_dir / _COMPLETE).exists():
        _stop("SOURCE_RETIREMENT_ALREADY_INTENDED_OR_CURRENTNESS_UNKNOWN")
    for target in targets:
        manifest_dir = store._manifest_dir(target["id"])
        if not manifest_dir.is_dir() or (manifest_dir / _INTENT).exists() or (manifest_dir / _COMPLETE).exists():
            _stop("SOURCE_RETIREMENT_TARGET_ALREADY_INTENDED")
    return {"source_ref_id": source_id, "project_id": project_id,
            "native_binding": {
                "binding_class": proof["binding_class"],
                "native_file_ids": list(proof["native_file_ids"]),
                "source_ref_ids": list(proof["source_ref_ids"]),
                "binding_evidence_sha256": proof["binding_evidence_sha256"],
            },
            "command_id": proof["command_id"],
            "targets": targets, "shared_targets": shared_targets, "audit_dir": audit_dir,
            "protected_asset_census_sha256": proof["protected_asset_census_sha256"]}

def retire_source_content_exact_once(store: ArtifactStore, source: dict[str, Any],
                                     proof: dict[str, Any]) -> dict[str, Any]:
    """One explicit effect, no automatic retry/undo. Partial always STOP with audit intent."""
    # Serialization with R009 creation; the upper Runtime Project lock must also be held.
    with store._r009_prepare_lock():
        plan = prepare_source_content_retirement(store, source, proof)
        plain = [{"id":row["id"], "sha256":row["sha"], "bytes":row["size"]} for row in plan["targets"]]
        shared = [{"id":row["id"], "sha256":row["sha"], "bytes":row["size"],
                   "source_ref_owners":row["source_ref_owners"]} for row in plan["shared_targets"]]
        core = {
            "schema": "RUNTIME_EXCLUSIVE_PROJECT_SOURCE_CONTENT_ERASURE_R001",
            "source_ref_id": plan["source_ref_id"], "project_id": plan["project_id"],
            "native_binding": plan["native_binding"],
            "command_id": plan["command_id"],
            "protected_asset_census_sha256": plan["protected_asset_census_sha256"],
            "runtime_source_consumer_evidence_sha256": proof["runtime_source_consumer_evidence_sha256"],
            "content_sha256_records": plain,
            "retained_shared_content_records": shared,
            "user_confirmed": True,
            "retirement_utc": _utc(),
        }
        serialized = (json.dumps({**core,"state":"PREPARED"},sort_keys=True,ensure_ascii=False)+"\n").encode("utf8")
        # Install all non-content deny-read markers before removing any bytes.
        paths = [plan["audit_dir"] / _INTENT] + [store._manifest_dir(t["id"]) / _INTENT for t in plan["targets"]]
        for path in paths:
            _r009_assert_no_reparse_chain(store.root, path.parent)
            store._r009_write_exclusive(path, serialized, label="exclusive retirement intent")
        for item in plan["targets"]:
            path = item["path"]
            _r009_assert_no_reparse_chain(store.root, path)
            if not path.is_file() or _r009_is_reparse_or_symlink(path):
                _stop("SOURCE_RETIREMENT_TARGET_CHANGED_AFTER_INTENT_STOP")
            if _sha(path.read_bytes()) != item["sha"]:
                _stop("SOURCE_RETIREMENT_CONTENT_CHANGED_AFTER_INTENT_STOP")
            path.unlink()
            _r009_flush_parent_directory(path.parent)
            if path.exists(): _stop("SOURCE_RETIREMENT_REMOVE_READBACK_UNKNOWN")
        receipt = {**core,"state":"COMPLETED","retired_payload_count":len(plain),
                   "retained_shared_payload_count":len(shared),
                   "retired_content_bytes":sum(x["bytes"] for x in plain)}
        data = (json.dumps(receipt,sort_keys=True,ensure_ascii=False)+"\n").encode("utf8")
        store._r009_write_exclusive(plan["audit_dir"] / _COMPLETE, data, label="exclusive content retirement")
        for item in plan["targets"]:
            store._r009_write_exclusive(
                store._manifest_dir(item["id"]) / _COMPLETE,
                data,
                label="exclusive target content retirement",
            )
            if item["path"].exists():
                _stop("SOURCE_RETIREMENT_CONTENT_REAPPEARED")
        return receipt


def load_source_content_retirement_complete(
    store: ArtifactStore,
    *,
    source_ref_id: str,
    command_id: str,
    binding_evidence_sha256: str,
) -> dict[str, Any] | None:
    if not isinstance(store, ArtifactStore) or not isinstance(source_ref_id, str) or _RE.fullmatch(source_ref_id) is None:
        _stop("SOURCE_RETIREMENT_REPLAY_SCOPE_INVALID")
    audit_dir = store._manifest_dir("WEB_SOURCE_REF_" + source_ref_id)
    intent = audit_dir / _INTENT
    complete = audit_dir / _COMPLETE
    if not intent.exists() and not complete.exists():
        return None
    if not intent.is_file() or not complete.is_file() or _r009_is_reparse_or_symlink(intent) or _r009_is_reparse_or_symlink(complete):
        _stop("SOURCE_RETIREMENT_PARTIAL_OR_REDIRECTED_HISTORY_STOP")
    try:
        prepared = json.loads(intent.read_text("utf8"))
        done = json.loads(complete.read_text("utf8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise SourceRetirementStop("SOURCE_RETIREMENT_REPLAY_RECEIPT_UNKNOWN") from exc
    if (
        prepared.get("state") != "PREPARED"
        or done.get("state") != "COMPLETED"
        or done.get("source_ref_id") != source_ref_id
        or done.get("command_id") != command_id
        or done.get("native_binding", {}).get("binding_evidence_sha256") != binding_evidence_sha256
        or prepared.get("source_ref_id") != source_ref_id
        or prepared.get("command_id") != command_id
    ):
        _stop("SOURCE_RETIREMENT_REPLAY_IDENTITY_MISMATCH")
    return done


def retire_or_replay_source_content_exact_once(
    store: ArtifactStore, source: dict[str, Any], proof: dict[str, Any]
) -> dict[str, Any]:
    replay = load_source_content_retirement_complete(
        store,
        source_ref_id=source.get("source_ref_id"),
        command_id=proof.get("command_id"),
        binding_evidence_sha256=proof.get("binding_evidence_sha256"),
    )
    if replay is not None:
        return replay
    return retire_source_content_exact_once(store, source, proof)
