# Inquiry Desk｜普通用户安装与使用（R241 内部候选；不得作为正式版使用）
1. 双击 InquiryDesk_Setup_R241_NONSHIPPING.exe。该安装程序只安装产品代码、快捷方式和卸载入口，不安装你的私人数据。
2. 桌面双击 Inquiry Desk；若缺少 Microsoft WSL2、Docker Desktop、Python 3.12 或 Edge，会提示打开各软件官方安装网页。按厂家许可、UAC 和重启提示操作，然后再次点击同一个桌面图标，无需输入端口、容器名或 PowerShell 命令。
3. 首次组件准备按用户同意从精确版本摘要拉取 LibreChat、Mongo、Node 镜像，并从 PyPI 下载 SHA256 锁定的 Python 依赖。在线下载需联网、官方仓库可用以及足够磁盘空间。
4. Inquiry Desk 在 Docker Desktop 已安装但尚未运行时尝试自动启动，然后启动本地 Runtime、LibreChat 与用户独立数据卷，健康检查后打开 Edge 应用窗口。
5. 第一次在网页内创建自己的账号，配置自己的模型服务/API Key。安装包不自带开发者测试账号、Project、模型密钥。建立 Project 后可使用 Instructions、文件、历史聊天、Memory 和跨 Chat；这一完整用户流程尚须真实端到端验收。
6. 日常使用只需双击桌面快捷方式。若外部环境、镜像源或模型服务不可用，明确提示；绝不静默改用开发机、代理或未批准的执行器。

本候选仅供工程验收：本机静态检查或编译不等于 Windows 实际安装或 Project 全部功能 PASS。Win10 的厂家支持取决于实际系统、Docker Desktop/WSL 版本及微软服务期限；Windows Home 等系统不保证受当前厂商矩阵支持。日常使用不需要任何旧 Pack。

## 第一个账号安全收口（R228 候选）
第一次启动后在 LibreChat 网页创建第一个本地账号。程序在限定时间内检查本机专属 MongoDB 用户数，检测到第一个账号后将 ALLOW_REGISTRATION 关闭，并只重启本用户 LibreChat 服务，不会清空 Project 文件或 Mongo 数据卷；多账号异常时禁止继续宣称安全成功。正常关机或超时后可通过原桌面入口重试。此行为已做模拟验证，但尚未通过新安装实机验收。

R230 文档校验：本地 Runtime PDF 和 DOCX 两类合成文档已经通过实际解析、Project Source 保存和重启恢复测试；同时对错误的原生 JSZip 来源证明作拒绝测试。真实 Windows 新装与 LibreChat UI 的拖放消费仍需验收。

## 第一次连接 AI 模型（无需修改配置文件）
- 默认不预置任何开发者或测试账号、模型 API Key。LibreChat 官方 OpenAI、Anthropic、Google 端点配置为 user_provided，用户在自己的 Web UI 中输入密钥，密钥不会写入安装包。
- 首次登录后，在模型/Endpoint 选择器旁点“设置 API Key”（齿轮图标），或打开“设置 → Data & Privacy → API keys”，选择服务商后输入你自己申请的密钥。未填写有效密钥时，聊天模型不能正常回答，这是正常的使用前配置步骤。
- 想连接 Qwen、DeepSeek 等其他 OpenAI 兼容模型时，应使用 LibreChat 原生 Custom Endpoint 配置并自行提供对应密钥；不预置测试凭据，不额外开发第二套 Provider/Key 管理器。
- 模型 API 配置属于用户凭据，Project/Pack 身份与模型提供商身份互不等同。
- LibreChat 官方帮助：https://www.librechat.ai/docs/quick_start/first_chat

## 安装安全与更新状态（R241）
- 每次日常点击启动图标、卸载前，会对当前发行清单列出的所有程序文件重新计算 SHA256；文件被篡改时立即拒绝启动或卸载。
- **此版本仍不支持直接覆盖升级**：如果检测到旧 Inquiry Desk 程序安装，安装器会终止而不是盲目覆盖程序文件、更新 owner.json 或删除任何 Project 数据。
- 已证明此严格阻断行为，但可回滚的完整升级/修复流程仍需受支持 Windows 真实机验收；不得误认为已实现无缝更新。GitHub 中的 Source、CI 和 Draft EXE 不是用户数据备份。
- LibreChat 原生 Project 文件检索需 RAG API 和 pgvector 的真实服务链，当前 EXE 尚未整合并验收；Docling 解析与 Runtime Source 不能被宣称为完全的原生 File Search。用户上传的重要文档仍应独立备份。
