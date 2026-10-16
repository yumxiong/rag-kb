# Step 5 生产配置草案：双主机入口

日期：2026-10-15。状态：服务器基础条件已只读核验，完整候选已完成本地隔离验收，非部署授权。

应用验收基线：`62d4cffbaad0a84b6f2def76f3dbd992d3f53bb9`。
验收记录提交：`76df9da1983aa8faa9b6e789a3ec985189e41c0e`。
用户已选择保留 Streamlit 主域名，并为 Next 使用同一注册域名下的子域名。

## 入口与身份

| 入口 | 页面上游 | API 上游 |
| --- | --- | --- |
| `https://otocshow.xyz` | `frontend:8501`（Streamlit） | `backend:8000` |
| `https://next.otocshow.xyz` | `next:3000`（Next） | `backend:8000` |
| `http(s)://www.otocshow.xyz` | Dynadot Forward 302 → `https://next.otocshow.xyz` | 不承载应用 API |

用户确认：DNS 在 Dynadot 管理，无 CDN；`next` 已设置 A 记录指向服务器，
`www` 已设置 Dynadot Forward (302)。Forward 是 DNS 管理平台附带的 HTTP
转发服务，不是 CNAME，也不是本机 Nginx 规则。www 切换目标时需修改 Dynadot
Forward 设置，而非只重载本机 Nginx。浏览器跳转后使用目标主机的 host-only
Cookie；不迁移两个应用之间的身份、个人额度或对话。

两者共用 Nginx 的 80/443 端口，按 Host 分流。后端、Next、Streamlit 不发布宿主端口。
Next 浏览器只访问自己的同源 `/api`；服务端 rewrite 继续使用
`RAG_BACKEND_ORIGIN=http://backend:8000`，公网 API 由 Nginx 直接转发后端。
不添加 `NEXT_PUBLIC` 后端地址，不修改 ask 自动重试策略。

Next Cookie 保持 HttpOnly、Secure、SameSite=Lax、Path=/api，不设置 Domain。
Streamlit 继续使用服务端 session 的 `X-Anonymous-Token`；两个前端不共享身份。
子域名是不同 origin，但仍属于同一 site；子域名划分不替代后端 Origin 校验。

## DNS 与证书待落实

- 用户已配置 `next.otocshow.xyz` 的 A 记录；上线前仍须从无代理干扰的网络
  核对实际地址。只有 IPv6 入口确实可用时才添加 AAAA。
- 当前草案假定浏览器直连 Nginx。若使用 CDN、代理模式或负载均衡，必须先重新
  审查可信代理链，不能直接套用单层 Nginx 的 IP/协议处理。
- 已确认使用两张独立证书，分别只覆盖 `otocshow.xyz` 和 `next.otocshow.xyz`。
  仅覆盖根域名的证书不覆盖子域名；`*.otocshow.xyz` 也不自动覆盖根域名。
- 下方路径采用“两张 Let's Encrypt 证书”的规划值，不代表证书已签发或文件存在。
  若沿用其他证书服务，应改为实际只读挂载内的路径，不读取或提交私钥内容。
- www 由 Dynadot 转发端终止 TLS，其 HTTPS 证书及续期是独立的责任边界。
  本机 Nginx 不再为 www 提供应用虚拟主机；不能假定服务器的 Certbot 可以
  通过原有 webroot 为指向 Dynadot 的 www 完成 HTTP-01 验证。

## 当前完整候选

执行方案以 [首次部署候选与隔离验收](step5-first-deployment-candidate.md) 为准。
已从 deploy 的 Step5 模板形成独立的 `docker/step5-candidate/` 配置包，包含
无证书初始化、双 HTTPS 最终入口、独立 Certbot 和显式账本初始化四份 Compose。
不再采用旧基础 Compose → production overlay → Next overlay 的组合方式。
Nginx 使用独立 default health server，整目录只读挂载最终配置。
本地合成 TLS、ACME 路径、页面/WebSocket、真实后端准入 fixture、证书重载和
续期失败阻断已验收；证据边界、平台限制和未来命令见上述记录。

## 持久卷、镜像与预算

- 以实际服务器部署目录为准核对 `${DEPLOY_ROOT}/data` 的 bind source 和 Linux 文件系统。
  不因新目录缺少账本而自动 bootstrap，不覆盖、回退或重建已有账本。
- reference 必须在配额挂载之外，作为预先存在的只读文件挂载；建议同样使用
  `create_host_path: false`，缺文件时直接失败，避免自动创建目录。
- `ANONYMOUS_MOUNT_SOURCE` 是目标容器 `/proc/self/mountinfo` 的实际 source，
  不是随意填宿主目录，也不能照抄本地 Docker Desktop 的设备名。
  它须在 Compose 插值阶段提供；service `env_file` 不提供 Compose 插值变量。
