# Project experience contract

## Normal flow

New Project -> purpose once if needed -> New Chat -> direct request. The Project remains the user's durable workspace for conversation history, Instructions, explicit Memory, Files/Sources, bounded relevant context and saved Artifacts.

Normal users should not manually assemble an Agent, Skill, MCP server, Pack, provider tool router or local executor just to obtain Project continuity. External cloud storage/sync is not required for local Project use.

## Required Project behavior

A Project must provide:
- native LibreChat Project UI and chat lifecycle wherever sufficient;
- Project Instructions using LibreChat-native limits unless a proven need changes them;
- Project-scoped explicit Memory and clearly separated optional global-memory policy;
- same-Project cross-chat recall with exact historical-message reads when claims matter;
- Project Files/Sources with owner, revision, provenance and correct current bytes;
- safe, bounded source-to-new-Chat retrieval, citing verified evidence without full-library/history injection;
- strict cross-Project/user isolation, including file/knowledge lookup;
- durable Chat output to Source/Artifact with version, reopen and safe recovery semantics;
- clear Project-level Archive, Delete, retention and same-machine data backup/restore/repair behavior;
- portable logical identities that do not depend on machine-local username/drive/install root;
- optional Project/Pack/Local Action capabilities without making them Project identity.

## Currentness and proof boundaries

The accepted normal-use Project Core remains valid at its proven ceiling. Current Daily source-to-new-Chat/file reattachment, RAG security, Archive/Delete and full Project backup still require their specific natural user and data safety proofs. Do not promote isolated tests or source presence to Product PASS. Unsafe File Search remains off for the affected consumer until scoped native owner isolation is accepted.

## Continuity target

Recent same-Project context may be injected automatically within a bounded budget; older information must remain exactly recoverable through candidate search followed by exact-message read. Project source files never all enter every chat by default.

Continuity and model choice remain Provider-neutral. ChatAnywhere or any authorized model, Agent or Pack must not silently erase Project Memory/history/current Source governance. A temporary provider catalogue failure cannot narrow the authorized user model choices without an explicit degraded status.

## File/Artifact ownership

Prefer LibreChat native Project Files and user-file reuse where complete. Project Sources, user-global Library files and generated Artifacts are different fact classes. Do not create another File DB/Search DB/vector DB/notes backend. Deleting a Project must not delete shared Library objects or external canonical files without a separate authorized effect.

## Installed EXE is not Project data migration

Aides final packaged EXE must install on a fresh supported Windows PC and permit a normal user to create a **new** local Project without cloud sync or importing an old machine's database. Optional old-Project export/import/rebinding is a separate feature; it must not block the fresh-EXE user journey. On-device data preservation across launch, restart, repair, update and rollback remains mandatory wherever affected. Packs are optional and must not become a default Project dependency.
