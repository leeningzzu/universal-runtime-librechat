#!/usr/bin/env python3
"""Verify the exact NONSHIPPING Inquiry Desk product-source release.
Read-only source/manifest/license/privacy assertions, NOT Product or Program PASS.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

REPO=Path(__file__).resolve().parents[1]
BUNDLE=REPO/"windows"/"inquiry_desk"
PAYLOAD=BUNDLE/"payload"
INSTALLER=BUNDLE/"installer"
MANIFEST=PAYLOAD/"manifest"/"SHA256SUMS"
RELEASE=REPO/"release"/"RELEASE_CANDIDATE.json"

def check(value, reason):
    if not value:
        raise SystemExit("BLOCK_R232_SOURCE: "+reason)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    record=json.loads(RELEASE.read_text(encoding="utf8"))
    check(record["status"]=="NONSHIPPING_DO_NOT_RELEASE", "unverified status")
    check(record["GitHub_release_published"] is False, "fabricated release")
    rows=MANIFEST.read_text(encoding="utf8").splitlines()
    check(len(rows)==80,"expected 80 SHA records")
    listed=set()
    for row in rows:
        check(re.fullmatch(r"[a-f0-9]{64}  .+",row), "malformed SHA row")
        expected,name=row.split("  ",1)
        rel=Path(name)
        check(not rel.is_absolute() and ".." not in rel.parts and "\\" not in name, "unportable path")
        check(name not in listed, "duplicate source")
        listed.add(name)
        file=PAYLOAD/rel
        check(file.is_file() and not file.is_symlink(), "missing/redirected source")
        check(digest(file.read_bytes())==expected,"bad source SHA: "+name)
    actual=set()
    excluded=(".pyc",".whl",".tar",".pyd",".exe",".pfx",".p12")
    personal=[
      re.compile(rb"(?i)[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9._-]{2,}"),
      re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
      re.compile(rb"(?:sk-[A-Za-z0-9_-]{32,}|AIza[A-Za-z0-9_-]{24,}|github_pat_[A-Za-z0-9_-]{30,}|ghp_[A-Za-z0-9]{35,})"),
      re.compile(rb"(?i)(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_KEY|GEMINI_API_KEY|DEEPSEEK_API_KEY|JWT_SECRET)\s*[=:]\s*[\"']?[A-Za-z0-9._~+/\-=]{45,}"),
      re.compile(rb"(?i)(?:installed_pack_[a-z_]+\.py|pack_promotion_authority[/\\])"),
    ]
    for file in PAYLOAD.rglob("*"):
        if not file.is_file():continue
        rel=file.relative_to(PAYLOAD).as_posix()
        check(not file.is_symlink() and "__pycache__" not in file.parts,"cache/reparse")
        check(file.suffix.lower() not in excluded,"heavy unwanted package")
        data=file.read_bytes()
        check(not any(x.search(data) for x in personal),"privacy regex match: "+rel)
        actual.add(rel)
    check(actual==listed|{"manifest/SHA256SUMS"},"source inventory drift")
    check(record["payload_file_count"]==81 and record["payload_manifest_rows"]==80,"cardinality drift")
    check(digest(MANIFEST.read_bytes())==record["payload_SHA256SUMS_sha256"],"manifest identity drift")
    # The PUBLIC source-review branch must retain the original project's
    # MIT rights and the exact LibreChat v0.8.8 attribution; compiled overlays
    # must never silently become copyright-free code.
    root_license=(REPO/"LICENSE").read_bytes()
    upstream_license=(REPO/"licenses/LibreChat-v0.8.8-MIT-LICENSE.txt").read_bytes()
    notice=(REPO/"NOTICE").read_text(encoding="utf8")
    check(digest(root_license)=="573a7a3f058cf7b94dfd1c6df413e5aa86b2d4af5865775e80aaf8a78c7282d3",
          "public repository MIT original license not identical")
    check(digest(upstream_license)=="1ce5c9d51e5ab764b44142cd44d1e687f5bfe32f807c7221c14d061007309b97",
          "pinned LibreChat v0.8.8 MIT attribution missing")
    check("modified compiled LibreChat API overlay" in notice and
          "Public" not in notice.split("## Candidate branch distribution boundary")[-1][:20],
          "third party redistribution NOTICE does not match branch")
    # GitHub executable upload is a separate owner-approved, private DRAFT effect.
    # The Git commit stores only its immutable identity and release notes.
    asset_policy=json.loads((REPO/"release/R232_DRAFT_RELEASE_ASSET_POLICY.json").read_text(encoding="utf8"))
    check(asset_policy["status"]=="LOCAL_READY_NOT_UPLOADED","GitHub draft status falsely promoted")
    check(asset_policy["release_channel"]=="EXACT_PUBLIC_GITHUB_REPOSITORY_UNPUBLISHED_DRAFT_ONLY" and asset_policy["target_repository"]=="leeningzzu/universal-runtime-librechat" and asset_policy["target_repository_visibility"]=="PUBLIC","selected GitHub source target not exact")
    check(asset_policy["product_pass"] is False and asset_policy["release_allowed_public"] is False,
          "unsafe public release promotion")
    check(asset_policy["asset_name"]==record["exe_name"],"release EXE name mismatch")
    check(asset_policy["asset_bytes"]==record["exe_bytes"],"release EXE size mismatch")
    check(asset_policy["asset_sha256"]==record["exe_sha256"],"release EXE digest mismatch")
    check(asset_policy["binary_asset_not_git_commit"] is True,"binary must be Release asset only")
    expected_asset_sum=asset_policy["asset_sha256"]+"  "+asset_policy["asset_name"]
    actual_asset_sum=(REPO/"release/R232_NONSHIPPING_EXE_SHA256SUMS.txt").read_text(encoding="utf8").strip()
    check(expected_asset_sum==actual_asset_sum,"Release checksum sidecar differs")
    notes=(REPO/"release/R232_PRIVATE_DRAFT_NOTES.md").read_text(encoding="utf8")
    check("NONSHIPPING" in notes and "PRIVATE DRAFT" in notes,"release notes safety status absent")
    # Real GitHub release SHA verification is performed only after remote upload.
    entry=PAYLOAD/"product"/"windows"/"InquiryDesk.ps1"
    check(entry.is_file() and not (PAYLOAD/"product/windows/InquiryDesk_R227.ps1").exists(),"wrong entry path")
    content=entry.read_text(encoding="utf-8-sig")
    for token in ("OPENAI_API_KEY=user_provided","ANTHROPIC_API_KEY=user_provided","GOOGLE_KEY=user_provided"):
        check(content.count(token)==1,"API key user-provided mode missing")
    for token in ("UNIVERSAL_RUNTIME_ARTIFACT_ROOT","C5_BACKUP_PROJECT_ROUTE_SHA256","ComposeArgv","NativeArgv"):
        check(token in content,"Runtime/C5 user-owned identity missing")
    pins=json.loads((PAYLOAD/"manifest/upstream-pinned-sources.NONSHIPPING.json").read_text(encoding="utf8"))
    check(len(pins.get("upstream_images",[]))==3,"pinned image roles changed")
    for image in pins["upstream_images"]:
        check(re.fullmatch("sha256:[a-f0-9]{64}",image["digest"]),"digest not pinned")
    nsi=(INSTALLER/"InquiryDesk_Setup_R232_NONSHIPPING.nsi").read_text(encoding="utf-8-sig")
    callbacks=[s for s in nsi.splitlines() if s.strip().startswith(("CreateShortCut ","Exec ","ExecWait ")) and "product\\windows\\" in s]
    check(len(callbacks)==4 and all("product\\windows\\InquiryDesk.ps1" in line for line in callbacks),"missing real entrypoints")
    check("!if /FileExists" in nsi,"compile-time file guard missing")
    check("RMDir /r" not in nsi and "down -v" not in content and "docker prune" not in content,"unsafe deletion")
    inc=(INSTALLER/"R232_EXACT_UNINSTALL_ALLOWLIST.nsh").read_text(encoding="utf-8-sig")
    deleted=[x.replace("\\","/") for x in re.findall(r'(?m)^\s*Delete "\$INSTDIR\\([^"]+)"$',inc)]
    check(len(deleted)==81 and set(deleted)==actual,"uninstall source allowlist diverged")
    print(json.dumps({"status":"PASS_R232_NONSHIPPING_SOURCE_INTEGRITY_ONLY","manifest_files":len(actual),"recorded_sha":len(rows),"setup_shortcut_uninstall_sources":len(callbacks),"uninstall_allowlist_count":len(deleted),"GitHub_release_and_Product_PASS":False}))

if __name__=="__main__":
    main()
