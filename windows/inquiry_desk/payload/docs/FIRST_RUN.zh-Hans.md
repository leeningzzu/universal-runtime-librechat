# Inquiry Desk｜Windows 安装、Project 使用与核验说明书

**版本：P4A LibreChat v0.8.9-rc1 原生 Project Files + R195 C5 隔离候选（NONSHIPPING）。属于上游预发布验证，不建议在存有重要个人资料的电脑上安装。**

本说明书已包含在安装器中。Windows 开始菜单 → Inquiry Desk → 帮助与安装步骤 可重新打开。普通用户不用操作 PowerShell、Docker 命令或端口。

## 一、产品与前提

- Inquiry Desk 使用一个 LibreChat Project/Chat 界面，Windows 桌面快捷方式用于打开同一产品；不需要任何用户 Pack。
- 安装 EXE 包含官方编译的 LibreChat 客户端与产品程序文件，但仍是**在线安装器**：不包含 Docker 镜像、Python 环境或本地大模型；首次使用仍需要下载安装依赖。
- 本软件不内置 ChatGPT 订阅、模型 API 额度、你的账户密码或旧聊天。普通聊天模型密钥与文件检索的 Embeddings 密钥是两套不同凭据。
- 此候选尚未通过受支持 Windows 新机的全量安装、真实 Project 对话、彻底删除和更新回滚验收，不能当成正式版。

## 二、双击安装与第一次打开

1. 在**独立测试 Windows 用户或电脑**上双击 InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.exe。为保护已有资料，安装器检测到同目录的已有版本时会停止覆盖安装。
2. 点击桌面 Inquiry Desk 快捷方式。若缺少 WSL2、Docker Desktop、Python 3.12 或 Microsoft Edge，程序会询问是否打开对应官方安装网站。按厂商许可、UAC 和重启提示操作后，再次点击同一个快捷方式。
3. 首次准备时，在明确许可后获取 LibreChat、MongoDB、Node Adapter、官方 RAG API 和 pgvector 五组固定摘要镜像，并安装 SHA256 锁定的 Runtime/Docling 依赖。
4. 安装入口尝试启动 Docker Desktop、个人 Runtime 和现有 LibreChat 应用，健康检查后用 Edge 应用窗口打开。镜像源、Docker 或网络不可用时，相关功能不会悄悄使用开发者电脑或其他执行器。
5. 在 LibreChat 内创建**第一个本机账号**。程序会尝试关闭后续公开注册；继续使用该账号登录。如果提示注册安全收口尚未完成，返回桌面入口重新检查。

## 三、配置普通聊天模型

1. 登录 LibreChat，打开模型/Endpoint 选择器旁的 API Key 设置入口，选择提供商，输入自己合法获得的密钥。
2. OpenAI、Anthropic、Google 在候选配置中采用 LibreChat 原生 user_provided 方式；其他模型要使用官方支持的 Custom Endpoint 配置，不能假设所有模型已内置。
3. 在不上传文件的普通 Chat 中询问一句话，先验证模型是否实际回答。没配置有效密钥或额度不足时，模型不会正常回答。
4. ChatGPT 的付费订阅不等于 API 额度，也不会自动成为本机模型或文件检索密钥。

## 四、完整 Project 使用顺序

1. 左侧 Projects → New project，创建一个测试 Project。
2. 打开 Project 后编辑并保存 Instructions。这些指令影响以后在该 Project 中发送的消息，不会改写以前的回答。
3. 进入 Project → New chat，连续建立两条 Chat，检查两条聊天都归属于当前 Project。
4. 用 Change project 将独立旧 Chat 移入测试 Project，或用 Remove from project 移出。移动与永久删除 Chat 是不同操作。
5. Project 的原生 Files / 参考文件区域已采用 LibreChat v0.8.9-rc1 的成熟界面与后端文件管理接口；用 Add files 上传一份无敏感内容的 PDF/DOCX 测试资料，检查文件列表、授权添加/移除和当前 Project 归属。文件检索索引仍需从 Processing 转为 Ready，并且当前 Chat/Agent 必须具有 File Search 权限。
6. 在同一 Project 的 Chat 中启用 File Search，询问刚上传文件里的具体内容，检查回答引用的来源，不要把解析完成或文件出现在列表里当成检索已经正常。
7. 另建一条 Chat，再测试是否真正准确取得旧 Chat 的消息，并验证其他 Project 的消息不能混入。Project Memory、Source 与跨 Chat 召回已有基础实现和部分隔离验收，但本候选的真实模型与 GUI 全流程尚未完成总体验收。
8. 关闭窗口、重新从桌面打开，核对 Project、Instructions、Chats 和 Source 的持续保存、读取与隔离。

