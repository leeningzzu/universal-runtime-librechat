# Inquiry Desk - Windows 使用者安装与运行合同（候选，尚未最终验收）

面向普通用户的交付目标是一个 Windows EXE：双击安装，缺少必要环境时引导打开相应的官方下载安装页面，首次登录并创建自己的 Project，日常只需打开桌面快捷方式，卸载时明确保留用户数据。用户无需理解或操作 Runtime、MCP、端口、Docker 命令。

## 当前 R239 候选实际实现
- 环境检测与官方地址：Microsoft WSL2、Docker Desktop、Python 3.12、Microsoft Edge。缺少时在取得用户同意后打开官网，安装和许可/UAC/重启由厂商界面完成。当前尚不是全自动无人参与的环境安装器。
- 首次 Core：按固定 Docker 镜像摘要获取 LibreChat v0.8.8、MongoDB 与 Node；创建独立 Runtime/Docling Python 环境并按锁定 SHA256 下载其依赖。全部网络目标和新机器成功率尚未验收。
- 账号：首次由用户创建，程序生成独立随机密码学密钥；首次注册关闭流程仅在隔离模拟中过关，真实登录与服务重启未通过新机验收。
- 个人模型：LibreChat 原生 user_provided OpenAI/Anthropic/Google 端点，用户从内置模型/API Key 设置入口提供自己的密钥。任何测试模型 API Key 不进入 EXE。
- Project：Instructions、Chat/跨聊天历史、Project Memory、文本 Source、PDF/DOCX 文件、C5 受保护删除；本地合成 Runtime 接口测试已通过部分能力，但全新 LibreChat UI 联动、真实模型回答和真正的 C5 永久删除尚未验收。
- 日常运行：桌面快捷方式指向不带版本号的 InquiryDesk.ps1，代码检测并按需启动 Docker Desktop、Runtime、Compose 服务后打开 Edge 应用窗口。不同 Windows 用户/电脑的真实日常重启尚未验收。
- 卸载：Windows“已安装应用”或开始菜单内卸载，只删除受控程序文件，默认保留 Project/Chat/Memory、账号、上传文件、受保护备份和独立 Docker 卷。专门的“删除全部个人数据”二次确认流程尚未实现，不得暗中清空用户资料。
- Windows 10：本机 19045 只读代码检测可通过，不等于 Docker/Windows 10 Home 官方支持和完整产品首次安装验收。当前正式发行支持矩阵为未证明。

## 绝对不得对用户宣称
- 不能把 2 MB 文件大小当成整个 Runtime 安装体积。依赖和 Docker 镜像在线下载后仍会占用磁盘。
- 不能把 80/80 文件哈希、NSIS 成功或原生 Runtime 合成接口成功描述为完整 ChatGPT Project 等价、正式产品或 Program PASS。
- R239 NONSHIPPING EXE 是工程候选，未签名，不建议安装在有重要资料的正式使用电脑上。
