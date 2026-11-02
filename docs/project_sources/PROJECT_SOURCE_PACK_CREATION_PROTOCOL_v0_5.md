# Universal Runtime｜Project Source｜Pack Creation Protocol v0.5

STATUS = STABLE_PROJECT_SOURCE
AUTHORITY_STATUS = ACTIVE_STABLE_AUTHORITY
REVISION_OF = PROJECT_SOURCE_PACK_CREATION_PROTOCOL_v0_4.md
SUPERSEDES = PROJECT_SOURCE_PACK_CREATION_PROTOCOL_v0_4.md
PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
STABLE_PACK_CREATION_AUTHORITY = PROJECT_SOURCE_PACK_CREATION_PROTOCOL_v0_5.md
HISTORY_REWRITE = NO
MODEL_OUTPUT_IS_PROPOSAL_ONLY = YES
NO_SILENT_STABLE_SOURCE_MUTATION = YES

SEMANTIC_DELTA =
PROJECT_EXPERIENCE_DISTILLATION_CONSUMER
+ PROJECT_OVERLAY_FILE_HOME
+ CANDIDATE_PREVIEW_EVAL_PROMOTION_BOUNDARY
+ PRIVACY_DEIDENTIFICATION_BEFORE_REUSE
+ NO_AUTO_PROMOTE_INSTALL_ACTIVATE
+ REUSABLE_SKILL_HOME_DECISION
+ PORTABLE_SKILL_SOURCE_AND_RUNTIME_PROJECTION_SEPARATION
+ PROGRESSIVE_DISCLOSURE
+ TRIGGER_POSITIVE_NEGATIVE_HELDOUT_EVAL
+ WITH_SKILL_VS_BASELINE_TASK_EVAL
+ THIRD_PARTY_SKILL_SECURITY_COMPATIBILITY
+ CANDIDATE_ONLY_PROMOTION_HANDOFF

## 1. Purpose

定义 Universal Runtime 中“新 Pack 从 Creator Intent 到首次可用/可 Promotion Candidate”的稳定创建协议。

本协议负责回答：

> 一个新的领域 Pack 应该怎样开始、怎样缩小范围、怎样先复用已有能力、怎样与创作者确认方向、怎样用最小代表性 Slice 建立真实产品能力，并在通过验收后进入 Pack Lifecycle。

本协议不替代以下当前 owning Authorities：
- current promoted Runtime Architecture Authority；
- current Runtime Hard Invariants Authority；
- current promoted External Capability Assembly Authority；
- current Stable Pack Lifecycle & Update Authority；
- current Stable Handoff Authority。

上述 Sources 各自保持原 Authority。这里按 fact-class owner 绑定，不冻结 superseded version-qualified filename；point-of-use 必须解析 current promoted/stable owner。

NEW_PACK_CREATION_TRIGGER = YES  
CREATOR_INTENT_BEFORE_IMPLEMENTATION = YES  
CAPABILITY_MAP_BEFORE_REPOSITORY_CHOICE = YES  
EXISTING_INVENTORY_BEFORE_REIMPLEMENTATION = YES  
CREATOR_DECISION_BEFORE_MATERIAL_IMPLEMENTATION = YES  
FIRST_REPRESENTATIVE_SLICE_REQUIRED = YES  
BIG_BANG_PACK_IMPLEMENTATION_BY_DEFAULT = NO
PROJECT_LOCAL_METHOD_NE_GLOBAL_SKILL = YES
PACK_NE_SKILL = YES
SKILL_CANDIDATE_REQUIRES_INDEPENDENT_REUSE_CONSUMER = YES
GITHUB_DISCOVERY_NE_INSTALL_AUTHORITY = YES
NO_GENERIC_SKILL_ENGINE_OR_MARKETPLACE = YES
PROJECT_EXPERIENCE_DISTILLATION_IS_CANDIDATE_FIRST = YES
AUTO_OBSERVE_CAN_PROPOSE_BUT_NOT_PROMOTE = YES

---

## 2. Authority Boundary

Pack 是领域应用，不是 Runtime Authority Kernel。

