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
