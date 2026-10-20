# Step5 远端准备记录（2026-10-17）

> 阶段记录：下文“当前”“下一步”“本轮”均指 2026-10-17 对应阶段，不代表后续最终状态。
> 部署已完成并修复 Streamlit，当前基线及证据范围见[部署收尾总览](step5-deployment-baseline-20261020.md)。

用户授权远端准备，并另行明确授权真实金额账本及独立 reference 向目标服务器传输、
暂存和校验。本轮未获证书签发或应用启动授权，因此均未执行。

## 已完成

- 目标 `191.40.41.77`，ED25519 公钥与用户云控制台指纹
  `SHA256:yxUaukNKLR72JR7yOR3gl9yYd+S0MSVcQ3Rv/7fcof0` 一致。
  固定记录位于本地忽略目录 `rag-step5-local-remote-20261017/known_hosts`。
  本机 ssh-keyscan 的 KEX 不兼容，改用 SSH 的 curve25519-sha256，人工核对
  显示的指纹一致后保存，后续连接均使用 StrictHostKeyChecking=yes。
- 准备前无容器、无镜像、无 `/opt/rag-kb`。现有 Docker 网络为 172.17/16、
  172.18/16，与候选 172.30/24 无冲突。保留 1Panel、Docker 和现有网络。
- 创建 `/opt/rag-kb` 及 data、config、secrets、state、backups、certbot、releases。
  私有目录受限；公开 challenge webroot 及其子目录为 0755。
- 固定包上传到 `/opt/rag-kb/releases/20261017-4d1ba85`，所有 SHA256SUMS 项匹配。
  源快照安全解包到 `/opt/rag-kb/repository`，源提交为
  `4d1ba85b46ade64bae52d5c200e3660c2671de0b`。
- 公开 AtlasDesk v3 知识库安装到 data，逐文件哈希匹配。未重建或调用供应商。
- 加载三个应用镜像及 Nginx、Certbot，共五个；核对 linux/amd64、固定镜像 ID
  或配置摘要、应用源提交标签，均匹配[固定清单](step5-fixed-delivery-manifest.json)。
- 无网络、只读临时容器取得 data 的 mount source 为 `/dev/sda1`，填入外置
  `/opt/rag-kb/release.env`；外置 backend.env 仅含已确认非敏感配置及 secret 路径。
  四份独立 Compose `config --quiet` 通过；不代表 secrets、reference、证书已就绪。
- 目标 Linux 缺失 bind source 拒绝且不自动创建目录；宿主临时目录完成
  write、file fsync、replace、directory fsync 检查后清理。
- 最终磁盘约 31 GB 可用，无容器残留，监听仍为 22 和 38821，无 80/443。

首次远端 Bash 脚本受 Windows CRLF 影响失败，尚未进入目录创建；改以字节传输 LF
后完成。本轮没有覆盖原有项目目录或删除用户文件。

## 真实账本衔接状态

自动审批最初要求对敏感账本向该目的地传输补充明确授权；用户确认后才执行。
本地 `rag-step5-local-paid-state` 仍是原始账本，未重置、删除或改写金额。
使用既有 `.quota.lock` 排除并发写入，程序验证 schema 与身份关联后传输三个文件，
不将内容输出给模型。远端暂存位置为：

`/opt/rag-kb/state/ledger-handoff-20261017`

目录 0700，文件按 umask 077 创建并 fsync，传输后逐文件哈希匹配。
固定后端镜像通过无网络、只读挂载校验 schema、money 状态、reference/marker 身份关联
及哈希。没有运行 bootstrap，没有创建 `/opt/rag-kb/data/quotas` 或正式 config/reference。

这是一份未启用的副本，不是已完成所有权切换。应用启动前须停止本地付费写入，
重新在锁保护下核对本地与暂存副本；如发生变化必须同步最新状态，再完成显式切换。
保留所有历史消费和未决请求，不能初始化零账本替代。未启用前本地原件仍需保留。

## 后续行动与授权边界

1. 下一步单独授权仅 HTTP 初始化入口和 ACME staging 验证：先验证 root/next 公网
   challenge，再用邮箱 `xihuyue@gmail.com` 验证两张独立证书；www 不在本服务器签发。
   当前未启动 HTTP 入口、未接受 ACME 条款、未创建账户、未申请证书。
2. staging 成功后，正式签证按授权执行；不自动启动最终应用。
3. 应用启动前准备四个真实 secret 文件（当前远端 secrets 为空）、完成账本最终同步与
   所有权切换、验证目标 Linux 下正式账本挂载与存储保护，再单独授权应用启动。
   本轮没有传输 API 密钥，也没有生成管理员密码或 JWT secret。
4. 生产容量、真实供应商、公网 TLS、续期和恢复仍需对应阶段验收。
   未安装 cron、监控或每日备份任务；备份目录已准备，仍采用用户选择的轻量方案。

本地非敏感操作结果在忽略目录 `rag-step5-local-remote-20261017`；远端摘要为
`/opt/rag-kb/state/remote-preparation.json`。本记录不包含私钥、API key 或账本内容。
