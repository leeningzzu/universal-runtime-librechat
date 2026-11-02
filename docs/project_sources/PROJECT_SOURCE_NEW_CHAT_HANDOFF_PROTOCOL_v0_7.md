# Universal Runtime｜Project Source｜New Chat Handoff Protocol v0.7

STATUS = STABLE_PROJECT_SOURCE
AUTHORITY_STATUS = ACTIVE_STABLE_AUTHORITY
REVISION_OF = PROJECT_SOURCE_NEW_CHAT_HANDOFF_PROTOCOL_v0_6.md
SUPERSEDES = PROJECT_SOURCE_NEW_CHAT_HANDOFF_PROTOCOL_v0_6.md
PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
STABLE_HANDOFF_AUTHORITY = PROJECT_SOURCE_NEW_CHAT_HANDOFF_PROTOCOL_v0_7.md
HISTORY_REWRITE = NO
MODEL_OUTPUT_IS_PROPOSAL_ONLY = YES
NO_SILENT_STABLE_SOURCE_MUTATION = YES

SEMANTIC_DELTA =
ACCEPTED_BASELINE_SET_TRANSPORT
+ INVALIDATION_SCOPED_REVALIDATION
+ NO_WHOLESALE_RECEIVE_REPLAY
+ BASELINE_PROOF_CEILING_TRANSPORT
+ HANDOFF_FIELD_DEDUPLICATION
+ SINGLE_CANDIDATE_DISPOSITION
+ MATERIAL_ROUTE_STATE_TRANSPORT
+ ROUTE_STATE_RECEIVE_ACCEPTANCE
+ FORMAL_NEXT_ACTION_ROUTE_CONSISTENCY_CHECK
+ SUPPORTING_EVIDENCE_NE_ROUTE_AUTHORITY
+ TRANSIENT_ROUTE_STATE_NOT_STABLE_SOURCE
+ PROGRAM_SCOPE_TRANSPORT
+ PASS_SCOPE_AND_OPEN_PROGRAM_PLANES
+ REQUIRED_SUCCESSOR_CONTINUITY
+ HANDOFF_PROGRAM_SCOPE_RECEIVE_CHECK
+ USER_JOURNEY_WEBCODEX_AND_UPSTREAM_RETIREMENT_FIELDS


## 1. Purpose

定义 Universal Runtime 开发过程中跨 Chat 的稳定承接协议。

目标：
- 在重要 Milestone / Phase / capability 边界主动选择干净的新 Chat；
- 防止长上下文导致 stale evidence、状态漂移、重复执行和旧 memory 误判；
- 只携带下一步真正需要的 transient state 与 evidence；
- Stable Project Sources 不重复复制进每次 Handoff；
- 新 Chat 必须从实际 Windows evidence 恢复状态，而不是从聊天记忆推断 PASS。

CHAT_MEMORY_IS_NOT_STATE_AUTHORITY = YES  
PROACTIVE_HANDOFF_ADVISORY = YES  
HANDOFF_AT_NATURAL_BOUNDARY = YES  
DO_NOT_SPLIT_ATOMIC_EXECUTION = YES  
RECEIVE_CHECK_NE_WHOLESALE_PRODUCT_REGRESSION = YES  
ACCEPTED_BASELINE_INHERITS_UNLESS_INVALIDATED = YES

## 2. Source-of-Truth precedence

新 Chat 恢复状态时：

1. Actual local Runtime files / logs / Artifact / Manifest / SHA supplied by user
2. Latest NEW_CHAT_HANDOFF + BUILD_STATUS
3. Stable Project Sources + current Project Instructions
4. Previous Chat / memory only as context

Never infer a new PASS from old discussion when current execution evidence is absent.

Do not confuse this with replaying every previously accepted Product capability. Current Windows evidence is re-observed only for bindings required by the Handoff/current successor or for a declared invalidation/currentness conflict. Previously accepted baselines are inherited at their recorded proof ceiling unless their inputs/consumer/currentness are invalidated.

If Handoff conflicts with newer actual Windows evidence:

WINDOWS_EVIDENCE_WINS = YES  
→ STOP / RESCOPE before execution.

## 3. Proactive Handoff Trigger

Controller 应主动评估是否换 Chat，不要求用户提醒。

