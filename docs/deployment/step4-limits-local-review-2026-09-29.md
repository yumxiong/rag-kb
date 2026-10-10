# 第 4 步限流与 deadline：本地实现和验证记录

日期：2026-09-29。分支 `deploy/production`，起始 HEAD `8ba5c03`。本轮改动未提交。

2026-09-30 最新状态：Linux 容器完整测试命令已运行通过，**668 passed / 1 skipped，覆盖率 80.56%**；跳过项为缺少 Streamlit 的整个前端测试模块，不能称为全部测试零跳过。14 个第 4 步应用/测试文件的静态检查通过；既有验收 fixture 的 Black/flake8 未通过，原文件保留。详细范围与证据见末尾“Linux 完整测试补验”。前面各阶段的“尚未完成”按历史时点理解，不代表最新状态。

## 已实现

- `/api/qa/ask` 每匿名身份滚动 60 秒最多 6 次有效尝试；`/api/qa/quota` 每身份最多 60 次；`/api/session/anonymous` 每来源 IP 最多 30 次。拒绝返回 `429 rate_limited` 和同值 `Retry-After`，在预算准入前拒绝。
- 全局 HTTP 并发默认 20，请求完整响应结束前保持槽位；超额返回结构化 `503 service_busy`。问答工作默认全局 5、每身份 1；拒绝不扣额度。问答使用有界线程池，槽位绑定底层线程 future，超时或协程取消后直到工作线程真正退出才释放。
- 问答总 deadline 60 秒，查询 Embedding 单次最多 15 秒、Chat 单次最多 45 秒，客户端 timeout 同时受问答剩余时间约束。超时返回结构化 `504 upstream_timeout`。取消标记会阻止工作线程在检查点继续启动后续调用或缓存结果；已发起的同步供应商调用不能由 Python 强行中断，也可能已产生费用。
- 上述限流、并发和超时配置拒绝非正整数；总 deadline、Embedding、Chat 的环境配置不得超过 60/15/45 秒。
- 生产模板和 public-sim Nginx 配置含独立的普通 API、ask、login、session 限流，显式 `limit_req_status 429`，网关自身 429/502/504 的 JSON 错误体和 request ID；login 的 Retry-After 为 60 秒，其余为 1 秒。`/ask` 代理读取超时为 90 秒。后端返回的额度/预算错误仍由后端响应，不做网关错误页拦截。

## 本地验证

- `D:\Python311\python.exe -m pytest tests/ -q --cov-report=term`：**673 passed**，总覆盖率 **80.59%**，超过仓库 70% 门槛。另运行 `tests/test_step4_limits.py tests/test_budget_contract.py`：**158 passed**。使用 `$env:TEMP\rag-step3-test-deps` 中的临时测试依赖；供应商和网络请求均为 mock/内存 transport。
- 针对性测试覆盖身份/IP 滚动窗口、跨身份全局问答槽位、超时和取消后线程仍运行时的槽位保持、响应体未结束时的 HTTP 槽位、实际 LangChain/OpenAI SDK 请求的 timeout 参数、配置硬上限。
- 修改文件的 Black `--check`、isort `--check-only`、flake8（`--max-line-length=88 --extend-ignore=E203,W503`）、compileall 和 `git diff --check` 均通过。未执行会改写全仓库的 `make format`；未运行完整 `make format && make lint && make test` 序列。

## 尚未验收（首次 Windows 验证时的历史状态）

以下 Docker 访问失败为历史记录；手动审批后的实际结果见后续章节。当时尚未完成真实 FastAPI 单 worker + Nginx 的端到端联验、完整 Linux 测试及公网生产验收。

