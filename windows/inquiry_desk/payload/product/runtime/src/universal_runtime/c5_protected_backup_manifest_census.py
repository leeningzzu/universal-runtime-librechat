from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import os
import stat


class C5ProtectedBackupCensusError(ValueError):
    """Fail-closed error for the bounded protected-backup proof set."""


def _stop(code: str) -> None:
    raise C5ProtectedBackupCensusError(code)


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError:
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & flag)


def _plain_dir(path: Path, *, code: str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(path)))
    if not lexical.is_dir() or _is_reparse_or_symlink(lexical):
        _stop(code)
    if lexical.resolve(strict=False) != lexical:
        _stop(code)
    return lexical


def _plain_file(path: Path, *, code: str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(path)))
    if not lexical.is_file() or _is_reparse_or_symlink(lexical):
        _stop(code)
    if lexical.resolve(strict=False) != lexical:
        _stop(code)
    return lexical


def _sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, *, code: str) -> tuple[dict[str, Any], str]:
    path = _plain_file(path, code=code)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise C5ProtectedBackupCensusError(code) from exc
    if not isinstance(value, dict):
        _stop(code)
    return value, sha256(raw).hexdigest()


def _walk_plain_files(root: Path, *, max_files: int) -> list[tuple[Path, os.stat_result]]:
    root = _plain_dir(root, code="C5_PROTECTED_BACKUP_TREE_INVALID")
    result: list[tuple[Path, os.stat_result]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise C5ProtectedBackupCensusError("C5_PROTECTED_BACKUP_TREE_UNREADABLE") from exc
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise C5ProtectedBackupCensusError("C5_PROTECTED_BACKUP_TREE_UNREADABLE") from exc
            attrs = getattr(info, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if entry.is_symlink() or bool(attrs & reparse_flag):
                _stop("C5_PROTECTED_BACKUP_TREE_REDIRECTED")
            path = Path(entry.path)
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                result.append((path, info))
                if len(result) > max_files:
                    _stop("C5_PROTECTED_BACKUP_TREE_UNBOUNDED")
            else:
                _stop("C5_PROTECTED_BACKUP_TREE_ENTRY_INVALID")
    result.sort(key=lambda row: row[0].relative_to(root).as_posix())
    return result


def _bounded_tree_rows(root: Path, *, max_files: int = 25000) -> list[dict[str, Any]]:
    root = _plain_dir(root, code="C5_PROTECTED_BACKUP_TREE_INVALID")
    return [
        {
            "relative": path.relative_to(root).as_posix(),
            "bytes": info.st_size,
            "sha256": _sha_file(path),
        }
        for path, info in _walk_plain_files(root, max_files=max_files)
    ]


def _tree_stat(path: Path) -> dict[str, Any]:
    lexical = Path(os.path.abspath(os.fspath(path)))
    if not lexical.exists():
        return {"exists": False, "count": 0, "bytes": 0}
    rows = _walk_plain_files(lexical, max_files=25000)
    return {
        "exists": True,
        "count": len(rows),
        "bytes": sum(info.st_size for _, info in rows),
    }


def _manifest_row(name: str, digest: str, schema: str, state: str) -> dict[str, str]:
    if not name or len(digest) != 64 or len(schema) > 160 or len(state) > 200:
        _stop("C5_PROTECTED_BACKUP_MANIFEST_IDENTITY_INVALID")
    return {"name": name, "sha256": digest, "schema": schema, "state": state}


def _c5_r001_row(directory: Path) -> dict[str, Any]:
    manifest, manifest_sha = _load_json(
        directory / "BACKUP_MANIFEST.json",
        code="C5_PROTECTED_BACKUP_C5_MANIFEST_INVALID",
    )
    if (
        manifest.get("schema") != "C5_LOCAL_PROTECTED_BACKUP_ISOLATED_RESTORE_R001"
        or manifest.get("status")
        != "PASS_BOUNDED_VERIFIED_QUIESCENT_SNAPSHOT_AND_ISOLATED_RESTORE"
        or manifest.get("backup_id") != directory.name
        or manifest.get("runtime", {}).get("isolated_byte_restore_sha_equal") is not True
        or manifest.get("live_ui_user_assets", {}).get("isolated_restore_sha_equal") is not True
        or manifest.get("source_effects", {}).get("production_mutation") is not False
        or manifest.get("source_effects", {}).get("real_delete") is not False
        or manifest.get("source_effects", {}).get("external_upload") is not False
        or manifest.get("source_effects", {}).get("promotion") is not False
        or manifest.get("source_effects", {}).get("provider_calls") != 0
    ):
        _stop("C5_PROTECTED_BACKUP_C5_CONTRACT_INVALID")
    mongo = manifest.get("mongo")
    if not isinstance(mongo, dict):
        _stop("C5_PROTECTED_BACKUP_C5_MONGO_PROOF_INVALID")
    archive = _plain_file(
        directory / "mongo.archive.gz",
        code="C5_PROTECTED_BACKUP_C5_ARCHIVE_INVALID",
    )
    if (
        archive.stat().st_size != mongo.get("archive_bytes")
        or _sha_file(archive) != mongo.get("archive_sha256")
        or mongo.get("write_counter_before") != mongo.get("write_counter_after")
    ):
        _stop("C5_PROTECTED_BACKUP_C5_ARCHIVE_CURRENTNESS_CHANGED")
    declared_trees = manifest.get("runtime", {}).get("trees")
    if not isinstance(declared_trees, dict) or not declared_trees:
        _stop("C5_PROTECTED_BACKUP_C5_RUNTIME_TREE_PROOF_INVALID")
    runtime_root = _plain_dir(
        directory / "runtime",
        code="C5_PROTECTED_BACKUP_C5_RUNTIME_ROOT_INVALID",
    )
    runtime_stats: list[dict[str, Any]] = []
    actual_names = {item.name for item in runtime_root.iterdir() if item.is_dir()}
    if actual_names != set(declared_trees):
        _stop("C5_PROTECTED_BACKUP_C5_RUNTIME_TREE_SET_CHANGED")
    for name in sorted(declared_trees):
        spec = declared_trees[name]
        if not isinstance(spec, dict):
            _stop("C5_PROTECTED_BACKUP_C5_RUNTIME_TREE_PROOF_INVALID")
        current = _tree_stat(runtime_root / name)
        if (
            current["exists"] is not bool(spec.get("exists"))
            or current["count"] != spec.get("count")
            or current["bytes"] != spec.get("bytes")
            or not isinstance(spec.get("sha256"), str)
            or len(spec["sha256"]) != 64
        ):
            _stop("C5_PROTECTED_BACKUP_C5_RUNTIME_TREE_STAT_CHANGED")
        runtime_stats.append({"name": name, **current, "declared_sha256": spec["sha256"]})
    ui_specs = manifest.get("live_ui_user_assets", {}).get("tree_hashes")
    if not isinstance(ui_specs, dict) or set(ui_specs) != {"uploads", "images"}:
        _stop("C5_PROTECTED_BACKUP_C5_UI_TREE_PROOF_INVALID")
    ui_root = _plain_dir(
        directory / "ui_assets",
        code="C5_PROTECTED_BACKUP_C5_UI_ROOT_INVALID",
    )
    ui_stats: list[dict[str, Any]] = []
    for name in ("images", "uploads"):
        spec = ui_specs[name]
        current = _tree_stat(ui_root / name)
        if (
            not isinstance(spec, dict)
            or current["exists"] is not bool(spec.get("exists"))
            or current["count"] != spec.get("count")
            or current["bytes"] != spec.get("bytes")
            or spec.get("sha256") is not None
            and (not isinstance(spec.get("sha256"), str) or len(spec["sha256"]) != 64)
        ):
            _stop("C5_PROTECTED_BACKUP_C5_UI_TREE_STAT_CHANGED")
        ui_stats.append({"name": name, **current, "declared_sha256": spec.get("sha256")})
    top_files = []
    for path in sorted((item for item in directory.iterdir() if item.is_file()), key=lambda value: value.name):
        path = _plain_file(path, code="C5_PROTECTED_BACKUP_C5_TOP_FILE_INVALID")
        top_files.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _sha_file(path)})
    extra_dirs = {item.name for item in directory.iterdir() if item.is_dir()} - {
        "runtime", "ui_assets", "native_volume_assets",
    }
    if extra_dirs:
        _stop("C5_PROTECTED_BACKUP_C5_UNEXPECTED_DIRECTORY")
    native_rows: list[dict[str, Any]] = []
    native_root = directory / "native_volume_assets"
    if native_root.exists():
        native_rows = _bounded_tree_rows(native_root, max_files=64)
    return {
        "backup_id": directory.name,
        "backup_class": "C5_R001",
        "proof_manifests": [
            _manifest_row(
                "BACKUP_MANIFEST.json",
                manifest_sha,
                manifest["schema"],
                manifest["status"],
            )
        ],
        "bounded_currentness": {
            "top_files": top_files,
            "runtime_tree_stats": runtime_stats,
            "ui_tree_stats": ui_stats,
            "native_volume_assets": native_rows,
        },
    }


