# Universal Runtime｜Project Source｜Runtime Development Strategy v0.8

STATUS = PROJECT_SOURCE_STABLE
AUTHORITY_STATUS = ACTIVE_STABLE_AUTHORITY
REVISION_OF = PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_7.md
SUPERSEDES = PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_7.md
CANONICAL_SOURCE = PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_8.md
FULL_REPLACEMENT_SOURCE = YES
PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_USER_APPROVAL_2026_10_15
ACTIVE_STABLE_RUNTIME_DEVELOPMENT_STRATEGY_AUTHORITY = PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_8.md
PREVIOUS_STABLE_SOURCE_SHA256 = 65f704d52f7be1473dfe045924abcbae8c9280a2ddacb81b56c08835bd0fa439
MODEL_OUTPUT_IS_PROPOSAL_ONLY = NO
HISTORY_REWRITE = NO
CLASSIFICATION = RUNTIME_GENERAL
PREVIOUS_PROMOTED_STRATEGY_PRESERVED = YES
NO_SILENT_STABLE_SOURCE_MUTATION = YES

SEMANTIC_DELTA =
AIDES_PROJECT_COMPLETE_THEN_NATIVE_OPTIONAL_PACK_AUTHOR_THEN_WINDOWS_EXE
+ EXE_FRESH_INSTALL_NE_OLD_PROJECT_DATA_MIGRATION
+ EXTERNAL_CLOUD_SYNC_NOT_REQUIRED
+ OPTIONAL_PACK_CREATION_WITH_NO_GENERIC_FACTORY
+ POINT_OF_USE_USER_PURPOSE_ORDER_BINDING
+ PRESERVE_ACCEPTED_V0_7_IN_FULL
+ NATIVE_PROVIDER_USER_SCOPED_MODEL_CATALOG_COMPLETE_CHOICE
+ TRANSIENT_DISPLAY_PASS_NE_DURABLE_AVAILABILITY_PASS
+ MODEL_DISCOVERY_FAILURE_VISIBLE_AND_USER_SCOPED_FALLBACK
+ PROVIDER_NATIVE_CONSUMER_SOURCE_AND_REGRESSION_LINKAGE
+ PRESERVE_V0_6_ACCEPTED_STRATEGY
+ OPTIONAL_LOCAL_ACTION_PROVIDER_SELECTION
+ MCP_TRANSPORT_OPTIONAL_NOT_PROJECT_REQUIREMENT
+ CURRENT_PROVIDER_REPLACEABILITY_AND_SINGLE_SELECTION
+ LOCAL_ACTION_DONOR_COMPARISON_DIMENSIONS
+ BUILTIN_GUIDE_USER_SEMANTIC_SYNC
+ CURRENT_PRIORITY_REMOVED_FROM_STABLE_STRATEGY
+ ACCEPTED_BASELINE_INHERITANCE_ENGINEERING_DISCIPLINE
+ INVALIDATION_SCOPED_REGRESSION
+ PRESERVE_V0_2_STRATEGY
+ ANY_SUPPORTED_WINDOWS_RELEASE_TARGET
+ PATH_AGNOSTIC_INSTALL_AND_WORKSPACE_BINDING
+ FRESH_MACHINE_PORTABILITY_ACCEPTANCE
+ LOCAL_ACTION_CAPABILITY_FIRST_EXECUTOR_REPLACEABLE
+ LIBRECHAT_NATIVE_INTEROP_FIRST
+ MCP_OPTIONAL_TRANSPORT_REQUIRED_CAPABILITY
+ INTERNAL_PROXY_TUNNEL_FORBIDDEN
+ PORTABLE_SOURCE_ABSOLUTE_PATH_SCAN
+ NORMAL_USER_SHELL_JOURNEY_AND_REENTRY
+ FIRST_RUN_DAILY_USE_REPAIR_UPDATE_ROLLBACK_ACCEPTANCE
+ INFRASTRUCTURE_HIDDEN_FROM_NORMAL_USER

---

## 0. Purpose

本 Source 定义 Universal Runtime 的长期高效开发策略。

它服务于 Program North Star：

> Aides 以完整 Project 用户体验为第一产品目标，优先复用 LibreChat 原生能力；由现有 Runtime 治理支持用户创建、审核和按需安装/激活/停用/卸载 Pack，最后使用成熟 Windows 安装技术将产品封装为在任意受支持 Windows PC 上可全新安装的 EXE。安装到另一台 PC 不要求云同步，也不要求搬迁旧电脑的 Project 数据。

PROGRAM_PORTABILITY_TARGET = ANY_SUPPORTED_WINDOWS_PC
DEVELOPER_MACHINE_NE_RELEASE_IDENTITY = YES

本 Source 不拥有：

- 当前 Milestone / transient Build Status；
- user-visible product brand / naming authority；
- exact Chat rollover / FileDrop 行为；
- external capability 的详细 adoption 流程；
- 新 Pack 的详细创建流程；
- Pack update 的详细 lifecycle；
- 当前具体 executor/tool 名称。

这些由各自 owning Source / Project Instructions 负责。

---

# A. Development North Star

## A1. Program delivery order

开发必须区分：

1. SHARED PRODUCT FOUNDATION：WEB_R004 命名共享 Web/Desktop 产品底座能力族；是否为当前优先级由 Project Instructions / latest Handoff 决定；
2. RUNTIME AUTHORITY PLANE：Authority / Artifact / Permission / Project/Source/Memory / Pack / Job Pin / Promotion / Audit；
3. DOMAIN PACK PLANE：Novel / Academic / Regulatory / Market / Software Development 等领域应用；
4. DEVELOPMENT EXECUTION PLANE：由 Project Instructions / current policy 选择的本地/外部开发执行器。

用户确认的产品价值交付顺序（Milestone 优先序，**不是**自动改变当前 Stage 的证明上限）：

P1_PROJECT_COMPLETE_NORMAL_USER_JOURNEY
→ P2_LIBRECHAT_NATIVE_ADVANTAGES_COMPOSED_IN_THE_SAME_PROJECT_SHELL
→ P3_USER_CREATABLE_GOVERNED_OPTIONAL_PACK_CANDIDATE_AND_REPRESENTATIVE_INSTALL_ACTIVATE_DEACTIVATE_UNINSTALL
→ P4_PACKAGED_WINDOWS_EXE_FRESH_INSTALL_ANY_SUPPORTED_PC

- P1：Project 是身份与工作中心；在 LibreChat 中完成 New Project → New Chat → 指定/按策略调用同 Project 资料 → 回答来源可核验 → 保存 Source/Artifact → 再次打开；Instructions、History、Memory、Files、Archive/Delete、权限及当前本地数据持久性按实际用户消费者关闭。已接受的 PX/Human 基线继承，不重跑。
- P2：保持 LibreChat 现有模型入口、Agents、Skills、MCP、工具与连接器；仅对已证实的 Project 体验缺口采用 Runtime 或最薄适配。MCP 不是 Project 身份或普通 Project 使用前提。
- P3：使用已 Promotion 的 Pack Creation/Lifecycle 协议和 LibreChat 原生 Skills 支持用户创建可评估的 Pack Candidate；按独立消费者和正/负/留出证据验收，Promotion、Install、Activate、Deactivate、Uninstall、Update 各自独立且不自动发生；不新建通用 Pack Factory。零 Pack 项目始终可用。
- P4：以成熟、可替换的 Windows EXE/installer 路线封装同一 LibreChat Shell/Runtime，验证在不同受支持 Windows PC 的**全新安装、启动、新建 Project、使用可选 Packs、修复/更新/回滚/卸载**。普通用户不手动操作 Docker、PowerShell、MCP 或代理。
- **新机安装 ≠ 旧机数据迁移**：不要求云端文件平台、远程同步、用户旧 Project 导出、旧 Chat 转移或跨机恢复作为 EXE 首次安装前置条件。现有 Project 在当前电脑上的备份、安全恢复、更新后保留数据仍是相关消费者硬约束；跨电脑导入旧数据是独立可选用户能力。
- GitHub 是受 CI 与分支规则保护的产品源码发布面，不是用户 Project 存储或同步后端。
- P1–P4 是用户价值的执行排序，不把 P3 Pack 实例变成零 Pack Core EXE 的技术硬依赖；最终 Packless 安装包必须不捆绑任何可选用户 Pack 内容。

