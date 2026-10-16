# Step 5 首次部署候选与隔离验收

日期：2026-10-15。状态：本地配置候选，尚未提交、上传或在服务器执行。
应用基线为 `62d4cffbaad0a84b6f2def76f3dbd992d3f53bb9`，当前记录 HEAD 为
`76df9da1983aa8faa9b6e789a3ec985189e41c0e`。本文中的 Linux 命令是后续操作方案，
**需要另行授权远端准备、真实签证和启动服务**，本轮均未执行。

2026-10-16 的路径、供应商、费用要求与轻量运维决定见
[部署参数确认](step5-deployment-decisions.md)。其后续决定优先于本文历史待确认项；
每日 50 元的保守金额准入已在本地代码实现，见[金额准入说明](step5-money-admission.md)。
旧固定镜像不含此能力；新镜像及目标环境尚待验收，不能直接启动付费服务。
[受限真实对照](step5-paid-model-comparison.md)发现新嵌入模型检索回归，建议保留 v3；
当前候选仍指向新模型，须先确认最终模型并同步调整独立索引路径。

## 候选组成

- [初始化 Compose](../../docker/step5-candidate/compose.init.yml)：仅 HTTP Nginx，
  两个应用域名开放 ACME 路径，页面返回 503；不需要证书或后端。
- [最终 Compose](../../docker/step5-candidate/compose.app.yml)：backend、Streamlit、
  Next、Nginx 四服务。只有 Nginx 发布 80/443，后端单 worker、单副本。
- [Certbot Compose](../../docker/step5-candidate/compose.certbot.yml)：独立短生命周期
  服务，不挂 Docker socket、应用 secrets 或账本。
- [初始化账本 Compose](../../docker/step5-candidate/compose.bootstrap.yml)：无网络、
  必须显式调用；挂载已审查的初始化脚本，拒绝覆盖已有或部分初始化状态。
- [发布参数示例](../../docker/step5-candidate/release.env.example) 和
  [后端参数示例](../../docker/step5-candidate/backend.env.example)：占位符必须替换；
  示例只含文件引用，没有密钥。次数配额与 50 元金额预算已确认，详见部署参数记录。
- [续期脚本](../../scripts/deployment/renew-step5-certificates.sh)：宿主调度入口，
  配置预检 → Nginx 预检 → renew → Nginx 复检 → reload，失败即停止，并带互斥锁。

这些 Compose 文件分别独立使用，**不要叠加旧基础/production/Next overlays**，
也不要运行旧 `scripts/deploy.sh`。最终 Nginx 整目录只读挂载，避免单文件 bind
在原子替换后继续读取旧 inode。Certbot 整个目录树共享，保留 live/archive 链接。

根域名固定为 Streamlit，`next.otocshow.xyz` 固定为 Next。www 保持 Dynadot
302 导航，不加入本机 server_name 或证书 SAN；切换导航在 Dynadot 完成。
未知 HTTP Host 返回 404，未知 HTTPS SNI 拒绝握手。HSTS 不包含 includeSubDomains
或 preload。Next 同源 `/api` 由 Nginx 直接转发后端，Next 镜像仍须按
`RAG_BACKEND_ORIGIN=http://backend:8000` 构建。保持 host-only Cookie、后端准入、
不自动重试 ask、失败计次及两个前端独立身份的契约。

## 目标主机准备方案

建议固定代码目录 `/opt/rag-kb/repository`，运行目录 `/opt/rag-kb`。交付完整受审查
代码快照及可追溯镜像，不复制 integration 工作区或本地虚拟环境。服务器为
2 CPU/4 GiB，优先异机构建后交付；镜像可使用受控 registry digest 或经校验的
save/load 离线包，须核对 linux/amd64 和 image ID，不能将本地 ID 当成 registry digest。