def _c6_row(directory: Path) -> dict[str, Any]:
    name = "C6_PROTECTED_NATIVE_BLOBS_MANIFEST_R001.json"
    manifest, manifest_sha = _load_json(
        directory / name,
        code="C5_PROTECTED_BACKUP_C6_MANIFEST_INVALID",
    )
    files = manifest.get("files")
    if (
        manifest.get("schema") != "C6_PROTECTED_NATIVE_CANONICAL_BLOB_RECOVERY_R001"
        or manifest.get("result") != "COPIED_TWO_CANDIDATE_BLOBS_WITH_INDEPENDENT_SHA"
        or manifest.get("current_UI_Mongo_Runtime_modified") is not False
        or manifest.get("deleted_user_files_or_backups") is not False
        or manifest.get("original_rollback_containers_modified") is not False
        or manifest.get("restored_to_Production") is not False
        or not isinstance(files, list)
        or len(files) != manifest.get("source_count_verified_copied")
        or len(files) != 2
    ):
        _stop("C5_PROTECTED_BACKUP_C6_CONTRACT_INVALID")
    blobs: list[dict[str, Any]] = []
    for row in sorted(files, key=lambda value: value.get("protected_relative_filename", "")):
        if not isinstance(row, dict):
            _stop("C5_PROTECTED_BACKUP_C6_FILE_PROOF_INVALID")
        relative = row.get("protected_relative_filename")
        if not isinstance(relative, str) or not relative.startswith("blobs/") or ".." in relative.split("/"):
            _stop("C5_PROTECTED_BACKUP_C6_FILE_PROOF_INVALID")
        path = _plain_file(directory / Path(relative), code="C5_PROTECTED_BACKUP_C6_BLOB_INVALID")
        digest = _sha_file(path)
        if (
            path.stat().st_size != row.get("protected_file_bytes_actual")
            or digest != row.get("protected_sha256")
            or digest != row.get("independent_stopped_source_double_read_sha256")
        ):
            _stop("C5_PROTECTED_BACKUP_C6_BLOB_CURRENTNESS_CHANGED")
        blobs.append({"relative": relative, "bytes": path.stat().st_size, "sha256": digest})
    if {item.name for item in directory.iterdir()} != {"blobs", name}:
        _stop("C5_PROTECTED_BACKUP_C6_ENTRY_SET_CHANGED")
    return {
        "backup_id": directory.name,
        "backup_class": "C6_NATIVE_BLOB_R001",
        "proof_manifests": [
            _manifest_row(name, manifest_sha, manifest["schema"], manifest["result"])
        ],
        "bounded_currentness": {"blobs": blobs},
    }


