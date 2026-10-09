# Step 5 deploy 发布候选 RC1

日期：2026-10-09。状态：**可进入本地提交评审；有条件发布候选，尚未批准生产发布。**

## 基线与候选身份

- 工作区：`D:\claudeCode\rag_kb-deploy`，分支 `deploy/production`。
- 基线 HEAD：`738da665b634278fd92d7ab04ef2f2aa1f05a16c`。
- 本候选是基线之上的未提交变更，没有新的提交 SHA；RC1 名称不代替 Git 提交身份。
- [候选内容清单](step5-release-candidate-manifest.json)记录 18 个主体文件的 SHA-256
  和 Git blob OID（按 Git clean 规则计算，不写对象）。修改后应重审并更新清单。
- 加上本文和清单，候选共 **20 文件：5 修改、15 新增**。清单不自包含，也不哈希本文。

## 精确纳入范围

| 组 | 文件 | 目的 |
| --- | --- | --- |
| 错误契约修正 | `v0.app-rag/lib/api.ts`、`v0.app-rag/tests/api.test.ts` | 解析 retry_after_seconds；新增 body 回退、Header 单独使用和优先级测试，不自动重放 ask |
| Next 打包 | `v0.app-rag/next.config.mjs`、`v0.app-rag/Dockerfile`、`v0.app-rag/.dockerignore` | standalone、多阶段镜像、Node 24.16.0 / pnpm 10.18.3、非 root、构建输入白名单 |
| 部署接入 | `docker/docker-compose.next.yml`、`docker/nginx/conf.d/next.conf.template` | 独立域名，页面到 Next，同源 API 到后端；不切换既有 Streamlit 首页 |
| 排除本地文件 | `.gitignore`、`.dockerignore` | 排除生成配置、依赖、构建产物和验收目录 |
| 传输合成验收 | `docker/docker-compose.next-smoke.yml`、`scripts/acceptance/step5/gateway_fixture.mjs`、`scripts/acceptance/step5/next_gateway_check.py`、`scripts/acceptance/step5/next_standalone_check.mjs` | 打包、HTTPS、转发、限流、网关 502/90 秒 504、不重放 |
| 真实准入验收 | `docker/docker-compose.next-real.yml`、`scripts/acceptance/step5/real_gateway_fixture.py`、`scripts/acceptance/step5/real_gateway_check.py` | 真实 FastAPI 路由/身份/额度/并发/deadline，临时账本与合成引擎 |
| 记录 | `docs/deployment/step5-deploy-environment-acceptance.md`、`docs/deployment/step5-next-deployment.md`、本文、`docs/deployment/step5-release-candidate-manifest.json` | 环境、证据、限制、发布边界与固定审查清单 |

排除并保留 `.step4-evidence/`、`.step4-run/`。不读取或纳入它们的内容。
所有 `.env*`、密钥/证书、生成的 next.conf、生产配置、账本、日志、虚拟环境、
node_modules、.next、包缓存及 rag-step5-local-* 运行目录均不纳入。
integration 原有未跟踪回执不属于此候选，不读取、复制或补交。

## 评审结果与发布条件

未发现阻止形成候选的业务逻辑问题。本轮只整理候选及复核，未改变此前验收的源码
和部署实现。冻结身份/计次/nullable 额度/同源 API 契约没有变化，后端 app 源码无差异。

| 事项与位置 | 判断与后续要求 |
| --- | --- |
| `docker/docker-compose.next-real.yml` 的本地 SHA 镜像及 smoke-next:latest | 仅验收工具前置条件，不是可在任意机器拉取的发布镜像；跨机复验须先准备等价依赖镜像并重新记录镜像身份，不能把该 Compose 当生产部署 |
| `docker/docker-compose.next.yml` 的 nginx:1.28-alpine | 会覆盖共享 Nginx 镜像；隔离模板已通过 nginx -t，但既有 Streamlit 虚拟主机及最终生产组合未验收，生产切换前必须补验 |
| Node/Nginx 镜像 tag | 固定版本号不等于不可变 digest；发布时记录实际镜像 digest，改变基础镜像或依赖后按影响补验 |
| 新增 Python 验收脚本 | flake8/AST 通过；Black CLI/API 未正常结束，不宣称格式门禁全部通过。推送前需完成仓库要求的 format/lint/test 门禁，不做无关批量整改 |
| 真实环境与安全 | make check-security 未运行；它读取真实配置/密钥，与当前边界冲突。真实供应商、生产持久卷/备份恢复、公网 HTTPS 仍须另行授权验收 |

这是一份有条件的发布候选，不是生产就绪确认。没有授权暂存、提交、推送、生产配置
读取或上线；本轮未执行这些操作。

## 证据与适用范围

- 独立 Python 环境：pip check 通过，685 passed，覆盖率 80.56% ≥70%。这是
  固定基线的环境验收；后续变更未修改 app/，不把旧结果说成候选重新全仓运行。
- Next 字段修正后：21 项测试、typecheck、lint 通过；standalone 和 Linux 镜像构建通过。
- 传输 fixture：Cookie/Origin、转发头、后端错误、Nginx 限流、实际 90 秒 504 与
  连接中断 502，通过七次 ask/七次上游计数证明无代理重放。
- 真实准入 fixture：身份隔离/复用、Origin 拒绝、失败/cache 标记计次、个人限额、
  提前断连、真实 60 秒 deadline 及工作线程槽位保留通过。模型/向量依赖为合成替身，
  不宣称真实供应商、真实缓存实现或新增全站预算/BYOK 覆盖。
- 75 秒浏览器 AbortController 未在新网关下重测。先前 IME/浏览器证据沿用原限定范围。
- 两个 Docker 验收项目均已 down；临时账本随容器销毁。临时证书目录被忽略，未纳入。

详见[环境验收](step5-deploy-environment-acceptance.md)与
[部署接入及两轮网关验收](step5-next-deployment.md)。

本轮候选复核：20 路径与 18 份 SHA-256/Git blob OID 一致，候选 Markdown 的
16 个本地链接通过，新增 Python AST/规定参数 flake8 通过，Git diff --check 通过。
三组 Compose（smoke、real、base+next）解析通过；两个验收项目 ps 为空。
全程未读取生产 overlay 或 .env，暂存区无差异。业务实现未变，未重复全仓或浏览器验收。

## 后续提交与发布建议

建议作为一个自包含本地提交：
`feat(deploy): prepare Step 5 Next gateway release candidate`。
说明应覆盖错误契约修正、Next 镜像/代理、隔离验收、共享 Nginx 变更和上述证据限制。

得到明确本地提交授权后，先验证 HEAD、清单哈希及工作区，再按清单逐路径暂存
18 个主体文件及本文/清单；禁止 `git add .`。暂存后确认恰好 20 文件、5 M/15 A，
执行 staged diff 检查，审查无关文件未混入，再创建本地提交并记录完整 SHA。
这不包含 push 或生产部署授权。

生产候选应在提交 SHA 固定后，再确定测试域名、证书、origin allowlist、最终镜像
digest、既有虚拟主机兼容性、持久化和恢复步骤。上线和回滚均不得重置额度账本。
