# Project 原生文件检索与记忆闭合 — 官方复用证据和产品验收门槛（候选）

FACT_CLASS = NON_AUTHORITY_PRODUCT_DESIGN_AND_TEST_GAP
CURRENT_GIT_SOURCE_LINE = candidate/inquiry-desk-windows-product / R239 NONSHIPPING
BINARY_PUBLIC_RELEASE = BLOCK_DO_NOT_SHIP
PRODUCT_PASS = NO
PROGRAM_PASS = NO

## 目标
普通用户：新建 Project，保存 Instructions、Project Memory、多个 Chat，上传 PDF/DOCX，直接在相同 Project 中询问文件并得到有来源的回答；同 Project 旧 Chat 能精确检索，跨 Project 与其他账号隔离；数据可重启恢复、删除时仅清理独占字节。这些功能必须在单一 LibreChat UI 中工作，不另建第二套 Chat/Project Shell、Chat DB、Search DB 或自研 Skill/Agent 引擎。

## 已确认事实和上游成熟能力
- LibreChat v0.8.8 原生 Projects 提供 Instructions、关联 Chat 和参考 Files，Project 无默认模型；官方说明 File Search 依赖 RAG API 和文件索引角色权限。来源 https://www.librechat.ai/docs/features/projects
- LibreChat 原生 File Search 使用 vendor RAG API 对文档切块检索，并使用 PostgreSQL + pgvector；官方 Docker Compose 将 rag_api 和 vectordb 作为原生服务。来源 https://www.librechat.ai/docs/features/rag_api 与 https://www.librechat.ai/docs/configuration/rag_api
- RAG 官方 lite 镜像注册源 registry.librechat.ai/librechat-ai/librechat-rag-api-dev-lite，2026-10-31 只读 OCI index sha256:a62ce2221b43a9bb57fa6cb733e7047c80132960272c33d5704028f3071a1251；该 digest 仅是候选元数据，不代表已通过版本兼容、安全或安装验收。
- Pgvector 上游 docker tag pgvector/pgvector:0.8.0-pg15-trixie 为现有 LibreChat Compose 中采用的官方配置；本机 DockerHub digest metadata 直连失败，所以未取得、未猜测其可发行 immutable digest。
- 默认 RAG_API_URL 不能凭空启用；它需要真实 RAG service/vector DB，且文件 embedding 的服务端 API key/embeddings provider 必须明确配置。用户在 LibreChat UI 配的 user_provided 模型 key 不得默认为 RAG 后端可用的服务级 key。来源 https://www.librechat.ai/docs/configuration/rag_api
- 个人文档用于远程 embeddings 时存在隐私成本：必须由用户确认 provider 和效果域；未授权不得上传文档字节到外部服务。默认零 Packs 仍须能普通聊天，不能因 File Search 未配置而导致 Core 完全不能使用。

## 当前实证
- R229/R230 独立 Runtime API 测试：Project、Instructions、Chat、Memory、文本 Source、PDF/DOCX 解析和 Source 恢复均有 PASS，范围仅独立合成 HTTP。
- R239 原生 LibreChat projectChatRecall.js 正反模拟：搜索当前 Project 旧 Chat、读取准确消息 PASS，其他 Project/当前 Chat 读取拒绝 PASS；使用已有 LibreChat models 查询函数，不建第二个聊天存储。不是生产容器/真实模型回答 PASS。
- R239 当前仅有 librechat + mongodb + runtime-adapter 三个 Compose 服务，未配置 RAG_API_URL、rag_api、vectordb；不能称 Project File Search 已经运行，也不能把 Runtime Docling 文档解析等同于原生文件检索。
- R239 Project Memory 在独立 Runtime 存储中可读，但真正 LibreChat UI 发送消息时按 Project ID 注入 Memory 尚未验收。用户全局 Memory 不等于 Project Memory。

## 下一步不允许偷换
优先 CURRENT LibreChat 官方 Compose/RAG API + 自带 pgvector，**不是再发明一套自建向量 DB/文件索引/Notes**。以 pinned 官方镜像/依赖、明确 embeddings 提供商与费用/隐私同意为前提，最小化接入 Project File Search；评估已有 Runtime Source consumer 与原生 File Search 的冲突、重复存储、所有权和删除语义。每个 Project 仍只用一个逻辑身份。
必须在受支持的独立 Windows 用户环境验收：
1. RAG 与 PGvector 官方 SHA、来源许可证/层历史/运行兼容；服务健康和真实文件索引。
2. LibreChat Project UI 新建/Instructions/Files/多 Chat/Memory，文件上传 Ready，真实模型 File Search 与引用，以及关闭后恢复。
3. 同 Project 准确召回，跨 Project/其他账号隔离；被删除 Project 独占原文件、向量和 Runtime Source 正确清理，共享邻居独立保留。
4. 账号/密钥/隐私同意、数据安全更新/回滚和从 EXE 安装/卸载，真实 E2E 证明。此前阶段 PASS 不得提升为 Product PASS。

NO_CUSTOM_VECTORDB_BY_DEFAULT = YES
NO_SECOND_SHELL_OR_CHAT_STORE = YES
NO_SILENT_EMBEDDING_PROVIDER_OR_NETWORK_FALLBACK = YES