def _filep0_row(directory: Path) -> dict[str, Any]:
    mongo_name = "MONGO_NATIVE_MANIFEST.json"
    delta_name = "RUNTIME_DELTA_MANIFEST.json"
    mongo, mongo_sha = _load_json(
        directory / mongo_name,
        code="C5_PROTECTED_BACKUP_FILEP0_MONGO_MANIFEST_INVALID",
    )
    delta, delta_sha = _load_json(
        directory / delta_name,
        code="C5_PROTECTED_BACKUP_FILEP0_DELTA_MANIFEST_INVALID",
    )
    if (
        mongo.get("schema")
        != "FILEP0_NATIVE_MONGO_CURRENT_PROTECTED_NO_WRITES_ISOLATED_RESTORE_R001"
        or mongo.get("status")
        != "PASS_MONGO_NATIVE_DUMP_NO_WRITE_WINDOW_AND_ISOLATED_RESTORE"
        or mongo.get("isolated_restore_document_and_index_digest_equal") is not True
        or mongo.get("production_mongo_mutations") != 0
        or mongo.get("user_project_delete") is not False
        or mongo.get("write_counter_pre") != mongo.get("write_counter_post")
        or delta.get("schema")
        != "FILEP0_NATIVE_RUNTIME_DELTA_REFERENCES_ACCEPTED_RUNTIME_DONOR_R001"
        or delta.get("status") != "PASS_130_CURRENT_DELTA_FILES_SCOPED_COPY_AND_SHA"
        or delta.get("native_stopped_R004_backup_sources_modified") is not False
    ):
        _stop("C5_PROTECTED_BACKUP_FILEP0_CONTRACT_INVALID")
    archive = _plain_file(
        directory / str(mongo.get("mongo_archive_filename")),
        code="C5_PROTECTED_BACKUP_FILEP0_ARCHIVE_INVALID",
    )
    if (
        archive.stat().st_size != mongo.get("mongo_archive_bytes")
        or _sha_file(archive) != mongo.get("mongo_archive_sha256")
        or mongo.get("mongo_archive_sha256") != delta.get("mongo_new_native_archive_sha256")
        or mongo_sha != delta.get("mongo_new_native_archive_manifest_sha256")
    ):
        _stop("C5_PROTECTED_BACKUP_FILEP0_MONGO_CURRENTNESS_CHANGED")
    rows = delta.get("delta_protected_files")
    if (
        not isinstance(rows, list)
        or len(rows) != delta.get("current_delta_count")
        or len(rows) != delta.get("source_and_backup_sha_equal_count")
        or len(rows) > 5000
    ):
        _stop("C5_PROTECTED_BACKUP_FILEP0_DELTA_PROOF_INVALID")
    actual: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: value.get("relative", "")):
        if not isinstance(row, dict):
            _stop("C5_PROTECTED_BACKUP_FILEP0_DELTA_PROOF_INVALID")
        relative = row.get("relative")
        if not isinstance(relative, str) or not relative or ".." in relative.split("/"):
            _stop("C5_PROTECTED_BACKUP_FILEP0_DELTA_PROOF_INVALID")
        path = _plain_file(
            directory / "runtime_delta" / Path(relative),
            code="C5_PROTECTED_BACKUP_FILEP0_DELTA_FILE_INVALID",
        )
        digest = _sha_file(path)
        if path.stat().st_size != row.get("bytes") or digest != row.get("sha256"):
            _stop("C5_PROTECTED_BACKUP_FILEP0_DELTA_CURRENTNESS_CHANGED")
        actual.append({"relative": relative, "bytes": path.stat().st_size, "sha256": digest})
    if sum(item["bytes"] for item in actual) != delta.get("current_delta_bytes"):
        _stop("C5_PROTECTED_BACKUP_FILEP0_DELTA_BYTES_CHANGED")
    if {item.name for item in directory.iterdir()} != {
        "mongo.archive.gz", mongo_name, "runtime_delta", delta_name,
    }:
        _stop("C5_PROTECTED_BACKUP_FILEP0_ENTRY_SET_CHANGED")
    return {
        "backup_id": directory.name,
        "backup_class": "FILEP0_NATIVE_MONGO",
        "proof_manifests": [
            _manifest_row(mongo_name, mongo_sha, mongo["schema"], mongo["status"]),
            _manifest_row(delta_name, delta_sha, delta["schema"], delta["status"]),
        ],
        "bounded_currentness": {
            "mongo_archive": {
                "name": archive.name,
                "bytes": archive.stat().st_size,
                "sha256": _sha_file(archive),
            },
            "runtime_delta_files": actual,
        },
    }


