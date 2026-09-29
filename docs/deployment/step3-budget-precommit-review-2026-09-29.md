# 第 3 步额度与全站预算：本地验收与提交前审阅

日期：2026-09-29。范围：第 3 步后端额度/预算实现及其兼容性审阅；不进入第 4 步完整限流验收。

## 1. 结论与工作区边界

**本轮已修复 R1、R3、R4、R5 以及 R2 的输入/输出单次成本边界，并补充定向测试；仍不能认定完整冻结契约或生产发布验收通过。** deadline、上游超时及实际工作退出前保留槽位仍待后续阶段共同实现和验收。下文区分已修复、已验证和仍待验收；不进入第 4 步完整限流验收。

- 工作区：`D:\claudeCode\rag_kb-deploy`；分支：`deploy/production`。
- 开始审阅时实际执行了 `git status --short --branch`、`git log -1 --oneline`、`git show --stat --oneline HEAD`。
- 实测 HEAD：`918aaeb`，提交标题以 `test(deploy): record step5 proxy and Linux volume acceptance` 开头。本记录不是新提交，不生成或预测新的提交哈希。
- 当前第 3 步代码仍是未提交工作区差异；上一轮仅新增本记录，本轮在保留既有实现基础上继续修复并更新测试和记录。
- 当前 worktree Git 元数据再次核验为 `D:/claudeCode/rag_kb/.git/worktrees/rag_kb-deploy`；分支为 `deploy/production...origin/master [ahead 8]`。未更改任何其他 worktree。
- 未修改 `rag_kb-integration`，未回退、清理、暂存或提交既有改动。
- 第 2 步的 Docker/Nginx 配置、验收脚本、文档与 Linux 证据不变。它们不能作为本次预算改动的生产验收证据。
- 本记录不包含 `.env` 内容、证书、真实 API key、生产 reference、生产账本或敏感日志。

审阅依据：[冻结的匿名身份与额度契约](../api/anonymous-session-and-quota.md)，重点为第 3～6 节。其第 7 节的完整限流/并发/代理联验仍在本次范围之外。

## 2. 已实现且有定向回归证据的内容

| 内容 | 实现与测试证据 | 本次结论 |
| --- | --- | --- |
| 个人额度和全站问答准入 | `AnonymousSessionStore.admit()`；`test_sixth_default_ask_denied_and_cache_counts_only_real_calls`、`test_budget_competition_and_restart_persistence` | 同一账本、锁和提交边界；默认第 6 次 429；拒绝不改变计数；重启保留已提交计数 |
| 所有适用预算闸门 | `_exhausted()`、`record_attempt()`；`test_admission_and_snapshot_check_every_applicable_gate` | ask、总聊天、查询 Embedding 对所有模式生效；默认聊天闸门不约束 BYOK |
| BYOK 分类计数 | `test_byok_keeps_personal_count_and_uses_shared_ask_budget` | BYOK 不增加个人次数，增加全站 ask 及对应供应商尝试分类；切换模式保留默认次数 |
| 供应商调用前计数 | `question_budget()`、`ChatAttemptCallback`、`CachedEmbeddings`；真实 LangChain 链配合 mock 供应商 | 一次正常聊天只记录一次；实际调用前持久化；SDK 重试为 0 |
| 查询不自动分片 | `test_embedding_sdk_sends_one_unsplit_query_without_retries` 的 3 个 provider 分支 | 已安装的真实 Embedding SDK 对 2000 字符查询调用 mock client 一次，传入原始字符串 |
| 缓存及失败语义 | `test_qa_cache_hit_still_counts_a_new_embedding_miss`、`test_provider_failure_is_counted_without_refund` | 缓存仍记 ask，不虚增聊天；检索发生的 Embedding miss 仍计数；失败不退款 |
| 写盘失败与不确定结果 | `test_storage_failure_prevents_next_provider_call` | 准入、Embedding、LLM 记账失败均阻断后续供应商调用；模拟落盘后异常时不回滚账本并锁定不可用 |
| 并发预算竞争与跨日 | `test_concurrent_provider_attempts_cannot_exceed_limit`、`test_fractional_clock_reset_and_cross_midnight_accounting` | 预算并发不超额；个人/ask 归准入日，调用尝试归发起日；UTC 小数秒重置计算正确 |
| HTTP 契约 | `test_invalid_payload_never_admitted`、`test_invalid_byok_never_falls_back_or_charges`、匿名身份测试 | 非法参数为 400；同身份 ask/quota；成功与受控错误的 request_id body/header 一致 |
| 管理端点 | `test_admin_snapshots_and_reset_preserve_global_budget`、`test_anonymous_token_cannot_manage_budget` | 快照脱敏；个人重置幂等，不重置全站计数或身份期限；记录时间、操作者、目标摘要与 request_id，不记录原因正文 |
| 无默认 key 与空知识库 | `test_empty_library_and_missing_default_key_do_not_charge` | 分别 503 `service_unavailable` / `knowledge_base_unavailable`，准入前拒绝，不执行旧 Demo 检索回退 |
| 公开检索与健康探针 | `test_production_paid_probes_disabled_and_shallow_probe_is_free` | 生产 `/search`、深度/with_qa 探针禁用；浅探针显式传 `deep=False` |
| 配置与错误码 | 配置参数化测试、`test_all_literal_session_error_codes_have_public_messages` | 个人/全站日上限接受正整数；UTC、生产个人额度检查；当前代码抛出的字面量 SessionError code 均有消息映射 |

