# Public Source License and Attribution Review

This document records a bounded source-only attribution review; the actual
repository copyright grant is the root **LICENSE**. On 2026-10-09 the owner
explicitly selected MIT for original Universal Runtime source. The root
**NOTICE** preserves applicable third-party licensing references. Later
LibreChat source patch or Windows binary releases require separate review.

## Source-owned boundaries

- This repository is a sanitized Universal Runtime **source-only** candidate.
- The user-facing LibreChat application/shell is upstream; this repository
  does not ship full LibreChat source or its compiled app.
- The patches/librechat/README.md file is a SHA/path inventory, **not**
  redistributed source or a claim that the private modification is
  accepted for public release.
- Local current Handoff, Pack installations/promotions, user File bytes,
  Mongo, backups, credentials and machine resolver roots stay outside Git.
- No automatically installed Packs or second Shell.

## Verified LibreChat upstream source

- Official: https://github.com/LibreChat-AI/LibreChat
- Release: v0.8.8, marked pre-release by GitHub.
- Full verified tag commit:
  e8f3be08623663d4ad7f7241e693c94469b63bb0.
- Upstream repository license: MIT, per GitHub API.
- Preserve upstream copyright/license/NOTICE on redistributed derivative
  patches or copied source. Actual private patch series and downstream
  redistribution rights remain subject to separate source review.

## Other vendor notice in this source candidate

src/universal_runtime/web_vendor/LICENSE.markdown-it-14.3.1.txt
contains original authors' copyright and MIT-style license. Preserve it
with any corresponding vendored Markdown-it material. An original project
license must not override a third-party notice.

## Repository license decision: accepted MIT

The owner explicitly replied **采用 MIT** on 2026-10-09 and earlier authorized
public GitHub repository creation and sanitized source upload under
https://github.com/leeningzzu/universal-runtime-librechat.

- Original Universal Runtime source: root MIT LICENSE, leeningzzu 2026.
- Upstream LibreChat: MIT, exact verified v0.8.8 commit recorded above.
- Separate markdown-it license: retained in source as originally provided.
- Historical license gate: preserved in
  docs/upstream/REPOSITORY_LICENSE_DECISION_R001.md with status
  **ACCEPTED_MIT_R001**.
- Raw LibreChat patches/compiled Shell: not included in current source-only
  publication; require future exact-diff and notice review.

This decision lifts the original-source-license choice blocker for the
reviewed source-only branch. It is **not** a Product PASS, Windows installer,
permission to publish private data, or a claim that all future distributions
have already been reviewed.
