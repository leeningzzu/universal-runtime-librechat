# Inquiry Desk｜卸载和 Project 数据保护（R227 内部候选）
- Windows 设置 → 应用 → 已安装应用 → Inquiry Desk → 卸载；也可开始菜单 → Inquiry Desk → 卸载。
- 卸载前通过当前用户专属 Compose 标识停止本软件容器，不使用 docker compose down -v 或 docker prune；并且仅在明确确认 Python 进程属于本软件时停止 Runtime。
- 按发行清单删除本软件代码、快捷方式和卸载项；不递归清空未知目录。
- 默认保留 LocalAppData/InquiryDesk/Core_v088 下的账号密钥、Runtime/文档环境与项目元数据，以及 Docker 内独立的 Mongo/上传文件卷，方便重装或迁移；默认卸载不删除其他账号、Project、Chat、Memory、Library 或 Files。
- 真正彻底删除用户数据属于另一高风险动作，必须明确选择并完成独立备份、所有权和共享文件保护验收；当前内部候选不提供该破坏性功能，也不会谎称已经完成。
- 更新、修复、回滚以及从一个 Windows 用户迁移到另一台电脑仍需实际验收，才能公开发布。

R228 默认卸载只停止当前安装所有的容器和 Runtime 并删除受控程序文件，不清理独立 Mongo 数据卷与用户文件；C5 永久删除仅限用户在 Project 内明确确认的独占资源，并须通过真实新机测试，不能用卸载代替 Project 删除。

R229 数据所有权修正：Runtime 与 C5 原有 Job Authority 文件锁、Project Artifacts、机器本地解析器与备份收据统一存于个人数据目录（Windows LocalAppData/InquiryDesk/Core_v088/runtime），不再写入软件安装目录。卸载默认保留个人资料、Mongo/文件数据卷和受保护备份。原 LibreChat 界面、文件解析、模型配置和永久删除仍需新机验收后才能宣布正式可用。
