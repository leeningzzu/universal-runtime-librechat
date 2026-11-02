# Universal Runtime｜Project Source｜Stable Architecture v0.9

STATUS = STABLE_PROJECT_SOURCE
AUTHORITY_STATUS = ACTIVE_STABLE_AUTHORITY
REVISION_OF = PROJECT_SOURCE_RUNTIME_ARCHITECTURE_v0_8.md
SUPERSEDES = PROJECT_SOURCE_RUNTIME_ARCHITECTURE_v0_8.md
PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
STABLE_RUNTIME_ARCHITECTURE_AUTHORITY = PROJECT_SOURCE_RUNTIME_ARCHITECTURE_v0_9.md
HISTORY_REWRITE = NO
MODEL_OUTPUT_IS_PROPOSAL_ONLY = YES
NO_SILENT_STABLE_SOURCE_MUTATION = YES

SEMANTIC_DELTA =
CORE_PROJECT_BASELINE_VS_OPTIONAL_EXTENSION_PLANE
+ PROJECT_ZERO_PACK_AGENT_SKILL_MCP_LOCAL_ACTION_BASELINE
+ LOCAL_ACTION_PROVIDER_CLASS_NOT_EXECUTOR_IDENTITY
+ MCP_OPTIONAL_INTEROP_NOT_PROJECT_REQUIREMENT
+ PACK_USER_CHOICE_REASSERTION
+ BUILTIN_GUIDE_CURRENTNESS_CONTRACT
+ PROJECT_EXPERIENCE_CAPABILITY_CONTRACT
+ PROJECT_MEMORY_VS_USER_MEMORY_EXPLICIT
+ PROJECT_FILES_SOURCES_ARTIFACT_SHELF_TERMINOLOGY
+ STORAGE_RETRIEVAL_INJECTION_RECOVERY_CAPACITY_SEPARATION
+ NATIVE_SKILL_AGENT_MCP_COMPOSITION_WITHOUT_PROJECT_IDENTITY
+ EXPERIENCE_GRADUATION_PRODUCT_SEAM
+ TRANSIENT_CURRENT_PRIORITY_REMOVED_FROM_STABLE_ARCHITECTURE
+ PRESERVE_V0_5_ARCHITECTURE
+ ANY_SUPPORTED_WINDOWS_PC_PORTABILITY_TARGET
+ LOGICAL_PROJECT_WORKSPACE_BINDING
+ MACHINE_LOCAL_PATH_RESOLUTION_REGISTRY
+ LOCAL_ACTION_CAPABILITY_EXECUTOR_SEPARATION
+ MCP_TRANSPORT_NOT_AUTHORITY
+ MCP_ROOTS_DEPRECATED_NOT_PROJECT_IDENTITY
+ INTERNAL_PROXY_TUNNEL_FORBIDDEN
+ HOST_SIDE_FILESYSTEM_CAPABILITY_BOUNDARY
+ FRESH_MACHINE_PORTABILITY_ACCEPTANCE
+ NORMAL_USER_WINDOWS_SHELL_CONTRACT
+ SHELL_INFRASTRUCTURE_HIDDEN_FROM_NORMAL_FLOW
+ USER_DATA_REPAIR_UPDATE_ROLLBACK_CONTINUITY

---

## 1. Program North Star

Universal Runtime 项目的最终目标不是单独造一个 Runtime 内核，也不是只造一个聊天 Web。

最终目标是：

> 建立一个 Windows-local、可长期维护、可切换模型、可审计、可升级的 AI 工作平台；先完成一个接近 ChatGPT 使用体验、保留开放多模型优势的共享 Web/Desktop 交互底座，再在同一 Runtime 治理与产品底座上持续加载小说、学术论文、政府报告、审评报告、股票分析、软件开发等领域 Pack。

PROGRAM_NORTH_STAR = SHARED_AI_PRODUCT_FOUNDATION + GOVERNED_MULTI_PACK_PLATFORM
PROGRAM_PORTABILITY_TARGET = ANY_SUPPORTED_WINDOWS_PC
SUPPORTED_WINDOWS_MEANS = PUBLISHED_RELEASE_SUPPORT_MATRIX_NOT_ONE_DEVELOPER_MACHINE

WEB_PRODUCT_IS_FOUNDATION_NOT_FINAL_DOMAIN_PACK = YES
PACKS_ARE_DOMAIN_APPLICATIONS_ON_SHARED_PRODUCT_FOUNDATION = YES
RUNTIME_IS_AUTHORITY_CONTROL_PLANE_NOT_FINAL_USER_INTERFACE = YES

### 1.0A Canonical product / capability taxonomy

The product must remain useful with **zero user-installed Packs**. LibreChat/current primary shell plus Runtime Authority and native/shared capabilities form the Core Product. User Packs add optional capability; they are not required product substrate.

CORE_PRODUCT = LIBRECHAT_CURRENT + RUNTIME_AUTHORITY + NATIVE_SHARED_CAPABILITIES  
PACKLESS_CORE_MODE_SUPPORTED = YES  
ALL_USER_PACKS_OPTIONAL = YES  
PROJECT_IDENTITY_NE_PACK_IDENTITY = YES  
PROVIDER_IDENTITY_NE_PROJECT_IDENTITY = YES  
SHELL_IDENTITY_NE_PROVIDER_IDENTITY = YES  
SECOND_SHELL_NOW = NO  
MCP_IS_INTEROP_TRANSPORT_NOT_AUTHORITY = YES  
LOCAL_ACTION_EXECUTOR_IS_REPLACEABLE = YES

Permanent role map:
- **Project** = user workspace/context/history/source/artifact hub;
- **User Pack** = installable, activatable, deactivatable and removable capability package;
- **Universal Pack** = optional cross-domain reusable methods proven across materially different Projects/domains; it is not Core;
- **Domain Pack** = optional domain capability such as academic, market or novel workflows;
- **Project-local Overlay** = Project-scoped method or operating knowledge not yet independently reusable;
- **Skill** = narrow reusable procedural capability with an independent consumer and trigger/task-value evidence;
- **Provider** = model access route/profile; provider changes must not rewrite Project or Pack identity;
- **Product shell** = replaceable user interaction/delivery surface; current shell remains LibreChat unless a later shell gate proves material user gain.

A material successor must not be selected merely because a Candidate already exists. The current Stage must first rebind the Program purpose, the affected plane, and the object role (Core / Project / Pack / Skill / Provider / Shell / evidence). Detailed point-of-use enforcement belongs to Handoff/Process/Project Instructions, not this Architecture.

### 1.1 Shared product-foundation lane definition

`WEB_R004` is the named shared Web/Desktop product-foundation family used by this Program. **Whether it is the current active priority is transient Project-Instructions / Handoff state, not Stable Architecture currentness.**

WEB_R004 product purpose:

> Provide a ChatGPT-like Project/Chat experience while preserving LibreChat multi-model/open-ecosystem strengths and Runtime-owned local Authority, Artifact, Permission, Project/Source/Memory, Pack, Job Pin, Promotion and Audit boundaries.

