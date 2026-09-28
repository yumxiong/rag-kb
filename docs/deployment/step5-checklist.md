目标：在 rag_kb-deploy 中完成一套独立、可部署、可被 Streamlit 和未来 v0/Next 前端共同使用的匿名身份、配额和成本控制机制；在 rag_kb-integration 中按同一契约接入并验证新前端，最后由 deploy 统一完成生产部署验收。

执行记录（2026-09-28）：第 0 步已完成，见 [基线文档](step5-baseline.md)及 [integration 回执快照](receipts/step5-integration-receipt-2026-09-28.md)。后端基线为 `58626e8d6b4df891564590da69865eb4f6795a4b`；integration 已确认边界但未同步代码。第 1 步契约已由双方冻结，deploy 正执行第 2 步。本清单不属于上述代码基线提交，随第 0 步文档独立归档。

第 0 步文档归档：`66c38183e53294158efca66d4790489ca51f9112`。第 1 步产物：[共享契约](../api/anonymous-session-and-quota.md)，版本 `anonymous-quota-v1-draft.2`，双方确认的正文提交为 `0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`；[integration 接受回执](receipts/step5-contract-integration-acceptance-2026-09-28.md)已归档，契约冻结。功能按后续步骤分别验收。

第 0 步：冻结协作边界和当前基线
deploy 执行
[x] 记录当前部署分支提交号、工作区状态和当前第 4 步验收结果。
[x] 确认第 4 步相关修改已经整理为一个或多个可引用提交。
[x] 记录当前已有能力：
QuotaManager 按 IP + User-Agent 识别用户；
/api/qa/quota 返回 HTTP 200 和配额 JSON；
/api/qa/ask 在问答前扣减个人配额；
max_concurrent_requests 已有中间件；
max_concurrent_llm_requests 已在 /ask 中通过共享信号量包裹 engine.ask()；源码接入已确认，实际并发、取消和超时行为仍待验收；
Nginx 已有 IP 限流配置；
尚无明确的全站预算控制。
[x] 明确当前实现不能直接作为第 5 步完成版本，尤其是 IP + User-Agent 在 Streamlit 服务端转发场景下会合并访客。
产物
建议新增：

docs/deployment/step5-baseline.md
记录：

部署分支：
基线提交：
第 4 步验收提交：
当前个人配额机制：
当前网关限流机制：
当前应用并发机制：
当前缺失能力：
完成标准
[x] deploy 和 integration 都知道后续开发基于哪个提交。（2026-09-28 收到并核对 integration 回执；接收不等于代码已同步。）
[x] 没有把两个 worktree 当前未提交修改直接当作共享基线。
[x] 确认第 5 步要修复的是已有公网风险和成本控制缺口，而不是单纯新增 UI。
第 1 步：先写共享契约，不要先改代码
这一步是两个 worktree 对齐的核心。

1.1 确定身份方案
推荐采用“后端签发、前端保存、后端验证”的方案。

建议设计为：

Next 浏览器
  └─ 首次访问 /api/session/anonymous
       └─ FastAPI 返回 HttpOnly Cookie

Streamlit 浏览器
  └─ Streamlit session_state 保存后端签发的匿名 token
       └─ Streamlit 服务端请求 FastAPI 时转发该 token
不要让浏览器自己生成一个普通字符串后直接作为可信身份。

需要明确：

[x] 匿名身份如何首次创建。
[x] 匿名身份有效期。
[x] 是否使用 HttpOnly Cookie。
[x] Cookie 的 Secure、SameSite、Path、Domain。
[x] Streamlit 如何保存并转发身份。
[x] Next 前端和 Streamlit 是否都使用相同的后端身份格式。
[x] 匿名身份是否允许主动重置。
[x] 服务重启后身份是否继续有效。
[x] 后端如何防止用户伪造任意身份 ID。
推荐使用：

匿名 ID：随机不可预测值
传输方式：原建议为 HttpOnly Cookie 或签名 Bearer Token；本轮草案明确采用后端随机凭证，Next 用 HttpOnly Cookie，Streamlit 用 X-Anonymous-Token，管理员 Bearer JWT 保持独立。
后端存储：只保存哈希后的身份键
1.2 确定配额语义
必须明确：

[x] 什么时候扣减个人额度（草案：准入事务提交时）：
收到合法请求后扣减；
还是模型调用成功后扣减。
[x] 超时、模型错误、限流时是否退回额度。
[x] 缓存命中是否扣减。
[x] BYOK 是否绕过默认模型额度。
[x] 每日重置时间和时区。
[x] 管理员是否拥有重置某个匿名身份的能力。
[x] 配额数据是否需要重启后保留。
建议首版规则：

