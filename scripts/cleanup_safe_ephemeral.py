from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

# Closed allowlist only. These are bounded scratch/test/cache namespaces with no durable consumer.
SAFE_TOP_LEVEL_DIRS = (
    ".e01-test-temp",
    ".e01-test-temp2",
    ".e01-test-temp3",
    ".e01-verify",
    ".phasec-tmp",
    ".phasec-tmp3",
    ".pytest_cache",
    ".pytest_tmp_d02",
    ".pytest_tmp_e4",
    ".pytest_tmp_okd_f1a",
    ".pytest_tmp_okd_product",
    ".test-tmp",
    "_pytest_tmp",
)

# Derived Python bytecode is auto-cleanable only inside these named namespaces.
PYCACHE_TOP_LEVELS = (".sidecars", "src", "tests", "packs")

# Explicitly outside this consumer's authority. Kept here as a guard/documented boundary.
PROTECTED_TOP_LEVELS = frozenset(
    {
        ".venv",
        ".staging",
        "artifacts",
        "handoff",
        "_authoritative",
        "governance",
        "config",
        "docs",
        "fixtures",
        "schemas",
        "scripts",
        "workspace",
    }
)

SCHEMA = "LOCAL_UNIVERSAL_RUNTIME_SAFE_EPHEMERAL_CLEANUP_RECEIPT_V1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def file_tree_bytes(path: Path) -> tuple[int, int, list[str]]:
    if not path.exists():
        return 0, 0, []
    if path.is_symlink():
        raise RuntimeError(f"SYMLINK_TARGET_FORBIDDEN:{path}")
    if path.is_file():
        return path.stat().st_size, 1, []
    total = 0
    files = 0
    errors: list[str] = []

    def on_walk_error(exc: OSError) -> None:
        filename = getattr(exc, "filename", None) or str(path)
        try:
            shown = Path(filename).resolve().relative_to(ROOT.resolve()).as_posix()
        except Exception:
            shown = str(filename)
        errors.append(f"WALK:{shown}:{type(exc).__name__}")

    for base, dirs, names in os.walk(
        path,
        topdown=True,
        followlinks=False,
        onerror=on_walk_error,
    ):
        base_path = Path(base)
        safe_dirs = []
        for name in dirs:
            child = base_path / name
            if child.is_symlink():
                errors.append(f"SYMLINK_CHILD:{child}")
                continue
            safe_dirs.append(name)
        dirs[:] = safe_dirs
        for name in names:
            p = base_path / name
            try:
                if p.is_symlink():
                    errors.append(f"SYMLINK_FILE:{p}")
                    continue
                total += p.stat().st_size
                files += 1
            except OSError as exc:
                errors.append(f"STAT:{p}:{type(exc).__name__}")
    return total, files, errors


def relative_checked(path: Path) -> str:
    resolved_root = ROOT.resolve()
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"OUTSIDE_PROJECT_ROOT:{path}") from exc
    if not rel.parts:
        raise RuntimeError("PROJECT_ROOT_DELETE_FORBIDDEN")
    if rel.parts[0] in PROTECTED_TOP_LEVELS:
        raise RuntimeError(f"PROTECTED_TOP_LEVEL:{rel.parts[0]}")
    return rel.as_posix()


def discover_targets() -> tuple[list[dict], list[dict]]:
    candidates: list[tuple[Path, str]] = []
    blocked: list[dict] = []
    for name in SAFE_TOP_LEVEL_DIRS:
        p = ROOT / name
        if p.exists():
            candidates.append((p, "SAFE_EPHEMERAL_BOUNDED_TEMP_ROOT"))

    for top in PYCACHE_TOP_LEVELS:
        base = ROOT / top
        if not base.exists():
            continue
        if base.is_symlink():
            raise RuntimeError(f"PYCACHE_NAMESPACE_SYMLINK_FORBIDDEN:{top}")
        namespace_errors: list[str] = []

        def on_namespace_error(exc: OSError) -> None:
            filename = getattr(exc, "filename", None) or str(base)
            try:
                shown = Path(filename).resolve().relative_to(ROOT.resolve()).as_posix()
            except Exception:
                shown = str(filename)
            namespace_errors.append(f"WALK:{shown}:{type(exc).__name__}")

        for current, dirs, _files in os.walk(
            base,
            topdown=True,
            followlinks=False,
            onerror=on_namespace_error,
        ):
            current_path = Path(current)
            # Never descend through links. Also skip node_modules: this consumer owns Python bytecode only.
            dirs[:] = [
                d
                for d in dirs
                if d != "node_modules" and not (current_path / d).is_symlink()
            ]
            if "__pycache__" in dirs:
                p = current_path / "__pycache__"
                candidates.append((p, "SAFE_EPHEMERAL_PYTHON_BYTECODE"))
                dirs.remove("__pycache__")
        for error in sorted(set(namespace_errors)):
            blocked.append(
                {
                    "path": top,
                    "category": "SAFE_EPHEMERAL_NAMESPACE_PARTIALLY_BLOCKED",
                    "reason": "ACL_OR_SCAN_BLOCKED_NO_PRIVILEGE_ESCALATION",
                    "error": error,
                }
            )

    unique: dict[str, tuple[Path, str]] = {}
    for path, category in candidates:
        rel = relative_checked(path)
        unique[rel] = (path, category)

    rows = []
    for rel in sorted(unique):
        path, category = unique[rel]
        size, files, errors = file_tree_bytes(path)
        if errors:
            blocked.append(
                {
                    "path": rel,
                    "category": category,
                    "reason": "ACL_OR_SCAN_BLOCKED_NO_PRIVILEGE_ESCALATION",
                    "errors": errors[:10],
                }
            )
            continue
        rows.append(
            {
                "path": rel,
                "category": category,
                "bytes_pre": size,
                "files_pre": files,
            }
        )
    blocked.sort(key=lambda row: (str(row.get("path", "")), str(row.get("error", row.get("errors", "")))))
    return rows, blocked