- Docker CLI 与 Compose 可用，但 Docker Desktop daemon 命名管道访问被拒；一次提权重试因自动审批服务返回 503 未执行。本机没有原生 Nginx，WSL 列表访问被拒。因此**没有执行 `nginx -t`，也没有完成代理层与应用层限流联验**。部署环境须用渲染后的 HTTPS 配置执行 `nginx -t`，再分别触发网关 429、502、504 与后端 429、503、504，核对 JSON、Header、登录等待时间及后端错误不被覆盖。
- 重启 Codex 后再次请求提权执行只读 `docker info --format '{{.ServerVersion}}'`，自动审批服务仍返回 `503 Service Unavailable: No available channel for the current group`（request id `202609291437099287060638268d9d6jAjSe8NX`），并明确表示 action was not executed。此次没有得到 Docker daemon 的新结果；`docker compose -f docker/docker-compose.yml config --quiet`、`docker ps`、容器启动及 `nginx -t` 均未执行。没有绕过审批，也没有读取生产 `.env`、敏感卷或日志。
- 本轮重新运行 Windows 定向测试 `tests/test_step4_limits.py tests/test_budget_contract.py --no-cov -q`：**158 passed in 49.47s**；修改过的 Python 文件经 Black `--check`、isort `--check-only`、flake8 与 compileall 检查均退出 0。一次未设置临时依赖 `PYTHONPATH` 的静态检查命令因 `No module named isort` 未完成，随后已使用正确依赖路径重跑通过。未在本轮重跑完整覆盖率测试，前述 **673 passed / 80.59%** 为此前同工作区的本地结果。
- 尚未进行真实供应商、Linux/Docker 预算集成、Streamlit/浏览器、断电持久化或公网 HTTPS 生产验收；未读取生产有效配置、供应商账户消费上限、敏感账本或日志。同步 SDK 调用和 OS 线程不能强制终止；极端卡死的供应商调用可能延迟关机，需在真实环境验证供应商超时与进程管理行为。
- 应用级分钟窗口和并发闸门是单进程内存状态；当前生产部署假设单 backend worker/replica。扩容为多进程或多副本前需要共享限流与并发协调方案及重新验收。

本记录仅证明 Windows 本地回归和代码边界；不能作为公网生产或 Nginx 联验完成的凭证。

## 手动审批后 Docker Desktop 隔离验收

日期：2026-09-29。用户切换手动审批后重试。本轮没有提交，没有修改 integration worktree，也没有读取生产 `.env`、API key、账本或敏感日志。

- 提权 `docker info --format '{{.ServerVersion}}'` 成功，daemon 版本 **29.7.2**；提权 `docker ps` 成功，验收开始时无运行容器。普通权限查询仍因 Docker 配置和命名管道权限被拒，与提权成功结果分别记录。
- 根目录 `.env` 仅检查存在性，未读取内容。设置 `COMPOSE_DISABLE_ENV_FILE=1` 后执行 `docker compose -f docker/docker-compose.yml config --quiet`，退出 0；这不是生产有效环境配置校验。
- 使用本机已有 `nginx:alpine`，将生产模板的 DOMAIN 渲染为 `step4.local`，启用模板证书选项 2，生成独立一天有效的自签测试证书。容器内 `nginx -t` 返回 syntax is ok / test is successful，退出 0。Nginx 镜像内无 openssl；本机 OpenSSL 证书生成也未成功，随后用已安装 cryptography 库生成测试证书。未读取任何已有私钥。
- 独立网络 `rag-step4-isolated` 上启动固定响应的 Python HTTP 测试上游和 Nginx，HTTPS 仅绑定 `127.0.0.1:18443`。网关联验配置由上述模板派生，仅将 `proxy_read_timeout 60s` 改为 `1s` 以快速触发网关 504；原模板的 60 秒等待未实测。
- 每路由并发请求 64 次，session / ask / login / general 分别观察到 **58 / 59 / 58 / 43** 个网关 429；均为 `rate_limited` JSON，Retry-After 分别为 **1 / 1 / 60 / 1** 秒，与 body 同值，X-Request-ID 与 body 一致。网关自身 502 / 504 的 JSON 和 request ID 检查通过。
- 固定测试上游的 429 `quota_exceeded`、503 `global_budget_exceeded`、504 `upstream_timeout` 及后端 request ID 原样保留；客户端伪造的 X-Forwarded-For 被 Nginx 覆盖。这证明代理转发行为，尚未证明 Uvicorn 可信代理配置下真实 FastAPI 的客户端 IP 解析。
- 现有 `docker-backend:latest` 内挂载当前 app、tests 和 pytest.ini，工作目录 `/tmp`，不挂载根目录 `.env` 或生产数据。Linux Python **3.11.16** 执行 `tests/test_step4_limits.py tests/test_budget_contract.py --no-cov -q`：**158 passed in 22.59s**。该结果仍使用 mock/内存 HTTP transport；不是实际供应商调用或真实后端代理联验。
- 完整 Linux 测试尝试因未挂载 `eval` 模块而在收集阶段停止：**7 errors / 1 skipped**，退出 1；附带覆盖率 **23.28%** 来自未执行测试的收集阶段，未达到 70%，不能计为完整测试通过。未执行完整 `make format && make lint && make test` 序列。
- 验收后仅停止移除本轮的 `rag-step4-nginx`、`rag-step4-upstream` 容器及 `rag-step4-isolated` 网络。测试脚本、渲染配置和临时证书位于忽略目录 `.pytest_cache/step4-nginx`，未纳入提交。

