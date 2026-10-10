# Step 5 Next 部署接入方案与验收

日期：2026-10-09。基线 `738da665b634278fd92d7ab04ef2f2aa1f05a16c`。
本轮准备仓库变更，未生成或修改真实生产配置，未部署、提交或推送。

## 拓扑与文件

独立 Next 测试域名：浏览器 → HTTPS Nginx；页面和静态资源 → Next:3000，
同源 `/api/*` → backend:8000。既有域名的 Streamlit 根路径、管理入口及其
WebSocket 保持原配置。Next 与 Streamlit 不共享匿名身份，后端预算仍统一。

- [Next Dockerfile](../../v0.app-rag/Dockerfile)：Node 24.16.0 bookworm-slim、pnpm
  10.18.3、冻结锁文件安装，standalone 多阶段构建，非 root 运行、HTTP 健康检查。
- [Next 构建上下文](../../v0.app-rag/.dockerignore)：只允许源码和构建输入；排除
  本地环境、密钥、依赖与缓存。根目录 Docker ignore 也补充排除 Next 构建产物及验收目录。
- [Compose overlay](../../docker/docker-compose.next.yml)：追加 Next 内部服务，不发布
  3000 端口；挂载独立 next.conf，并等待 Next 健康。不存在的挂载文件直接报错。
- [Nginx 模板](../../docker/nginx/conf.d/next.conf.template)：独立虚拟主机，单独命名
  限流区，保留后端错误码及 Header，网关自己的 429/502/504 输出契约 JSON。
  覆盖 X-Forwarded-For、关闭 proxy_next_upstream，不对 ask 自动重放。

Next rewrite 仍由服务端 `RAG_BACKEND_ORIGIN` 控制；Docker build 显式设为
`http://backend:8000`，不得加 NEXT_PUBLIC 前缀。该地址在构建时写入产物；改变
目标必须重建镜像。公网 `/api` 由 Nginx 直接接管，不经 Next，避免改变 FastAPI
仅信任 Nginx 固定 IP 的链路。后端和 Next 均不得额外开放公网端口。

## 后续生产配置步骤（需要另外授权，不在本轮执行）

1. 选择独立 Next 域名、证书及容器内证书路径。在现有证书挂载下准备证书。
   只替换模板中的 NEXT_DOMAIN、NEXT_TLS_CERT、NEXT_TLS_KEY；不要对整个文件
   做无限制环境变量替换，以免清空 Nginx 的 `$host`、`$remote_addr` 等变量。
2. 输出至 gitignored `docker/nginx/conf.d/next.conf`；不要覆盖现有 Streamlit 配置。
3. 后端 `ALLOWED_ORIGINS` 追加准确的 Next HTTPS origin，保留既有 origin；
   Cookie Secure=true、host-only、Path=/api。后端 worker=1、replica=1，存储与
   独立 UUID 校验、预算配置不变，TRUSTED_PROXY_IPS 保持现有 Nginx 地址。
4. 组合顺序为 base → 已审阅的生产 overlay → next overlay。next overlay 使用
   Nginx 1.28-alpine，须连同已有虚拟主机做完整 `nginx -t` 和回归验收；不要
   将当前仍引用 production-init 的模板误当作已经启用 HTTPS 的生产文件。
5. 先测试域名验收，再另行决定首页切换。回滚时撤下 Next 虚拟主机挂载/服务，
   保留原 Streamlit 入口；不恢复旧账本、不撤销后端预算保护。

模板命令（生产配置读取及启动需单独授权）：

```powershell
docker compose -f docker/docker-compose.yml -f docker/docker-compose.production.yml -f docker/docker-compose.next.yml config --quiet
```

## 本轮已完成

- Next standalone `build` 通过（Next 16.2.6 / Turbopack）。
- [本机 standalone 探针](../../scripts/acceptance/step5/next_standalone_check.mjs)
  通过：真实 Node standalone server，首页、JS、public 图标；模拟后端响应的
  Set-Cookie、Cookie/Origin 转发、503 错误和每次 ask 仅一次上游请求。
  运行后已停止本轮 13011/18000 服务。
- `docker compose config --quiet`：独立 smoke 文件、base + next overlay 均通过；
  设置 COMPOSE_DISABLE_ENV_FILE=1，没有读取生产 overlay 或任何 .env。
- 新增两个 Node 脚本语法检查、Python AST、Python 探针 flake8 及 Git 差异检查通过。
  本轮 Black CLI 与 API 比较均长时间未返回，已中止，不宣称格式检查通过。
