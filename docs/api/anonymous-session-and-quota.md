# 匿名会话、配额与成本控制共享契约

版本：`anonymous-quota-v1-draft.1`。拟定日期：2026-09-28。状态：**deploy 提案，待 integration 评审；尚未实现，尚未冻结。**

后端代码基线：`58626e8d6b4df891564590da69865eb4f6795a4b`。第 0 步文档归档提交：`66c38183e53294158efca66d4790489ca51f9112`。协作依据：[基线及接收记录](../deployment/step5-baseline.md)、[integration 回执快照](../deployment/receipts/step5-integration-receipt-2026-09-28.md)。回执只确认第 0 步，不是对本草案的认可。

本文中的“必须”是拟实现的 v1 目标，不是当前 `58626e8` 的行为。双方确认本文的版本和提交后，再执行第 2 步。后台与 Streamlit 可先独立交付；完整 Next 验收与生产首页切换另行推进。

## 1. 核心决定与适用范围

| 事项 | v1 提案 |
| --- | --- |
| 身份 | 后端生成 256 bit 不透明随机凭证，服务端只存 SHA-256 摘要及期限；不接受客户端自编身份 ID |
| Next 传输 | 同源 HttpOnly Cookie；浏览器代码不读取凭证 |
| Streamlit 传输 | 每个 `st.session_state` 保存后端签发凭证，用 `X-Anonymous-Token` 转发 |
| 跨前端关系 | 同一协议、同一后端；不要求同一浏览器在 Next 与 Streamlit 使用同一个身份或共享个人额度 |
| 额度 | 默认 key 每身份每天 5 个已准入问答；BYOK 免个人次数限制，但受全站预算、速率、并发限制 |
| 时区 | 统一 UTC，00:00 重置；所有 API 时间为 RFC 3339 UTC（`Z`） |
| 失败扣额 | 准入前拒绝不扣；准入原子提交后成功、缓存、上游失败、超时均计一次，不自动退款 |
| 成本硬闸门 | 每日问答准入数 + 实际发起的聊天/查询 Embedding 尝试数；v1 不宣称精确金额预算 |
| 部署 | 一个后端实例、一个 Uvicorn worker，线程可并发；单个账本与进程内锁、原子文件替换，禁止多副本写账 |
| 重复提交 | v1 不提供幂等去重；每个成功准入的 POST 独立计数，客户端不自动重放问答 |

生产启用本契约必须同时替换 Streamlit 的身份与错误处理。不能只修改后端、留下旧 UI 将“配额耗尽”当 HTTP 200 回答。本契约的会话/额度/错误规则覆盖 `/api/session/anonymous`、`/api/qa/ask`、`/api/qa/quota` 和下述配额管理接口；管理员登录 JWT 协议保持独立。未列出的 API 暂不承诺同一响应结构，付费调用限制仍按第 5 节执行。

## 2. 匿名身份与传输

### 2.1 凭证与存储

凭证格式为 `anon_v1_` + 32 个密码学随机字节的 base64url（不带 padding，随机部分 43 字符）。格式正确并不代表有效：必须对完整凭证取 SHA-256，并命中后端已持久化、未过期的会话记录。`/ask` 与 `/quota` 共用同一解析器；客户端不能把摘要当凭证使用。

固定有效期 30 天（2,592,000 秒），从创建时计算，不滑动续期。复用会话不会改变期限或额度。正常后端重启保留身份；凭证原文不落后端账本、不进入日志/URL。账本保存摘要、创建/到期时间和计数，过期身份不再可用；过期会话及个人明细在到期后 7 天内清理，已累计的全站日计数不会随之减少。

前端不提供“重置身份”按钮。清 Cookie、无痕浏览或丢失 Streamlit 会话仍能创建新身份，这是匿名 Demo 的已知限制，不承诺“一自然人一份额度”。新身份速率限制和全站预算是必要补充。

### 2.2 创建或复用：`POST /api/session/anonymous`

请求必须为 `Content-Type: application/json`，Body 为以下之一；未知字段或其他 transport 返回 `400 invalid_request`：

```json
{"transport":"cookie"}
```

```json
{"transport":"header"}
```

没有凭证时创建会话，返回 **201**。有有效凭证时复用原身份，返回 **200**；不会刷新到期时间。此接口不调用模型，不扣问答额度，但受速率、创建上限和全局应用并发限制。

Cookie 模式响应（不会返回 `token` 字段）：

```json
{
  "transport": "cookie",
  "expires_at": "2026-10-28T12:00:00Z",
  "request_id": "8d1d8bdf-6f07-4c73-824b-746461ec8a15"
}
```

Header 模式响应仅额外包含 `token`（下例为占位符，不是可用凭证）：

