# Universal Runtime｜Project Source｜Pack Lifecycle & Update v0.3

STATUS = STABLE_PROJECT_SOURCE
AUTHORITY_STATUS = ACTIVE_STABLE_AUTHORITY
REVISION_OF = PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE_v0_2.md
SUPERSEDES = PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE_v0_2.md
PROMOTED_FROM = PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE_v0_3_CANDIDATE_R001.md
PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
STABLE_PACK_LIFECYCLE_AUTHORITY = PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE_v0_3.md
HISTORY_REWRITE = NO

## 1. Purpose

Define lifecycle rules for:
- Packless Core and optional user-Pack semantics;
- Pack discovery/availability, install, activation, deactivation and uninstall;
- multiple registered/active Packs;
- Pack version pinning;
- Pack and Rule updates;
- adopted external-component update discovery;
- creator-facing update reminders;
- staged simplification opportunities;
- regression, Promotion and rollback boundaries.

This Source stores governance only. It must not store current Pack versions, current external SHAs, active Job IDs, temporary update candidates, current logs, Build Status, or machine-specific installed paths.

## 2. Core principles

MULTI_PACK_SUPPORTED = YES
PACK_COMPOSITION_BY_CAPABILITY_CONTRACT = YES
JOB_SCOPES_PACK_LOADS = YES
PACK_PERMISSION_IS_JOB_SCOPED = YES
ONE_PRIMARY_PACK_PER_JOB_BY_DEFAULT = YES
PACKLESS_CORE_MODE_SUPPORTED = YES
ALL_USER_PACKS_OPTIONAL = YES
PACK_PROMOTION_NE_INSTALL = YES
PACK_INSTALL_NE_ACTIVATE = YES
PACK_ACTIVATE_NE_PROJECT_IDENTITY = YES
PACK_DEACTIVATE_NE_UNINSTALL = YES
PACK_UPDATE_NE_AUTO_ACTIVATE = YES
PACK_UNINSTALL_REQUIRES_ZERO_ACTIVE_CONSUMERS = YES

PACK_UPDATE_IS_CANDIDATE_FIRST = YES
RUNNING_JOB_PINS_PACK_VERSION = YES
PACK_UPDATE_NE_AUTO_PROMOTE = YES
PACK_UPDATE_REQUIRES_REGRESSION = YES
PACK_UPDATE_NEVER_REWRITES_HISTORY = YES

EXTERNAL_UPDATE_DISCOVERY_SUPPORTED = YES
MATERIAL_UPDATE_NOTIFICATION = YES
UPDATE_BRIEF_BEFORE_ADOPTION = YES
SIMPLIFICATION_OPPORTUNITY_REVIEW = YES
EXTERNAL_UPDATE_NE_AUTO_ADOPT = YES

SYNC_NE_UPDATE = YES
UPDATE_NE_PROMOTE = YES

## 3. User Pack installed lifecycle

Core Product must remain usable with no user Pack installed or active. User Packs are optional capabilities, not required application components.

Recommended user-facing lifecycle:
`AVAILABLE → INSTALLED → ACTIVATED → DEACTIVATED → UNINSTALLED`

Version/update lifecycle is orthogonal:
`INSTALLED vN → UPDATE CANDIDATE vN+1 → REVIEW → PROMOTION → future activation/adoption`

Rules:
- `AVAILABLE` is discoverable/eligible; it is not installed.
- `INSTALLED` means local bytes/metadata are present and verified; no Project/Job is implied to use them.
- `ACTIVATED` means one Project/Job may select/pin the exact Pack revision under Runtime Authority.
- `DEACTIVATED` removes future/default consumption without deleting Pack bytes or rewriting history.
- `UNINSTALLED` removes Pack bytes only when no active Project binding, running Job pin, required rollback/migration dependency or retained audit consumer requires them.
- Promotion creates a legal version; Promotion must not silently install, activate or rebind a Project.
- Uninstall must distinguish Pack code/content from Project data and durable artifacts produced while the Pack was active.

PACKLESS_PROJECT_SUPPORTED = YES  
INSTALL_IS_MACHINE_STATE = YES  
ACTIVATION_IS_PROJECT_OR_JOB_SCOPED = YES  
PROMOTION_NE_ACTIVATION = YES  
UNINSTALL_NE_HISTORY_DELETE = YES

