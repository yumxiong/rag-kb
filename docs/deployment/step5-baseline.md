# 第 5 步协作边界与当前基线

冻结日期：2026-09-27。对应 [第 5 步执行清单](step5-checklist.md) 的第 0 步。

本记录冻结代码参照点、职责和交接方式，不是匿名身份 API 契约，也不表示第 5 步功能或生产部署已验收。本文的“上线第 4/5 步”指 [上线清单](demo-v0.1.0-checklist.md)；“子步骤”指第 5 步执行清单中的第 0～10 步。

## 1. 固定提交与工作区快照

下表来自本次只读检查，工作区状态为本次文档编辑前的状态。未 fetch，未核实远端或服务器版本。

| 工作区 | 分支 | 当时 HEAD | 工作区状态与用途 |
| --- | --- | --- | --- |
| `rag_kb-deploy` | `deploy/production` | `58626e8d6b4df891564590da69865eb4f6795a4b` | 已跟踪文件无修改；仅 `docs/deployment/step5-checklist.md` 未跟踪。此 HEAD 是第 5 步后端开发基线。 |
| `rag_kb-integration` | `feat/frontend-backend-integration` | `82d5037e38f355a406dee30af4b8632b8195e241` | `v0.app-rag/` 未跟踪；不纳入共享基线，也不是已交付前端。 |
| `rag_kb` | `feat/public-eval-corpus` | `2af58b56f8f5c494eca958fd5765d90158bb5c6c` | 公开语料改造仍有未提交修改；不视为已完成或可整体合并的发布版本。 |
| `rag_kb-showcase` | `chore/repository-showcase` | `b562fb10a877ead7605be362e89f0b909630cefa` | 仅记录 worktree 列表中的 HEAD；未检查工作区内容，不属于本轮交接范围。 |

主仓库当时已跟踪修改为 `eval/corpora/public_v1/README.md`、`eval/validate_eval_set.py`、`scripts/deploy.sh`；未跟踪项为 `docs/public-eval-milestone-03.md`、四份 `docs/repository-showcase-*` 记录/计划/清单、`eval/corpora/public_v1/artifacts/seed-validation.json`、`eval/datasets/`、`eval/validate_annotations.py`、`tests/test_seed_annotations.py`。这里只记录 Git 状态，未读取这些未提交内容或将其复制到 deploy。

### 可引用的提交链

| 用途 | 提交 | 说明 |
| --- | --- | --- |
| deploy 与 integration 的共同祖先 | `82d5037e38f355a406dee30af4b8632b8195e241` | 当前 integration HEAD；不是第 5 步后端基线。 |
| 上线第 3 步：模型配置、语料快照与问题清单 | `61d784ee38ae892159c3ecb78482842995512e92` | 第 4 步的前置提交。 |
| 上线第 4 步：修复与验收归档；第 5 步后端基线 | `58626e8d6b4df891564590da69865eb4f6795a4b` | `deploy(04): Completed field testing and acceptance of the isolated environment, and fixed several issues`，提交时间 2026-09-27 11:55:23 +08:00。包含应用修改、测试、验收报告和截图。 |

第 4 步真实验收发生在 **2026-09-23**，当时是 `61d784e` 加工作区修改；这些修改和证据于 **2026-09-27** 归档为 `58626e8`。报告中的 `runtime: uncommitted deployment worktree changes` 以及旧记录的“未提交”描述保留其历史含义，不能解释为当前代码仍未提交，也不能改写成在新提交上重跑了验收。

2026-09-27 产物当时为文档工作区修改，不自动成为新代码基线。2026-09-28 收到 integration 回执后，将本文、执行清单、上线清单及回执快照作为独立文档提交归档；提交号在后续第 1 步记录中引用，后端代码基线保持不变。不可用移动的分支名或未提交文件代替固定 SHA。

## 2. 上线第 4 步验收状态