- 首轮 Docker 引擎未启动；用户启动后，Docker 29.7.2 下完成镜像构建、
  `nginx -t`、Next 健康检查及 HTTPS 合成探针，均通过。
- Next 运行 UID=1000，构建产物 rewrite 为 `http://backend:8000/api/:path*`；
  Next 与 fixture 均无宿主端口发布，网关仅发布 `127.0.0.1:18443`。
- 镜像标识：`sha256:17c64f0b8f99896340099412d17d893a3bb1d15f3629ce40a6f0b028a99d901e`。
  Linux 安装 296 个平台适用包，锁文件保持冻结；临时下载连接重置经重试恢复。
- 首次运行发现只接 internal 网络的网关没有实际发布端口：HostConfig 有绑定但
  NetworkSettings.Ports 为空，宿主连接拒绝。修正为仅网关追加 ingress 网络后
  完整探针通过；Next 与 fixture 仍仅连接 internal 网络。

standalone 探针仅验证传输和打包，不验证真实后端准入、预算或浏览器 Secure Cookie
行为，不替代既有 integration 证据和后续生产验收。

本机复现：在 `v0.app-rag` 中使用 pnpm 10.18.3 执行 `pnpm build`，然后回到
仓库根目录执行 `node scripts/acceptance/step5/next_standalone_check.mjs`。
须保留默认 loopback 构建目标，且 13011/18000 端口空闲；探针只访问临时传输替身。

## 本地 Docker 隔离验收与复现

仅使用独立 [smoke Compose](../../docker/docker-compose.next-smoke.yml)，不要与
生产文件组合。项目名固定为 rag-step5-next-smoke；唯一公开端口绑定
127.0.0.1:18443，Next/fixture 仅接内部网络；网关另接入口网络以发布端口，
因此不宣称网关本身禁止外连。无生产卷、配置或 key 挂载。
fixture 是传输替身，没有真实身份/账本/模型，不得用于生产。

执行 Docker 命令必须使用 require_escalated，注明“本地 Docker 隔离验收/只读检查”。

```powershell
# prepare 只创建新目录；已有目录时停止，避免覆盖。
& .\.venv-deploy-step5\Scripts\python.exe scripts/acceptance/step5/next_gateway_check.py prepare
$env:COMPOSE_DISABLE_ENV_FILE = '1'
docker compose -p rag-step5-next-smoke -f docker/docker-compose.next-smoke.yml up -d --build --wait
docker compose -p rag-step5-next-smoke -f docker/docker-compose.next-smoke.yml exec -T gateway nginx -t
& .\.venv-deploy-step5\Scripts\python.exe scripts/acceptance/step5/next_gateway_check.py probe
# 无论验收成败，停止本轮独立项目。
docker compose -p rag-step5-next-smoke -f docker/docker-compose.next-smoke.yml down
```

[HTTPS 探针](../../scripts/acceptance/step5/next_gateway_check.py) 使用本轮临时自签证书
进行证书校验，不禁用 TLS 验证。断言页面路由、Cookie 属性与转发、Origin、伪造
X-Forwarded-For 被覆盖、后端 429/503/502/504 保留、无重复 ask、网关真实限流及
/ws/ 404，均已通过。连接中断实际触发网关 502；无响应触发 90 秒网关 504
（断言耗时 89 至 105 秒），检查网关生成 request_id、no-store 和 JSON code。
七次 ask 的上游计数恰好增加七次，失败路径未重放。

本轮 `down` 已移除全部 smoke 容器及两张网络，项目 ps 为空；镜像缓存保留。
本轮生成的临时证书和配置保留在 gitignored 目录，复验须检查两天证书有效期；
prepare 不覆盖既有目录。未读取生产配置或敏感日志，未提交、推送或上线。

评审结论：第 3 项的容器及代理接入通过本地传输合成验收，可进入真实后端的
隔离链路验收。fixture 只提供传输替身，Cookie 是固定合成值，并非真实身份；
HTTP 客户端检查也不等于浏览器 Secure Cookie 验收。

真实后端 Origin 拒绝、身份隔离、准入计次和提前断连已由下述补验通过；
75 秒浏览器客户端取消边界尚未重新验证；90 秒网关超时和 502/504 映射已有合成证据。
生产 overlay 与既有虚拟主机组合尚未读取/运行。公网 HTTPS、真实供应商、生产持久卷与
备份恢复属于后续授权范围。无需无理由重复已有 IME 测试。

