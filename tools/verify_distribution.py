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
RELEASE=REPO/"release"/"P4A_RC1_NATIVE_PROJECT_FILES_SOURCE_CANDIDATE_R002.json"

def check(value, reason):
    if not value:
        raise SystemExit("BLOCK_P4A_PRODUCT_SOURCE: "+reason)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    record=json.loads(RELEASE.read_text(encoding="utf8"))
    check(record["status"]=="NONSHIPPING_DO_NOT_RELEASE", "unverified status")
    check(record["GitHub_release_published"] is False, "fabricated release")
    rows=MANIFEST.read_text(encoding="utf8").splitlines()
    check(len(rows)==495,"expected 495 SHA records")
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
    check(record["payload_file_count"]==496 and record["payload_manifest_rows"]==495,"cardinality drift")
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
          "pinned LibreChat upstream MIT attribution changed")
    check("v0.8.9-rc1" in notice and "8d3da9bbb220a0a96be9330a2e1cbd385fb786d5" in notice and
          "Public" not in notice.split("## Candidate branch distribution boundary")[-1][:20],
          "third party redistribution NOTICE does not match branch")
    # R241 remains historical: never mutate its approved private Draft metadata
    # to pretend this isolated P4A source is a released or signed executable.
    check((REPO/"release/R241_DRAFT_RELEASE_ASSET_POLICY.json").is_file(),
          "R241 historical release evidence missing")
    check(record.get("build_pending") is True and
          record.get("exe_sha256") is None and record.get("exe_bytes") is None and
          record.get("GitHub_release_published") is False and
          record.get("installed_product_pass") is False and
          record.get("program_pass") is False,
          "P4A source falsely promoted to executable or Product PASS")
    check(record.get("exe_name") == "InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.exe",
          "P4A executable identity not frozen")
    entry=PAYLOAD/"product"/"windows"/"InquiryDesk.ps1"
    check(entry.is_file() and not (PAYLOAD/"product/windows/InquiryDesk_R227.ps1").exists(),"wrong entry path")
    content=entry.read_text(encoding="utf-8-sig")
    for token in ("OPENAI_API_KEY=user_provided","ANTHROPIC_API_KEY=user_provided","GOOGLE_KEY=user_provided"):
        check(content.count(token)==1,"API key user-provided mode missing")
    for token in ("UNIVERSAL_RUNTIME_ARTIFACT_ROOT","C5_BACKUP_PROJECT_ROUTE_SHA256","ComposeArgv","NativeArgv"):
        check(token in content,"Runtime/C5 user-owned identity missing")
    # Point-of-use R002 regression: installed Windows launcher must reject,
    # never require, the retired v0.8.8 precompiled API. Keep accepted Project
    # identity and exact R195/rc1 owner/memory/file consumers unchanged.
    owner_body=content.split("function Assert-CodeOnlyManifest {",1)[1].split("function Assert-Windows {",1)[0]
    required_part=owner_body.split("foreach($relative in @(",1)[1].split(")) {",1)[0]
    check("api.index.cjs" not in required_part and
          "LEGACY_COMPILED_API_MUST_NOT_SHADOW_RC1_NATIVE_PROJECT_FILES" in owner_body and
          "product\\overlay\\librechat\\server.index.js" in required_part and
          "product\\overlay\\librechat\\projects.js" in required_part and
          "product\\overlay\\librechat\\frontend-dist\\index.html" in required_part and
          "product\\overlay\\librechat\\C5WholeProjectDeleteOwners.js" in required_part,
          "old v0.8.8 compiled API required by Windows check or rc1 consumers missing")
    check(record.get("R002_launcher_legacy_compiled_api")=="EXPLICIT_FORBIDDEN_NOT_REQUIRED" and
          record.get("R002_changed_payload_files")==[
             "docs/FIRST_RUN.zh-Hans.md","product/windows/InquiryDesk.ps1"] and
          record.get("R002_inherited_unchanged_payload_shas")==493,
          "R002 bounded native entry repair provenance missing")
    pins=json.loads((PAYLOAD/"manifest/upstream-pinned-sources.NONSHIPPING.json").read_text(encoding="utf8"))
    check(len(pins.get("upstream_images",[]))==5 and
          {i["role"] for i in pins["upstream_images"]}==
          {"librechat","mongodb","node-adapter-runtime","pgvector","rag-api"},
          "exact pinned native Project service roles changed")
    for image in pins["upstream_images"]:
        check(re.fullmatch("sha256:[a-f0-9]{64}",image["digest"]),"digest not pinned")
    nsi=(INSTALLER/"InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.nsi").read_text(encoding="utf-8-sig")
    check('"DisplayName" "Inquiry Desk v0.8.9-rc1 (NONSHIPPING)"' in nsi,
          "new user-facing rc1 installer still identifies obsolete v0.8.8 shell")
    callbacks=[s for s in nsi.splitlines() if s.strip().startswith(("CreateShortCut ","Exec ","ExecWait ")) and "product\\windows\\" in s]
    check(len(callbacks)==5 and all("product\\windows\\InquiryDesk.ps1" in line for line in callbacks),"missing real entrypoints including file-search settings")
    check("!if /FileExists" in nsi,"compile-time file guard missing")
    receipt = (PAYLOAD/"product/runtime/src/universal_runtime/c5_runtime_operation_receipt.py").read_text(encoding="utf8")
    for token in (
        "C5_COMPLETE_OWNED_CHAT_CASCADE_INCOMPLETE",
        "C5_COMPLETE_EXCLUSIVE_OR_SHARED_FILE_SCOPE_MISMATCH",
        "C5_COMPLETE_RUNTIME_SOURCE_PAYLOADS_NOT_RETIRED",
        "C5_COMPLETE_RETIRED_SOURCE_PAYLOAD_STILL_PRESENT",
        "PERMANENT_CONTENT_ERASURE_COMPLETE_R001.json",
        "_assert_complete_runtime_source_content_current(",
    ):
        check(token in receipt, "C5 whole Project delete truth guard absent: "+token)
    check("    Assert-CodeOnlyManifest\n    if(!(Test-Path -LiteralPath $OwnerFile" in content,
          "daily user owner did not verify actual product file SHA")
    check("function Shutdown-Core {\n    # Exact code integrity is mandatory" in content,
          "uninstaller failed to verify exact product source")
    check('IfFileExists "$INSTDIR\\manifest\\SHA256SUMS" 0 +3' in nsi,
          "untrusted silent in-place overwrite is not prevented")
    check(record.get("proof_ceiling",{}).get("gate2") ==
          "OFFICIAL_RC1_NATIVE_FILES_UI_4_API_SOURCE_COMPILED_EXE_NOT_YET_REAL_E2E",
          "native file search falsely claimed beyond actual product proof")
    compose=(PAYLOAD/"product/compose/docker-compose.online-nonshipping.yaml").read_text(encoding="utf8")
    check(all(t in compose for t in (
        "  vectordb:", "  rag_api:", 'RAG_API_URL: "http://rag_api:8000"',
        "pgvector-data:/var/lib/postgresql/data")),
        "official native RAG/pgvector missing from real product Compose")
    check(all(t in content for t in ("AIDES_RAG_ENV_FILE","AIDES_PGVECTOR_ENV_FILE",
          "function Configure-FileSearch", "RAG_OPENAI_API_KEY=", "EMBEDDINGS_PROVIDER=openai",
          "Configure-FileSearch -DuringSetup", "[IO.File]::Replace")) and
          not re.search(r"RAG_OPENAI_API_KEY=sk-[A-Za-z0-9_-]{20,}",content),
          "RAG user consent and private key setup not installed or credential bundled")
    manual=(PAYLOAD/"docs/FIRST_RUN.zh-Hans.md").read_text(encoding="utf-8")
    guide=(PAYLOAD/"docs/DATA_AND_UNINSTALL.zh-Hans.md").read_text(encoding="utf-8")
    check(all(t in manual for t in ("v0.8.9-rc1","Project","File Search","Embeddings",
          "永久彻底删除","配置 Project 文件检索")) and
          all(t in guide for t in ("P4A rc1","pgvector","永久","卸载")) and
          "配置 Project 文件检索.lnk" in nsi and
          nsi.count("配置 Project 文件检索.lnk")==2,
          "complete embedded user manual and settings shortcut not packaged")
    # RC1: reuse the entire mature upstream native Project Files UI/API,
    # never reintroduce v0.8.8 compiled API or a new file store.
    c5root=PAYLOAD/"product/overlay/librechat"
    route=(c5root/"projects.js").read_text(encoding="utf8")
    index=(c5root/"server.index.js").read_text(encoding="utf8")
    context=(c5root/"ProjectAssistantProfile.js").read_text(encoding="utf8")
    owner=(c5root/"C5WholeProjectDeleteOwners.js").read_text(encoding="utf8")
    fence=(c5root/"C5WriteFence.js").read_text(encoding="utf8")
    check('source: "'+'$'+'{AIDES_PAYLOAD_ROOT}/librechat/ProjectAssistantProfile.js"' in compose and
          "function fetchProjectRuntimeContext" in context and
          "function searchProjectSources" in context and
          "projectRuntimeContextBindingEquals" in context,
          "Project Memory or Source owner missing from actual UI")
    required_native_file_handlers=("listProjectFiles","listAvailableProjectFiles",
                                  "addProjectFile","removeProjectFile")
    check(all("handlers."+x in route for x in required_native_file_handlers) and
          all("db."+x in route for x in ("getProjectFiles","getAvailableProjectFiles",
                                      "addChatProjectFile","removeChatProjectFile")),
          "four native upstream Project reference-file CRUDs not installed")
    check("createC5NativeWholeProjectProductRoute" in route and
          "createC5WholeProjectDeleteOwners" in route and
          "handlers.deleteProject" not in route and
          "C5WholeProjectDeleteOwners" in route,
          "R195 whole Project permanent deletion not installed safely")
    check(index.count("app.locals.aidesC5WriteFence = createC5WriteFence();")==1 and
          index.count("app.use(app.locals.aidesC5WriteFence.middleware());")==1 and
          "FORWARD_ONLY_DURABLE_RECEIPT_R001" in owner and
          "result.protectedBackupReady === false" in owner and
          "function createC5WriteFence(" in fence and
          "C5_PROJECT_DELETE_WRITE_FENCE_ACTIVE" in fence,
          "native R195 global Writer/forward-only recovery contract not applied")
    required_mounts=(
      "/app/api/server/index.js",
      "/app/api/server/routes/projects.js",
      "/app/api/server/routes/runtimeProjects.js",
      "/app/api/server/routes/c5",
      "/app/api/server/services/C5WholeProjectDeleteOwners.js",
      "/app/api/server/services/C5WriteFence.js",
      "/app/api/server/services/Files/crossStorePermanentDelete.js",
      "/app/api/server/services/Endpoints/agents/projectChatToolsBridge.js",
      "/app/api/server/middleware/projectRuntimeMemoryContext.js",
      "/app/client/dist",
    )
    check(all(compose.count("target: "+x)==1 for x in required_mounts) and
          "/app/packages/api/dist/index.cjs" not in compose and
          not (c5root/"api.index.cjs").exists(),
          "upstream rc1 native model API accidentally shadowed by old compiled overlay")
    profile=json.loads((REPO/"r242_isolated/R195_NATIVE_C5_SOURCE_PROVENANCE_GATE23.json").read_text(encoding="utf8"))
    reuse=profile.get("expected_sha256_by_target_relative",{})
    check(len(reuse)==18 and all(digest((c5root/rel).read_bytes())==sha for rel,sha in reuse.items()),
          "previously accepted mature R195 owner sources changed")
    staged=json.loads((REPO/"r242_isolated/RC1_NATIVE_FILES_R195_SINGLE_SHELL_STAGED_PATCH_R001/STAGING_EXACT_RC1_OWNER_SHA_R001.json").read_text(encoding="utf8"))
    expected_owners=staged.get("R195_exact_source_preimage_by_target",{})
    check(len(expected_owners)==6 and all(
          digest((c5root/name).read_bytes())==
          (staged["server_index_after_bounded_fence_sha256"] if name=="server.index.js" else sha)
          for name,sha in expected_owners.items()),
          "RC1 vendor R195 owner or global Writer middleware code changed")
    check(record.get("R241_source_physical_erasure_truth_inherited_unmodified") is True and
          "PERMANENT_CONTENT_ERASURE_COMPLETE_R001.json" in receipt,
          "R241 stricter original and derivative content erasure truth not carried")
    check(record.get("proof_ceiling",{}).get("gate3") ==
          "R195_NATIVE_C5_FRONTBACK_R241_TRUTH_IN_SOURCE_NO_REAL_COMPLETE",
          "C5 real deletion completion overstated")
    check(record.get("real_Project_C5_full_delete_physical_afterstate_E2E") is False and
          record.get("real_Project_RAG_memory_crosschat_file_GUI_E2E") is False and
          record.get("supported_Windows11_live_install") is False,
          "source-only progress misreported as complete Product")
    check(record.get("legacy_v088_compiled_api_overlay_in_new_payload") is False,
          "second stale compiled API owner smuggled into current candidate")
    official=next((x for x in pins["upstream_images"] if x["role"]=="librechat"),None)
    check(official is not None and
          official["version"]=="v0.8.9-rc1" and
          official["digest"]=="sha256:4a540a793a573b0e0f674b7831dc9c71d64e544215469b3f69caebb622e4972d",
          "RC1 official linux/amd64 digest not pinned")
    yaml=(c5root/"librechat.yaml").read_text(encoding="utf8")
    check("version: 1.3.18" in yaml and "retainedFileCleanup: false" in yaml,
          "official rc1 config version or user file retention changed")
    dist=c5root/"frontend-dist"
    fp=REPO/"r242_isolated/OFFICIAL_RC1_PROJECT_FILES_R195_C5_BUILT_FRONTEND_TO_SINGLE_SHELL_R001.json"
    frontend=json.loads(fp.read_text(encoding="utf8"))
    assets=frontend["sha256_files"]
    check(frontend["official_rc1_lock_sha256"]==
          "2fa0ea3ce9a09037d0255d8161d684928ee9bfb6d1f4ee860f73487e69ab1dcc" and
          record["official_rc1_full_build_lock_sha256"]==frontend["official_rc1_lock_sha256"] and
          record["official_rc1_frontend_asset_count"]==393 and len(assets)==393 and
          record["official_rc1_frontend_index_sha256"]==assets.get("index.html"),
          "exact official rc1 frontend graph, file count or SHA not proven")
    check(all((dist/name).is_file() and digest((dist/name).read_bytes())==sha
              for name,sha in assets.items()) and
          set("product/overlay/librechat/frontend-dist/"+name for name in assets).issubset(actual),
          "native rc1 Project Files frontend asset omitted or byte modified")
    check(any(b"COMPLETE_VERIFIED_PROJECT_DELETE" in x.read_bytes()
                  and b"C5_WHOLE_PROJECT_DELETE_READY" in x.read_bytes()
                  and b"/files/available" in x.read_bytes()
                  for x in dist.rglob("*.js")),
          "official compiled Project Files plus C5 UI not present in the same shell")
    check(record.get("proof_ceiling",{}).get("gate2")==
          "OFFICIAL_RC1_NATIVE_FILES_UI_4_API_SOURCE_COMPILED_EXE_NOT_YET_REAL_E2E",
          "Project reference files GUI and real RAG E2E conflated")
    check("P4A_RC1_NATIVE_PROJECT_FILES_EXACT_UNINSTALL_ALLOWLIST.nsh" in nsi and
          "P4A_R195_UI_EXACT_UNINSTALL_ALLOWLIST.nsh" not in nsi,
          "non-current uninstall allowlist left in rc1 candidate")
    check("RMDir /r" not in nsi and "down -v" not in content and "docker prune" not in content,"unsafe deletion")
    inc=(INSTALLER/"P4A_RC1_NATIVE_PROJECT_FILES_EXACT_UNINSTALL_ALLOWLIST.nsh").read_text(encoding="utf-8-sig")
    deleted=[x.replace("\\","/") for x in re.findall(r'(?m)^\s*Delete "\$INSTDIR\\([^"]+)"$',inc)]
    check(len(deleted)==496 and set(deleted)==actual,"uninstall source allowlist diverged")
    print(json.dumps({"status":"PASS_P4A_RC1_UPSTREAM_NATIVE_PROJECT_FILES_R195_C5_SOURCE_ONLY_NOT_PRODUCT","manifest_files":len(actual),"recorded_sha":len(rows),"setup_shortcut_uninstall_sources":len(callbacks),"uninstall_allowlist_count":len(deleted),"GitHub_release_and_Product_PASS":False}))

if __name__=="__main__":
    main()