WEB_FOUNDATION_FIRST = YES
PROJECT_COMPLETE_USER_JOURNEY_FIRST = YES
NATIVE_LIBRECHAT_CAPABILITY_FIRST = YES
REPRESENTATIVE_OPTIONAL_PACK_CREATION_BEFORE_FINAL_EXE_PRIORITY = YES
FRESH_EXE_INSTALL_NE_OLD_PROJECT_MIGRATION = YES
CLOUD_SYNC_IS_NOT_PROGRAM_PREREQUISITE = YES
PACKLESS_CORE_REQUIRED = YES
PACK_FIXTURES_MAY_PRECEDE_WEB_BASELINE_FOR_ARCHITECTURE_PROOF = YES
LARGE_SCALE_PACK_EXPANSION_BEFORE_WEB_BASELINE = NO

当 current priority 位于 shared product foundation 时，用户可直接观察的产品改善是主要价值指标之一。
当 latest accepted route 已进入 Pack/domain expansion 后，Pack 的领域能力/科学有效性/工作流价值可以成为主要价值指标，即使公共壳本身没有每次都发生可见变化。

CURRENT_PROGRAM_PRIORITY_NE_STABLE_DEVELOPMENT_STRATEGY = YES

PRODUCT_VISIBLE_DELTA_FIRST_DURING_WEB_FOUNDATION = YES
PACK_DOMAIN_VALUE_FIRST_AFTER_PACK_LANE_ENTRY = YES
HARD_FLOORS_REMAIN_NON_BYPASS = YES

## A2. Runtime positioning

Universal Runtime 不是：

- 新的通用 Agent Framework；
- 新的模型 Provider Gateway；
- 新的分布式 Workflow Engine；
- 新的 Observability 平台；
- 新的 Package Manager；
- 新的完整 Chat / Project / Memory 产品壳。

Universal Runtime 是：

> Local AI Production Runtime / Authority Control Plane

它负责跨领域不变的运行宪法：

- Authority
- Artifact Identity
- Revision / SHA
- Permission
- Load Plan
- Job Pins
- Pack Contract
- Review Binding
- Approval
- Promotion
- Audit / Provenance
- Model Policy Authority

---

## A3. Canonical product-role strategy

Default platform strategy must preserve a Packless Core. User Packs are optional capabilities and must not be prerequisites for normal Chat/Project/File/Memory/MCP/Provider/Local-Action use.

CORE_PRODUCT = LIBRECHAT_CURRENT + RUNTIME_AUTHORITY + NATIVE_SHARED_CAPABILITIES  
PACKLESS_CORE_MODE_SUPPORTED = YES  
ALL_USER_PACKS_OPTIONAL = YES

Role rules:
- Project is the user workspace/context hub.
- Pack is an optional capability package; Universal and Domain Packs share the same installed lifecycle.
- Universal Pack is optional and contains only cross-domain methods that earned reuse; it must not duplicate native/shared infrastructure.
- Provider is model access. OpenAI-compatible gateways/providers should use LibreChat custom endpoints when sufficient; provider choice must not create a second shell or rewrite Project/Pack identity. A current provider example such as ChatAnywhere remains a point-of-use Provider decision, not Stable platform identity.
- Shell is the replaceable product interaction/delivery layer; current functional S1 remains the existing LibreChat-based entry until a formal shell gate proves material user gain.
- MCP is interoperability transport; Runtime remains Authority.

GENERAL_CHAT_SYSTEM_INTERNAL_SEMANTIC_OWNER_NE_UNIVERSAL_USER_PACK = YES  
PROVIDER_NE_SHELL = YES  
PROVIDER_NE_PACK = YES  
PACK_NE_CORE_PRODUCT = YES

Before material implementation, first ask whether the target belongs to Core, Project, Pack, Skill, Provider, Shell or evidence. If the role changed since the route was compiled, re-enter the Process/Architecture owner rather than patching the nearest Candidate.

# B. Strategy owner boundaries

避免把相同流程在多个 Source 中重复维护。

RUNTIME_DEVELOPMENT_STRATEGY_OWNS =
- platform delivery order;
- Runtime native vs reusable-infrastructure boundary at strategy level;
- model/cost/context strategy;
- Runtime update/version/migration strategy;
- Core freeze and deferred-complexity strategy.

DELEGATED_OWNERS =
- hard integrity floors → Runtime Hard Invariants;
- material-action route selection / Stop-Loss / user-burden / active closure → Process Improvement;
- external prior-art / license / reuse mode / component adoption → External Capability Assembly;
- new Pack creation → Pack Creation Protocol;
- Pack update / multi-Pack lifecycle → Pack Lifecycle & Update;
- rollover / user transition / result return → Handoff;
- exact current local executor preference → Project Instructions.

Do not duplicate their detailed checklists here.

---

# C. Reuse-first product and infrastructure strategy

Before material implementation of a product capability or infrastructure capability:

1. define the user/product/domain outcome;
2. check current primary product-shell upstream capability when UI/product-facing;
3. check existing Runtime / Pack capability inventory;
4. invoke External Capability Assembly when a material external gap remains;
5. prefer REUSE / UPDATE / THIN_ADAPTER / COMPOSE / NO_OP over custom subsystem;
6. custom build only when total cost and governance burden are lower.

UPSTREAM_CURRENTNESS_BEFORE_CUSTOM_PRODUCT_BUILD = YES
REUSE_BEFORE_REIMPLEMENT = YES
COMPOSE_BY_RUNTIME_CONTRACT = YES
GENERIC_AGENT_HARNESS_CUSTOM_BUILD = NO
GENERIC_CHAT_PROJECT_MEMORY_REIMPLEMENTATION = NO

The detailed route receipt and Stop-Loss mechanics are owned by the Process Improvement Source.

---

## C1. Cross-lifecycle reuse preflight

Before custom work in a shared product or EXE-lifecycle capability, perform a milestone-scoped currentness/reuse check across the affected product loop.

Relevant capability families include:

- product shell/workspace;
- developer execution / coding agent;
- tool/agent interoperability;
- Windows thin shell;
- installer / updater / distribution;
- local service/process lifecycle;
- dependency/update discovery;
- supply-chain scanning/provenance/signing;
- browser automation;
- Knowledge/RAG/Memory;
- diagnostics/observability;
- installed-app secret storage.

The objective is not to maximize dependencies. The objective is to minimize custom product/infrastructure surface while preserving Runtime Authority.

For each family ask:

1. Is the current product shell/platform already solving it?
2. Is a mature whole solution able to absorb several planned subcomponents?
3. What planned custom code can be deleted before implementation?
4. What existing glue/user steps can be retired?
5. What new privilege/network/credential/update burden would adoption introduce?
6. Can the external capability be replaced or rolled back without moving Authority out of Runtime?

CURRENT_PACKAGE_SELECTIONS_REMAIN_TRANSIENT = YES
MATURE_PLATFORM_PRIMITIVE_BEFORE_CUSTOM_INFRASTRUCTURE = YES
DELETE_PLANNED_CUSTOM_IS_VALID_OPTIMIZATION = YES

## C2. Accepted baseline inheritance / regression-scope engineering discipline

Engineering validation starts from the latest accepted baseline, not from zero.