```json
{
  "transport": "header",
  "token": "<backend-issued-anon_v1-token>",
  "expires_at": "2026-10-28T12:00:00Z",
  "request_id": "8d1d8bdf-6f07-4c73-824b-746461ec8a15"
}
```

Cookie 模式设置 Cookie，不返回 Header token；Header 模式不设置 Cookie。每种 transport 只接受对应凭证，避免将 HttpOnly Cookie 通过切换 transport 导出为可读 token。

| 凭证情况 | 会话接口 | `/ask`、`/quota` |
| --- | --- | --- |
| 无凭证 | 201 新建 | `401 anonymous_session_required`，不隐式创建 |
| 对应传输方式的有效凭证 | 200 复用 | 使用现有身份 |
| 已知但过期凭证 | `401 anonymous_session_expired` | 同左，不扣额 |
| 错误格式、摘要未命中、已删除记录 | `401 anonymous_session_invalid` | 同左，不扣额 |
| Cookie 与 Header 同时存在，或 transport 与现有凭证不匹配 | `400 invalid_request` | 同时存在即 400，即使两者相同也不做优先级猜测 |

Cookie 凭证失效时，后端响应附带同 Path/Domain 的删除 Cookie。会话接口收到无效凭证不能在同一次请求中顺便创建新身份。缺失或过期时前端最多初始化一次；无效凭证显示“会话失效，请重新连接”，只允许用户明确操作后申请一次。再次失败就展示错误，不循环重建。网络、限流、预算、服务端错误不得触发换身份。问答不会因重新初始化而自动重放。

### 2.3 Cookie、Header 与来源校验

| 项目 | 生产值/规则 |
| --- | --- |
| Cookie 名 | `rag_anonymous` |
| 属性 | `HttpOnly; Secure; SameSite=Lax; Path=/api` |
| Domain | 不设置，host-only；测试子域名与正式域名拥有不同 Cookie |
| Max-Age / Expires | 剩余有效期/固定到期时刻；复用不延长；删除时 `Max-Age=0` |
| Header | `X-Anonymous-Token: <token>`，仅服务器端 Streamlit/测试客户端使用 |
| 管理员身份 | `Authorization: Bearer <admin JWT>`；不能代替匿名 token，也不免除问答限额 |
| BYOK | 继续使用 `LLM-Api-Key`、`LLM-Provider`、`LLM-Base-URL`、`LLM-Model`；不是匿名身份 |
| 追踪 | 响应 `X-Request-ID`；后端生成 UUID，网关自行拒绝时由网关生成；不信任公网传入值 |
| 缓存策略 | 会话、额度及问答的 HTTP 响应 `Cache-Control: no-store`；与服务端 QA 缓存不同 |

本地纯 HTTP 调试可显式关闭 Cookie Secure，仅限 loopback 开发配置；生产及公网测试必须 HTTPS。Next 优先同源 `/api` 反向代理；不使用跨站 Cookie、`SameSite=None` 或共享父域 Cookie。CORS 只允许明确开发来源，带凭证时禁止 `*`；允许必要的自定义请求头，并向浏览器暴露 `X-Request-ID`、`Retry-After`。

开发时若直接跨端口访问后端，浏览器请求需 `credentials: 'include'`，后端 allowlist 必须包含准确的前端 origin；统一使用 localhost 或统一使用 127.0.0.1，不混用主机名。Cookie 不按端口隔离，测试不同环境时使用独立浏览器上下文或主机名。推荐仍通过 Next 开发代理保持同源，避免把开发例外带到生产。

所有 Cookie 认证的变更请求（包括 Cookie 模式初始化）要求 JSON，校验浏览器 `Origin` 与显式配置的本前端 origin 一致，不从未经信任的 Host/X-Forwarded-Host 推导允许来源。跨源或 `Origin: null` 拒绝 `403 origin_not_allowed`。Cookie 模式无 Origin 的 POST 同样拒绝；命令行 Cookie 测试必须显式设置正确 Origin。Header 模式允许无 Origin 的服务端请求；若带 Origin 仍须通过 allowlist。禁止将匿名凭证放在查询串、浏览器 localStorage 或前端公开环境变量中。

### 2.4 两条真实请求链路

**Next：** 浏览器访问当前前端 origin → 以 `credentials: 'same-origin'` POST `{"transport":"cookie"}` → 浏览器保存 Set-Cookie → 同源 GET `/api/qa/quota`、POST `/api/qa/ask` 自动携带 Cookie。客户端启动时可调用会话接口复用已有身份，初始化完成前禁用提问；组件重复挂载必须复用同一个初始化 Promise，避免并发创建。跨标签页首次初始化竞争可能留下少量未使用身份；不得因此宣称跨标签页严格只创建一次。