测试文件：[HTTP/引擎契约测试](../../tests/test_budget_contract.py)、[账本测试](../../tests/test_global_budget.py)。这里的并发测试仅验证预算计数原子性，不是第 4 步身份速率/并发验收。

## 3. 付费入口盘点

| 入口 | 当前调用路径 | 审阅边界 |
| --- | --- | --- |
| 公共 `/api/qa/ask` | `admit()` 成功后，在 executor 工作线程内建立 `question_budget()`，再执行 `engine.ask()` | 统一预算；底层缺失上下文默认拒绝已补齐，见 R1 |
| 公共 `/api/qa/search` | 非开发模式返回 403 `feature_disabled` | 不通过此入口开放生产付费检索 |
| 管理员 `/api/qa/health` | 禁止 deep/with_qa；生产浅检查传 `deep=False` | 不调用探针模型；不等于真实生产环境健康验收 |
| `/health`、suggestions、`/api/documents/library` | 配置/本地元数据路径，没有显式查询 Embedding 或聊天调用 | 静态调用路径审阅；`list_documents()` 仍可能初始化 SDK/向量库，不能描述为“从不初始化模型对象” |
| `/quota`、`/budget`、`/quota/stats`、个人重置 | 身份解析/账本读写 | 不调用供应商；管理接口继续要求 admin JWT |
| 管理员上传、异步上传、批量任务 | admin JWT + 默认关闭的 `ENABLE_DOCUMENT_MAINTENANCE`；任务执行与文档 Embedding 前再查开关 | 独立维护费用，不计入匿名预算；开窗不代表供应商账户费用已受本账本限制 |
| 离线工具/直接调用 QAEngine、Embeddings | 生产查询缺失上下文时拒绝；受信任工具可显式使用 `offline_provider_access(reason=...)` | 显式离线范围不是 HTTP 输入选项；需要独立数据、额度与供应商消费上限，不宣称计入公共预算 |

没有发现当前生产公共 ask 以外仍直接开放的匿名付费搜索入口；不据此证明管理员/离线费用受匿名账本限制。

## 4. 本轮修复状态及后续验收边界

### R1 — 已修复并定向验证：缺失预算上下文默认拒绝