新 Pack 可以拥有自己的：
- Workflow
- Skills
- Rules
- Deterministic Executors
- Adapters
- Prompts
- Domain Schemas
- Fixtures
- Domain QA
- Creator-facing workflow

但必须复用 Runtime-owned：
- Artifact identity
- Revision / SHA
- Job identity
- Pack identity / version binding
- Permission
- Load Plan
- Review binding
- Stale invalidation
- Persistence legality
- Model Policy authority
- Promotion
- Audit / provenance

PACK_CREATION_CANNOT_CHANGE_CORE_AUTHORITY_BY_DEFAULT = YES  
PACK_TYPES_MUST_NOT_LEAK_INTO_RUNTIME_CORE = YES  
EXTERNAL_TYPES_MUST_NOT_LEAK_INTO_PACK_CONTRACT = YES  
MODEL_OUTPUT_IS_PROPOSAL_ONLY = YES  
RUNTIME_IS_ONLY_COMMIT_OWNER = YES

若新 Pack 需要修改 Runtime Core Authority / shared contract：
STOP → 提供具体跨域证据 → 单独 Architecture Review。

---

## 3. Pack Creation Entry

当 Creator 表达新的领域目标，例如：

- “建立一个政府报告 Pack”
- “建立一个学术论文 Pack”
- “建立一个审评报告 Pack”
- “建立一个股票分析 Pack”
- “建立一个软件开发 Pack”

Controller 应识别：

NEW_PACK_CREATION_TRIGGER = YES

第一步不是写代码，也不是选择 GitHub 仓库。

先生成窄 Creator Intent：

CREATOR_GOAL =  
TARGET_USER =  
PRIMARY_INPUTS =  
PRIMARY_OUTPUTS =  
SUCCESS_CRITERIA =  
AUTHORITATIVE_INPUTS =  
MODEL_ROLES =  
DETERMINISTIC_ROLES =  
MATERIAL_HUMAN_DECISIONS =  
NETWORK_NEED =  
FILESYSTEM_NEED =  
PERSISTENCE_NEED =  
KNOWN_HIGH_RISKS =  
EXPLICIT_OUT_OF_SCOPE =

只询问会改变能力、权限、预算、输出、验收、持久化或创作者体验的问题。

ASK_ONLY_MATERIAL_QUESTIONS = YES

---

## 4. Capability Map

Creator Intent 明确后，把 Pack 拆成独立能力。

典型类别可包括：

- intake / parsing
- planning
- memory / state
- retrieval / research
- drafting / generation
- revision / audit
- deterministic computation
- data acquisition
- citation / provenance
- domain validation
- UI
- orchestration
- persistence
- export

每个 capability 单独分类：

EXISTING = Runtime/现有 Pack 已满足  
PARTIAL = 可复用，但存在明确缺口  
MISSING = 当前不存在

不要因为 Pack 最终需要很多能力，就一次性实现全部能力。

CAPABILITY_FIRST_NOT_REPOSITORY_FIRST = YES  
ONE_CAPABILITY_ONE_OWNERSHIP_DECISION = YES

---

## 5. Existing Runtime Inventory

外部搜索前，先检查 Runtime/已存在 Pack/已验证 capability。

目标是回答：

1. 哪些能力已经存在？
2. 哪些能力只需组合？
3. 哪些能力需要 Pack-owned domain logic？
4. 哪些能力才是真正 external gap？
5. 是否存在已通过 fixture/regression 的能力可直接复用？

如果现有 Inventory 已满足需求：

NO_EXTERNAL_GAP

不得为了“更完整”重复实现已有能力。

REUSE_VALIDATED_INTERNAL_CAPABILITY_FIRST = YES

---

## 6. External Prior-Art & Creator Decision

对真正的 MISSING/PARTIAL capability，调用 current promoted External Capability Assembly Authority。

流程：

Creator Intent  
→ Capability Map  
→ Existing Inventory  
→ External Prior-Art Discovery  
→ Candidate Comparison  
→ Creator Decision Brief  
→ 1–3 Hybrid Options

External review 必须 capability-first，不得先决定“哪个仓库成为 Pack”。

默认只做 metadata-first discovery；不得因 discovery 自动：
- clone
- install dependency
- import code
- grant permission
- change Runtime architecture