WEB_R004_PRODUCT_NORTH_STAR = CHATGPT_LIKE_UX + LIBRECHAT_MULTI_MODEL_OPEN_ECOSYSTEM + LOCAL_RUNTIME_GOVERNANCE
CURRENT_USER_PRODUCT_WORKING_NAME = INQUIRY_DESK
INTERNAL_RUNTIME_NAME = UNIVERSAL_RUNTIME
PRODUCT_NAME_NE_RUNTIME_NAME = YES
PRIMARY_PRODUCT_SHELL_FAMILY = LIBRECHAT_CURRENT_REPLACEABLE
FINAL_COMMERCIAL_BRAND_AND_INSTALLER_FILENAME = DEFER_UNTIL_S2_CLEARANCE

`Inquiry Desk` remains the current user-facing working name and `Universal Runtime` remains the internal Authority/control-plane name unless a later explicit product-naming decision changes it. Product naming does not own the current material route.

LibreChat is the current shell family, not Runtime Authority and not permanent Project identity. Exact shell revision/build/current deployment belongs in Build Status / current product evidence rather than Stable Architecture.

CURRENT_PROGRAM_PRIORITY_NE_STABLE_ARCHITECTURE = YES
CURRENT_SHELL_EXACT_REVISION_NE_STABLE_ARCHITECTURE = YES

### 1.2 Program sequencing

默认 Program 顺序：

WEB_R004 SHARED PRODUCT FOUNDATION
→ PRODUCT BASELINE ACCEPTANCE
→ DOMAIN PACK EXPANSION
→ MULTI_PACK COMPOSITION / DEEPER PRODUCT SPECIALIZATION

在 WEB_R004 基线未建立前：

- 主力开发不得被大规模新 Pack 建设分散；
- 允许使用 Novel / Market / Academic 等代表性 fixture 或窄 Pack slice 证明 Runtime contract；
- 代表性 Pack fixture 不等于当前主产品 Lane 切换；
- Pack 未来能力不得成为推迟 Web/Desktop 产品底座的理由。

WEB_FOUNDATION_BEFORE_LARGE_SCALE_PACK_EXPANSION = YES
REPRESENTATIVE_PACK_FIXTURE_BEFORE_WEB_BASELINE = ALLOWED_WHEN_ARCHITECTURE_PROOF_REQUIRES
REPRESENTATIVE_FIXTURE_NE_ACTIVE_PRODUCT_LANE_SWITCH = YES

WEB_R004 基线完成后：

- Pack 成为主要领域扩展方式；
- 同一 Web/Desktop 壳承载不同 Pack 的工作流、Skills、Rules、Executors、Adapters 与领域 UX；
- Runtime 继续统一治理 Authority、Permission、Job Pin、Persistence、Promotion 与 Audit。

---

## 2. Product and execution architecture

必须区分两个相互连接但不同的平面。

### 2.1 Interaction / Product Plane

Inquiry Desk Desktop Thin Shell
→ LibreChat / current primary product shell
→ Runtime Interaction Ports

职责：

- chat / history / streaming / stop / retry / restart;
- Projects / files / attachments / sources;
- Memory / Library / Knowledge user experience;
- Web research / tools / user-visible approvals;
- Pack entry / mode / domain workflow presentation;
- desktop launch / window / tray / health UX.

Product Plane 不拥有正式 Authority。

### 2.2 Runtime / Domain Execution Plane

Universal Runtime
→ Primary Pack
→ Workflow
→ Skills + Deterministic Executors + Rules + Adapters
→ Models / Tools / External Capabilities

Pack != Skill.

Runtime 统一拥有：

- Artifact identity / Revision / SHA;
- Job identity and exact pins;
- Permission / Load Plan;
- Review / Approval / Promotion;
- Persistence legality;
- Project / Source / Memory authoritative bindings where assigned;
- Model Policy authority;
- Audit / Provenance / stale invalidation.

Pack 拥有领域 workflow 和 domain logic，但不得接管 Runtime Authority。

### 2.3 Product-shell integration rule

任何 ChatGPT-like 用户能力在 material custom implementation 前，默认顺序：

CURRENT PRODUCT-SHELL UPSTREAM CAPABILITY
→ EXISTING RUNTIME CAPABILITY
→ MATURE PRIOR-ART / DONOR
→ THIN CONTRACT / ADAPTER / COMPOSITION
→ ONLY THEN GENUINE CUSTOM GAP

UPSTREAM_CURRENTNESS_BEFORE_CUSTOM_PRODUCT_BUILD = YES
REUSE_PRODUCT_CAPABILITY_BEFORE_CUSTOM_UI = YES
CUSTOM_UI_REQUIRES_GENUINE_PRODUCT_GAP = YES
GENERIC_AGENT_HARNESS_CUSTOM_BUILD = NO

详细 external reuse / adoption ownership 由 `PROJECT_SOURCE_EXTERNAL_CAPABILITY_ASSEMBLY` 的 current promoted Stable Authority 负责；Architecture 不固定其版本号。


### 2.3A Project-first user workspace

WEB_R004 的用户工作空间以 Project 为第一层组织单元，而不是以 Pack 为第一层。

PROJECT_FIRST_USER_WORKSPACE = YES
PACK_BEHIND_PROJECT = YES
PACK_NE_PRIMARY_USER_WORKSPACE = YES
PROJECT_UI_MUST_NOT_REQUIRE_USER_TO_UNDERSTAND_RUNTIME_INTERNALS = YES

默认用户心智模型：

Chat
→ Project
→ Files / Library / Knowledge
→ Memory / Context
→ Tools / Models
→ optional domain capability

Pack 是 Project 背后的领域执行能力，可由 Runtime 按 Project binding、权限、workflow 和 current intent 组合；Pack 不得要求为每个领域重建一套 Chat / Project / Memory / Files / History 产品壳。

Project-first 不意味着 Pack Authority 被弱化。Runtime 继续拥有 Project/Pack binding、Permission、Persistence、Job Pin、Promotion 与 Audit；Product Plane 只呈现用户工作空间。

### 2.3B Project Context Continuity baseline

ChatGPT-like Project parity 不能只以“存在 Project 列表/目录”作为完成标准。

PROJECT_CONTEXT_CONTINUITY_IS_PRODUCT_BASELINE = YES

至少应区分并组合以下上下文层：

1. CURRENT_CHAT_CONTEXT
   - 当前 Chat / branch 的活跃消息上下文；
   - 由产品壳原生 conversation/message graph 优先提供。

2. PROJECT_INSTRUCTIONS
   - 当前 Project 的稳定用户作用域规则；
   - 不覆盖 Runtime / Pack / Safety / Permission Authority。

3. PROJECT_LIBRARY_KNOWLEDGE
   - 当前 Project 的 files / Source / Library / Knowledge；
   - 优先复用产品壳原生文件/知识能力与 Runtime existing Source bindings。

4. PROJECT_DURABLE_MEMORY
   - Project-local 的稳定事实、偏好、决策、当前项目状态；
   - 与 user-global memory 分离；
   - authoritative persistence 仍受 Runtime currentness / revision / provenance 规则约束。

5. PROJECT_CROSS_CHAT_RECALL
   - 在当前 user + current Project 作用域内搜索历史 Chat，再按需读取 exact historical messages；
   - 优先复用当前产品壳 conversation DB / existing search/index；
   - 不因该需求自动创建第二 Chat DB、第二 Search DB 或 semantic-chat vector DB。