```javascript
await fetch('/api/session/anonymous', {
  method: 'POST', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ transport: 'cookie' })
});
// 实际客户端必须检查响应；下面的问答只由用户主动触发。
await fetch('/api/qa/ask', {
  method: 'POST', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ question: 'AtlasDesk 网页上传的单个文件最大支持多大？', max_sources: 3 })
});
```

SSR/BFF 若参与请求，须逐请求转发该浏览器的 Cookie，并将初始化产生的 Set-Cookie 返回给同一浏览器；不能使用跨访客共享 Cookie jar。v1 优先浏览器直连同源 API，暂不引入 BFF。

**Streamlit：** 浏览器连接 Streamlit → 本 session 缺少凭证时，服务端 POST `{"transport":"header"}` → 仅保存响应 token/expiry 至该 `st.session_state` → 额度和问答的服务端请求均带 `X-Anonymous-Token`，连同该 session 的 BYOK 设置。匿名 token 不放进 `st.cache_resource`、全局变量、HTML/JS 或所有访客共用的 `requests.Session()`。

正常 rerun 保持身份；Streamlit 浏览器刷新、断连后新建 session 或进程重启可能丢失 token，此时创建新身份。后端正常重启不会让仍由前端持有的 token 失效。返回给 Streamlit Python 的 Set-Cookie 不会到达访客浏览器，因此此链路明确使用 Header，不声称浏览器 Cookie 已共享。两套前端间切换可能有两份个人额度，全站预算始终共用。

## 3. 问答与额度接口

### 3.1 `POST /api/qa/ask`

身份必需，JSON 请求沿用现有字段：

```json
{
  "question": "AtlasDesk 网页上传的单个文件最大支持多大？",
  "max_sources": 3,
  "document_id": null
}
```

`question` 必须为非空字符串，原始输入最多 2000 个 Unicode 字符，去首尾空白后至少 1 字符；`max_sources` 可省略/null（默认 3），非空时整数 1～5；`document_id` 可省略/null，非空时 UUID v4（最多 128 字符）。额外字段拒绝，不接受客户端指定计数、额度、价格、模型输出上限或身份 ID。v1 不接收对话历史，UI 历史仅用于展示。缺字段、类型错误、JSON 错误及 Pydantic 校验统一为 `400 invalid_request`，不再由此返回 422。

成功仍为 HTTP 200，保留原响应字段并新增 `request_id`：

```json
{
  "answer": "AtlasDesk 网页上传的单个文件最大支持 40 MB。",
  "sources": [
    {
      "document_name": "atlas-03-document-ingestion.md",
      "content": "<完整检索分块，不是后台路径>",
      "similarity_score": 0.9,
      "page_number": null
    }
  ],
  "processing_time": 1.25,
  "from_cache": false,
  "request_id": "8d1d8bdf-6f07-4c73-824b-746461ec8a15"
}
```

`similarity_score` 沿用后端数值，不作为校准后的置信度百分比展示。边界题“资料没有报价”属于有效回答，正常计数；空知识库在准入前返回 `503 knowledge_base_unavailable`，不伪装成成功回答。引擎异常和空模型输出必须抛出受控错误，不再在 `answer` 内拼接异常。

BYOK 非空 key 只意味着选择 BYOK 路径，不代表 key 已验证；校验失败不得回退站点 key。没有 BYOK key 时拒绝任何其他 LLM 覆盖字段，默认 key 只能用部署固定的模型和 URL。BYOK provider、URL 必须通过后端 allowlist/SSRF 检查，未知值拒绝，不静默改成其他 provider。BYOK 不改变站点 Embedding 凭证。v1 前端仅内存/session 保存 BYOK，不继续默认持久化到浏览器 localStorage。

### 3.2 `GET /api/qa/quota`

身份必需，不创建身份、不扣问答额度、不调用模型。返回 HTTP 200，即使个人或全站已耗尽；存储不可用则返回受控 503。请求携带与下一次 ask 一致的 BYOK headers；额度查询不验证供应商 key。

```json
{
  "quota_enabled": true,
  "has_custom_key": false,
  "used_count": 2,
  "daily_limit": 5,
  "remaining": 3,
  "reset_at": "2026-09-29T00:00:00Z",
  "global_budget": { "status": "available", "reset_at": "2026-09-29T00:00:00Z" },
  "request_id": "8d1d8bdf-6f07-4c73-824b-746461ec8a15"
}
```