建议换 Chat 的自然边界包括：
- Phase / Milestone 完成；
- 新 Pack 或重大 capability 开始；
- deterministic development → first L3 live execution；
- L3 → L4 Promotion；
- Authority / Schema / Permission / Persistence / Job Pin / Model Policy 等重大边界变化；
- 下一步需要大量新 source/code analysis；
- 当前 Chat 已明显过长并增加 stale-context 风险。

不要声称知道精确剩余 token/context 百分比。  
使用保守启发式判断。

若当前 Patch/Gate 正在执行：  
先完成或 STOP 当前 atomic action，  
不得为换 Chat 而切断一次执行。

## 4. Exit Package

决定切换 Chat 时，旧 Chat 必须先生成：

1. NEW_CHAT_HANDOFF_<MILESTONE>_Rxxx.md
2. BUILD_STATUS_<MILESTONE>_Rxxx.md
3. NEW_CHAT_START_PROMPT
4. FILES_REQUIRED_FOR_NEXT_CHAT 清单

Handoff 必须保持紧凑，只保存恢复下一动作需要的 transient state。

NEW_CHAT_HANDOFF 应包含：

PROGRAM_NORTH_STAR =  
PROGRAM_PURPOSE_DIGEST =  
CORE_PRODUCT =  
OPTIONAL_CAPABILITIES =  
PROJECT_ROLE =  
PACK_ROLE =  
SHELL_ROLE =  
PROVIDER_ROLE =  
CURRENT_STAGE_PURPOSE =  
THIS_ACTION_ADVANCES_WHICH_PLANE =  
THIS_ACTION_MUST_NOT_CHANGE =  
CURRENT_PRODUCT =  
CURRENT_PHASE =  
CURRENT_STAGE_GOAL =  
STAGE_GOAL_NE_PROGRAM_NORTH_STAR = YES / NO  
PASS_SCOPE = ATOMIC / MILESTONE / PRODUCT_BASELINE / PROGRAM  
PROGRAM_PLANES_COVERED =  
PROGRAM_PLANES_OPEN =  
NOT_PROVEN =  
REQUIRED_SUCCESSOR =  
DEFERRED_BUT_REQUIRED =  
USER_VISIBLE_DELTA =  
WEBCODEX_TRIGGER_CLASS = NONTRIGGER / READ_ONLY_AUTO / EFFECT_REQUIRES_APPROVAL / NOT_APPLICABLE  
UPSTREAM_RETIREMENT_SEAM =  
PROJECT =  
CURRENT_DEVELOPMENT_MODE =  
PRIMARY_ACTIVE_PACK =  
CURRENT_MODE =  
LAST_CLOSED_MILESTONE =  
LATEST_WINDOWS_ACCEPTANCE =  
CURRENT_ACTIVE_CAPABILITY =  
ACCEPTED_BASELINE_REFS =  
BASELINE_PROOF_CEILINGS =  
CURRENT_DELTA_TOUCH_SET =  
INVALIDATED_BASELINE_REFS =  
REVALIDATION_SCOPE =  
NONINVALIDATED_BASELINE_INHERITANCE = PASS / FAIL / NOT_RUN  
CURRENT_MATERIAL_ROUTE_ID =  
CURRENT_MATERIAL_ROUTE_SUMMARY =  
UPSTREAM_NATIVE_BASELINE =  
NO_CUSTOM_BUILD_SET =  
THIN_SEAMS_TO_KEEP =  
PROVEN_CONTRACTS =  
EXACT_RELEVANT_BINDINGS =  
OPEN_BLOCKERS =  
DEFERRED_CAPABILITIES + REENTRY_CONDITION =  
KNOWN_SUPPORTING_GAPS =  
ROUTE_INVALIDATION_TRIGGERS =  
ROUTE_INVALIDATION_MATCHES =  
ACTIVE_MATERIAL_RISKS =  
FILES_REQUIRED_FOR_NEXT_CHAT =  
FORMAL_NEXT_ACTION =  
NEXT_EXECUTION_LOCATION =  
EXECUTION_DOMAIN =  
REQUIRED_EXECUTOR =  
EXECUTOR_BOOTSTRAP_REQUIRED = YES / NO  
EXECUTOR_BOOTSTRAP_TOKEN =  
SURFACE_REENTRY_ATTEMPT = 0 / 1  
SURFACE_FAILURE_FINGERPRINT =  
REASONING_LEVEL =  
DEEPSEEK =  
MODEL_PROFILE =  
TIANXIABO_FORMAL_WRITE = NO  
UNIQUE_NEXT_ACTION =

