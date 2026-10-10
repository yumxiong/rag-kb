# Step 5 deploy 独立环境验收

日期：2026-10-09。工作区：`D:\claudeCode\rag_kb-deploy`。

结论：固定交接版本的独立依赖环境验收通过；不代表生产部署验收。

## 版本与范围

- 分支：`deploy/production`。
- 验收 HEAD：`738da665b634278fd92d7ab04ef2f2aa1f05a16c`。
- 父提交：`9d42d19bc89fd26995b084828b39bf603483cda6`。
- 依据：[integration 交付清单](step5-delivery-checklist.md)及[既有验收记录](step5-acceptance.md)。
- 本轮仅建立 deploy 依赖环境、运行检查并记录结果；未修改业务代码、依赖声明或锁文件。

## 环境与结果

| 项目 | 本轮结果 |
| --- | --- |
| Python | Windows，Python 3.11.5；新建 `.venv-deploy-step5`，不复用 integration 环境 |
| 环境隔离 | `include-system-site-packages = false`；user site 禁用；site-packages 仅来自该虚拟环境 |
| Python 安装 | 按 `requirements.txt` 和 `requirements-frontend.txt` 从公开 PyPI 安装，exit 0 |
| `pip check` | `No broken requirements found.`，exit 0 |
| 隔离全仓 pytest | **685 passed，90.83 秒，覆盖率 80.56%，exit 0** |
| 覆盖率门槛 | 保留 pytest.ini 的 70% 门槛；3617 statements，703 missed |
| Node | 24.16.0 |
| pnpm | 固定使用 10.18.3；临时 npm exec 获取，不修改全局工具 |
| Next 安装 | `install --frozen-lockfile`，295 packages，exit 0；不更新锁文件 |
| Next 测试 | 18 passed，0 failed，exit 0 |
| Next lint / build / typecheck | 均 exit 0；Next 16.2.6，Turbopack 构建 |

Python 传递依赖由当日解析得到，并非完整锁定环境；本次安装及测试通过不构成未来依赖解析结果相同的保证。安装结果包括 posthog 5.4.0、openai 1.109.1、numpy 1.26.4、unstructured-client 0.26.2。未额外覆盖仓库版本约束。

## 可复现命令

以下创建命令仅用于尚不存在的环境；本轮环境已保留，不要覆盖重建。

```powershell
python -m venv .venv-deploy-step5
& .\.venv-deploy-step5\Scripts\python.exe -m pip --isolated install --disable-pip-version-check --index-url https://pypi.org/simple -r requirements.txt -r requirements-frontend.txt
& .\.venv-deploy-step5\Scripts\python.exe -m pip --isolated check
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& .\.venv-deploy-step5\Scripts\python.exe scripts/acceptance/step5/repository_checks.py

Push-Location v0.app-rag
$env:CI = 'true'
$env:NEXT_TELEMETRY_DISABLED = '1'
npm exec --yes --registry=https://registry.npmjs.org --package=pnpm@10.18.3 -- pnpm install --frozen-lockfile --store-dir .pnpm-store --registry https://registry.npmjs.org
npm exec --yes --registry=https://registry.npmjs.org --package=pnpm@10.18.3 -- pnpm test
npm exec --yes --registry=https://registry.npmjs.org --package=pnpm@10.18.3 -- pnpm lint
npm exec --yes --registry=https://registry.npmjs.org --package=pnpm@10.18.3 -- pnpm build
npm exec --yes --registry=https://registry.npmjs.org --package=pnpm@10.18.3 -- pnpm typecheck
Pop-Location
```

实际检查阶段直接用 Node 调用 npm 缓存中已下载的 pnpm 10.18.3 CLI，避免再次访问 registry；各 package script 与上述命令一致。build 先于单独 typecheck 执行，以产生新环境的 `.next/types`。

## 安装过程与边界

- 首次 pip/pnpm 下载被沙箱网络限制阻断，后经升级执行访问公开包源成功。Next 下载中的临时连接重置在工具重试后恢复。
- 本机 pnpm 11.7.0 首轮退出码为 1，报告 `ERR_PNPM_IGNORED_BUILDS`，并自动在 workspace 文件加入 `allowBuilds` 占位字段。本轮已将该文件逐字节恢复为固定提交原文；没有批准 esbuild/sharp 构建脚本。后续使用 pnpm 10.18.3 成功安装，保留原有 `ignoredBuiltDependencies`。
- pnpm 10 首次因无 TTY 拒绝重建本轮 node_modules；核实目录位于 deploy 且非重解析点后，设置 CI 模式重建成功。未触碰 integration 依赖或用户既有目录。
- npm exec 的离线调用曾因缓存元数据不可用失败；随后直接调用已下载的固定 CLI，测试成功执行。
- Python 使用仓库隔离脚本：临时 cwd、合成配置、禁用 dotenv/keyring、阻断业务 socket 连接及敏感文件访问；只允许 Windows 标准库 socketpair 内部连接。保留真实应用模块和原有测试门槛，正常退出清理临时测试目录及覆盖率报告。
- Next 项目没有 `.env*` 文件；关闭构建遥测。本轮未启动前后端联验服务，也未重复浏览器或 IME 验收。
- 构建产物的同源 `/api/:path*` rewrite 指向默认 `http://127.0.0.1:18000/api/:path*`。这仅是本地构建验证，不能作为生产镜像的代理配置交付。
- `.venv-deploy-step5`、node_modules、包缓存、`.next` 和 tsbuildinfo 保持忽略；原有 `.step4-evidence/`、`.step4-run/` 保留。
- 未读取真实配置、密钥、生产账本或敏感日志；未运行 `make check-security`。未使用 Docker、真实供应商、生产环境或外部消息功能；未提交或推送。
- 本轮未重跑 Python 格式及 lint；既有 Black CLI 和扩展 frontend lint 限制不因本轮测试通过而改变。

## 下一步

第二项是修正 `v0.app-rag/lib/api.ts` 中错误体回退字段 `retry_after` 为契约的 `retry_after_seconds`，增加针对性测试。部署接入时固定 Node/pnpm 工具版本，准备 Next 容器及同源代理拓扑，再按变更范围验收。生产 HTTPS、真实供应商、真实安全配置、持久卷与备份恢复仍需后续授权。
