# Step 5 第 8 子步骤交付审查清单

日期：2026-10-08。工作区：`D:\claudeCode\rag_kb-integration`。

结论：双前端本地合成联验已完成；全仓隔离测试、≥70% 覆盖率及规定范围的格式/lint 检查已通过，提交范围审查通过。用户已明确授权创建本地提交，不推送；真实安全配置和生产验收仍由 deploy 在授权环境完成。
本交付提交包含下列范围，排除原有 `step5-integration-receipt.md`。没有推送、生产部署、外部消息或 deploy 工作区修改。下文检查记录中的 HEAD 指提交前基线。

## 1. 基线与交付范围

- 分支：`feat/frontend-backend-integration`。
- 提交前基线 HEAD：`9d42d19bc89fd26995b084828b39bf603483cda6`。
- 后端限制修复：`28c5c2552389f498d03e4a4a709400d0eab3b04b`。
- 后端身份与额度修复：`86de66966a0fbd505faeb1d3a054696c768c795b`。
- 冻结契约正文：`0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`。

| 文件或目录 | 审查内容 |
| --- | --- |
| `v0.app-rag/` | Next 前端源码、测试、配置、依赖锁文件及原有 UI 资源；同源 API、后端 Cookie 身份、额度与错误展示、引用、输入及重试交互 |
| `frontend/components/chat_interface.py` | 原始 Unicode 长度检查、排队后禁用输入、防重复提交、安全错误与明确重试、BYOK 空值处理 |
| `frontend/components/document_manager.py` | BYOK 空值处理 |
| `frontend/streamlit_app.py` | 移动端侧栏 auto、BYOK 空值处理 |
| `frontend/utils/quota_display.py` | Streamlit 当前会话身份与刷新限制提示 |
| `tests/test_demo_frontend.py`、`tests/test_quota_frontend_contract.py` | Streamlit 回归测试；importorskip 后导入的局部 lint 豁免 |
| `.gitignore`、`v0.app-rag/.gitignore` | 忽略临时验收目录和构建缓存，包括 tsbuildinfo |
| [合成联验脚本](../../scripts/acceptance/step5/local_dual_frontend.py) | 本地合成 FastAPI、临时账本、双前端启动及 HTTP/AppTest 联验 |
| [网络故障探针](../../scripts/acceptance/step5/streamlit_network_probe.py) | 本地已准入响应丢失与用户明确重试验证 |
| [全仓隔离检查脚本](../../scripts/acceptance/step5/repository_checks.py) | 禁用真实配置/密钥读取及业务网络连接，在临时 cwd 执行完整 pytest 与原有覆盖率门槛 |
| `tests/test_anonymous_session.py` | 收尾 isort：仅将第三方 TestClient 导入移至第三方分组 |
| [验收记录](step5-acceptance.md)、本文及两张移动端截图 | 命令、结果、历史问题修正和证据边界 |

截图：[Next](receipts/step5-next-mobile-2026-10-08.png)、[Streamlit](receipts/step5-streamlit-mobile-2026-10-08.png)。
原有 `step5-integration-receipt.md` 保留且未重写，不应因其当前未跟踪状态而自动纳入提交。
审查全部新增源码应同时查看 `git ls-files --others --exclude-standard`；单独 `git diff` 不包含未跟踪文件正文。

## 2. 验收结果与边界

| 项目 | 结果和证据来源 |
| --- | --- |
| Next 匿名身份、额度隔离及刷新保持 | 本地 HTTP 独立 Cookie jar；Tabbit 与用户 Chrome 无痕操作互相核对额度 |
| suggestions、quota、library、ask、回答及引用 | 本地合成 HTTP 与浏览器验证；引用可展开、恶意标记按文本显示；文档详情仍是管理员接口，匿名请求 401 为预期 |
| 429 quota_exceeded / rate_limited；503 global_budget_exceeded / service_busy；504 upstream_timeout | 后端真实准入逻辑搭配合成依赖的 HTTP 验证；UI 注入错误仅证明前端展示，两类证据分别记录 |
| 失败、超时、缓存命中计次及 nullable 额度 | 合成后端 HTTP 验证，不自动退款，不伪装成 unlimited |
| 网络失败及明确重试 | Next 浏览器验证；Streamlit 本地 TCP 响应丢失探针：一次准入计 1，未自动重放，点击重试后计 2 |
| 重复提交、加载状态、移动端、2000 Unicode 字符 | 浏览器及对应回归测试；Streamlit 接受 2000 emoji、拒绝 2001 中文字符 |
| 真实微信输入法 | 用户在 Chrome 无痕分别测试 Next 与 Streamlit：第一次 Enter 结束组合且无计次，第二次 Enter 一次回答且只计 1 |
| Streamlit 完整刷新丢失身份 | 冻结契约 §2.4 允许；按用户选择保留契约并补提示，不声称跨刷新身份持久化 |

