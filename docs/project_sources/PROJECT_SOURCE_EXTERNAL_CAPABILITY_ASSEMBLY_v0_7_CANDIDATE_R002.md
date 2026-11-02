# Universal Runtime｜Project Source Revision Candidate｜External Capability Assembly v0.7 R002

STATUS = PROJECT_SOURCE_REVISION_CANDIDATE
AUTHORITY_STATUS = NON_AUTHORITY_UNTIL_EXPLICIT_PROMOTION
REVISION_OF = PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_6.md
TARGET_IF_APPROVED = PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_7.md
FULL_REPLACEMENT_CANDIDATE = YES
SUPERSEDES_CANDIDATE = PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_7_CANDIDATE_R001.md
PROMOTION_STATUS = NOT_PROMOTED
ACTIVE_STABLE_EXTERNAL_CAPABILITY_AUTHORITY = PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_6.md
HISTORY_REWRITE = NO
MODEL_OUTPUT_IS_PROPOSAL_ONLY = YES
NO_SILENT_STABLE_SOURCE_MUTATION = YES

SEMANTIC_DELTA =
HIGH_COMPLEXITY_SINGLE_SEAM_WHOLE_SOLUTION_TRIGGER
+ LIFECYCLE_RESPONSIBILITY_COMPLEXITY_NOT_SURFACE_COUNT_ONLY
+ SIMPLE_SINGLE_SEAM_NONTRIGGER
+ EXISTING_WHOLE_SOLUTION_ROUTE_PRESERVED
+ WINDOWS_PORTABILITY_AND_PATH_IDENTITY_ASSESSMENT
+ INTEROP_TRANSPORT_NE_CAPABILITY_AUTHORITY
+ INTERNAL_PROXY_TUNNEL_REJECTION
+ LOCAL_ACTION_HOST_REPLACEABILITY

## 1. Purpose

Define how Runtime evaluates and composes material external capabilities for the shared product foundation, development/runtime infrastructure, and Domain Packs while keeping Runtime-owned authority and contracts.

This Source is stable governance. It does not store current package selections, temporary repository SHAs, current Build Status, current milestone state, credentials, ports, or one-off decisions.

It does not own current executor preference, product architecture, Pack creation details, or Process route/Stop-Loss; those remain with their owning Sources / Project Instructions.

## 2. Core principles

REUSE_BEFORE_REIMPLEMENT = YES
CAPABILITY_FIRST_NOT_REPOSITORY_FIRST = YES
COMPOSE_BY_CONTRACT_NOT_SOURCE_MERGE = YES
INTERNAL_CONTRACT_BEFORE_EXTERNAL_INTEGRATION = YES
EXTERNAL_REPOSITORY_IS_NOT_AUTHORITY = YES
ONE_CAPABILITY_ONE_ADOPTION_DECISION = YES
ONE_EXTERNAL_COMPONENT_ONE_PROVENANCE_RECORD = YES
PRODUCT_SHELL_UPSTREAM_BEFORE_EXTERNAL_PRODUCT_BUILD = YES
WHOLE_SOLUTION_DONOR_CHECK_BEFORE_MULTI_COMPONENT_COMPOSITION = YES
WHOLE_SOLUTION_DONOR_CHECK_FOR_HIGH_COMPLEXITY_SINGLE_SEAM = YES
BROAD_EXTERNAL_OPERATOR_SURFACE_NOT_DEFAULT = YES
ADJACENT_CONSUMER_SCAN_BEFORE_COMPONENT_GLUE = YES
WHOLE_SOLUTION_UI_OR_WORKFLOW_CAN_OUTRANK_CUSTOM_BRIDGE = YES
CROSS_LIFECYCLE_CAPABILITY_FAMILY_SCAN_BEFORE_CUSTOM_INFRASTRUCTURE = YES
PLANNED_CUSTOM_DELETION_IS_FIRST_CLASS_REUSE_BENEFIT = YES
SYSTEM_UPDATE_DISCOVERY_NE_AUTO_ADOPTION = YES
MATERIAL_CROSS_LAYER_COMPOSITION_RECHECK = YES
CURRENT_PROJECT_NAMES_NE_LONG_TERM_AUTHORITY = YES
ONE_PRIMARY_IMPLEMENTATION_PER_CAPABILITY_FAMILY_BY_DEFAULT = YES
ANY_SUPPORTED_WINDOWS_PC_COMPATIBILITY_REQUIRED_FOR_PORTABLE_PRODUCT_COMPONENT = YES
INTEROP_TRANSPORT_NE_CAPABILITY_AUTHORITY = YES
MCP_IS_OPTIONAL_INTEROP_NOT_PROJECT_IDENTITY = YES
INTERNAL_PROXY_OR_TUNNEL_DEPENDENCY_REJECT = YES
LOCAL_ACTION_EXECUTOR_MUST_REMAIN_REPLACEABLE = YES

