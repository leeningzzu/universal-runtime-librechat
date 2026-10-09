# Public Source License and Attribution Review

This document is **not a repository LICENSE**. Publication remains blocked
until the repository owner explicitly selects a source license and the
resulting LICENSE/NOTICE review completes.

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

## Owner decision still required

Before pushing the reviewed source into the public repository, choose how
**original Universal Runtime code** is licensed (e.g. MIT, Apache-2.0,
or retaining all rights with no downstream reuse license). MIT upstream
does not automatically grant rights to original downstream code.
Review selected license compatibility and notices; close or supersede
LICENSE_DECISION_REQUIRED.md only after acceptance.

Public GitHub empty repository creation is separately authorized and now
completed. A public empty repo is not a public source release.
