"""C5 existing Runtime webapp thin route composition, no separate App or DB.

Production-shaped candidate: calls current _service() and existing installed-aware
retirement primitives. No fixture auth header or mutable test injection.
"""
from __future__ import annotations

from typing import Any, Callable
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import hmac
from contextvars import ContextVar, copy_context
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from universal_runtime.c5_protected_backup_prepare_receipt import C5ProtectedBackupPrepareReceipt, C5PrepareStop

from universal_runtime.web_continuity import (
    WebContinuityError, _stable_id, _validate_command_id, _validate_label,
)
from universal_runtime.core.job_authority import JobAuthorityRegistry
from universal_runtime.core.source_content_retirement import (
    SourceRetirementStop,
    list_project_source_retirement_candidates,
)
from universal_runtime.c5_runtime_operation_receipt import (
    C5ProjectCascadeReceiptOwner, C5ReceiptStop,
)
# Historical JobAuthority is not a SourceRef/Memory read dependency.
# Current target-Project executable Jobs remain a separate C5 effect owner.

_NATIVE_ID = re.compile(r"^[a-f0-9]{24}$", re.IGNORECASE)
_RUNTIME_PROJECT_ID = re.compile(r"^PRJ_[A-Za-z0-9_]{8,128}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_C5_PHASES = {
    "C5_INVENTORY", "C5_NATIVE_RUNTIME_IDEMPOTENT_BINDING",
    "BEFORE_EFFECT", "RECOVERY_READINESS", "BEFORE_C5",
    "NATIVE_FILE_EFFECT", "CONTINUE_PARTIAL", "C5_FINAL_ABSENCE_VERIFY",
    "C5_COMPLETE_RELEASE", "C5_PRE_EFFECT_ABORT_RELEASE",
}
_C5_LEASE_LOCK = threading.RLock()
_C5_LEASES: dict[str, dict] = {}
_C5_LEASE_SECONDS = 180
_C5_BACKUP_REFRESH_LOCK = threading.Lock()
_C5_NATIVE_SCOPE = ContextVar("c5_current_native_scope", default=None)
_C5_BACKUP_SCRIPT_SHA256 = "c0f175e72d5b3b9d935ff767451c8128511cbd10f5291d3d5c5f4e752f5b5192"


def _release_c5_lease(runtime_project_id: str, lease_id: str) -> None:
    with _C5_LEASE_LOCK:
        current = _C5_LEASES.get(runtime_project_id)
        if current is None or current.get("lease_id") != lease_id:
            return
        _C5_LEASES.pop(runtime_project_id, None)
        timer = current.get("timer")
        if timer is not None:
            timer.cancel()
        current["lock_context"].__exit__(None, None, None)


def register_project_execution_under_c5_fence(
    *, runtime_project_id: str, register: Callable[[], Any],
) -> Any:
    """Atomically register one current execution only when no C5 lease owns its Project.

    This is a thin composition seam between the existing process-local execution
    registry and the existing C5 lease. It persists no state and creates no job
    index/cache. Lock ordering is always C5 lease -> execution registry.
    """
    if (_RUNTIME_PROJECT_ID.fullmatch(runtime_project_id or "") is None
            or not callable(register)):
        raise RuntimeError("C5_CURRENT_EXECUTION_REGISTRATION_SCOPE_INVALID")
    with _C5_LEASE_LOCK:
        current = _C5_LEASES.get(runtime_project_id)
        if current is not None and current.get("expires_at", 0) <= time.monotonic():
            _release_c5_lease(runtime_project_id, current["lease_id"])
            current = None
        if current is not None:
            raise RuntimeError("C5_PROJECT_DELETE_LEASE_ACTIVE")
        return register()


def _abort_c5_lease(*, runtime_project_id: str, native_project_id: str,
                    owner_id: str, membership_sha256: str,
                    supplied_lease_id: str) -> dict:
    with _C5_LEASE_LOCK:
        current = _C5_LEASES.get(runtime_project_id)
        if (
            current is None
            or current.get("lease_id") != supplied_lease_id
            or current.get("native_project_id") != native_project_id
            or current.get("owner_id") != owner_id
            or current.get("membership_sha256") != membership_sha256
        ):
            raise RuntimeError("C5_PRE_EFFECT_ABORT_LEASE_SCOPE_INVALID")
        result = {
            "lease_id": current["lease_id"],
            "sealed_project_revision": current["sealed_project_revision"],
            "protection_mode": current["protection_mode"],
            "guard_counters": dict(current["guard_counters"]),
        }
        _release_c5_lease(runtime_project_id, supplied_lease_id)
        return result


def _hold_c5_lease(*, runtime_project_id: str, native_project_id: str,
                   owner_id: str, project_revision: int,
                   membership_sha256: str, supplied_lease_id: str | None,
                   protection_mode: str,
                   guard_counters: dict[str, int],
                   job_authority: JobAuthorityRegistry,
                   admission_phase: str = "") -> tuple[str, bool, int]:
    """Hold one exact C5 lease while Runtime revisions advance through retirement.

    The sealed Project revision is the revision admitted before irreversible
    effects. Runtime PREPARE/CONFIRM/COMMIT legitimately increment the current
    revision; that progression must not look like a foreign lease. Native
    membership and the forward-recovery policy remain immutable for the lease.
    """
    with _C5_LEASE_LOCK:
        current = _C5_LEASES.get(runtime_project_id)
        if current is not None and current.get("expires_at", 0) <= time.monotonic():
            _release_c5_lease(runtime_project_id, current["lease_id"])
            current = None
        created = False
        if current is None:
            if supplied_lease_id is not None:
                raise RuntimeError("C5_ADMISSION_LEASE_NOT_FOUND")
            lock_context = job_authority._lock()
            lock_context.__enter__()
            lease_id = "C5LEASE_" + secrets.token_urlsafe(24)
            current = {
                "lease_id": lease_id,
                "native_project_id": native_project_id,
                "owner_id": owner_id,
                "sealed_project_revision": project_revision,
                "latest_runtime_revision": project_revision,
                "membership_sha256": membership_sha256,
                "protection_mode": protection_mode,
                "guard_counters": dict(guard_counters),
                "lock_context": lock_context,
            }
            _C5_LEASES[runtime_project_id] = current
            created = True
        else:
            if supplied_lease_id != current.get("lease_id") and not (
                supplied_lease_id is None
                and admission_phase in {
                    "C5_INVENTORY", "BEFORE_EFFECT",
                    "RECOVERY_READINESS", "CONTINUE_PARTIAL",
                }
            ):
                raise RuntimeError("C5_ADMISSION_LEASE_CONFLICT")
            if (
                current.get("native_project_id") != native_project_id
                or current.get("owner_id") != owner_id
                or current.get("membership_sha256") != membership_sha256
                or current.get("protection_mode") != protection_mode
                or any(guard_counters[key] < current.get("guard_counters", {}).get(key, -1)
                       for key in ("insert", "update", "delete"))
            ):
                raise RuntimeError("C5_ADMISSION_LEASE_SCOPE_CHANGED")
            latest = current.get("latest_runtime_revision")
            if type(latest) is not int or project_revision < latest:
                raise RuntimeError("C5_RUNTIME_REVISION_REGRESSED_DURING_LEASE")
            current["latest_runtime_revision"] = project_revision
        old_timer = current.get("timer")
        if old_timer is not None:
            old_timer.cancel()
        current["expires_at"] = time.monotonic() + _C5_LEASE_SECONDS
        timer = threading.Timer(
            _C5_LEASE_SECONDS,
            _release_c5_lease,
            args=(runtime_project_id, current["lease_id"]),
        )
        timer.daemon = True
        current["timer"] = timer
        timer.start()
        return current["lease_id"], created, current["sealed_project_revision"]