## 五、配置 Project 文件检索（独立许可）

LibreChat 原生 File Search 需要 RAG API、pgvector 和 Embeddings 提供商。本候选已把 RAG/pgvector 作为同一产品组件装入安装配置，**但真实索引、权限与带引用回答尚未得到新机验收**。

- 首次安装后程序会询问是否要配置独立的 OpenAI Embeddings API Key。你可以拒绝或暂缓：这不影响无文件的普通聊天。
- 此后可通过 Windows 开始菜单 → Inquiry Desk → **配置 Project 文件检索**，使用现有启动器的密码输入框保存独立密钥。配置文件位于当前用户私有目录，不会与普通聊天模型的 user_provided 密钥混用。
- 远程 Embeddings 可能将上传文档的文本片段交给 API 提供商处理并产生费用；必须由你明确选择。ChatGPT 订阅没有自动附赠这项 API 用量。
- 当前内置向导只配置官方 lite RAG 的 OpenAI Embeddings；其他 Embeddings 提供商或本地向量模型未被本候选自动启用。
- 保存后重新打开 Inquiry Desk，再用**无敏感内容的测试文件**检查 File Search 是否 Ready、有实际回答与来源。服务未连接、角色权限不足或未配置 API Key 时，不能宣称完成。
- 官方帮助：https://www.librechat.ai/docs/features/projects 和 https://www.librechat.ai/docs/configuration/rag_api

## 六、永久彻底删除 Project 的重要限制

**目前 P4A 还没有完成 C5 真正永久删除的真实产品闭环，请勿试删任何真实资料。**

最终必须二次确认后，只永久删除目标 Project 独占的 Instructions、已归属与归档 Chat、Messages、Memory、Sources 原文与衍生内容、独占文件/Blob/向量和 CodeEnvironment；保留移出 Chat、共享或独立 Library 文件、其他 Project 与全局记忆，并独立验证物理内容已经不存在。

LibreChat 上游常规 Delete project 可能仅解除 Chat 归属，**不等于历史或文件已经永久擦除**。本候选复用 v0.8.9-rc1 原生 Project 文件界面与管理接口、R195 成熟 C5 不可逆删除前后端及 Writer/Runtime 所有权、跨存储清理，并保留 R241 更严格的实际物理擦除判定。**仍未在受支持的独立 Windows 上完成真实用户确认、Source/File/Blob/Vector 独占内容清除、共享资料保留及重启恢复验收，不得宣称永久删除成功。**

## 七、卸载、更新与数据保护

- Windows 设置 → 应用 → 已安装应用 → Inquiry Desk → 卸载，或使用开始菜单里的卸载入口。
- 默认卸载只停止本安装管理的组件，移除受控软件文件，不清空 Mongo、pgvector、上传文件、Runtime/Memory、凭据或备份。卸载不等于删除 Project 或删除个人数据。
- 本候选不允许直接覆盖升级；数据安全的修复、更新、回滚和迁移仍然是必须验收的产品功能。
- GitHub 仓库、程序安装包、CI 和安装日志都不是你的 Project 私人资料备份；重要资料仍应有独立备份。

## 八、常见问题

| 现象 | 处理建议 |
| --- | --- |
| 启动提示缺少 WSL、Docker、Python 或 Edge | 使用弹出的厂家官方安装页面完成安装，回到同一个桌面入口 |
| Chat 没有真实回答 | 先检查模型选择与对应用户 API Key、网络及额度 |
| 文件已上传但 File Search 不工作 | 检查独立 Embeddings 授权、RAG 服务和索引 Ready，不要误认 Docling 解析等于搜索 |
| 跨 Chat 没有引用到旧消息 | 检查聊天是否属于同一 Project，不能把历史存在等同精确召回 |
| 点击删除后项目不见了 | **不能把界面消失当作永久删除成功** |
| 程序 SHA 校验失败 | 不要手动替换受控文件；使用未来经验证的修复入口 |
| 已有安装被阻止覆盖 | 这是数据保护措施，目前尚无正式可用的升级/回滚入口 |

## 九、本候选的证据边界

已验证：官方 rc1 原生 Project Files / R195 C5 前端完整源码构建，以及原生文件接口、普通 Project 路由和删除安全拒绝的隔离测试。新 EXE 需以最终独立编译和实际解包 SHA 回执为准，不能因文件存在就宣称 Product PASS。

尚未验证：受支持新 Windows 电脑安装、真实模型回答、RAG 文件引用、Project Memory/跨 Chat 模型上下文、C5 永久删除与共享邻居保护、安全更新/回滚/卸载、公开签名和 GitHub 安装字节一致性。

**只有完整用户体验、数据安全和正式发行均验收通过，才能称为完整 Project EXE。**
