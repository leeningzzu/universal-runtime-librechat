from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import re
from pathlib import Path
import zipfile

from universal_runtime.core.artifact_store import ArtifactStore, R009OpaqueArtifactError
from universal_runtime.core.enums import PersistenceClass
from universal_runtime.document_parse_adapter import (
    DoclingSidecarBinding,
    ParsedDocumentProposal,
    parse_local_document_proposal,
)


class DocumentArtifactConsumerError(RuntimeError):
    """Fail-closed error for the first Runtime-owned document bundle consumer."""


_BUNDLE_SCHEMA = "UR_PLANE_C_C1_DOCUMENT_ARTIFACT_BUNDLE_R001"
_MANIFEST_SCHEMA = "UR_PLANE_C_C1_DOCUMENT_ARTIFACT_BUNDLE_MANIFEST_R001"
_PROVENANCE_SCHEMA = "UR_PLANE_C_C1_DOCUMENT_ARTIFACT_PROVENANCE_R001"
_FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class DocumentBundleArtifact:
    artifact_id: str
    artifact_revision: int
    artifact_sha256: str
    input_sha256: str
    input_format: str
    markdown_sha256: str
    json_sha256: str
    member_manifest_sha256: str
    persistence_class: str


def _zip_member(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(filename=name, date_time=_FIXED_ZIP_DATE)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    return info, data


def build_document_bundle_bytes(
    *,
    original_bytes: bytes,
    proposal: ParsedDocumentProposal,
    source_filename: str,
) -> bytes:
    if not isinstance(original_bytes, bytes):
        raise DocumentArtifactConsumerError("original_bytes must be exact bytes")
    if _sha256_bytes(original_bytes) != proposal.input_sha256:
        raise DocumentArtifactConsumerError("original bytes do not match proposal input SHA")
    if proposal.input_format not in {"pdf", "docx"}:
        raise DocumentArtifactConsumerError("proposal input format is not allowlisted")
    if not isinstance(source_filename, str) or not source_filename:
        raise DocumentArtifactConsumerError("source_filename must be non-empty")
    if Path(source_filename).name != source_filename:
        raise DocumentArtifactConsumerError("source_filename must not contain a path")
    expected_suffix = ".pdf" if proposal.input_format == "pdf" else ".docx"
    if Path(source_filename).suffix.lower() != expected_suffix:
        raise DocumentArtifactConsumerError("source_filename extension does not match proposal format")

    try:
        json.loads(proposal.json_bytes.decode("utf-8"))
        proposal.markdown_bytes.decode("utf-8")
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DocumentArtifactConsumerError("proposal output is not valid UTF-8 Markdown/JSON") from exc

    if _sha256_bytes(proposal.markdown_bytes) != proposal.markdown_sha256:
        raise DocumentArtifactConsumerError("proposal Markdown SHA mismatch")
    if _sha256_bytes(proposal.json_bytes) != proposal.json_sha256:
        raise DocumentArtifactConsumerError("proposal JSON SHA mismatch")

    original_member = "original" + expected_suffix
    provenance = {
        "schema": _PROVENANCE_SCHEMA,
        "bundle_schema": _BUNDLE_SCHEMA,
        "source_filename": source_filename,
        "input_format": proposal.input_format,
        "input_sha256": proposal.input_sha256,
        "markdown_sha256": proposal.markdown_sha256,
        "json_sha256": proposal.json_sha256,
        "parser_binding": dict(proposal.parser_binding),
        "warnings": list(proposal.warnings),
        "authority": {
            "original_bytes": "RUNTIME_BUNDLE_MEMBER_EXACT_SOURCE_BYTES",
            "derived_markdown": "RUNTIME_OWNED_DERIVED_BYTES",
            "derived_json": "RUNTIME_OWNED_DERIVED_BYTES",
            "external_parser_output": "VALIDATED_PROPOSAL_CONSUMED_BY_RUNTIME",
        },
    }
    provenance_bytes = _canonical_json_bytes(provenance)

    members = {
        original_member: original_bytes,
        "document.md": proposal.markdown_bytes,
        "document.json": proposal.json_bytes,
        "provenance.json": provenance_bytes,
    }
    member_rows = [
        {
            "path": name,
            "bytes": len(data),
            "sha256": _sha256_bytes(data),
        }
        for name, data in sorted(members.items())
    ]
    manifest = {
        "schema": _MANIFEST_SCHEMA,
        "bundle_schema": _BUNDLE_SCHEMA,
        "member_count": len(member_rows),
        "members": member_rows,
    }
    manifest_bytes = _canonical_json_bytes(manifest)

    final_members = {
        "00_DOCUMENT_BUNDLE_MANIFEST.json": manifest_bytes,
        **members,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(final_members):
            info, data = _zip_member(name, final_members[name])
            archive.writestr(info, data)
    bundle_bytes = output.getvalue()

    # Closed-world self-validation before returning bytes to ArtifactStore.
    with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as archive:
        names = set(archive.namelist())
        if names != set(final_members):
            raise DocumentArtifactConsumerError("document bundle closed-world member mismatch")
        for name, expected in final_members.items():
            actual = archive.read(name)
            if actual != expected:
                raise DocumentArtifactConsumerError(f"document bundle byte mismatch: {name}")
    return bundle_bytes


_LIBRECHAT_NATIVE_DOCUMENT_MAX_BYTES = 15 * 1024 * 1024
_LIBRECHAT_NATIVE_DOCUMENT_FORMATS = {
    ".docx": {"input_format": "docx", "original_member": "original.docx", "parser_engine": "mammoth"},
    ".pdf": {"input_format": "pdf", "original_member": "original.pdf", "parser_engine": "pdfjs-dist"},
}


@dataclass(frozen=True)
class ValidatedLibreChatNativeDocumentBundle:
    source_filename: str
    input_format: str
    input_sha256: str
    markdown_sha256: str
    json_sha256: str
    member_manifest_sha256: str


def validate_librechat_native_document_bundle_bytes(
    *,
    bundle_bytes: bytes,
    expected_source_filename: str,
) -> ValidatedLibreChatNativeDocumentBundle:
    """Validate one externally assembled LibreChat-native PDF/DOCX proposal bundle before persistence."""
    if not isinstance(bundle_bytes, bytes) or not bundle_bytes:
        raise DocumentArtifactConsumerError("prebuilt document bundle bytes must be non-empty")
    if (
        not isinstance(expected_source_filename, str)
        or not expected_source_filename
        or Path(expected_source_filename).name != expected_source_filename
    ):
        raise DocumentArtifactConsumerError("expected_source_filename must be one base name")
    suffix = Path(expected_source_filename).suffix.lower()
    format_spec = _LIBRECHAT_NATIVE_DOCUMENT_FORMATS.get(suffix)
    if format_spec is None:
        raise DocumentArtifactConsumerError("expected_source_filename must be PDF or DOCX")
    original_member = format_spec["original_member"]

    expected_names = {
        "00_DOCUMENT_BUNDLE_MANIFEST.json",
        original_member,
        "document.md",
        "document.json",
        "provenance.json",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(expected_names) or len(set(names)) != len(names) or set(names) != expected_names:
                raise DocumentArtifactConsumerError("prebuilt document bundle closed-world member mismatch")
            for info in infos:
                if info.compress_type != zipfile.ZIP_STORED or (info.flag_bits & 0x1):
                    raise DocumentArtifactConsumerError("prebuilt document bundle members must be unencrypted ZIP_STORED")
            members = {name: archive.read(name) for name in expected_names}
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError) as exc:
        if isinstance(exc, DocumentArtifactConsumerError):
            raise
        raise DocumentArtifactConsumerError("prebuilt document bundle ZIP is invalid") from exc

    original_bytes = members[original_member]
    if not original_bytes or len(original_bytes) > _LIBRECHAT_NATIVE_DOCUMENT_MAX_BYTES:
        raise DocumentArtifactConsumerError("prebuilt document original bytes exceed native parser contract")

    try:
        manifest = json.loads(members["00_DOCUMENT_BUNDLE_MANIFEST.json"].decode("utf-8"))
        provenance = json.loads(members["provenance.json"].decode("utf-8"))
        neutral = json.loads(members["document.json"].decode("utf-8"))
        decoded_text = members["document.md"].decode("utf-8")
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DocumentArtifactConsumerError("prebuilt document bundle JSON/text is invalid UTF-8") from exc

    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != _MANIFEST_SCHEMA
        or manifest.get("bundle_schema") != _BUNDLE_SCHEMA
        or manifest.get("member_count") != 4
        or not isinstance(manifest.get("members"), list)
        or len(manifest["members"]) != 4
    ):
        raise DocumentArtifactConsumerError("prebuilt document bundle manifest is invalid")
    expected_member_names = expected_names - {"00_DOCUMENT_BUNDLE_MANIFEST.json"}
    row_map: dict[str, dict[str, object]] = {}
    for row in manifest["members"]:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise DocumentArtifactConsumerError("prebuilt document bundle manifest row is invalid")
        member_path = row["path"]
        if member_path in row_map:
            raise DocumentArtifactConsumerError("prebuilt document bundle manifest path is duplicated")
        row_map[member_path] = row
    if set(row_map) != expected_member_names:
        raise DocumentArtifactConsumerError("prebuilt document bundle manifest member set is invalid")
    for name in expected_member_names:
        data = members[name]
        row = row_map[name]
        if row.get("bytes") != len(data) or row.get("sha256") != _sha256_bytes(data):
            raise DocumentArtifactConsumerError(f"prebuilt document bundle member binding mismatch: {name}")

    input_format = format_spec["input_format"]
    if (
        not isinstance(provenance, dict)
        or provenance.get("schema") != _PROVENANCE_SCHEMA
        or provenance.get("bundle_schema") != _BUNDLE_SCHEMA
        or provenance.get("source_filename") != expected_source_filename
        or provenance.get("input_format") != input_format
    ):
        raise DocumentArtifactConsumerError("prebuilt document provenance is invalid")
    input_sha = _sha256_bytes(original_bytes)
    markdown_sha = _sha256_bytes(members["document.md"])
    json_sha = _sha256_bytes(members["document.json"])
    if (
        provenance.get("input_sha256") != input_sha
        or provenance.get("markdown_sha256") != markdown_sha
        or provenance.get("json_sha256") != json_sha
    ):
        raise DocumentArtifactConsumerError("prebuilt document provenance SHA binding is invalid")

    parser_binding = provenance.get("parser_binding")
    version_fields = (
        parser_binding.get("component_version") if isinstance(parser_binding, dict) else None,
        parser_binding.get("parser_engine_version") if isinstance(parser_binding, dict) else None,
        parser_binding.get("bundle_writer_version") if isinstance(parser_binding, dict) else None,
    )
    if (
        not isinstance(parser_binding, dict)
        or parser_binding.get("component") != "@librechat/api.parseDocument"
        or parser_binding.get("parser_engine") != format_spec["parser_engine"]
        or parser_binding.get("bundle_writer") != "jszip"
        or parser_binding.get("delivery_path") != "document_parser"
        or parser_binding.get("authority_class") != "NON_AUTHORITY_NATIVE_PARSER_PROPOSAL"
        or parser_binding.get("output_contract") != "plain_text"
        or any(
            not isinstance(value, str)
            or not value
            or len(value) > 64
            or re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]*", value) is None
            for value in version_fields
        )
    ):
        raise DocumentArtifactConsumerError("prebuilt document parser provenance is not allowlisted")

    expected_authority = {
        "original_bytes": "RUNTIME_BUNDLE_MEMBER_EXACT_SOURCE_BYTES",
        "derived_markdown": "RUNTIME_OWNED_DERIVED_BYTES",
        "derived_json": "RUNTIME_OWNED_DERIVED_BYTES",
        "external_parser_output": "VALIDATED_PROPOSAL_CONSUMED_BY_RUNTIME",
    }
    if provenance.get("authority") != expected_authority:
        raise DocumentArtifactConsumerError("prebuilt document authority contract is invalid")
    warnings = provenance.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise DocumentArtifactConsumerError("prebuilt document warnings are invalid")

    if (
        not isinstance(neutral, dict)
        or neutral.get("schema") != "UR_LIBRECHAT_NATIVE_DOCUMENT_TEXT_R001"
        or neutral.get("source_filename") != expected_source_filename
        or neutral.get("text") != decoded_text
        or neutral.get("text_sha256") != markdown_sha
    ):
        raise DocumentArtifactConsumerError("prebuilt document neutral text projection is invalid")

    return ValidatedLibreChatNativeDocumentBundle(
        source_filename=expected_source_filename,
        input_format=input_format,
        input_sha256=input_sha,
        markdown_sha256=markdown_sha,
        json_sha256=json_sha,
        member_manifest_sha256=_sha256_bytes(members["00_DOCUMENT_BUNDLE_MANIFEST.json"]),
    )