Creator Decision Brief 应说明：
- 外部已有能力
- 各候选 strengths / weaknesses
- Windows compatibility
- license/security
- side effects
- integration/removal cost
- Runtime-owned responsibilities
- genuine remaining gap

Creator 未明确方向前，不进入 material implementation。

CREATOR_DECISION_BRIEF_REQUIRED = YES  
HYBRID_OPTIONS_REQUIRED_WHEN_MATERIAL = YES  
EXTERNAL_REPOSITORY_IS_NOT_AUTHORITY = YES

---

## 7. Pack Creation Direction

Creator 明确选择后，冻结当前 Pack Creation Direction：

PACK_PURPOSE =  
PRIMARY_WORKFLOW =  
CAPABILITY_ALLOCATION =  
RUNTIME_OWNED =  
PACK_OWNED =  
EXTERNAL_REUSE_MODE =  
MODEL_PROFILE_REQUIREMENTS =  
DETERMINISTIC_EXECUTORS =  
PERMISSION_BOUNDARY =  
PERSISTENCE_BOUNDARY =  
HUMAN_DECISION_POINTS =  
KNOWN_LIMITATIONS =  
OUT_OF_SCOPE =

外部 reuse mode 由 current promoted External Capability Assembly Authority 拥有并在 point-of-use 解析；本 Source 不复制其枚举，避免版本漂移。FORK / WHOLESALE_ADOPTION 的额外架构与显式人工批准要求继续由该 owner 决定。

---

## 8. Runtime Internal Contract

material implementation 前，必须先定义 Runtime-owned boundary。

合同至少说明：

INPUT =  
OUTPUT =  
AUTHORITY =  
PERMISSION =  
LOAD_SCOPE =  
PERSISTENCE =  
MODEL_PROFILE =  
DETERMINISTIC_EXECUTOR =  
FAILURE / BLOCKER =  
PROVENANCE =  
REVIEW / APPROVAL =

Pack 不得把 provider/model 名称写死进业务 Schema。

PACK_USES_MODEL_PROFILE_NOT_PROVIDER_NAME = YES

Machine-verifiable facts 优先 deterministic executor。

DETERMINISTIC_FIRST = YES

---

## 9. Project experience graduation and Pack role classification

Project work may generate reusable methods, but Project facts and a Project method are not automatically global capability. Before creating any Skill or Pack Candidate, classify the smallest truthful home.

Graduation route:
- `PROJECT_FACT / DECISION / PRIVATE SOURCE` → remain Project Memory / Source / Artifact; never auto-promote.
- `PROJECT_METHOD` → `PROJECT_LOCAL_OVERLAY` while Project-specific or independent reuse is unproven.
- `NARROW_METHOD + INDEPENDENT_REUSE_CONSUMER` → `DEPLOYMENT_SKILL_CANDIDATE`.
- `COHERENT_DOMAIN_CAPABILITY_FAMILY` → `DOMAIN_PACK_CANDIDATE`.
- `CROSS_DOMAIN_METHOD + materially different independent Projects/domains + held-out evidence` → `UNIVERSAL_PACK_CANDIDATE`.

Universal Pack is optional; it is not Core Product and must not duplicate LibreChat/Runtime native/shared capabilities. Domain Packs are likewise optional and must not become Project identity.

Before a Universal Pack Candidate is created, classify each proposed capability as one of:
`LIBRECHAT_NATIVE | RUNTIME_AUTHORITY | PROJECT_LOCAL_OVERLAY | DEPLOYMENT_SKILL_CANDIDATE | UNIVERSAL_PACK_CANDIDATE | DOMAIN_PACK | DOCUMENTATION_ONLY | CASE_EVIDENCE | DELETE_AS_DUPLICATE`.

Prefer extracting methods from mature Project evidence and existing reusable packages rather than scaffolding a Universal Pack from scratch. Extraction must remove Project facts, secrets, provider identity, developer-machine paths, raw executor handles and Project-specific permissions.

