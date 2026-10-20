# Step5 部署基线收尾（2026-10-20）

首次部署已完成，进入小范围试用和维护阶段。本记录汇总此前执行结果及用户反馈；
2026-10-20 本轮仅审查、补充并提交文档，没有连接服务器、调用模型或重新运行验收。
下列运行状态依据此前记录与最近反馈，不是本轮实时服务器快照。

## 当前部署组成

| 项目 | 固定状态 |
| --- | --- |
| 入口 | `https://otocshow.xyz` 为 Streamlit；`https://next.otocshow.xyz` 为 Next |
| www | Dynadot 302 转发至 Next，由 DNS 服务商管理，不在应用 Nginx 签证或承载 |
| 主机布局 | `/opt/rag-kb`；仓库快照在 `repository`，data/config/secrets/state/证书位于仓库外 |
| 后端 | `rag-step5-backend:4d1ba85`，单 worker、单副本 |
| Next | `rag-step5-next:4d1ba85`，构建参数 `RAG_BACKEND_ORIGIN=http://backend:8000` |
| Streamlit | `rag-step5-streamlit:21271bf`，已修复包根目录搜索路径 |
| 代理与签证工具 | 固定 Nginx 1.28、Certbot 5.5.0，完整 ID 见交付清单 |
| 知识库 | 公开 AtlasDesk，9 文档、32 分块；text-embedding-v3，1024 维，独立索引目录 |
| 聊天 | DeepSeek deepseek-flash；保留既定切片、批量与超时契约 |
| 账本 | 远端正式 data/quotas 为唯一有效账本，本地旧 reference 已封存，不得重新启用 |
| 金额准入 | 每 UTC 日 50 元保守预留，包含项目聊天、向量化、导入与验收；价格策略持续有效、人工调价 |

[固定交付清单](step5-fixed-delivery-manifest.json)保留原始 2026-10-17 包及
`current_image_overrides`。恢复部署必须叠加 Streamlit 补丁，不得仅使用旧镜像。
原服务器 repository 快照及后端/Next 源提交为 `4d1ba85`，Streamlit 源提交为 `21271bf`；
本地部署记录提交与应用构建提交分开追溯。文档提交不需要重建镜像。

## 完整记录与证据

1. [远端准备](step5-remote-preparation-20261017.md)：主机指纹、交付校验、镜像加载及账本暂存。
2. [ACME staging](step5-acme-staging-20261017.md)：两域名 HTTP-01 dry-run 成功。
3. [正式证书](step5-production-certificates-20261017.md)：两张独立单域名证书、信任链核验。
4. [启动前准备](step5-prestart-readiness-20261017.md)：凭据、账本最终切换、存储验证及配套备份。
5. [公网启动](step5-public-launch-20261017.md)：协议/API 验证及三次受限真实问答。
6. [续期运维](step5-renewal-operations-20261017.md)：真实 renew dry-run、调度命令及轮转验证。
7. [Streamlit 修复](step5-streamlit-import-fix-20261019.md)：旧错误复现、镜像内整页测试和真实浏览器渲染。

2026-10-19 用户手动确认服务器自动续期任务执行成功。2026-10-20 用户实测：
Next 与 Streamlit 在手机和电脑均可访问、回答、展示引用，在资料不足时拒答，并显示额度。
用户认为 Next 的整体及移动端体验更好，下一阶段优先优化 Next UI。
这些是用户反馈，不是代理重新采集的日志、设备矩阵或自动化测试结果。

此前公网 HTTP 200、WebSocket 101 和健康检查未发现 Streamlit 页面导入错误；
记录该覆盖缺口，不将旧结果描述为完整浏览器验收。后续修复验证和用户手动问答补充了证据。
没有宣称全范围历史前端 lint 通过、并发容量达标或生产真实账本回滚恢复通过。

## 保持不变的身份与预算契约

Next 依赖后端 HttpOnly、Secure、SameSite=Lax、Path=/api、无 Domain Cookie，
浏览器只访问同源 `/api`，不生成可信身份或执行预算准入。
Streamlit 在服务端页面会话保存匿名 token 并转发 X-Anonymous-Token，身份与 Next 独立。
用户观察到刷新后恢复 5 次，符合完整刷新/断线可能丢失身份的已冻结契约：新身份有新的
个人额度，原身份记录并未清空，全站次数和金额账本不会随刷新重置。本轮不修改该机制。

ask POST 不自动重试；准入后的失败、超时和缓存命中均计一次，不自动退款。
daily_limit/remaining 可为 null；匿名文档详情 401、公开 library 正常；不恢复旧 ws 路由。
50 元按配置价格预留，不是供应商最终账单的无条件上限，供应商变价需人工维护。

## 维护与恢复边界

两张正式证书首次签发到期日为 2027-01-15 UTC。续期每天北京时间 03:17 检查，
日志按日轮转、保留 14 份并压缩、仅 root 可读。继续每周及变更后人工检查执行结果与
证书有效期；不依赖到期邮件，不增加监控或外部通知。

管理员随机凭据保存在服务器 root 专用文件中；操作人员自行通过可信终端保管，
不贴入聊天或提交 Git。变更前停止账本写入并备份 data 与独立 reference；现有启动前备份
只代表当时状态。后续恢复不得回退已消费和未决金额，也不得并行启用本地旧账本。
暂无异机备份，每日本地备份调度未启用；主机损坏时本地备份也可能丢失。

## 下一阶段

本次提交作为部署记录收尾基线，保留 deploy/production 用于线上维护。
下一步经用户指令从该提交建立独立 `feat/next-ui-refresh` 分支/worktree，优先本地
公开模拟数据下进行视觉与响应式优化，不复制密钥、账本、运行证据或 integration 文件。
UI 修改保留认证、准入、超时与错误呈现契约；通过回归和审查后再独立构建、授权发布。
本轮没有创建新 worktree、推送、合并或改变线上服务。