- `require_query_context()` 在生产缺失预算上下文时抛出 `503 service_unavailable`；查询 Embedding、`QAEngine.ask()`、聊天 callback 和直接深度探针均检查。检索异常不会吞掉 `SessionError`。聊天 callback 不再只在入口有上下文时安装，因此执行边界再次漏传也不能静默跳过记账。
- `offline_provider_access(reason=...)` 是受信任离线工具的显式代码范围，退出即恢复；HTTP 不提供开启该范围的字段。显式开发模式可离线查询；已有预算上下文优先于离线范围，不能利用后者跳过公共计数。管理员文档维护使用 R3 的独立开关，不依赖匿名问答上下文。
- 证据：`test_production_missing_context_blocks_provider` 覆盖查询/ask/聊天边界；`test_context_lost_in_worker_is_not_an_offline_permission` 覆盖线程丢失上下文；`test_http_worker_missing_budget_scope_fails_closed` 人为移除 HTTP worker 范围，验证供应商调用为零、已准入 ask 不退款；显式离线范围/账本优先级另有测试。
- 上轮“无上下文 Embedding 仍调用 1 次”是修复前离线复现，不是当前行为。真实 HTTP `/ask` 原本已建立上下文，不能把上轮复现描述为已证明 HTTP 绕过。

### R2 — 单次输入/输出边界已修复；deadline 仍待后续

- 问题最长 2000 字符；服务端 `llm_max_tokens` 仅接受 1～800 的整数（含环境字符串），配置加载与启动预算校验均拒绝超限；客户端 payload 仍不能覆盖输出上限。
- `question_cost.py` 使用当前 ChatOpenAI 的 messages 转换规则，计算角色、提示、问题、上下文和 JSON 转义后的完整序列化字节数，上限 32 KiB。本机 HTTPX 0.27 使用 ASCII 转义 JSON，因此采用其较保守的 UTF-8 字节大小，同时覆盖未转义 UTF-8 表示；不是 tokenizer 或金额估算。
- 保留问题与提示，按原检索优先级（全局最近两个候选优先，再补多样性候选；限定文档路径保留检索顺序）选择能放入的完整分块；放不下的分块跳过，再检查后续候选。引用保留实际入选的完整分块，不显示被剔除内容。
- 检索、裁剪、缓存键、生成和引用共用同一证据快照；缓存键升级为 `bounded-evidence-v2`，完整内容、顺序、文件/页码等纳入 SHA-256，避免旧 200 字符前缀摘要导致引用失配。QA 缓存命中也先解析所需证据；测试强制查询 Embedding 缓存失效时，最近邻与多样性检索产生的两次尝试均计数，未发生聊天则不计聊天。
- Chat callback 在记账/供应商调用前再次校验完整 messages，超限直接拒绝。证据：`test_messages_fit_cost_cap_and_citations_match_selected_evidence` 对 default/BYOK 检查真实链的 SDK payload、当前 HTTPX 编码、引用、缓存及尾部内容变化；`test_oversized_complete_messages_rejected_at_chat_boundary`；`tests/test_question_cost.py`；输出配置边界测试。
- 未读取生产密钥配置，未核验实际部署的固定型号或账户消费上限。裁剪可能剔除必要证据，真实示例质量验收仍需另行安排。
- 缺少：60 秒问答 deadline、每次 Embedding ≤15 秒/聊天 ≤45 秒且不超过剩余 deadline，以及受控 `504 upstream_timeout`。当前 API 将供应商异常归为 `502 upstream_error`；错误码覆盖测试并不证明尚未抛出的 timeout code 已支持。
- `async with semaphore` 包围 executor await；若请求协程取消而线程仍工作，代码没有把槽位释放绑定到线程真正退出。此项为静态风险发现，本轮未执行取消/超时/身份并发验收。
- deadline 和工作任务生命周期需与第 4 步的并发语义一起设计、实现和验收；本轮没有增加 `wait_for()`，不声称响应超时代表供应商已取消或槽位安全。

### R3 — 已修复并定向验证：维护费用入口默认关闭

