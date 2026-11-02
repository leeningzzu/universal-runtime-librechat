#!/usr/bin/env python3
"""Verify retained P4A historical local artifacts after GitHub-only recovery.
Non-authority evidence; no real user data, no product or release PASS.
"""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"archive/non_authority_p4a_pre_rc1_r002"
MANIFEST=BASE/"ARCHIVE_SHA256_MANIFEST_R001.json"
EXPECTED_SHA="8249a69e6f464ae70835dc69a1200d2ab26102c34ec635759c43dece149084e8"

def fail(message):
    raise SystemExit("BLOCK_NONAUTHORITY_ARCHIVE_INTEGRITY: "+message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    if not MANIFEST.is_file() or sha(MANIFEST.read_bytes())!=EXPECTED_SHA:
        fail("archive SHA record missing or modified")
    data=json.loads(MANIFEST.read_text(encoding="utf8"))
    if data.get("source_untracked_candidate_file_count")!=56:
        fail("historical source file count drift")
    if data.get("source_total_bytes")!=1436999:
        fail("historical source byte total drift")
    if data.get("fact_class")!="RETENTION_ARCHIVE_NON_AUTHORITY" or data.get("promotion_or_product_pass") is not False:
        fail("archived source claimed current product authority")
    entries=data.get("sha_manifest_of_original_untracked_file_paths",{})
    if len(entries)!=56:
        fail("metadata file count does not match actual archives")
    files=set()
    total=0
    for name,entry in entries.items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            fail("invalid archived path "+name)
        if not name.startswith(("r242_isolated/","release/","windows/inquiry_desk/installer/")):
            fail("non-historical source entered the archive "+name)
        copied=BASE/relative
        if not copied.is_file() or copied.is_symlink():
            fail("archive source no longer a normal file "+name)
        if copied.stat().st_size != entry["bytes"] or sha(copied.read_bytes())!=entry["sha256"]:
            fail("historical source SHA differs from retained source "+name)
        if entry.get("current_active_product") is not False:
            fail("historical artifact incorrectly designated current "+name)
        total+=entry["bytes"]
        files.add(name)
    existing={file.relative_to(BASE).as_posix() for file in BASE.rglob("*") if file.is_file() and file.name not in ("ARCHIVE_SHA256_MANIFEST_R001.json","README.md")}
    if existing!=files or total!=data["source_total_bytes"]:
        fail("unlisted archive file or incomplete retained collection")
    print(json.dumps({"status":"PASS_HISTORICAL_56_SHA_NONAUTHORITY_NOT_PRODUCT",
       "file_count":56,"retained_source_bytes":total,
       "only_archive_role":True,"Product_PASS":False,
       "Program_PASS":False},sort_keys=True))

if __name__=="__main__":main()
