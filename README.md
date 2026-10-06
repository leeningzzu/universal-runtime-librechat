# Universal Runtime / AI Workbench

Universal Runtime is a Windows-first product built on the current LibreChat shell. The product goal is not to copy LibreChat or accept its present limitations; it reuses LibreChat native capabilities wherever they satisfy the product contract and adds only the smallest governed extensions needed for Project continuity, explicit Project Memory, exact Source currentness, portable local work, Pack lifecycle, and release governance.

## Product contract

Normal use is Project-first:

1. Open the shared LibreChat-based shell.
2. Create or open a Project.
3. Start a chat.
4. Ask directly.

Users should not need to understand Packs, MCP, local executors, ports, Docker, SHAs, or Promotion for normal work.

See:
- `docs/PROJECT_EXPERIENCE_CONTRACT.md`
- `docs/CAPABILITY_LIFECYCLE_MATRIX.md`
- `docs/upstream/CUSTOM_SEAMS.yaml`
- `AGENTS.md`

## Upstream-first rule

For every capability, prefer:

`LibreChat current upstream -> existing Runtime/Pack -> mature prior art -> thin adapter -> narrow custom gap only`.

If a later LibreChat release absorbs a custom seam, deletion or deprecation is preferred over maintaining two implementations.

## Repository status

This repository staging is a sanitized public-source foundation, not a Production snapshot. It intentionally excludes user data, current Mongo data, browser state, machine-local resolver state, secrets, rollback bytes, private Projects, unpublished domain Packs, and build caches.

Publication is blocked until the repository-level license is explicitly selected. See `LICENSE_DECISION_REQUIRED.md`.
