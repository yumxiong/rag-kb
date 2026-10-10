# demo-v0.1.0 上线清单

最后更新：2026-09-28。范围：匿名问答与引用、管理员维护、小型公开语料、基本成本控制和运维。先验证候选提交，最后打正式 tag；已发布 tag 不移动。生产配置、凭证、证书和数据独立持久化。

| 步骤 | 状态 | 结果与下一步 |
| --- | --- | --- |
| 1. 独立发布工作区 | 已完成 | 用户已建立 `rag_kb-deploy` / `deploy/production`。本地 HEAD 与 origin/master 基线均为 `82d5037e38f355a406dee30af4b8632b8195e241`；本轮未刷新远端。 |
| 2. 服务器部署条件 | 用户已确认 | 用户确认服务器兼容部署脚本、域名已解析。实际域名、资源参数、SSH 方式及网络验证记录待服务器配置时补录；本轮未连接服务器。 |
| 3. 固定首版内容 | 已完成 | [语料与验收说明](../demo-v0.1.0/README.md)：9 份原文、4 个首页问题、1 个边界题；DeepSeek `deepseek-flash` + Qwen `text-embedding-v3`。 |
| 4. 最小应用修复 | 本地验收通过，已提交 | 5 题真实 API、必要引用原文、匿名管理拒绝、真实管理员 Markdown 维护、浏览器桌面/移动视口验证通过。2026-09-27 已归档至 `58626e8d6b4df891564590da69865eb4f6795a4b`；Docker/外网在第 7/10 步复验。 |
| 5. 配额与成本控制 | 进行中：契约草案待复审 | [执行清单](step5-checklist.md)第 0 步已归档；第 1 步 [draft.2](../api/anonymous-session-and-quota.md)已修订，待 integration 复审。integration 未同步代码，功能尚未实现。 |
| 6. 部署与更新流程 | 待执行 | 修复证书、端口检查和失败状态；区分首次部署与日常更新。 |
| 7. 本地 Docker 验证 | 待执行 | 独立配置和数据，导入 allowlist；验证问答、引用、管理操作、配额、超时、持久化及项目检查。 |
| 8. 服务器配置与凭证 | 待执行 | 管理员密码哈希、交互式 secrets、域名/地址、目录权限；凭证不入 Git。 |
| 9. 部署候选版本 | 待执行 | 记录确定提交，启动容器、HTTPS/续期、导入快照及真实模型调用。 |
| 10. 外网验收 | 待执行 | 问答、引用、权限、多访客配额、错误提示、移动端与端口暴露。 |
| 11. 最低运维能力 | 待执行 | 存活监控、用量提醒、日志轮转、备份恢复、续期及回滚验证。 |
| 12. 正式发布 | 待执行 | PR 合并，最终验收提交打 `demo-v0.1.0`，服务器运行版本对齐，README 增加入口。 |

## 第 3 步记录

- 语料来源：`feat/public-eval-corpus`，提交 `2af58b56f8f5c494eca958fd5765d90158bb5c6c`。9 份源文档无未提交修改；来源 README 和评测产物的未提交变化未纳入快照。未修改其他 worktree。
- 原文逐字节复制；源文档与来源提交比较时允许 Git 检出换行转换。每份快照及来源 blob 的 SHA-256 单独记录于 manifest。
- 模型变更：更新提供商默认映射、现有配置单测预期和 `SETUP_API_KEY.md`；演示配置显式设置模型型号，保留用户自定义模型覆盖机制。
- 无答案题审阅：9 份原文没有私有化部署报价；BYOK 费用说明不能当作报价证据。
- 已执行只读命令：`git worktree list`、`git rev-parse HEAD origin/master`、`git status --short`、`git grep -n 'deepseek-v4-flash'`；主仓库 `git status --short -- eval/corpora/public_v1`。未读取生产凭证、访问模型或服务器。
- 源文件 Git blob 核对在 Python 子进程中遇到 worktree ownership 检查，使用单次命令的 `-c safe.directory=D:/claudeCode/rag_kb` 完成只读核对，未更改全局 Git 配置。
- 验证结果：`D:/claudeCode/rag_kb/venv311/Scripts/python.exe -m pytest tests/test_config.py -o addopts= -q`：35 passed。仅运行配置相关测试，显式取消默认覆盖率选项，不代表全项目 70% 覆盖率门槛通过；全量检查在第 7 步及推送前执行。
- Python 标准库离线核对通过：9 份快照与源文件逐字节一致、SHA-256/字节数正确、导入白名单恰好 9 份文件、4 个首页问题及 1 个无答案题、5 段证据原文位于指定章节。`git diff --check` 通过；配置、测试与 API 配置文档中旧型号无残留。
- `corpus/.gitattributes` 为快照 Markdown 禁用 Git 换行转换，避免服务器检出后哈希漂移。该文件不在导入白名单内。
- 模型实际维度、调用日期、回答及引用通过情况留待第 4/7 步。未执行真实 API、Docker 或全量测试，未提交、推送或打 tag。

