# Provider model-catalogue and manual-choice contract

This contract implements the promoted Runtime Development Strategy v0.7 provider boundary without creating a second model router or provider database.

## User-facing invariant

For a configured provider and the current user's credential, every model returned by the provider's compatible, authorized model-catalogue endpoint remains available in LibreChat's native selector. A Project or profile may recommend a default, but it must not silently narrow the authorized catalogue or mutate Project identity.

## Native ownership

- LibreChat remains the owner of encrypted `user_provided` credentials, `/api/models`, the Custom Endpoint, and the model selector.
- The Product does not read, print, export, duplicate, or publish user credentials.
- Model discovery is metadata retrieval only; it must not send an inference request or incur a model-completion charge.
- Public provider marketing lists are not proof of one user's entitlements.

## Failure and cache semantics

- A discovery timeout is an explicit degraded state, not proof that a one-item fallback is the complete catalogue.
- A last-known-good positive catalogue may be reused only when keyed by the credential-derived native cache identity; catalogues must not leak across users or credentials.
- ChatAnywhere receives a bounded 20-second discovery window and a 10-minute positive cache because the accepted five-second path repeatedly timed out. Other user-provided providers retain the prior five-second/no-shared-cache policy.
- Static defaults remain verified emergency fallbacks, never a hidden permanent whitelist.

## Acceptance ceiling

A one-time visible menu proves only `PASS_DISPLAY`. Durable capability requires current-consumer tests for delayed discovery, provider-down cached recovery, cross-credential isolation, normal reload/reopen behavior, and one natural user selection. It does not prove that every listed model can complete a billed request.

## Source and release linkage

The exact implementation is `patches/librechat/chatanywhere-native-model-catalog-r002.patch`, fenced by its JSON manifest and public regression test. Production adoption, Product PASS, and Program PASS are separate governed decisions.