For every bounded material delta:
1. bind exact mutation preimage/current config;
2. bind ALLOWED_CHANGE_SCOPE and PROTECTED_PASS_SET;
3. identify the proof dependencies touched by the delta;
4. run targeted correctness for the changed capability;
5. run the smallest protected regression whose dependency actually changed;
6. inherit unchanged accepted baselines at their recorded proof ceiling;
7. expand only when a shared dependency/currentness/permission/persistence/Authority change proves wider invalidation.

A new Chat, a newer supporting audit, or a desire for reassurance does not by itself require repeating Human/product acceptance.

HEALTH_OR_SHA_CURRENTNESS_NE_FULL_PRODUCT_REPLAY = YES
SAME_PROOF_FAMILY_REPEAT_NE_HIGHER_PROOF_CLASS = YES
BOUND_DELTA_REGRESSION_SCOPE_FOLLOWS_DEPENDENCIES = YES

Exact trigger semantics remain owned by Process; Handoff transports accepted baseline and revalidation scope. This Strategy only defines the engineering default so implementation/validation plans do not silently expand.

# D. Web foundation → Pack platform strategy

WEB_R004 is not a Pack. It is the shared interaction/product foundation through which Packs will later be exposed.

WEB_R004 responsibilities:

- Chat / history / streaming / restart;
- file/source intake UX;
- Projects / Memory / Library / Knowledge surface;
- Web/tool interaction surface;
- desktop daily-entry / thin-shell experience;
- Runtime governance seams;
- Pack entry and domain-mode presentation.

Pack responsibilities remain optional capability-specific. Normal Core use must not require a Pack. Domain Packs remain domain-specific; a Universal Pack is still optional and may contain only cross-domain methods whose reuse has been proven.

After Web baseline:

shared shell / Packless Core
→ Runtime job/permission/load-plan binding
→ zero or one Primary Pack for a Pack-governed Job by default
→ supporting capabilities/Packs only when proven necessary.

PACKLESS_CORE_BEFORE_PACK_EXPANSION = YES
ONE_PRIMARY_PACK_BEFORE_MULTI_PACK = YES
PACK_EXPANSION_MUST_REUSE_SHARED_PRODUCT_FOUNDATION = YES
WEB_PRODUCT_UX_MUST_NOT_BE_REIMPLEMENTED_PER_PACK_BY_DEFAULT = YES

## D1. Installed Product vs Developer Source Workspace

装好的 Inquiry Desk / Web/Desktop Production 与用于持续开发的 Source Workspace 必须分离。用户可以从产品 UI 发起开发请求，但 Production 不得直接修改自身当前安装文件。

推荐链路：

installed Product UI
→ current allowed development capability
→ versioned Developer Source Workspace
→ read-only inspection or isolated writable Candidate
→ tests / review / acceptance
→ explicit Promotion
→ side-by-side Production version update

PRODUCTION_INSTALL_NE_DEVELOPER_SOURCE_WORKSPACE = YES
PRODUCTION_SELF_EDIT = NO
DEVELOPER_SOURCE_WORKSPACE_VERSIONED = YES
DEVELOPER_MODE_READ_ONLY_FIRST = YES
WRITABLE_DEVELOPMENT_PREFERS_ISOLATED_WORKTREE_OR_EQUIVALENT = YES
TARGET_CHECKOUT_OR_PRODUCTION_MUTATION_REQUIRES_EXPLICIT_OWNER_ACCEPTANCE = YES
DEVELOPER_MODE_PREFERS_PROJECT_BOUND_CAPABILITY = YES
BROAD_OPERATOR_SURFACE_IS_NOT_DEFAULT_PRODUCT_INTEGRATION = YES

### D1.1 Developer Mode minimum product loop

Developer Mode 的第一目标不是“把 coding tools 塞进当前聊天页”，而是让用户以最低负担完成安全的自我开发闭环：

> Product UI / Desktop entry → project-bound development surface → versioned Source Workspace → read-only inspection → isolated writable Candidate when needed → deterministic tests/review → preview/acceptance → explicit Promotion → side-by-side Production update → rollback if needed

当成熟的 project-bound developer surface 已经同时提供项目绑定、任务生命周期、只读/可写隔离、review/acceptance 与本地 UI 时，默认先证明该 whole-solution baseline；不得仅为了“看起来更内嵌”就先建设自定义 MCP bridge / Tool Router / coding UI。

DEDICATED_MATURE_DEVELOPER_SURFACE_CAN_PRECEDE_EMBEDDED_MCP = YES
EMBEDDED_DEVELOPER_INTEGRATION_REQUIRES_PROVEN_USER_BURDEN_GAIN = YES
MATURE_WHOLE_SOLUTION_MAY_DELETE_CUSTOM_PROTOCOL_GLUE = YES
SELF_DEVELOPMENT_LOOP_MUST_INCLUDE_PREVIEW_PROMOTION_ROLLBACK = YES

更深的 product-shell-native MCP/Agent 集成只有在自然使用证明独立 developer surface 带来材料级上下文切换或用户负担时才升级；升级时仍必须保留 project-bound、least-privilege、read-only-first 与 isolated writable workspace 边界。

开发执行器可以由产品壳通过成熟 Tool/MCP/Connector 能力调用，但具体 executor/tool 名称仍由 Project Instructions 与 current external-capability decision 负责；本 Strategy 不固定 vendor-specific transport。

---

## D2. S1 Thin Desktop Shell strategy

S1 must remain a thin product entry around the current Web product shell, not a second desktop application stack.

Before implementing desktop lifecycle behavior, prefer a mature Windows-compatible shell/platform that already supplies native primitives such as:

- WebView-based embedding when appropriate;
- window lifecycle and state restore;
- tray;
- single instance;
- autostart;
- deep links;
- notifications;
- bounded shell/process integration;
- capability/permission scoping;
- secure local storage primitives where mature.

S1 should custom-build only the genuine remaining product gap, such as Runtime health/launch coordination that cannot be safely delegated.

S1_MUST_NOT_REIMPLEMENT_LIBRECHAT_UI = YES
S1_MATURE_DESKTOP_PRIMITIVES_FIRST = YES
CUSTOM_TRAY_AUTOSTART_SINGLE_INSTANCE_DEEP_LINK_FRAMEWORK_BY_DEFAULT = NO

At S1 entry, re-check upstream currentness. A framework selected earlier is not permanently privileged.

### D2A. Normal-user shell journey and current-baseline preservation

Shell work is accepted by the user journey it removes, not by merely producing an EXE or opening a WebView.

Target normal flow:

one desktop/Start-menu action
→ product performs prerequisite and service health handling
→ focus an existing product window or open one window
→ restore valid authentication, Project and local UI state
→ user starts/continues work without terminal or infrastructure configuration.

The normal surface must not require the user to understand or manually operate PowerShell, ports, Docker/container topology, MCP servers, Local Action executor names, Runtime component names or internal proxy routes. Advanced/Developer surfaces may expose those details when they are the actual task.

SHELL_DAILY_ENTRY_USER_ACTION_TARGET = ONE
SHELL_EXISTING_WINDOW_FOCUS_REQUIRED_WHEN_SUPPORTED = YES
SHELL_LOGIN_SESSION_CONTINUITY_REQUIRED = YES
SHELL_INTERNAL_INFRASTRUCTURE_HIDDEN_BY_DEFAULT = YES
SHELL_REPAIR_MUST_PRESERVE_USER_DATA = YES
SHELL_FAILURE_MUST_RETURN_ONE_ACTIONABLE_RECOVERY_PATH = YES

A proven functional thin-shell baseline is preserved until a material user gap justifies native packaging work. Native EXE re-entry may be triggered by second-machine deployment burden or a proven need for single-instance/window-state, tray/autostart, deep-link/file association, native notification, sidecar/service lifecycle, signed install/update, repair or rollback. Aesthetic preference alone is not sufficient.

FUNCTIONAL_THIN_SHELL_BASELINE_BEFORE_NATIVE_REWRITE = YES
NATIVE_SHELL_REENTRY_REQUIRES_MATERIAL_USER_OR_LIFECYCLE_GAP = YES
CURRENT_SHELL_IMPLEMENTATION_REMAINS_TRANSIENT_NOT_STABLE_AUTHORITY = YES

