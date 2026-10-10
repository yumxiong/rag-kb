# Step 5 deploy 交接记录

状态（2026-10-07）：**代码已固定，可供 integration 接入**。后端代码交接点：`86de66966a0fbd505faeb1d3a054696c768c795b`，分支 `deploy/production`。冻结契约为 [`anonymous-quota-v1-draft.2`](../api/anonymous-session-and-quota.md)，正文提交 `0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`。本记录由后续纯文档提交归档，代码交接点不因此改变。本轮只创建本地提交，未推送远端，未修改 integration worktree。

| 提交 | 范围 |
| --- | --- |
| `28c5c2552389f498d03e4a4a709400d0eab3b04b` | 第 4 子步骤：身份限流、HTTP/问答并发租约、deadline、SDK 超时、Nginx 错误响应与代理超时、测试和隔离验收脚本 |
| `86de66966a0fbd505faeb1d3a054696c768c795b` | 第 5 子步骤：独立 Cookie 客户端额度隔离测试、移除 Streamlit 无效 WebSocket 初始化 |

前置历史包括 `da67133`（匿名身份）、`918aaeb`（代理与 Linux 卷验收）和 `8ba5c03`（共享预算与单问成本）。建议合并上述代码交接点及其祖先历史；若 cherry-pick，先核对已接收历史并按依赖顺序补齐，不能在尚无身份/预算实现的分支上只取最后两个提交。接入方记录最终 merge/cherry-pick 提交号和测试结果。

2026-10-07 复核：已比对第 4 子步骤只读源码快照与当前源码，仅叠加本轮两个代码文件；无网络 Linux 临时容器运行 `python -m pytest tests/ -q --cov-report=term`，**674 passed、0 skipped、覆盖率 80.62%**。第 4 子步骤 15 个目标文件 Black/isort/flake8 退出 0；新增测试文件三项检查于 2026-10-01 通过，本轮未变更。没有宣称全仓库 `make format && make lint` 通过，Streamlit 既有 lint 问题仍见验收记录。未执行推送。

本地复跑证据：`.step4-evidence/handoff-20261007-tests.txt`。`.step4-run/`、`.step4-evidence/` 保留但不入 Git；共享提交包括验收脚本和文档，不要求 integration 复制临时快照、账本或运行日志。真实供应商、云服务器持久卷/正常重启/备份恢复、公网 HTTPS 及完整双前端浏览器链路仍待后续阶段验收。

| 项目 | 交接约定 |
| --- | --- |
| 匿名身份 | 后端签发不可预测 token；Next 使用同源 HttpOnly Cookie，Streamlit 当前 session 以 `X-Anonymous-Token` 转发；管理员 JWT 独立 |
| `/ask` | `POST /api/qa/ask`，JSON `question`（最多 2000 字符）、可选 `max_sources`、`document_id`；BYOK 用约定的 `LLM-*` Header；成功 200 含 `request_id` 和引用 |
| `/quota` | `GET /api/qa/quota`，同一匿名身份及 BYOK 模式；返回 `quota_enabled`、`used_count`、可空 `daily_limit`/`remaining`、UTC `reset_at`、`has_custom_key`、`global_budget`、`request_id` |
| 错误 | 结构化 `detail.code/message/request_id`；个人额度 429 `quota_exceeded`、速率 429 `rate_limited`、全站预算 503 `global_budget_exceeded`、繁忙 503 `service_busy`、超时 504 `upstream_timeout`、供应商失败 502 `upstream_error` |
| 扣额 | 准入前拒绝不扣；原子准入后缓存命中、失败、超时均计一次，不自动退款；BYOK 免个人默认 key 次数但仍受全站预算 |
| 全站成本 | 单实例单 worker 的持久账本控制问答、聊天与查询 Embedding 次数；usage 金额仅估算，不作为放行闸门 |
| 限流和并发 | Nginx 与应用各自限流；全局 HTTP 与问答工作槽位、每身份一个工作任务；问答线程实际退出后才释放工作槽位 |
| 代理 | HTTPS Nginx `/api/*` 指向 FastAPI，根路径暂为 Streamlit；新前端先用独立测试入口，同源 `/api`；只有可信 Nginx 可转发客户端 IP |
| 限制 | Streamlit 和 Next 不保证共享同一访客身份；不自动重放 POST；仅单后端实例精确计账；真实供应商、云卷恢复、公网 HTTPS 和双前端生产链路未验 |

integration 按上述代码交接点及依赖历史接收，按冻结契约接入，不自行实现身份签发或额度判定。之后先做双前端本地联验，最后由 deploy 完成云服务器生产部署验收。后端阶段当前证据与边界见 [`step5-backend-review-2026-10-01.md`](step5-backend-review-2026-10-01.md)。