只记录与下一阶段相关的 exact SHA/evidence。  
不要复制全部历史日志。

BUILD_STATUS 只保存当前 transient engineering state，  
不得 Promotion 为 Stable Project Source。

## 5. What NOT to carry

默认不要重新上传：
- 已存在于同一 Project 的 Stable Project Sources；
- 完整旧 Chat；
- 所有历史 Gate logs；
- 已由最新 acceptance summary 取代的旧 evidence；
- cache/temp；
- API Key / secrets；
- 与下一动作无关的旧 Artifact。

只有下一步实际需要 exact bytes 时，  
才上传对应 evidence bundle / source snapshot / artifact。

## 6. Stable Sources vs Handoff

Stable Project Sources 保存：  
Architecture、Hard Invariants、Handoff Protocol、长期 Governance、  
Frozen Contracts、已批准 Development Strategy。

Handoff / Build Status 保存：  
CURRENT_PHASE、最新 PASS/FAIL、当前 SHA、Run evidence、  
当前 Candidate、临时 blocker、下一动作。

TRANSIENT_STATE_MUST_NOT_ENTER_STABLE_SOURCE = YES

## 7. New Chat Start

新 Chat 开始任何代码、PowerShell、DeepSeek、Desktop Work、  
依赖安装或 Runtime mutation 前，必须先读取最新 Handoff/Build Status。

第一响应必须返回：

HANDOFF_ACCEPTANCE_RESULT = PASS / FAIL  
HANDOFF_PROGRAM_SCOPE_CHECK = PASS / FAIL / NOT_RUN  
PROGRAM_NORTH_STAR =  
CURRENT_PRODUCT =  
CURRENT_PHASE =  
CURRENT_STAGE_GOAL =  
PASS_SCOPE =  
PROGRAM_PLANES_COVERED =  
PROGRAM_PLANES_OPEN =  
NOT_PROVEN =  
REQUIRED_SUCCESSOR =  
DEFERRED_BUT_REQUIRED =  
USER_VISIBLE_DELTA =  
WEBCODEX_TRIGGER_CLASS =  
UPSTREAM_RETIREMENT_SEAM =  
FILES_READ =  
SOURCE_OF_TRUTH =  
CURRENT_DEVELOPMENT_MODE =  
LAST_CLOSED_MILESTONE =  
CURRENT_ACTIVE_MILESTONE =  
LOCAL_VALIDATION_STATUS =  
ACCEPTED_BASELINE_RECEIVE_CHECK = PASS / FAIL / NOT_RUN  
ACCEPTED_BASELINE_REFS =  
CURRENT_DELTA_TOUCH_SET =  
INVALIDATED_BASELINE_REFS =  
REVALIDATION_SCOPE =  
NONINVALIDATED_BASELINE_INHERITANCE = PASS / FAIL / NOT_RUN  
CURRENT_MATERIAL_ROUTE_ID =  
ROUTE_STATE_ACCEPTED = PASS / FAIL / NOT_RUN  
ROUTE_CONSISTENCY_WITH_FORMAL_NEXT_ACTION = PASS / FAIL / NOT_RUN  
DEFERRED_CAPABILITIES =  
ACTIVE_MATERIAL_RISKS =  
FORMAL_NEXT_ACTION =  
NEXT_EXECUTION_LOCATION =  
EXECUTION_DOMAIN =  
REQUIRED_EXECUTOR =  
EXECUTOR_BOOTSTRAP_REQUIRED = YES / NO  
EXECUTOR_BOOTSTRAP_TOKEN =  
SURFACE_REENTRY_ATTEMPT = 0 / 1  
SURFACE_FAILURE_FINGERPRINT =  
REASONING_LEVEL =  
DEEPSEEK =  
MODEL_PROFILE =  
TIANXIABO_FORMAL_WRITE = NO

禁止从旧 memory 推断新 PASS。


### 7A. Program Purpose Rebind before material successor

A material successor must not be compiled from nearby Candidate availability alone. Before route-state continuity is accepted, the receiver must restore:
PROGRAM_NORTH_STAR / CORE_PRODUCT / OPTIONAL_CAPABILITIES / PROJECT_ROLE / PACK_ROLE / SHELL_ROLE / PROVIDER_ROLE / CURRENT_STAGE_PURPOSE / THIS_ACTION_ADVANCES_WHICH_PLANE / THIS_ACTION_MUST_NOT_CHANGE.