PROJECT_FACT_NE_REUSABLE_CAPABILITY = YES  
PROJECT_LOCAL_METHOD_NE_GLOBAL_CAPABILITY = YES  
DOMAIN_PACK_NE_PROJECT_IDENTITY = YES  
UNIVERSAL_PACK_NE_CORE = YES  
UNIVERSAL_PACK_REQUIRES_CROSS_DOMAIN_EVIDENCE = YES  
EXPERIENCE_GRADUATION_IS_CANDIDATE_FIRST = YES  
NO_GENERIC_EXPERIENCE_COMPILER_BY_DEFAULT = YES

## 9A. Project experience distillation consumer

This is the product/process consumer that turns repeated Project operating knowledge into the smallest reusable Candidate. It does **not** create a Generic Experience Compiler or a new Pack factory.

Trigger only when natural Project work shows a materially reusable method, repeated avoidable user burden, or an explicit user request to preserve/reuse a method.

Required classification:

EXPERIENCE_SUBJECT =  
SOURCE_PROJECT_REFS =  
PRIVATE_OR_PROJECT_FACTS_TO_EXCLUDE =  
SMALLEST_TRUTHFUL_HOME = PROJECT_SOURCE / PROJECT_MEMORY / PROJECT_ARTIFACT / PROJECT_LOCAL_OVERLAY / SKILL_CANDIDATE / DOMAIN_PACK_CANDIDATE / UNIVERSAL_PACK_CANDIDATE  
INDEPENDENT_REUSE_CONSUMER =  
TRIGGER_CONTRACT =  
NONTRIGGER_CASES =  
WITH_VS_WITHOUT_VALUE_DIMENSION =  
HELD_OUT_CASES =  
PERMISSION_NETWORK_FILESYSTEM_BOUNDARY =  
PORTABILITY_SANITIZATION =  
PROMOTION_OWNER =

### Project-local Overlay home

A Project-local Overlay is not an installed Pack and not automatically a global Skill. Prefer storing it as a governed Project Artifact/Source containing:
- method purpose;
- trigger / nontrigger;
- procedure;
- Project-specific assumptions;
- authoritative Project refs;
- known limitations;
- revision/provenance.

It remains Project-scoped until an independent consumer exists.

### Skill Candidate home

When the method qualifies as a Skill Candidate and the current shell/runtime supports Agent Skills conventions, prefer:

SKILL.md  
references/  
scripts/  
assets/

plus governed evaluation artifacts:
- SKILL_TRIGGER_EVAL;
- SKILL_TASK_BASELINE_COMPARISON;
- SKILL_SECURITY_COMPATIBILITY_REVIEW when material;
- exact Candidate revision/manifest.

Runtime-specific lookup paths, Model Specs, hooks, MCP ids, provider names or invocation metadata are projections; they must not become the portable Skill source Authority.

### Pack Candidate home

A Domain/Universal Pack Candidate may contain only the capability family that earned that classification. Reuse the existing Pack manifest / Runtime Internal Contract / Skills / Rules / Executors / Adapters / references / fixtures / expected outputs / regression evidence. Do not create a second Pack DSL.

### Automatic assistance boundary

The system may automatically:
- notice repeated method structure from current Project work;
- compile a Candidate;
- remove or flag Project facts, secrets, provider identity, raw executor handles and developer-machine paths;
- merge duplicates;
- produce a before/after or with/without comparison;
- run deterministic/held-out evaluation within existing permission;
- present one Promotion brief.

The system must not automatically:
- overwrite Project Instructions or Stable Sources;
- Promote a Skill/Pack;
- install or activate a Pack;
- widen permission/network/filesystem scope;
- copy private Project material into a reusable Candidate without explicit admissibility;
- delete the Project-local predecessor because a reusable Candidate exists.

AUTO_CANDIDATE_COMPILE_ALLOWED_WHEN_TRIGGERED = YES
AUTO_PROMOTE_EXPERIENCE = NO
AUTO_INSTALL_EXPERIENCE = NO
AUTO_ACTIVATE_EXPERIENCE = NO
PROJECT_PRIVATE_FACTS_NE_REUSABLE_METHOD = YES

A Candidate is rejected or remains Overlay when no incremental value appears against the same/bounded task baseline.

## 10. First Representative Slice

新 Pack 第一次实现默认不追求“完整 Pack”。