本轮 Docker 权限阻断已解除，完成了本地 Nginx 语法检查和固定测试上游的网关联验；仍需真实 FastAPI 单 worker + Nginx 联验应用并发/超时槽位/可信代理，以及完整 Linux 测试。真实供应商、生产账户消费上限、断电持久化、浏览器/Streamlit、公网 HTTPS 和 Linux 生产验收均未完成。

## 真实 FastAPI 单 worker 隔离联验（2026-09-30）

- 使用当前工作区 `app.main:app`、单 Uvicorn worker 和真实 lifespan；工作目录为临时 `.step4-run`，显式设置隔离 upload/chroma/quota/job/tmp 路径，不加载根 `.env`。匿名账本由现有 `bootstrap()` 初始化到临时目录。
- QA 的 vector store 和 engine 仅在验收 fixture 中替换为本地内存 double；不会调用真实供应商。应用路由、中间件、账本、并发 gate、QA executor、deadline 和 lease 逻辑均为当前代码。
- 直接后端：health 200；匿名 session 201；quota 200；普通 ask 200 且响应 request ID 存在。直接请求伪造 `X-Forwarded-For` 未改变 peer 处理。
- 临时 Nginx 容器代理到该 Uvicorn：经代理 session/quota/ask 分别 201/200/200，响应 request ID 存在；Nginx 覆盖客户端伪造的 `X-Forwarded-For`。该配置只绑定本机临时端口。
- 同一匿名身份发起 `slow`（fixture 线程睡眠 4 秒）期间，第二个 ask 返回 503 `service_busy`；线程完成后后续 ask 恢复 200，事件记录显示 finish 晚于第二请求，验证 lease 绑定实际 worker future。
- `timeout` fixture 线程睡眠 70 秒；直连后端约 60.0 秒返回 504 `upstream_timeout` 且带 request ID，事件记录显示 worker 约 70 秒才 finish。经 Nginx 的同一请求先受 60 秒 `proxy_read_timeout` 约束，未将网关 504 误记为后端 504。
- 这是 Windows + Docker Desktop 的本地隔离验收，provider 为 fixture，不代表真实供应商、生产账户消费上限、公网 HTTPS、Linux 生产部署或浏览器/Streamlit 验收。

## Linux 完整测试补验（2026-09-30）

### 收集依赖及隔离方式