合法问答请求进入模型调用前扣减一次。
请求参数错误不扣减。
限流、并发拒绝不扣减。
模型调用失败是否退回，必须固定一种规则并写入文档。
缓存命中仍计入请求次数，避免通过重复提问绕过行为控制。
BYOK 是否免个人额度，沿用当前产品设定，但仍受全站预算和限流约束。
1.3 确定全站成本控制
个人额度不能代替全站预算。

至少确定：

[x] 全站每日最大问答请求数。
[x] 全站每日最大估算成本，或最大模型调用次数。
[x] 是否区分默认 API Key 和 BYOK。
[x] 全站预算重置时间。
[x] 达到预算后的状态码和页面提示。
[x] 管理员查看当前全站用量的方法。
[x] 多进程或多容器时数据是否仍然一致。
当前项目使用本地 JSON 文件和进程内锁，适合单机单进程 Demo。第 5 步必须明确：

首版部署是否保证单后端实例运行？
如果是，可以使用文件持久化 + 进程锁。
如果不是，需要 Redis 或数据库提供原子计数。
在没有引入 Redis 前，不应宣称支持多副本精确预算控制。

1.4 确定错误契约
建议统一为：

情况	HTTP	code
参数错误	400	invalid_request
个人额度耗尽	429	quota_exceeded
网关请求过快	429	rate_limited
全站预算耗尽	503	global_budget_exceeded
后端并发繁忙	503	service_busy
模型调用超时	504	upstream_timeout
模型服务错误	502	upstream_error
统一响应形态：

{
  "detail": {
    "code": "quota_exceeded",
    "message": "今日免费提问次数已用完",
    "request_id": "..."
  }
}
/api/qa/quota 统一返回：

{
  "quota_enabled": true,
  "used_count": 2,
  "daily_limit": 5,
  "remaining": 3,
  "reset_at": "2026-09-29T00:00:00Z",
  "has_custom_key": false,
  "global_budget": {
    "status": "available",
    "reset_at": "2026-09-29T00:00:00Z"
  },
  "request_id": "..."
}
产物
建议新增：

docs/api/anonymous-session-and-quota.md
文档必须包含：

身份创建和传递；
Streamlit 请求链路；
Next 请求链路；
配额扣减规则；
全站预算规则；
限流和并发规则；
错误码；
Cookie/Header 约定；
示例请求与响应；
已知限制。
完成标准
[x] deploy 和 integration 都认可同一份契约。（双方确认 draft.2 正文提交 `0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`，状态 frozen；见 [契约接受回执](receipts/step5-contract-integration-acceptance-2026-09-28.md)。第 0 步回执仍仅代表基线接收。）
[x] integration 不再自行设计另一套身份或配额协议。（已在第 0 步回执接受该边界；当前仍只做独立页面工作。）
[x] deploy 后续代码修改都有明确目标。（草案已定义目标；双方冻结后才进入第 2 步。）
第 2 步：deploy 实现匿名身份
只在 rag_kb-deploy 中实现。

可能涉及的文件
app/api/qa.py
app/main.py
新增 app/core/anonymous_session.py
app/core/config.py
frontend/streamlit_app.py
可能新增 tests/test_anonymous_session.py
执行项
[x] 新增匿名身份创建或获取接口。
[x] 后端签发不可预测或带签名的身份凭证。
[x] 后端只使用经过验证的身份计算配额键。
[x] 支持浏览器 Cookie。
[x] 支持 Streamlit 服务端转发身份。
[ ] 明确反向代理下的 X-Forwarded-For 使用规则。（协议已规定；生产网关和 Uvicorn 配置待联验。）
[x] 不再直接使用容器内部看到的 Streamlit IP 作为个人身份。
[x] 日志中不打印完整身份凭证。
[x] 对身份凭证设置过期策略。
[x] 匿名身份接口不能暴露配额内容之外的敏感信息。
Streamlit 适配
Streamlit 的身份处理应只做：

[x] 首次启动会话时获取后端匿名凭证。
[x] 保存到当前 Streamlit session。
[x] 每次问答和额度查询时转发。
[x] Streamlit rerun 后仍保持同一会话身份。
[x] 失败时重新申请身份，而不是静默生成任意 ID。（仅确定性过期/缺失自动恢复一次；失效或其他错误等待明确重连。）
deploy 测试
至少覆盖：