字段始终存在：`quota_enabled`/`has_custom_key` 为 boolean，`used_count` 为非负整数，`daily_limit`/`remaining` 为非负整数或 null，`reset_at` 为 UTC 字符串。`used_count` 是该身份当日**默认 key**已准入次数，切换 BYOK 不清零。BYOK 或本地关闭个人额度时，`daily_limit`/`remaining` 为 null，表示本次请求模式不执行个人上限；BYOK 时 `quota_enabled` 仍为 true（全局个人额度功能开关）。禁用个人额度不禁用全站预算，生产须启用个人额度。禁止 `"unlimited"`、999999 等混合类型或伪上限。

`global_budget.status` 仅 `available` / `exhausted`，按当前默认 key/BYOK 模式判断所有适用闸门，不受个人剩余额度影响。公开响应不暴露全站计数或阈值。即使使用 BYOK，全站耗尽时仍显示不可用；额度读数只是快照，不是后续问答预约。

问答完成或失败后可刷新一次额度；页面聚焦/手动操作时刷新即可，不做高频轮询。输入按钮同时参考个人剩余、全站状态和本页 pending 状态；最终以服务端响应为准。

## 4. 配额扣减、并发与失败

请求顺序：网关/应用基础保护 → 参数、Origin、BYOK 校验 → 匿名身份解析 → 访客速率限制 → 获取全局问答和单身份并发槽位 → 检查知识库可用性 → **一次账本事务检查并扣个人额度及全站问答数** → 检索/缓存/模型 → 返回结果。最外层全局请求中间件可能更早返回 503；不得因此提前扣额。

原子事务须同时检查个人额度、当日全站问答上限、适用模型调用闸门和账本健康；全部满足后才把个人默认 key 计数（BYOK 不加）、全站问答计数以及 default/BYOK 分类计数一起持久化。不同组件分别写两个 JSON 文件不符合原子要求。写盘确认前不执行任何外部模型/Embedding 调用。

| 情形 | 个人默认 key 计数 / 全站问答计数 | 模型尝试计数 |
| --- | --- | --- |
| 参数、来源、身份错误；速率拒绝；初始并发繁忙；空库 | 不扣 | 不发起 |
| 个人额度或准入时预算已满 | 不扣，两类计数均不变 | 不发起 |
| 准入后 QA 缓存命中 | 各 +1；BYOK 仅全站 +1 | 聊天 +0；若此前检索调用了查询 Embedding，仍计 Embedding |
| 成功、正常拒答、上游失败/超时/空回答 | 各 +1；BYOK 仅全站 +1；不退款 | 已持久化的尝试计数保留 |
| 准入后另一个请求耗尽模型预算，本请求在下一调用前被拒绝 | 已准入计数保留；响应 `global_budget_exceeded` | 未发起的调用不加；此前尝试保留 |
| 准入后客户端断开、响应丢失、进程崩溃 | 已准入计数保留，不自动补发或退款 | 预先记账的尝试保留，宁可保守多计，不重复发起 |
| 账本写入/持久化结果不确定 | 禁止继续外部调用；后端进入不可用状态待核对 | 不以客户端失败推断未扣，不能自动回滚已落盘计数 |

这里的“扣减”是准入即结算请求次数；不实现失败退款或按模型成功才扣的二阶段结算。模型尝试在每次实际调用前另做原子检查并加一，不在结束时再加。模型结果/usage/状态可补记，但不得在故障恢复时再次扣同一已记录尝试。所有缓存读取也在问答准入后，因此不会绕过请求预算。

跨 UTC 午夜：个人和问答准入计入准入日，外部调用尝试计入发起日。午夜不重置仍在执行的并发槽位；请求可跨日，管理员统计不要求每日日请求数与模型次数一一相等。

v1 不支持 `Idempotency-Key` 或 exactly-once。相同问题、相同 payload、重复点击只要分别准入就是多次问答；QA 缓存不等于幂等。前端禁用重复提交，Next/Streamlit/HTTP adapter 不自动重试 POST；失败只能由用户主动重试，UI 告知“已受理请求即使失败也可能计入今日次数”。`request_id` 用于诊断，不是重放键。若未来要求安全自动重放，必须升级契约并实现持久化幂等记录。

## 5. 全站预算与其他付费入口

### 5.1 v1 默认硬上限（待评审的 Demo 配置）

| 配置名（拟新增/沿用） | 默认值 | 统计范围 |
| --- | --- | --- |
| `DEFAULT_DAILY_QUOTA` | 5 | 每匿名身份默认 key 问答准入 |
| `GLOBAL_DAILY_ASK_LIMIT` | 500 | 全站 default + BYOK 问答准入，含缓存和失败 |
| `GLOBAL_DAILY_DEFAULT_LLM_LIMIT` | 200 | 使用站点 key 发起的聊天尝试 |
| `GLOBAL_DAILY_LLM_LIMIT` | 500 | default + BYOK 全部聊天尝试 |
| `GLOBAL_DAILY_QUERY_EMBEDDING_LIMIT` | 1000 | 公共问答链路查询 Embedding 的实际供应商请求尝试 |
| `QUOTA_TIMEZONE` | `UTC` | v1 只接受 UTC；其他值启动失败 |