Minimum semantic defaults unless a current promoted Authority explicitly changes them:
- Core Product remains usable with zero user Packs;
- user Packs are optional installable/activatable/deactivatable/removable capabilities;
- Project is the user workspace, not a Pack;
- Provider is model access, not Shell/Project/Pack identity;
- current Shell is replaceable and must not be changed by a Provider or Pack decision;
- MCP is interoperability transport, not Runtime Authority;
- Local Action executor is replaceable and machine-local resolution must not become portable identity.

If the current action would silently change one of these roles, set `PURPOSE_REBIND_CONSISTENCY = BLOCK` and return to the owning Architecture/Process Source before implementation. A user reminder that re-establishes an already-active purpose rule is `POINT_OF_USE_PROGRAM_PURPOSE_CONSUMER_MISSING`.

PURPOSE_REBIND_REQUIRED_BEFORE_MATERIAL_SUCCESSOR = YES  
CANDIDATE_AVAILABILITY_NE_ROUTE_AUTHORITY = YES  
PROJECT_PACK_PROVIDER_SHELL_ROLE_DRIFT = BLOCK

### 7B. Material route-state continuity

If the sender had an established material route, the receiver must restore and accept it before compiling a material successor.

Minimum route state:

CURRENT_MATERIAL_ROUTE_ID
CURRENT_MATERIAL_ROUTE_SUMMARY
UPSTREAM_NATIVE_BASELINE
NO_CUSTOM_BUILD_SET
THIN_SEAMS_TO_KEEP
DEFERRED_CAPABILITIES + REENTRY_CONDITION
KNOWN_SUPPORTING_GAPS
ROUTE_INVALIDATION_TRIGGERS
ROUTE_INVALIDATION_MATCHES

Receive order:

CURRENT SOURCES / INSTRUCTIONS / EXACT HANDOFF
→ ROUTE_STATE_ACCEPTED
→ RECONCILE SUPPORTING EVIDENCE
→ ROUTE_INVALIDATION_CHECK
→ ROUTE_CONSISTENCY_WITH_FORMAL_NEXT_ACTION
→ ONLY THEN MATERIAL SUCCESSOR

A newer Source audit, local receipt, proof repair or other supporting artifact is not route authority merely because it is newer. If no declared invalidation trigger is matched, the receiver continues the current route. If a trigger is matched, the receiver returns the route to the Process owner for bounded re-evaluation before advancing.

Material route state is transient Handoff/Build Status. It must not be promoted to Stable Source merely to survive rollover.

ROUTE_STATE_ACCEPTED_REQUIRED_WHEN_ESTABLISHED = YES
ROUTE_CONSISTENCY_WITH_FORMAL_NEXT_ACTION_REQUIRED = YES
SUPPORTING_EVIDENCE_NE_ROUTE_AUTHORITY = YES
MATERIAL_ROUTE_STATE_TRANSIENT_ONLY = YES
NO_GENERIC_ROUTE_DATABASE = YES

Matched nontriggers: same-group read/search/test/diff/CI/delivery and supporting audits with no route-invalidation match.


### 7C. Program-scope receive / stage-ceiling continuity

If the sender had a material Program route or the handoff follows a Stage/Milestone/Product PASS, the receiver must restore Program scope before compiling the successor.

Required transient fields:

PROGRAM_NORTH_STAR
CURRENT_PRODUCT
CURRENT_PHASE
CURRENT_STAGE_GOAL
PASS_SCOPE
PROGRAM_PLANES_COVERED
PROGRAM_PLANES_OPEN
NOT_PROVEN
REQUIRED_SUCCESSOR
DEFERRED_BUT_REQUIRED
USER_VISIBLE_DELTA
WEBCODEX_TRIGGER_CLASS
UPSTREAM_RETIREMENT_SEAM

Receive order:

CURRENT SOURCES / INSTRUCTIONS / EXACT HANDOFF
→ HANDOFF_PROGRAM_SCOPE_CHECK
→ VERIFY STAGE_GOAL_NE_PROGRAM_NORTH_STAR
→ VERIFY PASS_SCOPE
→ VERIFY OPEN PROGRAM PLANES
→ VERIFY REQUIRED SUCCESSOR
→ VERIFY CURRENT MATERIAL ROUTE CONSISTENCY
→ ONLY THEN COMPILE MATERIAL SUCCESSOR