def sha_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def delete_target(rel: str) -> None:
    path = ROOT / Path(rel)
    checked = relative_checked(path)
    if checked != rel:
        raise RuntimeError(f"TARGET_REBIND_MISMATCH:{rel}:{checked}")
    if not path.exists():
        return
    if path.is_symlink():
        raise RuntimeError(f"SYMLINK_DELETE_FORBIDDEN:{rel}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    if path.exists():
        raise RuntimeError(f"DELETE_POSTCONDITION_FAILED:{rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded SAFE_EPHEMERAL cleanup for LocalUniversalRuntime")
    parser.add_argument("--apply", action="store_true", help="Apply deletion. Omit for dry-run inventory.")
    parser.add_argument("--receipt", type=Path, default=None, help="Optional receipt output path.")
    parser.add_argument(
        "--expected-plan-sha256",
        default=None,
        help="Optional exact dry-run plan SHA required before apply/current execution.",
    )
    args = parser.parse_args()

    rows, blocked = discover_targets()
    plan_sha = sha_json({"targets": rows, "blocked": blocked})
    if args.expected_plan_sha256 is not None and plan_sha != args.expected_plan_sha256:
        raise RuntimeError(
            f"PLAN_CHANGED_SINCE_DRY_RUN:expected={args.expected_plan_sha256}:actual={plan_sha}"
        )
    total_pre = sum(int(row["bytes_pre"]) for row in rows)
    files_pre = sum(int(row["files_pre"]) for row in rows)
    deleted: list[str] = []
    apply_blocked: list[dict] = []

    if args.apply:
        # Recheck each target immediately before mutation; discovery produced only fixed-class targets.
        for row in rows:
            rel = row["path"]
            path = ROOT / Path(rel)
            size_now, files_now, errors = file_tree_bytes(path)
            if errors:
                apply_blocked.append(
                    {
                        "path": rel,
                        "category": row["category"],
                        "reason": "ACL_OR_SCAN_BLOCKED_AT_APPLY_NO_PRIVILEGE_ESCALATION",
                        "errors": errors[:10],
                    }
                )
                continue
            if size_now != row["bytes_pre"] or files_now != row["files_pre"]:
                raise RuntimeError(f"TARGET_CHANGED_SINCE_PLAN:{rel}")
            try:
                delete_target(rel)
            except (PermissionError, OSError) as exc:
                apply_blocked.append(
                    {
                        "path": rel,
                        "category": row["category"],
                        "reason": "DELETE_BLOCKED_NO_PRIVILEGE_ESCALATION",
                        "error": type(exc).__name__,
                    }
                )
                continue
            deleted.append(rel)

    post_remaining = []
    if args.apply:
        for rel in deleted:
            if (ROOT / Path(rel)).exists():
                post_remaining.append(rel)
        if post_remaining:
            raise RuntimeError("DELETE_POSTCONDITION_SET_FAILED:" + repr(post_remaining))

    blocked_all = blocked + apply_blocked
    deleted_set = set(deleted)
    bytes_deleted = sum(int(row["bytes_pre"]) for row in rows if row["path"] in deleted_set)
    files_deleted = sum(int(row["files_pre"]) for row in rows if row["path"] in deleted_set)
    if args.apply:
        result_code = "PASS_SAFE_EPHEMERAL_APPLY_WITH_BLOCKED" if blocked_all else "PASS_SAFE_EPHEMERAL_APPLY"
    else:
        result_code = "PASS_SAFE_EPHEMERAL_DRY_RUN_WITH_BLOCKED" if blocked else "PASS_SAFE_EPHEMERAL_DRY_RUN"

    receipt = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now(),
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "authority": "USER_APPROVED_SAFE_EPHEMERAL_ONLY",
        "plan_sha256": plan_sha,
        "target_count": len(rows),
        "blocked_count": len(blocked_all),
        "bytes_planned": total_pre,
        "files_planned": files_pre,
        "bytes_deleted": bytes_deleted,
        "files_deleted": files_deleted,
        "targets": rows,
        "blocked": blocked_all,
        "deleted_paths": deleted,
        "privilege_escalation": False,
        "acl_mutation": False,
        "protected_classes": ["UNKNOWN", "RETAIN_EVIDENCE", "RETAIN_ROLLBACK", "RETAIN_USER_ASSET"],
        "protected_top_levels": sorted(PROTECTED_TOP_LEVELS),
        "docker_mutation": False,
        "production_mutation": False,
        "staging_candidate_deletion": False,
        "rollback_deletion": False,
        "user_asset_deletion": False,
        "result": result_code,
    }

    if args.receipt is not None:
        receipt_path = args.receipt
        if not receipt_path.is_absolute():
            receipt_path = ROOT / receipt_path
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("RECEIPT=" + str(receipt_path))
    print("RESULT=" + receipt["result"])
    print("TARGET_COUNT=" + str(len(rows)))
    print("BLOCKED_COUNT=" + str(len(blocked_all)))
    print("BYTES_PLANNED=" + str(total_pre))
    print("BYTES_DELETED=" + str(bytes_deleted))
    print("FILES_PLANNED=" + str(files_pre))
    print("FILES_DELETED=" + str(files_deleted))
    print("PLAN_SHA256=" + plan_sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