## 后续验收记录模板

每次追加：日期、步骤、候选提交、语料版本、配置版本（不含凭证）、验证命令、通过/失败、问题及下一步。问答验证另记问题 ID、实际引用、事实覆盖、缓存状态和耗时。故障修复后生成新候选提交重新验收，正式发布前不打 tag。

## 第 4 步记录（2026-09-22）

本轮变更尚未提交。语料版本仍为 `atlasdesk-demo-v1`，未更改原文或运行时索引，未修改其他 worktree。

- 首页说明匿名提问、管理员维护、9 份虚构资料及能力边界；将“基于文档训练”改为检索描述。
- `/api/qa/suggestions` 返回与冻结问题清单一致的 4 个问题。运行时代码只包含问题，不包含答案和预期证据，也不依赖 Docker 镜像外的 docs 目录。空库返回空问题列表及文档数 0；接口失败在 UI 显示暂不可用，不再当作空库。
- 示例点击进入正常 `/api/qa/ask`，清除先前的单文档限定，保证跨文档示例按全库检索。引用文件名与预览 HTML 转义，长片段仍可展开完整原文；修复非 JSON 网关错误提示。
- 管理员页面补齐与首页一致的本地后端默认地址；修正 BYOK 密钥传输说明及 DeepSeek 自动填充型号。
- 22 个管理端点分别验证匿名、错误签名、过期令牌及非管理员角色：前三种返回 401，普通角色返回 403。涵盖上传、批量上传、删除、任务状态/取消、缓存清理和配额管理等。另验证错误密码拒绝、正确密码登录取得令牌并访问管理列表。未改动鉴权实现。
- 匿名问答及引用 API 测试使用替身向量库和问答引擎，验证两个来源完整透传、公开目录不包含内部 ID/路径。**不证明实际召回、生成或无答案题拒答通过。**

验证命令及结果：

```text
D:/claudeCode/rag_kb/venv311/Scripts/python.exe -m pytest tests/test_demo_access.py tests/test_api.py tests/test_qa_engine.py -o addopts= -q
# 146 passed；现有 requests 依赖兼容性警告 1 条
python -m pytest tests/test_demo_frontend.py -o addopts= -q
# 5 passed，使用安装了 Streamlit 1.50.0 的 Python
D:/claudeCode/rag_kb/venv311/Scripts/python.exe -m flake8 app/core/demo_content.py tests/test_demo_access.py tests/test_demo_frontend.py --max-line-length=88 --ignore=E203,W503,E402
# passed
git diff --check
# passed
```

Streamlit AppTest 验证完整匿名首页、4 个按钮、无上传控件、示例请求无管理员令牌、完整引用展示、清空对话、接口错误恢复和引用 HTML 转义。HTTP 调用均为测试替身，未启动对外服务。后端虚拟环境未安装 Streamlit，因此前端测试单独使用系统 Python。相关 Python 文件经 Black/isort 格式化；本轮未执行全项目格式化/检查与覆盖率门槛，推送前仍需项目规定的全量检查。

剩余验收条件：

1. 真实 API 凭证路径尚未提供，当前 worktree 的 secrets 仅有说明文件。已向用户询问可用于独立测试的配置路径；不要在对话或日志中输出密钥。
2. 得到凭证后，在独立数据目录导入 9 份快照，使用 `deepseek-flash` / `text-embedding-v3`，逐题记录实际回答、引用、耗时、Embedding 维度和缓存状态；边界题须确认未编造报价。
3. Tabbit 稳定启动器 `diagnose` 退出码 1 且无输出，本轮无法取得浏览器截图或完成视觉检查；未创建浏览器任务。需要恢复浏览器工具后补充桌面/移动端检查。AppTest 不替代视觉验收。
4. 访客身份、配额与成本控制留在第 5 步；另发现 QAEngine 初始化仍硬编码输出上限 1000，而配置片段写 800，第 5 步需统一并验证实际生效值。

## 第 4 步真实验收续记（2026-09-23）

本节更新上节的待办状态。基于 HEAD `61d784ee38ae892159c3ecb78482842995512e92` 加本 worktree 未提交修改验收，不代表已发布 tag。密钥仅从用户指定的 `.env` 文件引用读取，未输出到日志或报告。