## 5. Multi-Pack lifecycle

Runtime may register many Packs. A normal Core Chat/Project may use zero Packs. A Pack-governed Job normally has zero or one PRIMARY_PACK by default; supporting capability composition is allowed only when a concrete consumer proves the need.

A Pack-governed Job may have:
- zero or one PRIMARY_PACK by default;
- zero or more SUPPORTING_PACKS/capabilities only when justified;
- one Job-specific Authority Map;
- one Load Plan;
- one Permission Plan;
- one Execution Budget;
- pinned component versions.

Supporting Packs expose capabilities through Runtime-owned contracts. Do not load complete Pack contexts merely because a supporting capability is used.

Permissions are scoped to the Job/capability. Permission granted to one Pack/capability must not silently flow to another.

MULTI_PACK_ORCHESTRATION_REMAINS_DEFERRED_UNTIL_NATURAL_NEED = YES

## 5. Job version pinning

At Job creation, pin the execution provenance needed for reproducibility, including where applicable:

- Pack ID/version
- Workflow version
- Rule version
- Adapter/Executor version
- external component exact revision
- Model Profile
- relevant contract/schema revision

A running Job continues with its pinned versions even when newer versions are promoted later.

Do not mutate a running Job from Pack vN to vN+1 mid-workflow.

A new version may be selected by future Jobs after explicit Promotion.

## 6. Pack update levels

### PATCH

Examples:
- bugfix
- rule correction
- Adapter correction
- no breaking contract change

Typical gate:
targeted deterministic tests
→ Pack regression
→ staging
→ explicit Promotion.

### MINOR

Examples:
- new optional capability
- new compatible Adapter
- backward-compatible contract extension

Typical gate:
capability fixture
→ compatibility tests
→ Pack regression
→ staging
→ Promotion.

### MAJOR

Examples:
- Pack schema break
- Authority ownership change
- Artifact/persistence format change
- workflow-state contract break

Requires:
migration plan
→ old/new fixtures
→ compatibility analysis
→ migration tests
→ shadow/staging
→ explicit human/Controller approval.

Old projects may remain pinned to the old major version.

## 7. External component update discovery

Adopted external components remain pinned to an exact commit/tag/release.

Discovery of upstream changes may be periodic or user-triggered, but discovery itself is metadata-only by default.

Do not automatically clone, install, import or execute a newly released version.

Possible metadata sources include:
- releases/tags
- changelog/release notes
- security advisories
- license metadata
- compatibility notes
- API/CLI deprecation notices

The Runtime should compare the discovered version against the currently adopted exact revision.

## 8. Material update classification

Classify discovered changes as one or more of:

NO_MATERIAL_CHANGE
SIMPLIFICATION_CANDIDATE
CAPABILITY_IMPROVEMENT
COMPATIBILITY_IMPROVEMENT
SECURITY_RELEVANT
MAINTENANCE_RELEVANT
BREAKING_CHANGE
LICENSE_CHANGE
DEPRECATION_RISK

NO_MATERIAL_CHANGE should normally produce no user interruption.

Material notification is appropriate when a change could:

- materially improve the creator's workflow;
- remove custom Runtime/Pack code;
- eliminate a workaround;
- merge or remove an Adapter/sidecar/dependency;
- reduce dependency or permission surface;
- improve Windows/local compatibility;
- improve deterministic/reproducible behavior;
- materially improve reliability/performance;
- provide a capability previously planned for custom development;
- fix a meaningful security/maintenance problem;
- introduce a breaking/license/deprecation risk that requires action.

## 9. Simplification Opportunity Review

When an external update may simplify the architecture, do not evaluate only “new features.”

Ask:

1. Can this replace custom code?
2. Can it remove an Adapter or sidecar?
3. Can it collapse multiple external components into one without authority leakage?
4. Can it reduce dependency, network, permission or persistence complexity?
5. Can it remove a workaround discovered in Retrospective?
6. Can it simplify the creator-facing workflow?
7. Does the simplification preserve Runtime-owned contracts and replaceability?

A simplification is not beneficial if it increases lock-in, authority coupling, security risk, or replacement cost more than the complexity it removes.

## 10. Creator-facing Update Decision Brief

