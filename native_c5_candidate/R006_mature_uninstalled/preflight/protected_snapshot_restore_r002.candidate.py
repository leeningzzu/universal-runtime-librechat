"""One-shot local protected current Mongo + Runtime backup and isolated restore.

Proof ceiling: verified no-write observation window for Mongo standalone
(opcounters + exact EJSON per-document digests) and Runtime full-file SHA
manifest pre/post. NOT a distributed transaction or production cutover.

Does not mutate Production, invoke model providers, access network beyond
local Docker engine, or upload any backed-up content to external services.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
STAGING = pathlib.Path(__file__).resolve().parent
BACKUP_BASE = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "UniversalRuntime" / "ProtectedBackups"
MONGO_CONTAINER = "ur-web-r004-daily-mongo-r004"
# First-party LibreChat local user assets reside in the running UI writable
# layer, not the three pre-existing Runtime-only backup sources.
UI_CONTAINER = "ur-web-r004-daily-ui-r005"
UI_ASSET_PATHS = {
    "uploads": "/app/uploads",
    "images": "/app/client/public/images",
}

MONGO_IMAGE = "sha256:972a9fa5d0f06418faa85d3f831ebba14e203a55dee5cd2dbcaf09490d2eff31"
PROD_IMAGES = {
    "ur-web-r004-daily-ui-r005": "sha256:ebffd0ea8f5f2f37bf5da7a9bc1d352ea7aec149e6a4694dae82826d76c49a4c",
    "ur-web-r004-daily-adapter-r005": "sha256:d7d131710ac06de23d1b6b0a32b76176ba254e33767b502416e4bab438e57c59",
    MONGO_CONTAINER: MONGO_IMAGE,
}
PROD_ROUTE = "6ca05c2e04e2d2882f61d1937b59a23ff5c7141cb5e69531655605240e96ee76"
JS_DIGEST = r"""
const d=db.getSiblingDB('LibreChat');
const crypto=require('crypto');
const before=db.serverStatus();
const coll=d.getCollectionNames().sort();
const all=crypto.createHash('sha256');
const indexes=crypto.createHash('sha256');
const indexesRaw=crypto.createHash('sha256');
const canonical=(o)=>Array.isArray(o)
 ? '['+o.map(canonical).join(',')+']'
 : o!==null&&typeof o==='object'
   ? '{'+Object.keys(o).sort().map(k=>JSON.stringify(k)+':'+canonical(o[k])).join(',')+'}'
   : JSON.stringify(o);
