# Project experience contract

## Normal flow

New Project -> purpose once if needed -> New Chat -> direct request.

Normal users should not manually assemble an Agent, Skill, MCP server, Pack or local executor just to obtain Project continuity.

## Required Project behavior

A Project must provide:
- native LibreChat Project UI and chat lifecycle where sufficient;
- Project Instructions using the LibreChat-native limit/configuration unless a proven user need requires otherwise;
- Project-scoped explicit Memory;
- Project-only or Project-plus-global-memory policy;
- same-Project cross-chat recall;
- exact historical message read when precise claims matter;
- Project Files/Sources;
- bounded retrieval/context injection;
- strict cross-Project isolation;
- portable identity across supported Windows machines;
- backup/restore/rebind;
- clear Archive and Delete semantics;
- optional Pack/Local Action capabilities without making them Project identity.

## Continuity target

Recent same-Project context may be injected automatically within a bounded budget. Older information must remain exactly recoverable through candidate search followed by exact-message read.

Continuity must be Provider-neutral. Selecting ChatAnywhere, another provider, or an Agent must not silently remove Project Memory/history semantics.

Model choice is also Provider-neutral: a Project may recommend a model, but the native selector must preserve every model actually authorized for the current user and provider. A transient catalogue failure or one-item fallback must not be promoted as the complete authorized set.

## File capacity

The Product should preserve LibreChat native Project-file capacity rather than lowering it to an internal Runtime retrieval prototype limit. Runtime retrieval limits are implementation ceilings, not user-visible Project limits.

## Delete semantics

Delete/Archive semantics remain a material Product decision. External canonical local files and user-global Library files must never be silently deleted because one Project is removed.