## D3. S2 Installer / Update / Distribution strategy

S2 is a product-lifecycle capability, not a request to build a package manager or updater engine.

At S2 entry, compare mature Windows-compatible whole-solution routes for:

- installer;
- signed package/binary delivery;
- update discovery;
- staged download;
- delta/full update where useful;
- repair;
- rollback;
- distribution channel;
- portable mode if the user/product actually needs it；
- install-root independence；
- different Windows username / user profile；
- different drive or workspace location；
- machine-local workspace rebind/autodiscovery；
- no developer-machine absolute path in portable source/config/manifests.

Select one primary lifecycle route by default. Do not stack multiple updaters/installers over the same fact class without a proven need.

CUSTOM_INSTALLER_ENGINE_BY_DEFAULT = NO
CUSTOM_UPDATER_ENGINE_BY_DEFAULT = NO
CUSTOM_DELTA_PATCHER_BY_DEFAULT = NO
ONE_PRIMARY_PRODUCT_LIFECYCLE_ROUTE_BY_DEFAULT = YES
ANY_SUPPORTED_WINDOWS_PC_RELEASE_ACCEPTANCE_REQUIRED = YES
PORTABLE_PRODUCT_SOURCE_MUST_BE_PATH_AGNOSTIC = YES
INSTALL_ROOT_NE_PROJECT_IDENTITY = YES
FRESH_MACHINE_ACCEPTANCE_REQUIRES_DIFFERENT_USERNAME_AND_LOCATION = YES
FINAL_USER_INSTALL_MUST_NOT_REQUIRE_PROJECT_SPECIFIC_MANUAL_DOCKER_MCP_PROXY_OR_EXECUTOR_SETUP = YES
S2_MUST_REEVALUATE_DOCKER_DESKTOP_OR_CONTAINER_RUNTIME_DEPENDENCY = YES
FRESH_EXE_ON_ANOTHER_SUPPORTED_PC_REQUIREMENT = YES
CROSS_PC_OLD_PROJECT_DATA_TRANSFER_IS_EXE_RELEASE_BLOCKER = NO
EXTERNAL_CLOUD_FILE_OR_SYNC_SERVICE_REQUIRED_FOR_LOCAL_PROJECT = NO
OPTIONAL_EXTERNAL_PROVIDER_OR_CONNECTOR_NETWORK_NE_INTERNAL_CLOUD_DEPENDENCY = YES


Runtime retains Promotion legality. External update tooling may discover/download/test a Candidate, but may not own Production Promotion.

### D3A. Any-supported-Windows portability and machine-local resolution strategy

Release/installer work must treat current developer-machine paths as fixtures, never product identity.

Preferred durable contract:
`Project logical workspace binding` → `machine-local resolver` → `effective Windows root` → `current Local Action Host`.

Durable Project/export state must not require:
- a developer-specific absolute user-profile path；
- a specific drive letter；
- a developer checkout/install root；
- a raw Local Action provider project/session id；
- a raw MCP server/tool id.

Machine-local state may contain those values as deployment resolution. On a new supported Windows PC, the resolver should prefer machine-locatable defaults/known install metadata, then a one-time bounded user folder bind only when necessary. Do not ask the user to transcribe paths the machine can locate.

Before release Candidate acceptance, scan portable source/config/manifests for developer-machine absolute paths. Explicit machine-local receipts, generated staging launch scripts and current request snapshots are excluded from portable identity but must not be shipped as canonical portable config.

ABSOLUTE_PATH_LEAK_IN_PORTABLE_SOURCE = BLOCK
MACHINE_LOCAL_GENERATED_STATE_MAY_USE_EFFECTIVE_ABSOLUTE_PATH = YES
PORTABILITY_REBIND_MUST_NOT_REWRITE_PROJECT_IDENTITY = YES

### D3B. Installer, first-run, repair, update, rollback and uninstall user journey

S2 selection must compare complete mature Windows lifecycle routes, not isolated installer formats. Tauri/WebView2, MSIX/App Installer/WinGet, Velopack or another mature route are comparators; no repository or format is preselected by this Strategy.

The selected route must minimize ordinary-user work and prove:
- no developer checkout, username, drive letter or install-root identity;
- no manual PowerShell, Docker, MCP, proxy/tunnel or executor configuration;
- product-managed prerequisite/service startup and bounded repair;
- local product launch without Internet, with provider/network failure reported separately;
- authentication and Project/user-data continuity across restart/update;
- code/data/source-workspace separation;
- candidate-first update with explicit material approval and exact rollback;
- repair that does not silently reset Mongo/Project/Library/Memory/user data;
- uninstall that distinguishes removing product code from retaining/removing user data;
- machine-local workspace rebind/autodiscovery without Project identity rewrite;
- one copyable diagnostic/repair path when automatic recovery cannot complete.

FIRST_RUN_MUST_NOT_REQUIRE_DEVELOPER_KNOWLEDGE = YES
DAILY_USE_MUST_NOT_REQUIRE_ADMINISTRATIVE_INFRASTRUCTURE_STEPS = YES
LOCAL_PRODUCT_START_NE_PROVIDER_NETWORK_SUCCESS = YES
UPDATE_MUST_PRESERVE_AUTHENTICATION_PROJECT_AND_USER_DATA = YES
ROLLBACK_MUST_RESTORE_PRODUCT_VERSION_WITHOUT_HISTORY_REWRITE = YES
UNINSTALL_DATA_RETENTION_CHOICE_REQUIRED = YES

Release acceptance must include at least:
1. clean install on a fresh supported Windows profile with different username/location;
2. repeat launch and existing-window behavior;
3. reboot/re-entry when autostart is supported/enabled;
4. provider outage while local shell/history remain usable;
5. one component failure followed by bounded repair;
6. update Candidate, accepted Promotion and exact rollback;
7. workspace rebind/autodiscovery;
8. uninstall/repair data-retention semantics.

COMPONENT_HEALTH_PASS_NE_NORMAL_USER_PRODUCT_PASS = YES
FRESH_MACHINE_USER_JOURNEY_ACCEPTANCE_REQUIRED = YES

### D3C. Provider plane and ChatAnywhere / OpenAI-compatible gateways

Model providers and API gateways are Provider-plane integrations, not product shells, Packs or Project identity. When the current primary shell supports an OpenAI-compatible custom endpoint, use that native endpoint surface before building a custom provider gateway.

Currentness route:
`LibreChat native/custom endpoint → user/provider profile → model/profile capability check → only then thin adapter if a material incompatibility remains.`

ChatAnywhere is a current optional provider example only; availability, model list, pricing and endpoint details are transient/currentness facts and must not become durable Runtime or Project identity.

CHATANYWHERE_ROLE = OPTIONAL_PROVIDER_EXAMPLE  
CHATANYWHERE_SECOND_SHELL = NO  
CUSTOM_PROVIDER_GATEWAY_BY_DEFAULT = NO  
PROVIDER_SWITCH_MUST_NOT_REWRITE_PROJECT_OR_PACK_IDENTITY = YES

### D3C-1. Native Provider catalogue and durable manual-choice contract

This is a **Provider-plane user-experience contract**, not a list of model names, prices, credentials, URLs, runtime ports, current failures, or ephemeral product status. Those facts remain in the current Build Status / exact product release evidence.