正整数配置须启动校验，0/负数不是“无限制”。部署可以降低/调整阈值，但须记录有效配置；增加成本暴露时重新验收。全站账本按 UTC 日分区，重启不归零；不把旧 IP/UA 个人额度迁移到新身份，首次切换备份旧账本并初始化独立 v1 账本，明确新计数起点。

准入时任意适用闸门已满即拒绝，**包括缓存请求**。全局问答、总聊天、查询 Embedding 上限适用于所有访客；默认聊天上限只约束 default 模式，达到它后 BYOK 仍可在其他全站上限内继续。随后每次 cache miss 产生的实际上游请求仍须在调用点检查预算，防止并发超发。查询 Embedding 可以一次问答多次发起，必须逐次记录，不能用“一个问答一个向量请求”假设；每次调用只允许一个不超过 2000 字符的查询，不自动分片扩成多次隐藏请求。

分别保留 `ask_default`、`ask_byok`、`llm_default`、`llm_byok`、`query_embedding_default`、`query_embedding_byok`。Embedding 的两类均使用站点资源；供应商超时/错误等已发起尝试仍计费式记数，不因未收到 usage 而记零。Chat/Embedding SDK、HTTP adapter 和链路自动重试均设置为 **0**，禁止模型自动 fallback；一次用户 ask 最多一次聊天尝试，Embedding 多次调用都经闸门。

若有可靠 usage 则记录输入/输出 token 及明确模型价格版本，缺失记 null/unknown，不能伪造零费用；金额统计只是估算，不作为 v1 放行条件。BYOK 聊天费用由用户承担，站点查询 Embedding/计算费用由站点承担。

### 5.2 单次调用界限

问题最多 2000 字符，输出最多 800 tokens，默认聊天型号固定 `deepseek-flash`，默认 Embedding 固定 `text-embedding-v3`；BYOK 仍不得覆盖输出上限。实际发送到模型的完整 messages（系统提示、问题、检索上下文）序列化 UTF-8 内容合计最多 32 KiB；按相关度裁剪上下文并保留问题/系统提示，不能仅声明未执行的 `max_context_length=4000`。引用只展示实际纳入模型上下文的来源；必要证据因裁剪丢失须重跑示例验收。

采用字节上限避免在无法可靠确定 BYOK tokenizer 时声称精确输入 token 预算。模型 token 上限不能代替金额上限，不同供应商价格/分词不同。问答总处理 deadline 60 秒（检索开始至生成完成），每个上游请求 timeout 不超过剩余 deadline，Embedding 每次最多 15 秒，聊天最多 45 秒；前端超时 75 秒，Nginx `/ask` 读取超时 90 秒。

到 deadline 返回 `504 upstream_timeout` 不等于线程/供应商计算已停止。实际工作未退出前保持问答及身份并发槽位、禁止开始后续调用，不能因协程取消而提前释放槽位或退款；已发起供应商工作可能仍收费。全局请求槽位在响应结束后可释放，但问答工作槽位必须随实际任务释放。

### 5.3 付费旁路处理

| 入口 | v1 处理 |
| --- | --- |
| 公共 `/api/qa/ask`，含无默认 key 的旧 Demo fallback | 必须经过统一预算；生产无默认模型配置时 default 路径返回 `503 service_unavailable`，不执行未受控检索回退 |
| 当前匿名 `/api/qa/search` | 生产 Demo 禁用（`403 feature_disabled`），不让公开检索绕过问答额度消耗 Embedding；Next 使用 `/ask` |
| `/api/qa/health` 深度/with_qa 探针 | 生产禁止付费探针（`403 feature_disabled`）；管理员浅检查不调用模型；普通 `/health` 不调用模型 |
| suggestions、公开 `/api/documents/library`、额度和预算统计 | 必须只读本地元数据/账本，不触发聊天/Embedding |
| 管理员导入、上传、批量任务 | 仅受信任管理员；不计匿名问答预算，另计维护费用，不宣称其已被公共预算限制。公网 Demo 默认 `ENABLE_DOCUMENT_MAINTENANCE=false`，管理员操作返回 `403 feature_disabled`；受控维护窗口才显式开启、限制白名单并记录费用 |
| 离线导入脚本、评测、直接调用 QAEngine | 不在 HTTP 公共预算保证内，使用独立数据/额度与供应商消费上限；不得在公网入口间接暴露 |

v1 的“全站预算”指全部公共问答流量，不声称可限制同一供应商账户的所有离线/维护费用。默认 key 必须配置供应商侧消费上限作为账户级兜底；这不替代应用闸门。没有使用上下文的线上 QAEngine/Embedding 调用必须拒绝或显式走受控维护路径，不能因为忘传账本而默认为无限制。