[x] 两个匿名身份产生两个独立额度。
[x] 同一匿名身份多次请求持续累计。
[x] Streamlit rerun 不改变身份。
[x] 无凭证请求能够获得新身份。
[x] 伪造身份凭证被拒绝或被视为新身份。
[x] 过期身份按约定处理。
[x] ask 和 quota 使用同一身份。
[ ] 代理转发后不会把所有访客合并。（模拟同一来源身份隔离通过；真实代理联验待办。）
第 3 步：deploy 实现个人配额和全站预算
3.1 重构个人配额
当前 QuotaManager 使用 IP + User-Agent，需要改为使用第 2 步定义的匿名身份键。

执行：

[ ] 将 QuotaManager._get_user_id() 改为基于可信匿名身份。
[ ] 对旧配额数据设计迁移或直接废弃策略。
[ ] 保存 reset_at，不要只返回 last_reset_date。
[ ] 统一时区。
[ ] 统一“检查并扣减”的原子操作。
[ ] 避免并发请求同时通过额度检查。
[ ] 让 /ask 和 /quota 共用同一个身份解析函数。
[ ] 管理员重置功能也使用同一身份键。
3.2 实现全站预算
可以新增：

app/core/global_budget.py
最低能力：

[ ] 记录当天全站问答数。
[ ] 记录默认 Key 和 BYOK 的调用数。
[ ] 记录估算 tokens 或成本，若实际模型响应能提供用量。
[ ] 原子检查并增加。
[ ] 达到上限后阻止模型调用。
[ ] 提供管理员统计。
[ ] 进程重启后保留数据。
[ ] 记录每日重置时间。
[ ] 明确文件损坏时的安全策略。
建议先实现“请求数预算”，再根据模型实际 usage 增加成本预算。不要在没有可靠 token 统计时伪装成精确金额预算。

3.3 集成到问答流程
/api/qa/ask 的顺序应明确为：

验证请求参数
→ 解析匿名身份
→ 检查限流
→ 检查全局并发
→ 检查个人额度
→ 检查全站预算
→ 原子扣减
→ 调用检索和模型
→ 返回结果
需要特别决定：

[ ] 个人额度和全站预算是同时扣减还是分别扣减。
[ ] 哪一步失败时回滚前面的扣减。
[ ] 模型调用失败是否退回。
[ ] 缓存命中如何处理。
[ ] BYOK 是否仍受全站预算限制。
3.4 统一响应
[ ] /api/qa/ask 不再用 HTTP 200 携带“配额已用完”的普通答案文本。
[ ] /api/qa/quota 返回统一字段。
[ ] 每个请求生成 request_id。
[ ] 日志记录 request_id、匿名身份哈希、结果类型和耗时。
[ ] 不记录 API Key、Cookie 原文或完整问题内容。
第 4 步：deploy 完善限流、并发和代理边界
执行项
[ ] 验证 ConcurrencyLimitMiddleware 确实限制了目标请求。
[ ] 确认 max_concurrent_llm_requests 实际接入 QAEngine。
[ ] 给 /api/qa/ask 设置单独限流。
[ ] 给登录接口设置更严格限流。
[ ] 给普通 API 设置通用限流。
[ ] 明确 Nginx 限流和 FastAPI 限流是否重复扣压。
[ ] 确认 Nginx 正确转发：
Host
X-Real-IP
X-Forwarded-For
X-Forwarded-Proto
Cookie
必要 Header
[ ] 确认 /api 路由不会被转发到 Streamlit。
[ ] 删除或禁用没有后端实现的 /ws/{client_id} 初始化。
[ ] 如果暂时保留 WebSocket，必须明确后端路由和代理配置；否则应移除调用。
[ ] 确认前端容器不能把 http://backend:8000 暴露给浏览器端代码。
部署边界
对于未来 Next 前端，推荐最终结构：