必须选择一个最小但真实、有产品意义的代表性 Slice。

First Slice 必须同时满足：

1. 能验证 Pack 的核心领域差异；
2. 能复用 Runtime shared contracts；
3. 有 deterministic/可验证的 acceptance；
4. Scope 足够小，失败时能定位 ownership；
5. 不需要先建设 Generic subsystem；
6. 对最终用户具有真实价值，而非仅 scaffold。

示例：

Novel：
Teacher Source → governed operating-knowledge Candidate

Academic：
Research question + bounded evidence set → citation-grounded gap Candidate

Regulatory Review：
bounded applicant input + deterministic reproduction → discrepancy report

Market：
bounded price fixture → deterministic indicator result + provenance

FIRST_SLICE_MUST_BE_PRODUCT_MEANINGFUL = YES  
FIRST_SLICE_MUST_HAVE_ACCEPTANCE_EVIDENCE = YES

---

## 10A. Reusable Skill / Prompt capability packaging & evaluation

A Pack may own Skills and Prompts, but a repeated method is not automatically a Skill.

Before creating a reusable Skill Candidate, resolve the smallest correct home:

PROJECT_METHOD / PROJECT_LOCAL_OVERLAY
→ useful inside one Project or not independently reusable yet;

PROMPT_TEMPLATE
→ reusable wording/input scaffold without a separate task capability/resource lifecycle;

DEPLOYMENT_SKILL_CANDIDATE
→ independently reusable procedural capability with a named trigger and consumer;

EXTERNAL_SKILL_DONOR
→ third-party Skill considered for reuse/adoption;

MERGE_EXISTING_SKILL / NO_OP
→ existing capability already absorbs the need.

PROJECT_LOCAL_METHOD_NE_GLOBAL_SKILL = YES
PACK_NE_SKILL = YES
SKILL_CANDIDATE_REQUIRES_INDEPENDENT_REUSE_CONSUMER = YES

### Portable source and projection

When the current shell/runtime supports the Agent Skills convention, prefer a portable SKILL.md source and optional references/scripts/assets. Product-specific lookup paths, frontmatter extensions, hooks, tools, models or invocation semantics are runtime projections/adapters, not a second Skill Authority.

PORTABLE_SKILL_SOURCE_PREFERRED_WHEN_SUPPORTED = YES
RUNTIME_PROJECTION_NE_PORTABLE_SOURCE_AUTHORITY = YES
UNSUPPORTED_VENDOR_SEMANTICS_REQUIRE_EXPLICIT_REVIEW = YES

### Progressive disclosure

Reusable Skill Candidates should keep:
1. discovery metadata/name/description lightweight;
2. full instructions loaded only when triggered;
3. references/scripts/assets loaded only when needed.

Detailed material belongs in references rather than duplicating the same instructions in multiple surfaces. Relative references and bounded reference depth are preferred. Client-specific numeric line/token limits are compatibility guidance, not a universal quality score.

PROGRESSIVE_DISCLOSURE_REQUIRED_FOR_REUSABLE_SKILL_CANDIDATE = YES
SKILL_CONTEXT_BUDGET_REVIEW_REQUIRED = YES

### Trigger evaluation

The description is a trigger contract. It must state WHAT the Skill does and WHEN it applies.

Before a reusable Skill Candidate is accepted, evaluate on the intended runtime/profile:
- should-trigger cases;
- near-miss should-not-trigger cases;
- held-out cases;
- adjacent/competing capability cases when material.

Do not hard-code a universal “pushy” description or “always invoke when 1% relevant” policy. Different runtimes may under-trigger or over-trigger differently.

SKILL_TRIGGER_EVAL_REQUIRES_POSITIVE_NEGATIVE_HELDOUT = YES
SKILL_TRIGGER_TUNING_IS_RUNTIME_SPECIFIC = YES
UNIVERSAL_ALWAYS_INVOKE_POLICY = NO

### Task-value evaluation

A Skill that triggers correctly can still be useless.

Compare realistic tasks with and without the Skill, using the same or materially comparable inputs. Include known-good, known-bad/counterexample and held-out tasks.

Prefer deterministic assertions/checks first. Semantic/model grading is allowed only where deterministic checks cannot judge the target quality; it is not mandatory.