- **Full authorized choice, not a Product-imposed subset.** In normal use, the native shell must make all models actually returned as authorized **and compatible** for the current user/provider profile available for manual selection. The Product must not silently narrow a successfully retrieved catalogue to a single fallback, pin an undisclosed model, or substitute a Provider without user direction. Native provider capability restrictions and actual account entitlements remain binding; public marketing lists are not proof of account access.
- **Native credential and currentness boundary.** Prefer the existing shell's `user_provided` encrypted user-credential path and authenticated native model-discovery consumer. Do not print/read/extract/copy keys, cookies or tokens for catalogue verification; do not run paid inference to validate catalogue display. Any metadata discovery must preserve per-user isolation, authorization and credential-revocation semantics.
- **Failure is not a whitelist.** Dynamic discovery, fallback defaults and short-lived caches are distinct. A `fetch=true` setting or one screenshot of a populated menu is not evidence of durable discovery. On provider timeout/failure, show an accurate degraded state; do not represent one default entry as the complete model inventory. Reuse native per-user, validity-scoped last-known-good metadata only if provenance, user binding, expiry and revocation are proven; otherwise retain safe verified defaults with a visible limitation, not invented entries or a cross-user shared cache.
- **The affected proof is a complete native consumer journey.** For any promoted change to endpoint config, model-fetch logic, auth/cache, native egress or selector, preserve the accepted Packless/Project/other-provider baseline and recheck only invalidated proof families: (a) authorized catalogue identity/extent, (b) native menu selectable IDs and manual choice without charged generation, (c) timeout/reload/reauth recovery, (d) no cross-account leakage or stale unauthorized entries. `PASS_DISPLAY` at a single moment is narrow proof and cannot certify complete availability or future recovery.
- **Root-fix source ownership.** Before calling the issue closed, bind the exact deployed LibreChat source/config/mount to its reviewed, licensed **source-controlled** template/patch and regression consumer. A public Runtime source-only Git tree or Handoff/route-graph update is not equivalent to deployed shell configuration, an executable regression, a Production adoption, or GitHub sync. Promotion and repository publication remain separate authorized effects after consumer PASS; no second model router, shell, proxy/tunnel, data store or broad baseline replay.
- **Repeated known failure:** when an already accepted model-choice journey regresses, the existing Process Stop-Loss and point-of-use action compiler must first compare its **last accepted positive** with the current negative at the actual model-discovery/user-menu consumer. Do not spawn an equivalent C8-R00x diagnostic chain or update unrelated Sources. If the previous success was only display-scoped, retain it at that ceiling and return one complete bounded native-fix-or-defer action.

USER_MANUAL_AUTHORIZED_MODEL_CHOICE_REQUIRED = YES  
ONE_TIME_VISIBLE_MODEL_MENU_NE_DURABLE_PROVIDER_ACCEPTANCE = YES  
FAILED_MODEL_DISCOVERY_NE_COMPLETE_PROVIDER_CATALOG = YES  
DYNAMIC_FALLBACK_NE_PRODUCT_WHITELIST = YES  
NATIVE_PROVIDER_CONSUMER_AND_RELEVANT_RELEASE_REGRESSION_REQUIRED = YES  
PROVIDER_METADATA_AND_CURRENT_FAILURE_NE_STABLE_SOURCE = YES  

## D4. Tool / agent / browser interoperability strategy

Prefer mature interoperable tool/agent protocols and shell-native integrations over a project-specific generic router or protocol.

For tool capabilities:
PRODUCT_SHELL_NATIVE
→ MATURE TOOL INTEROP
→ THIN_ADAPTER
→ ONLY THEN CUSTOM TOOL PROTOCOL

For coding agents:
CURRENT_PROJECT_BOUND_EXECUTOR
→ MATURE AGENT INTEROP / REPLACEABLE AGENT SURFACE
→ ONLY THEN CUSTOM INTEGRATION GAP

For browser automation:
PRODUCT_SHELL / MATURE ACCESSIBILITY_OR_PROTOCOL_BASED_BROWSER_AUTOMATION
→ THIN TOOL INTEGRATION
→ ONLY THEN CUSTOM BROWSER AGENT

GENERIC_TOOL_ROUTER_CUSTOM_BUILD = NO
GENERIC_AGENT_PROTOCOL_CUSTOM_BUILD = NO
CUSTOM_BROWSER_AGENT_BY_DEFAULT = NO

For local project work, local action is optional and trigger-scoped:

TASK_REQUIRES_LOCAL_CANONICAL_WORK?
→ NO: remain in Project/Core shell; do not invoke a Local Action provider.
→ YES:
  PRODUCT_SHELL_NATIVE_LOCAL_CAPABILITY
  → CURRENT_SELECTED_PROJECT_BOUND_LOCAL_ACTION_PROVIDER
  → IF MATERIAL GAP/REPLACEMENT OPPORTUNITY EXISTS: compare mature provider alternatives
  → MATURE INTEROP (native connector / MCP / HTTP / CLI / STDIO / ACP-like)
  → THIN_ADAPTER
  → ONLY THEN NARROW_CUSTOM_GAP

The Local Action provider class is replaceable. Do not treat the current selected implementation as permanent Product/Project identity. Do not keep multiple equivalent providers active in parallel by default; select one minimum-sufficient route per current task/workspace, with an explicit replacement seam.

When a material provider re-evaluation is triggered, compare at least:
- Windows/current-shell compatibility;
- direct-local operation without internal proxy/tunnel dependency;
- logical workspace binding and machine-local resolution;
- filesystem confinement, blocked paths and path-escape/symlink safety;
- read/write/exact-edit/search/process/git/test primitives;
- approval/effect boundary;
- session/job/outcome-unknown recovery and idempotency;
- result return to the same Project Chat;
- attachment/artifact transfer;
- credential/secret boundary;
- install/update/rollback/removal burden;
- maintenance surface and upstream currentness;
- what current custom glue can be deleted.

Concrete projects are transient donor/provider candidates owned by External Capability currentness, not Stable Strategy. A provider that is excellent for ChatGPT web through a public tunnel may still be a poor internal same-machine route if it requires a tunnel; its direct-local mode may remain a valid candidate.

MCP_INTEROPERABILITY_CAPABILITY_SUPPORTED = YES
PROJECT_MCP_REQUIRED = NO
MCP_REQUIRED_FOR_LOCAL_WORK = NO
MCP_PREFERS_LIBRECHAT_NATIVE_CAPABILITY_WHEN_USED = YES
CURRENT_LOCAL_ACTION_PROVIDER_IS_REPLACEABLE = YES
CURRENT_LOCAL_ACTION_PROVIDER_NE_STABLE_PROJECT_IDENTITY = YES
PARALLEL_EQUIVALENT_LOCAL_ACTION_STACKS_BY_DEFAULT = NO
INTERNAL_PROXY_OR_TUNNEL_DEPENDENCY = FORBIDDEN
INTERNAL_LOCAL_COMPONENTS_USE_DIRECT_LOOPBACK_OR_HOST_BRIDGE = YES
WHOLE_DRIVE_DOCKER_MOUNT_BY_DEFAULT = FORBIDDEN
CONTAINER_RUNTIME_NE_PRODUCT_IDENTITY = YES

## D4A. Built-in guide currentness strategy

The built-in user guide/manual must track promoted user-facing semantics, not internal implementation churn.

On a material user-facing Stable Source/Project-Instructions semantic change:
1. compare the current guide against affected semantics only;
2. update the smallest affected guide section;
3. keep Project Core vs optional capability roles explicit;
4. never freeze current ports/SHA/container/session/provider-specific Local Action identity into the guide;
5. validate that the guide still describes a zero-Pack/zero-Agent/zero-MCP/zero-Local-Action Project baseline correctly.

Internal-only engineering changes with no user-facing semantic delta are guide NO_OP.

BUILTIN_GUIDE_CURRENTNESS_CHECK_ON_USER_SEMANTIC_DELTA = YES
BUILTIN_GUIDE_FULL_REWRITE_BY_DEFAULT = NO
BUILTIN_GUIDE_TRANSIENT_STATE = NO
BUILTIN_GUIDE_MUST_NOT_MAKE_OPTIONAL_CAPABILITY_MANDATORY = YES

## D5. Installed secret and diagnostics strategy