- 新增 `enable_document_maintenance=False`（环境变量 `ENABLE_DOCUMENT_MAINTENANCE`），认证管理员后仍须检查开关。覆盖同步 `/upload`、`/upload?async_processing=true`、线程池 `/upload-async` 和 `/batch-upload`，关闭时返回受控 `403 feature_disabled`。
- 线程池提交、线程池/BackgroundTasks 实际执行、向量写入与文档 Embedding miss 边界再检查；禁止把公共问答上下文借作文档导入权限。维护拒绝不会触发向量层的逐条重试。
- 证据：`test_closed_maintenance_rejects_admin_before_any_work` 的四种路由，拒绝时不调用文档处理器、不提交两种后台任务；`test_queued_maintenance_rechecks_window_before_processing`；`test_document_embedding_requires_window_or_explicit_offline_scope`。既有上传测试显式打开维护窗口。
- 开窗维护及显式离线文档费用不记入匿名查询账本，测试验证其公共计数不变。供应商维护白名单、费用记录与账户级消费上限仍需运营控制；不能声称本开关已经实现维护金额预算或核验生产维护窗口。

### R4 — 已修复客户端协议；完整浏览器验收未进行

- 管理页输入并验证 64 位小写 `quota_ref` 与 1～200 字符原因，按 JSON 提交；文案明确仅清该身份个人次数，不重置全站预算/身份期限，移除 IP/User-Agent 选目标的旧说明。
- 主页面与文档组件在默认/BYOK 模式都携带匿名身份及当前 BYOK headers 请求 `/quota`；共用 `quota_display.py` 展示 `available`/`exhausted`、UTC `reset_at`，区分个人次数与全站可用性。缺失预算状态不显示可用；数字直接采用服务端返回值。
- 文档组件补齐原先遗漏的匿名身份 Header/有界恢复。BYOK 不再提前返回“无限制”提示；个人关闭也继续展示全站状态。重置失败不输出原始 HTTP 内容，不自动重发。
- `tests/test_quota_frontend_contract.py` 的 13 项使用实际客户端函数配合 HTTP/UI doubles，覆盖两组件 × 两模式 × 两预算状态及重置 JSON/无效输入；既有 Streamlit AppTest 另纳入回归。这些不等于真实浏览器或 Streamlit 全流程验收。

### R5 — 已修复主机匹配和重定向策略；不是完整 SSRF 验收

- 取消字符串前缀判断，匹配解析后的 HTTPS scheme、IDNA/lowercase 主机、有效端口（缺省等价 443）、完整 base path；仅容许尾部 `/` 差异。白名单是 API base 列表，不隐式授权子域、子路径或其他端口。
- 拒绝 userinfo、空/非法端口、控制字符、反斜杠、百分号编码、点段、双斜杠、query、fragment 和主机尾点；DNS 失败/空集合/任何非公网或多播地址均拒绝。
- ChatOpenAI 的同步/异步 HTTP 客户端显式 `follow_redirects=False`。`tests/test_url_safety.py` 的 40 项覆盖匹配、非公网 DNS 和真实 SDK + 内存 HTTP transport 的 301/302/303/307/308（同步/异步），每次只请求白名单主机一次，不访问跳转目标；HTTP ask/quota 拒绝伪主机并不准入/不调用供应商另有测试。
- 上轮伪主机被接受是修复前 mock 复现，当前不再成立。没有真实 DNS/供应商请求用于上述新测试；DNS 检查与实际连接仍是分离步骤，未做 DNS 重绑定、网络出口或完整 SSRF 联验，不作全面安全验收结论。

### 明确未进入的第 4 步

身份滚动速率、单身份并发、任务真实退出前保留槽位、取消/timeout 后禁止后续供应商调用、Nginx 与应用限流/错误格式联验均未在本轮实现或验收。现有全局请求并发中间件仍返回旧字符串 detail；这属于后续统一服务繁忙契约的检查项。第 2 步已有代理和 Linux 持久卷证据保持原状。

**本轮已完成上述限定范围的代码补齐；不再把它们列为尚未实现。下一步先审阅最终差异与证据，再由用户明确授权是否创建第 3 步提交。R2 deadline/生命周期及第 4 步须单独安排，不自动开始。**

## 5. 本次复核环境、命令和结果

Windows 本地 Python `3.11.5`：`D:\Python311\python.exe`。本轮再次实测依赖版本：FastAPI `0.115.0`、Pydantic `2.9.0`、LangChain/core `0.3.0`、langchain-openai `0.2.0`、langchain-chroma `0.1.4`、pytest `8.3.0`、Black `24.8.0`、isort `5.13.0`、flake8 `7.1.0`、HTTPX `0.27.0`。