### 隔离环境与实测结果

- 本机后端 `127.0.0.1:18004`、前端 `127.0.0.1:18504`；向量库、上传、作业、缓存、配额和临时管理员凭证均在 Git 忽略的 `data/acceptance-step4/`。不复用其他 worktree 的服务或数据。
- 9 份原文经生产 DocumentProcessor 和 Qwen Embedding 入库，32 个分块、1024 维。使用 `deepseek-flash` 非思考模式、输出上限 800；真实模型探针确认响应型号。
- 5 道题 HTTP 200、`from_cache=false`，4 道可回答题的全部预期原文都包含在实际返回引用内；跨文档题同时覆盖接入与排障资料。边界题明确资料缺少私有化报价，没有编造价格。逐题答案、来源、耗时和证据核对见 [公开验收报告](../demo-v0.1.0/acceptance-2026-09-23.json)。原始运行数据仅本地保留，报告不含凭证、私有路径或管理员令牌。
- 22 个真实管理端点匿名请求均返回 401；独立随机临时管理员登录、列表查询、Markdown 异步上传、完成状态查询、删除成功，最终目录恢复 9 份文档。伪造/过期/普通角色的拒绝仍由离线回归覆盖。
- Tabbit 验证匿名首页、示例点击、真实跨文档答案、展开完整来源、清空对话及匿名 Admin 登录页。已查看 1440×1000 桌面和 390×844 移动视口截图。移动视口完成真实问答操作；这不是外网或实体手机验收。

### 本轮修复及限度

1. 后端原先将引用截断到 300 字，关键证据位于后文时无法核对。现在返回完整检索分块，由前端保留预览与展开功能。
2. 建议接口原先把分块数当文档数，已改为目录文档数；首页显示 9 份而非 32 份。
3. 原 MMR 在演示题中漏掉必要证据。现在保留最相近的 2 个片段，再以 MMR lambda=0.3 的候选补足 6 个去重片段。未修改语料、问题或预期答案，无问题特判。此调整只是开发样例修复，不构成正式检索评测结论。
4. DeepSeek 显式禁用思考模式，并使用配置的温度/输出上限；空答案不再作为成功结果缓存。首次出现空答案的具体服务端终止原因未捕获，不能将其确定归因于思考预算；修复后真实调用均返回非空答案。
5. 发现 `ENABLE_QA_CACHE=false` 原先无效，已使读取和写入都遵循该开关，并增加检索流程版本/参数的缓存命名空间，避免读到旧截断引用。本次关闭问答缓存；查询 Embedding 可以命中独立测试缓存。
6. 示例改成两列，输入提示缩短以适应窄屏。保存的截图拍摄于缩短提示之前，缩短后再次截图遇到 Tabbit capture timeout；原浏览器交互与截图仍有效，不声称最终逐像素复核完成。
7. 额外尝试中文 UTF-8 TXT 上传时在 Windows 加载失败；代码的 TextLoader 未显式设置编码，推测与系统默认编码有关，尚未单独修复。首版只导入 Markdown，此项作为第 7 步的非阻断兼容性检查记录。

### 验证命令与状态

```text
D:/claudeCode/rag_kb/venv311/Scripts/python.exe data/acceptance-step4/run.py ingest
# 9 documents / 32 chunks / 1024 dimensions；仅空独立集合执行
D:/claudeCode/rag_kb/venv311/Scripts/python.exe data/acceptance-step4/run.py serve
D:/claudeCode/rag_kb/venv311/Scripts/python.exe data/acceptance-step4/run.py ask
D:/claudeCode/rag_kb/venv311/Scripts/python.exe data/acceptance-step4/admin_check.py
# 本地临时脚本不入 Git；重建时按 manifest allowlist + 独立目录执行同一生产处理链路
D:/claudeCode/rag_kb/venv311/Scripts/python.exe -m pytest tests/test_evidence_retriever.py tests/test_qa_engine.py tests/test_api.py tests/test_demo_access.py tests/test_config.py -o addopts= -q
# 184 passed，现有 requests 兼容性警告 1 条
python -m pytest tests/test_demo_frontend.py -o addopts= -q
# 5 passed
D:/claudeCode/rag_kb/venv311/Scripts/python.exe -m flake8 app/core/qa_engine.py app/core/demo_content.py tests/test_evidence_retriever.py --max-line-length=88 --ignore=E203,W503
# passed
git diff --check
# passed
```

下一步：第 5 步访客身份与全站成本控制。尚未运行全量覆盖率、Docker 或云服务器验证，未提交/推送/打 tag。临时 40 次个人额度仅用于验收，不能直接作为生产成本控制方案。