6. USER_GLOBAL_MEMORY
   - 仅保存跨 Project 仍合理的用户级长期偏好/个人背景；
   - USER_GLOBAL_MEMORY_NE_PROJECT_MEMORY = YES。

7. INTERACTION_MEMORY_CANDIDATE
   - 对“先前讨论/决定/尝试”的可复用交互经验允许形成非 Authority 候选；
   - 模型不得静默把普通推断直接提升为 authoritative Project Memory；
   - Promotion / persistence 必须服从现有 Authority 与 lifecycle 规则。

上下文组合必须有界、按当前请求选择，不要求把所有历史 Chat / Memory / Files 全量塞入 prompt。

NO_GENERIC_CONTEXT_MANAGER_BY_DEFAULT = YES
NO_GENERIC_MEMORY_BACKEND_BY_DEFAULT = YES
NO_SECOND_CHAT_DB_BY_DEFAULT = YES
NO_SECOND_SEARCH_DB_BY_DEFAULT = YES
PROJECT_SCOPE_MUST_BE_SERVER_SIDE_ENFORCED = YES

Project context continuity 的自然实施顺序优先为：

CURRENT_SHELL_NATIVE_PROJECT / CHAT / FILE / MEMORY CAPABILITY
→ EXISTING_RUNTIME_PROJECT_INSTRUCTIONS / MEMORY / LIBRARY
→ CURRENT_SHELL_EXISTING_SEARCH / CONVERSATION_STORE
→ MATURE DONOR PATTERN WHEN A MATERIAL GAP REMAINS
→ THIN PROJECT-SCOPED RETRIEVAL / COMPOSITION SEAM
→ ONLY THEN NEW PERSISTENT SUBSYSTEM IF STILL PROVEN NECESSARY

### 2.3C Concrete donor currentness and retirement

本 Stable Architecture 只固定 capability / ownership / layering，不固定具体第三方项目为长期 Authority。

CONCRETE_EXTERNAL_DONOR_NE_STABLE_ARCHITECTURE_AUTHORITY = YES
DONOR_SELECTION_IS_CURRENTNESS_BOUND = YES
UPSTREAM_NATIVE_REPLACEMENT_PREFERS_SEAM_RETIREMENT = YES

例如 cross-chat retrieval、memory-tool interaction、knowledge selection 等可以借成熟 prior-art 的 primitive / pattern，但具体 donor 名称、版本、repo、license、安全与 adoption mode 由 External Capability Assembly / current Handoff / implementation manifest 在 point-of-use 按 current evidence 决定。

若 LibreChat/current shell 上游后续原生提供等价或更完整能力：

UPSTREAM_NATIVE_CAPABILITY
→ validate compatibility / Authority boundary
→ retire corresponding local thin seam when safe

不得因为已经写过 custom seam 就阻止上游原生替换。

### 2.3D Explicit Project Context Policy and isolation

Project Context Continuity 必须有显式作用域策略，不能由模型、Provider 或隐式产品行为自行决定跨 Project 读取范围。

PROJECT_CONTEXT_POLICY_REQUIRED = YES

第一阶段至少支持两个逻辑模式：

1. PROJECT_ONLY
   - 允许 current chat、same-Project historical chats、Project Instructions、Project Library/Knowledge、Project durable Memory；
   - 不引用 user-global Memory；
   - 不读取其他 Project 或 general chat 的 conversation context。

2. PROJECT_PLUS_GLOBAL_USER_MEMORY
   - 保留全部 Project-local context；
   - 额外允许经过许可的 user-global stable preferences / profile Memory；
   - 仍不得因为 global Memory 开启而自动获得 cross-Project chat recall。

PROJECT_ONLY_NE_EMPTY_MEMORY = YES
GLOBAL_USER_MEMORY_NE_CROSS_PROJECT_CHAT_RECALL = YES
CONTEXT_POLICY_SWITCH_NE_DATA_COPY_OR_DELETE = YES
PROJECT_CONTEXT_SCOPE_MUST_BE_SERVER_SIDE_ENFORCED = YES

Context policy 只决定本轮可见/可检索范围，不得静默搬迁、复制或删除已有 Source/Memory。任何实际持久化迁移仍服从 Runtime lifecycle、revision、provenance 与 explicit Promotion/approval 规则。

共享或敏感 Project 若未来启用协作，默认必须使用 PROJECT_ONLY 或更严格边界；不得把协作者个人 global Memory 注入共享 Project。

### 2.3E Curated Project Sources and live external references

ChatGPT-like Project 的长期知识不能只来自上传文件和自动 Memory。用户应能够把有价值的聊天产物显式沉淀为 Project Source。

PROJECT_SOURCE_CLASSES MAY INCLUDE:
- USER_FILE / USER_TEXT;
- RUNTIME_BOUND_SOURCE / LIBRARY_ITEM;
- SAVED_CHAT_OUTPUT / DECISION_NOTE / DRAFT / ANALYSIS;
- LIVE_EXTERNAL_REFERENCE / CONNECTED_APP_REFERENCE.

CHAT_OUTPUT_TO_PROJECT_SOURCE_REQUIRES_EXPLICIT_USER_OR_GOVERNED_PROMOTION = YES
MODEL_CANNOT_SILENTLY_PROMOTE_CHAT_OUTPUT_TO_PROJECT_SOURCE = YES
PROJECT_SOURCE_NE_PROJECT_MEMORY = YES

默认语义：
- 需要用户看见、复用、审计、下载、比较或长期维护的内容，优先成为 Project Source / Artifact；
- 紧凑的项目事实、偏好、当前状态可以进入 Project Memory；
- 历史讨论本身保持为 Conversation/Episodic context，由 cross-chat recall 按需召回。

外部实时 Source 默认保存引用与 provenance，而不是无条件复制整个外部系统：

LIVE_REFERENCE_NE_LOCAL_CANONICAL_COPY = YES
LIVE_REFERENCE_ACCESS_REVALIDATED_AT_USE = YES
LIVE_REFERENCE_CURRENTNESS_REVALIDATED_AT_USE = YES
NO_AMBIENT_CONNECTOR_SYNC_BY_DEFAULT = YES

若为离线、可复现或审计而需要持久快照，应生成明确 revision/SHA/provenance 的 Snapshot Artifact；Snapshot 与 live reference 是不同事实类。

### 2.3F Project-scoped Tools / Work-like execution

Project 内的 Tool / Agent / Work-like capability 必须继承 Project 的身份、上下文策略、权限与 Source scope；不得只靠 prompt 提醒“不要访问别的 Project”。

PROJECT_TOOL_EXECUTION_INHERITS_PROJECT_SCOPE = YES
PROJECT_WORK_EXECUTION_INHERITS_PROJECT_SCOPE = YES
TOOL_OR_AGENT_CANNOT_EXPAND_PROJECT_CONTEXT_SCOPE = YES
TOOL_OUTPUT_IS_NOT_AUTHORITY_BY_DEFAULT = YES
WORK_OUTPUT_IS_NOT_PROJECT_SOURCE_UNTIL_EXPLICITLY_SAVED_OR_PROMOTED = YES

Context mode 与 Tool/Work capability 是两个独立合同。某个 upstream 产品当前不支持某种组合，不代表 Architecture 应永久复制该限制；每一种组合必须独立做 compatibility/permission acceptance。