浏览器
  └─ https://demo.example.com/
       ├─ /          → Next 或静态前端
       └─ /api/*     → FastAPI
对于当前 Streamlit 首版：

浏览器
  └─ https://demo.example.com/
       ├─ /          → Streamlit
       └─ /api/*     → FastAPI
这两种入口不能同时占用同一个根路径，因此必须决定：

[ ] 首版公网根路径仍由 Streamlit 提供；
[ ] 新前端先使用独立子路径或独立测试域名；
[ ] 新前端验收通过后，再切换反向代理根路径；
[ ] 管理员入口是否继续由 Streamlit 提供。
第 5 步：deploy 完成后端验收
在真实前端接入前，先完成后端验证。

自动化测试
建议新增或扩展：

tests/test_anonymous_session.py
tests/test_quota_contract.py
tests/test_global_budget.py
tests/test_rate_limit_contract.py
至少验证：

[ ] 两个匿名身份额度隔离。
[ ] 同一身份额度累计。
[ ] 额度达到上限返回 429。
[ ] 全站预算达到上限返回 503。
[ ] 限流返回 429。
[ ] 并发繁忙返回 503。
[ ] 失败请求是否正确回滚额度。
[ ] /quota 与 /ask 身份一致。
[ ] 重启后额度和预算数据保留。
[ ] 管理员统计不泄露完整访客身份。
[ ] 自定义 API Key 的规则符合契约。
[ ] 反向代理 Header 不会让访客身份全部合并。
deploy 本地联调
使用两个独立浏览器上下文或两个独立客户端：

客户端 A：
  获取匿名身份
  查询额度
  提问若干次

客户端 B：
  获取匿名身份
  查询额度
  提问若干次

验证 A 与 B 的额度分别累计。
不要只使用同一个 requests.Session() 测试，因为那无法证明身份隔离。

完成标准
[ ] 后端测试通过。
[ ] 两个独立访客额度隔离。
[ ] 全站预算能够阻止继续调用模型。
[ ] 错误码和 JSON 结构与契约一致。
[ ] Streamlit 仍能完成示例题和引用展示。
[ ] 旧的“HTTP 200 + 普通答案文本”配额逻辑已移除或明确兼容策略。
第 6 步：形成 deploy 的共享提交和交接记录
deploy 完成第 2～5 步后，暂停继续扩展功能，先形成交接点。

提交拆分建议
feat(quota): define anonymous session contract
feat(quota): add backend-issued anonymous identity
feat(quota): add global budget and quota error contract
feat(quota): forward visitor identity in Streamlit
test(quota): verify identity isolation and budget limits
docs(deploy): record step five validation
如果改动量不大，也可以合并成两个或三个提交，但不要把所有修改压成一个无法审阅的大提交。

交接记录
在 deploy 中新增或更新：

docs/deployment/step5-handoff.md
包含：

后端提交号：
契约文档：
匿名身份方式：
Streamlit 转发方式：
/ask 请求格式：
/quota 响应格式：
错误码：
个人额度规则：
全站预算规则：
限流规则：
并发规则：
代理路径：
已知限制：
integration 接入注意事项：
integration 接收动作
在 rag_kb-integration 中：

[ ] 读取契约文档。
[ ] 将 deploy 确定提交合并或 cherry-pick 到当前分支。
[ ] 不直接复制 deploy 工作区文件。
[ ] 记录合并提交号。
[ ] 如果出现冲突，优先保留 deploy 的后端规则，再适配前端。
[ ] 不在 integration 中重新设计身份和配额逻辑。
第 7 步：integration 接入和核实
这一阶段才开始修改 v0.app-rag/。

前端必须实现
[ ] 首次访问时完成匿名身份初始化。
[ ] 后续请求自动携带 Cookie 或约定凭证。
[ ] 调用 /api/qa/suggestions。
[ ] 调用 /api/qa/ask。
[ ] 调用 /api/qa/quota。
[ ] 显示真实知识库数量和名称。
[ ] 使用 deploy 已验收的示例问题。
[ ] 显示加载状态。
[ ] 防止重复提交。
[ ] 显示回答。
[ ] 显示来源文件名。
[ ] 支持展开完整引用原文。
[ ] 处理 429、503、504、400。
[ ] 额度耗尽时显示剩余次数和重置时间。
[ ] 失败时可以重新提交。
[ ] “新对话”真正清空当前页面会话。
[ ] 删除静态的虚构最近对话和知识库。
[ ] 删除没有后端行为的设置入口，或明确实现其功能。
[ ] 手机端默认收起侧栏。
[ ] 实际限制 2000 字符。
[ ] 正确处理中文输入法组合状态。
不应在 integration 重复实现
[ ] 不重新实现匿名身份签发。
[ ] 不重新实现配额计数。
[ ] 不重新实现全站预算。
[ ] 不在前端判断“是否允许调用模型”。
[ ] 不通过解析中文答案判断配额状态。
[ ] 不绕过后端直接调用模型服务。
integration 测试
[ ] 两个浏览器上下文使用不同匿名身份。
[ ] 页面显示两个独立额度。
[ ] 刷新页面后身份仍保持。
[ ] 个人额度耗尽提示正确。
[ ] 全站预算耗尽提示正确。
[ ] 网络失败可以重试。
[ ] 引用内容完整且正确转义。
[ ] 示例问题提交真实请求。
[ ] 移动端输入和侧栏正常。
[ ] 构建、TypeScript 检查、lint 通过。
第 8 步：两套前端并行验收
在切换公网入口前，两边都要验证同一后端。

Streamlit 验收
[ ] 匿名身份创建。
[ ] /ask 请求带身份。
[ ] /quota 与问答使用同一身份。
[ ] 配额耗尽提示正确。
[ ] 引用展示正确。
[ ] 管理员功能不受匿名身份影响。
v0/Next 验收
[ ] 匿名身份创建。
[ ] Cookie 正确保存。
[ ] /ask 请求带 Cookie。
[ ] /quota 与问答使用同一身份。
[ ] 配额耗尽提示正确。
[ ] 引用展示正确。
[ ] 两个浏览器访客互不影响。
结果记录
建议新增：

docs/deployment/step5-acceptance.md
记录：

后端提交：
Streamlit 前端提交：
v0/Next 前端提交：
测试日期：
个人额度：
全站预算：
访客 A 结果：
访客 B 结果：
限流结果：
并发结果：
代理结果：
失败场景：
已知限制：
第 9 步：deploy 集成新前端，但暂不立即替换公网入口
执行项
[ ] 在 deploy 中引入 integration 的确定前端提交。
[ ] 为新前端使用独立容器或独立服务名。
[ ] 使用独立测试端口或测试子域名。
[ ] 继续保留 Streamlit 管理入口。
[ ] 确认两个前端共享同一 FastAPI 后端。
[ ] 确认两个前端不共享不应共享的运行时数据。
[ ] 确认 /api 只指向 FastAPI。
[ ] 确认生产 Cookie 配置在 HTTPS 下正常。
[ ] 先让 Streamlit 继续作为正式根路径。
[ ] 新前端通过测试入口完成外网验证。
完成标准
[ ] 新前端在公网测试入口可用。
[ ] Streamlit 正式入口仍可回滚。
[ ] 两个前端不会互相覆盖配额或身份。
[ ] 发现问题时无需重新构建后端核心。
第 10 步：决定是否切换公网首页
只有满足以下条件才切换：

[ ] 第 5 步后端契约已提交。
[ ] 后端自动化测试通过。
[ ] Streamlit 真实验收通过。
[ ] v0/Next 真实验收通过。
[ ] 两个访客额度隔离。
[ ] 全站预算能阻止模型调用。
[ ] HTTPS Cookie 在真实域名下有效。
[ ] 移动端基本可用。
[ ] 失败和限流提示清晰。
[ ] 有明确回滚提交。
[ ] 生产数据和密钥独立持久化。
切换时：

[ ] 记录切换前后提交号。
[ ] 先部署新前端。
[ ] 验证健康检查。
[ ] 再修改 Nginx 根路径。
[ ] 从外部网络完成问答和额度检查。
[ ] 保留 Streamlit 回滚路径。
[ ] 把最终运行提交记录到上线清单。
两个 worktree 的最终职责边界
rag_kb-deploy
负责：

[ ] 匿名身份协议；
[ ] 配额和全站预算；
[ ] 限流和并发；
[ ] FastAPI 错误契约；
[ ] Streamlit 适配；
[ ] Nginx、HTTPS、Cookie 和代理；
[ ] 后端测试；
[ ] 生产部署和回滚；
[ ] 最终公网验收。
rag_kb-integration
负责：

[ ] v0/Next 页面工程化；
[ ] 问答和引用 UI；
[ ] 配额和错误状态展示；
[ ] 访客会话请求接入；
[ ] 移动端和交互体验；
[ ] 前端构建、lint 和测试；
[ ] 基于 deploy 契约的客户端验收。
共同负责
[ ] 契约文档；
[ ] 示例问题和验收场景；
[ ] 提交号和版本记录；
[ ] 两个前端使用同一后端的端到端验证；
[ ] 最终公网切换决策。
最重要的执行原则是：

deploy 先确定“身份、配额、预算和错误如何工作”；integration 再实现“页面如何调用和展示”；最后由 deploy 把两者放到同一生产代理和域名下验证。

当前：双方已确认 `anonymous-quota-v1-draft.2` 正文提交 `0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`，契约已冻结，第 1 步完成；deploy 进入第 2 步匿名身份实现。文档确认不代表功能、故障注入或两套前端联调通过。

第 2 步本地验证：后端全量 `pytest --no-cov -q` 为 439 passed、1 skipped；Streamlit 交互测试另用装有 Streamlit 的解释器运行，5 passed。第 2 步仍需真实代理来源/转发联验、Linux 持久卷及故障注入后才能关闭；第 3 步全站预算与问答准入原子性尚未开始。见 [本地建账与运行说明](step5-anonymous-store-operations.md)。
