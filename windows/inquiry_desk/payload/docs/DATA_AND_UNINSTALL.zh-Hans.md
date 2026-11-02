# Inquiry Desk｜卸载与个人数据保护说明（P4A rc1 原生 Project Files 候选内置）

**本候选尚未正式发布，以下是已实现的保护设计与仍需实机验收的界限。**

## 普通卸载：默认保留用户资料

1. Windows 设置 → 应用 → 已安装应用 → Inquiry Desk → 卸载，或开始菜单 → Inquiry Desk → 卸载 Inquiry Desk。
2. 卸载器先核对受控代码 SHA 和当前用户的软件归属，尝试停止本用户专属 LibreChat、MongoDB、Runtime Adapter、RAG、pgvector 服务及其 Runtime 进程；不能确认独占归属时必须拒绝高风险操作。
3. 卸载只删除其明确管理的程序代码、快捷方式、注册项，不调用 docker prune、down -v 或递归清空未知目录。
4. 默认保留本用户的 Project、Chat、Memory、Source、模型账号配置、上传文件和 Mongo/pgvector Docker 卷、Runtime 数据与受保护备份。这不是卸载失败，而是刻意避免丢失资料。
5. 卸载后不能自行把删除软件目录或 Docker 卷当成安全永久删除；重要资料应独立备份。

## 删除一个 Project 不等于卸载软件

C5 完整 Project 删除必须在明确二次确认后，清理该 Project 独占的 Instructions、全部已归属 Chat（包括归档）、Message/ToolCall、Project Memory、Source 原文与派生内容、文件/Blob/向量/CodeEnvironment，同时保留其他 Project、移出的 Chat、共享 Library 与全局记忆。完成回执必须独立验证物理字节缺失。

**目前 P4A 没有通过真实 C5 永久删除端到端验收。** 上游 LibreChat 的 Delete project 可能只是取消 Chat 归属，不能被当作不可逆擦除功能。不要用真实敏感资料试删。

## 删除所有个人数据

这是第三种独立的高风险生命周期，需要用户另外明确授权并证明独占所有权、备份、效果与恢复界限。本候选没有经过真实验收的“一键清空所有个人数据”入口。

## 更新、修复、回滚

为保护已有资料，当前版本遇到既有 Inquiry Desk 安装会停止覆盖。支持的修复、无损升级、回滚与迁移还需新机实测。不能通过强制卸载、清空数据卷或手动删目录来绕过该门槛。

**GitHub 的源码、CI 和 EXE 都不是 Project 资料备份。**