IME 实测第一次 Enter 留下字面拼音 `zhongwen`，证明该组合状态下没有误提交；不扩大为所有中文候选、所有输入法或浏览器兼容性结论。
测试替身及本地账本的结果不代表真实供应商、生产费用控制或公网环境结果。

## 3. 收尾检查

以下结果来自本轮收尾。Next 命令工作目录为 `v0.app-rag`，其他命令在仓库根目录执行。

| 检查 | 结果 |
| --- | --- |
| `pnpm test` | 18 项通过 |
| `pnpm typecheck`、`pnpm lint`、`pnpm build` | 全部通过 |
| `python -m pytest tests/test_demo_frontend.py tests/test_quota_frontend_contract.py --no-cov -q` | 29 项通过；不是全仓覆盖率证明 |
| `python -m flake8 app/ tests/ scripts/check_docs.py --max-line-length=88 --extend-ignore=E203,W503` | 通过；与 Make lint 范围一致 |
| 两个新增验收脚本的同参数 flake8 | 通过 |
| Make format 范围及三个验收脚本的 Black 只读比较 | 当前共 90 个 Python 文件无待格式化项；使用 Black 24.8.0 API 逐文件比较，未批量重写用户文件 |
| isort 5.13.0 | `--check-only app/ tests/ frontend/ scripts/check_docs.py scripts/acceptance/step5/` 通过；修正两处导入排序及一处混合换行，不改变 importorskip 执行顺序 |
| 隔离环境全仓 pytest 与 70% 覆盖率门槛 | **685 passed，80.56%，101.83 秒，exit 0**；此前缺依赖导致的 12 个收集错误已解除 |
| `make check-security` | 未执行：该目标会读取配置并调用 get_api_key，与本轮禁止读取 .env/密钥的约束冲突；不能声称生产安全配置检查通过 |
| `python scripts/check_docs.py`、`git diff --check` | 最终通过：54 Markdown、202 本地链接；Git 分支/HEAD 未变，未跟踪路径无敏感配置、账本或缓存混入 |

2026-10-08 全仓补验使用 Python 3.11.5 的 `.venv-step5-check`，通过 `--system-site-packages` 复用已有包；按两个 requirements 文件安装缺项及约束内版本：`langchain-chroma==0.1.4`、`isort==5.13.0`、`posthog==5.4.0`，另安装 isort 的传递依赖 `pipreqs==0.5.0`。未修改全局 Python 或依赖声明。

```powershell
& D:\Python311\python.exe -m venv --system-site-packages .venv-step5-check
& .\.venv-step5-check\Scripts\python.exe -m pip --isolated install --disable-pip-version-check --index-url https://pypi.org/simple -r requirements.txt -r requirements-frontend.txt
& .\.venv-step5-check\Scripts\python.exe scripts/acceptance/step5/repository_checks.py
& .\.venv-step5-check\Scripts\python.exe -m isort --check-only app/ tests/ frontend/ scripts/check_docs.py scripts/acceptance/step5/
& .\.venv-step5-check\Scripts\python.exe -m flake8 app/ tests/ scripts/check_docs.py scripts/acceptance/step5/ --max-line-length=88 --extend-ignore=E203,W503
```