## 第 5 步基线冻结记录（2026-09-27）

- 第 4 步修复、测试、公开验收报告和截图已于 2026-09-27 提交为 `58626e8d6b4df891564590da69865eb4f6795a4b`，前置提交为 `61d784ee38ae892159c3ecb78482842995512e92`。上文“未提交”描述的是 2026-09-22/23 当时状态；本次核对没有重跑真实验收。
- 第 5 步后端开发基线固定为 `58626e8d6b4df891564590da69865eb4f6795a4b`。本轮编辑前 deploy 已跟踪文件无修改，仅第 5 步执行清单未跟踪；integration 仍在 `82d5037e38f355a406dee30af4b8632b8195e241`，未跟踪 `v0.app-rag/` 不作为共享版本。
- 已完成 [第 0 步基线文档](step5-baseline.md)：职责边界、提交依赖、现有额度/并发/网关机制与风险。LLM 信号量已接入 `/ask`；输出 token 上限已读取配置，默认 800。仍缺可信匿名身份、全站预算及统一错误契约，且扣额早于 LLM 繁忙检查。
- 第 0 步 integration 接收回执待补录；下一阶段为共享契约。本文档更新未实现第 5 步功能，未修改其他 worktree，未提交、推送、打 tag 或部署。

## 第 0 子步骤接收与归档（2026-09-28）

- 已核对 integration 回执并保存 [原文快照](receipts/step5-integration-receipt-2026-09-28.md)，哈希、来源及接收状态见 [基线补录](step5-baseline.md)。本节更新上节当时的“待补录”状态。
- integration 接受固定后端基线及协作边界，仍在 `82d5037e38f355a406dee30af4b8632b8195e241`，未同步代码；第 0 步完成。接收方原回执未提交，deploy 独立归档证据，不代替对方提交。
- 第 1 步开始拟定共享契约，拟定完成后交 integration 评审；后端与 Streamlit 可独立验收，Next 完整验收与生产切换单独记录。未进入第 2 步实现或部署。

## 第 1 子步骤共享契约草案（2026-09-28）

- 第 0 步文档归档提交：`66c38183e53294158efca66d4790489ca51f9112`，包括回执原文快照；后端代码基线仍为 `58626e8d6b4df891564590da69865eb4f6795a4b`。
- 新增 [匿名身份与配额契约](../api/anonymous-session-and-quota.md)，版本 `anonymous-quota-v1-draft.1`。定义 Cookie/Header 双链路、生命周期、UTC 配额、原子准入与失败计数、分类调用预算、并发/速率/代理、持久化故障、错误码及前端示例，并逐项回应 integration 回执的评审问题。
- 草案选择后端随机凭证、默认个人 5 次/日、全站 500 问答/日、站点 key 聊天 200 次/日、全部聊天 500 次/日、查询 Embedding 1000 次/日；这些是待评审配置，不是已经部署的运行值。新行为还包括禁用生产公开 search/付费健康探针、默认关闭上传维护，需在契约确认及后续验收中明确验证。
- 第 1 步尚未双方冻结；integration 的基线接收不代表契约认可。待对方审阅该版本及文档提交后再实施第 2 步。本轮仅文档归档与拟定，未修改应用、运行数据或其他 worktree，未推送或部署。

## 第 1 子步骤契约修订（2026-09-28）

- integration 静态审阅 draft.1 提出两项待定规则：过期 Cookie/Header 的自动恢复次数，以及断电保证所需的目录 fsync、持久卷/初始化状态校验。该审阅不是契约接受回执。
- deploy 将契约修订为 `anonymous-quota-v1-draft.2`：过期凭证有界恢复且不重放问答；账本以父目录 fsync 为确认边界，显式 bootstrap 与独立预期 UUID/挂载检查阻止丢卷后自动建空账。新增对应后续验收场景。
- draft.2 待 integration 针对固定提交复审；第 1 步未冻结，第 2 步未开始。以上是契约定义，尚未运行故障注入或功能测试。

## 第 1 步冻结及第 2 步进展（2026-09-28）

- integration 已接受 `anonymous-quota-v1-draft.2`，协议正文固定为 `0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`；[接受回执](receipts/step5-contract-integration-acceptance-2026-09-28.md)由 deploy 归档。该确认只针对文档协议。
- deploy 已进入匿名身份实现，完成 Header/Cookie 会话、统一身份解析、持久账本、Streamlit 转发与本地定向测试。生产 Linux 挂载与断电故障注入、真实反向代理、多前端联调及全站预算仍待后续验收；目前不应部署为公开服务。