For a material update, provide a concise brief:

CURRENT_COMPONENT =
CURRENT_REVISION =
NEW_CANDIDATE =
MATERIAL_CHANGE_CLASS =

WHAT_CHANGED =
WHY_RELEVANT =
SIMPLIFICATION_OPPORTUNITY =
CAPABILITIES_AFFECTED =
BENEFITS =
RISKS_OR_REGRESSIONS =
WINDOWS_COMPATIBILITY =
LICENSE_SECURITY_CHANGE =
INTERNAL_CONTRACT_IMPACT =
INTEGRATION_OR_MIGRATION_COST =
RUNNING_JOB_IMPACT = NONE / EXPLAIN
RECOMMENDED_OPTIONS =

Normally offer only relevant choices:

KEEP_CURRENT
STAGE_UPDATE_CANDIDATE
REPLACE_CUSTOM_CAPABILITY
RECOMPOSE_CAPABILITIES
DEFER

Do not ask the creator to decide from version numbers alone.

## 11. External update staging

If an update is worth evaluating:

discovered upstream version
→ exact candidate revision
→ license/security delta review
→ affected-capability contract test
→ Adapter/Executor fixture
→ Pack regression
→ compatibility check
→ shadow/live test only if evidence requires it
→ Controller decision
→ explicit Promotion.

No update may bypass the Runtime Internal Contract.

If upstream API changes but Pack contract does not, prefer adapting the Adapter rather than leaking the new external API into Pack schema.

If the Pack contract must change, reclassify the update to the appropriate Pack update level.

## 12. Sync, Update, Promotion

SYNC:
discover/register a candidate or upstream revision.
No production behavior change.

UPDATE/STAGE:
build/test a new Pack/component candidate in isolation.
No production default change.

PROMOTE:
explicitly make the accepted candidate available as the new default for eligible future Jobs/projects.

SYNC != UPDATE != PROMOTE.

## 13. Rollback and history

Promotion never deletes the previous accepted version.

Maintain provenance sufficient to return a project/new Job to an earlier compatible Pack/component version.

A rollback is a new controlled binding decision, not history rewriting.

Running Jobs remain pinned unless a separate migration/reopen decision explicitly changes them.

## 14. External update and process improvement

A material external update may trigger a programmer-style Retrospective when it:

- eliminates a repeated workaround;
- reveals duplicated custom capability;
- significantly simplifies workflow;
- changes the best capability composition;
- invalidates an earlier integration assumption.

Any generalized process change follows the current Process Improvement owner selected by current Project Instructions.

Stable governance changes remain Candidate-first, prefer full-replacement Source successors, require exact review/evidence proportional to the change, and require explicit Promotion. This lifecycle Source must not bind itself to an obsolete Process revision or legacy MANUAL_PATCH_CANDIDATE naming convention.

## 15. Automation boundary

Do not build a large automatic Updater/Marketplace/Dependency Solver before the lifecycle is proven.

Initial implementations may use manual or narrow metadata checks.

Only after multiple real Pack/external-component updates demonstrate stable repeated patterns should common automation be considered.

Automated update discovery, when later implemented, may notify about material changes but must not auto-install or auto-promote.

## 16. Stop conditions

STOP and return to Controller if:

- an update would overwrite history;
- a running Job would silently change pinned version;
- upstream change leaks third-party types into Pack schema;
- license/security change is unresolved;
- migration impact is unknown;
- update requires unapproved permissions/dependencies;
- simplification would increase authority coupling;
- the update path becomes more complex than keeping/reimplementing the capability;
- automatic discovery is about to become automatic adoption/promotion.

---

---

## 17. Stable disposition

This v0.3 is the active Stable Pack Lifecycle & Update Authority.

It preserves v0.2 version pinning, Candidate-first update, external-component currentness, simplification, Promotion, rollback and running-Job immutability semantics while adding Packless Core, optional user-Pack semantics, install/activate/deactivate/uninstall lifecycle, Promotion/install/activation separation, and zero-or-one Primary Pack semantics by default.

Multi-Pack orchestration remains deferred until natural evidence requires it. Promotion of this governance Source does not install, activate, bind, update, or remove any Pack.

`PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE_v0_2.md` is historical superseded authority; the v0.3 Candidate remains promotion provenance only.

PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