A product capability, Runtime/development infrastructure capability, or Pack may combine strengths from external projects. Composition occurs through the narrowest sufficient Runtime-owned Contract + Adapter/Skill/Executor/Sidecar/Connector. Unmanaged source-tree fusion is forbidden.

External capability roles must be distinguished:

METHOD_DONOR = idea / definition / validation method only
CAPABILITY_DONOR = narrow module / API / CLI / connector reuse
PRODUCT_OR_RUNTIME_COMPONENT = a proven component that actually enters the running architecture

Most candidates should remain METHOD_DONOR or CAPABILITY_DONOR unless runtime adoption materially reduces total complexity.

Runtime retains Authority, Artifact, Revision/SHA, Permission, Persistence, Promotion and Audit.

## 3. Material external-capability sequence

Preferred sequence for a material product / Runtime-infrastructure / Pack capability gap:

User / product / domain outcome
→ Current Product-Shell Upstream Capability (when product-facing)
→ Existing Runtime / Pack Capability Inventory
→ Capability Map
→ External Prior-Art Discovery
→ Candidate Shortlist
→ Mature Whole-Solution Check
→ Adjacent Consumer / Product Loop Challenge
→ GitHub / vendor Capability Comparison
→ Reuse Mode Decision
→ Narrow Internal Contract
→ Minimal Integration
→ Deterministic Fixture / Side-by-side Proof
→ Regression / Security / License Review
→ Provenance
→ Staging
→ Explicit Promotion when persistence or Production adoption is required

Do not start with “which repository should become the Pack/product.”
Start with “what exact outcome is missing, what already exists, and which mature capability can delete the most custom work with the least new authority/dependency surface.”

If one mature whole solution can safely absorb several planned custom subcomponents, compare that route before composing multiple new dependencies.

Apply the same whole-solution check when the named gap appears to be only one seam but that seam would make one custom owner carry several long-lived, coupled lifecycle responsibilities such as durable state/persistence, restore/replay, concurrency/single-writer safety, idempotency/crash recovery, latest-state discovery/indexing, integrity/corruption detection, rollback/point-in-time recovery, or IAM/secret/privacy/rights boundaries. Complexity is therefore not inferred from planned surface count alone.

Before authoring glue for a material seam, also ask how the candidate changes the complete user/product loop, not only the named integration point:
- which upstream/downstream consumers become simpler or disappear;
- whether a mature UI/workflow already delivers the user outcome without deeper protocol integration;
- whether the candidate creates duplicate evidence/authority paths;
- what new maintenance, credential, network, update or removal burden appears;
- what deeper integration remains genuinely unproven after the minimum baseline.

A mature whole-solution surface may be selected as the first product baseline even when a more embedded integration is technically possible. Embedded integration becomes a later candidate only when natural use proves material burden or missing capability.

## 4. Capability Map

Decompose the material product / infrastructure / Pack gap into capabilities before evaluating repositories.