- 开始时核对 `git status --short --branch`、`git log -1 --oneline`、`git show --stat --oneline HEAD`、`git diff --check`：分支为 `deploy/production`，HEAD 为 `8ba5c03`，既有改动均保留，diff check 退出 0。
- 执行 `rg -n "eval|evaluation" tests app scripts`，确认此前收集失败的 7 个测试模块依赖 `eval`：`test_compare_runs.py`、`test_eval_manifest.py`、`test_evaluate_retrieval_v3.py`、`test_run_score.py`、`test_scoring_guards.py`、`test_scoring_metrics.py`、`test_validate_eval_set.py`。同时确认需要 `frontend` Python 源码及已跟踪的 `docs/demo-v0.1.0/questions.json`。
- 从当前工作区按文件白名单复制 100 个文件到新的 `.step4-run/linux-full-20260930-*` 快照：`app/eval/frontend/tests` 的已跟踪 Python 源码、`pytest.ini`、`pyproject.toml`、上述公开演示 JSON，以及未跟踪的 `app/core/deadline.py`、`tests/test_step4_limits.py`、`scripts/acceptance/step4/real_app_fixture.py`。保留工作区未提交内容，不使用 HEAD 版本替代。各快照附源文件 SHA-256 清单。
- 使用已有后端镜像 `sha256:168bc2ec9e66a7f8f749996fcf882b1f7f4f1662c0dc27f1375948938b553387`，Linux Python **3.11.16**、pytest **8.3.0**。Docker 调用均提权，并明确用于“本地 Docker 隔离验收/只读检查”。
- 容器使用 `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --no-healthcheck --rm`；快照只读挂载为 `/workspace`，工作目录 `/tmp`，`PYTHONPATH=/workspace`。`/tmp` 为临时 tmpfs，`/app` 另用空 tmpfs 遮蔽；入口 `env -i` 清空镜像环境，仅设置运行所需变量，禁用 Python 字节码写入并使用空 keyring 后端。未传入宿主机凭据，未挂载工作区根目录、`.env`、`data`、`logs`、`secrets` 或 `.git`。
- 容器测试入口将 `/tmp/tests` 链接到快照 tests，将 pytest.ini 复制到 `/tmp`，实际运行 `python -m pytest tests/ -q --cov-report=term`。保留仓库原有覆盖率选项及 70% 门槛；覆盖率文件、HTML、缓存及合成测试数据均写入容器临时目录。

### 失败定位与复跑结果

- 补齐挂载后的首轮：**667 passed / 1 failed / 1 skipped，覆盖率 80.56%，pytest 退出 1**。失败为 `tests/test_demo_access.py::test_anonymous_demo_question_and_citations` 返回 503 而非 200，不能记录为通过。
- 原因：该测试已 mock QA engine，但未 mock `Settings.get_api_key()`；配置单例在测试收集阶段创建，晚于收集才执行的环境变量 fixture 不会更新该单例。干净容器没有外部凭据，因而触发正常的未配置服务拒绝。
- 仅修改 `tests/test_demo_access.py`：在该用例现有 mock 范围内显式 mock 凭据获取，返回固定虚构测试值。未改变应用代码、生产配置或服务拒绝规则，未读取真实 API key。
- 新快照复跑：**668 passed / 1 skipped in 21.62s，覆盖率 80.56%，pytest 退出 0**。此前缺失 `eval` 导致的收集错误已消除。完整运行后仍有 1 个模块级跳过：镜像未安装 `streamlit`，`tests/test_demo_frontend.py` 的 `pytest.importorskip("streamlit")` 跳过该模块，其中 5 个测试未执行。因此不将此结果写为 Windows 的 673 passed，也不声称 Streamlit/浏览器已验收。
- 本轮没有重跑 Windows 完整测试；前述 673 passed / 80.59% 仍为历史 Windows 结果。此前收集失败的 23.28% 也仍为无效验收结果，未替换或删除其历史记录。

### 只读静态检查及保留项

