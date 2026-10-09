# Domain context

## Core terms

**Shell** — current LibreChat user-facing shell. Replaceable; never duplicated by a Pack or Runtime feature.

**Project** — workspace/context/history/source/artifact hub. Project identity is logical and portable.

**Runtime** — Authority, permission, revision, persistence legality, Promotion, currentness and audit control plane. Not the final UI.

**Pack** — optional reusable governed capability. A Project works without user Packs.

**Skill** — reusable method primitive, preferably LibreChat-native when possible. Skill identity is not Pack identity.

**MCP** — optional interoperability transport. Not Runtime Authority and not required for local work.

**Local Action** — replaceable host capability for local canonical read/write/process/git/test. Raw executor identity remains machine-local.

**Source** — Project-bound durable evidence with identity/revision/SHA/provenance. A Source is not equivalent to a File attachment.

**Library** — user-level reusable file pool. It must remain distinct from Project-only Sources and from generated Artifacts.

**Artifact** — generated durable output or governed evidence object.

## Design priority

Outcome first -> native LibreChat foundation -> smallest gap extension -> acceptance in the normal user flow -> retire custom seams when upstream absorbs them.
