#!/usr/bin/env python3
"""GitHub-only portable development continuity verification, not Product PASS."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
AUTHORITIES={
    "PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_7_CANDIDATE_R002.md":
        "5b8f0a815a607f8bee724c471e9e1acfe715b8e6bfc35a5ba674726880ec7dac",
    "PROJECT_SOURCE_NEW_CHAT_HANDOFF_PROTOCOL_v0_7.md":
        "6fb2b4a724d0bd2474ea80d24e9d6b09b714c685e19ec7f5545f18ce68c75b8d",
    "PROJECT_SOURCE_PACK_CREATION_PROTOCOL_v0_5.md":
        "49cfc192c762df002309c37238d8fe5c071ebb7b2ae3a051539cbc9b7eb24468",
    "PROJECT_SOURCE_PACK_INTAKE_AND_PROCESS_IMPROVEMENT_v0_25.md":
        "b8442041050df8aa35af3bc6cd7c37090e39174fbf66a9e331177a7f34e96204",
    "PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE_v0_3.md":
        "ed73248ac64faaaedd8818728d379766a2a43f1bbe34ce19a31aa9478d0e508b",
    "PROJECT_SOURCE_RUNTIME_ARCHITECTURE_v0_9.md":
        "5628416ee59d44deef765c41474b3427f98148eddf2d7debefd298c7ed08a6eb",
    "PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_8.md":
        "e50094bbaa1e5cb4302520212491b3a2f16463d4788a3b6333c15df79f74ad85",
    "PROJECT_SOURCE_RUNTIME_HARD_INVARIANTS_v0_2_CANDIDATE_R002.md":
        "c5cc59939334c3eafb812ff7cda6b5b29e35ac4f2f70ff7bcce36c4a014b3a55",
    "WINDOWS_PRODUCT_SHELL_USER_JOURNEY_CONTRACT_R001.md":
        "f41d5180d1c3bcbc52981debd630aa35b9125dd8c6af24afd371f506ea6ebec5",
}
BIN_NAME="InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.exe"
BIN_SHA="81420f4aacc56100d0027f335e8eaa460d4c9322f79afe7362c7ac86d0822c18"
BIN_SIZE=19341420
PATCH_ROOT=ROOT/"patches/librechat/v0.8.9-rc1"
SOURCE_ROOT=ROOT/"docs/project_sources"
RECOVERED_NAME="PROJECT_SOURCE_RUNTIME_HARD_INVARIANTS_v0_1.md"
RECOVERED_SHA="59c40f56e00a1089bf84efe3a9e8fccd200c26228f1fa9c1143355c241bbfcea"
RECOVERED_METADATA="docs/project_sources/RECOVERED_HARD_INVARIANTS_V01_TEXT_PROVENANCE_R001.json"


def verify(condition, reason):
    if not condition:
        raise SystemExit("BLOCK_GITHUB_CONTINUITY: "+reason)

def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--exe",type=Path,help="optional, owner-downloaded exact GitHub DRAFT EXE")
    args=parser.parse_args()
    expected_docs=[
        "AGENTS.md",
        "docs/PROGRAM_PURPOSE_R001.md",
        "docs/CURRENT_DELIVERY_STATE_R001.md",
        "docs/CURRENT_DELIVERY_STATE_R002.md",
        "docs/CURRENT_DELIVERY_STATE_R003.md",
        "release/P4A_RC1_R002_GITHUB_DRAFT_REMOTE_PASS_R001.json",
        "docs/GITHUB_ONLY_REENTRY_R001.md",
        "docs/BUILD_REPRODUCTION_R001.md",
        "docs/PORTABILITY_AND_LOCAL_RETIREMENT_R001.md",
        "release/P4A_RC1_R002_NONSHIPPING_RELEASE_NOTES.md",
        "release/P4A_RC1_R002_NONSHIPPING_EXE_SHA256SUMS.txt",
    ]
    for name in expected_docs:
        verify((ROOT/name).is_file(),"missing source handoff "+name)
    names={f.name for f in SOURCE_ROOT.glob("*.md")
           if f.name not in ("README.md",RECOVERED_NAME)}
    verify(names==set(AUTHORITIES),"Project Source original set mismatch")
    s=json.loads((SOURCE_ROOT/"SOURCE_FILES_SHA256_R001.json").read_text(encoding="utf8"))
    verify(len(s.get("files",{}))==9 and
           s.get("active_stable_hard_invariants_v0_1_original_missing") is True,
           "research Source authority and missing predecessor misreported")
    for name,expected in AUTHORITIES.items():
        path=SOURCE_ROOT/name
        actual=sha(path.read_bytes())
        verify(actual==expected, "original Project Source byte drift "+name)
        verify(s["files"][name]["sha256"]==expected,
               "Project Source hash index drift "+name)
    for name in ["PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_7_CANDIDATE_R002.md",
                 "PROJECT_SOURCE_RUNTIME_HARD_INVARIANTS_v0_2_CANDIDATE_R002.md"]:
        verify(s["files"][name]["authority_class"]=="UNPROMOTED_CANDIDATE",
               "silently promoted Source revision Candidate "+name)
    recovered=SOURCE_ROOT/RECOVERED_NAME
    verify(recovered.is_file() and sha(recovered.read_bytes())==RECOVERED_SHA,
           "indexed Stable v0.1 text recovery drift")
    text=recovered.read_text(encoding="utf8")
    verify(text.startswith("# Universal Runtime｜Project Source｜Hard Invariants v0.1") and
           "RUNTIME_IS_ONLY_COMMIT_OWNER = YES" in text and
           len(text.splitlines())==78,
           "recovered v0.1 Stable text content not grounded")
    recovered_prov=json.loads((ROOT/RECOVERED_METADATA).read_text(encoding="utf8"))
    verify(recovered_prov.get("indexed_instances_count")==5 and
           recovered_prov.get("all_indexed_instance_contents_text_equal") is True and
           recovered_prov.get("original_raw_file_sha256")=="UNAVAILABLE" and
           recovered_prov.get("recovered_utf8_canonical_content_sha256")==RECOVERED_SHA and
           recovered_prov.get("recovery_does_not_promote_v02_candidate") is True,
           "v0.1 normalized-text source recovery overclaims original raw evidence")
    patches=json.loads((PATCH_ROOT/"SOURCE_PROVENANCE_R001.json").read_text(encoding="utf8"))
    verify(patches["upstream_exact_commit"]==
           "8d3da9bbb220a0a96be9330a2e1cbd385fb786d5",
           "upstream rc1 exact source owner changed")
    verify(patches["upstream_exact_lock_sha256"]==
           "2fa0ea3ce9a09037d0255d8161d684928ee9bfb6d1f4ee860f73487e69ab1dcc",
           "official dependency lock SHA changed")
    repl=patches.get("patch_source_files",{})
    verify(len(repl)==5 and len(patches.get("original_upstream_files_sha256",{}))==5,
           "full R195 client patch provenance missing")
    for name,digest in repl.items():
        file=PATCH_ROOT/name
        verify(file.is_file() and sha(file.read_bytes())==digest,
               "exact native Project C5 frontend source missing/changed "+name)
    record=json.loads((ROOT/"release/P4A_RC1_NATIVE_PROJECT_FILES_SOURCE_CANDIDATE_R002.json").read_text(encoding="utf8"))
    verify(record.get("status")=="NONSHIPPING_DO_NOT_RELEASE" and
           record.get("installed_product_pass") is False and
           record.get("program_pass") is False,
           "candidate SOURCE incorrectly elevated to Product PASS")
    verify(record.get("exe_name")==BIN_NAME and
           record.get("payload_file_count")==496 and
           record.get("payload_manifest_rows")==495,
           "current complete Project product identity changed")
    checksum=(ROOT/"release/P4A_RC1_R002_NONSHIPPING_EXE_SHA256SUMS.txt").read_text(encoding="utf8").strip()
    verify(checksum==BIN_SHA+"  "+BIN_NAME,"download checksum sidecar changed")
    expected_manifest=record["payload_SHA256SUMS_sha256"]
    manifest=ROOT/"windows/inquiry_desk/payload/manifest/SHA256SUMS"
    verify(sha(manifest.read_bytes())==expected_manifest,
           "current product source/manifest changed")
    if args.exe:
        actual=args.exe
        verify(actual.is_file() and actual.name==BIN_NAME,
               "owner-downloaded GitHub DRAFT asset name missing/changed")
        verify(actual.stat().st_size==BIN_SIZE and sha(actual.read_bytes())==BIN_SHA,
               "owner-downloaded DRAFT EXE bytes not identical")
    paths=list(ROOT.rglob("*.env"))
    verify(not any(f.is_file() for f in paths if ".git" not in f.parts),
           "private .env unexpectedly placed in public source clone")
    print(json.dumps({
        "status":"PASS_GITHUB_CONTINUITY_SOURCE_ONLY_NOT_PRODUCT_PASS",
        "Project_Source_original_sha_pass":9,
        "promoted_stable_authority":6,
        "unpromoted_candidates":2,
        "supporting_contract":1,
        "hard_invariants_v01_indexed_text_recovered":True,
        "hard_invariants_v01_recovered_utf8_sha256":RECOVERED_SHA,
        "hard_invariants_v01_original_raw_sha_unavailable":True,
        "native_R195_client_patch_sources_sha_pass":len(repl),
        "current_product_source_manifest_sha":expected_manifest,
        "DRAFT_EXE_download_verified":bool(args.exe),
        "Product_PASS":False,"Program_PASS":False
    },sort_keys=True))
if __name__=="__main__":
    main()