检查脚本使用临时 cwd、清理继承环境、临时用户目录、禁用 dotenv/keyring 读取及业务 socket 连接；文件访问审计阻断仓库 data/logs/secrets、真实 .env 和 secrets 路径。仅允许 Windows 标准库 socketpair 的内部回环连接，以支持 asyncio；首轮全阻断导致框架初始化错误，已中止并修正包装后完整重跑。未 stub 缺失模块、未调用真实供应商、未降低门槛。pytest cache、合成数据和 HTML 覆盖率报告位于临时目录，正常退出后清理。

环境边界：这是复用系统包的检查环境，并非纯净依赖锁定环境。`pip check` 仍报告继承的 albumentations/pydantic、camelot-py/pandas/pypdf、paddlex/PyYAML、pipdeptree/pip 冲突；完整项目测试通过不代表全局包健康检查通过。deploy 应按仓库依赖在其独立环境验收，不复制此虚拟环境。首次联网安装受 sandbox 阻断，随后经升级执行安装成功。Black CLI 在本机未正常结束，已中止，最终格式结果来自无缓存 API 比较，不声称 CLI 命令通过。

额外前端 flake8 检查存在历史问题：`chat_interface.py` 为 E501 ×9；`streamlit_app.py` 为 E501 ×16、E402 ×4、W293 ×10、E722 ×1。与 HEAD 的同命令分类数量一致，本轮没有进行无关批量整改；这不等于扩展范围 lint 全通过。

## 4. 运行环境收尾与复现

- 已停止本轮拥有的合成服务；13010（Next）、18501（Streamlit）、18080（fixture）、18502/18081（辅助探针）均不再监听，3010 也无监听。
- 已删除两个残余的 `rag-step5-local-*` 临时目录；先断开复制前端中的 node_modules Junction，再删除目录。项目 `v0.app-rag/node_modules` 保留。
- `.next`、`node_modules`、`.pnpm-store`、`*.tsbuildinfo` 和临时运行目录保持忽略，不属于交付。
- 未读取或输出 .env、密钥、生产账本或敏感日志；未使用 Docker。
- 全仓补验正常退出的临时目录已自动删除；首轮中止残留目录已核对绝对路径后清理。最终六个验收端口无监听，检查虚拟环境保持忽略并保留供复验。

需要再次启动时，在独立 PowerShell 中运行：

```powershell
python scripts/acceptance/step5/local_dual_frontend.py --serve
```

访问 `http://127.0.0.1:13010/` 与 `http://127.0.0.1:18501/`。该命令持续运行，Ctrl+C 停止本轮服务；使用全新临时账本，历史测试额度不会保留。
不加 `--serve` 执行 HTTP/AppTest 合成检查并退出；浏览器操作与真实 IME 需要单独验证，脚本不会替代这些证据。

## 5. 下一步与审查勾选项

- [x] 本地合成双前端交互验收及手动 IME 结果归档。
- [x] Streamlit 刷新身份限制按冻结契约提示，明确计次和重试边界。
- [x] 测试服务与临时目录收尾，保留未提交内容及原有回执。
- [x] 补齐 isort 和完整隔离测试，覆盖率 80.56% ≥70%；安全配置读取继续排除在本轮授权范围外。
- [x] 复核已跟踪差异、未跟踪文件清单和 Next 核心请求/交互路径；未发现需改变冻结契约的缺陷。
- [x] 提交范围确认：8 个已修改文件、95 个新增文件，包含 Next 源码/配置/锁文件及原有 UI 组件与静态资源；原有回执明确排除。依赖、缓存、虚拟环境及运行数据不纳入。
- [x] 用户明确授权创建本地提交，不推送；本交付提交记录该授权与已审查范围。
- [ ] 固定版本后续交接仍待授权，由 deploy 审查接收；不得直接同步覆盖 deploy 工作区。
- [ ] deploy 负责生产部署、公网 HTTPS、真实供应商、持久卷及备份恢复验收，仍不属于 integration 范围。

本提交可作为后续固定版本交接的审查依据，不包含推送或部署授权。本地交互验收无需从头重做；后续代码、依赖或运行配置变化时按受影响范围补验。真实 `make check-security`、生产部署与上述环境边界均未被本轮全仓测试替代。
