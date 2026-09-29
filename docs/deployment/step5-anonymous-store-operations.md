# 第 2 步匿名账本本地运行与生产前置条件

此文档记录当前实现的操作入口，不是生产放行证明。当前生产 Compose 仍须在后续步骤完成卷、代理、限流、预算和故障验收。

## 本地 Windows 调试

停掉后端，选择全新的独立目录执行一次：

```powershell
python scripts/bootstrap-anonymous-store.py --storage data/quotas --reference data/anonymous-store-reference.json --development
```

`reference` 不能位于 `storage` 内。记下输出的 UUID，并核对 `quota-state-v1.json`、`initialized-v1.json` 和独立 reference 中的 UUID 一致。若任一文件已存在或上次初始化中断，工具拒绝覆盖；先人工核对，不能删除后重建已有额度。随后在本地进程环境设置 `QUOTA_STORAGE_PATH`、`ANONYMOUS_STORE_REFERENCE` 和 `ANONYMOUS_STORAGE_DEVELOPMENT=true`；本地 HTTP Cookie 测试才允许显式设置 `ANONYMOUS_COOKIE_SECURE=false`。Windows 调试不提供断电持久性保证。

## Linux 生产前置条件

生产建账必须使用与服务启动相同的预期挂载点和挂载来源。停服并确认持久卷后执行：

```sh
python scripts/bootstrap-anonymous-store.py \
  --storage /app/data/quotas \
  --reference /app/config/anonymous-store-reference.json \
  --mount-path /app/data \
  --mount-source '<source from /proc/self/mountinfo>'
```

挂载核验失败时，建账工具会在创建目录之前拒绝执行。

- 停服期间确认实际持久卷已挂载到 `/app/data`，检查 `/proc/self/mountinfo` 的挂载源与部署配置相符，且账本目录可写；不要在缺卷时执行 bootstrap。独立 reference 应放在配额卷之外的持久配置位置。
- 显式 bootstrap 一次，核对三个 UUID 后配置 `QUOTA_STORAGE_PATH`、`ANONYMOUS_STORE_REFERENCE`、`ANONYMOUS_MOUNT_PATH=/app/data`、`ANONYMOUS_MOUNT_SOURCE`（mountinfo 中的实际 source），并保持 `ANONYMOUS_STORAGE_DEVELOPMENT=false`、`ANONYMOUS_COOKIE_SECURE=true`。服务启动会拒绝缺卷、缺文件、UUID 错配、不可写或第二个进程；不得通过新建空目录规避拒绝。
- 只运行一个 Uvicorn worker。生产 Compose 模板已声明账本数据与独立 reference 挂载及必需环境配置，但实际 `.env.production`、reference、Linux 挂载源仍由部署人员准备和核验；模板存在不等于目标主机已经通过验收。不能仅靠本步骤启动公网 Demo。

## 可信代理规则

- 目前唯一可信反向代理为 Nginx。public-sim 与生产模板将 **nginx** 固定为 `172.30.0.10`，后端 `TRUSTED_PROXY_IPS=172.30.0.10`，由镜像启动命令传给 Uvicorn 的 `--forwarded-allow-ips`，并显式启用 `--proxy-headers`。frontend 不应占用或包含在此可信地址中，禁止设为 `*` 或整个 Docker 子网。
- Nginx 各 API location 覆盖 `X-Forwarded-For` 为 `$remote_addr`，覆盖 `X-Forwarded-Proto` 为 `$scheme`；不拼接公网客户端提交的地址链。Cookie 与 `X-Anonymous-Token` 沿真实 HTTP 请求透传，个人计数仍取后端已验证的凭证摘要。
- Streamlit 的 `http://backend:8000` 请求不经过 Nginx，Uvicorn 忽略其自报转发地址；会话创建速率与日创建计数使用 frontend 的真实连接 IP。不同 Streamlit session 使用不同 token，因此共享创建 IP 不等于共享个人额度。
- 当前只验证了单层 Nginx。以后增加 CDN/LB 时须重新定义并验收可信链，不能直接恢复追加任意客户端 XFF。
- 运行前检查 `docker network inspect` 的所有 IPAM 网段。`172.30.0.0/24` 若与已有网络重叠，应协调修改基础 Compose、生产模板子网、两个 Nginx 固定地址和可信地址，再重新验证；不要为解决冲突删除其他项目的网络。

