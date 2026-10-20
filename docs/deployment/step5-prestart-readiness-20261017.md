# 应用启动前准备（2026-10-17）

> 阶段记录：下文“当前”“下一步”“本轮”均指 2026-10-17 对应阶段，不代表后续最终状态。
> 部署已完成并修复 Streamlit，当前基线及证据范围见[部署收尾总览](step5-deployment-baseline-20261020.md)。

用户明确授权供应商密钥安全传输、JWT/管理员凭据生成，以及真实账本最终同步与切换。
本轮未启动应用，没有付费供应商调用。前置[正式证书](step5-production-certificates-20261017.md)
已就绪。

## 凭据

两把指定的本地供应商密钥通过固定主机指纹的 SSH stdin 传至
`191.40.41.77:/opt/rag-kb/secrets`，分别为 `chat_api_key`、`embedding_api_key`。
程序逐字节验证传输结果，未在命令参数、日志或聊天中输出密钥内容。

固定后端镜像在断网一次性容器中生成 JWT secret 和随机管理员密码，以项目所用
`pwdlib.PasswordHash.recommended()` 生成密码哈希。JWT 使用 48 字节随机源，
管理员密码使用 32 字节随机源，均以 URL-safe 编码保存。

- 应用只读挂载 `jwt_secret` 和 `admin_password_hash`。
- 管理员用户名 `admin`；原始随机密码仅存于服务器
  `/opt/rag-kb/state/admin-credentials.json`，不在应用挂载目录中。
- 上述四个 secret 文件及管理员凭据文件均核验为 root 所有、0600。
- 通过项目 Settings 实际读取文件，完成正确/错误密码验证及 JWT 签验；未启动认证服务。

管理员应在自己的受信任 SSH 终端读取密码并存入密码管理器，不将密码贴入聊天或 Git。
本轮没有把明文凭据下载回工作区。

## 账本最终同步和所有权

在本地原账本 `.quota.lock` 独占保护下重新读取并验证 schema、money 状态及
reference/marker 的身份一致性，将最新原字节传至远端
`/opt/rag-kb/state/ledger-final-20261017` 并校验哈希。

随后在同一锁保护期间将本地 reference 从
`rag-step5-local-paid-state/reference/anonymous-store-reference.json` 改名封存为
`anonymous-store-reference.retired-20261017.json`，保留内容及原账本。
此移动的两个绝对路径均核验位于本项目 paid-state 内，未覆盖现存文件。
本地新增 `REMOTE_OWNER_20261017.txt` 说明远端是唯一有效账本。
释放锁后验证：按旧 reference 路径重新打开本地账本返回 `quota_storage_unavailable`。

远端将最终副本原字节安装至正式路径：

- `/opt/rag-kb/data/quotas/quota-state-v1.json`
- `/opt/rag-kb/data/quotas/initialized-v1.json`
- `/opt/rag-kb/config/anonymous-store-reference.json`

没有运行 bootstrap，没有清空、退款或重置历史消费与未决请求。远端现为唯一有效 owner，
但应用进程尚未启动。本地封存文件不得放回原路径继续消费，也不能重新初始化本地账本。
历史暂存副本仍保留用于追溯，不用于覆盖更新后的正式账本。

## 验证和备份

使用固定后端镜像、`--network none`，正式 data/reference/secret 挂载及
production 模式（development=false）验证：

- `/dev/sda1` 挂载核验、账本打开及关闭后重新打开通过。
- 第二持有者和错误 mount source 均被拒绝。
- money 状态可读取；校验前后正式账本与最终同步副本哈希相同。
- 真实配置与认证文件读取通过，供应商网络调用次数为 0。
- 最终应用 Compose `config --quiet` 通过，不等同于应用启动验收。

所有一次性容器退出后，创建 `/opt/rag-kb/backups/prestart-20261017.tar.gz`，
包含 data 和独立 reference，逐成员哈希校验通过，受限权限保存并 fsync。
此备份包含真实账本，不能公开或加入 Git；运行后的新消费不能用旧备份回滚。
备份未包含 secrets、证书或整机配置，不宣称具备异机灾难恢复能力。

最终仅 HTTP 初始化 Nginx 运行且 healthy，仅发布 80。未启动应用、未开放 HTTPS，
未安装续期调度。临时验证容器均已退出。

## 下一步

单独授权应用启动及公网验收后：停止 HTTP 初始化栈，使用已固定镜像启动最终四服务栈，
核验两入口 HTTPS、API、Cookie、真实供应商及资源容量。真实接口验收必须沿用远端
正式金额账本，所有付费调用经过现有准入，不再使用本地旧账本。
部署就绪后还需配置并验证续期调度与 renew dry-run；当前自动续期尚未启用。

远端摘要为 `/opt/rag-kb/state/prestart-readiness.json`；本地非敏感结果在忽略目录
`rag-step5-local-remote-20261017` 中。此前远端准备、staging、签证和本记录于 2026-10-20 统一审查归档。