远端准备前确认：80/443 云安全组、公网 DNS/无错误 AAAA、路径、ACME 联系邮箱、
模型供应商与预算，以及备份存放位置。保留 1Panel 和现有网络；再次确认
172.30.0.0/24 不冲突。只在授权后创建以下目录并以受限权限准备配置：

```bash
umask 077
install -d -m 700 /opt/rag-kb/{data,config,secrets,state,certbot/conf}
install -d -m 755 /opt/rag-kb/certbot/www
install -d -m 755 /opt/rag-kb/certbot/www/.well-known
install -d -m 755 /opt/rag-kb/certbot/www/.well-known/acme-challenge
```

`certbot/www` 只存放公开 challenge；挂载到容器后的目录及其 challenge 子目录
必须允许 Nginx 非 root worker 遍历，challenge 文件须可读（通常为 0644）。
不要把证书、私钥或应用 secrets 放在这个公开目录，也不要递归放宽其他目录权限。
目标机签证前须通过实际 HTTP challenge 探针核验读取权限。

由操作者在仓库外准备 `release.env`、`backend.env` 及四个 secrets 文件；JWT
secret 和管理员密码哈希须符合现有认证规则。不要将真实内容填回示例或输出完整
`docker compose config`/容器环境。secret 文件须对实际容器 UID 可读，其他用户不可读。
不要给占位符配置启动放行，也不要用 `make check-security` 读取当前禁止访问的配置。

下列 bash 会话仅用于未来操作，`release.env` 只承载 Compose 插值，backend.env
仅提供后端环境，两者不能混用。不依赖隐式 `.env`：

```bash
set -euo pipefail
export COMPOSE_DISABLE_ENV_FILE=1 DEPLOY_ROOT=/opt/rag-kb
cd /opt/rag-kb/repository
bundle="$PWD/docker/step5-candidate"
init=(docker compose --env-file "$DEPLOY_ROOT/release.env" -p rag-step5 -f "$bundle/compose.init.yml")
app=(docker compose --env-file "$DEPLOY_ROOT/release.env" -p rag-step5 -f "$bundle/compose.app.yml")
cert=(docker compose --env-file "$DEPLOY_ROOT/release.env" -p rag-step5-certbot -f "$bundle/compose.certbot.yml")
boot=(docker compose --env-file "$DEPLOY_ROOT/release.env" -p rag-step5-bootstrap -f "$bundle/compose.bootstrap.yml")
for path in data config secrets state certbot/conf certbot/www; do
  test -d "$DEPLOY_ROOT/$path"
done
test -f "$DEPLOY_ROOT/backend.env"
"${init[@]}" config --quiet
"${cert[@]}" config --quiet
```

宿主目录存在性检查是必须步骤。本地 Docker Desktop 实测会创建缺失的 Windows
bind 目录，不能只依赖 `create_host_path: false`；目标 Linux 行为须再核验。

## 首次签证与账本准备

先启动仅 HTTP 初始化入口，确认两个域名的 challenge 文件可从公网访问。
真实 staging dry-run、接受 ACME 服务条款及正式签发均需另行授权；以下邮箱为占位符：

```bash
"${init[@]}" up -d --wait
"${init[@]}" exec -T nginx nginx -t
for host in otocshow.xyz next.otocshow.xyz; do
  "${cert[@]}" run --rm --no-deps certbot certonly --dry-run --webroot \
    -w /var/www/certbot --non-interactive --agree-tos \
    --email REPLACE_WITH_ACME_EMAIL --cert-name "$host" -d "$host"
done
```

staging 验证通过后，经授权用相同参数移除 `--dry-run` 正式签发。检查两张证书的
SAN、有效期、lineage 与文件存在性，不读取私钥。没有正式证书不能启动最终 Nginx。

账本只允许在后端停止、data/quotas 全新且 reference 不存在时显式初始化。
首先通过同一 bootstrap 服务、同一 data bind 只读取得 mountinfo：