## 6. 持久化、管理与恢复

拟沿用 `QUOTA_STORAGE_PATH`（默认 `./data/quotas`），新的统一账本 `quota-state-v1.json` 包含版本、身份摘要/期限、日期分区、个人计数、全站分类计数。所有会话创建与准入/模型记账在同一进程锁保护下更新：构造新状态 → 同目录临时文件 → flush/fsync → 原子 replace → 更新内存。线程中的计费调用必须使用同一实例和锁，不读写独立缓存副本。

首版保证单容器单 worker；启动持有存储目录独占锁，第二个进程使用同目录时启动失败。生产配置显式 worker=1、replica=1，不滚动双实例共写，不使用多机共享文件系统。未来多副本须迁移到带事务的数据库/Redis 并重新验收，单机文件锁不是跨主机一致性保证。

首次建账必须显式初始化，并持久化初始化标记；已初始化目录账本丢失、损坏、版本不支持、目录不可写或持久化失败均 fail closed，禁止自动返回空表重新赠送额度。读取身份/额度不能确定正确状态时返回 `503 quota_storage_unavailable`；运营修复前禁用问答。无凭证的 `/health` 可报告 degraded，但不暴露文件路径。重启/断电后计数不低于已确认持久化的准入记录；落盘成功却未调用模型允许保守多计。

恢复/回滚不得直接恢复较旧且计数更少的账本继续开放服务。先停问答，核对当日已消耗数据，不能确定时把当日预算置为耗尽直到下一个 UTC 日或人工确认保守余额；不要靠切换旧版本代码重新启用无预算入口。身份和账本挂载持久卷，发布镜像不能覆盖。

### 管理员端点（仅 admin JWT）

- `GET /api/qa/budget`：新增统计接口，返回 `date`（UTC 日 `YYYY-MM-DD`）、`timezone:"UTC"`、`reset_at`、`limits`、`counts`、`usage`、`request_id`。`limits` 包含 `ask`、`default_llm`、`llm`、`query_embedding`；`counts` 包含第 5.1 节六类计数，总数由两类相加。`usage` 未采集时 null，采集时需标明模型/usage/价格来源，不含 key、原问题或供应商原始响应。只读、不调用模型，正常返回 200。
- `GET /api/qa/quota/stats`：改为返回 `date`、`reset_at`、`default_daily_limit`、`total_users`、`quotas`、`request_id`；`quotas` 是当日有计数的身份数组，每项仅 `quota_ref`（身份 token 的 SHA-256 摘要）、`used_count`、`daily_limit`，不返回原 token、IP/UA 或身份全量记录。仅管理员可读；普通 UI 不展示摘要。
- `POST /api/qa/quota/reset`：JSON `{"quota_ref":"<64位小写十六进制摘要>","reason":"<1至200字符原因>"}`。只清指定身份当日个人计数；不存在返回 `404 quota_not_found`，重复清零幂等成功；不改身份、不改全站/调用计数、不延长到期。返回 `{"success":true,"request_id":"<id>"}`。不再按管理员 IP/UA 选择目标。
- 不提供公网“清空全站预算”接口。管理员重置需记录时间、操作者内部标识、目标摘要与 request_id；原因不写普通访问日志。所有管理接口仍返回正确的 401/403，匿名 token 不具备管理权限。

## 7. 限流、并发与代理

这些上限是不同目的的独立保护，均不能替代预算。

| 层 | v1 默认规则 | 拒绝 |
| --- | --- | --- |
| Nginx IP | 沿用普通 API 10r/s burst20、ask 2r/s burst4、login 5r/m burst5；新增 session 1r/s burst5，均 nodelay | 429 `rate_limited`；Retry-After 普通/ask/session 1 秒，login 60 秒，可能仍需稍后重试 |
| 应用匿名身份 | `/ask` 每身份滚动 60 秒最多 6 次尝试（含被额度/预算拒绝的有效尝试）；`/quota` 每身份滚动 60 秒最多 60 次 | 429，等待时间为最早记录出窗口的向上取整秒数 |
| 应用会话/IP | 所有 session 请求每可信来源 IP 滚动 60 秒最多 30 次；新建身份每 IP 每 UTC 日最多 300 个、全站每日最多 1000 个 | 429；分钟限制等窗口，日限制等 UTC 重置；复用不占创建数 |
| 全局 HTTP 并发 | `MAX_CONCURRENT_REQUESTS=20`，不排队等待 | 503 `service_busy`，Retry-After 1 秒 |
| 问答工作并发 | `MAX_CONCURRENT_LLM_REQUESTS=5` 保护整个 engine.ask，缓存路径也占槽；每匿名身份最多 1 个工作任务 | 503 `service_busy`，Retry-After 1 秒；准入前拒绝不扣额 |

