# Security policy

This repository is intended to be public only after its publication blockers are cleared.

## Never commit

- provider API keys or secret values
- OAuth access/refresh tokens
- cookies, browser sessions, trust/device-bound tokens
- passwords or account exports
- DPAPI/encrypted local secret blobs
- current Mongo data or database dumps
- private Project/Chat/Memory/Source content
- user-uploaded files
- machine-local resolver state
- absolute developer workstation paths
- Production `.env` files
- rollback/preimage archives containing private data

## Reporting

Before public publication, report security issues privately to the repository owner. Do not put secrets or exploit payloads into a public issue.

## CI trust boundary

Pull-request workflows must not expose privileged secrets to untrusted fork code. Release/publish operations remain explicit trusted actions.