- Linux 测试通过后，对 15 个 Python 文件运行 Black `--check`、isort `--check-only`、flake8 `--max-line-length=88 --extend-ignore=E203,W503`。初次 Black 指出本轮测试修改的换行格式和既有 fixture 格式；isort 全通过；flake8 指出 fixture 的 E402/F401。
- 仅按 Black 提示调整本轮修改的测试文件换行。与已通过 Linux 测试的 100 文件快照逐一核对：99 个文件字节一致，只有 `tests/test_demo_access.py` 变化且 AST 完全一致；未因纯格式变化再次运行完整套件。
- Windows 只读静态检查曾两次无输出等待，均已中止，不计为通过；随后改用相同 Linux 镜像完成最终只读检查。最终 14 个应用/测试文件 Black、isort、flake8 均退出 **0**。精确文件清单见成功测试快照的 `static-targets.json`，排除单独报告的 `real_app_fixture.py`。
- 既有 `scripts/acceptance/step4/real_app_fixture.py` 原内容保留：Black 退出 **1**（字典换行）；isort 退出 **0**；flake8 退出 **1**（25–27 行 E402，26 行导出的 `app` 被报告 F401）。该脚本需要先执行 fixture 初始化再导入应用，本轮仅记录问题，不自动改写既有验收产物。**不能声称全部验收脚本静态检查通过。**
- 成功 pytest 的组合运行及最终分组静态运行均因上述静态失败而总体退出 **1**，与 pytest 自身退出 **0** 分开记录。PowerShell 将 Docker stderr 包装为 `NativeCommandError`，工具成败以各检查明确记录的退出码判断。未执行 `make format`、未宣称完整 `make format && make lint && make test` 通过。

### 可复核证据与验收边界

- 首轮证据：`.step4-evidence/linux-full-20260930-22760399-manifest.json`、`.step4-evidence/linux-full-20260930-22760399-output.txt`。
- 成功测试证据：`.step4-evidence/linux-full-20260930-2a93e5f4-manifest.json`、`.step4-evidence/linux-full-20260930-2a93e5f4-output.txt`；相应只读源码快照及 `run_linux_suite.py` 位于 `.step4-run/linux-full-20260930-2a93e5f4/`。
- 最终静态证据：`.step4-evidence/linux-static-20260930-output.txt`；检查入口 `.step4-run/linux-static-20260930.py`。复核时沿用成功快照，只读叠加当前 `tests/test_demo_access.py`，分开检查应用/测试文件及原 fixture。上述输出均为本轮隔离测试生成，不是生产日志。
- 本轮临时容器使用 `--rm`，结束后只读检查未发现本轮测试容器残留。已有 `.step4-run/`、`.step4-evidence/` 和验收 fixture 均保留，新增快照与结果也不删除。
- 本结果仅为 **Docker Desktop 上的 Linux 容器测试**，不是 Linux 生产部署验收。未验证真实供应商请求、生产账户消费上限、断电持久化、公网 HTTPS 或浏览器/Streamlit；未读取生产账本、敏感配置、数据卷或日志；未修改 integration worktree，未提交任何改动。

## 第 4 步本地验收收尾（2026-09-30）

### Fixture 静态检查修复

- 对既有 `scripts/acceptance/step4/real_app_fixture.py` 做最小格式和 lint 修复：保留先 bootstrap 隔离账本、再导入应用的顺序；为必须延后导入添加 `noqa: E402`，为 Uvicorn 需要的模块级 `app` 导出添加 `F401` 说明；仅展开 Black 要求的字典格式。
- 没有改变 fixture 请求行为、应用代码、生产配置或验收数据。使用只读 Docker 检查后，Black、isort、flake8 全部退出 0。

### 补齐 Streamlit 测试依赖后的 Linux 完整测试