应用身份速率窗口可内存保存，重启会重置分钟限制；身份创建的日计数必须进账本。先前在部署中可能只经过应用、不经过 Nginx 的 Streamlit 内部调用仍受到身份速率、会话创建、并发和预算约束。同一 Streamlit 服务的身份创建 IP 配额由访客共享，300/day 是首版容量限制；不能直接相信浏览器转发 IP 来提高它。若容量不够，调整配置并记录，而不取消全站创建上限。

Nginx 与应用的窗口/计数各自独立，任何一层拒绝都以错误码呈现，不在 UI 展示为个人额度耗尽。Nginx 限流须显式 `limit_req_status 429`，输出统一 JSON/Retry-After；仅拦截网关自己的拒绝，不覆盖后端原有 quota/budget 错误。Nginx 自己的超时/上游故障分别映射 504/502，JSON 失败时按第 8 节降级。

公网唯一 API 入口为 HTTPS Nginx，`/api/*` → FastAPI；容器内部 DNS/`http://backend:8000` 只给服务端使用。外层入口覆盖而非盲目追加客户端 X-Forwarded-For，FastAPI/Uvicorn 仅信任显式 Nginx 地址，禁止 `forwarded-allow-ips=*`；若增加 CDN/负载均衡则先配置可信代理链。直接内部 Streamlit 请求按真实连接来源限流，忽略其自报公网 IP。Cookie/匿名 Header、BYOK Header 需按原值转发且不记录；不以代理 IP 作为个人额度键。

生产 HTTP 初始化模板不构成完整 API 入口；通过 HTTPS 模板验证后才开放 Demo。删除没有后端实现的 `/ws/{client_id}` 初始化；Streamlit 自身 WebSocket 代理仍保留。根路径暂用 Streamlit，Next 测试域名使用同源 `/api`；切换后管理入口保留并记录回滚路径，不能让两套前端同时争用同一根路径。

## 8. 错误契约、重试与日志

所有本契约端点可控失败返回：

```json
{
  "detail": {
    "code": "quota_exceeded",
    "message": "今日免费提问次数已用完，请在重置后再试。",
    "request_id": "8d1d8bdf-6f07-4c73-824b-746461ec8a15",
    "retry_after_seconds": 3600,
    "reset_at": "2026-09-29T00:00:00Z"
  }
}
```

前三字段必需；`retry_after_seconds`/`reset_at` 仅适用时出现，缺失不表示立即重试。若有等待秒数，`Retry-After` Header 使用同一正整数（向上取整至少 1）；重置时间按 UTC，不按浏览器本地“明天”推测。`request_id` 与响应 Header 相同。未知/敏感异常只返回通用说明，不把供应商原始报错、key、路径、原问题带给客户端。

| HTTP | code | 展示/后续动作 |
| --- | --- | --- |
| 400 | `invalid_request` | 修改输入或配置；不重试原请求 |
| 401 | `anonymous_session_required` / `anonymous_session_expired` | 至多初始化一次；提示用户再次主动提交 |
| 401 | `anonymous_session_invalid` | 明确提示重新连接；不静默轮换身份 |
| 401 / 403 | `admin_auth_required` / `admin_forbidden` | 管理端身份无效/权限不足，不触发匿名身份重建 |
| 403 | `origin_not_allowed` / `feature_disabled` | 来源不允许/当前 Demo 未开放该操作 |
| 404 | `quota_not_found` | 管理员目标不存在，检查引用 |
| 429 | `quota_exceeded` | 展示个人次数与 reset_at，等待 UTC 重置；BYOK 可用性另查预算 |
| 429 | `rate_limited` | 提示稍后再试；等待 Retry-After，不更换身份 |
| 503 | `global_budget_exceeded` | “今日演示服务额度已用完，请在重置后再试”；本模式禁用问答至 reset_at |
| 503 | `service_busy` | “服务繁忙，请稍后再试”；不当作额度耗尽 |
| 503 | `quota_storage_unavailable` / `service_unavailable` / `knowledge_base_unavailable` | 服务暂不可用，不自动重建身份或重放问答 |
| 504 | `upstream_timeout` | 结果未完成，可能已计次数；允许用户稍后主动重试 |
| 502 | `upstream_error` | 模型调用失败，含 BYOK 鉴权错误、供应商限流、空输出；不能解释为匿名身份 401 |
| 500 | `internal_error` | 通用故障，显示 request_id；不输出内部异常 |