Development-time plaintext environment configuration must not silently become the permanent installed-product credential strategy.

When S1/S2 product packaging is mature enough to justify migration, re-evaluate mature OS/platform-managed secure secret storage.

Secret migration must be Candidate-first, rollbackable, and must not silently rotate credentials.

INSTALLED_SECRET_STORAGE_RECHECK_AT_S1_S2 = YES
SECRET_MIGRATION_NE_SILENT_ROTATION = YES

For diagnostics:

PRODUCT_SHELL_NATIVE_TRACE / HEALTH / RUM
→ RUNTIME EXISTING AUDIT/HEALTH
→ MATURE STANDARD OBSERVABILITY ONLY IF REAL DISTRIBUTED_SUPPORT_BURDEN EXISTS
→ NO CUSTOM OBSERVABILITY PLATFORM

# E. Token / Cost / Latency Optimization Strategy

## E1. 优先级

Token 优化不能只理解为“换便宜模型”。

总成本应理解为：

> 调用次数 × 输入 Token × 输出 Token × 模型价格  
> + escalation / retry / tool / latency cost

因此优化优先级是：

1. 不需要模型 → 不调用模型
2. Discovery metadata-only
3. Scope before load
4. Narrow Load Plan
5. Deterministic preprocessing first
6. SHA cache / unchanged result reuse
7. Incremental diff instead of full reload
8. Output budget
9. Lowest sufficient Model Profile
10. Escalate only when quality/risk evidence requires it

## E2. No-model First

以下任务默认不得调用模型，除非明确证明 deterministic executor 不足：

- SHA / hashing
- revision / version comparison
- schema validation
- permission validation
- exact diff
- file identity
- deterministic parsing
- numerical calculation
- statistical reproduction
- technical indicators
- known-format extraction
- cache lookup
- no-op detection

NO_OP_MUST_NOT_CALL_MODEL = YES。

## E3. Context Minimization

模型上下文构建遵守：

- metadata discovery first
- exact scope selection
- load only relevant source sections
- unchanged artifacts reuse by SHA
- do not repeatedly send stable full documents
- use incremental material diff when valid
- source-critical tasks不得用不可追溯的 lossy summary 替代原始 Authority Source
- 若必须压缩上下文，压缩产物也必须有 Artifact identity / SHA / provenance，并明确其非 Source Authority

---

# F. Task Difficulty and Model Fit

## F1. 不使用单一“难度分数”作为长期合同

任务选择模型不应只依赖：

> difficulty = 7 / 10

更合理的是 Runtime-owned `TaskRequirement` / `TaskComplexityVector`。

推荐维度：

- reasoning_depth
- ambiguity
- cross_source_dependency
- context_requirement
- output_length
- structured_output_requirement
- tool_requirement
- citation_requirement
- domain_specialization
- code_requirement
- numerical_requirement
- multilingual_requirement
- latency_target
- cost_budget
- risk_level
- quality_floor

Pack 只声明能力要求，不声明具体 Provider / Model。

## F2. Model Fit 不只看“强弱”

Runtime 必须考虑模型与任务的匹配度：

- 推理能力
- 长上下文稳定性
- 结构化输出可靠性
- 代码能力
- 数学/统计能力
- 长文写作能力
- 审核/批判能力
- 多语言能力
- 工具调用能力
- 视觉能力（如任务需要）
- 延迟
- Token 价格
- Provider 可用性
- 数据/隐私约束

因此“更强模型”不一定是“更适合模型”。

---

# G. Model Policy v0 — Deterministic First

## G1. Pack 请求 Profile，不请求 Provider / Model

Pack 合同应类似：

- NO_MODEL
- extract_fast
- balanced
- reason_high
- audit_high
- write_long

这些是逻辑 Profile。

Pack 不得写死：

- DeepSeek 某型号
- GPT 某型号
- Claude 某型号
- 任何未来 Provider 型号

## G2. ModelPolicy

第一版 Model Policy 必须 deterministic。

输入：

- TaskRequirement
- Pack requirement
- Job risk floor
- Job cost budget
- Job latency target
- allowed providers
- allowed capabilities
- pinned policy revision

输出：

- selected logical Model Profile
- selection reason
- minimum capability floor
- escalation rules
- policy revision

不允许第一版为了“智能”再调用一个 classifier model。

## G3. 推荐 Profile 层级

示例：

Tier 0 = NO_MODEL  
Tier 1 = FAST / EXTRACT  
Tier 2 = BALANCED  
Tier 3 = HIGH_REASONING  
Tier 4 = HIGH_RISK_AUDIT  
Specialized = LONG_WRITE / CODE / VISION / DOMAIN_SPECIALIST

Tier 不是 Provider 型号，只是能力合同。

## G4. 最低充分模型

选择原则：

> 在满足 quality floor、risk floor、context/tool requirements 的所有 Profile 中，选择预期总成本最低的合法 Profile。

不是：

> 永远选择最便宜模型。

也不是：

> 永远选择最强模型。

---

# H. Escalation Strategy

推荐运行链：

Task  
→ deterministic executor sufficient?  
→ YES: NO_MODEL  
→ NO: select lowest sufficient profile  
→ execute  
→ deterministic / quality gate  
→ PASS: complete  
→ uncertainty / quality failure / risk condition  
→ escalate one level  
→ new result / review

禁止：

- 无证据直接升级到最强模型；
- 弱模型失败后无限 retry；
- 使用更强模型绕过缺失 Source / Permission / Approval；
- 模型自己决定提高权限；
- 因成本原因低于风险最低能力要求。

---

# I. Model Update and Provider Update Lifecycle

## I1. Model 更新不能静默改变运行 Job

模型、Provider、Profile mapping 都属于可变基础设施。

因此 Job 必须至少可审计地绑定：

- model_policy_revision
- selected_model_profile
- model_profile_revision
- resolved_provider
- resolved_model identifier/version when available
- key generation parameters relevant to reproducibility
- execution timestamp
- fallback/escalation evidence

Running Job 默认不得因 Profile mapping 更新而偷偷切换模型。

## I2. New Model / New Version

新模型或模型新版本采用：

1. Discovery
2. Candidate Model Entry
3. capability metadata
4. license / terms / data-flow / security review（按需要）
5. representative fixture benchmark
6. quality / cost / latency / structured-output evaluation
7. Pack-specific regression where material
8. Staging Profile Mapping Candidate
9. explicit Promotion
10. new Jobs adopt promoted revision

不得：

- 自动替换运行 Job；
- 仅因 Benchmark 高就自动升级；
- 仅因价格低就降低 risk floor；
- 让 Provider alias 静默解析到未经验证的新模型。

## I3. Existing Job Upgrade

运行 Job 若需要切换到新 Model Policy / Profile Revision：

- explicit upgrade request
- impact brief
- exact old/new revision binding
- compatibility review
- affected artifact/review invalidation analysis
- explicit approval when material
- new Job revision / controlled reopen

不得 silent rebind。

## I4. Emergency Deprecation

如果旧模型因安全、Provider 下线或不可用必须停止：

默认：

> fail closed + required migration interface

只有 Job Policy 已提前批准等价或更高能力 fallback set 时，才允许自动 fallback。

每次 fallback 都必须进入 Audit。

---

# J. Model Capability Registry

Runtime 应区分：

1. `ModelProfile`：逻辑能力合同
2. `ModelProfileRevision`：稳定可 pin 的 Profile 版本
3. `ModelCandidate`：待验证的新 Provider/Model 映射
4. `ResolvedModelExecution`：某次任务实际调用了什么

Pack 只看到 1。

Job Pin 绑定 2。

Runtime Adapter 解析 3 → 4。

这样模型更新不会污染 Pack Schema。

---

# K. Adaptive Routing — Deferred

只有满足以下条件后，才允许引入 adaptive routing：