Fail closed when:
- `PASS_SCOPE` is missing;
- `PASS_SCOPE != PROGRAM` while material Program work remains but `PROGRAM_PLANES_OPEN` is missing/empty;
- `PASS_SCOPE != PROGRAM` while material Program work remains but `REQUIRED_SUCCESSOR` is missing;
- `CURRENT_STAGE_GOAL` is presented as equivalent to `PROGRAM_NORTH_STAR` without an explicit Program completeness receipt;
- a required Program plane present in the predecessor disappears from the successor without a declared route invalidation;
- the sender marked a user-burden/product-surface gap but the successor silently resumes domain expansion without closing or deferring it with exact re-entry.

On failure:
`HANDOFF_PROGRAM_SCOPE_CHECK = FAIL`
`NEXT_MATERIAL_ACTION = BLOCK`
`ROOT_CAUSE_CLASS = POINT_OF_USE_PROGRAM_SCOPE_CONSUMER_MISSING`

This check transports and validates transient scope state only. Handoff does not own the Program roadmap or recompile the route; current Project Instructions/user direction own current priority and Process owns material re-evaluation.

PROGRAM_SCOPE_STATE_TRANSIENT_ONLY = YES
STAGE_PASS_NE_PROGRAM_PASS = YES
NO_GENERIC_PROGRAM_ROUTE_DATABASE = YES


### 7D. Local-project executor bootstrap / host-surface re-entry

This subsection is interaction-owned. It does not select the executor itself; current Project Instructions / executor policy decide the exact required executor.

Predecessor compilation must set `EXECUTOR_BOOTSTRAP_REQUIRED = YES` only when all are true:
- the successor requires a new Chat or surface re-entry;
- `EXECUTION_DOMAIN = LOCAL_PROJECT_REQUIRED`;
- the selected current executor requires a conversation-host bootstrap/mention;
- that executor remains the legal minimum-sufficient local route.

When `EXECUTOR_BOOTSTRAP_REQUIRED = YES`:
1. `EXECUTOR_BOOTSTRAP_TOKEN` must be frozen in the Handoff. For the current WebCodex Local binding, the token is `@WebCodex Local`.
2. The successor user's **first message first line** must be that token, followed by the complete Handoff Acceptance prompt. This is host bootstrap, not new authorization.
3. Successor still performs Handoff Acceptance first. If Acceptance PASS and the frozen next action remains `LOCAL_PROJECT_REQUIRED`, the same assistant response must actual-invoke the required local executor. Discovery/schema lookup or prose saying “will invoke” is insufficient.
4. If actual invocation returns a host/conversation-level forbidden error (for example `This conversation does not support developer MCPs` or semantic equivalent), STOP only the local action. Do not blame the repository/product, revoke Project-wide authorization, silently substitute another-domain executor, or ask the user to run machine-replaceable local commands.
5. For the same `Handoff identity + Source/current-state identity + host-failure fingerprint`, allow at most **one** fresh Project-Chat surface re-entry. Carry `SURFACE_REENTRY_ATTEMPT = 1` and the same current identities.
6. If the fresh Chat returns the same host-level forbidden fingerprint again, set `HOST_ADMISSION_BLOCKED = YES` and STOP Chat churn. The next recovery owner is host/account/workspace admission, not another rollover.
7. If actual invocation succeeds, continue the same grouped local closure in that Chat/session. Do not mechanically rollover for each read/search/test/diff/build step.
8. `CHAT_RUNTIME_ONLY`, pure `REMOTE_READ_ONLY_REQUIRED`, and local work already bound to a live exact executor session do not bootstrap a new Chat.

ROLLOVER_THRASHING_FOR_EXECUTOR_BOOTSTRAP = NO  
ONE_FRESH_SURFACE_REENTRY_PER_SAME_FINGERPRINT = YES

### 7E. Accepted baseline inheritance / invalidation-scoped revalidation

If the sender carries an accepted Product/Core baseline, the receiver must preserve that baseline at its recorded proof ceiling before compiling the next material successor.

Minimum transient fields:

ACCEPTED_BASELINE_REFS  
BASELINE_PROOF_CEILINGS  
CURRENT_DELTA_TOUCH_SET  
INVALIDATED_BASELINE_REFS  
REVALIDATION_SCOPE  
NONINVALIDATED_BASELINE_INHERITANCE

Receive order:

EXACT HANDOFF / BUILD STATUS / CURRENT SOURCES  
→ ACCEPTED_BASELINE_RECEIVE_CHECK  
→ bind CURRENT_DELTA_TOUCH_SET  
→ determine which baseline inputs/consumers/currentness are actually invalidated  
→ revalidate only those proof families  
→ inherit every non-invalidated baseline unchanged at its existing proof ceiling  
→ continue current route.

Rules:
- a new Chat is not a reason to rerun Product acceptance already carried by the Handoff;
- a bounded config/code/content delta does not invalidate unrelated Project/Memory/Source/Agent/Skill/MCP/shell proofs;
- a health/hash/currentness probe may be required when the current successor depends on that exact binding, but it must not silently expand into a full Product regression;
- same-proof-family repetition improves currentness/reproducibility only; it does not raise the proof class;
- newer Windows evidence that contradicts a carried baseline invalidates only the affected baseline/consumer and then follows the normal STOP/RESCOPE rule;
- when accepted-baseline bytes or consumer semantics changed, Process owns the proof-dependency re-evaluation; Handoff only transports the set and renders the receive result.

Fail closed when a material successor would proceed while an affected baseline is known stale, or when a non-invalidated baseline is silently dropped from the successor state.

Do not fail merely because unrelated historical acceptance has not been rerun in the receiving Chat.

ACCEPTED_BASELINE_RECEIVE_REQUIRED_WHEN_CARRIED = YES  
REVALIDATE_ONLY_INVALIDATED_PROOF_FAMILIES = YES  
NO_WHOLESALE_PRODUCT_REPLAY_ON_CHAT_ROLLOVER = YES  
SAME_PROOF_FAMILY_REPEAT_NE_HIGHER_PROOF_CLASS = YES

## 8. Important Milestone Entry

如果 FORMAL_NEXT_ACTION 属于 Important Milestone，  
Handoff Acceptance PASS 后先执行 Project Instructions 要求的：

PURPOSE/WHY NOW  
DESIGNER RATIONALE  
CUMULATIVE MAP  
PROJECT ENGINEER  
PROGRAMMER  
MAINTAINER  
USER/OPERATOR  
RISK PROPORTIONALITY  
UNIQUE NEXT ACTION

Review 不能：
- 扩大 Scope；
- 修改 Authority；
- 自动安装依赖；
- 调用 Live Model；
- 创建未经证明的新 subsystem。

## 9. Step Protocol

每次只允许一个 UNIQUE NEXT ACTION。

每一步必须明确：

1. Execution location
2. Reasoning level
3. DeepSeek YES/NO
4. Model Profile if applicable
5. Complete copyable command/prompt
6. Preconditions
7. Runtime automatic actions
8. Expected output
9. PASS conditions
10. STOP conditions
11. Unique recovery action
12. Unique next action

Do not cross multiple phases in one instruction.

## 10. Desktop Work / External Review Boundary

ChatGPT Desktop Work 或其他外部 review environment  
仅在 Controller 明确设置相应 NEXT_EXECUTION_LOCATION 时使用。

External/Work memory is never formal state Authority.

正式 review 必须绑定：
- exact target SHA
- exact Review Bundle
- required provenance
- stale validation

外部模型输出 = proposal only。  
Runtime remains only commit owner.

## 11. Handoff Completion Rule

旧 Chat 只有在以下条件满足后才视为完成承接：

HANDOFF_FILES_CREATED = YES  
LATEST_ACCEPTANCE_RECORDED = YES  
TRANSIENT_STATE_SEPARATED_FROM_STABLE_SOURCE = YES  
FILES_REQUIRED_FOR_NEXT_CHAT_LISTED = YES  
NEW_CHAT_START_PROMPT_PROVIDED = YES  
UNIQUE_NEXT_ACTION_PROVIDED = YES  
PROGRAM_SCOPE_FIELDS_PROVIDED_IF_MATERIAL = YES  
HANDOFF_PROGRAM_SCOPE_CHECK_COMPILED_IF_REQUIRED = YES  
MATERIAL_ROUTE_STATE_CARRIED_IF_ESTABLISHED = YES  
ROUTE_STATE_RECEIVE_CHECK_COMPILED_IF_REQUIRED = YES  
ACCEPTED_BASELINE_SET_CARRIED_IF_ESTABLISHED = YES  
ACCEPTED_BASELINE_RECEIVE_CHECK_COMPILED_IF_REQUIRED = YES  
REVALIDATION_SCOPE_BOUND_IF_DELTA_EXISTS = YES  
EXECUTOR_BOOTSTRAP_COMPILED_IF_REQUIRED = YES

