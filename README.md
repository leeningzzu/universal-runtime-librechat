# Inquiry Desk - Windows online installer source (NONSHIPPING)

This is the source-and-build candidate in the existing Universal Runtime Git repository. It is not a promoted Product/Program baseline or a public release. No retired Pack is installed by default.

- Product: one LibreChat v0.8.8 shell plus Runtime Project/Memory/Chat/Source/C5 and optional governed capabilities.
- The compact NSIS Windows installer contains 81 exact product files, not Docker images or bundled Python environments. The installer can open official vendor prerequisite URLs and fetch SHA-pinned components when authorized.
- The installer is currently unsigned and NOT approved for general users. A compiler PASS does not prove full clean-machine install, UI, provider-model, Project data deletion, uninstall, or Program PASS.
- The exact built R232 candidate exists outside this Git source tree. See release/RELEASE_CANDIDATE.json; binary delivery belongs to a later approved GitHub Release asset rather than Git repository history.
- Developer binaries, private .env, old Projects, uploaded user data, API keys, Mongo volumes, Docker archives, offline wheelhouses and retired Packs are not copied to this publication branch.
- The historical developer main holds unrelated old source and six files with Windows user path literals. Never push main, --all or --mirror without separately auditing and approving it.
- Future code changes should be made here and verified with python tools/verify_distribution.py before a signed release candidate can be built. Exact branch/commit and CI receipts must be recorded before claiming source-to-EXE parity.

See docs/INSTALL_USER.md, docs/SECURITY_AND_CLEANUP.md, and docs/G3_RELEASE_GATE.md for user acceptance requirements.