The Skill must earn material incremental value in at least one named consumer dimension such as:
- quality/correctness;
- reproducibility;
- rework reduction;
- user burden reduction;
- context/token efficiency;
- reliable use of bundled deterministic scripts/assets.

TRIGGER_PASS_NE_TASK_VALUE_PASS = YES
SKILL_TASK_EVAL_REQUIRES_BASELINE_AND_HELDOUT = YES
DETERMINISTIC_ASSERTIONS_FIRST = YES
NO_INCREMENTAL_VALUE_CAN_REJECT_SKILL = YES

### Scripts / tools / network / security / compatibility

External Skill discovery is metadata-only by default. A GitHub/registry entry is not install authority.

For third-party Skills, bind exact source/revision and resolve:
- license;
- trust/provenance;
- bundled scripts;
- network operations;
- tool dependencies;
- credential requirements;
- destructive actions;
- target runtime/platform compatibility.

Use the current External Capability Assembly owner for material third-party adoption decisions. Request only the minimum tools required by the Skill.

THIRD_PARTY_SKILL_REQUIRES_LICENSE_TRUST_SECURITY_REVIEW = YES
GITHUB_DISCOVERY_NE_INSTALL_AUTHORITY = YES
SKILL_TOOL_SCOPE_MUST_BE_MINIMUM_SUFFICIENT = YES

### Promotion handoff

Skill evaluation can produce a Candidate; it does not Promote.

A reusable Skill requires natural prospective evidence before Stable/Installed Promotion:
- materially different natural positives;
- a correct matched nontrigger/negative;
- actual consumer;
- FP/FN and burden/maintenance evidence;
- exact candidate/review;
- explicit human Promotion.

Pack Creation owns the first usable Skill Candidate inside the Pack. Current Pack Lifecycle owns later version pinning, update, staging, Promotion and rollback.

SKILL_CANDIDATE_NE_INSTALLED_OR_PROMOTED = YES
PACK_CREATION_HANDS_SKILL_CANDIDATE_TO_PACK_LIFECYCLE = YES
AUTO_INSTALL_SKILL = NO
AUTO_PROMOTE_SKILL = NO
NO_GENERIC_SKILL_ENGINE_OR_MARKETPLACE = YES

---

## 11. Complexity Budget

首次 Slice 在实现前必须声明 Complexity Budget：

NEW_RUNTIME_CORE_FILES =  
NEW_RUNTIME_SCHEMA =  
NEW_PACK_FILES =  
NEW_DEPENDENCIES =  
NETWORK_CALLS =  
MODEL_CALLS =  
NEW_PERMISSIONS =  
NEW_GENERIC_SUBSYSTEMS =  
ROLLBACK_COST =  
MAINTENANCE_COST =

默认目标：

CORE_CHANGE = 0  
GENERIC_SUBSYSTEM = 0  
NEW_DEPENDENCY = 0 unless proven necessary

如果 auxiliary/tooling complexity 超过 capability value：
STOP / RESCOPE。

---

## 12. Implementation & Acceptance Gates

默认顺序：

L0 STATIC / inventory / exact-input capture  
→ minimal Patch Candidate  
→ L1 deterministic targeted acceptance  
→ L2 native/local integration regression  
→ L3 live/model/external integration only when required  
→ L4 Promotion only when product/staging evidence requires

不得为了流程完整而强制所有 Pack 使用全部 Gate。

USE_LOWEST_SUFFICIENT_GATE = YES

任何 Patch 遵守：

ONE_TASK_ONE_PATCH_ONE_MANIFEST = YES  
ONE_PATCH_ONE_LOCAL_ACCEPTANCE = YES

如果发生失败，按 Project Instructions 的 Failure Class / Stop-Loss 处理。

---

## 13. Creator / User Experience

Pack 创建治理应尽量隐藏后台工程细节。

Creator-facing 默认流程：

1. 说清想做什么
2. 系统理解目标
3. 系统展示 Capability Map
4. 系统说明已有能力与外部 prior-art
5. Creator 选择方向
6. 系统实现 First Slice
7. Creator 只在 material decision / acceptance / promotion 介入