### 2.3G Project portability and lifecycle contract

PRIMARY_PRODUCT_SHELL_IS_REPLACEABLE = YES 要求 Project 也不能成为 shell-specific dead end。

PROJECT_PORTABILITY_IS_PRODUCT_LIFECYCLE_CAPABILITY = YES
DURABLE_PROJECT_IDENTITY_MUST_NOT_DEPEND_ON_ABSOLUTE_WINDOWS_PATH = YES
PROJECT_WORKSPACE_BINDING_MUST_BE_LOGICAL = YES
MACHINE_LOCAL_WORKSPACE_RESOLUTION_IS_NOT_PORTABLE_PROJECT_STATE = YES


Project portability 至少应能表达或恢复：
- Project identity / display metadata；
- Project Instructions；
- chat membership 与 source↔target conversation identity mapping；
- Project Source/Library references 与必要 snapshots；
- Project Memory scope metadata 与 explicit durable entries；
- relevant provenance/currentness needed to verify import/replay；
- Pack/capability binding only through Runtime-owned logical contracts；
- logical local-workspace binding ids when local canonical work exists；
- no developer-machine username, drive letter, install root, raw executor handle, raw MCP server identity or machine-local project handle as durable Project identity.

PORTABILITY_REUSES_NATIVE_IMPORT_EXPORT_WHERE_AVAILABLE = YES
PORTABILITY_IMPORT_MUST_BE_IDEMPOTENT_OR_FAIL_CLOSED = YES
PORTABILITY_MUST_NOT_CREATE_SECOND_CHAT_DB = YES
PORTABILITY_MUST_NOT_CREATE_SECOND_PROJECT_PLATFORM = YES

原始导出、规范化中间件、导入 receipt、rehydration receipt 与 parity receipt 属于迁移证据/实现，不自动进入 Stable Source。Stable Architecture 只拥有 capability/boundary。

### 2.3H Collaboration floor — deferred until real multi-user need

当前 WEB_R004 主线不因 GPT-like parity 自动打开团队协作建设。

PROJECT_COLLABORATION_IMPLEMENTATION_NOW = DEFER

若未来启用共享 Project，最低硬边界为：
- explicit ACL / role / owner；
- server-side user + Project authorization；
- shared Project defaults to Project-only context；
- collaborator personal/global Memory is not shared context；
- files/live sources are revalidated against owner/current access at use；
- removal/revocation must stop future retrieval without relying on stale prompt context.

COLLABORATION_NE_REASON_TO_BUILD_SECOND_PROJECT_SHELL = YES

### 2.3I Context selection quality floor

Context Continuity 的目标不是“加载越多越像 GPT”，而是在当前 scope 内选择最相关、最新、可追溯的上下文。

CONTEXT_SELECTION_OPTIMIZES_RELEVANCE_CURRENTNESS_SCOPE = YES
STALE_OR_CONTRADICTED_MEMORY_CANNOT_SILENTLY_OVERRIDE_CURRENT_EVIDENCE = YES
EXACT_SOURCE_OR_CHAT_VIEW_FOLLOWS_SEARCH_WHEN_CLAIM_MATTERS = YES
FULL_HISTORY_OR_FULL_LIBRARY_INJECTION_BY_DEFAULT = NO

语义检索、hybrid retrieval、exact grep/read、full-context injection 是不同 retrieval primitives；由 source class、规模、任务和当前产品壳能力选择。Architecture 不固定某一 vector DB 或 retrieval engine。


### 2.3J Project Resource identity and membership contract

Project 不能只依赖 UI folder / sidebar location 来推断资源归属。凡是会影响上下文、权限、迁移、删除或执行的资源，都必须有稳定的逻辑 Project membership。

PROJECT_RESOURCE_MEMBERSHIP_MUST_BE_EXPLICIT = YES
PROJECT_MEMBERSHIP_NE_UI_LOCATION = YES
PROJECT_RESOURCE_IDENTITY_MUST_BE_STABLE = YES

逻辑上至少覆盖：
- Conversation / branch；
- Project Source / Library binding / live reference；
- Project Memory entry；
- durable Project Artifact / Note；
- Pack / capability binding；
- Project-scoped execution/automation binding when present。

任何 search/view/tool/import/export consumer 不得仅凭名称、路径、prompt 文本或客户端状态推断 Project membership。服务端必须以 current user / tenant + Project identity + resource identity 做授权与归属校验。

Stable Architecture 不固定数据库字段或 vendor schema；具体映射由 current shell / Runtime adapter 实现，但 shell replacement 后逻辑 identity 必须可恢复。

### 2.3K Instruction / policy precedence contract

随着 Project Instructions、global user preferences、Pack rules、Agent/model instructions、当前 user turn 和 Tool policies 同时存在，优先级不能依赖字符串拼接顺序。

INSTRUCTION_PRECEDENCE_MUST_BE_EXPLICIT = YES
PROMPT_CONCATENATION_ORDER_NE_AUTHORITY_ORDER = YES

长期原则：
- Runtime / safety / permission / formal Authority 永远不能被 Project、Agent、Memory 或当前聊天覆盖；
- Pack / Job formal constraints 仅在其合法 scope 内生效；
- Project Instructions 在当前 Project 内高于 user-global style/default preferences；
- 当前 user turn 可覆盖较低级 preference/default，但不能覆盖 formal Authority / permission / safety；
- retrieved chats / Memory / Sources 提供 context/evidence，不自动升级为 instruction Authority；
- model/provider-specific hidden/default behavior 不得成为 Runtime Authority。

Project instructions override global defaults 的产品语义可以复用成熟壳，但最终 legality 由 Runtime scope/Authority 决定。

### 2.3L Context budget, selection manifest, and explainability

Unified Project Context 必须是有界组合，不得通过“不断追加 token”实现连续性。

PROJECT_CONTEXT_BUDGET_REQUIRED = YES
PROJECT_CONTEXT_SELECTION_MANIFEST_REQUIRED = YES
CONTEXT_ITEM_MUST_RETAIN_ORIGIN_AND_SCOPE = YES

每次 material context assembly 至少能够审计：
- context class；
- logical resource identity；
- Project scope；
- source/revision/currentness when applicable；
- retrieval/search/view route；
- inclusion reason；
- truncation/omission reason when material；
- whether full-content, exact-range, semantic retrieval, memory injection or chat recall was used。

Selection Manifest 是 execution/context evidence，不自动成为 Stable Source 或 user-facing clutter。

优先顺序不是固定 token 百分比；应按 Authority、task relevance、currentness、exactness、risk 和 model context budget 决定。若 claim 依赖 retrieved item，应能够从 search result 进入 exact source/chat view，而不是只保留不可追溯摘要。

### 2.3M Project lifecycle, retention, move/copy, and deletion semantics

Project 是长期工作空间，因此删除、移出、复制、归档和权限撤销必须在大规模自然使用前有明确语义。

PROJECT_LIFECYCLE_SEMANTICS_REQUIRED = YES
DELETE_NE_ARCHIVE = YES
REMOVE_FROM_PROJECT_NE_DELETE_RESOURCE = YES
PROJECT_OWNED_COPY_NE_SHARED_LIBRARY_REFERENCE = YES