- 已积累足够真实 Job telemetry；
- 已有稳定 TaskRequirement schema；
- 已有 deterministic baseline policy；
- 已有 quality gate；
- 已有 cost / token / latency observability；
- 已有 Pack-specific regression fixtures；
- 已证明 adaptive router 的收益高于复杂度。

未来 adaptive router 可以复用成熟项目，但 Runtime 必须继续拥有：

- risk floor
- quality floor
- allowed profile set
- policy revision
- final selection legality

Adaptive Router output = proposal only。

不得成为 Authority。

---

# L. External Infrastructure Composition

未来可考虑的能力类别：

- Model Gateway / Router
- Durable Execution
- Observability
- Retrieval / Vector DB
- Parser / OCR
- Domain data adapter
- Windows thin-shell primitives
- installer / updater / distribution
- local service/process wrapper
- dependency/update discovery
- supply-chain scan / SBOM / provenance / signing
- browser automation
- installed-app secret storage

这些类别默认先比较成熟 whole solution / platform primitive。只有真实缺口才进入 custom implementation。

但全部必须：

External Capability  
→ Runtime Contract  
→ Adapter / Executor / Sidecar  
→ fixture / regression  
→ staging  
→ promotion

不得把具体外部项目名称写进长期 Runtime Hard Invariants。

---

# M. Runtime Update and Versioned Component Lifecycle

## M1. Runtime 自身也必须是可版本化组件

Runtime 是 Authority Owner，因此 Runtime 自身升级的治理强度必须高于普通 Pack / Model 更新。

Runtime 更新不得等价于“覆盖安装新文件”。推荐长期语义：

> Discover → Candidate Runtime → Compatibility / Migration Analysis → Staging → Core Regression → Representative Pack Regression（material change 时）→ Explicit Approval → Promotion → New Jobs Adopt

Running Job 不得因 Runtime 新版本出现而静默重绑定。

Job 应逐步具备可审计的 Runtime 绑定：

- runtime_version
- runtime_contract_revision
- runtime_schema_revision（如适用）
- runtime_update_policy_revision（如适用）

并与以下 Pins 一起形成完整 Job Execution Identity：

- primary Pack / Pack version / Pack manifest SHA
- Workflow / Rule / Schema revisions
- Adapter / Executor revisions
- Model Policy / Model Profile revisions
- Permission Plan revision

## M2. Code Version 与 Authoritative Data 分离

Windows 本地长期部署优先采用 side-by-side version layout，而不是覆盖历史版本。

推荐原则：

- Runtime code version 与 authoritative data 分离；
- installed Production 与 Developer Source Workspace 分离；
- 新 Runtime 先以 candidate/staging 版本并存；
- Promotion 后只切换默认新 Job 使用的 Runtime；
- 旧 Runtime 版本保留以支持 rollback / audit / controlled reopen；
- 不得因升级而直接覆盖 Artifact / Job / Audit history。

`SIDE_BY_SIDE_RUNTIME_INSTALLATION` 是推荐实现模式，不要求当前阶段立刻开发完整 Updater。

## M3. Runtime Update Classification

Runtime 更新至少区分：

### PATCH

Bug / security fix，Authority Contract 不变。

最低 Gate：targeted deterministic regression + native product regression。

### MINOR

新增兼容能力，既有 Authority Contract 保持兼容。

最低 Gate：Core regression；若影响公共 Pack contract，增加 representative Pack regression。

### CONTRACT CHANGE

Artifact / Job / Permission / Pack / ModelPolicy / Schema 等 contract 改变。

必须：

- migration design
- backward compatibility analysis
- old/new exact revision binding
- migration fixture
- representative regression
- explicit approval

### MAJOR

Authority semantics、Persistence semantics、Job lifecycle、substrate boundary 等重大改变。

必须：

- independent architecture decision
- staged candidate
- migration rehearsal
- rollback plan
- representative Pack regression
- explicit human approval

不得自动 Promotion。

## M4. Authority Schema Migration

Migration 不得被视为对旧 Authority 的静默修改。

正确语义：

> old authoritative state → deterministic migration → new revision candidate → validation → migration receipt → commit

Migration evidence 至少应绑定：

- source schema / contract revision
- target schema / contract revision
- source Artifact / Job revision + SHA
- target revision + SHA
- migration implementation revision
- migration result
- timestamp / provenance

旧 Authority 必须保留。

因此：

`MIGRATION_NE_MUTATION = YES`

## M5. Running Job Runtime Pin

默认：

- 新 Job 使用当前已 Promotion 的 Runtime revision；
- Running Job 继续使用创建时的 Runtime contract/version binding；
- Runtime update 不得静默改变 running Job；
- 若必须升级 running Job，必须经过 controlled migration / reopen；
- material migration 必须分析已有 Artifact / Review / Approval 是否失效。

如果旧 Runtime 因重大安全问题不可继续使用：

> fail closed + required migration interface

不得以“紧急”为理由静默迁移 Authority 数据。

## M6. Representative Pack Regression

Runtime 是多个 Pack 的公共底层。

因此 material Runtime change 除 Core regression 外，应运行代表性跨领域 fixture，以证明公共 Contract 没有被领域特例污染。

长期建议至少保留：

- one narrative/content-heavy fixture
- one deterministic/data-heavy fixture
- one structured/citation-heavy fixture（相关 Pack 成熟后）

不要求每次 Runtime patch 完整重跑所有生产 Pack；Regression scope 应与 change ownership/risk 匹配。

## M7. Runtime Dependency Updates

MAF、Model Gateway、Telemetry SDK、Parser、Database driver 等依赖更新必须作为 External Component Update Candidate 处理。

禁止：

- production environment `upgrade all` 后直接继续运行；
- Provider alias 静默解析到未经验证的新 dependency behavior；
- 依赖升级绕过 Adapter contract tests。

标准流程：

> Discovery → exact candidate version/tag/commit → change brief → license/security/data-flow review（按需）→ adapter tests → Runtime regression → staging → explicit Promotion

External dependency 不是 Authority。

## M8. Automatic Update Boundary

长期允许：

- AUTO_UPDATE_DISCOVERY = YES
- MATERIAL_UPDATE_NOTIFICATION = YES
- AUTO_DOWNLOAD_TO_STAGING = FUTURE_OPTIONAL
- AUTO_TEST_CANDIDATE = FUTURE_SUPPORTED

长期禁止：

- AUTO_RUNTIME_PROMOTION
- AUTO_AUTHORITY_SCHEMA_MIGRATION
- AUTO_RUNNING_JOB_REBIND

自动化只能准备 Candidate / Evidence，不能拥有 Promotion Authority。

## M9. Unified Versioned Component Lifecycle

当 Runtime / Pack / Rule / ModelPolicy / Model / External Component 各自流程被实际证明后，可以抽象共享生命周期：

> DISCOVER → CANDIDATE → ASSESS → PIN EXACT REVISION → STAGING → REGRESSION → APPROVAL → PROMOTION → NEW JOBS ADOPT

并保持：

> RUNNING JOBS = EXACT PINS / NO SILENT REBIND

但在至少三类 versioned component 生命周期被实际走通前，不实现 Generic Update Manager。

`AUTOMATE_ONLY_AFTER_FLOW_IS_PROVEN = YES`

---

## M10. Release provenance and supply-chain evidence

As WEB_R004 matures toward signed EXE/package distribution, reuse mature supply-chain capabilities instead of building a custom scanner, SBOM engine, attestation system or signing protocol.

A mature release path may compose, as justified:

source revision
→ deterministic build/test
→ dependency / image / filesystem security scan
→ SBOM / provenance evidence
→ artifact attestation / signature
→ Candidate release
→ explicit Runtime/Product Promotion
→ installer/update channel

The exact tools remain transient adoption choices.

SUPPLY_CHAIN_TOOL_NE_AUTHORITY = YES
BUILD_ATTESTATION_NE_PROMOTION = YES
SIGNATURE_NE_ACCEPTANCE = YES
RELEASE_SECURITY_EVIDENCE_BINDS_EXACT_ARTIFACT = YES

