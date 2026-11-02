# R242｜隔离原生 Project 删除接线与严格证明上限

STATUS = ISOLATED_NONSHIPPING_SOURCE_CANDIDATE
BASE_SHA = d816141cc8b576a15651cc640743c26b6113ba01
PRODUCT_GOAL = ONE_COMPLETE_LIBRECHAT_PROJECT_FIRST_WINDOWS_EXE
NO_REAL_USER_DELETE / NO_PRODUCTION / NO_GITHUB_PUSH / NO_STABLE_PROMOTION

## 实际工程增量

- `native/projects.js` 以原生 LibreChat 已有 Project Router 为唯一入口，正常的 List/Create/Get/Edit/Assign 五条路径不依赖 C5；对 DELETE 仅委派成熟 R006 Controller，绝不调用上游 unassign-only DELETE 作为 fallback。
- DELETE 要求新 UI 发出 `X-C5-Irreversible-Confirmed: C5_EXPLICIT_USER_CONFIRM_R242`；该标记不是权限，只证明显式用户确认意图；真实权限、运行中 Job、Writer、备份/恢复、Project Source/Memory/File/Vector 专属所有权仍由 R006/Runtime 逐个实际验证。当前预编译 v0.8.8 UI 尚未接入此标记，必须拒绝删除。
- `compose/docker-compose.c5-synthetic.override.yaml` 仅由隔离测试主动叠加，读取 frozen R006 精确源码，并覆盖原生后端 Project route/File/Code/Vector 文件；并未修改 R241 默认 Compose、80 行发行 manifest 或正在运行的用户产品。
- Node 路由测试与 Python SHA/合同测试只证明源代码接线、负例保护和 frozen R006 来源，不能声称实际界面运行成功。

## 当前无法被伪造的保护合同矛盾

安装产品 Runtime `c5-admission` 明确处于 `FORWARD_ONLY_DURABLE_RECEIPT_R001`，返回 `protectedBackupReady: False`，旧 per-delete backup API 返回 HTTP 410；成熟 R006 `readNativeInventory` 和 `verifyPreEffectBoundary` 仍要求 `protectedBackupReady === true`。不能硬改 true，不能以 Forward Receipt 冒充 Coherent Protected Backup。必须由既有 Runtime/C5 owner 完成对同一恢复保障合同的正式可验证统一，才能解锁真实不可逆效果。

另缺运行中的 `aidesC5WholeProjectDeleteOwners` 提供的准确 admissionOwner/referenceOwner；它必须证明目标 Project 的实时 Job/Writer、共享 Library/Agent/File/Blob/Vector、Sources/Memory 以及完整物理后状态。不能由路由名称、File.user 或零条数据库记录推断其完整性。

## 版本对照与保留策略

2026-10-26 官方 LibreChat v0.8.9-rc1 有向量按原记录命名空间清理与 Projects/文件更新，但官方 Project 删除仍只删除 Project 本身并取消聊天归属，不能替代整 Project 永久级联合同；保留 pinned v0.8.8，RC1 仅作为有界 donor/currentness 比较，不自动升级、不复制未审查源码。

## 目标 Program 全部仍须完成

Core Project Instructions / cross-Chat / Project-scoped Memory / native File Search+RAG+pgvector and provenance / editable Source and Artifacts / C5 permanent delete and shared-neighbor isolation / first install + model + Windows user journey / repair-update-rollback-uninstall / signed GitHub downloaded EXE installed bytes equality。阶段性脚本和源文件通过不能越级成为 Product 或 Program PASS。

PASS_SCOPE = ISOLATED_SOURCE_AND_NEGATIVE_CONSUMER_ONLY
PRODUCT_PASS = NO
PROGRAM_PASS = NO
PUBLIC_RELEASE = BLOCK
NOT_PROVEN = INSTALLED_NATIVE_BACKEND, BROWSER_CONFIRMATION_UI, CURRENT_OWNER_PROVIDER, BACKUP_RECOVERY_CONTRACT, FILE_VECTOR_GRAPH, SUPPORTED_WINDOWS_REAL_USER_E2E