不要要求 Creator：
- 手工设计 Schema
- 选择 framework internal type
- 处理 SHA
- 维护 permission manifest
- 逐个批准机器可确定的行政步骤

NO_ADMINISTRATIVE_HUMAN_WORK_IF_MACHINE_CAN_PROVE_IT = YES  
HUMAN_SILENCE_IS_NOT_APPROVAL = YES

---

## 14. Pack Creation Artifacts

在 Pack 创建过程中，可产生：

- CREATOR_INTENT
- CAPABILITY_MAP
- EXISTING_INVENTORY
- EXTERNAL_REFERENCE_ASSESSMENT（需要时）
- CREATOR_DECISION_BRIEF
- PACK_CREATION_DIRECTION
- INTERNAL_CONTRACT
- FIRST_SLICE_DESIGN
- PATCH_MANIFEST
- FIXTURE
- ACCEPTANCE_EVIDENCE
- PROJECT_EXPERIENCE_DISTILLATION_RECEIPT（only when Project→Overlay/Skill/Pack graduation is triggered）
- PROJECT_LOCAL_OVERLAY_ARTIFACT（when the smallest truthful home remains Project-local）
- REUSABLE_SKILL_EVALUATION（only when Skill packaging/adoption is triggered）
- SKILL_TRIGGER_EVAL（should-trigger / should-not-trigger / held-out）
- SKILL_TASK_BASELINE_COMPARISON（with-Skill vs without-Skill）
- SKILL_SECURITY_COMPATIBILITY_REVIEW（when material）
- STAGING/PROMOTION evidence

但稳定 Project Source 不保存当前 Pack 的 transient SHA、Run logs、Candidate 状态或 Build Status。

TRANSIENT_STATE_MUST_NOT_ENTER_STABLE_PROJECT_SOURCE = YES

跨 Chat 时按 current Stable Handoff Authority。

---

## 15. Completion Criteria

一个新 Pack 不因“目录创建成功”而视为创建完成。

首次 Pack Creation 至少要求：

CREATOR_DIRECTION_CONFIRMED = YES  
PACK_OWNERSHIP_BOUNDARY_DEFINED = YES  
EXTERNAL_GAP_ASSESSED = YES  
FIRST_REPRESENTATIVE_SLICE_IMPLEMENTED = YES  
TARGETED_ACCEPTANCE_PASS = YES  
REQUIRED_NATIVE_REGRESSION_PASS = YES  
CORE_CHANGE_JUSTIFIED_OR_ZERO = YES  
DEPENDENCY_ADOPTION_JUSTIFIED_OR_ZERO = YES  
KNOWN_LIMITATIONS_RECORDED = YES

If Project experience graduation is triggered, additionally require:

EXPERIENCE_HOME_DECISION_COMPLETE = YES  
PRIVATE_PROJECT_FACTS_EXCLUDED_OR_EXPLICITLY_BOUND = YES  
INDEPENDENT_REUSE_CONSUMER_PROVEN_OR_OVERLAY_RETAINED = YES  
AUTO_PROMOTION_STATUS = NOT_PERFORMED

If the First Slice or Pack direction includes a reusable Skill Candidate, additionally require:

SKILL_HOME_DECISION_COMPLETE = YES
SKILL_PORTABLE_SOURCE_OR_RUNTIME_BOUNDARY_EXPLICIT = YES
SKILL_PROGRESSIVE_DISCLOSURE_PASS = YES
SKILL_TRIGGER_POSITIVE_NEGATIVE_HELDOUT_PASS = YES
SKILL_TASK_WITH_VS_WITHOUT_BASELINE_PASS = YES
SKILL_SECURITY_COMPATIBILITY_PASS = YES
SKILL_PROMOTION_STATUS = CANDIDATE_ONLY

These checks are conditional; a Pack with no reusable Skill seam does not manufacture Skill ceremony.

是否进入 L3/L4，由 Pack 风险和产品路径决定。

首次可用版本进入正式生命周期后，后续版本治理移交 current Stable Pack Lifecycle & Update Authority。

PACK_CREATION_NE_PACK_LIFECYCLE = YES

---

## 16. Stop Conditions

STOP and return to Controller if：

