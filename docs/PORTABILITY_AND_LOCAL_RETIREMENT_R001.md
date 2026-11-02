# GitHub remote verification BEFORE local cleanup — data-safe decision

User intent: all relevant source, original Project research purposes, build status, tests, exact EXE bytes and independent-model reentry must survive even if disposable Windows staging files are retired. GitHub migration does not move personal Project data.

Mandatory proof before considering ANY local staging removal:
1. GitHub candidate branch source push success with exact new HEAD and fresh-clone readback of full product code, nine original Project Sources, five rc1 patch-source inputs, 393 built browser assets, installer, 495-line manifest, tests, notes and current handoff.
2. GitHub Actions CI run for that exact new commit PASS. Older branch checks do not count.
3. GitHub owner-only DRAFT Release exists with the exact R002 EXE and checksum sidecar, and user/account can download them. Actual downloaded file size 19,341,420 and SHA256 81420f4aacc56100d0027f335e8eaa460d4c9322f79afe7362c7ac86d0822c18. Upload response alone is not a byte parity readback.
4. Fresh clone from GitHub without old Windows source directories passes tools/verify_distribution.py and tools/verify_github_continuity.py. GitHub alone is sufficient for development source and build provenance, but NOT private user account data.
5. No active build/test process depends on a candidate staging directory; current user/source value and rollback value have been assessed individually.

Allowed to retire only exact inactive, reproducible scratch caches, obsolete incomplete temporary dependency archives and truly redundant failed installer duplicates, after all five proof families pass. Do not delete current source or EXE until remote reentry is independently verified. Never blindly clean a whole inbox, Desktop, Downloads, parent Runtime root or Docker host.

NEVER delete or publish without separate authorization: real Chat/Project/Memory/File/Source/Library data, account credentials, API secrets, Mongo/pgvector volumes, user backups, rollback assets, signed production artifacts or original promoted Project Source authority. No Docker prune, compose down -v or recursive user-data deletion.

RECOVERED AUTHORITY TEXT LIMITATION: Nine uploaded originals retain exact raw-file SHA. Hard Invariants v0.1, absent from that set, is now additionally present as indexed canonical text with five matching copies, but the original physical file SHA is unavailable; do not claim raw byte parity. Hard Invariants v0.2 Candidate remains NON_AUTHORITY.