上一轮把缺失的 langchain-chroma 和 isort 安装到 `$env:TEMP\rag-step3-test-deps`，本轮先用 `Test-Path` 确认目录存在后复用；未安装新依赖，未更改 requirements 或系统 Python。另一台机器应使用完整、版本一致的隔离测试环境，不能直接假设临时目录存在。

### 定向回归

```powershell
$env:PYTHONPATH = "$env:TEMP\rag-step3-test-deps"
$tests = @(
  "tests/test_budget_contract.py",
  "tests/test_global_budget.py",
  "tests/test_api.py",
  "tests/test_demo_access.py",
  "tests/test_qa_engine.py",
  "tests/test_evidence_retriever.py",
  "tests/test_anonymous_session.py",
  "tests/test_quota_manager.py",
  "tests/test_cached_embeddings.py",
  "tests/test_vector_store.py",
  "tests/test_config.py",
  "tests/test_url_safety.py",
  "tests/test_question_cost.py",
  "tests/test_quota_frontend_contract.py",
  "tests/test_demo_frontend.py"
)
& D:\Python311\python.exe -m pytest @tests --no-cov -q
```

本轮最终实测：**447 passed in 67.09s**，退出码 0。使用临时账本/reference、mock 供应商和向量数据；部分测试使用真实 FastAPI 路由、LangChain 链/SDK、HTTPX 内存 transport 和 Streamlit AppTest，没有真实付费供应商请求，不是 Chroma/公网端到端或真实浏览器验收。

中间结果如实保留：R1/R5 初轮 120 通过、10 个重定向测试夹具失败（全局替换 HTTPX 类破坏 SDK 类型检查），局部替换工厂后通过；R2 初轮 170 通过、6 个旧检索假设失败，更新可迭代夹具和实际计数后相关 176 项通过；首次扩展 445 通过、2 个旧配置/SDK 参数断言失败，修正为 1～800 输出限制及零重试/不分片参数后，重跑同一 447 项全部通过。没有把失败轮次或修复前复现计作有效保护证据。

上一轮历史结果仍为原 8 文件 **273 passed in 26.26s**；它是修复前基线，不代表本轮新增边界当时已受保护。

### 格式、静态检查与编译

```powershell
# PYTHONPATH 先指向原临时依赖，再更换 formatter 的临时目录。
$env:BLACK_CACHE_DIR = Join-Path (Get-Location) '.pytest_cache\black-step3'
$env:TEMP = Join-Path (Get-Location) '.pytest_cache\step3-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:BLACK_CACHE_DIR, $env:TEMP | Out-Null
$files = @(git diff --name-only -- '*.py') +
         @(git ls-files --others --exclude-standard -- '*.py')
& D:\Python311\python.exe -m black --workers 1 --check @files
& D:\Python311\python.exe -m isort --check-only @files
& D:\Python311\python.exe -m flake8 @files --select=F
& D:\Python311\python.exe -m compileall -q @files
git diff --check
```

本轮对修改文件执行了 isort/Black 格式化。最终 Black、isort、F 类检查和编译全部退出 0；Black 报告 **30 个文件不需修改**。F 类检查指出的前端未使用导入/变量已移除，没有全局调整换行或治理整个仓库 E501。

首次 Black 已格式化部分文件后未退出，已中断；没有盲目循环重试。随后使用工作区内已忽略的 `.pytest_cache` 子目录承载缓存/TEMP/TMP，带 60 秒终止保护的检查正常退出，最终再检查通过。本轮没有使用提权。系统进程信息查询曾因权限被拒绝，但未影响上述替代方式完成检查。

本记录写入后再执行末尾 Git 检查。`git diff --check` 只覆盖受跟踪文件差异；新文件另做内容、换行和敏感材料人工审阅，不能把该命令当作新文件或密钥扫描器。

### 修复前两项离线复现（历史，不是当前行为）

上一轮执行方式：在同一 Python/PYTHONPATH 下，用 `unittest.mock` 替换缓存和供应商、DNS；当时不修改源文件、不连接外部网络。