Typical categories may include:

- planning
- memory/state
- retrieval
- drafting/generation
- revision/audit
- deterministic computation
- data acquisition
- citation/provenance
- UI
- orchestration
- persistence
- domain rules

Each capability receives an independent adoption decision.

## 4A. Cross-lifecycle capability-family map

For product-foundation and EXE-lifecycle work, capability discovery must scan the complete affected product loop rather than only the named seam.

Typical cross-lifecycle capability families include:

- product shell / workspace / Projects / Memory / Knowledge / Files / Web / Tools;
- developer execution / coding agent / project-bound development surface;
- tool and agent interoperability protocols;
- Windows thin-shell primitives: window, tray, single-instance, autostart, deep link, notification, window state and capability/permission boundary;
- installer / updater / distribution / repair / rollback delivery;
- local service / process lifecycle;
- dependency and upstream update discovery;
- software supply-chain scanning, SBOM, provenance, attestation and signing;
- browser/tool automation;
- Knowledge / RAG / Memory backends;
- diagnostics / tracing / observability;
- installed-app secret storage;
- any adjacent capability whose mature implementation can delete planned custom work elsewhere in the loop.

This list is a capability taxonomy, not a frozen component selection.

Before custom infrastructure is authored in any such family:

CURRENT_UPSTREAM / PLATFORM PRIMITIVE
→ EXISTING PRODUCT / RUNTIME CAPABILITY
→ MATURE WHOLE-SOLUTION / COMPONENT
→ THIN_ADAPTER / COMPOSE / UPDATE / REPLACE
→ ONLY THEN GENUINE CUSTOM GAP

The comparison must ask not only “can this component implement the named feature?” but also:

- which planned custom modules can now be deleted before they are built;
- which existing adapters, launchers, bridges or user steps become unnecessary;
- whether one mature platform primitive absorbs several separate planned subsystems;
- whether an apparently smaller dependency introduces a larger credential/network/update/maintenance burden;
- whether the selected route remains replaceable and rollbackable.

Concrete current products/repositories belong in transient Build Status / current capability maps, not in this Stable Source.


## 4B. High-complexity single-seam whole-solution trigger

A nominally single capability/seam can still be a whole-solution candidate when its custom implementation would bundle multiple lifecycle responsibilities that are independently failure-prone, security- or authority-sensitive, and expected to evolve over time.

Classify:

HIGH_COMPLEXITY_SINGLE_SEAM = YES / NO
HIGH_COMPLEXITY_REASONS =
PLANNED_CUSTOM_SURFACES_BEFORE =
PLANNED_CUSTOM_SURFACES_AFTER =
CUSTOM_SURFACES_ELIMINATED =
DONOR_GLUE_DELTA =
MAINTENANCE_DELTA =
AUTHORITY / DEPENDENCY / REMOVAL_COST =

HIGH_COMPLEXITY_SINGLE_SEAM = YES only when a mature whole solution could materially absorb the bundled responsibilities or delete custom infrastructure. It is not triggered by a fixed keyword list, fixed responsibility count, repository size, or abstract technical difficulty score.

Typical signals may include several of:
- durable state / persistence continuity;
- backup, restore or replay;
- concurrency / single-writer coordination;
- idempotency / crash recovery;
- discovery/indexing of the latest valid state;
- content identity / integrity / corruption detection;
- rollback / point-in-time restore;
- credential / IAM / secret boundaries;
- privacy / data-rights boundaries;
- lifecycle update/removal duties that would otherwise become custom infrastructure.

Required order remains:

CURRENT / UPSTREAM CAPABILITY
→ MATURE WHOLE-SOLUTION OR COMPONENT
→ THIN ADAPTER / COMPOSE / UPDATE / REPLACE
→ GENUINE CUSTOM GAP ONLY

A simple stateless API, parser, single pure transformation, or narrow seam already fully owned by an existing capability without new persistence/recovery/concurrency/index/permission lifecycle is a correct nontrigger. Do not manufacture whole-solution research merely because a mature repository might exist.