def _c5_current_execution_scope_under_held_lease(
    *, runtime_project_id: str, native_project_id: str,
    owner_id: str, membership_sha256: str, lease_id: str,
    active_project_worker_count: Callable[[str], int],
) -> dict:
    """Seal the current target-Project process execution scope under one C5 lease.

    The existing JobAuthority filesystem lock is already held for the lease, so
    no new Job issuance/activation can race the delete. The webapp registers the
    only current provider execution owner through
    register_project_execution_under_c5_fence(), which shares this lock. Normal
    deletion therefore does not traverse historical JobAuthority/Formal records.
    """
    if not callable(active_project_worker_count):
        raise RuntimeError("C5_CURRENT_EXECUTION_OWNER_UNAVAILABLE")

    def assert_exact_lease() -> dict:
        live = _C5_LEASES.get(runtime_project_id)
        if not (
            isinstance(live, dict)
            and live.get("lease_id") == lease_id
            and live.get("native_project_id") == native_project_id
            and live.get("owner_id") == owner_id
            and live.get("membership_sha256") == membership_sha256
            and live.get("expires_at", 0) > time.monotonic()
            and live.get("lock_context") is not None
        ):
            raise RuntimeError("C5_CURRENT_EXECUTION_EXCLUSIVE_LEASE_LOST")
        return live

    with _C5_LEASE_LOCK:
        lease = assert_exact_lease()
        proof = lease.get("sealed_project_execution_facts")
        if proof is not None:
            if (
                proof.get("logical_project_id") != runtime_project_id
                or proof.get("scope_verified") is not True
                or type(proof.get("project_active_pinned_jobs")) is not int
                or proof.get("project_active_pinned_jobs") < 0
                or proof.get("historical_job_projection_performed") is not False
            ):
                raise RuntimeError("C5_CURRENT_EXECUTION_REUSED_PROOF_INVALID")
            return dict(proof)

        target_workers = active_project_worker_count(runtime_project_id)
        if type(target_workers) is not int or target_workers < 0:
            raise RuntimeError("C5_CURRENT_EXECUTION_OWNER_RESULT_INVALID")
        facts = {
            "schema": "AIDES_C5_PROJECT_CURRENT_EXECUTION_SCOPE_R001",
            "source": "P1S3_PROCESS_LOCAL_REGISTRY_PLUS_JOB_AUTHORITY_EXCLUSIVE_LOCK",
            "logical_project_id": runtime_project_id,
            "project_active_pinned_jobs": target_workers,
            "project_active_formal_workers": target_workers,
            "historical_job_projection_performed": False,
            "scope_verified": True,
            "project_effect_safe_from_current_execution": target_workers == 0,
            "writer_exclusivity_proven": True,
            "delete_permitted": False,
        }
        lease = assert_exact_lease()
        lease["sealed_project_execution_facts"] = dict(facts)
        return dict(facts)


