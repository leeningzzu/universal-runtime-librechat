# 依赖、第三方软件和来源边界

普通用户的 Inquiry Desk 安装器复用微软 WSL、Docker Desktop、Microsoft Edge、Python 3.12 的成熟安装软件；必要时从其官方页面引导安装。Docker 和 WSL 并未被这个轻量 EXE 内置。

产品唯一 UI 是 LibreChat v0.8.8，复用 MongoDB 官方镜像和 Node 官方镜像提供现有 Adapter 代码运行环境。确切仓库和 sha256 摘要在发行 payload 内的 manifest/upstream-pinned-sources.NONSHIPPING.json。用户首先需要联网获取受控的依赖。

此候选只确认了部分镜像 tag/digest 与本地旧验收信息。第三方源码版权许可证、二进制衍生构建来源、镜像层历史隐私、漏洞公告、官方仓库线上拉取及完整版本可维护性，都需要正式发行前独立验收。不得将这里的记录解释为版权许可证已经通过或者第三方物料适合公开商用分发。
