"""Runtime-owned directory Pack promotion authority first slice (R005 contract revision)."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from .enums import PersistenceClass
from .hashing import sha256_bytes
from .models import ArtifactManifest


class PackPromotionError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PACK_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED_BASES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_WINDOWS_INVALID_CHARS = set('<>:"\\|?*')
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/])")
_WINDOWS_UNC_PATH_RE = re.compile(
    r"""(?i)(?<![:A-Za-z0-9])(?:\\\\|//)[^\\/\s"'<>|]+[\\/][^\\/\s"'<>|]+"""
)
_RAW_EXECUTOR_HANDLE_RE = re.compile(r"(?i)\bagent:desktop-[A-Za-z0-9._-]+:[A-Za-z0-9._:-]+\b")
_PORTABLE_TEXT_SUFFIXES = {
    ".cjs", ".js", ".json", ".md", ".mjs", ".ps1", ".py",
    ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}

LEGACY_PACK_PROMOTION_CONTRACT_REVISIONS = frozenset({"MINIMUM_PACK_PROMOTION_CONTRACT_R005"})
PACK_PROMOTION_CONTRACT_REVISION = "MINIMUM_PACK_PROMOTION_CONTRACT_R006"
SUPPORTED_PACK_PROMOTION_CONTRACT_REVISIONS = (
    LEGACY_PACK_PROMOTION_CONTRACT_REVISIONS | {PACK_PROMOTION_CONTRACT_REVISION}
)
PACK_CONTENT_MANIFEST_SCHEMA_REVISION = "RUNTIME_PACK_CONTENT_MANIFEST_R001"
PACK_PROMOTION_RECEIPT_SCHEMA_REVISION = "RUNTIME_PACK_PROMOTION_RECEIPT_R002"

PACK_PROMOTION_REVIEW = "PACK_PROMOTION_REVIEW"
PACK_PROMOTION_HUMAN_APPROVAL = "PACK_PROMOTION_HUMAN_APPROVAL"
PACK_PROMOTION_COMMIT = "PACK_PROMOTION_COMMIT"
IMMUTABLE_ARTIFACT_REVISION = 1


@dataclass(frozen=True)
class PromotionArtifactBinding:
    artifact_id: str
    revision: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or _ARTIFACT_ID_RE.fullmatch(self.artifact_id) is None:
            raise PackPromotionError("invalid immutable promotion artifact_id")
        if self.revision != IMMUTABLE_ARTIFACT_REVISION:
            raise PackPromotionError("immutable promotion artifact revision must be exactly 1")
        if not _valid_sha256(self.sha256):
            raise PackPromotionError("immutable promotion artifact sha256 must be lowercase 64-hex")

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreparedPackCandidate:
    candidate_path: str
    source_content_manifest_path: str
    pack_id: str
    pack_version: str
    source_content_manifest_sha256: str
    pack_yaml_sha256: str
    promoted_content_manifest_sha256: str
    promoted_content_manifest: dict[str, Any]
    file_entries: tuple[tuple[str, int, str], ...]


@dataclass(frozen=True)
class PackPromotionRequest:
    candidate_path: Path
    source_content_manifest_path: Path
    pack_id: str
    pack_version: str
    source_content_manifest_sha256: str
    pack_yaml_sha256: str
    expected_promoted_content_manifest_sha256: str
    review_artifact: PromotionArtifactBinding
    approval_artifact: PromotionArtifactBinding


@dataclass(frozen=True)
class PackPromotionReceipt:
    schema_revision: str
    contract_revision: str
    promotion_id: str
    pack_id: str
    pack_version: str
    source_content_manifest_sha256: str
    pack_yaml_sha256: str
    review_receipt_sha256: str
    promoted_content_manifest_sha256: str
    review_artifact_id: str
    review_artifact_revision: int
    review_artifact_sha256: str
    approval_artifact_id: str
    approval_artifact_revision: int
    approval_artifact_sha256: str
    approval_id: str
    approver_id: str
    persistence_class: str
    source_candidate_path: str
    source_content_manifest_path: str

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError as exc:
        raise PackPromotionError(f"cannot lstat filesystem path: {path}") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse_flag)


def _assert_no_reparse_chain(root: Path, target: Path) -> None:
    root = _lexical_absolute(root)
    target = _lexical_absolute(target)
    if not _is_relative_to(target, root):
        raise PackPromotionError("path escapes exact allowlisted root")
    current = root
    if current.exists() and _is_reparse_or_symlink(current):
        raise PackPromotionError(f"reparse/symlink path is forbidden: {current}")
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and _is_reparse_or_symlink(current):
            raise PackPromotionError(f"reparse/symlink path is forbidden: {current}")


