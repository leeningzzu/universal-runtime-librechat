# Inquiry Desk — AI agent entrypoint

Read this file first when continuing from GitHub with a different AI model or Windows PC. This repository is the source of the CURRENT candidate, not proof that the installed product works.

## Read order
1. docs/PROGRAM_PURPOSE_R001.md (North Star, architecture and user workflow).
2. docs/project_sources/README.md and SOURCE_FILES_SHA256_R001.json (six active Stable Sources, two unpromoted Candidates, one supporting contract).
3. docs/CURRENT_DELIVERY_STATE_R002.md (latest exact GitHub migration and product proof ceilings; R001 remains predecessor).
4. docs/GITHUB_ONLY_REENTRY_R001.md and docs/BUILD_REPRODUCTION_R001.md (recovery without local histories).
5. release/P4A_RC1_R002_NONSHIPPING_RELEASE_NOTES.md, tools/verify_distribution.py, tools/verify_github_continuity.py, tests.
6. Actual product source: windows/inquiry_desk/payload/product and SHA inventory: windows/inquiry_desk/payload/manifest/SHA256SUMS.

## Mission
Any supported Windows PC -> one LibreChat Project-first Web/Desktop shell -> Runtime Authority -> optional governed Domain/Universal Packs / AI Workbench. Core must work with ZERO user-installed Packs. Project identity != Pack/Agent/Provider/Shell/MCP/raw executor/drive/path. Model Provider offers access only; Runtime governs permissions/revision/persistence/Promotion/audit, never a second UI. MCP is optional transport; replaceable Local Action Host is optional machine capability.

Normal user flow: New Project -> purpose once if needed -> New Chat -> direct request. Instructions, same-Project history recall, Project-scoped Memory, user-global Memory, Project Files/Sources, model File Search and durable Artifacts are distinct. Storage != retrieval != injection != exact recovery. No blanket history injection.

Prefer current LibreChat native upstream -> mature Runtime/Pack reuse -> thin adapter; NO second shell, chat DB, vector DB, generic Agent/Skill engine, generic memory/router, custom installer/update engine, mandatory internal proxy/tunnel or whole-drive Docker bind. Preserve accepted P1/P2 baselines; a bounded delta only revalidates directly affected consumers.

## Current product proof ceiling
The exact current NONSHIPPING R002 EXE is named InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.exe.
Expected bytes: 19,341,420; SHA256: 81420f4aacc56100d0027f335e8eaa460d4c9322f79afe7362c7ac86d0822c18.
The v0.8.9-rc1 upstream Project Files UI and native file routes, R195 native Project C5 delete front/back, Runtime memory/source bridge, R241 strict physical erasure source truth and RAG/pgvector are compiled into one shell. NSIS source-to-EXE 495/495 SHA, Windows PowerShell 5.1 Mode Check exit 0, and static five-service Compose config PASS. These are CODE/BUILD PASS ONLY.
REAL Gate2 Project/FileSearch/Memory/cross-Chat and REAL Gate3 physical irreversible delete/shared-survival E2E are NOT PROVEN. P4B data-safe update/repair/uninstall and G3 signed production Release NOT PROVEN. PRODUCT_PASS=NO; PROGRAM_PASS=NO. NEVER fake success from a syntactic test or deleted UI row.

## Authority and effect boundaries
Promoted Stable Sources own durable facts; current material route comes from latest accepted Handoff/Build Status and later machine evidence. Candidates do not auto-Promote. Runtime is the only effect/approval owner; Git commits cannot Promote source, release product or erase real data. Do not read or export model/account secrets, Mongo data, uploaded File/Source, private Chat, user Memory, protected backups, rollback materials. The public GitHub candidate branch is code only.
Do not push main, --all, --mirror or force. Do not promote this unsigned NONSHIPPING EXE to a public latest Release: owner-only DRAFT asset is the authorized transfer staging until full Product/G3 proof.
Do not auto-retry a partially executed or UNKNOWN C5 operation. Owner, Writer, lease, Source/File/Blob/Vector afterstate, shared neighbors and restart recovery require independent proof.

## Single current action
UNIQUE_NEXT_ACTION = GITHUB_CI_SOURCE_REENTRY_PASS_THEN_ACTIONS_BUILD_EXACT_R002_EXE_AND_CREATE_OWNER_ONLY_DRAFT_WITH_REMOTE_SHA_READBACK_R002
The screened source was pushed to the candidate branch at predecessor SHA 51de4a84fa764a8bbd403947f1affb8ffe754d23; its CI failed because the new continuity checker was accidentally omitted from the commit, not because the 496-file product failed its source SHA. A separate fresh GitHub clone rebuilt the exact 19,341,420-byte R002 EXE with the SAME SHA256. The new candidate revision adds the missing continuity checker and an official source-integrity-dependent GitHub Actions job which is allowed to publish ONLY an owner-visible NONSHIPPING Draft after exact source-to-binary SHA parity. Check the NEW remote commit/CI and Draft download SHA, not old status text, before considering any local staging retirement. After remote parity, resume supported isolated Windows11 synthetic Project Gate2/Gate3 real E2E. Do not change Production/Daily, real user data or public latest release.