至少区分：
- move conversation into/out of Project；
- archive conversation；
- delete conversation；
- remove/detach Project Source；
- delete Project；
- revoke live-reference permission；
- copy/duplicate Project or selected conversations when supported；
- leave shared Project when collaboration is later enabled。

Project 删除不得凭 UI convenience 猜测是否同时删除独立 Library/externally-owned assets。Project-owned bytes、shared Library refs、live external refs、snapshots 必须按各自 ownership/persistence class 处理。

不可逆 destructive action 必须 fail closed，并保持现有 Runtime Permission/Persistence/Promotion hard floors。

### 2.3N Conversation branch / lineage preservation

长期 Project 工作会自然产生 branch / fork / continuation。Branch 不能被当作无来源的新聊天，否则 cross-chat recall、migration、dedupe 和 collaboration 会失真。

CONVERSATION_LINEAGE_IS_PORTABLE_METADATA = YES
BRANCH_DEFAULTS_TO_PARENT_PROJECT_SCOPE = YES
BRANCH_NE_INDEPENDENT_AUTHORITY = YES

Project-scoped retrieval 可检索 branch，但必须能够保留 parent/branch lineage，并在需要时避免将同一祖先内容机械重复注入上下文。

Migration / import / export 应尽量保留 lineage；若上游格式不能表达 lineage，必须在 parity/gap receipt 中显式记录降级，而不是静默扁平化。

### 2.3O Durable editable Project Artifact / Note class

Chat、Memory、RAG file 三类资源不足以覆盖长期 Project 工作。成熟工作空间还需要“用户可见、可编辑、可反复精炼、可作为完整 context 或 source 使用”的 durable Artifact/Note。

DURABLE_PROJECT_ARTIFACT_CLASS_REQUIRED = YES
PROJECT_ARTIFACT_NE_CHAT_HISTORY = YES
PROJECT_ARTIFACT_NE_MEMORY_SNIPPET = YES
PROJECT_ARTIFACT_NE_OPAQUE_RAG_CHUNK = YES

典型对象包括：
- decision note；
- project brief；
- living specification；
- research synthesis；
- draft / outline；
- maintained checklist / plan；
- user-curated reference note。

优先复用 current shell/native Artifact/Note/document surface 或 Runtime existing Artifact/Library primitives。不得仅因该能力存在就建设第二文档平台。

Artifact 可作为 Project Source，但其编辑、revision、provenance、sharing、export 和 deletion 语义必须保持可审计。

### 2.3P General Project execution-scope inheritance

任何从 Project 发起或绑定到 Project 的执行能力，都必须继承 Project scope，而不仅限于当前命名的 Tool / Work。

PROJECT_EXECUTION_INHERITS_PROJECT_SCOPE = YES

适用能力包括未来可能存在的：
- Tool / MCP；
- Agent / Subagent；
- Work-like task；
- scheduled chat / automation；
- background job；
- code/sandbox workspace；
- external development connector。

Project destination 不是单纯 UI filing tag。若 execution 声称使用 Project context，则必须同时继承合法的 Project identity、context policy、source scope、permission/data policy 与 audit binding。

AUTOMATION_OR_BACKGROUND_EXECUTION_CANNOT_WIDEN_PROJECT_SCOPE = YES
EXECUTION_OUTPUT_REQUIRES_EXPLICIT_PERSISTENCE_CLASS = YES

### 2.3Q Project defaults are soft configuration, not identity

ChatGPT-like Project 不应把一个具体模型、Provider、Agent 或 tool bundle 写死为 Project identity。

PROJECT_MODEL_NE_PROJECT_IDENTITY = YES
PROJECT_PROVIDER_NE_PROJECT_IDENTITY = YES
PROJECT_AGENT_NE_PROJECT_IDENTITY = YES

允许未来存在 soft defaults，例如：
- preferred logical Model Profile；
- suggested Agent / capability；
- default tool allowlist；
- response style / presentation preference。

但这些默认值必须可被合法 per-chat/task selection 覆盖，并继续服从 Runtime Model Policy、Permission、Pack/Job constraints。Project portability 不得因为某个 Provider/Agent 不存在而整体失效。

Nested Project / deep folder hierarchy 不是 GPT-like baseline hard requirement；若未来 UI 需要 hierarchy/tagging，应与 Project Authority/scope identity 解耦。


### 2.3R Logical local workspace binding and machine-local resolution

Local canonical files/folders are a required AI Workbench capability, but a Windows path is not portable Project identity.

LOCAL_FILESYSTEM_CAPABILITY_REQUIRED = YES
PROJECT_WORKSPACE_BINDING = LOGICAL
MACHINE_LOCAL_WORKSPACE_RESOLUTION = HOST_LOCAL
ABSOLUTE_WINDOWS_PATH_IS_REQUEST_OR_MACHINE_STATE_ONLY = YES
PROJECT_EXPORT_MUST_NOT_REQUIRE_MACHINE_LOCAL_PATH = YES
LOCAL_ACTION_EXECUTOR_IDENTITY_NE_PROJECT_IDENTITY = YES

A durable Project may reference a logical workspace binding such as `primary-local-workspace`. The current machine resolves that logical id to an effective Windows root through machine-local state. Moving to another supported Windows PC may require one bounded rebind or machine-locatable auto-discovery, but must not require Project schema migration or history rewrite.

Machine-local resolution may contain:
- effective Windows root；
- current executor implementation/profile；
- executor-specific project/session handle；
- local capability/health metadata；
- current machine provenance.

Those fields are deployment state, not portable Project Authority. Current request snapshots may expose an effective path when needed for user clarity, but export/import must separate that from durable identity.

MACHINE_LOCAL_WORKSPACE_REGISTRY_REQUIRED_WHEN_LOCAL_WORK_EXISTS = YES
MACHINE_LOCAL_REBIND_IS_EXPLICIT_OR_MACHINE_LOCATABLE = YES
NO_RAW_WEBCODEX_PROJECT_HANDLE_IN_PORTABLE_PROJECT_IDENTITY = YES

### 2.3S Optional Local Action provider / MCP / filesystem role boundary

The optional product capability is `local canonical project work`, not a specific executor, provider or transport. Project Core must remain complete when this capability is unused or unavailable.

LOCAL_ACTION_CAPABILITY_FIRST = YES
CURRENT_EXECUTOR_IMPLEMENTATION_IS_REPLACEABLE = YES
CORE_PROJECT_LOCAL_ACTION_REQUIRED = NO
MCP_INTEROPERABILITY_CAPABILITY_SUPPORTED = YES
MCP_REQUIRED_FOR_LOCAL_WORK = NO
PROJECT_MCP_REQUIRED = NO
MCP_IS_INTEROP_TRANSPORT_NOT_AUTHORITY = YES
MCP_ROOTS_NE_PROJECT_AUTHORITY = YES
MCP_ROOTS_NEW_DEPENDENCY = NO
CURRENT_LOCAL_ACTION_PROVIDER_NE_PROJECT_IDENTITY = YES

Default routing:
- Chat/uploaded bytes or Project Source sufficient → LibreChat/Runtime, no Local Action provider；
- local canonical read actually required → selected Project-bound Local Action provider, read-only；
- local write/execute/test/git actually required → selected Project-bound Local Action provider with one complete effect approval；
- external SaaS/service → product-shell native connector/plugin/MCP when mature；
- Authority/Promotion → Runtime.

