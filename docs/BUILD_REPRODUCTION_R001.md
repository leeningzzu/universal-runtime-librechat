# Exact SOURCE and NONSHIPPING EXE reproduction

This describes developer evidence, not normal end-user setup. Every path is relative to the fresh Git clone; do not hardcode a developer drive or username.

## Current exact source
- Product payload: windows/inquiry_desk/payload (495 exact SHA256 listed in manifest/SHA256SUMS; 496 controlled files).
- Windows installer: windows/inquiry_desk/installer/InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.nsi.
- Windows PowerShell 5.1 launcher: windows/inquiry_desk/payload/product/windows/InquiryDesk.ps1. It rejects the retired v0.8.8 compiled API; never restore that file as an active consumer.
- Original Runtime and C5 complete-delete truth: product/runtime/src/universal_runtime/c5_runtime_operation_receipt.py.
- R195 C5 owner/Writer/cross-store deletion and Project-scoped memory/Source context: product/overlay/librechat and product/overlay/adapter.
- Single LibreChat, Mongo, adapter, RAG and pgvector services: product/compose/docker-compose.online-nonshipping.yaml; exact 5 vendor image roles in manifest/upstream-pinned-sources.NONSHIPPING.json.
- User guide embedded under payload/docs. No Docker images, Python wheels, private Project data, local models, or provider keys are bundled inside the EXE.

## Quick source QA
Run from repo root on a supported Windows development environment:
  python tools/verify_distribution.py
  python tools/verify_github_continuity.py
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File tests/test_r241_owner_integrity.ps1
  node tests/test_r239_project_chat_recall_scope.js
  node r242_isolated/tests/test_rc1_native_project_files_r195_owner_router.cjs
For the isolated strict C5 Runtime module tests use the already pinned requirements-runtime-complete-SHA256-R211.txt as CI; do not silently use unrelated interpreter packages or model calls.

## Official frontend reproducibility
- Exact upstream LibreChat git commit: 8d3da9bbb220a0a96be9330a2e1cbd385fb786d5 (official v0.8.9-rc1 pre-release).
- Exact official package-lock sha256: 2fa0ea3ce9a09037d0255d8161d684928ee9bfb6d1f4ee860f73487e69ab1dcc.
- Node 24.22.2 official Windows portable zip pinned SHA256: ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2.
- The five exact mature R195 Project deletion UI files are stored as full source in patches/librechat/v0.8.9-rc1 with ORIGINAL and PATCHED file SHA in SOURCE_PROVENANCE_R001.json. Do not overwrite a different upstream version silently. Official rc1 Project reference-files UI/API and source handlers remain native upstream; no second custom file system.
- On clean upstream rc1 checkout, verify the original five upstream hashes, apply only the five replacement files from this GitHub candidate, run npm ci using the original lock, then npm run frontend. Do not update dependency graph or use stale v0.8.8 precompiled API.
- Already compiled frontend assets are checked into windows/inquiry_desk/payload/product/overlay/librechat/frontend-dist (393 files). Official index sha256 e575d2f0dd92c1c1399ada16b54276653c654eccfff1bfdb4931cdf3210bf031. Every byte is covered by source manifest.
- A locally rebuilt dist with different bytes must become a new reviewed candidate, not falsely adopt the old EXE hash.

## NSIS developer build
Using official verified NSIS 3.13 on Windows PowerShell:
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows_distribution.ps1 -MakensisPath <verified-nsis-makensis-executable>
The build uses a temporary short X: compile alias and then must release it. The alias is NOT a durable Project path or identity and never requires a whole-drive Docker mount. The builder fails if output already exists.
Expected archived R002 compiled EXE sha256: 81420f4aacc56100d0027f335e8eaa460d4c9322f79afe7362c7ac86d0822c18, size 19,341,420 bytes; a different compiler timestamp or toolchain requires fresh exact SHA and receipt.

## Proof limit
Source QA, compiled frontend/dist, NSIS, PowerShell 5.1 Mode Check, Compose config and copied asset SHA are NOT live E2E. Gate 2 real provider model, Project File Search citing PDF/DOCX, Memory/cross-Chat; Gate 3 real physical deletion and shared-neighbor preservation; P4B maintenance; G3 signed release remain unproven.
