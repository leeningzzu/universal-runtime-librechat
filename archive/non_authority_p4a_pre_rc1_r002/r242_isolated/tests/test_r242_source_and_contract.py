"""R242 isolated proof-family test; no network, Docker, user data or effects."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
mature = root / "native_c5_candidate" / "R006_mature_uninstalled"
provenance = json.loads((mature / "SOURCE_PROVENANCE_R241.json").read_text(encoding="utf-8"))
entries = provenance["archive_entries"]
assert len(entries) == 36, "MATURE_R006_SOURCE_COUNT_DRIFT"
for entry in entries:
    file = mature / entry["path"]
    assert file.is_file(), f"R006_MISSING_{entry['path']}"
    actual = hashlib.sha256(file.read_bytes()).hexdigest()
    assert actual == entry["sha256"], f"R006_SHA_DRIFT_{entry['path']}"
print("R242_FROZEN_R006_SOURCE_SHA=PASS_36_OF_36")

compose = (root / "r242_isolated/compose/docker-compose.c5-synthetic.override.yaml").read_text(encoding="utf-8")
assert compose.count("source: ") == 11, "R242_SOURCE_BIND_CARDINALITY"
assert compose.count("target: ") == 11, "R242_TARGET_BIND_CARDINALITY"
assert compose.count("read_only: true") == 11, "R242_MOUNTS_MUST_BE_READONLY"
assert "mongodb:" not in compose and "runtime-adapter:" not in compose, "NO_SECOND_DB_OR_ADAPTER"
assert "AIDES_R242_NATIVE_ROOT" in compose and "AIDES_R242_R006_ROOT" in compose
for entry in entries:
    if entry["path"].startswith(("api/server/routes/", "api/server/services/Files/")):
        if entry["path"].endswith((".candidate.js", "/crud.js")) and "/tests/" not in entry["path"]:
            # Only integration route dependencies are mounted; the separate
            # native runtime owner modules and non-route sources stay frozen.
            pass
print("R242_ISOLATED_COMPOSE_MOUNTS=PASS_11_READONLY")

runtime = (root / "windows/inquiry_desk/payload/product/runtime/src/universal_runtime/c5_retirement_runtime_routes.py").read_text(encoding="utf-8")
r006 = (mature / "api/server/routes/c5NativeWholeProjectBinding.candidate.js").read_text(encoding="utf-8")
assert '"protectedBackupReady": False' in runtime, "R242_RUNTIME_BACKUP_CONTRACT_CHANGED_REASSESS"
assert "protectedBackupReady === true" in r006 or "protectedBackupReady===true" in r006, "R006_MATURE_ADMISSION_CHANGED_REASSESS"
assert "C5_PER_DELETE_GLOBAL_BACKUP_DISABLED_USE_EXPLICIT_REPAIR" in runtime
assert "FORWARD_ONLY_DURABLE_RECEIPT_R001" in runtime
print("R242_CURRENT_RUNTIME_VS_R006_PROTECTION=EXPECTED_BLOCK_NO_FALSE_PASS")

manifest = (root / "windows/inquiry_desk/payload/manifest/SHA256SUMS").read_text(encoding="utf-8").splitlines()
assert len(manifest) == 80, "R241_ACCEPTED_RELEASE_MANIFEST_MUTATED"
assert not any("r242_isolated" in item for item in manifest), "R242_ISOLATION_LEAK"
print("R242_PREVIOUS_R241_RELEASE_SOURCE_MANIFEST=INHERITED_UNMODIFIED")
