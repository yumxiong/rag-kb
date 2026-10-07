# 第 5 子步骤：后端验收复核（2026-10-01）

范围：`deploy/production`，基准 HEAD `8ba5c03` 加保留的第 4 子步骤未提交改动。本记录属于整份 `step5-checklist.md` 的后端验收阶段，不代表整份计划完成或生产验收。

## 清单逐项核对

| 项目 | 现有实现与证据 | 本轮状态 |
| --- | --- | --- |
| 两身份隔离、同身份累计、429 个人额度 | `tests/test_anonymous_session.py`、`tests/test_budget_contract.py::test_sixth_default_ask_denied_and_cache_counts_only_real_calls`；新增两个独立 Cookie 客户端端到端测试 | 本轮 Linux 隔离测试通过 |
| 全站预算 503、阻止模型继续调用 | `tests/test_budget_contract.py::test_byok_keeps_personal_count_and_uses_shared_ask_budget`、`test_storage_failure_prevents_next_provider_call`、`tests/test_global_budget.py` | 本轮 Linux 完整测试通过 |
| 速率 429、并发 503 | `tests/test_budget_contract.py::test_identity_rate_windows_reject_without_budget_admission`、`test_global_question_gate_applies_across_identities`、`test_timed_out_question_keeps_worker_slots_until_thread_exits`；第 4 子步骤真实 FastAPI 单 worker + 临时 Nginx 本地联验 | 已有本地证据；不是生产联验 |
| 失败请求是否回滚额度 | 冻结契约第 4 节规定准入前拒绝不扣，准入后失败、超时、缓存命中均计一次，不自动退款；`test_provider_failure_is_counted_without_refund` | 清单措辞需按契约解释，非缺陷 |
| `/quota` 与 `/ask` 同一身份 | `test_real_ask_and_quota_share_identity_behind_proxy`；新增双 Cookie 客户端流程 | 本轮 Linux 隔离测试通过 |
| 重启保留额度和预算 | `tests/test_anonymous_session.py::test_header_identity_is_persistent_and_private`、`tests/test_global_budget.py::test_budget_competition_and_restart_persistence`；第 2 子步骤 Linux named volume 重启验证 | 已有本地证据；云主机卷与恢复另验 |
| 管理统计脱敏 | `tests/test_budget_contract.py::test_admin_snapshots_and_reset_preserve_global_budget` | 已有覆盖 |
| BYOK 契约 | `test_byok_keeps_personal_count_and_uses_shared_ask_budget`、`test_invalid_byok_never_falls_back_or_charges` 等 | 已有覆盖；真实供应商未验 |
| 代理 Header 与访客隔离 | 第 2、4 子步骤真实 Nginx → Uvicorn 本地联验；新增独立 Cookie 客户端测试 | 本地证据已有；公网 HTTPS 待验 |
| 错误 JSON、Streamlit 示例和引用、旧 200 配额文本 | `tests/test_budget_contract.py::assert_error`、`tests/test_demo_frontend.py`；`/ask` 返回 429 `quota_exceeded` | Streamlit 5 项和后端完整测试本轮通过 |

## 本轮变动与验证

- 移除 Streamlit 首页对不存在的 `/ws/{client_id}` 的初始化；保留 Streamlit 自身 WebSocket。没有改动问答、身份或额度调用链。
- 新增两个独立 Cookie 客户端的 session → quota → ask 测试，断言各自累计、A 耗尽 429 后 B 仍有余额，以及引擎仅执行三次。
- `D:\Python311\python.exe -m pytest tests/test_demo_frontend.py -q --no-cov`：5 passed。本机后端测试因缺少 `langchain_chroma` 无法收集；之后启动 Docker Desktop Linux daemon，使用此前已验收镜像及只读源码快照，仅叠加本轮两个改动文件，在无网络临时容器复跑。
- 新增双客户端所在模块：11 passed。完整 Linux 套件：**674 passed、0 skipped、覆盖率 80.62%**，达到 70% 门槛。测试使用 mock/内存 transport，不调用真实供应商；这不是生产验收。
- 第 4 子步骤的 15 个静态检查目标在本轮 Black、isort、flake8 均通过。新增测试调整既有导入顺序后，Black、isort、flake8 也均通过。Streamlit 文件既有 flake8 问题不在本轮清理范围。

## 尚需完成

1. 2026-10-07 用户授权提交后，已固定代码交接点 `86de66966a0fbd505faeb1d3a054696c768c795b`，包含第 4 子步骤提交 `28c5c25`。完整 Linux 套件再次通过：674 passed、0 skipped、80.62%；第 4 子步骤静态检查通过。接收顺序和提交范围见 `step5-handoff.md`；不得从未提交工作区复制文件。
2. integration 接入后完成双前端本地联验。随后由 deploy 在云服务器验证真实供应商及生产账户消费上限、持久卷和备份恢复、正常重启、公网 HTTPS 与完整浏览器链路。不安排破坏性断电测试。

第 4 子步骤细节及隔离验收边界见 `step4-limits-local-review-2026-09-29.md`。现有 `.step4-evidence/`、`.step4-run/` 和 `scripts/acceptance/step4/` 均保留。