A whole solution is never automatically adopted. If its Authority, dependency, Windows, network, credential, maintenance, cost, rollback or removal burden is worse than the narrow custom/compose route, reject it explicitly and retain the lower-total-cost route.

WHOLE_SOLUTION_CHECK_FOR_HIGH_COMPLEXITY_SINGLE_SEAM = YES
SIMPLE_SINGLE_SEAM_WHOLE_SOLUTION_NONTRIGGER = YES

## 5. Prior-art discovery

Discovery is metadata-first.

Normally shortlist no more than 3 strong candidates per capability unless evidence shows the shortlist is insufficient.

Discovery must not automatically:
- clone repositories
- install dependencies
- import code
- grant network/filesystem permissions
- change Runtime architecture

Load only the narrow documentation/source needed to evaluate the selected capability.

## 5A. System-update radar and cumulative external evidence

External discovery may run continuously or periodically as metadata-only monitoring, but the monitoring surface is not Authority and is not an auto-updater.

SYSTEM_UPDATE_RADAR_ROLE =
DISCOVERY / CURRENTNESS / RISK / SIMPLIFICATION_INPUT_ONLY

It may observe multiple capability families and identify a material cross-layer composition opportunity when several individually modest upstream changes combine to alter the best route.

Examples of a material combined effect:

- product-shell + interoperability + developer-surface improvements jointly eliminate a custom bridge;
- thin-shell + updater + service primitives jointly eliminate custom launcher/update/service code;
- Project/Knowledge + RAG improvements jointly eliminate a planned custom Knowledge platform.

This Source defines what external evidence is relevant. The Process owner still decides material-trigger / successor-recheck semantics. Do not create a second feedback-counting or review engine here.

No mechanical event count, release count, star threshold or elapsed-time threshold may trigger adoption.

If combined evidence is insufficient to change REUSE / UPDATE / THIN_ADAPTER / COMPOSE / REPLACE / DELETE / DEFER, the correct result is silent NO_OP.

Monitoring must never automatically:

- install or upgrade a component;
- mutate Production;
- rotate credentials;
- change Authority;
- migrate schemas;
- promote a Candidate.

## 6. GitHub Candidate Comparison

When materially extending the product foundation, Runtime/development infrastructure, or a Pack, compare only the relevant mature external capabilities needed for the proven gap.

For each serious candidate, evaluate:

- primary capability focus
- notable strengths
- notable weaknesses
- what it does better than alternatives
- what it deliberately does not solve
- maturity/maintenance signals
- Windows compatibility, including clean-machine install and non-developer username/path；
- whether durable identity leaks absolute Windows paths, usernames, drive letters or install roots；
- whether direct-local operation exists without proxy/tunnel/relay；
- whether MCP/ACP/HTTP/CLI is merely transport or becomes unwanted Authority/identity；
- local filesystem scope confinement, blocked paths and symlink/path-escape behavior；
- API/CLI/library integration surface
- deterministic vs model-dependent behavior
- state/persistence model
- filesystem/network side effects
- license
- dependency/security surface
- integration cost
- replacement/removal cost
- authority conflicts
- best-fit use cases
- reasons not to adopt
- custom/planned code that can be deleted or avoided
- cross-layer composition effect
- upgrade / rollback / removal path
- build/release provenance and supply-chain implications when relevant
- privilege / credential / network expansion

Do not rank repositories only by stars or popularity.

The goal is to expose capability trade-offs, not to declare one repository universally “best.”

### 6A. Local Action Host / filesystem / interoperability donor review

When evaluating local coding/file/action projects, compare capability roles separately:
- filesystem primitives；
- workspace confinement；
- read/write/process/git/test actions；
- approval policy；
- session/job/evidence lifecycle；
- result return to the product shell；
- transport/interoperability surface；
- Windows install/update/rollback lifecycle.