- 从已核对的本地 `docker-backend:latest` 镜像（基础镜像 digest `sha256:168bc2…553387`）构建独立临时镜像 `rag-step4-test:9d15b6ce`，只额外安装仓库 `requirements-frontend.txt` 中的测试依赖。构建上下文只有 Dockerfile 和该依赖文件，不含工作区源码、`.env`、密钥、数据或日志；`pip check` 通过。
- 依赖下载发生在镜像构建阶段；实际测试容器使用 `--network none`，源码快照只读挂载至 `/workspace`，工作目录 `/tmp`，`/tmp` 为临时 tmpfs，未挂载 `.env`、`data`、`logs`、`secrets` 或 `.git`。完整命令仍为 `python -m pytest tests/ -q --cov-report=term`。
- 结果：**673 passed in 23.10s，0 skipped，覆盖率 80.56%**。`tests/test_demo_frontend.py` 的 5 个 Streamlit 测试已实际执行。随后对 15 个应用、测试和验收 fixture Python 文件运行 Black、isort、flake8，全部退出 0。
- 证据：`.step4-evidence/closeout-20260930-9d15b6ce-build.txt`、`.step4-evidence/closeout-20260930-9d15b6ce-tests.txt`；源码快照及构建目录位于 `.step4-run/closeout-20260930-9d15b6ce/`。这仍是隔离自动化测试，不是浏览器或 Streamlit 生产验收。

### 90 秒 Nginx ask 代理与真实 FastAPI deadline 联验

- 新增验收专用 `proxy_deadline_fixture.py`、`proxy_deadline_checks.py` 和 `run_proxy_deadline.ps1`。fixture 仅替换 vector store/QA engine 为合成 double；真实 FastAPI lifespan、路由、中间件、账本、并发 gate、QA executor、deadline 和 lease 逻辑保持当前工作区实现。
- Nginx 派生配置从当前生产模板复制相关 location 块，`/api/qa/ask` 的 `proxy_read_timeout 90s` 未改；仅增加内部 upstream、只读容器所需 `/tmp` 临时目录，并将派生配置的 `proxy_pass` 指向命名 upstream。模板文件本身未修改。容器网络使用内部 Docker network，backend/Nginx/client 固定地址分别为 `172.30.244.2/.3/.4`，没有宿主机端口发布。`nginx -t` 返回 syntax is ok / test is successful。
- 直接后端伪造 `X-Forwarded-For: 198.51.100.77` 时观察到真实客户端 `172.30.244.4`；经 Nginx 后观察到 Nginx 地址 `172.30.244.3`，伪造值被覆盖。所有响应 request ID 与响应体 request ID 一致，客户端记录只保存响应摘要和计数，不保存匿名 token。
- 初始 session/quota/ask 经 Nginx 分别为 201/200/200。timeout worker 开始后，同身份 `busy-during` 返回 503 `service_busy`；后端约 **60.025 秒**返回 504 `upstream_timeout`。在 504 已返回但 worker 仍运行时，`busy-after` 仍返回 503；worker 约 **70.003 秒**结束后，`recovery` 返回 200。
- 额度快照显示：`ask_default` 只从 0 增至 1（initial），再增至 2（准入后 timeout），最后 recovery 完成后为 3；busy 拒绝和 timeout 结果没有额外增加个人已用次数，其他预算计数保持 0。这里的 timeout 额度已在后端准入阶段保留，不能解释为供应商实际成功调用或费用结算。
- 第一次启动尝试因只读 Nginx 默认临时目录失败，第二次仍缺少默认 fastcgi 临时目录，第三/四次修正派生 upstream，均未进入请求阶段；这些尝试的配置与输出保留在 `.step4-evidence/closeout-proxy-20260930-9d15b6ce*`。第五次到达请求阶段但客户端脚本读取 401 body 字段错误；第六次修正后完整通过。失败均为隔离脚本/派生配置问题，不涉及生产模板或应用代码。
- 成功证据：`.step4-evidence/closeout-proxy-20260930-9d15b6ce-attempt6/proxy-summary.json`、`.step4-evidence/closeout-proxy-20260930-9d15b6ce-attempt6/config-provenance.json` 以及 `closeout-20260930-9d15b6ce-attempt6-proxy-run.txt`。所有临时容器和网络已在启动器 `finally` 中清理。

上述收尾结果仍属于 Windows + Docker Desktop 的本地隔离验收：供应商为 fixture，Nginx 为内部临时实例；不代表真实供应商请求、生产账户消费上限、断电持久化、公网 HTTPS、Linux 生产部署或浏览器/Streamlit 验收。