- 保留已批准的个人额度、全站预算、UTC 日边界、60 秒 deadline 和并发保护。
  本轮不读取 `.env.production`，因此实际生效值仍待非敏感字段核验。
- 旧模板以 build 为主；新候选要求显式提供镜像引用。上线前须选择固定的发布镜像引用，
  记录镜像 ID/仓库 digest 及目标架构，不把本地 image ID 当成已发布的 registry digest。
  本地已验收镜像见 [固定版本验收记录](step5-fixed-predeployment-acceptance.md)。

## 后续核验顺序与回滚

1. 从可信网络核对入口解析；服务器尚未部署，按两张独立证书首次签发准备。
   www 继续由 Dynadot 提供 HTTPS 转发，不加入本机证书；签发后再验公网 TLS 与续期。
2. 根据目标服务器路径审阅完整生产配置，检查固定代理 IP 和网段冲突、非敏感
   环境值、持久卷/reference 的独立性及备份方案。不得输出完整容器环境或密钥。
3. 在无生产数据的隔离环境验证完整组合配置、健康检查、两个主机 TLS、WebSocket、
   同源 API 与错误码。新候选已通过本地合成隔离验收，目标主机和真实配置仍需补验。
4. 获得授权后才执行目标环境备份/恢复演练、真实供应商及公网验收、发布切换。
5. Next 入口回滚时撤下其虚拟主机和服务，保留 Streamlit HTTPS 入口与已经核验的
   后端预算保护；DNS/证书按实际方案处理，不回滚账本或恢复旧额度。

## Certbot 与公开 HTTPS 只读审查（2026-10-14）

### 观测结果及限制

- 本次访问 www 的 HTTP 和 HTTPS 均返回 302，Location 为
  `https://next.otocshow.xyz`，没有跟随重定向发送业务请求。
- www 的 TLS 握手通过系统信任及主机名校验。该访问路径展示的证书由
  Let's Encrypt YR1 签发，SAN 为 `*.otocshow.xyz`、`otocshow.xyz`，有效期
  2026-09-11 09:23:41 UTC 至 2026-12-10 09:23:40 UTC，覆盖 www。
  这是 www 访问端的证书证据，不证明应用服务器的 Certbot lineage 覆盖 www，
  也不证明同一证书已经部署到根域名或 Next 入口。
- 本机 DNS（含指定 1.1.1.1 的查询）返回 198.18 段合成地址，可能受本地代理
  干扰；根域名、Next 的 TLS 握手返回 EOF。故未确认权威 DNS 的真实地址，
  也不把这些失败认定为服务器故障或证书缺失；需从独立网络复核。
- 主仓库本地 `docker/certbot/conf` 只有 accounts、renewal、renewal-hooks
  等目录，没有 live 证书目录，renewal 与各 hook 子目录未枚举到文件；实际
  `docker-compose.certbot.override.yml` 也不存在。未读取 accounts 内容或私钥。
  目前无法从本地副本核验服务器证书、实际 renewal 参数或已安装定时任务。

### 仓库机制与风险

[部署脚本](../../scripts/deploy.sh) 的 227 行起为 `${DOMAIN}` 和 `www.${DOMAIN}`
一起申请 webroot 证书。257 行生成的 cron 每日服务器时间 03:17 执行
`certbot renew --webroot -w /var/www/certbot --quiet`，返回成功后执行
`nginx -s reload`。这证明脚本包含续期与重载安排，不证明服务器安装且正在
运行这份 cron。不要为了安装定时任务重新运行完整 deploy.sh；它还会生成配置、
构建并启动服务。

- renew 在无证书到期时也可成功退出，因此现有安排并非“仅发生续期才重载”。
- 重载前没有 `nginx -t`；现有行尾输出重定向只覆盖 reload，不能声称收集了
  完整续期失败输出。应为整个执行链设置日志与失败告警，并做好敏感信息保护。
- [生产模板](../../docker/docker-compose.production.yml.template) 中注释掉的
  每 12 小时 renew 循环没有 Nginx reload；不能与宿主机 cron 混为一谈，也
  不应未经核实同时启用两套调度。
- 若实际根域名证书包含 www，且仍以本机 webroot 验证 www，外部 Forward
  可能把 challenge 请求送往别处。任一 SAN 验证失败可能导致整张证书无法续期。
  不能仅凭当前 www HTTPS 正常就认定根域名续期安全。
- 新模板要求 `ANONYMOUS_MOUNT_SOURCE` 在 Compose 插值阶段存在；cron 不继承
  交互 shell 的临时变量。未来续期作业需使用经审查的独立 Certbot Compose
  定义，或显式准备完整组合的非敏感插值输入；禁止打印整个环境。

