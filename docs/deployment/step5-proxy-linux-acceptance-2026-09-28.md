# 第 2 步可信代理与 Linux 匿名账本隔离联验

日期：2026-09-28。工作区：`rag_kb-deploy`，分支 `deploy/production`，HEAD `da67133e1c80fa405c123e5a3d81d9ccbe2eab80` 加本轮未提交配置/验收脚本。协议仍为双方冻结的 `anonymous-quota-v1-draft.2`，正文提交 `0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`；未修改冻结协议或开始第 3 步。

**结论：隔离 Linux 容器中的第 2 步代理与账本检查通过；不是公网部署许可。** 正式 Linux 主机/域名/持久卷、完整浏览器链路、真实模型回归、全站预算及完整准入规则仍待验收。

## 修复及环境

交接时 public-sim 把 `172.30.0.10` 分配给 frontend，而后端信任该地址。现已把固定地址移至 nginx，frontend 恢复动态地址。其余七个已有修改保留；本轮没有修改 `app/`、`frontend/` 或 rag_kb-integration，也没有提交。

使用 `desktop-linux`、Linux `6.6.114.1-microsoft-standard-WSL2`。原有网段 `172.17.0.0/16`、`172.18.0.0/16` 与 `172.30.0.0/24` 无重叠。测试 internal network 中 nginx 为 `.10`、backend `.20`、frontend `.30`、独立 HTTPS 客户端 `.40`，无宿主端口映射；使用已存在的本地镜像，没有使用业务 secrets 或生产数据。

账本和独立 reference 为不同 Docker named volumes，实际文件系统 ext4、source `/dev/sdc`，`ANONYMOUS_STORAGE_DEVELOPMENT=false`。Windows bind mount 仅用于读取代码/配置，没有被算作持久卷验收。source 值只描述本次 VM，不是生产配置建议。

后端执行真实 FastAPI lifespan、会话、额度和问答路由，沿用镜像中的 Uvicorn 可信代理参数。检索与模型通过仅在验收脚本目录中的 `backend_fixture.py` 替换，不调用供应商；故障注入也是测试入口专属。Streamlit AppTest 执行真实聊天组件、session_state 和真实内部 HTTP，没有 mock requests。Nginx 使用当前 `public-sim.conf`，测试证书经客户端 CA/主机名校验；运行容器由隔离脚本组装，不是完整生产 Compose 的启动验收。

## 已观测结果

| 场景 | 结果 |
| --- | --- |
| HTTPS → Nginx → Uvicorn/FastAPI | ASGI peer 为真实测试客户端 `.40`，scheme 为 https；伪造的 XFF 链、X-Real-IP 和 X-Forwarded-Proto 未控制该值，Nginx 的 `.10` 未被误当作来源 |
| Streamlit → 内部 HTTP → FastAPI | ASGI peer 为 frontend `.30`，scheme 为 http；直连自报公网 IP/https 被忽略；持久 `session_ip` 只出现两个真实连接来源的摘要 |
| 两个独立 Cookie jar | 分别累计 2/1；Cookie 为 HttpOnly/Secure/SameSite=Lax/Path=/api、host-only；复用不延长期限 |
| Header 及跨传输一致性 | Header 独立会话累计 1；同一 Cookie token 分开用 Header 查询得到相同计数；同时提交 Cookie/Header 返回 400；伪造 token 返回 401，未允许 Origin 返回 403 |
| 两个 Streamlit AppTest session | 实际问答分别累计 2/1，rerun token 不变；Nginx 根路径能返回真实 Streamlit HTTP 页面 |
| 两条链路的来源限流 | 轮换 31 个伪造 XFF，均为前 30 次创建成功、第 31 次 HTTP 429 `rate_limited`，包含正数 Retry-After |
| 启动拒绝 | 12 个 Linux 存储测试通过；涵盖普通目录伪装挂载、错 source、缺 reference、两文件丢失、部分 bootstrap、UUID 不符、损坏/非法计数、目录 fsync 不可用、第二进程等 |
| 完整进程启动拒绝 | 只读 named volume、未挂载账本卷时，真实 `app.main:app` Uvicorn 启动失败，进程退出码 3 |
| 持久性 | 普通 restart、SIGKILL/start、删除后端容器并重新创建，完整账本相同；原 token、到期时间、创建日计数及个人计数保留 |
| 四个写入故障边界 | 临时文件创建、文件 fsync、replace、目录 fsync 分别注入 OSError；`/ask` 返回受控 503，测试引擎调用增量 0，后续 quota/session 均锁存 503，不签发新 token |
| 故障恢复 | 各阶段重启后原凭证/已确认计数有效。目录 fsync 失败发生在 replace 后，保守保留那次未确认增量；其他阶段不增加计数 |
| 日志与清理 | 检查服务原始日志没有完整匿名凭证；最终所有本次命名容器、网络和测试卷清理成功 |

这些故障是在真实 Linux 文件系统调用边界注入异常；不是硬盘掉电、真实 ENOSPC、块设备损坏或宿主机重启实验。零调用证据来自测试引擎计数，不能替代第 3 步真实供应商调用点的预算闸门验收。

## 可复跑证据

入口：`python scripts/acceptance/step5/run.py`。条件与隔离/清理说明见[运行说明](step5-anonymous-store-operations.md)。

- 首轮 `step5-544465390d` 通过基础代理、存储与故障检查；随后加强缺卷、容器重建、直连限流和日志检查。
- 最终轮 `step5-391ec58a94` 全部通过、`cleanup_complete=true`。机器可读报告：[脱敏报告](receipts/step5-proxy-linux-2026-09-28.json)，记录开始/结束时间、镜像 ID、源码/配置 SHA-256 和逐项结果。
- 本地详细日志保存在 `logs/step5-391ec58a94/`（Git 忽略）；ASGI 观察只记录路径、来源、scheme、凭证是否存在、HTTP 状态，不包含凭证值。
- 既有匿名会话测试在 backend Linux 镜像内为 **10 passed**；Windows `D:\Python311\python.exe -m pytest --no-cov -q tests/test_demo_frontend.py` 为 **5 passed**。
- 新脚本 Black、isort（容器内）、flake8 及 `git diff --check` 通过；基础 `docker compose -f docker/docker-compose.yml config --quiet` 通过，三个 Compose YAML 及代理地址关系由联验脚本解析核对。
- Windows 解释器直接收集匿名会话测试因缺少 `langchain_chroma` 失败，后切换到依赖齐全的后端镜像完成上述 10 项回归。本轮未重跑历史全量 439 passed，也未声称通过全项目 70% 覆盖率门槛。

## 仍未完成

- 没有 `.env.production`、目标主机上的独立 reference 和实际生产挂载源；本轮也没有创建 `.env.public-sim` 或业务证书。
- 没有真实生产域名/公网访问、完整浏览器 WebSocket 会话、Next 联调或真实模型问题回归。
- Docker VM 中的 named-volume/进程重启结果不证明物理主机掉电或生产磁盘持久性。
- 第 3 步全站预算、个人/全站原子准入和完整扣额顺序尚未开始；更完整的 429/503/502/504、并发与付费旁路验收仍按后续清单推进。

仅将第 2 步中已获证据支持的代理/隔离测试勾选，生产与后续步骤维持未勾选。