Do not select a project merely because it exposes MCP. MCP, HTTP, CLI, stdio or ACP-like surfaces are integration choices. The product capability remains local project work and the executor must remain replaceable.

For a Windows-local shell and executor on the same machine, a donor's public tunnel/proxy/relay feature is not adopted unless a separate external-connectivity product requirement is explicitly approved. Internal product communication must remain direct-local.

DONOR_PUBLIC_TUNNEL_FEATURE_NE_REQUIRED_LOCAL_PRODUCT_ROUTE = YES
MCP_SUPPORT_CAN_BE_REQUIRED_WHILE_MCP_DEPENDENCY_IS_NOT = YES
MATURE_FILESYSTEM_PRIMITIVES_MAY_DELETE_CUSTOM_FILE_APIS = YES
MATURE_LOCAL_ACTION_HOST_MAY_DELETE_MULTIPLE_CUSTOM_SEAMS = YES

## 7. Creator Decision Brief

Before implementation, summarize the external landscape in creator-facing language.

The brief should answer:

1. What capabilities already exist externally?
2. Which project is strongest at each relevant capability?
3. What are the important trade-offs?
4. Which capabilities should remain Runtime-owned?
5. Which capabilities are still genuinely missing?
6. What could be combined to better match the creator’s goal?
7. What would each design cost in complexity, replaceability, and governance?

Avoid forcing the creator to choose between repository names without explaining the capability consequences.

## 8. Hybrid Design Options

When multiple projects have complementary strengths, provide normally 1–3 candidate compositions.

Example structure:

OPTION A — Minimal reuse
- external capability X
- Runtime-owned Y/Z
- lowest integration cost
- lower feature breadth

OPTION B — Balanced composition
- Project A for planning
- Project B for memory
- Runtime deterministic executor for facts
- Runtime authority/promotion
- moderate integration cost

OPTION C — Maximum external capability
- more sidecars/adapters
- highest breadth
- highest dependency/replacement cost

Each option must state:

- capability allocation
- Runtime-owned responsibilities
- external components
- expected benefits
- major weaknesses
- integration complexity
- authority/security concerns
- expected user/creator experience
- recommended conditions for choosing it

Hybrid design is an aid to creator thinking; it is not automatic approval to adopt dependencies.

## 9. Reuse modes

Allowed modes:

- NO_OP
- IDEA_ONLY
- REIMPLEMENT_PATTERN
- SKILL_REUSE
- THIN_ADAPTER
- COMPONENT_REUSE
- SIDECAR
- UPDATE_EXISTING_COMPONENT
- REPLACE_CUSTOM_CAPABILITY
- DELETE_PLANNED_CUSTOM
- COMPOSE
- FORK

Default preference:

NO_OP / DELETE_PLANNED_CUSTOM / IDEA_ONLY
→ UPDATE_EXISTING_COMPONENT / THIN_ADAPTER / REIMPLEMENT_PATTERN
→ COMPONENT_REUSE / SIDECAR / COMPOSE
→ FORK

`DELETE_PLANNED_CUSTOM` is a valid and preferred outcome when a mature upstream capability removes the need for a planned subsystem before implementation.

`REPLACE_CUSTOM_CAPABILITY` is preferred when a mature component safely absorbs an existing custom seam with lower total authority/dependency/maintenance cost.

FORK / WHOLESALE_ADOPTION requires separate architecture decision and explicit human approval.

Prefer reimplementation of a small pattern when adopting a large dependency would cost more than recreating the narrow capability.

## 10. Internal Contract first

Define Runtime-owned input/output contracts before integration.

External types, framework objects, provider-specific models, or repository-internal state must not leak into Pack schemas.

Conceptually:

Pack
→ Runtime Internal Contract
→ Adapter/Executor/Skill
→ External Component

External output enters Runtime as PROPOSAL/STAGING by default.