// Compare exact typed index options regardless of top-level BSON field
// serialization order, while preserving COMPOUND index key field order.
const canonicalIndex=(spec)=>{
 const serialized=EJSON.serialize(spec,{relaxed:false});
 const fields=Object.keys(serialized).sort().map(key=>[
  key,
  key==='key' ? EJSON.stringify(spec.key,{relaxed:false}) : canonical(serialized[key])
 ]);
 return JSON.stringify(fields);
};
let docs=0;
let indexCount=0;
for(const name of coll){
 const h=crypto.createHash('sha256');
 const cursor=d.getCollection(name).find({}).sort({_id:1}).batchSize(300);
 let n=0;
 while(cursor.hasNext()){
   h.update(EJSON.stringify(cursor.next(),{relaxed:false})+'\n');
   n++;
 }
 all.update(name+'|'+n+'|'+h.digest('hex')+'\n');
 const ix=d.getCollection(name).getIndexes();
 indexCount+=ix.length;
 indexesRaw.update(name+'|'+EJSON.stringify(ix,{relaxed:false})+'\n');
 indexes.update(name+'|'+ix.map(canonicalIndex).sort().join('\n')+'\n');
 docs+=n;
}
const after=db.serverStatus();
const writes=(s)=>({
 insert:Number(s.opcounters.insert),
 update:Number(s.opcounters.update),
 delete:Number(s.opcounters.delete)
});
print(JSON.stringify({
 data_sha256:all.digest('hex'),
 index_sha256:indexes.digest('hex'),
 raw_index_sha256:indexesRaw.digest('hex'),
 indexes:indexCount,
 collections:coll.length,documents:docs,
 pre:writes(before),post:writes(after),
 uptime_pre:before.uptime,uptime_post:after.uptime
}));
"""


def run(argv: list[str], *, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        argv, capture_output=True, text=True,
        errors="replace", encoding="utf-8", timeout=timeout,
    )
    if check and result.returncode:
        raise RuntimeError(
            "LOCAL_EXEC_FAILED " + pathlib.Path(argv[0]).name +
            " exit=" + str(result.returncode)
        )
    return result


def sha_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def assert_safe_tree(root: pathlib.Path) -> None:
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("CANONICAL_RUNTIME_ROOT_UNAVAILABLE")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            p = pathlib.Path(dirpath) / name
            attrs = getattr(os.lstat(p), "st_file_attributes", 0)
            if p.is_symlink() or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise RuntimeError("CANONICAL_SOURCE_REPARSE_ENTRY_DENIED")


def scan_tree(root: pathlib.Path) -> dict[str, Any]:
    if not root.is_dir():
        return {"exists": False, "count": 0, "bytes": 0, "sha256": None}
    assert_safe_tree(root)
    tally = hashlib.sha256()
    count = 0
    total = 0
    for parent, dirnames, names in os.walk(root, followlinks=False):
        dirnames.sort()
        names.sort()
        for name in names:
            p = pathlib.Path(parent) / name
            rel = p.relative_to(root).as_posix()
            before = p.stat()
            digest = sha_file(p)
            after = p.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError("SOURCE_FILE_MUTATED_DURING_HASH")
            tally.update(rel.encode("utf-8") + b"\0")
            tally.update(str(after.st_size).encode() + b"\0")
            tally.update(digest.encode() + b"\n")
            count += 1
            total += after.st_size
    return {
        "exists": True,
        "count": count,
        "bytes": total,
        "sha256": tally.hexdigest(),
    }


def scan_all(roots: dict[str, pathlib.Path]) -> dict[str, dict[str, Any]]:
    return {name: scan_tree(root) for name, root in roots.items()}


def current_ui_asset_fingerprint() -> str:
    """Source read only. Hash file names and bytes without exposing any names."""
    shell = (
        'set -eu; cd /app; '
        'for d in uploads client/public/images; do '
        'if [ -L "$d" ]; then exit 70; fi; '
        'if [ -d "$d" ]; then '
        'test -z "$(find "$d" -type l -print -quit)" || exit 71; '
        'tar -cf /dev/null "$d"; '
        'printf "P:%s\\n" "$d"; '
        'find "$d" -type f -print0 | LC_ALL=C sort -z | '
        'xargs -0 -r sha256sum | sha256sum; '
        'elif [ ! -e "$d" ]; then printf "A:%s\\n" "$d"; '
        'else exit 72; fi; done'
    )
    result = run(["docker.exe","exec",UI_CONTAINER,"sh","-c",shell],timeout=90)
    lines=result.stdout.splitlines()
    state=[line for line in lines if line[:2] in {"P:","A:"}]
    if [line[2:] for line in state]!=["uploads","client/public/images"]:
        raise RuntimeError("UI_ASSET_DIRECTORY_STATUS_UNVERIFIED")
    digests=[line for line in lines if line[:2] not in {"P:","A:"}]
    if len(digests)!=sum(line.startswith("P:") for line in state):
        raise RuntimeError("UI_ASSET_FINGERPRINT_INCOMPLETE")
    if any(len(line.split()[0])!=64 or
           any(ch not in "0123456789abcdef" for ch in line.split()[0])
           for line in digests):
        raise RuntimeError("UI_ASSET_HASH_UNVERIFIED")
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def copy_ui_assets_to_protected_backup(dest: pathlib.Path) -> dict[str, dict[str, Any]]:
    """Docker-native read-only copy from existing UI into protected local backup."""
    dest.mkdir(parents=True,exist_ok=False)
    for kind,container_path in UI_ASSET_PATHS.items():
        query = ["docker.exe","exec",UI_CONTAINER,"sh","-c",
                 "test -d '"+container_path+"'"]
        available=run(query,timeout=25,check=False)
        if available.returncode != 0:
            absent=run(["docker.exe","exec",UI_CONTAINER,"sh","-c",
                        "test ! -e '"+container_path+"' && test ! -L '"+container_path+"'"],
                       timeout=25,check=False)
            if absent.returncode != 0:
                raise RuntimeError("UI_USER_ASSET_DIRECTORY_AMBIGUOUS")
            # A never-created first-party folder is a valid absence only if
            # pre/post live fingerprints attest that it stayed absent.
            continue
        target=dest/kind
        target.mkdir()
        run(["docker.exe","cp",UI_CONTAINER+":"+container_path+"/.",str(target)],timeout=180)
    return scan_all({name:dest/name for name in UI_ASSET_PATHS})


def mongo_observation(container: str) -> dict[str, Any]:
    raw = run(
        ["docker.exe", "exec", container, "mongosh", "--quiet", "--eval", JS_DIGEST],
        timeout=75,
    ).stdout
    try:
        value = json.loads(raw.strip().splitlines()[-1])
    except Exception as exc:
        raise RuntimeError("MONGO_DIGEST_UNAVAILABLE") from exc
    for key in ("insert", "update", "delete"):
        if value["pre"][key] != value["post"][key]:
            raise RuntimeError("MONGO_WRITES_DURING_DIGEST")
    if value["uptime_post"] < value["uptime_pre"]:
        raise RuntimeError("MONGO_RESTART_DURING_DIGEST")
    return value


def same_window(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        before["post"] == after["pre"]
        and before["data_sha256"] == after["data_sha256"]
        and before["index_sha256"] == after["index_sha256"]
        and before["collections"] == after["collections"]
        and before["documents"] == after["documents"]
        and after["uptime_pre"] >= before["uptime_post"]
    )


def check_production() -> None:
    for name, image in PROD_IMAGES.items():
        actual = run(["docker.exe","inspect","--format","{{.Image}}",name],timeout=25).stdout.strip()
        if actual != image:
            raise RuntimeError("PRODUCTION_CONTAINER_IMAGE_CHANGED")
        state = run(["docker.exe","inspect","--format","{{.State.Status}}",name],timeout=25).stdout.strip()
        if state != "running":
            raise RuntimeError("PRODUCTION_CONTAINER_NOT_RUNNING")
    actual_route = run([
        "docker.exe","exec","ur-web-r004-daily-ui-r005",
        "sha256sum","/app/api/server/routes/projects.js",
    ],timeout=25).stdout.strip().split()[0]
    if actual_route != PROD_ROUTE:
        raise RuntimeError("PRODUCTION_PROJECT_DELETE_ROUTE_CHANGED")


def user_only_acl(target: pathlib.Path) -> None:
    sid_lines = run(["whoami.exe","/user","/fo","csv","/nh"],timeout=15).stdout
    rows = list(csv.reader(io.StringIO(sid_lines)))
    if not rows or len(rows[0]) < 2 or not rows[0][1].startswith("S-1-5-"):
        raise RuntimeError("WINDOWS_USER_SID_UNAVAILABLE")
    user_sid = rows[0][1]
    cmd = [
        "icacls.exe",str(target),"/inheritance:r","/grant:r",
        "*" + user_sid + ":(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F",
    ]
    run(cmd,timeout=25)
    run(["icacls.exe",str(target),"/verify"],timeout=20)
    # No personal SID or ACL security principal names printed or stored.
    print("ACL_OWNER_SYSTEM_ONLY_SETUP=PASS",flush=True)


def local_backup_base() -> pathlib.Path:
    if not os.environ.get("LOCALAPPDATA"):
        raise RuntimeError("LOCALAPPDATA_NOT_SET")
    for p in (BACKUP_BASE.parent.parent,BACKUP_BASE.parent,BACKUP_BASE):
        if p.is_symlink():
            raise RuntimeError("LOCAL_BACKUP_PATH_REPARSE")
    BACKUP_BASE.mkdir(parents=True,exist_ok=True)
    return BACKUP_BASE


def strict_test_root(p: pathlib.Path) -> None:
    root = p.resolve()
    assert root.parent == BACKUP_BASE.resolve()
    if root.exists():
        raise RuntimeError("PROTECTED_BACKUP_DESTINATION_COLLISION")


def wait_clone(name: str) -> None:
    for _ in range(35):
        out = run([
            "docker.exe","exec",name,"mongosh","--quiet",
            "--eval","print(db.adminCommand({ping:1}).ok)",
        ],timeout=12,check=False)
        if out.returncode == 0 and out.stdout.strip().endswith("1"):
            return
        time.sleep(1)
    raise RuntimeError("ISOLATED_RESTORE_MONGO_NOT_READY")


def run_backup():
    started = datetime.now(timezone.utc).isoformat()
    check_production()
    root = pathlib.Path.cwd().resolve()
    if not (root / "AGENTS.md").is_file() or not (
        root / "src" / "universal_runtime" / "web_continuity.py"
    ).is_file():
        raise RuntimeError("LOGICAL_RUNTIME_WORKSPACE_IDENTITY_UNVERIFIED")
    if not (root / "artifacts").is_dir():
        raise RuntimeError("LIVE_ARTIFACTSTORE_MISSING")
    machine_local = pathlib.Path(os.environ["LOCALAPPDATA"]) / "UniversalRuntime" / "machine_local"
    sources = {
        "runtime_artifacts": root / "artifacts",
        "machine_local": machine_local,
        "installed_projection": root / "_installed",
    }
    for name, path in sources.items():
        assert path.is_dir() and not path.is_symlink(), (
            "SOURCE_SCOPE_NOT_PROVEN", name
        )
    if shutil.disk_usage(root).free < 3 * 1024**3:
        raise RuntimeError("LOCAL_FREE_SPACE_INSUFFICIENT")
    backup_id = "C5_R001_" + time.strftime("%Y%m%dT%H%M%SZ",time.gmtime()) + "_" + uuid.uuid4().hex[:8]
    base = local_backup_base()
    dest = base / backup_id
    strict_test_root(dest)
    evidence_id = backup_id
    clone_name = "ur-c5restore-" + uuid.uuid4().hex[:12]
    clone_running = False
    dest_created = False
    valid_snapshot = False
    summary = None
    try:
        dest.mkdir()
        dest_created = True
        user_only_acl(dest)
        (dest / "runtime").mkdir()
        # Capture live writable-layer user bytes as part of the SAME
        # Mongo+Runtime consistent window; no new data backend.
        ui_digest_before=current_ui_asset_fingerprint()
        ui_assets=copy_ui_assets_to_protected_backup(dest/"ui_assets")
        if current_ui_asset_fingerprint()!=ui_digest_before:
            raise RuntimeError("UI_USER_UPLOADS_CHANGED_DURING_COPY")
        print("UI_WRITABLE_USER_ASSETS_PROTECTED=PASS",flush=True)

        # Runtime source copy is expensive; prepare it BEFORE the bounded
        # Mongo no-write window. Exact source hashes are reverified AFTER
        # the Mongo export so one stable canonical Runtime state spans it.
        baseline_trees = scan_all(sources)
        print("INITIAL_CANONICAL_SOURCE_SCANS=PASS",flush=True)
        for key, source in sources.items():
            shutil.copytree(source,dest / "runtime" / key,copy_function=shutil.copy2)
        copied_trees = scan_all({
            k:dest / "runtime" / k for k in sources
        })
        if baseline_trees != copied_trees:
            raise RuntimeError("RUNTIME_COPY_DIFFERS_FROM_PREIMAGE")
        check_production()
        print("RUNTIME_IMMUTABLE_COPY_AND_SHA_CHECK=PASS",flush=True)
        baseline_mongo = mongo_observation(MONGO_CONTAINER)

        # Use mature tools; dump runs in a disposable container on the
        # existing Mongo network namespace. It never writes into live Mongo.
        args = [
            "docker.exe","run","--rm","--pull","never",
            "--network","container:" + MONGO_CONTAINER,
            "--mount","type=bind,source=" + str(dest) + ",target=/checkpoint",
            "--entrypoint","mongodump",MONGO_IMAGE,
            "--host","127.0.0.1:27017",
            "--db","LibreChat","--archive=/checkpoint/mongo.archive.gz","--gzip",
        ]
        run(args,timeout=210)
        archive = dest / "mongo.archive.gz"
        if not archive.is_file() or archive.stat().st_size == 0:
            raise RuntimeError("MONGO_ARCHIVE_MISSING_OR_EMPTY")
        print("MATURE_MONGO_DUMP_LOCAL_ONLY=PASS",flush=True)

        # Mongo standalone has no oplog: observe immutable write counters,
        # complete logical document/index digests and monotonic uptime for
        # the narrow dump window. Never promote a changing dump to a snapshot.
        final_mongo = mongo_observation(MONGO_CONTAINER)
        if not same_window(baseline_mongo,final_mongo):
            raise RuntimeError("PRODUCTION_MONGO_CHANGED_DURING_DUMP")
        print("MONGO_STANDALONE_QUIESCENT_DUMP_WINDOW=PASS",flush=True)

        # Canonical Runtime records must remain exact across that same
        # bounded Mongo window. Later Runtime writes are outside this backup.
        post_trees = scan_all(sources)
        if baseline_trees != post_trees or baseline_trees != copied_trees:
            raise RuntimeError("ARTIFACTSTORE_CHANGED_DURING_BACKUP")
        if current_ui_asset_fingerprint()!=ui_digest_before:
            raise RuntimeError("UI_USER_ASSETS_CHANGED_DURING_MONGO_BACKUP")
        if scan_all({k:dest/"ui_assets"/k for k in UI_ASSET_PATHS})!=ui_assets:
            raise RuntimeError("PROTECTED_UI_USER_ASSET_COPY_CHANGED")
        check_production()
        valid_snapshot = True
        print("BOUNDED_CROSS_PLANE_VERIFIED_STATIC_WINDOW=PASS",flush=True)

        # Restore ONLY into an isolated Mongo container: no port publishing,
        # no Production volume, and the protected host archive mounted RO.
        run([
            "docker.exe","run","--rm","-d","--pull","never",
            "--name",clone_name,"--network","none",
            "--mount","type=bind,source=" + str(dest) + ",target=/checkpoint,readonly",
            MONGO_IMAGE,
        ],timeout=40)
        clone_running=True
        wait_clone(clone_name)
        run([
            "docker.exe","exec",clone_name,
            "mongorestore","--archive=/checkpoint/mongo.archive.gz","--gzip",
            "--nsInclude=LibreChat.*",
        ],timeout=210)
        restored_mongo = mongo_observation(clone_name)
        if (
            restored_mongo["data_sha256"] != baseline_mongo["data_sha256"]
            or restored_mongo["index_sha256"] != baseline_mongo["index_sha256"]
            or restored_mongo["indexes"] != baseline_mongo["indexes"]
            or restored_mongo["collections"] != baseline_mongo["collections"]
            or restored_mongo["documents"] != baseline_mongo["documents"]
        ):
            raise RuntimeError("ISOLATED_MONGO_DATA_OR_INDEX_MISMATCH")
        print("ISOLATED_MONGO_RESTORE_FULL_DOC_AND_INDEX_DIGEST=PASS",flush=True)

        # Simulate Runtime canonical-data recovery without modifying live
        # Runtime. This is a separate isolated path with exactly the same
        # manifest and canonical content hashes.
        isolated = dest / "isolated_restore_validation"
        isolated.mkdir()
        for key in sources:
            restore_name = "_installed" if key == "installed_projection" else key
            shutil.copytree(dest / "runtime" / key,isolated / restore_name)
        restored_trees = scan_all({
            k:isolated / ("_installed" if k == "installed_projection" else k)
            for k in sources
        })
        if restored_trees != baseline_trees:
            raise RuntimeError("ISOLATED_RUNTIME_ARTIFACT_BYTES_MISMATCH")
        print("ISOLATED_RUNTIME_RESTORE_EXACT_TREE_SHA=PASS",flush=True)
        # Verify user byte recovery from the protected backup into a
        # disposable isolated restore root, never the current UI container.
        ui_recovered=isolated/"ui_assets"
        ui_recovered.mkdir()
        for k in UI_ASSET_PATHS:
            if ui_assets[k]["exists"]:
                shutil.copytree(dest/"ui_assets"/k,ui_recovered/k,copy_function=shutil.copy2)
        if scan_all({k:ui_recovered/k for k in UI_ASSET_PATHS})!=ui_assets:
            raise RuntimeError("ISOLATED_UI_ASSET_BYTES_RESTORE_MISMATCH")
        print("ISOLATED_UI_UPLOAD_IMAGE_BYTE_RESTORE=PASS",flush=True)

        # Native LibreChat Project ID -> Runtime's existing deterministic
        # creation identity mapping; never log individual IDs or contents.
        sys.path.insert(0,str(root / "src"))
        from universal_runtime.web_continuity import _stable_id
        from universal_runtime.core.artifact_store import ArtifactStore
        from universal_runtime.installed_pack_projection import InstalledPackProjection
        from universal_runtime.installed_pack_web_continuity_adapter import InstalledPackWebContinuityService
        from universal_runtime.packs.registry import PackRegistry
        clone_store = ArtifactStore(isolated / "runtime_artifacts")
        # The accepted Runtime owns an exact legacy absolute-manifest
        # relocation primitive. Apply it ONLY to restored, isolated bytes.
        # This current-PC recovery uses the still-available old canonical
        # root to authenticate the legacy locator, then the cloned payload.
        # It does NOT prove source-independent disaster recovery (C6).
        relocation = clone_store.relocate_legacy_absolute_manifests(
            source_root=sources["runtime_artifacts"],
        )
        if relocation["result"] not in {"PASS", "NO_OP"}:
            raise RuntimeError("CLONE_LEGACY_REBIND_FAILED")
        relocated_count = int(relocation["migrated_manifest_count"])
        if relocated_count <= 0:
            raise RuntimeError("EXPECTED_LEGACY_RUNTIME_LOCATORS_NOT_REBOUND")
        print("ISOLATED_LEGACY_PROJECT_MANIFEST_REBIND=PASS",flush=True)
        clone_service = InstalledPackWebContinuityService(
            clone_store,
            installed_projection=InstalledPackProjection(isolated),
            promoted_registry=PackRegistry(root / "packs"),
            machine_local_state_root=isolated / "machine_local",
        )
        js = "const d=db.getSiblingDB('LibreChat');print(JSON.stringify(d.chatprojects.find({}, {_id:1}).toArray().map(x=>x._id.toString())))"
        stdout=run(["docker.exe","exec",clone_name,"mongosh","--quiet","--eval",js],timeout=30).stdout
        raw_ids=json.loads(stdout.strip().splitlines()[-1])
        mapping=0;packless=0
        for native_id in raw_ids:
            command_id="final-shell-project-by-librechat-project-" + hashlib.sha256(native_id.encode()).hexdigest()[:28]
            pid=_stable_id("PRJ",command_id,"LibreChat Project Context")
            project=clone_service.resolve_project_instructions_by_creation_identity(
                command_id=command_id,display_name="LibreChat Project Context"
            )
            if project is None or project.get("project_id") != pid:
                raise RuntimeError("ISOLATED_PROJECT_CROSS_PLANE_BINDING_MISSING")
            binding=clone_service.get_project_pack_binding(project_id=pid)
            mapping+=1
            if binding["binding"] is None:
                packless+=1
        if mapping != len(raw_ids):
            raise RuntimeError("RESTORED_PROJECT_COUNTS_MISMATCH")
        print("ISOLATED_LIBRECHAT_TO_RUNTIME_PROJECT_IDENTITY=PASS",flush=True)

        # Validate the backup itself remains exact before discarding temporary
        # isolated restored data; retain only the one owner-ACL-protected backup.
        backup_validation=scan_all({k:dest / "runtime" / k for k in sources})
        if backup_validation != baseline_trees:
            raise RuntimeError("PROTECTED_BACKUP_MUTATED_DURING_RESTORE")
        if scan_all({k:dest/"ui_assets"/k for k in UI_ASSET_PATHS})!=ui_assets:
            raise RuntimeError("PROTECTED_UI_ASSET_BACKUP_MUTATED_DURING_RESTORE")
        details={
            "schema":"C5_LOCAL_PROTECTED_BACKUP_ISOLATED_RESTORE_R001",
            "status":"PASS_BOUNDED_VERIFIED_QUIESCENT_SNAPSHOT_AND_ISOLATED_RESTORE",
            "proof_ceiling":"MONGO_STANDALONE_NO_WRITES_OVER_OBSERVED_WINDOW_PLUS_RUNTIME_SHA_PREPOST; NOT_TRANSACTIONAL_PRODUCTION_SNAPSHOT",
            "backup_id":evidence_id,
            "backup_path_class":"LOCALAPPDATA/UniversalRuntime/ProtectedBackups",
            "backed_up_at_utc":started,
            "mongo":{"collections":baseline_mongo["collections"],"documents":baseline_mongo["documents"],"ejson_sha256":baseline_mongo["data_sha256"],"index_sha256":baseline_mongo["index_sha256"],"archive_bytes":archive.stat().st_size,"archive_sha256":sha_file(archive),"write_counter_before":baseline_mongo["pre"],"write_counter_after":final_mongo["post"],"uptime_monotonic":final_mongo["uptime_post"]>baseline_mongo["uptime_pre"]},
            "runtime":{"trees":baseline_trees,"isolated_byte_restore_sha_equal":True,"legacy_manifests_rebound_in_isolated_copy":relocated_count,"legacy_rebind_requires_original_root_for_validation":True},
            "live_ui_user_assets":{"tree_hashes":ui_assets,"source_sha256":ui_digest_before,"isolated_restore_sha_equal":True},
            "cross_plane":{"native_project_count":len(raw_ids),"runtime_mapping_count":mapping,"packless_project_count":packless},
            "source_effects":{"production_mutation":False,"real_delete":False,"provider_calls":0,"external_upload":False,"promotion":False},
            "not_proven":["transactionally atomic snapshot under concurrent Mongo/Runtime writes","source-independent or different-machine legacy restore","actual C5 cutover","human Project delete acceptance","C5 Full/Product/Program PASS"],
        }
        (dest / "BACKUP_MANIFEST.json").write_text(json.dumps(details,sort_keys=True,indent=2)+"\n",encoding="utf-8",newline="\n")
        public_path=STAGING / "C5_PROTECTED_BACKUP_AND_RESTORE_RESULT_R001.json"
        public_summary={
            "schema":details["schema"],
            "status":details["status"],
            "proof_ceiling":details["proof_ceiling"],
            "backup_id":evidence_id,
            "backup_path_class":details["backup_path_class"],
            "mongo_collections":details["mongo"]["collections"],
            "mongo_documents":details["mongo"]["documents"],
            "mongo_archive_sha256":details["mongo"]["archive_sha256"],
            "mongo_data_sha256":details["mongo"]["ejson_sha256"],
            "runtime_trees":baseline_trees,
            "live_ui_user_asset_trees":ui_assets,
            "ui_byte_restore_verified":True,
            "legacy_manifests_rebound_in_isolated_copy":relocated_count,
            "source_independent_disaster_recovery_proven":False,
            "isolated_project_mapping_count":mapping,
            "isolated_packless_project_count":packless,
            "backup_acl":"USER_AND_SYSTEM_ONLY",
            "production_mutated":False,
            "content_uploaded":False,
            "not_proven":details["not_proven"],
        }
        public_path.write_text(json.dumps(public_summary,sort_keys=True,indent=2)+"\n",encoding="utf-8",newline="\n")
        summary=public_summary
        print(json.dumps({
            "status":details["status"],
            "mongo_collections":details["mongo"]["collections"],
            "mongo_documents":details["mongo"]["documents"],
            "runtime_files":sum(x["count"] for x in baseline_trees.values()),
            "runtime_data_MB":round(sum(x["bytes"] for x in baseline_trees.values())/1024**2,1),
            "ui_user_assets_MB":round(sum(x["bytes"] for x in ui_assets.values())/1024**2,1),
            "cross_plane_projects":mapping,
            "backup_id":evidence_id,
            "protected_local":True,
        }),flush=True)
    except Exception as exc:
        print(json.dumps({
            "status":"STOP_PROTECTED_BACKUP_OR_RESTORE",
            "error_class":type(exc).__name__,
            "error_code":str(exc)[:180],
            "backup_id":evidence_id,
            "verified_snapshot":valid_snapshot,
        }),flush=True)
        err={
            "status":"STOP",
            "error_class":type(exc).__name__,
            "reason":str(exc)[:180],
            "current_snapshot_accepted":False,
            "backup_path_class":"LOCALAPPDATA/UniversalRuntime/ProtectedBackups",
            "backup_id":evidence_id,
            "trace_tail":traceback.format_exc()[-1800:].replace(str(root),"[LOCAL_RUNTIME]"),
        }
        (STAGING/"STOP_C5_BACKUP_R001.json").write_text(json.dumps(err,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        raise
    finally:
        if clone_running:
            run(["docker.exe","rm","-f",clone_name],timeout=45,check=False)
        isolated_dir=dest / "isolated_restore_validation"
        if isolated_dir.is_dir():
            shutil.rmtree(isolated_dir)
        if dest_created and summary is None and dest.is_dir():
            shutil.rmtree(dest)
            print("INCOMPLETE_PROTECTED_SNAPSHOT_DISCARDED=PASS",flush=True)
        if summary is not None:
            print("PROTECTED_BACKUP_LOCAL_RETAINED=PASS",flush=True)
        check_production()


if __name__ == "__main__":
    run_backup()
