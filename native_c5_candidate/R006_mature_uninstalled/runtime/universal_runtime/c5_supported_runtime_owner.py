"""C5 current supported Runtime owner (Windows OS lock, same FastAPI lifespan).

Owner scope is SUPPORTED RUNTIME PROCESS ONLY, not all old independent
JobAuthority writers. No C5 effect or global-writer admission is granted.
The current native Project/Job/backup safety policy MUST independently gate
all deletion or Production effects. No new DB, supervisor or network service.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import os
import stat

_C5_EXPECTED_WEBAPP_SHA = "e80da544b5c3e87babe258b68313740d3316d2edd490f0a69acf4a23b404577b"
_OWNER_PID = None
_OWNER_LOCK = None


def _require_webapp_bytes():
    path = Path(__file__).with_name("webapp.py")
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("C5_SUPPORTED_RUNTIME_WEBAPP_NOT_CURRENT")
    exact = sha256(path.read_bytes()).hexdigest()
    if exact != _C5_EXPECTED_WEBAPP_SHA:
        raise RuntimeError("C5_SUPPORTED_RUNTIME_WEBAPP_SOURCE_DRIFT")
    return exact


def _assert_not_reparse(path: Path):
    if not path.exists():
        return
    if path.is_symlink():
        raise RuntimeError("C5_SUPPORTED_OWNER_PATH_REDIRECTED")
    data = os.lstat(path)
    if getattr(data, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise RuntimeError("C5_SUPPORTED_OWNER_PATH_REPARSE")


def _default_lock_path():
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise RuntimeError("C5_MACHINE_LOCAL_ROOT_MISSING")
    root = Path(local)
    if not root.is_absolute() or not root.is_dir():
        raise RuntimeError("C5_MACHINE_LOCAL_ROOT_INVALID")
    return root / "UniversalRuntime" / "WEB_R004" / "C5_supported_runtime_owner.lock"


@contextmanager
def supported_runtime_owner(*, isolated_lock_path: Path | None = None):
    """Hold Windows native byte-range lock throughout the REAL ASGI lifespan.

    The test-only lock path must be inside an isolated C5 staging directory;
    it never changes the Production owner file or process.
    """
    global _OWNER_PID, _OWNER_LOCK
    if os.name != "nt":
        raise RuntimeError("C5_WINDOWS_OS_OWNER_REQUIRED")
    source_sha = _require_webapp_bytes()
    if _OWNER_LOCK is not None:
        raise RuntimeError("C5_SUPPORTED_RUNTIME_OWNER_ALREADY_ENTERED")
    path = Path(isolated_lock_path) if isolated_lock_path is not None else _default_lock_path()
    if isolated_lock_path is not None and (
        not path.is_absolute()
        or ".staging" not in path.parts
        or "C5_CURRENT_WINDOWS_SUPPORTED_RUNTIME_OWNER_ENTRY_R001" not in path.parts
    ):
        raise RuntimeError("C5_ISOLATED_OWNER_LOCK_SCOPE_INVALID")
    for item in (path.parent.parent.parent, path.parent.parent, path.parent):
        _assert_not_reparse(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_not_reparse(path.parent)
    _assert_not_reparse(path)
    with path.open("a+b") as fd:
        fd.seek(0, os.SEEK_END)
        if fd.tell() == 0:
            fd.write(b"\0")
            fd.flush()
            os.fsync(fd.fileno())
        fd.seek(0)
        import msvcrt
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("C5_SUPPORTED_RUNTIME_OWNER_ALREADY_RUNNING") from exc
        _OWNER_PID = os.getpid()
        _OWNER_LOCK = fd
        try:
            yield {"runtime_source_sha256": source_sha, "owner_scope": "SUPPORTED_RUNTIME_ONLY"}
        finally:
            _OWNER_PID = None
            _OWNER_LOCK = None
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)


def supported_runtime_attestation():
    if _OWNER_PID != os.getpid() or _OWNER_LOCK is None:
        raise RuntimeError("C5_SUPPORTED_RUNTIME_OWNER_NOT_ACTIVE")
    return {
        "status": "SUPPORTED_RUNTIME_OWNER_ACTIVE",
        "owner_scope": "SUPPORTED_RUNTIME_ONLY",
        "runtime_source_sha256": _require_webapp_bytes(),
        "all_independent_job_authority_writers_excluded": False,
        "global_writer_backup_and_job_admission_proven": False,
    }