### 续期设计依据（历史审查；本地实现见完整候选）

1. 先只读列出服务器证书 SAN、有效期、lineage 名称、authenticator/webroot
   映射及调度方式，检查是否包含 www，不输出账户信息、私钥或完整运行日志。
2. 建议服务器管理两张证书：仅 `otocshow.xyz` 和仅 `next.otocshow.xyz`；www
   由 Dynadot 负责 HTTPS 转发。若现有证书含 www，另行授权后迁移 lineage/SAN，
   不直接删旧证书或修改 renewal 文件，不提前切到尚不存在的证书路径。
3. 两个应用主机的 HTTP `/.well-known/acme-challenge/` 必须到达 Certbot
   与 Nginx 共享的 webroot。签发 Next 前，先准备不会引用缺失证书的验证入口。
4. 选用一套宿主机 cron/systemd 调度：续期成功 → `nginx -t` 成功 → reload。
   可接受低频无变更重载；若仅希望实际续期时重载，可用 deploy-hook 写入
   专用共享标记，再由宿主调度读取并执行校验/重载，成功后清除标记。
   Certbot 容器无需为此挂载 Docker socket 或获取控制其他容器的权限。
5. 在单独授权后执行 staging dry-run，验证 challenge 与调度，再验证实际
   证书加载；dry-run 不是只读操作，本轮没有执行。

上述历史只读审查没有修改 DNS、签证或重载服务。后续本地合成容器验收见完整候选；服务器未变更。

## 目标服务器只读核验（2026-10-15）

用户随后明确项目尚未部署，并提供服务器访问方式。通过云控制台截图核对
SSH 主机公钥后，严格固定匹配的 ED25519 主机密钥完成登录。用户授权收紧
本地指定 SSH 私钥文件 ACL 为当前用户与 SYSTEM；没有修改密钥内容或服务器配置。

| 项目 | 实测 |
| --- | --- |
| 系统 | Debian 13 (trixie)，x86_64，2 个可用 CPU |
| 内存 | 3921 MiB，总体约 4 GiB；检查时可用 3397 MiB；无 swap |
| 根磁盘 | 40 GiB，检查时可用约 35 GiB |
| Docker / Compose | 29.8.1 / v5.5.1；Docker 服务 active |
| 容器、镜像、卷、构建缓存 | 均为空 |
| TCP 监听 | SSH 22、1Panel 38821、loopback SSH 转发端口；无 80/443/8000/8501/3000 |
| Docker 网络 | bridge `172.17.0.0/16`、1panel-network `172.18.0.0/16`；与候选 `172.30.0.0/24` 不重叠 |
| 服务器解析 | 根域名、Next 解析为用户提供的目标 IP；www 解析为外部转发地址 |
| Certbot | 无宿主 certbot 可执行程序，无容器；`/etc/letsencrypt` 不存在 |
| 续期调度 | 无 root crontab；常规系统 cron/systemd 文件未检出 Certbot/Let's Encrypt/Nginx reload 条目 |
| 部署目录 | 在 `/opt`、`/srv`、`/root` 的限定深度检查未发现匹配项目目录 |

上述结论不是全盘搜索或未来资源容量保证。未读取 `.env`、SSH 私钥内容、
证书私钥、生产账本或日志。未安装软件、创建远端目录、上传文件、启动容器、
运行 Certbot 或修改防火墙。主机 nftables 规则已只读检查；云平台安全组未核验，
80/443 无监听也不能证明端口已允许公网入站。

此前关于“旧根域名+www证书可能无法续期”的判断是针对旧部署脚本的条件风险，
不是本服务器已有故障。当前应按**首次签发**处理：为根域名和 Next 分别签发
证书，不把由 Dynadot 转发的 www 加入本机 webroot 证书 SAN。www 公开访问端的
证书不属于已核验的本机 Certbot 安装。

本地已形成并隔离验收完整首次部署候选，见 [当前操作方案](step5-first-deployment-candidate.md)：
HTTP ACME 初始化配置、双 HTTPS 最终配置、独立 Certbot 及续期后 `nginx -t`/reload 调度草案。
候选应保留既有 1Panel，不删除其网络；不需要重新安装已可用的 Docker。
2 CPU/4 GiB 主机宜优先使用已构建且可追溯的镜像，构建内存峰值和运行容量仍需
验证，不以当前空载资源推断完整构建一定成功。
在另行授权远端安装、签证或部署前，明确部署根目录、镜像交付方式、云防火墙
80/443 放行和 ACME 联系方式；不在本文中记录私钥路径或秘密值。
