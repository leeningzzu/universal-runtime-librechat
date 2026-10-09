# Repository licensing decision — R001

## Prior gate (preserved history)

Previously, this repository did not have a chosen public source license.
The initial publication gate was `BLOCK_PUBLICATION` and prohibited pushing
source until the owner selected a repository license and reviewed NOTICE and
LibreChat provenance. The historical filename was
`LICENSE_DECISION_REQUIRED.md`.

## Explicit owner decision

On 2026-10-09, the owner authorized creating and publishing a PUBLIC source
repository under the GitHub account `leeningzzu` and explicitly selected:
**"采用 MIT"** (adopt MIT).

- Original Universal Runtime repository source: **MIT**.
- Root LICENSE: canonical MIT text, copyright (c) 2026 leeningzzu.
- Root NOTICE: describes LibreChat MIT upstream and separately retained
  markdown-it license.
- Upstream LibreChat version pin: v0.8.8 full GitHub tag commit
  e8f3be08623663d4ad7f7241e693c94469b63bb0, pre-release category.
- Current source-only tree includes private-modification path/hash inventory,
  **not** a complete redistributed LibreChat patch series or Docker release.
- This decision does **not** authorize publishing user/private assets,
  model/provider secrets, machine state, development Packs or Product installers.

Decision status: **ACCEPTED_MIT_R001**. Previous license-choice blocker:
**CLOSED** for this reviewed source-only repository. New upstream copyrighted
assets and future binary/patch releases require their own scoped notice
review. Product/Program release acceptance remains separate.
