# Step 5 推送前门禁收尾

日期：2026-10-09。检查基线：`a05a4c6729044a14da79db53c2f4ef98ffa6cea6`。

结论：当前工作树的格式、规定范围 lint 和隔离全仓测试通过，可进入后续本地提交及
推送评审。此结论不是推送授权或生产就绪确认；格式修正与本文尚需后续提交固定。

## Black 卡住的定位与处理

Black 24.8.0 在 import 阶段即不返回，尚未遍历业务文件。`faulthandler` 的
5 秒栈显示卡在标准库 tempfile 的 `_mkstemp_inner` / NamedTemporaryFile，
调用来自 Black 编译模块加载链路。将进程 TEMP、TMP、BLACK_CACHE_DIR 指向工作区
内被忽略的 `.venv-deploy-step5/gate-tmp` 后，版本查询和 Black CLI 均正常结束。
这定位了默认临时文件路径相关问题；未据此推断杀毒软件或系统权限的具体根因，
未修改系统临时目录、全局环境变量或工具版本。

首次 CLI 检查：3 个新增验收脚本需格式化，90 个文件不变。仅格式化：

- `scripts/acceptance/step5/next_gateway_check.py`
- `scripts/acceptance/step5/real_gateway_check.py`
- `scripts/acceptance/step5/real_gateway_fixture.py`

改动仅为参数换行；与基线提交逐文件比较 `ast.dump(..., include_attributes=False)`
完全一致。未修改 app、frontend、Next、Docker/Nginx 配置、锁文件或 tests。

## 实际门禁结果

| 检查 | 结果 |
| --- | --- |
| `make format` | exit 0；Black 83 文件不变，isort 通过 |
| `make lint` | exit 0；严格沿用 Makefile 的 app/tests/scripts/check_docs.py 范围 |
| Black CLI 扩展检查 | 93 文件无需改动，exit 0；含全部 Step5 验收 Python 脚本 |
| isort 扩展 check-only | Make format 范围加 Step5 脚本，exit 0 |
| Step5 脚本 flake8 | exit 0，参数与 Make lint 一致 |
| `pip check` | No broken requirements found，exit 0 |
| 全仓隔离 pytest | **685 passed，94.70 秒，80.56% 覆盖率，exit 0**；门槛保留 70% |
| 已跟踪文档链接 | 56 Markdown、218 本地链接通过；未扫描原有 Step4 未跟踪目录 |
| AST 等价及差异检查 | 3 脚本 AST 不变；git diff --check 通过 |

本轮没有直接执行 `make test`：原目标直接启动 pytest，不提供配置/密钥隔离。
使用仓库 `repository_checks.py` 执行同一全仓 tests、pytest.ini、app 覆盖率和
原门槛，禁用真实配置、keyring 和业务网络，并将账本/报告放入临时 cwd。
这是同范围隔离测试门禁通过，不声称原始 `make format && make lint && make test`
整条命令已原样执行。用户禁止读取真实配置/密钥的边界继续优先。

## 复现

在仓库根目录的 PowerShell 中执行；变量只作用于当前进程及其子进程：

```powershell
New-Item -ItemType Directory -Force .venv-deploy-step5/gate-tmp | Out-Null
$env:TEMP = (Resolve-Path .venv-deploy-step5/gate-tmp).Path
$env:TMP = $env:TEMP
$env:BLACK_CACHE_DIR = Join-Path $env:TEMP 'black-cache'
$env:BLACK_NUM_WORKERS = '1'
$env:PATH = (Resolve-Path .venv-deploy-step5/Scripts).Path + ';' + $env:PATH
make format
make lint
python -m black --check --workers 1 app/ tests/ frontend/ scripts/check_docs.py scripts/acceptance/step5/
python -m isort --check-only app/ tests/ frontend/ scripts/check_docs.py scripts/acceptance/step5/
python -m flake8 scripts/acceptance/step5/ --max-line-length=88 --extend-ignore=E203,W503
python -m pip --isolated check
python scripts/acceptance/step5/repository_checks.py
```

## 候选与下一步

[RC1 清单](step5-release-candidate-manifest.json)保留原提交快照；其中 3 个脚本的
旧哈希仍代表 RC1，不代表这次格式化后的工作树。不要用当前文件匹配旧清单后宣称
新候选固定；后续本地提交应只包含 3 个格式修正与本文，共 4 文件，并记录新的 SHA。

历史文档中的 Black 未完成记录保持历史事实；当前状态以本次 CLI 通过记录为准。
本轮未修改前端代码，沿用已通过的 Next 21 测试、typecheck/lint 和构建证据；
AST 等价的格式修正无需重跑耗时 Docker/浏览器联验。

仍不宣称扩展 frontend flake8 全通过；Makefile 未包含该历史问题范围。
make check-security 仍未运行，因为它会读取真实配置并调用 get_api_key。
生产虚拟主机组合、真实供应商、持久卷和恢复验收边界未改变。

建议下一步：审查并授权创建 4 文件门禁收尾本地提交，再以新完整 SHA 确认推送目标
分支和远端、评审累积提交范围。推送与上线仍需独立明确授权。