- Creator Intent 尚不明确却准备实现；
- capability map 尚未建立却准备选择仓库；
- Existing Inventory 未检查却准备重复实现；
- material external gap 尚未比较 prior-art；
- Creator 尚未确认 material hybrid direction；
- external types/provider types 将泄漏到 Pack contract；
- Pack 需要改变 Core Authority 但没有跨域证据；
- dependency/license/security/permission 未解决；
- First Slice 失去真实产品价值，仅剩 scaffold；
- implementation scope 从 First Slice 静默扩大为完整 Pack；
- tooling/automation complexity 超过当前 capability 价值；
- Pack creation 准备绕过 Runtime Artifact/SHA/Permission/Promotion authority。
- Project-local method 仅因重复几次就被直接升级成 global/Installed Skill，尚无 independent reuse consumer；
- Skill 只有结构/description PASS，没有 should-not-trigger / held-out / with-vs-without task evidence；
- third-party Skill 未绑定 exact revision / license / trust / script-network-tool-credential review 就准备安装；
- vendor-specific projection 被误当成 portable Skill source Authority；
- Pack creation 开始建设 Generic Skill Engine / Marketplace / auto-installer。
- Project 私有事实/Source/secret/raw executor handle 在未去除或明确许可时进入可复用 Skill/Pack Candidate。
- 一个 Project-local method 因“重复出现”就自动 Promotion/安装/激活，而没有 independent consumer、negative/held-out 与增量价值证据。
- Experience distillation 被实现成 standing background compiler/database，而不是触发式复用现有 Project Source/Artifact/Skill/Pack lifecycle。

---

## 17. Automation Boundary

本协议首先是治理流程，不要求当前实现 Generic Pack Factory。

只有在至少多个不同领域 Pack 的创建流程真实走通，并出现稳定重复模式后，才考虑自动化：

- Creator Intent wizard
- Capability Map generator
- Prior-Art comparison assistant
- Pack scaffold generator
- Fixture template generator
- Pack creation UI
- Skill packaging/eval helper only after multiple real Skill Candidates prove a stable repeated flow
- experience-distillation helper only after materially different Project→Overlay/Skill/Pack graduations prove a stable repeated flow

AUTOMATE_ONLY_AFTER_FLOW_IS_PROVEN = YES

禁止为了“以后所有 Pack 都方便”提前建设：

- Generic Pack Generator
- Generic Plugin Marketplace
- Generic Dependency Solver
- Generic Schema Generator
- Generic Adapter Generator

---

## 18. Authority Map

本协议负责：

NEW PACK IDEA  
→ CREATOR INTENT  
→ CAPABILITY MAP  
→ INVENTORY  
→ EXTERNAL ASSESSMENT  
→ CREATOR DIRECTION  
→ INTERNAL CONTRACT  
→ FIRST REPRESENTATIVE SLICE  
→ ACCEPTANCE  
→ FIRST USABLE/STAGING CANDIDATE

其他 Authority：

Runtime Architecture / Hard Invariants  
→ 系统边界与不可违反规则

External Capability Assembly  
→ 外部 prior-art、reuse mode、license/security、hybrid composition

Pack Lifecycle & Update  
→ Pack 创建后的版本、更新、pin、promotion、rollback

New Chat Handoff Protocol  
→ 跨 Chat transient state 承接

ONE_AUTHORITY_PER_FACT_CLASS = YES

---

---

## 19. Stable disposition

This v0.5 is the active Stable Pack Creation Authority.

It preserves Creator Intent, Capability Map, internal-inventory-first, external prior-art, First Slice, complexity budget, reusable Skill evaluation and Project experience graduation while adding an explicit Project experience distillation consumer.

Natural Project methods may become governed Overlay/Skill/Pack Candidates without creating a Generic Experience Compiler or making a hidden Agent the Project identity.

Unproven product/process claims remain unproven: Project→Overlay→Skill natural-use evidence, correct Project-local non-promotion, and later Domain/Universal Pack graduation remain product evidence to be proven; this Promotion establishes governance only.

PROJECT_SOURCE_PACK_CREATION_PROTOCOL_v0_4.md is historical superseded authority.

PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