def protected_backup_manifest_census_record(
    localappdata: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    base = localappdata if localappdata is not None else os.environ.get("LOCALAPPDATA", "")
    if not base:
        _stop("C5_PROTECTED_BACKUP_LOCALAPPDATA_UNAVAILABLE")
    root = _plain_dir(
        Path(base) / "UniversalRuntime" / "ProtectedBackups",
        code="C5_PROTECTED_BACKUP_ROOT_INVALID",
    )
    entries = sorted(root.iterdir(), key=lambda value: value.name)
    if not entries:
        _stop("C5_PROTECTED_BACKUP_SET_EMPTY")
    rows: list[dict[str, Any]] = []
    for directory in entries:
        directory = _plain_dir(directory, code="C5_PROTECTED_BACKUP_ENTRY_INVALID")
        if directory.name.startswith("C5_R001_"):
            rows.append(_c5_r001_row(directory))
        elif directory.name.startswith("C6_NATIVE_BLOB_R001_"):
            rows.append(_c6_row(directory))
        elif directory.name.startswith("FILEP0_NATIVE_MONGO_"):
            rows.append(_filep0_row(directory))
        else:
            _stop("C5_PROTECTED_BACKUP_CLASS_UNKNOWN")
    return {
        "schema": "C5_VERIFIED_PROTECTED_BACKUP_MANIFEST_SET_R001",
        "proof_ceiling": (
            "ALL_TOP_LEVEL_PROTECTED_BACKUP_CLASSES_EXACT_MANIFESTS; "
            "C6_FILE_BYTES_AND_FILEP0_DELTA_BYTES_REHASHED; "
            "C5_RUNTIME_LARGE_TREE_STAT_CURRENTNESS_PLUS_ACCEPTED_RESTORE_TREE_SHA"
        ),
        "entries": rows,
    }


def protected_backup_manifest_census_sha256(
    localappdata: str | os.PathLike[str] | None = None,
) -> str:
    record = protected_backup_manifest_census_record(localappdata)
    payload = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()