若缺任一项：

HANDOFF_RESULT = INCOMPLETE

## 12. Default New-Chat Prompt Template

If `EXECUTOR_BOOTSTRAP_REQUIRED = YES`, the **first line** of the user's new-Chat message must be the exact frozen `EXECUTOR_BOOTSTRAP_TOKEN` before any other text. With the current WebCodex Local binding, that line is:

`@WebCodex Local`

If bootstrap is not required, do not mechanically add an executor mention.

继续 Windows-local Universal Runtime。

请先读取本次上传的最新：  
1. NEW_CHAT_HANDOFF  
2. BUILD_STATUS

同时遵守当前 Project Instructions 与 Stable Project Sources。
若 Handoff 携带 Program scope fields，先返回 HANDOFF_PROGRAM_SCOPE_CHECK；不得把当前 Stage PASS 解释为 Program 完成。
若 Handoff 携带 ACCEPTED_BASELINE_REFS，先做 ACCEPTED_BASELINE_RECEIVE_CHECK；默认继承未被当前 delta / currentness / consumer 变化直接失效的 baseline，不得把新 Chat 自动变成全产品回归。

Source of Truth：  
1. 实际 Windows Runtime 文件/日志/Artifact/Manifest/SHA  
2. 最新 Handoff/Build Status  
3. Stable Project Sources  
4. 旧 Chat/memory 仅作上下文

禁止根据旧 memory 推断新的 PASS。  
Windows evidence 与 Handoff 冲突时，以 Windows evidence 为准并 STOP/RESCOPE。

开始任何代码、PowerShell、DeepSeek、Desktop Work、  
依赖安装或 Runtime 修改前，先执行 Handoff Acceptance。

如果下一步属于 Important Milestone，  
随后主动执行四视角 Entry Review + Risk Proportionality。

如果 `EXECUTOR_BOOTSTRAP_REQUIRED = YES` 且 Handoff Acceptance PASS 后下一步仍为 `LOCAL_PROJECT_REQUIRED`，
同一回复立即 actual-invoke frozen `REQUIRED_EXECUTOR`；不得只发现 schema、不实际 invoke，也不得再要求用户回复“继续”。

若 actual invoke 返回同一 host-level forbidden fingerprint：
- `SURFACE_REENTRY_ATTEMPT = 0` 时只允许一次 fresh Project Chat re-entry；
- `SURFACE_REENTRY_ATTEMPT = 1` 时停止换 Chat并升级 host/account/workspace admission；
- 不重传已 current 的 Stable Sources，不重复授权，不改用普通 web/remote executor 伪装 local exact evidence。

成功 actual invoke 后，同一 grouped local closure 尽量在本 Chat 完成；不要机械 rollover。

每次只推进一个 UNIQUE NEXT ACTION。

---

## 13. Stable disposition

This v0.7 is the active Stable Handoff Authority.

It preserves Source-of-Truth precedence, Purpose Rebind, material-route continuity, Program-scope/stage-ceiling continuity, executor bootstrap, bounded surface re-entry and user-transition semantics while adding accepted-baseline inheritance with invalidation-scoped revalidation.

It also removes duplicated Purpose fields from the Exit Package template and collapses duplicated historical disposition text. These editorial repairs do not change Authority ownership.

Unproven product/process claims remain unproven: A future materially different rollover must still prove that a receiver inherits a multi-capability baseline without user reminder and revalidates only actually invalidated proof families; newer Windows evidence must still be able to invalidate the affected baseline and force bounded STOP/RESCOPE.

PROJECT_SOURCE_NEW_CHAT_HANDOFF_PROTOCOL_v0_6.md is historical superseded authority.

PROMOTION_STATUS = PROMOTED_BY_EXPLICIT_HUMAN_APPROVAL