Third-party tools must not directly declare CANON, grant author approval, bypass Revision/SHA, perform Promotion, mutate authoritative state, or self-escalate privileges.

## 11. Deterministic-first integration

Use deterministic executors for machine-verifiable facts such as SHA, diff, manifests, schema validation, financial indicators, statistical calculations, data transformation and reproducible metrics.

Models may interpret or propose, but should not become fact authority when deterministic computation exists.

Test the Runtime contract boundary. Do not recreate the third-party project’s entire internal test suite.

## 12. External evaluation record

Each adopted/evaluated capability should record:

- capability
- repository/project
- exact commit/tag/release
- license
- Windows compatibility
- integration surface
- deterministic/model behavior
- side effects
- dependency/security surface
- authority conflict
- integration cost
- removal cost
- reuse mode
- decision

When required, persist:

EXTERNAL_REFERENCE_ASSESSMENT_<TASK_ID>.md

## 13. License / security / revision

EXTERNAL_REFERENCE_BINDS_EXACT_COMMIT_OR_TAG = YES
NO_FLOATING_MAIN_BRANCH_DEPENDENCY = YES
LICENSE_REVIEW_REQUIRED_BEFORE_CODE_REUSE = YES
SECURITY_REVIEW_REQUIRED_BEFORE_DEPENDENCY_ADOPTION = YES
NO_LICENSE_OR_UNCLEAR_LICENSE = IDEA_ONLY
MODEL_CANNOT_AUTO_IMPORT_EXTERNAL_CODE = YES
MODEL_CANNOT_AUTO_ADD_DEPENDENCY = YES
PRODUCTION_GITHUB_NETWORK_DEPENDENCY = NO

Code reuse, sidecar use, subprocess invocation, network-service use, modification and redistribution are separate decisions.

## 14. Complexity stop rule

Default to IDEA_ONLY / REIMPLEMENT_PATTERN / DO_NOT_ADOPT when:

- dependency tree is disproportionately heavy
- authority boundaries cannot be isolated
- Windows support is poor
- side effects cannot be constrained
- license is incompatible/unclear
- a small capability requires a large framework
- replacement/removal cost is excessive
- Adapter complexity exceeds reimplementation cost

Do not build a Generic Plugin Platform, Adapter Generator, GitHub Package Manager or similar subsystem merely because external reuse is planned.

AUTOMATE_ONLY_AFTER_FLOW_IS_PROVEN = YES

Only consider common integration infrastructure after at least 2–3 successful real integrations reveal stable repeated patterns.

## 15. Product / Runtime / Pack assembly examples

Developer Mode / self-development:
- compare current product-shell native tool/agent surface with the mature project-bound developer surface as whole-solution alternatives
- prefer the minimum surface that already provides project binding, task lifecycle, read-only/writable isolation and review
- deeper embedded MCP/Agent integration only after natural-use burden proves material gain
- project-bound external development connector before broad operator exposure
- versioned Developer Source Workspace
- Runtime-owned review / approval / promotion boundary
- installed Production never becomes the mutable source workspace

Novel Pack:
- external planning
- external story memory
- external drafting/revision
- Runtime-owned Source/Revision/SHA/Stage/Promotion

Stock Pack:
- external data source
- deterministic Runtime indicators/backtests
- model explanation
- Runtime-owned provenance/authority

Academic Pack:
- external literature/research/writing capability
- deterministic R/Python/SAS analysis
- Runtime-owned dataset/code/result/citation provenance

Examples are illustrative, not frozen choices.

## 16. Stop conditions

STOP and return to Controller if:

- Core authority must change without proof
- external types would leak into Pack schema
- license/security review is unresolved
- integration needs unapproved dependency/privilege
- selected reuse mode expands beyond task scope
- third-party component becomes production authority
- integration tooling costs more than the capability it enables

## 17. Post-adoption external update review

After an external component is adopted, its exact revision remains pinned and registered for lifecycle review.