## 真实 FastAPI 准入链路补验

2026-10-09，独立项目 `rag-step5-next-real` 验收通过，probe exit 0。
新增 [Compose](../../docker/docker-compose.next-real.yml)、
[fixture](../../scripts/acceptance/step5/real_gateway_fixture.py) 和
[HTTPS 客户端](../../scripts/acceptance/step5/real_gateway_check.py)。

使用当前 deploy 的 app 源码只读挂载，真实路由、身份、存储、额度、并发、deadline
及异常映射不替换；仅向量库和问答引擎为合成依赖。Linux Python 依赖复用已有本地
镜像 `sha256:168bc2ec9e66a7f8f749996fcf882b1f7f4f1662c0dc27f1375948938b553387`，
不是本轮重新按 requirements 构建的后端发布镜像；独立 requirements 验收见
[环境记录](step5-deploy-environment-acceptance.md)。

隔离措施：后端只读根文件系统，`/app` 用空 tmpfs 遮蔽，所有运行目录和新 bootstrap
账本只在 `/tmp`；禁用 dotenv 与环境配置源，替换取 key 方法，阻断 socket 外连。
不挂载仓库根目录、真实配置、生产账本或日志；后端无宿主端口，Nginx 是唯一入口，
仅绑定 127.0.0.1:18443。Uvicorn 只信任本轮网关固定 IP 172.30.245.3。

| 场景 | 结果 |
| --- | --- |
| 两个独立 Cookie jar | A 提问后 used=1，B 保持 0；A 重新初始化复用身份，used 保持 1 |
| Origin 拒绝 | 带有效 Cookie 的不可信 Origin POST 返回 403 origin_not_allowed，额度不变 |
| 失败与缓存 | 合成引擎异常由真实路由映射 502；缓存标记响应成功，两者均各计一次 |
| 个人额度 | A 五次已准入后第六次返回 429 quota_exceeded，used=5；B 仍为 0 |
| 已准入后断连 | B 发送 8 秒慢请求，1 秒后确认 used=1 并关闭 HTTPS 连接；额度不退款 |
| 断连后槽位 | 工作线程未结束时返回 503 service_busy，不额外计次；结束后明确重试，used=2 |
| 后端真实 deadline | 70 秒合成工作触发真实 60 秒 deadline，返回 504 upstream_timeout，耗时断言 59 至 75 秒 |
| 超时后槽位与恢复 | 线程未退出时仍为 service_busy，used=3；线程结束后新提问成功，used=4；A 保持 5 |

请求只由客户端明确发送，断连等待期间额度保持不变；这些结果验证不自动重放、不退款、
槽位随工作线程生命周期释放。未模拟真实供应商内部取消或 SDK 重试；合成 cache 标记
不证明真实检索缓存。Cookie jar 是 HTTP 客户端，不等同于新增浏览器上下文验收。
前端 75 秒超时长于后端 60 秒 deadline，本轮提前断连不宣称覆盖浏览器 75 秒 AbortController。
未新增全站预算耗尽或 BYOK 场景，不扩大本轮结论。

首轮动态 Next IP 占用了后端固定 IP，启动失败；已为 Next 固定 .4、backend .2、
gateway .3 后重建独立项目，完整检查通过。`nginx -t`、新增脚本 flake8/AST 通过；
未重跑已知不返回的 Black 检查，不宣称 Black 通过。测试结束 `down` 成功，容器、
两张网络和 tmpfs 账本已移除，项目 ps 为空；原有未提交内容保留。

复现前需要上节临时证书/配置仍有效，18443 端口与 172.30.245.0/24 网段空闲：

```powershell
$env:COMPOSE_DISABLE_ENV_FILE = '1'
docker compose -p rag-step5-next-real -f docker/docker-compose.next-real.yml up -d --wait
docker compose -p rag-step5-next-real -f docker/docker-compose.next-real.yml exec -T gateway nginx -t
& .\.venv-deploy-step5\Scripts\python.exe scripts/acceptance/step5/real_gateway_check.py
docker compose -p rag-step5-next-real -f docker/docker-compose.next-real.yml down
```

评审结论：真实后端经新网关的本地身份、准入计次、断连及 deadline 场景通过。
下一阶段应收敛待提交变更并评审发布范围，再在明确授权下验证最终生产配置、真实供应商、
持久卷与恢复方案。当前没有生产切换、提交或推送授权。