```bash
ANONYMOUS_MOUNT_SOURCE=probe-only "${boot[@]}" run --rm --no-deps --entrypoint python bootstrap -B -c \
  'from pathlib import Path; print(next(x for x in Path("/proc/self/mountinfo").read_text().splitlines() if x.split(" - ")[0].split()[4]=="/app/data"))'
```

取分隔符 ` - ` 后的第二字段，按 mountinfo 八进制转义解码，写入 release.env
的 `ANONYMOUS_MOUNT_SOURCE`；不要填写宿主目录，不照抄 Windows 的 source。
配置 reference 在独立目录之外挂载。确认没有现存或部分初始化数据再执行：

```bash
"${boot[@]}" config --quiet
"${boot[@]}" run --rm --no-deps bootstrap
test -f "$DEPLOY_ROOT/config/anonymous-store-reference.json"
"${app[@]}" config --quiet
```

若失败，停止检查原因，不能删账本重试。正式上线前应对 data、reference 和配置
制定一致性备份与恢复流程；恢复不能回退已消耗额度，也不能并行运行两个后端。

## 最终启动与续期调度方案

确认 secrets 可读、两张正式证书就绪、镜像已固定及存储核验通过后，才授权切换：

```bash
"${init[@]}" down
"${app[@]}" up -d --wait
"${app[@]}" exec -T nginx nginx -t
```

这会有明确的入口停机窗口。启动失败时保留账本与 reference，按故障定位回退到
初始化入口，不重新初始化。随后验证公网 TLS、两入口、API、真实供应商、资源
峰值和数据恢复；仅容器 healthy 不代表这些验收已完成。

