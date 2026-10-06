# Repository instructions for AI coding agents

## North star

Any supported Windows PC -> LibreChat shared AI Web/Desktop shell -> Runtime Authority/Governance -> optional governed Packs / AI Workbench.

## Product rules

- Product goals are outcome-first. LibreChat is the primary shell foundation, not the ceiling on user experience.
- Preserve one shared LibreChat shell. Do not create a second shell.
- Prefer current LibreChat native capability before custom work.
- Do not create a second Chat DB, File DB, Search DB, vector DB, notes backend, generic Agent harness, generic Skill engine, generic MCP platform, generic Pack factory, or custom updater/delta engine unless a proven remaining gap requires it.
- Project identity is not Provider, Pack, Agent, MCP server, executor, session, drive letter, username, or absolute path.
- Packless Projects must remain fully usable.
- Promotion != Install; Install != Activate; Deactivate != Uninstall; Update != auto-adopt.
- Local Action providers are replaceable machine-local capabilities.
- Same-Project continuity must not require the user to select a hidden persistent Agent.
- Storage != retrieval != context injection != exact recovery.

## Project experience target

The normal Project flow must approach ChatGPT-like continuity:
- Project Instructions
- Project-scoped Memory
- same-Project cross-chat recall
- exact historical message recovery when claims matter
- Files/Sources
- bounded context
- Project isolation
- backup/restore/rebind
- clear Archive/Delete semantics

If LibreChat native behavior falls short of that contract, keep or add only the smallest replaceable seam needed to close the gap.

## Upstream absorption

Before custom work, inspect `docs/upstream/librechat.lock.json` and `docs/upstream/CUSTOM_SEAMS.yaml`.
Classify the seam as exactly one of:
- DELETE
- DEPRECATE
- KEEP_THIN
- KEEP_GAP
- DEFER

A new LibreChat stable release invalidates only proof families directly affected by changed upstream behavior.

## Safety and public-source rules

Never commit:
- API keys, OAuth/session tokens, cookies, browser profiles, DPAPI blobs, credentials
- user/private Projects, Chats, Memory, Sources, account data
- Mongo data/dumps
- machine-local resolver state
- absolute developer-machine paths
- Production `.env`
- `.staging`, `artifacts`, `.venv`, `.sidecars`, caches, logs, rollback bytes

Run `python scripts/public_repo_guard.py` before commit.