A Local Action provider may expose native shell tools, MCP, HTTP, CLI, stdio, ACP-like or another mature interface. Transport does not own Project identity, filesystem authority, persistence or Promotion. Prefer the current shell/native interoperability surface when it reduces glue and preserves zero-touch UX, but do not make MCP itself mandatory.

Concrete providers are currentness-bound and replaceable. Selection belongs to the current External Capability/Runtime route, not Stable Architecture. Do not keep multiple equivalent local-action stacks active by default merely because they exist.

The host-side provider, not the MCP protocol itself, owns actual Windows filesystem access. Container-wide drive mounts are not the default capability boundary.

WHOLE_DRIVE_DOCKER_MOUNT_BY_DEFAULT = FORBIDDEN
CONTAINER_RUNTIME_NE_PRODUCT_IDENTITY = YES
NORMAL_USER_LOCAL_ACTION_MUST_NOT_REQUIRE_MANUAL_DOCKER_MCP_OR_PROVIDER_SETUP = YES
INTERNAL_PROXY_OR_TUNNEL_DEPENDENCY = FORBIDDEN
INTERNAL_LOOPBACK_OR_HOST_BRIDGE_DIRECT_ONLY = YES
INTERNAL_ENDPOINTS_MUST_BYPASS_PROXY = YES

### 2.3T Normal-user Windows shell and lifecycle contract

The shell is a product entry/lifecycle surface, not a second Chat/Project product and not Runtime Authority.

NORMAL_USER_WINDOWS_SHELL_REQUIRED = YES
NORMAL_DAILY_ENTRY_TARGET = ONE_USER_ACTION_TO_EXISTING_OR_NEW_PRODUCT_WINDOW
NORMAL_USER_MUST_NOT_CONFIGURE_INTERNAL_COMPONENTS = YES
PRODUCT_SHELL_MUST_HIDE_POWERSHELL_PORTS_DOCKER_MCP_EXECUTOR_INTERNALS_BY_DEFAULT = YES
LOGIN_AND_PROJECT_SESSION_CONTINUITY_REQUIRED = YES
PRODUCT_CODE_DATA_AND_DEVELOPER_SOURCE_WORKSPACE_MUST_BE_SEPARATE = YES
REPAIR_MUST_NOT_SILENTLY_DELETE_OR_RESET_USER_DATA = YES
UPDATE_MUST_BE_CANDIDATE_FIRST_AND_ROLLBACKABLE = YES
UNINSTALL_MUST_DISTINGUISH_PRODUCT_CODE_FROM_USER_DATA = YES

The normal user journey is:

install or existing managed entry
→ one product launch action
→ prerequisite/service health handling by the product
→ existing-window focus or one new product window
→ authenticated Project workspace when a valid session exists
→ New Chat / direct request.

Only unavoidable user decisions may interrupt this flow, such as first authentication, an optional provider credential, a material filesystem permission/folder bind, effect approval, update Promotion or data-retention choice. Internal component names and transports remain Advanced/Developer details.

A thin shell may reuse browser app-mode, PWA/WebView, Tauri or another mature Windows primitive. Stable Architecture does not freeze the technology. Re-entry from a functional browser/app-mode shell to a native EXE requires a proven user/product gap such as second-machine deployment burden, single-instance/window lifecycle, tray/autostart, deep link/file association, native notification, sidecar/service ownership, repair, update, rollback or signed distribution.

SHELL_TECHNOLOGY_SELECTION_IS_CURRENTNESS_BOUND = YES
CURRENT_FUNCTIONAL_THIN_SHELL_MUST_NOT_BE_REWRITTEN_WITHOUT_MATERIAL_USER_GAIN = YES
SECOND_PRODUCT_SHELL_BY_DEFAULT = NO

Fresh-machine acceptance must prove the user journey, not merely process/container health. It must include a supported Windows profile with a different username and install/workspace location, launch without developer checkout knowledge, Project/user-data continuity, machine-local workspace rebind/autodiscovery where applicable, bounded repair, update/rollback, and no internal proxy/tunnel or manual Docker/MCP/executor setup.

USER_JOURNEY_PASS_NE_COMPONENT_HEALTH_PASS = YES
FRESH_MACHINE_SHELL_ACCEPTANCE_REQUIRED_BEFORE_DISTRIBUTION_FREEZE = YES

### 2.3U Project Experience capability contract

A ChatGPT-like Project experience is a workspace/context/history/source/memory/artifact capability composition. It is complete without Packs, Agents, Skills, MCP or a Local Action provider.

CORE_PROJECT_BASELINE_LAYERS:
1. current Chat context and branch lineage;
2. Project Instructions;
3. Project Files / governed Project Sources;
4. Project durable Memory;
5. same-Project cross-Chat recall with exact-message recovery;
6. durable editable Project Artifacts / Notes;
7. normal per-Chat model/provider selection and ordinary Chat actions supplied by the shared product shell.

OPTIONAL_CONTEXT_EXTENSION:
- user-global Memory, only when current policy/user choice permits it.

OPTIONAL_PROJECT_CAPABILITY_EXTENSION_PLANE:
- saved or ephemeral Agents;
- Skills;
- MCP-connected tools/services;
- Local Action providers for local canonical files/process/git/test;
- Domain/Universal Packs;
- scheduled/background/code-workspace capabilities when separately enabled.

Definitions:
- **Project Files** = shell-native user files attached/reused within a Project;
- **Project Sources** = governed, traceable long-lived materials/references/snapshots used as source evidence or maintained knowledge;
- **Project Memory** = compact Project-scoped durable facts/preferences/decisions/current state;
- **User-global Memory** = stable user-level facts/preferences that remain reasonable across Projects;
- **Project Artifact / Note** = user-visible editable durable work product/specification/synthesis;
- **Artifact Shelf / Library** = a user-visible cross-Project browsing/storage surface only when such a product surface actually exists. Do not label Project Files/Sources as a complete global Library merely for convenience.

PROJECT_MEMORY_NE_USER_GLOBAL_MEMORY = YES
PROJECT_SOURCE_NE_PROJECT_MEMORY = YES
PROJECT_ARTIFACT_NE_SOURCE_BY_DEFAULT = YES
ARTIFACT_CAN_BECOME_PROJECT_SOURCE_BY_EXPLICIT_SAVE_OR_GOVERNED_PROMOTION = YES
GLOBAL_LIBRARY_SHELF_NE_PROJECT_FILES = YES
PROJECT_CORE_REQUIRES_PACK = NO
PROJECT_CORE_REQUIRES_AGENT = NO
PROJECT_CORE_REQUIRES_SKILL = NO
PROJECT_CORE_REQUIRES_MCP = NO
PROJECT_CORE_REQUIRES_LOCAL_ACTION = NO
PROJECT_CORE_REQUIRES_ANY_SPECIFIC_LOCAL_ACTION_PROVIDER = NO
OPTIONAL_CAPABILITY_UNAVAILABLE_NE_PROJECT_FAILURE = YES

The experience goal is continuity by selection, not full-history/full-file injection. Search/recall may select candidates, but claims that materially depend on an item must be able to recover exact source/message context.

### 2.3V Project capacity contract — storage / retrieval / injection / recovery

Product capacity must be expressed on separate axes:

STORAGE_CAPACITY = how much durable Project material may exist;
RETRIEVAL_CAPACITY = how much a given search/index/retrieval path can inspect and rank for one request;
INJECTION_CAPACITY = how much selected content can enter one model/tool execution context;
RECOVERY_CAPACITY = how reliably an exact source/message/artifact can be reopened after search, compaction, branch, restart, export/import or migration.

These axes must not be collapsed into a single “Project capacity” number.

Exact numeric limits are current implementation/product evidence and belong in capability maps / Build Status / acceptance receipts, not Stable Architecture. Stable Architecture requires:
- explicit boundary behavior;
- no silent truncation when it changes product meaning;
- exact re-entry/read path after summary/search when the claim matters;
- bounded context assembly;
- scale acceptance at representative boundaries;
- native/upstream scale capability checked before new persistent infrastructure.

PROJECT_STORAGE_NE_MODEL_CONTEXT = YES
RETRIEVAL_COVERAGE_NE_MODEL_READ_ALL = YES
SEARCH_RESULT_NE_EXACT_SOURCE = YES
SCALE_GAP_NE_AUTO_NEW_DATABASE = YES

When a natural scale gap appears:
CURRENT_SHELL_NATIVE_SEARCH/RAG/CONTEXT → EXISTING_RUNTIME_SOURCE/HISTORY → mature donor if gap remains → thin adapter/replace → new persistent subsystem only for a proven residual gap.

### 2.3W Optional Project-scoped Skills / Agents / MCP / Local Action composition

These are optional advantages, not Project-completeness prerequisites. They are activated only when the user, current task, or an explicitly activated Pack requires them.

The normal Project user should request an outcome, not assemble internal primitives.

PROJECT_MAY_HAVE_SOFT_LOGICAL_ASSISTANT_PROFILE = YES
PROJECT_ASSISTANT_PROFILE_NE_PROJECT_IDENTITY = YES
PERSISTED_AGENT_ID_NE_PROJECT_IDENTITY = YES
EPHEMERAL_AGENT_EXECUTION_ALLOWED_WHEN_SHELL_NATIVE = YES

A logical assistant profile may project at runtime to shell-native Model Specs, ephemeral Agent execution, allowed Skills, tools, subagents or another current shell primitive. The projection is replaceable and must continue to inherit Project context/permission scope.

A saved/persisted Agent remains an explicit Advanced capability and may be user-selected when it is the task. Ordinary Project continuity must not depend on a hidden persisted Agent binding.

Skills should reuse portable Skill conventions and shell-native invocation where available. Runtime/Pack governs version, permission, install/activation and Promotion where those lifecycle facts exist; it does not need a second generic Skill engine.

MCP is one optional interoperability transport for mature tools. A Local Action provider may expose a native connector, MCP, HTTP, CLI, stdio, ACP-like or another mature interface. No one transport or provider is Project identity or a universal prerequisite.

A Project may invoke the currently selected Local Action provider when local canonical work is actually required. No concrete provider is Stable Architecture identity. Current/future alternatives remain eligible when the External Capability owner proves lower total user/maintenance/security cost. Raw provider/MCP/Runner/session identity remains machine-local and non-portable.

NORMAL_PROJECT_MANUAL_AGENT_SELECTION_TARGET = 0
NORMAL_PROJECT_MANUAL_SKILL_SELECTION_TARGET = 0
NORMAL_PROJECT_MANUAL_MCP_CONFIGURATION_TARGET = 0
NO_HIDDEN_PERSISTED_AGENT_CORE_DEPENDENCY = YES
PROJECT_MCP_REQUIRED = NO
PROJECT_LOCAL_ACTION_REQUIRED = NO
CURRENT_LOCAL_ACTION_PROVIDER_NE_STABLE_ARCHITECTURE = YES

### 2.3X Project experience graduation seam

Natural Project work may produce reusable operating knowledge. The product must preserve the smallest truthful home and avoid turning all useful experience into global Packs.

PROJECT_FACT / PRIVATE_SOURCE / DECISION → Project Memory / Source / Artifact  
PROJECT_METHOD → Project-local Overlay  
NARROW_METHOD + independent consumer + positive/negative/held-out value evidence → Skill Candidate  
COHERENT_DOMAIN_CAPABILITY → Domain Pack Candidate  
CROSS_DOMAIN_METHOD + materially different Project/domain evidence → Universal Pack Candidate.

The UI/product may later offer “save as Project method”, “propose reusable Skill” or similar affordances, but automatic observation may create only a Candidate. Stable promotion, install/activation, permission widening and deletion remain governed by their existing owners.

EXPERIENCE_GRADUATION_IS_CANDIDATE_FIRST = YES
NO_GENERIC_EXPERIENCE_COMPILER_BY_DEFAULT = YES
PACK_CREATION_OWNS_GRADUATION_DETAILS = YES
PACK_LIFECYCLE_OWNS_INSTALLED_LIFECYCLE = YES

### 2.3Y Built-in product guide currentness

The built-in product guide/manual is user documentation, not Authority. It must stay aligned with promoted user-facing semantics without copying transient engineering state.

MATERIAL_USER_FACING_STABLE_SEMANTIC_CHANGE → GUIDE_IMPACT_CHECK.

Update only affected guide sections. Internal SHA/run/container/build changes with no user-facing semantic delta are NO_OP for the guide.

Guide content must distinguish Core Project baseline from optional Agents/Skills/MCP/Local Action/Packs and must never present one current Local Action provider as mandatory product identity.

BUILTIN_GUIDE_NE_AUTHORITY = YES
BUILTIN_GUIDE_BINDS_CURRENT_STABLE_SEMANTICS = YES
GUIDE_TRANSIENT_BUILD_STATE = NO
GUIDE_OPTIONAL_CAPABILITY_ROLE_MUST_BE_EXPLICIT = YES
GUIDE_PROVIDER_SPECIFIC_LOCAL_ACTION_IDENTITY = NO

### 2.4 Developer Mode / self-development boundary

Inquiry Desk 可以提供用户可见的 Developer / Work-like 入口，但该入口属于 Product Plane，不得成为绕过 Runtime 治理的 Production 自修改通道。

推荐长期链路：

Product-shell native tool / agent surface
→ project-bound development connector
→ versioned Developer Source Workspace
→ Candidate / isolated workspace
→ deterministic validation / review
→ explicit Promotion
→ versioned Production install

PRODUCTION_INSTALL_NE_DEVELOPER_SOURCE_WORKSPACE = YES
PRODUCTION_SELF_MUTATION = NO
DEVELOPER_SOURCE_WORKSPACE_MUST_BE_VERSIONED = YES
DEVELOPER_MODE_MUST_NOT_REQUIRE_GENERIC_AGENT_HARNESS = YES
DEVELOPER_MODE_PREFERS_PROJECT_BOUND_CAPABILITY_OVER_BROAD_OPERATOR_SURFACE = YES
READ_ONLY_DEVELOPER_MODE_BEFORE_WRITABLE_MODE = YES
WRITABLE_MODE_PREFERS_ISOLATED_WORKSPACE = YES
TARGET_PRODUCTION_CHANGES_REQUIRE_EXPLICIT_PROMOTION = YES