## 可复跑的隔离 Linux 联验

在本工作区、Docker Linux engine 可用且本地已有 `docker-backend:latest`、`docker-frontend:latest`、`nginx:alpine` 时执行（宿主 Python 需 PyYAML）：

```powershell
python scripts/acceptance/step5/run.py
```

脚本使用随机 `step5-<id>` 前缀，先检查网段冲突及 Compose 中的 nginx/信任地址一致，再创建 internal network 和独立 named volumes。不会加载 `.env.public-sim`、`.env.production`、现有 secrets 或业务数据，也不映射宿主端口。运行结束在 `finally` 中清理本次创建的容器、网络及测试卷；若进程被强制中止，则按报告的 run ID 和 `step5.run` label 核查残留后仅清理对应资源，禁止全局 prune。

账本 `/app/data`、独立 `/reference`、存储故障测试目录均为 Linux named volume；只读 bind mount 仅用于本工作区源码和 Nginx 配置。脚本不使用 `development=true`，并拒绝将 9p/virtiofs 等 Windows 文件共享识别为通过的账本文件系统。本次实际观察为 ext4、mount source `/dev/sdc`；**其他部署不得照抄此 source，应重新读取自己的 `/proc/self/mountinfo`**。不同 named volume 可能共享设备 source，因此还须核对独立 reference、标记和账本 UUID，不能只看设备名。

Nginx 使用当前 public-sim 配置文件；脚本根据 Compose 声明的网段和可信地址组装隔离容器，并非启动现有生产 Compose。后端沿用已构建镜像的 Uvicorn 参数，测试入口仅替换为 `backend_fixture:app`：仍加载真实 FastAPI app/lifespan/身份/账本和问答路由，检索与模型为测试替身，另附测试专用 ASGI 观察及故障注入。此入口不打包到生产镜像，也不提供测试控制 API。

HTTPS 使用测试卷内生成的短期自签证书，客户端显式信任该证书并验证主机名，没有使用 `verify=False`。两个 Cookie 客户端经 Nginx 调用；两个 Streamlit AppTest session 在 frontend 容器中运行真实聊天组件，HTTP 不 mock，调用同一个后端。此范围验证内部调用和 rerun，不代表两个真实浏览器的 WebSocket/完整页面验收。

本轮包含：

- 真实 ASGI peer/scheme 与持久创建计数来源核验；两条链路轮换伪造 XFF 均无法绕过每分钟 30 次会话限制。
- 缺卷/普通目录伪装挂载、错 source、缺 reference、两文件同时丢失、部分 bootstrap、UUID 不匹配、损坏/非法计数、目录 fsync 不可用、只读卷和双进程拒绝。
- 普通重启、SIGKILL 后启动、容器删除重建后的完整账本一致性。
- 临时文件创建、文件 fsync、replace、目录 fsync 分阶段抛出 OSError；此前阶段真实执行，失败返回 503 且存储锁存为不健康。目录 fsync 失败前 replace 可能已生效，恢复后可以保留未确认的新增计数，不能倒退已确认计数。

`logs/step5-<id>/report.json` 保存脱敏结果、镜像 ID、源码摘要、挂载文件系统和清理结果；旁边保留脱敏服务日志与 ASGI 观察。原凭证只位于测试进程内存/临时测试卷，测试证书私钥与卷一起清理，不能归档它们。归档报告见 [2026-09-28 联验记录](step5-proxy-linux-acceptance-2026-09-28.md)。本测试证明 Docker Desktop Linux VM 上的进程故障处理，不证明目标生产磁盘、宿主机重启或断电持久性，也不覆盖尚未开始的全站预算和完整准入扣额规则。