def persist_librechat_native_document_bundle(
    *,
    store: ArtifactStore,
    bundle_bytes: bytes,
    expected_source_filename: str,
    job_id: str,
) -> DocumentBundleArtifact:
    """Validate, atomically persist, and read back one LibreChat-native PDF/DOCX bundle."""
    if not isinstance(store, ArtifactStore):
        raise DocumentArtifactConsumerError("store must be an ArtifactStore")
    if not isinstance(job_id, str) or not job_id:
        raise DocumentArtifactConsumerError("job_id must be non-empty")
    validated = validate_librechat_native_document_bundle_bytes(
        bundle_bytes=bundle_bytes,
        expected_source_filename=expected_source_filename,
    )
    bundle_sha = _sha256_bytes(bundle_bytes)
    try:
        binding, manifest = store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=bundle_sha,
            artifact_bytes=bundle_bytes,
            job_id=job_id,
            persistence_class=PersistenceClass.WORKING,
            expected_artifact_sha256=bundle_sha,
        )
    except (R009OpaqueArtifactError, OSError, PermissionError, ValueError) as exc:
        raise DocumentArtifactConsumerError("Runtime prebuilt document bundle commit failed") from exc
    persisted = Path(manifest.path).read_bytes()
    if persisted != bundle_bytes or _sha256_bytes(persisted) != binding.artifact_sha256:
        raise DocumentArtifactConsumerError("persisted prebuilt document bundle read-back mismatch")
    return DocumentBundleArtifact(
        artifact_id=manifest.artifact_id,
        artifact_revision=manifest.revision,
        artifact_sha256=manifest.sha256,
        input_sha256=validated.input_sha256,
        input_format=validated.input_format,
        markdown_sha256=validated.markdown_sha256,
        json_sha256=validated.json_sha256,
        member_manifest_sha256=validated.member_manifest_sha256,
        persistence_class=manifest.persistence_class.value,
    )