当前具体开发执行器、connector、credential 或 transport 不由本 Architecture 固定；由 Project Instructions、Runtime Development Strategy 与 External Capability Assembly 在 point-of-use 按 currentness/reuse evidence 选择。

---

## 3. Desktop shell boundary

Desktop shell 是共享产品底座的薄入口，不是最终 feature freeze 后才做的包装。

推荐顺序：

S0 DAILY ENTRY
→ DIRECT CHAT / FILE UX BASELINE
→ S1 THIN DESKTOP SHELL
→ CONTINUE PROJECT / MEMORY / RESEARCH / PACK CAPABILITIES INSIDE THE SHELL
→ S2 INSTALLER / UPDATE / ROLLBACK WHEN PRODUCT BASELINE IS MATURE

SHELL_EARLY = YES
SHELL_NE_FINAL_FEATURE_FREEZE = YES
THIN_SHELL_MUST_NOT_REIMPLEMENT_LIBRECHAT_CHAT_UI = YES
THIN_SHELL_MUST_NOT_OWN_RUNTIME_AUTHORITY = YES

---

## 4. Model architecture

Packs request capability profiles, never provider-specific model names:

- extract_fast
- write_main
- reason_high
- audit_high
- deterministic_compute
- human_decision

DeepSeek API remains a valid first-class formal-production provider route, but Pack contract must not depend on a specific provider/model identifier.

MODEL_UPDATE_IS_CANDIDATE_FIRST = YES
PACK_USES_MODEL_PROFILE_NOT_PROVIDER_NAME = YES

---

## 5. Resource discipline

广泛发现，狭窄加载，最小执行，明确持久化。

Discover broadly.
Load by scope.
Execute by necessity.
Persist by authority.

Discovery reads metadata only. Scope is resolved before loading. Deterministic execution is preferred before LLM calls. Every output has an explicit persistence class.

---

## 6. Authority boundary

- One authority per fact class.
- Model output is proposal-only.
- Runtime is the only formal commit owner.
- No silent mutation.
- Every formal review binds exact revision/hash.
- Checkpoint is not Artifact commit.
- Input/currentness changes invalidate dependent review/evidence according to owning rules.
- Product-shell convenience must not weaken Authority / Permission / Persistence / Promotion hard floors.

Detailed invariants remain owned by `PROJECT_SOURCE_RUNTIME_HARD_INVARIANTS_v0_1.md`.

---

## 7. Pack boundary

Pack 是可选能力包，不是产品壳，也不是 Runtime Core；普通 Core Chat / Project 在零用户 Pack 状态下仍必须完整可用。

A user Pack may own:
- Workflow
- Skills
- Rules
- Deterministic Executors
- Adapters
- Domain Schemas
- Fixtures / QA
- optional domain/cross-domain product behavior behind shared contracts

Pack must not reimplement LibreChat/Runtime-owned Chat, Project, Memory, Library, MCP platform, generic Agent engine, generic Skill engine, provider gateway, Authority, permission, Promotion or rollback.

User Pack classes:
- `UNIVERSAL_PACK` = optional cross-domain capability bundle earned by multi-Project/domain evidence;
- `DOMAIN_PACK` = optional domain-specific capability;
- system-internal semantic components required for Core behavior are not user-installable Packs merely because historical implementation used Pack machinery.

Install / activation / deactivation / uninstall / exact revision pinning are owned by Pack Lifecycle. Project-local method graduation is owned by Pack Creation.

Pack creation is governed by `PROJECT_SOURCE_PACK_CREATION_PROTOCOL` 的 current promoted Stable Authority。
Pack update / installed lifecycle / multi-pack lifecycle is governed by `PROJECT_SOURCE_PACK_LIFECYCLE_AND_UPDATE` 的 current promoted Stable Authority。

WEB_R004_NE_PACK = YES  
PACKLESS_CORE_MODE_SUPPORTED = YES  
ALL_USER_PACKS_OPTIONAL = YES  
PACK_EXPANSION_USES_SHARED_WEB_DESKTOP_FOUNDATION = YES
PROJECT_EXPERIENCE_GRADUATION_NE_PACK_INSTALL = YES
PROJECT_EXPERIENCE_GRADUATION_NE_PACK_ACTIVATION = YES
USER_CONTROLS_PACK_INSTALL_ACTIVATE_DEACTIVATE_UNINSTALL = YES

## 8. Stable-source ownership map

This Architecture owns:

- Program North Star;
- current user-product working-name ↔ internal Runtime name separation;
- Developer Mode product-plane ↔ versioned source/promotion boundary;
- current product/platform layering;
- Web foundation ↔ Pack platform relationship;
- interaction plane ↔ Runtime/domain plane boundary;
- Project-first user workspace ↔ Pack-behind-Project product model;
- durable Project Context Continuity capability layering and scope boundaries;
- explicit Project context-policy modes and isolation semantics;
- Project Source curation/live-reference product semantics;
- Project-scoped Tool/Work inheritance floor;
- Project portability capability boundary;
- Project Experience layer taxonomy and user-visible terminology;
- storage/retrieval/injection/recovery capacity separation;
- Project-scoped native Skill/Agent/MCP/Local-Action composition boundary;
- Project experience graduation seam at architecture level;
- normal-user Windows shell / lifecycle contract and shell-technology replaceability;
- future collaboration security floor while implementation remains deferred;
- high-level sequencing.

Other owners:

- Hard integrity rules → Runtime Hard Invariants;
- material action / Stop-Loss / process learning → Process Improvement Source;
- user transition / rollover / result return → Handoff Source;
- external reuse/adoption → External Capability Assembly;
- new Pack creation → Pack Creation Protocol;
- Pack version/update/multi-pack lifecycle → Pack Lifecycle & Update;
- detailed engineering/model/update strategy → Runtime Development Strategy.

ONE_AUTHORITY_PER_FACT_CLASS = YES

---

## 9. Legacy compatibility boundary

This successor does not silently relax any existing TianxiaBo read-only / Shadow-only restriction that remains active elsewhere in project governance.

Until that domain-specific boundary is explicitly migrated to its own current Pack/Project authority:

READ_TIANXIABO = YES
SHADOW_RUN = YES
TIANXIABO_FORMAL_WRITE = NO
WRITE_CURRENT = NO
WRITE_CANON = NO
CHANGE_TIANXIABO_STATE = NO
PUBLISH = NO

This compatibility section is not a statement that TianxiaBo is the current active product lane.

---

---

## 10. Stable disposition

This v0.9 is the active Stable Runtime Architecture Authority.

It preserves the accepted v0.8 Product/Project baseline while separating Core Project completeness from optional capability extensions, clarifying Local Action provider/transport replaceability, reasserting user-controlled Pack lifecycle, and binding built-in guide currentness to promoted user-facing semantics.

WEB_R004 remains the shared product-foundation capability family, while current priority is transient state owned by current Project Instructions/Handoff rather than Stable Architecture.

Unproven product/process claims remain unproven: Long-Chat and larger-history/source scale acceptance, a complete cross-Project Artifact Shelf/Library surface, natural optional Project→Overlay→Skill/Pack graduation, end-to-end replacement parity among Local Action providers, and fresh-machine distribution acceptance remain unproven product claims.

PROJECT_SOURCE_RUNTIME_ARCHITECTURE_v0_8.md is historical superseded authority.

PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