只安装一套调度。建议 root cron，每天 03:17（服务器时区）：

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 3 * * * /bin/bash /opt/rag-kb/repository/scripts/deployment/renew-step5-certificates.sh /opt/rag-kb >> /opt/rag-kb/state/certbot-renew.log 2>&1
```

日志仅保留在受限目录并配置轮转；用户选择暂不搭建监控，改为人工定期检查续期
结果和证书有效期，不依赖 ACME 邮件。本脚本不会启动应用，也没有 Docker socket 容器挂载。renew
没有更新证书时仍可能成功，允许每日一次无变更重载。真实 `renew --dry-run`
及定时任务执行须在目标机另行验收；本轮没有创建账户、申请证书或安装 cron。

## 本地隔离验收证据

使用本地既有应用镜像、loopback 18080/18443、合成证书和全新测试数据。
后端 fixture 使用真实会话/准入路由，替换向量和供应商访问，禁止外部连接；
不等于生产 app.main 启动或真实供应商验收。没有重复既有浏览器/IME/75 秒专项。

| 项目 | 结果与边界 |
| --- | --- |
| 无证书初始化 | 两域名 ACME 200、缺失 challenge 404、应用 503、www 404、health 200 |
| 最终入口 | 双 TLS 主机名验证、HTTP 跳转、ACME、两页面、Next 静态资源、Streamlit WS 101 |
| API 契约 | session、Secure/HttpOnly/host-only Cookie、ask 成功与计次、非法 Origin 403、公开 library、匿名 detail 401、docs/ws 404 |
| 网络边界 | 仅 Nginx 发布 loopback 端口，其余应用无宿主端口 |
| 证书加载 | 合成证书替换、nginx -t/reload 后观察新序列号；无效配置校验失败，旧 worker 继续服务 |
| 续期控制 | 离线模拟 Docker，成功顺序及预检/renew/复检/reload 失败退出、并发锁均通过；不模拟 ACME 成功 |
| 初始化账本 | 实际 production-mode 初始化，错误 mount source 拒绝、重复初始化拒绝且合成文件哈希不变 |
| 缺失目录 | Desktop 自动创建缺失 Windows bind 路径，记为限制；宿主 preflight 与目标 Linux 补验必需 |
| Certbot | 本地镜像版本 5.5.0；仅运行 --version，没有真实签证/续期 |

测试入口为 [入口验收](../../scripts/acceptance/step5/first_deployment_check.py)、
[初始化验收](../../scripts/acceptance/step5/bootstrap_candidate_check.py)、
[续期控制验收](../../scripts/acceptance/step5/renewal_control_check.py)。后者在无网络、
只读 rootfs 容器执行，`/tmp:exec` 仅供模拟命令；不挂 Docker socket。
所有测试容器与项目网络清理，合成证书/账本仅保留在被 Git 忽略的本地证据目录。
新增三个 Python 探针通过 Black 格式化、isort 检查及规定参数 flake8；续期脚本
通过 `bash -n`。四份 Compose YAML 解析及候选文件空白检查通过；文档检查覆盖
60 个 Markdown、234 个本地链接，明确排除原有 Step4 私有证据目录。
入口脚本首次运行因响应头大小写导致断言失败，规范化后通过；续期模拟首次因
tmpfs noexec 失败，测试容器调整为 `/tmp:exec` 后通过，未降低生产配置限制。

### 候选审查修正与针对性验证（2026-10-16）

- 公开 challenge webroot 及子目录单独使用 0755；证书、secrets 等目录仍为 0700。
  使用固定本地 Nginx 镜像与 Linux tmpfs 实测：root 所有的 0700 webroot 使两个
  主机的 challenge 均返回 404（`try_files` 映射）；改为 0755 后均返回 200。
  这验证 Linux 权限机制，目标服务器 bind 目录和公网 HTTP-01 仍需另行验收。
- 入口验收脚本清除继承的 Compose 控制变量，显式覆盖全部测试插值参数，并在
  启动前核对解析后的 bind 均位于本次合成目录、发布端口仅为指定 loopback 端口。
  注入冲突的目录、镜像、端口等环境变量后，实际 Compose 解析仍保持隔离；
  另以错误配置验证越界 bind 与公网端口会被拒绝。
- 未知 SNI 探针只接受服务器 `unrecognized_name` 告警；该负向探针关闭客户端
  证书校验，正常双主机 TLS 验证保持不变。针对性实测已确认正确配置拒绝未知 SNI；
  将测试默认虚拟主机改为提供根域名证书后，探针正确失败，不再误把主机名不匹配当通过。
- 本次仅启动一个临时 Nginx 容器，完成后已删除；未启动应用或 Certbot，未调用
  真实供应商或 ACME。成功合成证据目录为
  `rag-step5-local-first-deployment-20261016-110803`，被 Git 忽略，不提交其证书或私钥。
  针对性驱动保留于忽略目录 `rag-step5-local-review-fixes`。
- 首次尝试因本机 Docker engine 未运行而停止；启动 Docker Desktop 后，权限负例
  原先预期 403，按候选 `try_files` 的实际 404 行为修正断言后通过。
  修改的入口 Python 脚本通过 Black、isort 和规定参数 flake8 检查。

镜像 ID（本地验证，不代表已发布 registry digest）：

| 镜像 | SHA256 |
| --- | --- |
| backend | `38f92c22e43aef4729f0215efe7719315ae073ea7068b3bf7b638a212e614b1f` |
| Streamlit | `332f6a72f66b7206b745f4a55f2a25a6050772e4101e4790173248d77591583f` |
| Next | `770ec2eace84c54ac036ccd56cb5597f5e0594d8c83a9f51a6795496687948f5` |
| Nginx | `a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236` |
| Certbot | `78a7eaa40af657301e25731297b6e73646c695370d17e9bb03189fa82966d65c` |

结论：可以进入配置候选审查与本地提交阶段，尚不具备直接生产启动条件。
下一阶段先确认路径、镜像交付方式、供应商/预算、邮箱及云安全组，再分别授权远端
准备、staging/正式签证和应用启动。服务器容量、真实供应商、公网访问、定时续期、
持久卷与备份恢复仍是部署验收项。