def _latest_current_protected_backup() -> dict:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise RuntimeError("C5_PROTECTED_BACKUP_ROOT_UNAVAILABLE")
    root = Path(local) / "UniversalRuntime" / "ProtectedBackups"
    # A supported fresh installation legitimately has no backup directory yet;
    # Product prepare must invoke the existing snapshot owner to create it.
    if not root.exists():
        raise RuntimeError("C5_CURRENT_PROTECTED_BACKUP_RESTORE_REQUIRED")
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("C5_PROTECTED_BACKUP_ROOT_INVALID")
    now = datetime.now(timezone.utc)
    for directory in sorted(
        (p for p in root.glob("C5_R001_*") if p.is_dir() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        manifest_path = directory / "BACKUP_MANIFEST.json"
        archive_path = directory / "mongo.archive.gz"
        if not manifest_path.is_file() or not archive_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
            created = datetime.fromisoformat(manifest["backed_up_at_utc"])
        except Exception:
            continue
        if created.tzinfo is None:
            continue
        age = (now - created.astimezone(timezone.utc)).total_seconds()
        mongo = manifest.get("mongo")
        runtime = manifest.get("runtime")
        effects = manifest.get("source_effects")
        user_assets = manifest.get("live_ui_user_assets")
        if not (
            manifest.get("schema") == "C5_LOCAL_PROTECTED_BACKUP_ISOLATED_RESTORE_R001"
            and manifest.get("status") ==
                "PASS_BOUNDED_VERIFIED_QUIESCENT_SNAPSHOT_AND_ISOLATED_RESTORE"
            and manifest.get("backup_id") == directory.name
            and 0 <= age <= 3600
            and isinstance(mongo, dict)
            and isinstance(runtime, dict)
            and isinstance(effects, dict)
            and isinstance(user_assets, dict)
            and runtime.get("isolated_byte_restore_sha_equal") is True
            and user_assets.get("isolated_restore_sha_equal") is True
            and isinstance(user_assets.get("source_sha256"), str)
            and _SHA.fullmatch(user_assets["source_sha256"])
            and effects.get("production_mutation") is False
            and effects.get("real_delete") is False
            and isinstance(mongo.get("write_counter_after"), dict)
            and isinstance(mongo.get("archive_sha256"), str)
            and _SHA.fullmatch(mongo["archive_sha256"])
            and isinstance(mongo.get("ejson_sha256"), str)
            and _SHA.fullmatch(mongo["ejson_sha256"])
            and isinstance(mongo.get("index_sha256"), str)
            and _SHA.fullmatch(mongo["index_sha256"])
            and type(mongo.get("collections")) is int and mongo["collections"] >= 0
            and type(mongo.get("documents")) is int and mongo["documents"] >= 0
            and sha256(archive_path.read_bytes()).hexdigest() == mongo["archive_sha256"]
        ):
            continue
        return {
            "backup_id": directory.name,
            "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
            "mongo_write_counter": mongo["write_counter_after"],
            "mongo_data_sha256": mongo["ejson_sha256"],
            "mongo_index_sha256": mongo["index_sha256"],
            "mongo_collections": mongo["collections"],
            "mongo_documents": mongo["documents"],
            "user_assets_sha256": user_assets["source_sha256"],
        }
    raise RuntimeError("C5_CURRENT_PROTECTED_BACKUP_RESTORE_REQUIRED")


def _validated_mongo_counters(value: object) -> dict[str, int]:
    if not (
        isinstance(value, dict)
        and all(type(value.get(key)) is int and value[key] >= 0
                for key in ("insert", "update", "delete"))
    ):
        raise RuntimeError("C5_PROTECTED_BACKUP_COUNTERS_INVALID")
    return {key: value[key] for key in ("insert", "update", "delete")}


def _safe_backup_subprocess_code(completed) -> str:
    """Extract only a bounded C5 code from the first-party snapshot process.

    Prefer its one-line JSON STOP record. Fall back to a RuntimeError token for
    older scripts. Never surface paths, stderr, arbitrary exception text or user
    bytes through the Product error response.
    """
    streams = ((completed.stdout or ""), (completed.stderr or ""))
    for stream in streams:
        for line in reversed(stream.splitlines()):
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            code = value.get("error_code") if isinstance(value, dict) else None
            if (value.get("status") == "STOP_PROTECTED_BACKUP_OR_RESTORE"
                    and isinstance(code, str)
                    and re.fullmatch(r"C5_[A-Z0-9_]{1,120}", code)):
                return code
    combined = "\n".join(streams)
    codes = re.findall(r"RuntimeError:\s*(C5_[A-Z0-9_]{1,120})", combined)
    if codes:
        return codes[-1]
    # Current-state observation can be interrupted only by these bounded,
    # first-party read-window races. Map them to one safe Product code; never
    # surface traceback, paths, arbitrary stderr or user data.
    if re.search(r"RuntimeError:\s*(?:MONGO_WRITES_DURING_DIGEST|"
                 r"UI_USER_ASSETS_CHANGED_DURING_MONGO_BACKUP|"
                 r"UI_USER_UPLOADS_CHANGED_DURING_COPY)", combined):
        return "C5_CURRENT_BACKUP_SEMANTIC_READ_TRANSIENT"
    return "C5_PROTECTED_BACKUP_REFRESH_FAILED"


def _verify_current_protected_backup_semantics(*, runtime_root: Path,
                                                   backup: dict,
                                                   observed_counters: dict[str, int],
                                                   runner=subprocess.run) -> bool:
    script = runtime_root / "scripts" / "c5_current_protected_snapshot.py"
    if (
        not runtime_root.is_absolute()
        or not script.is_file()
        or script.is_symlink()
        or sha256(script.read_bytes()).hexdigest() != _C5_BACKUP_SCRIPT_SHA256
    ):
        raise RuntimeError("C5_PROTECTED_BACKUP_SCRIPT_IDENTITY_INVALID")
    completed = runner(
        [sys.executable, str(script), "--current-state-json"],
        cwd=str(runtime_root), env=dict(os.environ), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(_safe_backup_subprocess_code(completed))
    state = None
    for line in reversed((completed.stdout or "").splitlines()):
        try:
            candidate = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(candidate, dict) and candidate.get("status") ==                 "PASS_C5_CURRENT_PROTECTED_BACKUP_STATE_READ":
            state = candidate
            break
    if not (
        isinstance(state, dict)
        and isinstance(state.get("mongo_data_sha256"), str)
        and _SHA.fullmatch(state["mongo_data_sha256"])
        and isinstance(state.get("mongo_index_sha256"), str)
        and _SHA.fullmatch(state["mongo_index_sha256"])
        and type(state.get("mongo_collections")) is int
        and type(state.get("mongo_documents")) is int
        and isinstance(state.get("ui_user_assets_sha256"), str)
        and _SHA.fullmatch(state["ui_user_assets_sha256"])
        and isinstance(state.get("mongo_write_counter"), dict)
        and state.get("production_mutation") is False
        and state.get("real_delete") is False
    ):
        raise RuntimeError("C5_CURRENT_BACKUP_SEMANTIC_READ_INVALID")
    current_counters = _validated_mongo_counters(state["mongo_write_counter"])
    expected_counters = _validated_mongo_counters(backup["mongo_write_counter"])
    observed = _validated_mongo_counters(observed_counters)
    monotonic = all(
        current_counters[key] >= expected_counters[key]
        and current_counters[key] >= observed[key]
        for key in ("insert", "update", "delete")
    )
    return bool(
        monotonic
        and state["mongo_data_sha256"] == backup["mongo_data_sha256"]
        and state["mongo_index_sha256"] == backup["mongo_index_sha256"]
        and state["mongo_collections"] == backup["mongo_collections"]
        and state["mongo_documents"] == backup["mongo_documents"]
        and state["ui_user_assets_sha256"] == backup["user_assets_sha256"]
    )


def _semantic_backup_current_with_bounded_retry(*, runtime_root: Path,
                                                   backup: dict,
                                                   observed_counters: dict[str, int],
                                                   attempts: int = 3) -> bool:
    """Prove existing backup current before another full snapshot.

    This is a C5-specific, read-only bounded retry, not a generic task engine
    and never an automatic Project DELETE retry. Stable semantic mismatch
    returns False. Known observation-window contention retries at most three
    times; identity, ownership and unsupported failures remain immediate STOP.
    """
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise RuntimeError("C5_SEMANTIC_REUSE_RETRY_BOUND_INVALID")
    for attempt in range(1, attempts + 1):
        try:
            return _verify_current_protected_backup_semantics(
                runtime_root=runtime_root, backup=backup,
                observed_counters=observed_counters,
            )
        except RuntimeError as error:
            if (str(error) != "C5_CURRENT_BACKUP_SEMANTIC_READ_TRANSIENT"
                    or attempt >= attempts):
                raise
            time.sleep(float(attempt))
    raise RuntimeError("C5_SEMANTIC_REUSE_RETRY_BOUND_EXHAUSTED")


def _refresh_current_protected_backup(*, runtime_root: Path,
                                      observed_counters: dict[str, int],
                                      runner=subprocess.run) -> dict:
    """Reuse the existing protected snapshot implementation at Product prepare.

    No deletion or alternate backup engine is introduced. A current exact backup
    is reused only when its sealed Mongo counters equal the write-fenced caller's
    observation. Otherwise the existing local snapshot+isolated-restore script is
    run once under its own JobAuthority and bounded quiescence checks.
    """
    observed = _validated_mongo_counters(observed_counters)
    try:
        current = _latest_current_protected_backup()
        if (current["mongo_write_counter"] == observed
                or _semantic_backup_current_with_bounded_retry(
                    runtime_root=runtime_root, backup=current,
                    observed_counters=observed)):
            return {**current, "reused": True}
    except RuntimeError as error:
        if str(error) != "C5_CURRENT_PROTECTED_BACKUP_RESTORE_REQUIRED":
            raise
    if not _C5_BACKUP_REFRESH_LOCK.acquire(blocking=False):
        raise RuntimeError("C5_PROTECTED_BACKUP_REFRESH_IN_PROGRESS")
    try:
        # A concurrent completed refresh may now satisfy the exact observation.
        try:
            current = _latest_current_protected_backup()
            if (current["mongo_write_counter"] == observed
                    or _semantic_backup_current_with_bounded_retry(
                        runtime_root=runtime_root, backup=current,
                        observed_counters=observed)):
                return {**current, "reused": True}
        except RuntimeError as error:
            if str(error) != "C5_CURRENT_PROTECTED_BACKUP_RESTORE_REQUIRED":
                raise
        script = runtime_root / "scripts" / "c5_current_protected_snapshot.py"
        if (
            not runtime_root.is_absolute()
            or not script.is_file()
            or script.is_symlink()
            or sha256(script.read_bytes()).hexdigest() != _C5_BACKUP_SCRIPT_SHA256
        ):
            raise RuntimeError("C5_PROTECTED_BACKUP_SCRIPT_IDENTITY_INVALID")
        completed = runner(
            [sys.executable, str(script)],
            cwd=str(runtime_root),
            env=dict(os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1200,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(_safe_backup_subprocess_code(completed))
        refreshed = _latest_current_protected_backup()
        return {**refreshed, "reused": False}
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("C5_PROTECTED_BACKUP_REFRESH_TIMEOUT") from error
    finally:
        _C5_BACKUP_REFRESH_LOCK.release()


def install_project_retirement_routes(
    app: FastAPI,
    get_service: Callable,
    *,
    runtime_root: Path,
    active_worker_count: Callable[[], int],
    active_project_worker_count: Callable[[str], int],
    owner_attestation: Callable[[], dict],
    verify_native_project_owner: Callable[..., dict] | None = None,
):
    if not callable(active_worker_count) or not callable(active_project_worker_count):
        raise RuntimeError("C5_CURRENT_EXECUTION_OWNER_UNAVAILABLE")
    def require_existing_adapter_proxy(request: Request) -> None:
        expected = os.environ.get("UR_RUNTIME_PROXY_KEY", "")
        if not expected:
            raise HTTPException(status_code=503, detail={"code": "RUNTIME_PROXY_KEY_NOT_CONFIGURED"})
        supplied = request.headers.get("x-ur-runtime-proxy", "")
        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=401, detail={"code": "RUNTIME_ADAPTER_AUTH_REQUIRED"})

    def report(error: WebContinuityError) -> None:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error

    def receipt_binding(*, librechat_project_id: str, owner_id: str,
                        runtime_project_id: str | None = None) -> dict | None:
        if (_NATIVE_ID.fullmatch(librechat_project_id or "") is None
                or _NATIVE_ID.fullmatch(owner_id or "") is None):
            return None
        command_id = (
            "final-shell-project-by-librechat-project-" +
            sha256(librechat_project_id.encode("utf-8")).hexdigest()[:28]
        )
        expected = _stable_id("PRJ", command_id, "LibreChat Project Context")
        if runtime_project_id is not None and runtime_project_id != expected:
            return None
        service = get_service()
        if not service._record_exists(service._project_artifact_id(expected)):
            return None
        project, _ = service._raw_project(expected)
        if (project.get("project_id") != expected
                or project.get("status", "ACTIVE") not in
                   {"ACTIVE", "RETIRE_PENDING", "RETIRED"}):
            return None
        return {
            "authoritative": True,
            "librechat_project_id": librechat_project_id,
            "owner_id": owner_id,
            "runtime_project_id": expected,
        }

    def receipt_writer(*, librechat_project_id: str, owner_id: str,
                       runtime_project_id: str, phase: str) -> dict:
        with _C5_LEASE_LOCK:
            lease = _C5_LEASES.get(runtime_project_id)
            valid = bool(
                lease
                and lease.get("native_project_id") == librechat_project_id
                and lease.get("owner_id") == owner_id
                and lease.get("expires_at", 0) > time.monotonic()
                and phase in {"PREPARED", "CASCADE_PENDING", "PARTIAL_OR_BLOCKED", "COMPLETE"}
            )
        return {
            "authorized": valid,
            "exclusive_writer": valid,
            "protected_backup_ready": valid,
            "active_pinned_jobs": 0 if valid else 1,
        }

    def receipt_owner(request: Request, native_project_id: str):
        require_existing_adapter_proxy(request)
        actor = request.headers.get("x-librechat-authenticated-user-id", "")
        binding = receipt_binding(
            librechat_project_id=native_project_id, owner_id=actor,
        )
        if binding is None:
            raise HTTPException(
                status_code=409, detail={"code": "C5_OWNER_BINDING_UNPROVEN"})
        return C5ProjectCascadeReceiptOwner(
            service=get_service(),
            librechat_project_id=native_project_id,
            owner_id=actor,
            runtime_project_id=binding["runtime_project_id"],
            verify_project_owner_binding=lambda **scope: receipt_binding(**scope),
            admitted_effect_writer=receipt_writer,
        )

    def receipt_stop(error: C5ReceiptStop):
        raise HTTPException(status_code=409, detail={"code": error.code}) from error

    # C5-only request-independent BACKUP PREPARE (NOT an executor platform).
    # Actual native owner verification must be bound by the Product consumer.
    # Runtime's authenticated transport alone is NOT proof of native ownership.
    _prepare_gate = threading.RLock()
    _prepare_running: dict[str, threading.Thread] = {}
    _prepare_started: set[str] = set()
    _prepare_owner_holder: dict[str, C5ProtectedBackupPrepareReceipt] = {}

    def _native_owner_proof(*, owner_id: str, project_id: str) -> dict:
        # Current signed request context is supplied by the existing
        # JWT+Mongo-verified LibreChat native owner -> admitted Adapter.
        scope = _C5_NATIVE_SCOPE.get()
        return {"owned": scope == (owner_id, project_id),
                "ownerId": owner_id, "projectId": project_id}

    def _native_owner_attestation(request: Request, actor: str, project: str):
        if verify_native_project_owner is not None:
            # Exact isolated test callback; Production uses the trusted adapter
            # HMAC assertion from the native getChatProject DB owner consumer.
            return (actor, project)
        secret = os.environ.get("UR_RUNTIME_PROXY_KEY", "")
        stamp = request.headers.get("x-c5-native-owner-timestamp", "")
        actual = request.headers.get("x-c5-native-owner-signature", "")
        if (not secret or not stamp.isdigit() or len(stamp) != 10
                or abs(time.time() - int(stamp)) > 90
                or _SHA.fullmatch(actual or "") is None):
            raise C5PrepareStop("C5_NATIVE_OWNER_ATTESTATION_MISSING_OR_EXPIRED")
        message = "|".join((
            "C5_NATIVE_OWNER_R001", actor, project, stamp,
            request.method, request.url.path,
        )).encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), message, sha256).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise C5PrepareStop("C5_NATIVE_OWNER_ATTESTATION_MISMATCH")
        return actor, project

    def _prepare_receipts() -> C5ProtectedBackupPrepareReceipt:
        with _prepare_gate:
            if "owner" not in _prepare_owner_holder:
                _prepare_owner_holder["owner"] = C5ProtectedBackupPrepareReceipt(
                    service=get_service(),
                    verify_native_owner=verify_native_project_owner or _native_owner_proof,
                    verify_current_backup=_latest_current_protected_backup,
                    verify_semantic_current_backup=(
                        lambda *, backup, observed_counters:
                            _semantic_backup_current_with_bounded_retry(
                                runtime_root=runtime_root, backup=backup,
                                observed_counters=observed_counters,
                            )
                    ),
                )
            return _prepare_owner_holder["owner"]

    def _prepare_intent(request: Request, payload: dict) -> tuple[str, str, str, dict, bool]:
        require_existing_adapter_proxy(request)
        actor = request.headers.get("x-librechat-authenticated-user-id", "")
        project = payload.get("projectId")
        owner = payload.get("ownerId")
        fence_sha = payload.get("fenceSha256")
        counters = payload.get("mongoWriteCountersBefore")
        manual_retry = payload.get("manualRetry")
        if not (
            isinstance(project, str) and _NATIVE_ID.fullmatch(project)
            and isinstance(owner, str) and _NATIVE_ID.fullmatch(owner)
            and actor == owner
            and isinstance(fence_sha, str) and _SHA.fullmatch(fence_sha)
            and payload.get("confirmedIrreversibleProjectDelete") is True
            and type(manual_retry) is bool
            and payload.get("phase") in
                {"C5_INVENTORY", "C5_NATIVE_RUNTIME_IDEMPOTENT_BINDING"}
        ):
            raise HTTPException(
                status_code=409, detail={"code": "C5_PREPARE_SCOPE_INVALID"},
            )
        _validated_mongo_counters(counters)
        if active_worker_count() != 0 or owner_attestation().get("status") != "SUPPORTED_RUNTIME_OWNER_ACTIVE":
            raise HTTPException(
                status_code=409, detail={"code": "C5_PREPARE_RUNTIME_OWNER_BUSY"},
            )
        return actor, project, fence_sha, counters, manual_retry

    def _prepare_run_worker(*, manager: C5ProtectedBackupPrepareReceipt,
                            actor: str, project: str, operation_id: str,
                            counters: dict) -> None:
        try:
            result = _refresh_current_protected_backup(
                runtime_root=runtime_root, observed_counters=counters,
            )
            manager.finalize(
                owner_id=actor, project_id=project, operation_id=operation_id,
                backup_id=result["backup_id"],
                backup_manifest_sha256=result["manifest_sha256"],
                protected_user_assets_sha256=result["user_assets_sha256"],
                counters=result["mongo_write_counter"],
            )
        except BaseException as error:
            raw = str(error)
            code = raw if re.fullmatch(r"C5_[A-Z0-9_]{1,120}", raw) else "C5_PREPARE_SNAPSHOT_OUTCOME_UNKNOWN"
            try:
                manager.fail(
                    owner_id=actor, project_id=project, operation_id=operation_id,
                    error_code=code, uncertain=True,
                )
            except BaseException:
                # Never manufacture VERIFIED. A PREPARING receipt from the
                # previous Runtime generation will fail closed on recovery.
                pass
        finally:
            with _prepare_gate:
                _prepare_running.pop(operation_id, None)

    @app.post("/api/web/c5/protected-backup/prepare-start")
    async def c5_prepare_start(request: Request):
        raise HTTPException(status_code=410, detail={"code": "C5_PER_DELETE_GLOBAL_BACKUP_DISABLED_USE_EXPLICIT_REPAIR"})
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise C5PrepareStop("C5_PREPARE_BODY_INVALID")
            actor, project, fence, counters, manual_retry = _prepare_intent(request, payload)
            proved = _native_owner_attestation(request, actor, project)
            token = _C5_NATIVE_SCOPE.set(proved)
            try:
                manager = _prepare_receipts()
                with _prepare_gate:
                    prior = manager.latest(owner_id=actor, project_id=project)
                    prior_id = prior.get("operationId")
                    prior_worker = _prepare_running.get(prior_id) if prior_id else None
                    previous_worker_absent = prior_worker is None or not prior_worker.is_alive()
                    if (manual_retry and prior.get("phase") == "PREPARING"
                            and previous_worker_absent and prior_id):
                        prior = manager.fail(
                            owner_id=actor, project_id=project,
                            operation_id=prior_id,
                            error_code="C5_PREPARE_WORKER_LOST",
                            uncertain=True,
                        )
                    started = manager.start(
                        owner_id=actor, project_id=project, counters=counters,
                        explicit_confirmed=True, fence_sha256=fence,
                        manual_retry=manual_retry,
                        previous_worker_absent=previous_worker_absent,
                    )
                    opid = started["operationId"]
                    if started["phase"] == "PREPARING":
                        if opid in _prepare_started and opid not in _prepare_running:
                            raise C5PrepareStop("C5_PREPARE_WORKER_OUTCOME_UNKNOWN")
                        if opid not in _prepare_started:
                            _prepare_started.add(opid)
                            # Context preserves ONLY authenticated request
                            # ownership, not the HTTP connection or user JWT.
                            current_context = copy_context()
                            worker = threading.Thread(
                                name="c5-existing-protected-backup",
                                target=current_context.run,
                                daemon=True, args=(_prepare_run_worker,),
                                kwargs={"manager": manager, "actor": actor,
                                        "project": project, "operation_id": opid,
                                        "counters": counters},
                            )
                            _prepare_running[opid] = worker
                            try:
                                worker.start()
                            except BaseException:
                                _prepare_running.pop(opid, None)
                                manager.fail(
                                    owner_id=actor, project_id=project,
                                    operation_id=opid,
                                    error_code="C5_PREPARE_WORKER_START_FAILED",
                                    uncertain=True,
                                )
                                raise C5PrepareStop("C5_PREPARE_WORKER_START_FAILED")
                    return JSONResponse(
                        status_code=202 if started["phase"] == "PREPARING" else 200,
                        content=started,
                    )
            finally:
                _C5_NATIVE_SCOPE.reset(token)
        except C5PrepareStop as error:
            raise HTTPException(status_code=409, detail={"code": error.code}) from error
        except RuntimeError as error:
            code = str(error)
            code = code if re.fullmatch(r"C5_[A-Z0-9_]{1,120}", code) else "C5_PREPARE_ADMISSION_FAILED"
            raise HTTPException(status_code=409, detail={"code": code}) from error

    @app.get("/api/web/c5/protected-backup/prepare-status")
    async def c5_prepare_status(request: Request):
        raise HTTPException(status_code=410, detail={"code": "C5_PER_DELETE_GLOBAL_BACKUP_DISABLED_USE_EXPLICIT_REPAIR"})
        require_existing_adapter_proxy(request)
        actor = request.headers.get("x-librechat-authenticated-user-id", "")
        project = request.query_params.get("projectId", "")
        opid = request.query_params.get("operationId", "")
        if not (_NATIVE_ID.fullmatch(project) and _NATIVE_ID.fullmatch(actor)):
            raise HTTPException(status_code=409, detail={"code": "C5_PREPARE_SCOPE_INVALID"})
        try:
            proved = _native_owner_attestation(request, actor, project)
            token = _C5_NATIVE_SCOPE.set(proved)
            try:
                manager = _prepare_receipts()
                with _prepare_gate:
                    current = (
                        manager.poll(
                            owner_id=actor, project_id=project, operation_id=opid,
                        ) if opid else manager.latest(
                            owner_id=actor, project_id=project,
                        )
                    )
                    active_id = current.get("operationId")
                    if current["phase"] == "PREPARING" and active_id in _prepare_started:
                        worker = _prepare_running.get(active_id)
                        if worker is None or not worker.is_alive():
                            current = manager.fail(
                                owner_id=actor, project_id=project,
                                operation_id=active_id,
                                error_code="C5_PREPARE_WORKER_LOST",
                                uncertain=True,
                            )
                    return JSONResponse(content=current, status_code=200)
            finally:
                _C5_NATIVE_SCOPE.reset(token)
        except C5PrepareStop as error:
            raise HTTPException(status_code=409, detail={"code": error.code}) from error

    @app.post("/api/web/c5/protected-backup/refresh")
    async def c5_protected_backup_refresh(request: Request):
        raise HTTPException(status_code=410, detail={"code": "C5_PER_DELETE_GLOBAL_BACKUP_DISABLED_USE_EXPLICIT_REPAIR"})
        require_existing_adapter_proxy(request)
        payload = await request.json()
        actor = request.headers.get("x-librechat-authenticated-user-id", "")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail={"code": "C5_BACKUP_REFRESH_BODY_REQUIRED"})
        native_project_id = payload.get("projectId")
        owner_id = payload.get("ownerId")
        phase = payload.get("phase")
        counters = payload.get("mongoWriteCountersBefore")
        if not (
            isinstance(native_project_id, str) and _NATIVE_ID.fullmatch(native_project_id)
            and isinstance(owner_id, str) and _NATIVE_ID.fullmatch(owner_id)
            and owner_id == actor
            and phase in {"C5_NATIVE_RUNTIME_IDEMPOTENT_BINDING", "C5_INVENTORY"}
        ):
            raise HTTPException(status_code=409, detail={"code": "C5_BACKUP_REFRESH_SCOPE_INVALID"})
        try:
            observed = _validated_mongo_counters(counters)
            attestation = owner_attestation()
            if (
                active_worker_count() != 0
                or attestation.get("status") != "SUPPORTED_RUNTIME_OWNER_ACTIVE"
            ):
                raise RuntimeError("C5_BACKUP_REFRESH_RUNTIME_OWNER_BUSY")
            # The existing snapshot/restore subprocess is long-running blocking I/O.
            # Keep the ASGI event loop responsive to health/status during prepare.
            # This does NOT create a durable/background job or authorize DELETE.
            refreshed = await run_in_threadpool(
                _refresh_current_protected_backup,
                runtime_root=runtime_root, observed_counters=observed,
            )
            return {
                "schema": "AIDES_C5_PROTECTED_BACKUP_PREPARE_R001",
                "projectId": native_project_id,
                "ownerId": owner_id,
                "backupId": refreshed["backup_id"],
                "backupManifestSha256": refreshed["manifest_sha256"],
                "protectedUserAssetsSha256": refreshed["user_assets_sha256"],
                "mongoWriteCounters": refreshed["mongo_write_counter"],
                "reused": refreshed["reused"],
                "ready": True,
            }
        except RuntimeError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": str(error), "message": "C5 protected backup prepare unavailable"},
            ) from error


    @app.get("/api/web/projects/{native_project_id}/cascade-receipt")
    async def c5_cascade_receipt_get(native_project_id: str, request: Request):
        try:
            value = receipt_owner(request, native_project_id).load()
            return {"found": value is not None, "record": value}
        except C5ReceiptStop as error:
            receipt_stop(error)

    @app.post("/api/web/projects/{native_project_id}/cascade-receipt")
    async def c5_cascade_receipt_post(native_project_id: str, request: Request):
        try:
            owner = receipt_owner(request, native_project_id)
            payload = await request.json()
            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=400, detail={"code": "C5_RECEIPT_BODY_INVALID"})
            if (payload.get("projectId") != native_project_id
                    or payload.get("ownerId") != owner.owner_id):
                raise HTTPException(
                    status_code=409, detail={"code": "C5_RECEIPT_BODY_SCOPE_MISMATCH"})
            return owner.persist(payload)
        except C5ReceiptStop as error:
            receipt_stop(error)

    @app.get("/api/web/project-retirement/resolve")
    def project_retirement_resolve(request: Request, command_id: str, display_name: str):
        require_existing_adapter_proxy(request)
        service = get_service()
        try:
            command_id = _validate_command_id(command_id)
            display_name = _validate_label(display_name, "display_name")
            project_id = _stable_id("PRJ", command_id, display_name)
            if not service._record_exists(service._project_artifact_id(project_id)):
                memories = service.memory_service.list_memories(
                    project_id=project_id, include_deleted=True,
                )
                prior_create = service._record_exists(
                    service._command_artifact_id(command_id)
                )
                receipts = service._project_operation_receipts(project_id)
                work = service._machine_local_project_work_binding(project_id)
                if (
                    prior_create or memories["state_revision"] != 0 or
                    receipts or work is not None
                ):
                    raise WebContinuityError(
                        "RUNTIME_PROJECT_ORPHAN_STATE",
                        "Related Runtime state exists without a canonical Project",
                        status_code=409,
                    )
                return {
                    "found": False, "native_only_verified": True,
                    "project_id": project_id,
                }
            project, _ = service._raw_project(project_id)
            if (
                project.get("created_by_command_id") != command_id
                or project.get("display_name") != display_name
            ):
                raise WebContinuityError(
                    "PROJECT_IDENTITY_CONFLICT",
                    "Project creation provenance mismatch", status_code=409,
                )
            return {
                "found": True,
                "project_id": project_id,
                "project_revision": project["project_revision"],
                "status": project.get("status", "ACTIVE"),
                "retirement": project.get("retirement"),
            }
        except WebContinuityError as error:
            report(error)

    @app.post("/api/web/projects/{project_id}/retirement/{action}")
    async def retire_project(project_id: str, action: str, request: Request):
        require_existing_adapter_proxy(request)
        if action not in {"prepare", "confirm", "abort", "commit"}:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ACTION"})
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("retirement_id"), str):
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST"})
        retirement_id = payload["retirement_id"]
        service = get_service()
        try:
            if action == "prepare":
                expected = payload.get("expected_project_revision")
                if not isinstance(expected, int) or isinstance(expected, bool):
                    raise HTTPException(status_code=400, detail={"code": "REVISION_REQUIRED"})
                return service.prepare_project_retirement(
                    retirement_id=retirement_id,
                    project_id=project_id,
                    expected_project_revision=expected,
                )
            if action == "confirm":
                return service.confirm_librechat_deleted(
                    retirement_id=retirement_id, project_id=project_id,
                )
            if action == "abort":
                if payload.get("reason_code") != "LIBRECHAT_DELETE_FAILED":
                    raise HTTPException(status_code=400, detail={"code": "ABORT_REASON_INVALID"})
                return service.abort_project_retirement(
                    retirement_id=retirement_id,
                    project_id=project_id,
                    reason_code="LIBRECHAT_DELETE_FAILED",
                )
            return service.commit_project_retirement(
                retirement_id=retirement_id, project_id=project_id,
            )
        except WebContinuityError as error:
            report(error)


    @app.post("/api/web/projects/{project_id}/sources/{source_ref_id}/retire-content")
    async def retire_project_source_content(
        project_id: str, source_ref_id: str, request: Request,
    ):
        """Expose the existing exact Source retirement primitive to the admitted Adapter.

        This route owns no File/Source graph and performs no classification. The
        authenticated LibreChat consumer supplies the frozen C5 scope; Runtime
        revalidates Project revision, owner, reference counts, protected census,
        binding evidence and idempotency before any content effect.
        """
        require_existing_adapter_proxy(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_BODY_REQUIRED"}
            )
        expected = payload.get("expected_project_revision")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_REVISION_REQUIRED"}
            )
        if not isinstance(source_ref_id, str) or not source_ref_id or len(source_ref_id) > 256:
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_SOURCE_ID_INVALID"}
            )
        required_strings = (
            "command_id", "owner_id", "binding_class", "binding_evidence_sha256",
        )
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_strings):
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_IDENTITY_REQUIRED"}
            )
        if not isinstance(payload.get("external_ref_counts"), dict):
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_REFERENCE_COUNTS_REQUIRED"}
            )
        if not isinstance(payload.get("native_file_ids"), list) or not isinstance(
            payload.get("source_ref_ids"), list
        ):
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_BINDING_SET_REQUIRED"}
            )
        census = payload.get("protected_asset_census_sha256")
        if census is not None and (not isinstance(census, str) or _SHA.fullmatch(census) is None):
            raise HTTPException(
                status_code=400, detail={"code": "SOURCE_RETIREMENT_CENSUS_INVALID"}
            )
        service = get_service()
        try:
            return service.retire_project_source_content(
                command_id=payload["command_id"],
                project_id=project_id,
                expected_project_revision=expected,
                source_ref_id=source_ref_id,
                owner_id=payload["owner_id"],
                external_ref_counts=payload["external_ref_counts"],
                protected_asset_census_sha256=census,
                binding_class=payload["binding_class"],
                native_file_ids=payload["native_file_ids"],
                source_ref_ids=payload["source_ref_ids"],
                binding_evidence_sha256=payload["binding_evidence_sha256"],
            )
        except WebContinuityError as error:
            report(error)


    @app.post("/api/web/projects/{project_id}/c5-admission")
    async def c5_project_admission(project_id: str, request: Request):
        """Hold existing JobAuthority lock and prove one target Project admission.

        Native Project ownership/membership and live Mongo counters are supplied
        by the authenticated LibreChat process and rebound to one short lease.
        This endpoint never performs Project/Chat/File deletion.
        """
        require_existing_adapter_proxy(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail={"code": "C5_ADMISSION_BODY_REQUIRED"})
        phase = payload.get("phase")
        native_project_id = payload.get("projectId")
        owner_id = payload.get("ownerId")
        actor_id = request.headers.get("x-librechat-authenticated-user-id", "")
        membership_sha256 = payload.get("projectMembershipSha256")
        counters = payload.get("mongoWriteCounters")
        supplied_lease = payload.get("leaseId")
        if not (
            phase in _C5_PHASES
            and isinstance(native_project_id, str) and _NATIVE_ID.fullmatch(native_project_id)
            and isinstance(owner_id, str) and _NATIVE_ID.fullmatch(owner_id)
            and actor_id == owner_id
            and isinstance(membership_sha256, str) and _SHA.fullmatch(membership_sha256)
            and isinstance(counters, dict)
            and all(type(counters.get(key)) is int and counters[key] >= 0
                    for key in ("insert", "update", "delete"))
            and (supplied_lease is None or
                 isinstance(supplied_lease, str) and
                 re.fullmatch(r"[A-Za-z0-9_-]{16,128}", supplied_lease))
        ):
            raise HTTPException(status_code=400, detail={"code": "C5_ADMISSION_SCOPE_INVALID"})
        service = get_service()
        try:
            with service._lock:
                if not service._record_exists(service._project_artifact_id(project_id)):
                    if phase != "C5_NATIVE_RUNTIME_IDEMPOTENT_BINDING":
                        raise RuntimeError("C5_RUNTIME_PROJECT_ADMISSION_STATE_MISSING")
                    memories = service.memory_service.list_memories(
                        project_id=project_id, include_deleted=True,
                    )
                    receipts = service._project_operation_receipts(project_id)
                    work = service._machine_local_project_work_binding(project_id)
                    if memories["state_revision"] != 0 or receipts or work is not None:
                        raise RuntimeError("C5_RUNTIME_PROJECT_ORPHAN_STATE")
                    revision = 1
                    status = "NATIVE_ONLY_PREBIND"
                else:
                    project, _ = service._raw_project(project_id)
                    revision = project.get("project_revision")
                    status = project.get("status", "ACTIVE")
                    if (
                        project.get("project_id") != project_id
                        or type(revision) is not int or revision < 1
                        or status not in {"ACTIVE", "RETIRE_PENDING", "RETIRED"}
                    ):
                        raise RuntimeError("C5_RUNTIME_PROJECT_ADMISSION_STATE_INVALID")
            if phase == "C5_COMPLETE_RELEASE" and status != "RETIRED":
                raise RuntimeError("C5_COMPLETE_RELEASE_REQUIRES_RETIRED_PROJECT")
            if phase == "C5_PRE_EFFECT_ABORT_RELEASE":
                if supplied_lease is None:
                    raise RuntimeError("C5_PRE_EFFECT_ABORT_LEASE_REQUIRED")
                released = _abort_c5_lease(
                    runtime_project_id=project_id,
                    native_project_id=native_project_id,
                    owner_id=owner_id,
                    membership_sha256=membership_sha256,
                    supplied_lease_id=supplied_lease,
                )
                counters_admitted = all(
                    counters[key] >= released["guard_counters"].get(key, -1)
                    for key in ("insert", "update", "delete")
                )
                return {
                    "schema": "AIDES_C5_TARGET_PROJECT_ADMISSION_R001",
                    "projectId": native_project_id,
                    "ownerId": owner_id,
                    "runtimeProjectId": project_id,
                    "projectRevision": released["sealed_project_revision"],
                    "runtimeCurrentRevision": revision,
                    "projectMembershipSha256": membership_sha256,
                    "projectMembershipSealed": True,
                    "jobScope": "TARGET_PROJECT_CURRENT_EFFECTS",
                    "activePinnedJobs": 0,
                    "activeFormalWorkers": active_worker_count(),
                    "exclusiveWriter": True,
                    "forwardRecoveryReady": counters_admitted,
                    "protectedBackupReady": False,
                    "mongoWriteCountersMatchBackup": False,
                    "mongoSemanticStateMatchBackup": False,
                    "mongoWriteCountersAdmitted": counters_admitted,
                    "protectionMode": released["protection_mode"],
                    "backupCreated": False,
                    "backupId": None,
                    "backupManifestSha256": None,
                    "protectedUserAssetsSha256": None,
                    "leaseId": released["lease_id"],
                    "knownMissingOriginalFileIds": [],
                    "permitted": True,
                    "leaseReleased": True,
                }
            # Normal permanent Project deletion is forward-recoverable from the
            # existing durable cascade receipt and exact native owner graph. Do
            # not create or require a whole-workspace recovery snapshot here.
            protection_mode = "FORWARD_ONLY_DURABLE_RECEIPT_R001"
            counters_admitted = True
            job_authority = JobAuthorityRegistry(service.store.root.parent, service.store)
            lease_id, created, sealed_revision = await run_in_threadpool(
                _hold_c5_lease,
                runtime_project_id=project_id,
                native_project_id=native_project_id,
                owner_id=owner_id,
                project_revision=revision,
                membership_sha256=membership_sha256,
                supplied_lease_id=supplied_lease,
                admission_phase=phase,
                protection_mode=protection_mode,
                guard_counters=counters,
                job_authority=job_authority,
            )
            try:
                job_facts = _c5_current_execution_scope_under_held_lease(
                    runtime_project_id=project_id,
                    native_project_id=native_project_id,
                    owner_id=owner_id,
                    membership_sha256=membership_sha256,
                    lease_id=lease_id,
                    active_project_worker_count=active_project_worker_count,
                )
                target_workers = job_facts.get("project_active_pinned_jobs")
                global_workers = active_worker_count()
                attestation = owner_attestation()
                permitted = (
                    counters_admitted
                    and job_facts.get("scope_verified") is True
                    and target_workers == 0
                    and attestation.get("status") == "SUPPORTED_RUNTIME_OWNER_ACTIVE"
                )
                result = {
                    "schema": "AIDES_C5_TARGET_PROJECT_ADMISSION_R001",
                    "projectId": native_project_id,
                    "ownerId": owner_id,
                    "runtimeProjectId": project_id,
                    "projectRevision": sealed_revision,
                    "runtimeCurrentRevision": revision,
                    "projectMembershipSha256": membership_sha256,
                    "projectMembershipSealed": True,
                    "jobScope": "TARGET_PROJECT_CURRENT_EFFECTS",
                    "activePinnedJobs": target_workers,
                    "activeFormalWorkers": target_workers,
                    "activeGlobalFormalWorkers": global_workers,
                    "currentExecutionScopeSource": job_facts.get("source"),
                    "historicalJobProjectionPerformed": False,
                    "exclusiveWriter": permitted,
                    "forwardRecoveryReady": permitted,
                    "protectedBackupReady": False,
                    "mongoWriteCountersMatchBackup": False,
                    "mongoSemanticStateMatchBackup": False,
                    "mongoWriteCountersAdmitted": counters_admitted,
                    "protectionMode": protection_mode,
                    "backupCreated": False,
                    "backupId": None,
                    "backupManifestSha256": None,
                    "protectedUserAssetsSha256": None,
                    "leaseId": lease_id,
                    "knownMissingOriginalFileIds": [],
                    "permitted": permitted,
                    "leaseReleased": False,
                }
                if phase == "C5_COMPLETE_RELEASE" and permitted:
                    _release_c5_lease(project_id, lease_id)
                    result["leaseReleased"] = True
                elif not permitted and created:
                    _release_c5_lease(project_id, lease_id)
                    result["leaseReleased"] = True
                return result
            except Exception:
                if created:
                    _release_c5_lease(project_id, lease_id)
                raise
        except (RuntimeError, WebContinuityError) as error:
            raw_code = str(error)
            code = (raw_code if re.fullmatch(r"C5_[A-Z0-9_]{1,120}", raw_code)
                    else "C5_TARGET_PROJECT_ADMISSION_UNAVAILABLE")
            # Persist only one bounded diagnostic event in the existing Runtime
            # stdout stream. No IDs, paths, stack, contents or arbitrary errors.
            print(json.dumps({
                "schema": "AIDES_C5_TARGET_PROJECT_ADMISSION_STOP_R001",
                "status": "STOP_PRE_EFFECT_ADMISSION",
                "phase": phase,
                "code": code,
            }, sort_keys=True), flush=True)
            raise HTTPException(
                status_code=409,
                detail={"code": code, "message": "C5 target Project admission unavailable"},
            ) from error


    @app.get("/api/web/projects/{project_id}/c5-reference-inventory")
    def c5_reference_inventory(project_id: str, request: Request):
        """Read current native-bound Runtime SourceRef + Memory owner, even RETIRED.

        Normal resume_project() intentionally disallows retired Projects; use
        existing _raw_project, _source_ref and memory_service with one owner lock.
        Project-scoped metadata only; NEVER transmit memory text/source contents,
        claim FileID or Blob exclusivity, or change any retirement state.
        """
        require_existing_adapter_proxy(request)
        service = get_service()
        try:
            with service._lock:
                project, _ = service._raw_project(project_id)
                if project.get("project_id") != project_id:
                    raise WebContinuityError(
                        "C5_PROJECT_SCOPE_CHANGED", "canonical project changed", status_code=409
                    )
                status = project.get("status", "ACTIVE")
                instruction_binding = project.get("project_instruction_binding")
                if not isinstance(instruction_binding, dict):
                    raise WebContinuityError(
                        "C5_INSTRUCTIONS_BINDING_INVALID",
                        "Canonical Instructions binding unavailable", status_code=409
                    )
                current_instructions = service._load_exact_text_binding(instruction_binding)
                current_instructions_empty = current_instructions == ""
                if status == "RETIRED" and not current_instructions_empty:
                    raise WebContinuityError(
                        "C5_RETIRED_INSTRUCTIONS_STILL_PRESENT",
                        "Retired Project retains current Instructions", status_code=409
                    )

                if status not in {"ACTIVE", "RETIRE_PENDING", "RETIRED"}:
                    raise WebContinuityError(
                        "C5_PROJECT_STATUS_UNSUPPORTED", "unknown project state", status_code=409
                    )
                source_ids = project.get("source_ref_ids")
                if not isinstance(source_ids, list) or len(source_ids) > 20000 or len(set(source_ids)) != len(source_ids):
                    raise WebContinuityError(
                        "C5_SOURCE_REFERENCE_GRAPH_INVALID", "invalid source references", status_code=409
                    )
                sources = []
                for source_id in source_ids:
                    ref, binding = service._source_ref(source_id)
                    if ref.get("project_id") != project_id or ref.get("source_ref_id") != source_id:
                        raise WebContinuityError(
                            "C5_SOURCE_REFERENCE_OWNER_INVALID", "cross-project source", status_code=409
                        )
                    artifact = ref.get("source_artifact_binding")
                    if not isinstance(artifact, dict) or not isinstance(artifact.get("sha256"), str):
                        raise WebContinuityError(
                            "C5_SOURCE_ARTIFACT_BINDING_INVALID", "source identity unavailable", status_code=409
                        )
                    provenance = ref.get("provenance")
                    sources.append({
                        "source_ref": {
                            "project_id": project_id,
                            "source_ref_id": source_id,
                            "origin_class": ref.get("origin_class"),
                            "source_artifact_binding": {"sha256": artifact["sha256"]},
                            "provenance": {
                                "conversation_id": provenance.get("conversation_id")
                            } if isinstance(provenance, dict) else None,
                        },
                        "binding": {"revision": binding.get("revision")},
                    })
                try:
                    retirement_sources = list_project_source_retirement_candidates(
                        service.store,
                        project_id=project_id,
                        active_source_ref_ids=list(source_ids),
                    )
                except SourceRetirementStop as error:
                    raise WebContinuityError(
                        "C5_SOURCE_RETIREMENT_CANDIDATES_UNAVAILABLE",
                        str(error),
                        status_code=409,
                    ) from error
                retirement_source_ids = [
                    row.get("source_ref_id") for row in retirement_sources
                ]
                protected_asset_census_sha256 = (
                    service.c5_protected_backup_manifest_census_sha256()
                )
                active_retirement_ids = {
                    row.get("source_ref_id") for row in retirement_sources
                    if row.get("active_project_binding") is True
                }
                if (
                    len(retirement_sources) > 20000
                    or len(set(retirement_source_ids)) != len(retirement_source_ids)
                    or active_retirement_ids != set(source_ids)
                ):
                    raise WebContinuityError(
                        "C5_SOURCE_RETIREMENT_CANDIDATE_GRAPH_INVALID",
                        "retirement Source identities are not exhaustive",
                        status_code=409,
                    )

                memory = service.memory_service.list_memories(
                    project_id=project_id, include_deleted=False
                )
                if memory.get("project_id") != project_id:
                    raise WebContinuityError(
                        "C5_MEMORY_PROJECT_SCOPE_INVALID", "foreign memory owner", status_code=409
                    )
                current_memories = [{
                    "project_id": project_id,
                    "memory_id": item["memory_id"],
                    "memory_revision": item["memory_revision"],
                    "lifecycle_state": item["lifecycle_state"],
                } for item in memory["memories"]]
                after, _ = service._raw_project(project_id)
                if (after.get("project_revision") != project.get("project_revision")
                    or after.get("status", "ACTIVE") != status
                    or after.get("source_ref_ids") != source_ids):
                    raise WebContinuityError(
                        "C5_RUNTIME_REFERENCE_READ_STALE", "project changed while reading", status_code=409
                    )
                memory_again = service.memory_service.list_memories(
                    project_id=project_id, include_deleted=False
                )
                if memory_again["state_revision"] != memory["state_revision"]:
                    raise WebContinuityError(
                        "C5_RUNTIME_MEMORY_READ_STALE", "memory changed while reading", status_code=409
                    )
                # Do not scan the 113 global historical JAE records to read
                # Project Source/Memory. Point-of-effect admission separately
                # establishes current target Job, writer and backup safety.
                final_project, _ = service._raw_project(project_id)
                if (
                    final_project.get("project_revision") != project.get("project_revision")
                    or final_project.get("status", "ACTIVE") != status
                    or final_project.get("source_ref_ids") != source_ids
                ):
                    raise WebContinuityError(
                        "C5_RUNTIME_PROJECT_CHANGED_AFTER_REFERENCE_READ",
                        "Project changed after Source/Memory read",
                        status_code=409,
                    )
                return {
                    "project": {
                        "project_id": project_id,
                        "project_revision": project["project_revision"],
                        "status": status,
                        "source_ref_ids": source_ids,
                    },
                    "sources": sources,
                    "retirement_sources": retirement_sources,
                    "protected_asset_census_sha256":
                        protected_asset_census_sha256,

                    "instructions": {"current_empty": current_instructions_empty},
                    "memory": {
                        "schema": memory["schema"],
                        "project_id": project_id,
                        "state_revision": memory["state_revision"],
                        "memories": current_memories,
                    },
                }
        except WebContinuityError as error:
            report(error)
