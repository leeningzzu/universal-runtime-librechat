# G3 - 从 GitHub 到用户 EXE 的产品发行验收门槛

> 这是 R241 历史 Gate 快照。当前 P4A rc1 R002 的 EXE、代码及真实证明上限见 [当前交付状态](CURRENT_DELIVERY_STATE_R001.md) 和 [NONSHIPPING 说明](../release/P4A_RC1_R002_NONSHIPPING_RELEASE_NOTES.md)。原 80/81 文件统计不得冒充当前 495/496 文件。GitHub DRAFT 上传是用户当前请求，但不等于签名、完整 Product PASS 或公开正式发行。

当前 R241 是 NONSHIPPING 候选。GitHub Remote 尚无可信绑定，不能声称已 push、已运行 GitHub Actions、已发布 Release 或完成了签名。

| 证明族 | R241 当前状态 |
| --- | --- |
| 单一 LibreChat 产品壳、Core 在零 Pack 条件正常使用 | 旧基线可继承；全新安装未完成 |
| NSIS 编译与实际 EXE 提取、真实启动脚本存在 | PASS - R231/R241 文件消费者 |
| SHA256 80 个发行源文件、81 精确卸载清单 | PASS - 候选源码与 EXE |
| 清洁 Windows Python 3.12 Runtime 52 个锁依赖 | PASS - 独立离线安装、真实 Project/Memory HTTP |
| 清洁 Windows Docling 49 个锁依赖 | PASS - 独立离线安装、真实 DOCX 转换 |
| 真实 Runtime Project Instructions、Chat、Memory、跨 Chat、Source | PASS - 局部合成 HTTP；非完整 UI |
| PDF/DOCX Project 原生 Docling Source | PASS - 局部合成 HTTP + 错误来源拒绝 |
| 受支持的干净 Windows 上首次安装 Docker/WSL/Python/Edge | NOT PROVEN |
| 首个账号、注册关闭、用户模型 API Key、真实回答 | NOT PROVEN |
| LibreChat 原生 UI 的完整 Project 文件/记忆/检索/删除 | NOT PROVEN |
| 真正 C5 永久删除与共享邻居保留 | NOT PROVEN，不能绕过旧受限效果批准 |
| 真实卸载/重新安装/修复/更新/回滚的数据保留 | NOT PROVEN |
| Windows 10 Home 与其他受支持 Windows 机器矩阵 | NOT PROVEN |
| 全镜像层隐私、来源许可证、SBOM、安全公告 | NOT PROVEN |
| Windows 代码签名与 SmartScreen 发行 | NOT PROVEN |
| GitHub Remote + Commit + CI + Release + installed SHA 链 | NOT PROVEN |
| Product PASS / Program PASS | NO / NO |

GitHub 提交仅为源代码入库；没有完成每个必要消费者的证据就不得自动 Promotion、合并、签名或发正式 Release。