def _validate_pack_component(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _PACK_COMPONENT_RE.fullmatch(value):
        raise PackPromotionError(f"invalid {field} for authoritative directory identity")
    return value


def _windows_reserved_component(component: str) -> bool:
    base = component.split(".", 1)[0].upper()
    return base in _WINDOWS_RESERVED_BASES


def _canonical_relative_pack_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise PackPromotionError("manifest path must be a non-empty relative string")
    if value.startswith("/") or "\\" in value or ":" in value:
        raise PackPromotionError(f"illegal manifest path: {value}")
    if any(ord(ch) < 32 or ch == "\x7f" for ch in value):
        raise PackPromotionError(f"control character in manifest path: {value}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PackPromotionError(f"illegal manifest path component: {value}")
    for part in parts:
        if any(ch in _WINDOWS_INVALID_CHARS for ch in part):
            raise PackPromotionError(f"Windows-invalid manifest path component: {value}")
        if part.endswith(" ") or part.endswith("."):
            raise PackPromotionError(f"Windows trailing dot/space path component: {value}")
        if _windows_reserved_component(part):
            raise PackPromotionError(f"Windows reserved device path component: {value}")
    return "/".join(parts)


def _windows_collision_key(path: str) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in path.split("/"))


def _runtime_relative_locator(runtime_root: Path, target: Path | str, *, field: str) -> str:
    root = _lexical_absolute(runtime_root)
    resolved = _lexical_absolute(target)
    if not _is_relative_to(resolved, root):
        raise PackPromotionError(f"{field} escapes Runtime root")
    relative = resolved.relative_to(root).as_posix()
    try:
        return _canonical_relative_pack_path(relative)
    except PackPromotionError as exc:
        raise PackPromotionError(f"invalid portable {field}: {relative}") from exc


def _validate_runtime_relative_locator(value: Any, *, field: str) -> str:
    try:
        return _canonical_relative_pack_path(value)
    except PackPromotionError as exc:
        raise PackPromotionError(f"invalid portable {field}") from exc


def _legacy_locator_matches(value: Any, expected_relative: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    normalized = value.replace("\\", "/").rstrip("/")
    expected = expected_relative.strip("/")
    return normalized == expected or normalized.endswith("/" + expected)


def _assert_portable_candidate_content(
    actual_files: dict[str, Path],
    substantive_paths: tuple[str, ...],
) -> None:
    for rel in substantive_paths:
        target = actual_files[rel]
        if target.suffix.lower() not in _PORTABLE_TEXT_SUFFIXES:
            continue
        try:
            text = target.read_text(encoding="utf-8-sig")
        except UnicodeError as exc:
            raise PackPromotionError(f"portable text Pack content is not UTF-8: {rel}") from exc
        for line_no, line in enumerate(text.splitlines(), 1):
            if (
                _WINDOWS_ABSOLUTE_PATH_RE.search(line)
                or _WINDOWS_UNC_PATH_RE.search(line)
            ):
                raise PackPromotionError(
                    f"portable Pack content contains absolute Windows path: {rel}:{line_no}"
                )
            if _RAW_EXECUTOR_HANDLE_RE.search(line):
                raise PackPromotionError(
                    f"portable Pack content contains raw executor handle: {rel}:{line_no}"
                )


def _normalized_source_entries(raw_manifest: dict[str, Any]) -> tuple[str, str, tuple[tuple[str, int, str], ...]]:
    pack_id = _validate_pack_component(raw_manifest.get("pack_id"), field="pack_id")
    pack_version = _validate_pack_component(raw_manifest.get("pack_version"), field="pack_version")
    files = raw_manifest.get("files")
    if not isinstance(files, list) or not files:
        raise PackPromotionError("source content manifest files must be a non-empty list")
    exact_seen: set[str] = set()
    collision_seen: dict[tuple[str, ...], str] = {}
    entries: list[tuple[str, int, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise PackPromotionError("source content manifest file entry must be a mapping")
        path = _canonical_relative_pack_path(item.get("path"))
        if path in exact_seen:
            raise PackPromotionError(f"duplicate manifest path: {path}")
        key = _windows_collision_key(path)
        previous = collision_seen.get(key)
        if previous is not None and previous != path:
            raise PackPromotionError(f"Windows path normalization collision: {previous} vs {path}")
        exact_seen.add(path)
        collision_seen[key] = path
        size = item.get("size")
        sha = item.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise PackPromotionError(f"invalid size for manifest path: {path}")
        if not isinstance(sha, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", sha) is None:
            raise PackPromotionError(f"invalid SHA256 for manifest path: {path}")
        entries.append((path, size, sha.lower()))
    entries.sort(key=lambda row: row[0])
    return pack_id, pack_version, tuple(entries)


def _enumerate_candidate_files(candidate: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    collision_seen: dict[tuple[str, ...], str] = {}
    stack = [candidate]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise PackPromotionError(f"cannot enumerate candidate directory: {current}") from exc
        for entry in entries:
            path = Path(entry.path)
            if _is_reparse_or_symlink(path):
                raise PackPromotionError(f"reparse/symlink content is forbidden: {path}")
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise PackPromotionError(f"unsupported candidate filesystem entry: {path}")
            rel = path.relative_to(candidate).as_posix()
            rel = _canonical_relative_pack_path(rel)
            key = _windows_collision_key(rel)
            previous = collision_seen.get(key)
            if previous is not None and previous != rel:
                raise PackPromotionError(f"Windows path normalization collision: {previous} vs {rel}")
            collision_seen[key] = rel
            found[rel] = path
    return found


def _runtime_promoted_manifest(pack_id: str, pack_version: str, entries: tuple[tuple[str, int, str], ...]) -> dict[str, Any]:
    return {
        "schema_revision": PACK_CONTENT_MANIFEST_SCHEMA_REVISION,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "files": [
            {"path": path, "sha256": sha, "size_bytes": size}
            for path, size, sha in entries
        ],
    }


def _validate_promoted_manifest_object(raw: Any) -> tuple[str, str, tuple[tuple[str, int, str], ...]]:
    if not isinstance(raw, dict) or raw.get("schema_revision") != PACK_CONTENT_MANIFEST_SCHEMA_REVISION:
        raise PackPromotionError("invalid promoted content manifest schema")
    pack_id = _validate_pack_component(raw.get("pack_id"), field="pack_id")
    pack_version = _validate_pack_component(raw.get("pack_version"), field="pack_version")
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise PackPromotionError("invalid promoted content manifest files")
    exact_seen: set[str] = set()
    collision_seen: dict[tuple[str, ...], str] = {}
    rows: list[tuple[str, int, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise PackPromotionError("invalid promoted content manifest entry")
        path = _canonical_relative_pack_path(item.get("path"))
        if path in exact_seen:
            raise PackPromotionError(f"duplicate promoted content path: {path}")
        key = _windows_collision_key(path)
        previous = collision_seen.get(key)
        if previous is not None and previous != path:
            raise PackPromotionError(f"promoted content Windows path collision: {previous} vs {path}")
        exact_seen.add(path)
        collision_seen[key] = path
        size = item.get("size_bytes")
        sha = item.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or not _valid_sha256(sha):
            raise PackPromotionError(f"invalid promoted content identity for path: {path}")
        rows.append((path, size, sha))
    if rows != sorted(rows, key=lambda row: row[0]):
        raise PackPromotionError("promoted content manifest files must be canonically sorted")
    return pack_id, pack_version, tuple(rows)




def _pack_key_bytes(pack_id: str, pack_version: str) -> bytes:
    return _canonical({"pack_id": pack_id, "pack_version": pack_version})


def _pack_key_sha256(pack_id: str, pack_version: str) -> str:
    return sha256_bytes(_pack_key_bytes(pack_id, pack_version))


def _review_artifact_id(payload_sha256: str) -> str:
    if not _valid_sha256(payload_sha256):
        raise PackPromotionError("invalid review payload SHA256")
    return f"PACK_PROMOTION_REVIEW_{payload_sha256.upper()}"


def _approval_artifact_id(payload_sha256: str) -> str:
    if not _valid_sha256(payload_sha256):
        raise PackPromotionError("invalid approval payload SHA256")
    return f"PACK_PROMOTION_APPROVAL_{payload_sha256.upper()}"


def _commit_artifact_id(pack_id: str, pack_version: str) -> str:
    return f"PACK_PROMOTION_COMMIT_{_pack_key_sha256(pack_id, pack_version).upper()}"


def _promotion_store_root(runtime_root: Path) -> Path:
    return _lexical_absolute(runtime_root) / "artifacts" / "pack_promotion_authority"


def _artifact_manifest_path(store_root: Path, artifact_id: str) -> Path:
    if not isinstance(artifact_id, str) or _ARTIFACT_ID_RE.fullmatch(artifact_id) is None:
        raise PackPromotionError("invalid immutable promotion artifact_id")
    return _lexical_absolute(store_root) / "_manifests" / artifact_id / "R001.json"


def _immutable_payload_path(
    store_root: Path,
    *,
    evidence_class: str,
    artifact_id: str,
    payload_sha256: str,
    pack_key_sha256: str | None = None,
) -> Path:
    root = _lexical_absolute(store_root)
    if evidence_class == PACK_PROMOTION_REVIEW:
        if artifact_id != _review_artifact_id(payload_sha256):
            raise PackPromotionError("review artifact id/content address mismatch")
        return root / "immutable" / "review" / f"{payload_sha256}.json"
    if evidence_class == PACK_PROMOTION_HUMAN_APPROVAL:
        if artifact_id != _approval_artifact_id(payload_sha256):
            raise PackPromotionError("approval artifact id/content address mismatch")
        return root / "immutable" / "approval" / f"{payload_sha256}.json"
    if evidence_class == PACK_PROMOTION_COMMIT:
        if not _valid_sha256(pack_key_sha256):
            raise PackPromotionError("commit pack-key SHA is invalid")
        if artifact_id != f"PACK_PROMOTION_COMMIT_{pack_key_sha256.upper()}":
            raise PackPromotionError("commit artifact id/pack-key mismatch")
        return root / "commits" / pack_key_sha256 / f"{payload_sha256}.json"
    raise PackPromotionError("unsupported immutable promotion evidence class")


def _artifact_job_id(evidence_class: str, artifact_id: str) -> str:
    return f"PACK_PROMOTION:{evidence_class}:{artifact_id}"


def _artifact_metadata(
    evidence_class: str,
    contract_revision: str = PACK_PROMOTION_CONTRACT_REVISION,
) -> dict[str, Any]:
    if contract_revision not in SUPPORTED_PACK_PROMOTION_CONTRACT_REVISIONS:
        raise PackPromotionError("unsupported promotion artifact contract revision")
    return {
        "immutable": True,
        "promotion_evidence_class": evidence_class,
        "contract_revision": contract_revision,
    }


def _safe_mkdir_under(root: Path, target: Path) -> None:
    root = _lexical_absolute(root)
    target = _lexical_absolute(target)
    if not _is_relative_to(target, root):
        raise PackPromotionError("directory creation escapes exact allowlisted root")
    _assert_no_reparse_chain(root, target.parent if target != root else target)
    target.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_chain(root, target)


def _write_temp_file_verified(final: Path, data: bytes, *, label: str) -> Path:
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = parent / f".{final.name}.{label}.tmp-{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise
    check = temp.read_bytes()
    if check != data or sha256_bytes(check) != sha256_bytes(data):
        temp.unlink(missing_ok=True)
        raise PackPromotionError(f"{label} temp byte-preservation verification failed")
    return temp


def _publish_file_destination_absent(temp: Path, final: Path) -> None:
    if final.exists():
        raise FileExistsError(str(final))
    if os.name == "nt":
        os.rename(temp, final)
        return
    # Development/test portability only. Production first slice is Windows.
    os.link(temp, final)
    temp.unlink()


def _cleanup_temp_files(parent: Path, prefix: str) -> None:
    if not parent.is_dir():
        return
    for path in parent.glob(prefix + "*"):
        if path.is_file() and not path.is_symlink():
            path.unlink(missing_ok=True)


def _load_artifact_manifest(path: Path) -> ArtifactManifest:
    try:
        return ArtifactManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackPromotionError(f"immutable promotion artifact manifest is invalid: {path}") from exc


def _load_exact_immutable_artifact(
    runtime_root: Path,
    binding: PromotionArtifactBinding,
    *,
    expected_class: str,
    expected_persistence: PersistenceClass,
    expected_pack_id: str | None = None,
    expected_pack_version: str | None = None,
) -> tuple[dict[str, Any], ArtifactManifest, Path]:
    runtime_root = _lexical_absolute(runtime_root)
    store_root = _promotion_store_root(runtime_root)
    if not store_root.is_dir():
        raise PackPromotionError("Pack promotion authority store is missing")
    _assert_no_reparse_chain(runtime_root, store_root)

    manifest_path = _artifact_manifest_path(store_root, binding.artifact_id)
    if not manifest_path.is_file() or _is_reparse_or_symlink(manifest_path):
        raise PackPromotionError("exact immutable promotion artifact R001 manifest is missing")
    manifest = _load_artifact_manifest(manifest_path)
    metadata = manifest.metadata
    metadata_contract_revision = (
        metadata.get("contract_revision") if isinstance(metadata, dict) else None
    )
    if (
        manifest.artifact_id != binding.artifact_id
        or manifest.revision != IMMUTABLE_ARTIFACT_REVISION
        or manifest.sha256 != binding.sha256
        or manifest.persistence_class != expected_persistence
        or manifest.job_id != _artifact_job_id(expected_class, binding.artifact_id)
        or not isinstance(metadata, dict)
        or set(metadata) != {"immutable", "promotion_evidence_class", "contract_revision"}
        or metadata.get("immutable") is not True
        or metadata.get("promotion_evidence_class") != expected_class
        or metadata_contract_revision not in SUPPORTED_PACK_PROMOTION_CONTRACT_REVISIONS
    ):
        raise PackPromotionError("immutable promotion artifact manifest binding mismatch")

    if expected_class == PACK_PROMOTION_REVIEW:
        expected_path = _immutable_payload_path(
            store_root,
            evidence_class=expected_class,
            artifact_id=binding.artifact_id,
            payload_sha256=binding.sha256,
        )
    elif expected_class == PACK_PROMOTION_HUMAN_APPROVAL:
        expected_path = _immutable_payload_path(
            store_root,
            evidence_class=expected_class,
            artifact_id=binding.artifact_id,
            payload_sha256=binding.sha256,
        )
    elif expected_class == PACK_PROMOTION_COMMIT:
        prefix = "PACK_PROMOTION_COMMIT_"
        if not binding.artifact_id.startswith(prefix):
            raise PackPromotionError("commit artifact id is invalid")
        key_sha = binding.artifact_id[len(prefix):].lower()
        if not _valid_sha256(key_sha):
            raise PackPromotionError("commit artifact pack-key SHA is invalid")
        expected_path = _immutable_payload_path(
            store_root,
            evidence_class=expected_class,
            artifact_id=binding.artifact_id,
            payload_sha256=binding.sha256,
            pack_key_sha256=key_sha,
        )
    else:
        raise PackPromotionError("unsupported immutable promotion evidence class")

    payload_path = _lexical_absolute(expected_path)
    expected_locator = _runtime_relative_locator(
        runtime_root,
        payload_path,
        field="artifact_manifest_path",
    )
    if metadata_contract_revision == PACK_PROMOTION_CONTRACT_REVISION:
        if manifest.path != expected_locator:
            raise PackPromotionError("portable immutable artifact manifest path mismatch")
    elif not _legacy_locator_matches(manifest.path, expected_locator):
        raise PackPromotionError("legacy immutable artifact manifest path mismatch")

    _assert_no_reparse_chain(store_root, payload_path)
    if not payload_path.is_file() or _is_reparse_or_symlink(payload_path):
        raise PackPromotionError("immutable promotion artifact payload is missing or redirected")
    payload_bytes = payload_path.read_bytes()
    if sha256_bytes(payload_bytes) != binding.sha256:
        raise PackPromotionError("immutable promotion artifact payload SHA mismatch")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackPromotionError("immutable promotion artifact payload is invalid JSON") from exc
    if _canonical(payload) != payload_bytes:
        raise PackPromotionError("immutable promotion artifact payload is not canonical JSON")
    if payload.get("evidence_class") != expected_class:
        raise PackPromotionError("immutable promotion artifact evidence class mismatch")

    if expected_class == PACK_PROMOTION_REVIEW:
        expected_path = _immutable_payload_path(
            store_root,
            evidence_class=expected_class,
            artifact_id=binding.artifact_id,
            payload_sha256=binding.sha256,
        )
    elif expected_class == PACK_PROMOTION_HUMAN_APPROVAL:
        expected_path = _immutable_payload_path(
            store_root,
            evidence_class=expected_class,
            artifact_id=binding.artifact_id,
            payload_sha256=binding.sha256,
        )
    elif expected_class == PACK_PROMOTION_COMMIT:
        pack_id = payload.get("pack_id")
        pack_version = payload.get("pack_version")
        if not isinstance(pack_id, str) or not isinstance(pack_version, str):
            raise PackPromotionError("commit artifact Pack identity is invalid")
        key_sha = _pack_key_sha256(pack_id, pack_version)
        expected_id = _commit_artifact_id(pack_id, pack_version)
        if binding.artifact_id != expected_id or payload.get("pack_key_sha256") != key_sha:
            raise PackPromotionError("commit artifact deterministic identity mismatch")
        expected_path = _immutable_payload_path(
            store_root,
            evidence_class=expected_class,
            artifact_id=binding.artifact_id,
            payload_sha256=binding.sha256,
            pack_key_sha256=key_sha,
        )
    else:
        raise PackPromotionError("unsupported immutable promotion evidence class")

    if payload_path != _lexical_absolute(expected_path):
        raise PackPromotionError("immutable promotion artifact payload path mismatch")
    if expected_pack_id is not None and payload.get("pack_id") != expected_pack_id:
        raise PackPromotionError("immutable promotion artifact pack_id mismatch")
    if expected_pack_version is not None and payload.get("pack_version") != expected_pack_version:
        raise PackPromotionError("immutable promotion artifact pack_version mismatch")
    return payload, manifest, payload_path


@contextmanager
def _pack_promotion_lock(runtime_root: Path) -> Iterator[None]:
    runtime_root = _lexical_absolute(runtime_root)
    if not runtime_root.is_dir():
        raise PackPromotionError("Runtime root is missing")
    authority_root = runtime_root / "_authoritative" / "packs"
    _assert_no_reparse_chain(runtime_root, authority_root.parent)
    _safe_mkdir_under(runtime_root, authority_root)
    lock_path = authority_root / ".pack_promotion.lock"
    if lock_path.exists() and _is_reparse_or_symlink(lock_path):
        raise PackPromotionError("Pack promotion lock path is redirected")
    with open(lock_path, "a+b") as fh:
        if fh.seek(0, os.SEEK_END) == 0:
            fh.write(b"\0")
            fh.flush()
            os.fsync(fh.fileno())
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _persist_immutable_artifact_locked(
    runtime_root: Path,
    payload: dict[str, Any],
    *,
    evidence_class: str,
    persistence_class: PersistenceClass,
    artifact_id: str | None = None,
) -> PromotionArtifactBinding:
    runtime_root = _lexical_absolute(runtime_root)
    store_root = _promotion_store_root(runtime_root)
    _assert_no_reparse_chain(runtime_root, store_root.parent)
    _safe_mkdir_under(runtime_root, store_root)

    payload_bytes = _canonical(payload)
    payload_sha = sha256_bytes(payload_bytes)

    if evidence_class == PACK_PROMOTION_REVIEW:
        expected_artifact_id = _review_artifact_id(payload_sha)
        pack_key_sha = None
    elif evidence_class == PACK_PROMOTION_HUMAN_APPROVAL:
        expected_artifact_id = _approval_artifact_id(payload_sha)
        pack_key_sha = None
    elif evidence_class == PACK_PROMOTION_COMMIT:
        pack_id = _validate_pack_component(payload.get("pack_id"), field="pack_id")
        pack_version = _validate_pack_component(payload.get("pack_version"), field="pack_version")
        pack_key_sha = _pack_key_sha256(pack_id, pack_version)
        expected_artifact_id = _commit_artifact_id(pack_id, pack_version)
    else:
        raise PackPromotionError("unsupported immutable promotion evidence class")

    if artifact_id is None:
        artifact_id = expected_artifact_id
    if artifact_id != expected_artifact_id:
        raise PackPromotionError("immutable promotion artifact deterministic ID mismatch")

    binding = PromotionArtifactBinding(
        artifact_id=artifact_id,
        revision=IMMUTABLE_ARTIFACT_REVISION,
        sha256=payload_sha,
    )
    manifest_path = _artifact_manifest_path(store_root, artifact_id)
    payload_path = _immutable_payload_path(
        store_root,
        evidence_class=evidence_class,
        artifact_id=artifact_id,
        payload_sha256=payload_sha,
        pack_key_sha256=pack_key_sha,
    )

    # Any final R001 switches this identity into immutable-history semantics.
    if manifest_path.exists():
        loaded, _manifest, _path = _load_exact_immutable_artifact(
            runtime_root,
            binding,
            expected_class=evidence_class,
            expected_persistence=persistence_class,
        )
        if loaded != payload:
            raise PackPromotionError("conflicting immutable promotion artifact R001")
        return binding

    _safe_mkdir_under(store_root, payload_path.parent)
    _cleanup_temp_files(payload_path.parent, f".{payload_path.name}.payload.tmp-")

    # Precommit payload publication/recovery. Re-check R001 absence before any cleanup.
    if payload_path.exists():
        existing = payload_path.read_bytes()
        if existing != payload_bytes or sha256_bytes(existing) != payload_sha:
            if manifest_path.exists():
                raise PackPromotionError("immutable promotion artifact R001 appeared; payload cleanup forbidden")
            payload_path.unlink()
            if manifest_path.exists():
                raise PackPromotionError("immutable promotion artifact R001 appeared during payload cleanup")
    if not payload_path.exists():
        temp_payload = _write_temp_file_verified(payload_path, payload_bytes, label="payload")
        try:
            try:
                _publish_file_destination_absent(temp_payload, payload_path)
            except (FileExistsError, OSError):
                if not payload_path.exists():
                    raise
                existing = payload_path.read_bytes()
                if existing != payload_bytes or sha256_bytes(existing) != payload_sha:
                    if manifest_path.exists():
                        raise PackPromotionError("immutable promotion artifact R001 appeared; payload race cleanup forbidden")
                    payload_path.unlink()
                    if manifest_path.exists():
                        raise PackPromotionError("immutable promotion artifact R001 appeared during payload race cleanup")
                    raise PackPromotionError("conflicting malformed precommit payload destination")
            final_bytes = payload_path.read_bytes()
            if final_bytes != payload_bytes or sha256_bytes(final_bytes) != payload_sha:
                if manifest_path.exists():
                    raise PackPromotionError("immutable promotion artifact payload changed after R001 appeared")
                payload_path.unlink(missing_ok=True)
                raise PackPromotionError("immutable promotion artifact final payload verification failed")
        finally:
            temp_payload.unlink(missing_ok=True)
    else:
        existing = payload_path.read_bytes()
        if existing != payload_bytes or sha256_bytes(existing) != payload_sha:
            raise PackPromotionError("immutable promotion artifact orphan payload mismatch")

    manifest = ArtifactManifest.now(
        artifact_id=artifact_id,
        revision=IMMUTABLE_ARTIFACT_REVISION,
        sha256=payload_sha,
        path=_runtime_relative_locator(
            runtime_root,
            payload_path,
            field="artifact_manifest_path",
        ),
        persistence_class=persistence_class,
        job_id=_artifact_job_id(evidence_class, artifact_id),
        input_fingerprint=None,
        metadata=_artifact_metadata(evidence_class),
    )
    manifest_bytes = manifest.model_dump_json(indent=2).encode("utf-8")
    manifest_dir = manifest_path.parent
    _safe_mkdir_under(store_root, manifest_dir)
    _cleanup_temp_files(manifest_dir, ".R001.json.manifest.tmp-")

    if manifest_path.exists():
        loaded, _manifest, _path = _load_exact_immutable_artifact(
            runtime_root,
            binding,
            expected_class=evidence_class,
            expected_persistence=persistence_class,
        )
        if loaded != payload:
            raise PackPromotionError("conflicting immutable promotion artifact R001")
        return binding

    temp_manifest = _write_temp_file_verified(manifest_path, manifest_bytes, label="manifest")
    try:
        try:
            _publish_file_destination_absent(temp_manifest, manifest_path)
        except (FileExistsError, OSError):
            if not manifest_path.exists():
                raise
        loaded, _manifest, _path = _load_exact_immutable_artifact(
            runtime_root,
            binding,
            expected_class=evidence_class,
            expected_persistence=persistence_class,
        )
        if loaded != payload:
            raise PackPromotionError("immutable promotion artifact exact replay mismatch")
    finally:
        temp_manifest.unlink(missing_ok=True)
    return binding


def _validate_review_payload(
    payload: dict[str, Any],
    *,
    prepared: PreparedPackCandidate,
) -> None:
    required = {
        "evidence_class",
        "pack_id",
        "pack_version",
        "source_content_manifest_sha256",
        "pack_yaml_sha256",
        "review_result",
        "review_receipt_sha256",
        "review_receipt_text",
    }
    if set(payload) != required:
        raise PackPromotionError("review evidence fields are invalid")
    if payload.get("evidence_class") != PACK_PROMOTION_REVIEW:
        raise PackPromotionError("review evidence class mismatch")
    if payload.get("review_result") != "PASS":
        raise PackPromotionError("Pack promotion review evidence must be PASS")
    if payload.get("pack_id") != prepared.pack_id or payload.get("pack_version") != prepared.pack_version:
        raise PackPromotionError("review evidence Pack identity mismatch")
    if payload.get("source_content_manifest_sha256") != prepared.source_content_manifest_sha256:
        raise PackPromotionError("review evidence source-manifest binding mismatch")
    if payload.get("pack_yaml_sha256") != prepared.pack_yaml_sha256:
        raise PackPromotionError("review evidence pack.yaml binding mismatch")
    text = payload.get("review_receipt_text")
    if not isinstance(text, str) or not text:
        raise PackPromotionError("review evidence exact receipt text is missing")
    review_sha = payload.get("review_receipt_sha256")
    if not _valid_sha256(review_sha) or sha256_bytes(text.encode("utf-8")) != review_sha:
        raise PackPromotionError("review evidence exact receipt SHA mismatch")


def _validate_approval_payload(
    payload: dict[str, Any],
    *,
    prepared: PreparedPackCandidate,
    review_binding: PromotionArtifactBinding,
) -> None:
    required = {
        "evidence_class",
        "approval_id",
        "approver_id",
        "approved",
        "pack_id",
        "pack_version",
        "source_content_manifest_sha256",
        "pack_yaml_sha256",
        "promoted_content_manifest_sha256",
        "review_artifact_id",
        "review_artifact_revision",
        "review_artifact_sha256",
    }
    if set(payload) != required:
        raise PackPromotionError("human approval evidence fields are invalid")
    if payload.get("evidence_class") != PACK_PROMOTION_HUMAN_APPROVAL:
        raise PackPromotionError("human approval evidence class mismatch")
    if type(payload.get("approved")) is not bool or payload.get("approved") is not True:
        raise PackPromotionError("explicit human Pack promotion approval must be exact Boolean true")
    for field in ("approval_id", "approver_id"):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            raise PackPromotionError("human approval identity is missing")
    if payload.get("pack_id") != prepared.pack_id or payload.get("pack_version") != prepared.pack_version:
        raise PackPromotionError("human approval Pack identity mismatch")
    if payload.get("source_content_manifest_sha256") != prepared.source_content_manifest_sha256:
        raise PackPromotionError("human approval source-manifest binding mismatch")
    if payload.get("pack_yaml_sha256") != prepared.pack_yaml_sha256:
        raise PackPromotionError("human approval pack.yaml binding mismatch")
    if payload.get("promoted_content_manifest_sha256") != prepared.promoted_content_manifest_sha256:
        raise PackPromotionError("human approval promoted-manifest binding mismatch")
    if (
        payload.get("review_artifact_id") != review_binding.artifact_id
        or payload.get("review_artifact_revision") != review_binding.revision
        or payload.get("review_artifact_sha256") != review_binding.sha256
    ):
        raise PackPromotionError("human approval review-artifact binding mismatch")


def _receipt_promotion_id(fields: dict[str, Any]) -> str:
    return sha256_bytes(_canonical(fields))


def _validate_operational_promoted_pack_record(
    final: Path,
    *,
    expected_pack_id: str | None = None,
    expected_pack_version: str | None = None,
    authority_root: Path | None = None,
    containment_root: Path | None = None,
) -> dict[str, Any]:
    final = _lexical_absolute(final)
    if authority_root is not None:
        authority_root = _lexical_absolute(authority_root)
        if containment_root is not None:
            containment_root = _lexical_absolute(containment_root)
            if not _is_relative_to(authority_root, containment_root):
                raise PackPromotionError("authoritative Pack root escapes Runtime containment root")
            _assert_no_reparse_chain(containment_root, authority_root)
        if not _is_relative_to(final, authority_root):
            raise PackPromotionError("authoritative Pack record escapes exact authority root")
        _assert_no_reparse_chain(authority_root, final)
    if not final.is_dir() or _is_reparse_or_symlink(final):
        raise PackPromotionError("authoritative Pack record is missing or uses a reparse point")
    expected_top = {"content", "content_manifest.json", "promotion_receipt.json"}
    actual_top = {entry.name for entry in os.scandir(final)}
    if actual_top != expected_top:
        raise PackPromotionError("authoritative Pack record has missing or extra top-level entries")
    content_root = final / "content"
    manifest_path = final / "content_manifest.json"
    receipt_path = final / "promotion_receipt.json"
    if not content_root.is_dir() or _is_reparse_or_symlink(content_root):
        raise PackPromotionError("authoritative content root is invalid")
    if not manifest_path.is_file() or _is_reparse_or_symlink(manifest_path):
        raise PackPromotionError("authoritative content manifest is invalid")
    if not receipt_path.is_file() or _is_reparse_or_symlink(receipt_path):
        raise PackPromotionError("authoritative promotion receipt is invalid")

    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_raw = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackPromotionError("cannot parse promoted content manifest") from exc
    if _canonical(manifest_raw) != manifest_bytes:
        raise PackPromotionError("promoted content manifest is not canonical")
    pack_id, pack_version, manifest_entries = _validate_promoted_manifest_object(manifest_raw)
    if expected_pack_id is not None and pack_id != expected_pack_id:
        raise PackPromotionError("authoritative Pack id mismatch")
    if expected_pack_version is not None and pack_version != expected_pack_version:
        raise PackPromotionError("authoritative Pack version mismatch")

    found = _enumerate_candidate_files(content_root)
    if set(found) != {row[0] for row in manifest_entries}:
        raise PackPromotionError("authoritative content file set does not match content manifest")
    measured: list[tuple[str, int, str]] = []
    for path, expected_size, expected_sha in manifest_entries:
        target = found[path]
        data = target.read_bytes()
        actual = (path, len(data), sha256_bytes(data))
        if actual != (path, expected_size, expected_sha):
            raise PackPromotionError(f"stale authoritative Pack content: {path}")
        measured.append(actual)
    if tuple(measured) != manifest_entries:
        raise PackPromotionError("authoritative Pack tuple identity mismatch")

    receipt_bytes = receipt_path.read_bytes()
    try:
        receipt_raw = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackPromotionError("cannot parse promotion receipt") from exc
    if _canonical(receipt_raw) != receipt_bytes:
        raise PackPromotionError("promotion receipt is not canonical")
    required_receipt = {
        "schema_revision", "contract_revision", "promotion_id", "pack_id", "pack_version",
        "source_content_manifest_sha256", "pack_yaml_sha256", "review_receipt_sha256",
        "promoted_content_manifest_sha256",
        "review_artifact_id", "review_artifact_revision", "review_artifact_sha256",
        "approval_artifact_id", "approval_artifact_revision", "approval_artifact_sha256",
        "approval_id", "approver_id", "persistence_class",
        "source_candidate_path", "source_content_manifest_path",
    }
    if set(receipt_raw) != required_receipt:
        raise PackPromotionError("promotion receipt fields are invalid")
    contract_revision = receipt_raw.get("contract_revision")
    if (
        receipt_raw.get("schema_revision") != PACK_PROMOTION_RECEIPT_SCHEMA_REVISION
        or contract_revision not in SUPPORTED_PACK_PROMOTION_CONTRACT_REVISIONS
    ):
        raise PackPromotionError("promotion receipt schema/contract mismatch")
    if contract_revision == PACK_PROMOTION_CONTRACT_REVISION:
        candidate_locator = _validate_runtime_relative_locator(
            receipt_raw.get("source_candidate_path"),
            field="source_candidate_path",
        )
        manifest_locator = _validate_runtime_relative_locator(
            receipt_raw.get("source_content_manifest_path"),
            field="source_content_manifest_path",
        )
        if not candidate_locator.startswith(".staging/packs/"):
            raise PackPromotionError("portable source candidate locator must be under .staging/packs")
        if not manifest_locator.startswith(candidate_locator + "/"):
            raise PackPromotionError("portable source manifest locator must be inside source candidate")
    else:
        for field in ("source_candidate_path", "source_content_manifest_path"):
            if not isinstance(receipt_raw.get(field), str) or not receipt_raw.get(field):
                raise PackPromotionError(f"legacy promotion receipt {field} is missing")
    if receipt_raw.get("pack_id") != pack_id or receipt_raw.get("pack_version") != pack_version:
        raise PackPromotionError("promotion receipt Pack identity mismatch")
    if receipt_raw.get("persistence_class") != PersistenceClass.AUTHORITATIVE.value:
        raise PackPromotionError("promotion receipt persistence class is not AUTHORITATIVE")
    for field in (
        "source_content_manifest_sha256",
        "pack_yaml_sha256",
        "review_receipt_sha256",
        "promoted_content_manifest_sha256",
        "review_artifact_sha256",
        "approval_artifact_sha256",
    ):
        if not _valid_sha256(receipt_raw.get(field)):
            raise PackPromotionError(f"invalid promotion receipt SHA field: {field}")
    if receipt_raw.get("review_artifact_revision") != 1 or receipt_raw.get("approval_artifact_revision") != 1:
        raise PackPromotionError("promotion receipt immutable evidence revision mismatch")
    if not isinstance(receipt_raw.get("review_artifact_id"), str) or not isinstance(receipt_raw.get("approval_artifact_id"), str):
        raise PackPromotionError("promotion receipt immutable evidence identity is missing")

    material = dict(receipt_raw)
    promotion_id = material.pop("promotion_id")
    expected_promotion_id = _receipt_promotion_id(material)
    if promotion_id != expected_promotion_id:
        raise PackPromotionError("promotion receipt deterministic identity mismatch")

    manifest_sha = sha256_bytes(manifest_bytes)
    if receipt_raw.get("promoted_content_manifest_sha256") != manifest_sha:
        raise PackPromotionError("promotion receipt promoted-manifest binding mismatch")
    pack_yaml = content_root / "pack.yaml"
    if not pack_yaml.is_file() or _sha256_file(pack_yaml) != receipt_raw.get("pack_yaml_sha256"):
        raise PackPromotionError("promotion receipt pack.yaml binding mismatch")
    return {
        "pack_id": pack_id,
        "pack_version": pack_version,
        "content_root": str(content_root),
        "content_manifest_path": str(manifest_path),
        "content_manifest_sha256": manifest_sha,
        "promotion_receipt_path": str(receipt_path),
        "promotion_receipt_sha256": sha256_bytes(receipt_bytes),
        "promotion_receipt": receipt_raw,
        "pack_yaml_path": str(pack_yaml),
        "pack_yaml_sha256": receipt_raw["pack_yaml_sha256"],
    }


def validate_promoted_pack_record(
    final: Path,
    *,
    expected_pack_id: str | None = None,
    expected_pack_version: str | None = None,
    authority_root: Path | None = None,
    containment_root: Path | None = None,
) -> dict[str, Any]:
    """Validate operational Pack-directory bytes only; this does NOT establish lifecycle eligibility."""
    return _validate_operational_promoted_pack_record(
        final,
        expected_pack_id=expected_pack_id,
        expected_pack_version=expected_pack_version,
        authority_root=authority_root,
        containment_root=containment_root,
    )


def _commit_binding_for_pack(runtime_root: Path, pack_id: str, pack_version: str) -> PromotionArtifactBinding:
    store_root = _promotion_store_root(runtime_root)
    artifact_id = _commit_artifact_id(pack_id, pack_version)
    manifest_path = _artifact_manifest_path(store_root, artifact_id)
    if not manifest_path.is_file():
        raise PackPromotionError("Pack promotion commit R001 is missing")
    manifest = _load_artifact_manifest(manifest_path)
    return PromotionArtifactBinding(
        artifact_id=artifact_id,
        revision=manifest.revision,
        sha256=manifest.sha256,
    )


def validate_committed_promoted_pack(runtime_root: Path, pack_id: str, pack_version: str) -> dict[str, Any]:
    """Validate the sole Runtime-owned lifecycle Authority for one promoted Pack."""
    runtime_root = _lexical_absolute(runtime_root)
    pack_id = _validate_pack_component(pack_id, field="pack_id")
    pack_version = _validate_pack_component(pack_version, field="pack_version")
    authority_root = runtime_root / "_authoritative" / "packs"
    final = authority_root / pack_id / pack_version
    binding = _commit_binding_for_pack(runtime_root, pack_id, pack_version)
    commit_payload, _commit_manifest, _commit_payload_path = _load_exact_immutable_artifact(
        runtime_root,
        binding,
        expected_class=PACK_PROMOTION_COMMIT,
        expected_persistence=PersistenceClass.AUTHORITATIVE,
        expected_pack_id=pack_id,
        expected_pack_version=pack_version,
    )
    required_commit = {
        "evidence_class", "committed", "pack_id", "pack_version", "pack_key_sha256",
        "source_content_manifest_sha256", "pack_yaml_sha256",
        "promoted_content_manifest_sha256", "promotion_receipt_sha256",
        "review_artifact_id", "review_artifact_revision", "review_artifact_sha256",
        "approval_artifact_id", "approval_artifact_revision", "approval_artifact_sha256",
        "authoritative_content_path", "promotion_contract_revision",
    }
    if set(commit_payload) != required_commit:
        raise PackPromotionError("Pack promotion commit payload fields are invalid")
    if type(commit_payload.get("committed")) is not bool or commit_payload.get("committed") is not True:
        raise PackPromotionError("Pack promotion commit must be exact Boolean true")
    if commit_payload.get("pack_key_sha256") != _pack_key_sha256(pack_id, pack_version):
        raise PackPromotionError("Pack promotion commit pack-key mismatch")
    commit_contract_revision = commit_payload.get("promotion_contract_revision")
    if commit_contract_revision not in SUPPORTED_PACK_PROMOTION_CONTRACT_REVISIONS:
        raise PackPromotionError("Pack promotion commit contract revision mismatch")
    expected_content_locator = _runtime_relative_locator(
        runtime_root,
        final / "content",
        field="authoritative_content_path",
    )
    if commit_contract_revision == PACK_PROMOTION_CONTRACT_REVISION:
        if commit_payload.get("authoritative_content_path") != expected_content_locator:
            raise PackPromotionError("Pack promotion commit authoritative-content locator mismatch")
    elif not _legacy_locator_matches(
        commit_payload.get("authoritative_content_path"),
        expected_content_locator,
    ):
        raise PackPromotionError("legacy Pack promotion commit authoritative-content path mismatch")

    record = _validate_operational_promoted_pack_record(
        final,
        expected_pack_id=pack_id,
        expected_pack_version=pack_version,
        authority_root=authority_root,
        containment_root=runtime_root,
    )
    if record["promotion_receipt"]["contract_revision"] != commit_contract_revision:
        raise PackPromotionError("Pack promotion receipt/commit contract revision mismatch")
    if record["promotion_receipt_sha256"] != commit_payload.get("promotion_receipt_sha256"):
        raise PackPromotionError("Pack promotion commit receipt binding mismatch")
    if record["content_manifest_sha256"] != commit_payload.get("promoted_content_manifest_sha256"):
        raise PackPromotionError("Pack promotion commit content-manifest binding mismatch")
    if record["pack_yaml_sha256"] != commit_payload.get("pack_yaml_sha256"):
        raise PackPromotionError("Pack promotion commit pack.yaml binding mismatch")

    review_binding = PromotionArtifactBinding(
        commit_payload["review_artifact_id"],
        commit_payload["review_artifact_revision"],
        commit_payload["review_artifact_sha256"],
    )
    review_payload, _m, _p = _load_exact_immutable_artifact(
        runtime_root,
        review_binding,
        expected_class=PACK_PROMOTION_REVIEW,
        expected_persistence=PersistenceClass.AUDIT,
        expected_pack_id=pack_id,
        expected_pack_version=pack_version,
    )
    approval_binding = PromotionArtifactBinding(
        commit_payload["approval_artifact_id"],
        commit_payload["approval_artifact_revision"],
        commit_payload["approval_artifact_sha256"],
    )
    approval_payload, _m2, _p2 = _load_exact_immutable_artifact(
        runtime_root,
        approval_binding,
        expected_class=PACK_PROMOTION_HUMAN_APPROVAL,
        expected_persistence=PersistenceClass.AUTHORITATIVE,
        expected_pack_id=pack_id,
        expected_pack_version=pack_version,
    )

    # Validate semantic evidence against exact committed Pack identity.
    prepared_stub = PreparedPackCandidate(
        candidate_path=record["promotion_receipt"]["source_candidate_path"],
        source_content_manifest_path=record["promotion_receipt"]["source_content_manifest_path"],
        pack_id=pack_id,
        pack_version=pack_version,
        source_content_manifest_sha256=commit_payload["source_content_manifest_sha256"],
        pack_yaml_sha256=commit_payload["pack_yaml_sha256"],
        promoted_content_manifest_sha256=commit_payload["promoted_content_manifest_sha256"],
        promoted_content_manifest={},
        file_entries=(),
    )
    _validate_review_payload(review_payload, prepared=prepared_stub)
    _validate_approval_payload(
        approval_payload,
        prepared=prepared_stub,
        review_binding=review_binding,
    )
    receipt = record["promotion_receipt"]
    checks = {
        "source_content_manifest_sha256": commit_payload["source_content_manifest_sha256"],
        "review_artifact_id": review_binding.artifact_id,
        "review_artifact_revision": review_binding.revision,
        "review_artifact_sha256": review_binding.sha256,
        "approval_artifact_id": approval_binding.artifact_id,
        "approval_artifact_revision": approval_binding.revision,
        "approval_artifact_sha256": approval_binding.sha256,
        "approval_id": approval_payload["approval_id"],
        "approver_id": approval_payload["approver_id"],
        "review_receipt_sha256": review_payload["review_receipt_sha256"],
    }
    for field, expected in checks.items():
        if receipt.get(field) != expected:
            raise PackPromotionError(f"Pack promotion receipt external Authority binding mismatch: {field}")

    record["commit_artifact_id"] = binding.artifact_id
    record["commit_artifact_revision"] = binding.revision
    record["commit_artifact_sha256"] = binding.sha256
    record["commit_payload"] = commit_payload
    return record


class PackPromotionAuthority:
    """Runtime-owned Pack promotion with external immutable evidence and commit Authority."""

    def __init__(self, root: Path):
        self.root = _lexical_absolute(root)
        self.staging_packs_root = self.root / ".staging" / "packs"
        self.pack_authority_root = self.root / "_authoritative" / "packs"
        self.promotion_store_root = _promotion_store_root(self.root)

    def prepare(self, candidate_path: Path, source_content_manifest_path: Path) -> PreparedPackCandidate:
        if not self.root.is_dir():
            raise PackPromotionError("Runtime root is missing")
        candidate = _lexical_absolute(candidate_path)
        staging_root = _lexical_absolute(self.staging_packs_root)
        if not staging_root.is_dir() or not candidate.is_dir() or not _is_relative_to(candidate, staging_root):
            raise PackPromotionError("candidate is outside exact staging Pack allowlist")
        _assert_no_reparse_chain(self.root, staging_root)
        _assert_no_reparse_chain(staging_root, candidate)

        source_manifest = _lexical_absolute(source_content_manifest_path)
        if source_manifest.parent != candidate or not source_manifest.is_file() or _is_reparse_or_symlink(source_manifest):
            raise PackPromotionError("source content manifest must be one direct-child control sidecar")
        raw_manifest_bytes = source_manifest.read_bytes()
        try:
            raw_manifest = json.loads(raw_manifest_bytes.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PackPromotionError("cannot parse source content manifest") from exc
        pack_id, pack_version, entries = _normalized_source_entries(raw_manifest)

        actual_files = _enumerate_candidate_files(candidate)
        sidecar_rel = source_manifest.relative_to(candidate).as_posix()
        _assert_portable_candidate_content(
            actual_files,
            tuple(row[0] for row in entries),
        )
        expected_actual = {row[0] for row in entries} | {sidecar_rel}
        if set(actual_files) != expected_actual:
            raise PackPromotionError("candidate has missing or unmanifested substantive files")
        if sidecar_rel in {row[0] for row in entries}:
            raise PackPromotionError("source content manifest control sidecar must not be substantive content")

        measured: list[tuple[str, int, str]] = []
        for path, expected_size, expected_sha in entries:
            target = actual_files[path]
            if _is_reparse_or_symlink(target):
                raise PackPromotionError(f"reparse/symlink content is forbidden: {target}")
            data = target.read_bytes()
            row = (path, len(data), sha256_bytes(data))
            if row != (path, expected_size, expected_sha):
                raise PackPromotionError(f"candidate content identity mismatch: {path}")
            measured.append(row)
        measured_tuple = tuple(measured)
        if measured_tuple != entries:
            raise PackPromotionError("source manifest and independently measured tuple sets differ")

        pack_yaml = candidate / "pack.yaml"
        if "pack.yaml" not in actual_files:
            raise PackPromotionError("pack.yaml must be listed as substantive Pack content")
        try:
            pack_manifest = yaml.safe_load(pack_yaml.read_bytes())
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise PackPromotionError("cannot parse candidate pack.yaml") from exc
        if (
            not isinstance(pack_manifest, dict)
            or pack_manifest.get("pack_id") != pack_id
            or pack_manifest.get("version") != pack_version
        ):
            raise PackPromotionError("pack.yaml pack_id/version does not match source content manifest")
        pack_yaml_sha = _sha256_file(pack_yaml)
        entry_sha = {path: sha for path, _size, sha in entries}.get("pack.yaml")
        if entry_sha != pack_yaml_sha:
            raise PackPromotionError("pack.yaml SHA does not match source content manifest")

        promoted_manifest = _runtime_promoted_manifest(pack_id, pack_version, entries)
        promoted_bytes = _canonical(promoted_manifest)
        promoted_sha = sha256_bytes(promoted_bytes)
        return PreparedPackCandidate(
            candidate_path=str(candidate),
            source_content_manifest_path=str(source_manifest),
            pack_id=pack_id,
            pack_version=pack_version,
            source_content_manifest_sha256=sha256_bytes(raw_manifest_bytes),
            pack_yaml_sha256=pack_yaml_sha,
            promoted_content_manifest_sha256=promoted_sha,
            promoted_content_manifest=promoted_manifest,
            file_entries=entries,
        )

    def persist_review_evidence_from_controller(
        self,
        prepared: PreparedPackCandidate,
        *,
        review_receipt_text: str,
        review_result: str = "PASS",
    ) -> PromotionArtifactBinding:
        if review_result != "PASS":
            raise PackPromotionError("only an accepted PASS review may become Pack promotion review evidence")
        if not isinstance(review_receipt_text, str) or not review_receipt_text:
            raise PackPromotionError("exact accepted review receipt text is required")
        payload = {
            "evidence_class": PACK_PROMOTION_REVIEW,
            "pack_id": prepared.pack_id,
            "pack_version": prepared.pack_version,
            "source_content_manifest_sha256": prepared.source_content_manifest_sha256,
            "pack_yaml_sha256": prepared.pack_yaml_sha256,
            "review_result": "PASS",
            "review_receipt_sha256": sha256_bytes(review_receipt_text.encode("utf-8")),
            "review_receipt_text": review_receipt_text,
        }
        with _pack_promotion_lock(self.root):
            return _persist_immutable_artifact_locked(
                self.root,
                payload,
                evidence_class=PACK_PROMOTION_REVIEW,
                persistence_class=PersistenceClass.AUDIT,
            )

    def persist_human_approval_from_controller(
        self,
        prepared: PreparedPackCandidate,
        *,
        review_artifact: PromotionArtifactBinding,
        approval_id: str,
        approver_id: str,
        approved: bool,
    ) -> PromotionArtifactBinding:
        if type(approved) is not bool or approved is not True:
            raise PackPromotionError("explicit human approval must be exact Boolean true")
        if not isinstance(approval_id, str) or not approval_id or not isinstance(approver_id, str) or not approver_id:
            raise PackPromotionError("approval_id and approver_id are required")
        review_payload, _m, _p = _load_exact_immutable_artifact(
            self.root,
            review_artifact,
            expected_class=PACK_PROMOTION_REVIEW,
            expected_persistence=PersistenceClass.AUDIT,
            expected_pack_id=prepared.pack_id,
            expected_pack_version=prepared.pack_version,
        )
        _validate_review_payload(review_payload, prepared=prepared)
        payload = {
            "evidence_class": PACK_PROMOTION_HUMAN_APPROVAL,
            "approval_id": approval_id,
            "approver_id": approver_id,
            "approved": True,
            "pack_id": prepared.pack_id,
            "pack_version": prepared.pack_version,
            "source_content_manifest_sha256": prepared.source_content_manifest_sha256,
            "pack_yaml_sha256": prepared.pack_yaml_sha256,
            "promoted_content_manifest_sha256": prepared.promoted_content_manifest_sha256,
            "review_artifact_id": review_artifact.artifact_id,
            "review_artifact_revision": review_artifact.revision,
            "review_artifact_sha256": review_artifact.sha256,
        }
        with _pack_promotion_lock(self.root):
            return _persist_immutable_artifact_locked(
                self.root,
                payload,
                evidence_class=PACK_PROMOTION_HUMAN_APPROVAL,
                persistence_class=PersistenceClass.AUTHORITATIVE,
            )

    @staticmethod
    def _validate_request(request: PackPromotionRequest, prepared: PreparedPackCandidate) -> None:
        expected = {
            "pack_id": prepared.pack_id,
            "pack_version": prepared.pack_version,
            "source_content_manifest_sha256": prepared.source_content_manifest_sha256,
            "pack_yaml_sha256": prepared.pack_yaml_sha256,
            "expected_promoted_content_manifest_sha256": prepared.promoted_content_manifest_sha256,
        }
        for field, value in expected.items():
            if getattr(request, field) != value:
                raise PackPromotionError(f"Pack promotion request binding mismatch: {field}")

    def _load_governed_evidence(
        self,
        request: PackPromotionRequest,
        prepared: PreparedPackCandidate,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        review_payload, _rm, _rp = _load_exact_immutable_artifact(
            self.root,
            request.review_artifact,
            expected_class=PACK_PROMOTION_REVIEW,
            expected_persistence=PersistenceClass.AUDIT,
            expected_pack_id=prepared.pack_id,
            expected_pack_version=prepared.pack_version,
        )
        _validate_review_payload(review_payload, prepared=prepared)
        approval_payload, _am, _ap = _load_exact_immutable_artifact(
            self.root,
            request.approval_artifact,
            expected_class=PACK_PROMOTION_HUMAN_APPROVAL,
            expected_persistence=PersistenceClass.AUTHORITATIVE,
            expected_pack_id=prepared.pack_id,
            expected_pack_version=prepared.pack_version,
        )
        _validate_approval_payload(
            approval_payload,
            prepared=prepared,
            review_binding=request.review_artifact,
        )
        return review_payload, approval_payload

    def _expected_receipt(
        self,
        request: PackPromotionRequest,
        prepared: PreparedPackCandidate,
        review_payload: dict[str, Any],
        approval_payload: dict[str, Any],
    ) -> PackPromotionReceipt:
        fields = {
            "schema_revision": PACK_PROMOTION_RECEIPT_SCHEMA_REVISION,
            "contract_revision": PACK_PROMOTION_CONTRACT_REVISION,
            "pack_id": prepared.pack_id,
            "pack_version": prepared.pack_version,
            "source_content_manifest_sha256": prepared.source_content_manifest_sha256,
            "pack_yaml_sha256": prepared.pack_yaml_sha256,
            "review_receipt_sha256": review_payload["review_receipt_sha256"],
            "promoted_content_manifest_sha256": prepared.promoted_content_manifest_sha256,
            "review_artifact_id": request.review_artifact.artifact_id,
            "review_artifact_revision": request.review_artifact.revision,
            "review_artifact_sha256": request.review_artifact.sha256,
            "approval_artifact_id": request.approval_artifact.artifact_id,
            "approval_artifact_revision": request.approval_artifact.revision,
            "approval_artifact_sha256": request.approval_artifact.sha256,
            "approval_id": approval_payload["approval_id"],
            "approver_id": approval_payload["approver_id"],
            "persistence_class": PersistenceClass.AUTHORITATIVE.value,
            "source_candidate_path": _runtime_relative_locator(
                self.root,
                prepared.candidate_path,
                field="source_candidate_path",
            ),
            "source_content_manifest_path": _runtime_relative_locator(
                self.root,
                prepared.source_content_manifest_path,
                field="source_content_manifest_path",
            ),
        }
        return PackPromotionReceipt(promotion_id=_receipt_promotion_id(fields), **fields)

    def _assert_source_current(self, request: PackPromotionRequest, prepared: PreparedPackCandidate) -> PreparedPackCandidate:
        current = self.prepare(request.candidate_path, request.source_content_manifest_path)
        self._validate_request(request, current)
        if current != prepared:
            raise PackPromotionError("source candidate identity changed after preparation")
        return current

    def _existing_commit(self, pack_id: str, pack_version: str) -> dict[str, Any] | None:
        manifest_path = _artifact_manifest_path(
            self.promotion_store_root,
            _commit_artifact_id(pack_id, pack_version),
        )
        if not manifest_path.exists():
            return None
        return validate_committed_promoted_pack(self.root, pack_id, pack_version)

    def _commit_payload(
        self,
        prepared: PreparedPackCandidate,
        receipt_sha256: str,
        request: PackPromotionRequest,
        final: Path,
    ) -> dict[str, Any]:
        return {
            "evidence_class": PACK_PROMOTION_COMMIT,
            "committed": True,
            "pack_id": prepared.pack_id,
            "pack_version": prepared.pack_version,
            "pack_key_sha256": _pack_key_sha256(prepared.pack_id, prepared.pack_version),
            "source_content_manifest_sha256": prepared.source_content_manifest_sha256,
            "pack_yaml_sha256": prepared.pack_yaml_sha256,
            "promoted_content_manifest_sha256": prepared.promoted_content_manifest_sha256,
            "promotion_receipt_sha256": receipt_sha256,
            "review_artifact_id": request.review_artifact.artifact_id,
            "review_artifact_revision": request.review_artifact.revision,
            "review_artifact_sha256": request.review_artifact.sha256,
            "approval_artifact_id": request.approval_artifact.artifact_id,
            "approval_artifact_revision": request.approval_artifact.revision,
            "approval_artifact_sha256": request.approval_artifact.sha256,
            "authoritative_content_path": _runtime_relative_locator(
                self.root,
                final / "content",
                field="authoritative_content_path",
            ),
            "promotion_contract_revision": PACK_PROMOTION_CONTRACT_REVISION,
        }

    def _validate_existing_exact_replay(
        self,
        record: dict[str, Any],
        *,
        expected_receipt: PackPromotionReceipt,
        request: PackPromotionRequest,
        prepared: PreparedPackCandidate,
    ) -> PackPromotionReceipt:
        if record["promotion_receipt"] != expected_receipt.model_dump():
            raise PackPromotionError("conflicting committed authoritative Pack version")
        commit = record["commit_payload"]
        expected_commit = self._commit_payload(
            prepared,
            record["promotion_receipt_sha256"],
            request,
            Path(record["content_root"]).parent,
        )
        if commit != expected_commit:
            raise PackPromotionError("conflicting Pack promotion commit Authority")
        return PackPromotionReceipt(**record["promotion_receipt"])

    def _remove_uncommitted_final(self, final: Path) -> None:
        # Caller holds lock and has confirmed no commit R001 exists.
        if self._existing_commit(final.parent.name, final.name) is not None:
            raise PackPromotionError("committed authoritative Pack cannot be cleaned as uncommitted")
        if final.exists():
            shutil.rmtree(final)

    def promote(
        self,
        request: PackPromotionRequest,
        *,
        fail_before_publish: bool = False,
        fail_after_publish_before_commit: bool = False,
    ) -> PackPromotionReceipt:
        initial = self.prepare(request.candidate_path, request.source_content_manifest_path)
        self._validate_request(request, initial)

        with _pack_promotion_lock(self.root):
            prepared = self._assert_source_current(request, initial)
            review_payload, approval_payload = self._load_governed_evidence(request, prepared)
            expected_receipt = self._expected_receipt(
                request,
                prepared,
                review_payload,
                approval_payload,
            )

            existing = self._existing_commit(prepared.pack_id, prepared.pack_version)
            if existing is not None:
                return self._validate_existing_exact_replay(
                    existing,
                    expected_receipt=expected_receipt,
                    request=request,
                    prepared=prepared,
                )

            authority_root = _lexical_absolute(self.pack_authority_root)
            authority_parent = authority_root / prepared.pack_id
            final = authority_parent / prepared.pack_version
            _assert_no_reparse_chain(self.root, authority_root.parent)
            _safe_mkdir_under(self.root, authority_root)
            _safe_mkdir_under(authority_root, authority_parent)

            # Existing physical final is NON-AUTHORITATIVE because commit R001 is absent.
            if final.exists():
                try:
                    record = _validate_operational_promoted_pack_record(
                        final,
                        expected_pack_id=prepared.pack_id,
                        expected_pack_version=prepared.pack_version,
                        authority_root=authority_root,
                        containment_root=self.root,
                    )
                    if record["promotion_receipt"] != expected_receipt.model_dump():
                        self._remove_uncommitted_final(final)
                    else:
                        # Exact uncommitted final may be reused.
                        pass
                except PackPromotionError:
                    self._remove_uncommitted_final(final)

            if not final.exists():
                tmp = authority_parent / f".staging-{prepared.pack_version}-{expected_receipt.promotion_id}-{uuid.uuid4().hex}"
                try:
                    tmp.mkdir()
                    content_root = tmp / "content"
                    content_root.mkdir()
                    candidate = Path(prepared.candidate_path)
                    for rel, expected_size, expected_sha in prepared.file_entries:
                        src = candidate.joinpath(*rel.split("/"))
                        if _is_reparse_or_symlink(src):
                            raise PackPromotionError(f"candidate content became a reparse/symlink: {rel}")
                        data = src.read_bytes()
                        if len(data) != expected_size or sha256_bytes(data) != expected_sha:
                            raise PackPromotionError(f"candidate content changed before copy: {rel}")
                        dst = content_root.joinpath(*rel.split("/"))
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(data)
                    manifest_bytes = _canonical(prepared.promoted_content_manifest)
                    if sha256_bytes(manifest_bytes) != prepared.promoted_content_manifest_sha256:
                        raise PackPromotionError("promoted content manifest identity changed")
                    (tmp / "content_manifest.json").write_bytes(manifest_bytes)
                    (tmp / "promotion_receipt.json").write_bytes(_canonical(expected_receipt.model_dump()))
                    _validate_operational_promoted_pack_record(
                        tmp,
                        expected_pack_id=prepared.pack_id,
                        expected_pack_version=prepared.pack_version,
                        authority_root=authority_root,
                        containment_root=self.root,
                    )
                    if fail_before_publish:
                        raise PackPromotionError("injected pre-publish failure")
                    try:
                        if final.exists():
                            raise FileExistsError(str(final))
                        os.rename(tmp, final)
                    except OSError:
                        if not final.exists():
                            raise
                        # Cooperating Runtime operations are serialized; treat any destination
                        # appearance as an observed uncommitted race and validate/clean.
                        try:
                            record = _validate_operational_promoted_pack_record(
                                final,
                                expected_pack_id=prepared.pack_id,
                                expected_pack_version=prepared.pack_version,
                                authority_root=authority_root,
                                containment_root=self.root,
                            )
                            if record["promotion_receipt"] != expected_receipt.model_dump():
                                self._remove_uncommitted_final(final)
                                raise PackPromotionError("conflicting uncommitted destination-created race")
                        except PackPromotionError:
                            self._remove_uncommitted_final(final)
                            raise
                finally:
                    if tmp.exists():
                        shutil.rmtree(tmp, ignore_errors=True)

            record = _validate_operational_promoted_pack_record(
                final,
                expected_pack_id=prepared.pack_id,
                expected_pack_version=prepared.pack_version,
                authority_root=authority_root,
                containment_root=self.root,
            )
            if record["promotion_receipt"] != expected_receipt.model_dump():
                self._remove_uncommitted_final(final)
                raise PackPromotionError("uncommitted authoritative directory binding mismatch")

            if fail_after_publish_before_commit:
                raise PackPromotionError("injected post-publish pre-commit failure")

            # Final source-manifest + substantive-byte currentness immediately before commit.
            try:
                self._assert_source_current(request, prepared)
            except Exception:
                self._remove_uncommitted_final(final)
                raise

            receipt_sha = record["promotion_receipt_sha256"]
            commit_payload = self._commit_payload(prepared, receipt_sha, request, final)
            commit_binding = _persist_immutable_artifact_locked(
                self.root,
                commit_payload,
                evidence_class=PACK_PROMOTION_COMMIT,
                persistence_class=PersistenceClass.AUTHORITATIVE,
                artifact_id=_commit_artifact_id(prepared.pack_id, prepared.pack_version),
            )
            committed = validate_committed_promoted_pack(
                self.root,
                prepared.pack_id,
                prepared.pack_version,
            )
            if committed["commit_artifact_sha256"] != commit_binding.sha256:
                raise PackPromotionError("Pack promotion commit exact binding mismatch after commit")
            return PackPromotionReceipt(**committed["promotion_receipt"])


__all__ = [
    "PromotionArtifactBinding",
    "PreparedPackCandidate",
    "PackPromotionRequest",
    "PackPromotionReceipt",
    "PackPromotionError",
    "PackPromotionAuthority",
    "validate_promoted_pack_record",
    "validate_committed_promoted_pack",
]