错误优先级受最外层网关和 HTTP 中间件影响，例如无效输入在过载时也可能收到 503；不能用返回顺序推断身份/余额。`Retry-After` 是用户再次尝试的等待提示，不授权客户端自动重发 POST。

前端先看 HTTP status 和 Content-Type，再安全解析 JSON；HTML/空体/无效 JSON/未知 code 显示通用服务异常及可用的 request_id，不渲染原始响应为 HTML，也不计为成功回答。网络断开且没有响应不推断未扣额，可恢复后 GET quota；UI 所有数字使用服务端返回值。兼容旧后端仅用于迁移测试，不从旧 answer 字符串猜测新版错误码来声称已联调。

后端日志仅保留 request_id、匿名身份摘要的诊断前缀、操作/计数模式、结果 code、耗时和必要计数。不记录匿名 token、Cookie、Authorization、LLM-Api-Key、完整问题/答案、上游原始错误；访问日志不含请求头/body。管理员审计使用单独受控日志。新 request_id 不从用户输入直接回显，重试有新 ID。

## 9. 评审与后续验收清单

本次只拟定文档，以下都是后续验证要求：

| 场景 | 必须观察到的结果 |
| --- | --- |
| 两个浏览器上下文/两个 Streamlit session | 同后端、不同身份、个人额度分别累计；每个 session rerun 身份不变 |
| 同一 token Cookie 与 Header 分别调用 | 分开请求使用同一摘要计数；同时发送两种凭证被拒绝；Cookie 不可通过切换 transport 导出 |
| 过期、伪造、丢失与服务重启 | 严格按身份表处理；没有换身份死循环；正常重启保留账本 |
| 默认 key 第 6 次、BYOK 切换、相同问题缓存 | 5 次准入后 429；BYOK 免个人但仍计全站；缓存计请求，不虚增未发生的聊天调用 |
| 最后一个额度/预算单位的并发竞争 | 原子准入，无负数和超发；另一请求拒绝时不只扣个人而漏扣全站 |
| 上游失败、deadline、断连、SDK 重试 | 准入失败计数规则一致；没有隐式重试；任务未退出不释放问答槽位；已记尝试不退款 |
| 多次检索 Embedding、BYOK、匿名 search、付费探针 | 每个外部尝试受闸门控制；旁路被禁用；BYOK 不绕过站点 Embedding 上限 |
| 午夜、损坏/写失败、恢复旧账本、双 worker | UTC 分日；存储 fail closed；恢复不减少未知消费；第二进程拒绝启动 |
| Nginx + Streamlit 内部直连 + Next 同源 | 两条链路都受保护；分别触发 429/503/502/504；前端不暴露内部地址 |
| HTML 网关错误、跨站 POST、管理 JWT | UI 正确降级；Origin 拒绝；管理员与匿名权限隔离 |
| 第 4 步 5 道问题、引用与 UI | 新边界下示例和完整引用仍通过，文档数/名称来自真实后端 |

integration 评审重点：Cookie/同源可行性；不共享跨前端身份及重连限制；nullable 额度字段；错误与主动重试体验；75 秒客户端超时；不自动重发；BYOK 内存保存。deploy 评审重点：文件事务/进程约束、真实调用点记账、取消/超时槽位、限流覆盖、生产付费旁路关闭和配置上限。

当前评审状态：

- [x] deploy 已拟定 `anonymous-quota-v1-draft.1`，覆盖第 1 步所有定义项与回执的六类问题。
- [ ] integration 对本草案版本及其文档提交返回接受或逐项修改意见。
- [ ] deploy 合并意见，记录双方确认的同一提交，将状态改为 frozen；有行为变化必须递增版本。
- [ ] 子步骤 2～5 的代码、自动化测试和 Streamlit 真实验证完成；不能用文档检查代替。

评审未冻结前 integration 仅继续与契约无关的页面工作；草案 mock 标明版本，不视为真实联调。本文的默认数值、随机凭证方案、错误码与路由封禁均为完整可评审提案，没有暗示已有实现或替 integration 提前确认。

### 本轮文档验证（2026-09-28）

已执行 `git diff --check`，使用 Python 标准库核对本文及三份部署文档的 UTF-8、35 个本地文件链接、8 个 fenced JSON 示例和 6 个 Git 提交引用；第 0 步七项完成，第 1 步定义已拟定但双方接受仍待办，第 2 步后没有标记实现完成。回执源文件、归档文件和 `66c3818` 中的 blob 均具有基线记录中的同一 SHA-256。

`git diff --exit-code 58626e8d6b4df891564590da69865eb4f6795a4b -- app frontend docker tests scripts docs/demo-v0.1.0` 通过：没有应用实现或验收素材变更。没有运行功能测试、真实模型调用、Docker 或公网验收；这些文档检查不证明目标协议已经可用。
