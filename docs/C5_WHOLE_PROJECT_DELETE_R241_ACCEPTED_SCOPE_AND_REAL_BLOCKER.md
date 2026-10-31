# C5 全 Project 彻底删除：已接受合同、现有组件与真实缺口（R241）

FACT_CLASS = SUPPORTING_PRODUCT_SOURCE / NOT_STABLE_AUTHORITY / NOT_PRODUCT_PASS

## 已接受的用户操作合同
Project 删除须二次确认；只永久清理目标 Project 独占的 Project 身份、Instructions、Memory、活跃及归档 Chats、Messages、ToolCalls、SharedLinks、Sources/原文/衍生内容和独占 File/Blob/Vector/CodeEnvironment。保留移走的 Chat、共享或独立 Library File、其他 Project、全局用户记忆、受保护回滚与不含原始内容的审计证据。独立 Chat/File 的 30 天可恢复 Trash 是另外的生命周期，不能用它替代 Project 彻底删除。

## 历史真实失败不许改成 PASS
2026-10-24 的真实删除停在 PARTIAL_OR_BLOCKED：Mongo 原生 Project/Chat 已不存在，Runtime Project RETIRED/COMMITTED，但 4 份 Runtime Source、共 3,034 字节仍为 REMOVED_FROM_PROJECT/privacy_erasure=false，另有已标为保留的 File row/blob 不一致。旧 whole Project Product PASS 已被此自然消费者证据撤销。不得对该真实用户 Project 自动重试、继续删除或清理。

## R241 完成真值修复（非真实完整删除）
在现有 Runtime C5 回执持久化的 COMPLETE 之前，独立确认冻结的所有 Chats、仅独占 Files、全部 Runtime Sources 的永久擦除完成标记和物理原文/派生字节缺失，禁止误把共享文件当成目标删除。任何 UNKNOWN、来源未证明、数据重出现、漏删都拒绝 COMPLETE。当前实际 Runtime 模块 16 项合成正反测试 PASS，但只是完成真值保护，不代表全部原生删除效果 PASS。

成熟 R006 C5 原生 LibreChat 控制器、13-hook 级联、前端确认与测试，来自受保护源包 C5_CURRENT_FULL_PRODUCT_DELETE_SOURCE_R006.zip，原包 SHA256 c644f65e107ed6c949d2fa0d1d78a52c7ac1a1b3b1e5be3421075e4a37b27d35，重新逐字节收录到 native_c5_candidate/R006_mature_uninstalled。源包仍是 SOURCE_ONLY / NOT_INSTALLED；原生 Project delete 路由、File/Vector owner、Runtime 备份/Job/Writer 许可缺一就必须停止效果。

## 真实尚未通过的消费者
R241 正式打包的 GHCR LibreChat v0.8.8 Shell 目前没有安装此原生 13-hook Project Delete route，也没有证明运行时 aidesC5WholeProjectDeleteOwners resolver。真实 Project UI Delete、全部 Chat/File/Vector/Source 后效、共享邻居保留、备份一致与重启恢复、新 Windows 全流程均未通过。用户的真实 Mongo/Project 不得拿来做破坏性测试。不能使用清空目录、Docker prune、伪造回执或假省略文件的方式绕过 C5 法律归属和安全门槛。

NO_SECOND_SHELL = YES
NO_SECOND_CHAT_DB = YES
NO_GENERIC_GARBAGE_COLLECTOR = YES
NO_CUSTOM_VECTORDB = YES
REAL_PRODUCT_PASS = NO