def persist_local_document_bundle(
    *,
    store: ArtifactStore,
    input_path: Path | str,
    expected_input_sha256: str,
    allowed_roots: tuple[Path | str, ...],
    parse_work_root: Path | str,
    sidecar: DoclingSidecarBinding,
    job_id: str,
    timeout_seconds: int = 120,
) -> DocumentBundleArtifact:
    """Parse one exact local PDF/DOCX and atomically persist one Runtime-owned bundle.

    This first slice deliberately persists ONE opaque bundle Artifact, not several
    independently committed Artifacts. That preserves transaction-or-nothing
    semantics using the existing exact opaque ArtifactStore primitive.
    """
    if not isinstance(store, ArtifactStore):
        raise DocumentArtifactConsumerError("store must be an ArtifactStore")
    if not isinstance(job_id, str) or not job_id:
        raise DocumentArtifactConsumerError("job_id must be non-empty")

    source = Path(input_path).resolve()
    source_name = source.name
    before = source.read_bytes()
    if _sha256_bytes(before) != expected_input_sha256:
        raise DocumentArtifactConsumerError("input SHA mismatch before adapter call")

    proposal = parse_local_document_proposal(
        input_path=source,
        expected_input_sha256=expected_input_sha256,
        allowed_roots=allowed_roots,
        work_root=parse_work_root,
        sidecar=sidecar,
        timeout_seconds=timeout_seconds,
    )

    after = source.read_bytes()
    if after != before or _sha256_bytes(after) != expected_input_sha256:
        raise DocumentArtifactConsumerError("input bytes changed before Runtime commit")

    bundle_bytes = build_document_bundle_bytes(
        original_bytes=before,
        proposal=proposal,
        source_filename=source_name,
    )
    bundle_sha = _sha256_bytes(bundle_bytes)

    try:
        binding, manifest = store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=bundle_sha,
            artifact_bytes=bundle_bytes,
            job_id=job_id,
            persistence_class=PersistenceClass.WORKING,
            expected_artifact_sha256=bundle_sha,
        )
    except (R009OpaqueArtifactError, OSError, PermissionError, ValueError) as exc:
        raise DocumentArtifactConsumerError("Runtime ArtifactStore bundle commit failed") from exc

    # Re-open exact persisted bytes and validate the bundle after commit.
    persisted = Path(manifest.path).read_bytes()
    if persisted != bundle_bytes or _sha256_bytes(persisted) != binding.artifact_sha256:
        raise DocumentArtifactConsumerError("persisted bundle read-back mismatch")
    with zipfile.ZipFile(io.BytesIO(persisted), "r") as archive:
        member_manifest_bytes = archive.read("00_DOCUMENT_BUNDLE_MANIFEST.json")
        member_manifest_sha = _sha256_bytes(member_manifest_bytes)

    return DocumentBundleArtifact(
        artifact_id=manifest.artifact_id,
        artifact_revision=manifest.revision,
        artifact_sha256=manifest.sha256,
        input_sha256=proposal.input_sha256,
        input_format=proposal.input_format,
        markdown_sha256=proposal.markdown_sha256,
        json_sha256=proposal.json_sha256,
        member_manifest_sha256=member_manifest_sha,
        persistence_class=manifest.persistence_class.value,
    )