1. `CachedEmbeddings`：缓存固定 miss；mock provider 返回 `[1.0, 0.0]`；`anonymous_storage_development=False`、`in_question_budget()` 为 false 时调用 `embed_query`。观察到 provider call count 为 1，返回向量。
2. `is_safe_base_url`：mock `socket.getaddrinfo` 返回公网 IPv4；传入 R5 的两个示例 URL。观察到返回 true。

这两项是**修复前缺口复现**，不计入历史 273 项或本轮 447 项通过数。本轮 R1/R5 的反向保护测试已替代这些过时行为结论，见第 4 节。

### 本轮没有验证的内容

- 未运行全量 pytest；使用 `--no-cov`，未验证仓库要求的 ≥70% 覆盖率。
- `flake8 --select=F` 只证明所选文件没有 F 类问题；未宣称完整 `make lint` 或 `make format && make lint && make test` 通过。仓库已有 E501 问题的整体治理不在本轮范围。
- 未执行 Docker Desktop、Linux 预算集成、断电持久化、真实供应商或公网 HTTPS 生产部署验收。
- 未核验生产有效配置或供应商账户级消费上限；不记录或推测真实密钥及生产 reference。
- 未执行浏览器/Next/Streamlit 全流程或第 4 步完整限流验收。

## 6. 待审核文件与提交说明草案

本次待审核集合扩展为 **30 个 Python 代码/测试路径，加本记录，共 31 个路径**。原有 14 个代码/测试路径均保留，在其基础上修复；不得使用未经核对的 `git add .`：

```text
app/api/anonymous_session.py
app/api/documents.py
app/api/qa.py
app/core/anonymous_session.py
app/core/async_processor.py
app/core/cached_embeddings.py
app/core/config.py
app/core/global_budget.py
app/core/qa_engine.py
app/core/question_cost.py
app/core/url_safety.py
app/core/vector_store.py
app/main.py
app/models/schemas.py
frontend/components/document_manager.py
frontend/pages/Admin.py
frontend/streamlit_app.py
frontend/utils/quota_display.py
tests/test_api.py
tests/test_cached_embeddings.py
tests/test_config.py
tests/test_demo_access.py
tests/test_evidence_retriever.py
tests/test_global_budget.py
tests/test_budget_contract.py
tests/test_qa_engine.py
tests/test_question_cost.py
tests/test_quota_frontend_contract.py
tests/test_url_safety.py
tests/test_vector_store.py
docs/deployment/step3-budget-precommit-review-2026-09-29.md
```

既有测试变更包括新 400/503 契约、显式离线/维护配置、实际检索计数、零重试/不分片 SDK 参数及输出硬上限。未改写第 2 步验收脚本或匿名身份测试。上一轮收尾曾对原 14 文件做 SHA256 比对确认未改写；该历史事实不适用于本轮主动修复，不能继续写为“本轮代码未变”。

供后续审阅的提交标题方向：`feat(quota): enforce shared budgets and per-question cost limits`。这只是草案，不是已创建的提交。说明应包含缺失上下文拒绝、维护闸门、URL/重定向修复和客户端协议；同时明确 deadline/生命周期及生产验收边界。不得使用“完整生产验收通过”或“公网已部署”等描述。

最终检查命令：

```powershell
git status --short --branch
git diff --check
git diff --cached --name-only
git diff --name-only HEAD -- docker scripts docs ':!docs/deployment/step3-budget-precommit-review-2026-09-29.md'
```

末尾核验：HEAD 仍为 `918aaeb`，暂存区为空；第 2 步 Docker/Compose/Nginx、脚本、文档与 Linux 证据对 HEAD 无差异；`git diff --check` 退出 0。工作区维持上述 31 条待审核路径。没有暂存或提交。

已知 Git 环境提示仍包括用户级 ignore 文件权限警告和 LF/CRLF 提示；它们不授权清理工作区。本轮不宣称全量测试/覆盖率、完整 `make format && make lint && make test`、公网部署或第 4 步验收通过。下一步由用户审阅最终差异，并明确授权是否创建第 3 步提交。