证据：[2026-09-23 公开验收报告](../demo-v0.1.0/acceptance-2026-09-23.json)、[上线清单中的真实验收续记](demo-v0.1.0-checklist.md#第-4-步真实验收续记2026-09-23)、[演示内容说明](../demo-v0.1.0/README.md)。以上均已包含在 `58626e8`。

- 冻结语料为 `atlasdesk-demo-v1`：9 份 Markdown、32 分块、1024 维；生成模型 `deepseek-flash`，Embedding 模型 `text-embedding-v3`。
- 5 道真实 API 问答均返回 HTTP 200，`from_cache=false`；4 道可回答题覆盖必要引用，边界题说明缺少私有化报价，未编造价格。
- 22 个管理端点匿名请求均返回 401；临时管理员登录、列表、Markdown 上传、完成状态查询及删除成功，目录恢复为 9 份文档。
- 已完成桌面 1440×1000、移动视口 390×844 的浏览器验证，包括真实问答和完整来源展开。最终缩短输入提示后截图超时，不能声称最终逐像素复核完成。
- 历史回归记录为后端相关测试 184 passed、Streamlit 测试 5 passed、指定文件 flake8 和 `git diff --check` 通过；本次未重新运行这些测试或真实 API。
- 未完成全项目 70% 覆盖率门槛、Docker、云服务器和外网验收；没有据此认定生产可发布。Windows UTF-8 TXT 上传兼容性仍留待上线第 7 步检查，首版白名单仅使用 Markdown。

旧记录中“QAEngine 硬编码输出上限 1000”的问题已经由第 4 步修复：当前初始化读取 `settings.llm_max_tokens`，代码默认值及验收值均为 800。后续需验证部署配置实际生效，但不应重复列为未修复代码缺陷。验收临时个人额度 40 次不是生产额度。

## 3. 已有机制与已知缺口

以下是对固定基线的源码核对，配置默认值不等同于服务器运行值。

### 3.1 个人身份、额度与响应

依据：[`QuotaManager`](../../app/core/quota_manager.py)、[`qa.py`](../../app/api/qa.py)、[`config.py`](../../app/core/config.py)。

- `_get_user_id()` 使用 `SHA-256(client_ip + ':' + user_agent)` 的前 16 位十六进制字符。`/ask` 与 `/quota` 分别从 `request.client.host` 和 `user-agent` 构造相同字段，没有后端签发并验证的匿名身份。
- 默认开启配额，默认每日 5 次；以服务器本地 `datetime.now()` 判断日期，访问时惰性重置，没有固定时区和 `reset_at` 契约。
- `check_and_increment()` 在进程内 `threading.Lock` 下检查并扣减，保存至本地 `user_quotas.json`。正常读取可恢复计数，但不是跨进程原子计数；损坏文件会退回空额度表，保存失败只记日志。配置虽声明 `quota_storage_path`，工厂函数当前未传入，仍用构造默认路径 `./data/quotas`。
- `/api/qa/quota` 正常返回 HTTP 200 和 JSON。普通访客字段包括 `quota_enabled`、`has_custom_key`、`used_count`、`daily_limit`、`remaining`、`last_reset_date`、`message`；BYOK 的上限和剩余值是字符串 `unlimited`；关闭额度时仅返回开关和说明。没有 `reset_at`、`global_budget`、`request_id`。
- `/ask` 在问题检查和空库判断之后、引擎执行及 LLM 并发检查之前扣额。缓存命中也经过扣额；并发拒绝或后续异常没有退款逻辑。额度耗尽仍返回 HTTP 200 的 `QuestionResponse`，把拒绝提示放在 `answer` 中。
- 非空 BYOK key 会跳过个人额度；这不是密钥已验证或请求无服务端成本的证明。管理员重置当前按管理员请求的 IP/UA 定位，尚无按可信匿名身份指定目标的契约。

### 3.2 Streamlit 的访客合并风险

依据：[`streamlit_app.py`](../../frontend/streamlit_app.py) 的 `display_quota_info()` / `build_byok_headers()` 和 [`chat_interface.py`](../../frontend/components/chat_interface.py) 的问答请求。

当前链路是浏览器 → Streamlit → Python `requests` → FastAPI。`/ask`、`/quota` 没有携带后端签发的访客凭证；同一 Streamlit 服务转发的访客可能具有相同的后端可见 IP 和请求库 User-Agent，因此会合并额度。前端内部 `session_state` 或 WebSocket `client_id` 不等于后端认可的额度身份。单纯转发浏览器 IP/UA 也不能替代可信匿名凭证。

### 3.3 网关限流与代理

依据：[`production.conf.template`](../../docker/nginx/conf.d/production.conf.template)、[`public-sim.conf`](../../docker/nginx/conf.d/public-sim.conf)、[`production-init.conf.template`](../../docker/nginx/conf.d/production-init.conf.template)、[生产 Compose 模板](../../docker/docker-compose.production.yml.template)。

| 生产 HTTPS 模板中的位置 | IP 限流 | 突发设置 |
| --- | --- | --- |
| `/api/auth/login` | `5r/m` | `burst=5 nodelay` |
| `/api/qa/ask` | `2r/s` | `burst=4 nodelay` |
| `/api/` | `10r/s` | `burst=20 nodelay` |

- 键为 `$binary_remote_addr`。HTTPS 模板将 `/` 交给 Streamlit，将 `/api/` 交给 FastAPI，并设置 Host、X-Real-IP、X-Forwarded-For、X-Forwarded-Proto 等头。
- 模板尚未显式规定 `limit_req_status 429` 或统一 JSON 错误；不能将已有 Nginx 配置视为已满足第 5 步错误契约。代理可信来源及 Cookie/Header 的实际透传仍需验证。
- 生产 Compose 模板当前挂载的是初始化 HTTP 配置；该初始化配置没有 `/api/` 专用路由和上述限流。存在 HTTPS 模板不代表生产已启用它。
- Streamlit 如果通过容器内部地址直连 FastAPI，问答不经过 Nginx 的 `/api/qa/ask` 位置；公网网关限流不能单独覆盖此调用链。
- 应用中 SlowAPI 当前仅见登录接口的 `5/minute` 装饰器，`/ask` 没有对应装饰器；限流注册、实际拒绝响应及与 Nginx 的叠加行为尚未验收。

### 3.4 应用与模型并发

依据：[`main.py`](../../app/main.py)、[`concurrency.py`](../../app/core/concurrency.py)、[`qa.py`](../../app/api/qa.py)、[`QAEngine`](../../app/core/qa_engine.py)、[后端 Dockerfile](../../docker/Dockerfile.backend)。

- `max_concurrent_requests` 默认 20，已注册 `ConcurrencyLimitMiddleware`；繁忙时返回 HTTP 503 和字符串 `detail`，没有机器可读的 `service_busy` code。
- **`max_concurrent_llm_requests` 默认 5，已经接入 `/ask`。** 路由获取共享信号量，在其保护下通过线程执行 `engine.ask()`，默认 key 和 BYOK 引擎均走此路径。因此不是“只有配置、未使用”。
- 信号量保护的是路由内整个 `engine.ask()`（包含检索/缓存路径），不在 QAEngine 内部；不能据此保证所有直接引擎调用、独立检索或 Embedding 调用都受到同一约束。拒绝前已扣个人额度；取消/超时后工作线程是否继续执行及槽位释放行为仍待并发测试。
- 两层信号量均在单进程内。Dockerfile 的 Uvicorn 命令未显式指定多个 worker，但这不足以证明生产进程数或副本数已受约束。首版运行拓扑及多进程计数策略在子步骤 1 明确。

### 3.5 全站成本与后续修复范围

[`cost_optimization.py`](../../app/api/cost_optimization.py) 提供缓存统计和节省费用估算，不是模型调用前的全站预算闸门。当前没有全站每日请求/模型调用上限、预算原子扣减、默认 key 与 BYOK 分类账或预算耗尽后的统一拒绝。

第 5 步需完成可信匿名身份、个人额度与全站预算的一致扣减规则、持久化失败策略、共享错误契约、限流/并发覆盖验证，以及两个前端的访客隔离。预算范围还需明确检索产生的 Embedding 成本；不能把 BYOK 等同于零站点成本。以上是公网访问前必须补齐的风险控制，不因前端 UI 升级而自动解决。

## 4. 冻结协作边界

| 工作区 | 负责范围 | 本轮边界 |
| --- | --- | --- |
| deploy | 匿名身份签发和验证、个人额度、全站预算、后端错误、限流/并发、Streamlit 适配、后端测试、Nginx/HTTPS/Cookie/代理、生产部署与回滚 | 主导 `app/`、`frontend/`、`docker/`、部署脚本及相关后端测试的第 5 步变更；子步骤 1 先形成共享契约，再实现。 |
| integration | `v0.app-rag/` 的 Next/React 页面、问答和引用 UI、会话请求接入、额度/错误展示、移动端体验、前端构建/lint/测试 | 按 deploy 契约适配，不另建身份、扣额或预算规则，不抢改共享后端和生产代理；与契约无关的页面工作可独立继续。 |
| 主仓库 | 公开合成语料改造及评测 | 改造未完成。deploy 继续使用已冻结的 demo 快照/allowlist；后续更新须基于明确提交重新导入和验收，不直接复用主仓库运行数据。 |
| 双方共同 | 契约评审、固定示例与验收场景、版本交接、两个前端共用后端的端到端验证、切换决策 | 发现跨边界需求先在契约/交接记录明确，再由对应工作区实施并给出提交。 |

首版正式根路径沿用 Streamlit 的部署目标，管理员入口继续保留；Next 先在独立测试端口或测试域名验证。两个前端共用 FastAPI，`/api/*` 应只指向后端；通过共同验收后由 deploy 统一切换生产入口并保留回滚路径。本条是部署边界，不声称目前已有公网正式入口。

### 提交与数据交接规则

1. 第 5 步后端开发统一参考 `58626e8d6b4df891564590da69865eb4f6795a4b`。integration 当前仍在 `82d5037`，本次没有替它合并或移动 HEAD。
2. 若 integration 需要提前同步第 4 步能力，应在保存自身工作后合并固定的 `58626e8`，或按依赖顺序 cherry-pick `61d784e`、`58626e8`。不要仅挑后一个提交而遗漏语料/配置前置改动；以上是后续操作约定，本次未执行。
3. 子步骤 1 的目标契约为 `docs/api/anonymous-session-and-quota.md`，在 2026-09-27 冻结基线时尚未创建。2026-09-28 已拟定 [draft.1](../api/anonymous-session-and-quota.md)，待 integration 评审，尚未定稿。Cookie/Token 格式、期限、扣额退款、BYOK、预算阈值、时区和错误码以双方确认的契约为准；清单中的示例不是现有 API 保证。
4. deploy 在子步骤 2～5 实现并验证，子步骤 6 用确定提交和 `docs/deployment/step5-handoff.md` 交接；integration 再进行子步骤 7～8 的新协议接入/验收，并返回确定前端提交、后端版本及验证记录。
5. integration 通过 merge/cherry-pick 接收确定提交，记录来源 SHA 和本地结果 SHA。冲突保留已确认的后端规则并适配客户端；不能复制另一 worktree 的未提交文件作为共享版本。
6. 各工作区使用独立测试端口和运行数据。`.env`、secrets、密钥、管理员令牌、Cookie 原文、索引、缓存和额度文件不通过提交交接；验收报告只保留必要且脱敏的信息。
7. 主仓库当前 `scripts/deploy.sh` 也有未提交修改。deploy 后续修改部署脚本前需核对归属和确定提交，不能覆盖或直接复制主仓库工作区版本。

## 5. 完成记录与接收门槛

- [x] 记录 deploy 分支、完整基线 SHA、编辑前工作区状态和第 4 步验收范围。
- [x] 确认第 4 步代码、测试和证据已归档至可引用提交，前置提交明确。
- [x] 按源码记录身份、额度、网关和两层并发；区分已有实现、未验证行为及缺失能力。
- [x] 明确各 worktree 归属、共享提交方式及生产切换责任，不以未提交代码作为基线。
- [x] integration 接收确认：2026-09-28 已读本文并接受 `58626e8d6b4df891564590da69865eb4f6795a4b` 及协作边界；未同步代码，HEAD 仍为 `82d5037e38f355a406dee30af4b8632b8195e241`，契约确定前仅开展与契约无关的页面工作。

**第 0 步已完成：deploy 已冻结基线，integration 已确认接收。** 基线接收不等于代码已同步，也不等于第 1 步契约已获认可。后续契约拟定以本文为参照，双方确认契约后再进入相应实现步骤。

### 2026-09-28 接收补录与归档

- 来源：`D:/claudeCode/rag_kb-integration/docs/deployment/step5-integration-receipt.md`，用户在本会话明确通知接收，deploy 已只读核对原文与 integration Git 状态。
- 来源回执尚未提交；没有可引用的 integration 回执提交 SHA。deploy 保存 [回执原文快照](receipts/step5-integration-receipt-2026-09-28.md)，按原始字节复制，SHA-256 为 `3ae128109b1883b68db5a24d4fecae57bd38af4b698ffb2ca6c35415b20bf408`。快照中的“未提交”和待办清单描述接收方当时状态，不在快照内代改。
- 归档快照是用户授权的文档证据归档，不是复制未提交应用代码来建立共享基线。未改动 integration 工作区，未执行 merge/cherry-pick。
- 接受回执中的交付边界：第 5 步后端与 Streamlit 可以独立实现和验收，不以完整 Next 上线为前提；Next 联调验收和最终生产首页切换另行记录。
- 回执提出的身份续期/重连、跨前端身份、计费原子性、重试、其他付费入口和故障策略作为第 1 步必答项。
- 第 0 步文档与回执快照已归档于 `66c38183e53294158efca66d4790489ca51f9112`；此后本文新增的契约链接与该提交引用属于第 1 步文档更新，不改变后端代码基线。

2026-09-27 验证采用 Git 状态/历史/共同祖先核对、固定提交与当前已跟踪实现的一致性检查、源码静态检查，以及文档链接/提交引用检查和 `git diff --check`；当时未提交。2026-09-28 补录核对回执原文、哈希和 Git 状态，并归档文档。两轮均未访问生产凭证、模型 API 或服务器，未运行生产服务，未重跑第 4 步验收或全量测试，未推送或打 tag。

其他 worktree 的 Git 状态首次读取遇到 ownership 校验，随后使用单次 `git -c safe.directory=... -C ... status --short` 完成只读核对，未改全局配置。Git 另报告用户级 ignore 文件不可读；本记录按命令实际返回的状态记载，不包含被项目规则忽略的运行文件盘点。
