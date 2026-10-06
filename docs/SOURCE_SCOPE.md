# Public source scope

## Included in this foundation

- `src/`
- public-safe `tests/`
- `schemas/`
- `fixtures/`
- selected portable `scripts/`
- selected non-secret `config/`
- `packs/simplified_market_reference/`
- public architecture/experience/upstream-control docs
- GitHub workflow definitions

## Intentionally excluded

- Production `.env`
- current `artifacts/`
- current `.staging/`
- `.sidecars/`
- `.venv/`
- `logs/`, `workspace/`, `handoff/`
- `_installed/`, `_authoritative/`
- browser profiles/cookies/sessions
- Mongo data/dumps
- private Project/Chat/Memory/Source content
- machine-local resolver state
- rollback/preimage archives
- unpublished or provenance-unreviewed domain Packs
- tests that require those excluded private/unreviewed Pack fixtures
- private/frozen acceptance harnesses that depend on unpublished artifacts, promoted private Pack authority, old frozen HTML, or machine-specific model/provider state

This is an allowlist export, not a mirror of the development machine.