Update discovery is metadata-first and governed by the current component/update owner. A newly released external version is not an automatic upgrade.

When a material update or material cross-layer update cluster is discovered, reassess only the affected capability families. The review should identify whether the update:

- removes custom Runtime/Pack/product code;
- deletes planned custom work before implementation;
- allows two or more adapters/components to collapse into one;
- provides a cleaner/stabler API, CLI, MCP/ACP-like or platform contract;
- reduces dependency, privilege, credential, network or side-effect surface;
- improves Windows support;
- improves deterministic behavior or reproducibility;
- improves performance/reliability materially;
- improves installer/update/rollback/service lifecycle;
- improves supply-chain provenance/security;
- resolves a security/license/maintenance risk;
- replaces an earlier workaround;
- changes/deprecates an interface used by the product;
- changes the best whole-product composition even if no single release alone would justify re-entry.

If useful, provide a System / External Update Decision Brief containing:

- WHAT_CHANGED
- AFFECTED_CAPABILITY
- CURRENT_COMPONENT_OR_CUSTOM_SEAM
- USER_PRODUCT_IMPACT
- WHAT_CAN_BE_DELETED_OR_SIMPLIFIED
- CROSS_LAYER_COMPOSITION_EFFECT
- COMPATIBILITY / WINDOWS IMPACT
- SECURITY / LICENSE / SUPPLY_CHAIN IMPACT
- MIGRATION / INTEGRATION / ROLLBACK COST
- EXACT_REENTRY_POINT
- recommended disposition

Normally choose only among relevant dispositions such as:

- KEEP_CURRENT
- UPDATE_CANDIDATE
- REPLACE_CUSTOM_CAPABILITY
- THIN_ADAPTER
- COMPOSE
- DELETE_PLANNED_CUSTOM
- DEFER

Do not notify merely because a version number changed when there is no material product/system impact.

External updates may trigger a new composition option when they materially change the best capability allocation, but Runtime-owned Authority / Artifact / Permission / Promotion / Audit boundaries remain unchanged.

## 18. Candidate disposition

This v0.7 is a full-replacement Candidate over the active v0.6 External Capability Assembly Authority.

It preserves the v0.6 cross-lifecycle scan, mature whole-solution route, planned-custom deletion value, update-radar boundary, narrow integration preference and explicit Promotion discipline. The only material addition is the high-complexity single-seam trigger in §4B.

Natural evidence motivating this Candidate:
- STOCK_DSA reported a single named CROSS_RUN_RESEARCH_STATE_DURABILITY_GAP, but the seam's required comparison spans persistence continuity, append-only/correction lineage, PIT immutability, concurrency/single-writer safety, crash recovery, idempotency, latest-state discovery, content hashes, rollback/PIT restore, IAM/secrets, privacy/rights, cost and future-consumer compatibility.
- The correct route was to block custom implementation until bounded whole-solution research, while keeping Qlib/model training/private Promotion deferred and forbidding a second database/scheduler/evaluator.
- This demonstrates that planned custom-surface count alone can understate foundation complexity.

What is not proven:
- that any specific SQLite/object-store replication tool is the correct STOCK_DSA solution;
- that every persistence seam is high-complexity;
- that this trigger will fire prospectively before user reminder in a fresh unrelated project;
- that the whole-solution route will always beat a narrow custom implementation.

Required natural regression before Promotion should include:
1. one fresh high-complexity single seam where whole-solution research triggers before custom authoring and before user reminder;
2. one simple single seam where the whole-solution check correctly remains off or bounded;
3. evidence that the trigger reduces planned custom lifecycle surface or avoids unnecessary glue without increasing user/maintenance burden materially.

Until explicit Promotion:

ACTIVE_STABLE_EXTERNAL_CAPABILITY_AUTHORITY = PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY_v0_6.md
CANDIDATE_AUTHORITY = NONE

PROMOTION_STATUS = NOT_PROMOTED