Security evidence can block Promotion according to current policy, but external scanners/signers do not own Promotion.

# N. Core Completion / Freeze Criteria

Runtime Core 不以“功能最多”为完成标准。

进入 Core Baseline Freeze 的建议条件：

1. Artifact / Revision / SHA / Manifest proven
2. Review / stale invalidation proven
3. PASS / REVISE / BLOCKER proven
4. Approval / Promotion / History proven
5. One Primary Pack → Job exact pin proven
6. Permission / Load Plan job-scoped proven
7. deterministic Model Policy contract proven
8. Runtime version / contract revision is explicit and pin-able; migration/rollback semantics are defined
9. one non-novel cross-domain fixture proves Core reuse
10. native regression stable
11. no material domain-specific assumptions remain in Runtime Core

Freeze 后：

- Runtime Core 默认只修 bug / security / proven general gap；
- 若 WEB_R004 shared product foundation 已达到 baseline，则主力领域扩展转入 Packs；
- 若 Web/Desktop 产品基线仍未完成，Core Freeze 不得被误读为“等待 Pack 才能继续产品化”，产品壳/UX 可继续通过 thin seam 演进；
- 新 Runtime subsystem 需要独立 Complexity Budget 和 architecture justification。

---

# O. Deferred Complexity Rules

以下能力默认延后：

- Generic Multi-Pack Manager
- Marketplace
- Dependency Solver
- Auto GitHub Updater
- Generic Runtime Auto-Updater
- Generic Versioned Component Update Manager
- Custom installer engine
- Custom delta patcher
- Custom Windows service manager
- Custom browser agent / browser automation framework
- Custom secret vault
- Custom SBOM / vulnerability scanner / attestation system
- Custom tool protocol / custom coding-agent protocol
- Adaptive AI Router
- Distributed Temporal-like infrastructure
- Full observability backend
- Generic Runtime admin/dashboard polish that is not on the current primary product path
- generic plugin marketplace

只有真实产品路径证明需要时才打开。

---

# P. Default Engineering Decision Rules

长期默认：

RUNTIME_AUTHORITY_HARD_FLOORS_NON_BYPASS = YES  
REUSE_BEFORE_REIMPLEMENT = YES  
COMPOSE_BY_CONTRACT = YES  
PACKLESS_CORE_MODE_SUPPORTED = YES  
ALL_USER_PACKS_OPTIONAL = YES  
ONE_PRIMARY_PACK_BEFORE_MULTI_PACK = YES  
PROVIDER_NE_SHELL = YES  
PROVIDER_NE_PACK = YES  
DETERMINISTIC_MODEL_POLICY_BEFORE_ADAPTIVE_ROUTING = YES  
PACK_REQUESTS_CAPABILITY_NOT_PROVIDER = YES  
MODEL_SELECTION_MUST_BE_JOB_AUDITABLE = YES  
MODEL_POLICY_REVISION_MUST_BE_PINNABLE = YES  
MODEL_UPDATE_NE_SILENT_JOB_REBIND = YES  
NO_MODEL_IF_DETERMINISTIC_EXECUTOR_SUFFICES = YES  
TOKEN_REDUCTION_BEFORE_MODEL_PRICE_OPTIMIZATION = YES  
QUALITY_FLOOR_BEFORE_COST_OPTIMIZATION = YES  
RISK_FLOOR_CANNOT_BE_DOWNGRADED_BY_ROUTER = YES  
EXACT_MODEL_EXECUTION_MUST_BE_AUDITABLE = YES  
ADAPTIVE_ROUTING_REQUIRES_PROVEN_TELEMETRY = YES  
WEB_FOUNDATION_BASELINE_BEFORE_LARGE_SCALE_PACK_EXPANSION = YES
CORE_FREEZE_BEFORE_LARGE_SCALE_RUNTIME_SUBSYSTEM_EXPANSION = YES
RUNTIME_UPDATE_IS_CANDIDATE_FIRST = YES  
RUNTIME_UPDATE_NE_OVERWRITE_HISTORY = YES  
RUNNING_JOB_PINS_RUNTIME_REVISION = YES  
RUNTIME_UPDATE_NE_SILENT_JOB_REBIND = YES  
AUTHORITY_SCHEMA_MIGRATION_IS_NEW_REVISION = YES  
OLD_RUNTIME_VERSION_REMAINS_ROLLBACKABLE = YES  
RUNTIME_PROMOTION_REQUIRES_CORE_REGRESSION = YES  
MATERIAL_RUNTIME_CHANGE_REQUIRES_REPRESENTATIVE_PACK_REGRESSION = YES  
EXTERNAL_DEPENDENCY_UPDATE_NE_AUTO_ADOPT = YES  
AUTO_UPDATE_DISCOVERY_SUPPORTED = YES  
AUTO_RUNTIME_PROMOTION = NO
S1_MATURE_DESKTOP_PRIMITIVES_FIRST = YES
S2_MATURE_INSTALLER_UPDATER_DISTRIBUTION_FIRST = YES
NORMAL_USER_SHELL_HIDES_INFRASTRUCTURE_BY_DEFAULT = YES
FRESH_MACHINE_USER_JOURNEY_ACCEPTANCE_REQUIRED = YES
NATIVE_SHELL_REWRITE_REQUIRES_MATERIAL_USER_GAIN = YES
UPDATE_DISCOVERY_NE_PROMOTION = YES
SUPPLY_CHAIN_EVIDENCE_REUSE_BEFORE_CUSTOM = YES
MATURE_TOOL_AGENT_INTEROP_BEFORE_CUSTOM_PROTOCOL = YES
MATURE_BROWSER_AUTOMATION_BEFORE_CUSTOM_BROWSER_AGENT = YES
INSTALLED_SECRET_STORAGE_RECHECK_AT_S1_S2 = YES
NATIVE_DIAGNOSTICS_BEFORE_CUSTOM_OBSERVABILITY = YES
HISTORICAL_ROADMAP_IS_NON_AUTHORITY = YES
HISTORICAL_ROUTE_LOAD_BY_EXCEPTION_ONLY = YES

---

---

# Q. Stable Disposition

This v0.8 is the **active full-replacement Stable Runtime Development Strategy**, promoted by the user's explicit approval on 2026-10-15. It supersedes the exact promoted v0.7 (SHA256 `65f704d52f7be1473dfe045924abcbae8c9280a2ddacb81b56c08835bd0fa439`) without rewriting any older revision or accepted receipt.

The bounded semantic delta clarifies the Aides user-confirmed delivery order: a complete local-first Project normal-user journey; composition of mature LibreChat native models, MCP, Agents, Skills and tools; real user-authorable optional governed Pack Candidate formation and separate authorized install/activate/deactivate/uninstall; finally a packaged Windows EXE for fresh installation on any supported PC. Fresh EXE installation requires neither cloud synchronization nor migration of a previous PC's Projects. Directly affected local data durability, privacy, authorization, rollback and continuity remain hard safety floors.

The active current Phase/Stage/route comes only from the latest accepted Handoff/Build Status and newer exact Windows evidence. This Stable Source owns the durable delivery strategy, not transient action order, SHA, jobs, Product PASS, Program PASS, or supporting route-graph execution.

All unaffected v0.7 contracts and v0.6/v0.5 inherited strategies, previously accepted Project/Human/Packless/Pack-lifecycle proof ceilings and pre-existing hard STOPs remain intact. Strategy Promotion does not itself prove any additional user-visible Product/Pack/EXE success. Material Product changes remain subject to accepted baseline inheritance, directly invalidated proof families and actual-user acceptance.

PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_7.md, v0_6.md, and v0_5.md remain preserved historical predecessors. No historical authority or user Project data is rewritten by this Promotion.

PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_USER_APPROVAL_2026_10_15
