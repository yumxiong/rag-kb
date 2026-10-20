# 自动续期与日志轮转（2026-10-17）

> 阶段记录：下文“当前”“下一步”“本轮”均指 2026-10-17 对应阶段，不代表后续最终状态。
> 部署已完成并修复 Streamlit，当前基线及证据范围见[部署收尾总览](step5-deployment-baseline-20261020.md)。

用户授权配置自动续期、日志轮转及真实 `renew --dry-run`。前置
[公网启动验收](step5-public-launch-20261017.md)通过，应用保持运行。

## 已安装

服务器时区 CST / UTC+8，cron 服务和 logrotate.timer 均 active。
检查 root crontab、/etc/cron.d 和系统 timers 后未发现既有证书续期任务，
仅新增 `/etc/cron.d/rag-kb-renew`，每天北京时间 03:17 以 root 执行：

```cron
17 3 * * * root /bin/bash /opt/rag-kb/state/run-certificate-renewal.sh >> /opt/rag-kb/state/certbot-renew.log 2>&1
```

cron 文件 root 所有、0644，显式设置 SHELL、PATH，MAILTO 为空，不依赖邮件告警。
包装脚本 0700，记录起止时间及退出码，调用已固定的
`repository/scripts/deployment/renew-step5-certificates.sh /opt/rag-kb`。
核对远端续期脚本与本地 LF 规范化版本 SHA256 一致，`bash -n` 通过。
原脚本保留 flock 互斥、Compose 预检、Nginx 前后配置检查、renew 和 reload，失败停止，
不会自行启动应用。无证书变更时也可能执行一次低频 reload。

新增 `/etc/logrotate.d/rag-kb-renew`，仅覆盖 `state/certbot-renew.log`：daily、
rotate 14、compress、delaycompress、missingok、notifempty、create 0600 root root、
su root root。由已有 logrotate.timer 执行；不是每天新增一份空日志。
使用 rename/create，不使用 copytruncate；delaycompress 保留尚可能被写入的最近轮转文件。
轮转期间仍在执行的任务可能继续写入 `.1`，检查时应一并查看。

## 实际验证

- 持有相同续期锁，对两张正式 lineage 执行 `renew --dry-run --webroot`，
  root/next 均成功，退出码 0。正式 fullchain 文件哈希在测试前后相同。
- Certbot 非交互续期出现约 466 秒随机延迟，错误计数为 0；正常等待后完成，
  未并发重试或取消错峰机制。
- 使用接近 cron 的最小环境和 `/` 工作目录，手动执行同一包装命令，退出码 0。
  验证预检、续期检查、Nginx 复检及 reload 完整通过；未强制续发未到期证书。
- logrotate debug 解析通过，并对本任务日志执行一次真实 force 轮转；
  `.1` 与轮转前内容逐字节相同，新旧日志均为 0600。
- 结束后四容器全部 healthy、restart_count 0；公网两入口 HTTPS 证书校验及页面 200。
  无付费问答、无账本改动。

这验证了调度命令和服务配置，尚未等待首次次日 03:17 的自然触发，不能宣称已观测到
cron 定时执行。生产证书仍于 2027-01-15 UTC 到期；dry-run 不是正式续发。

## 后续用户核验

2026-10-19 用户表示已在服务器端手动确认自动续期任务执行成功。
这是用户提供的执行证据；代理未再次读取日志，不推断具体执行时间或发生了正式续发。

## 人工运维

首次计划执行后及此后每周、每次变更后，检查
`/opt/rag-kb/state/certbot-renew.log`（必要时连同 `.1`）的完成时间与 `exit=0`，
并核对两个公网证书有效期。失败时检查具体步骤，不删除证书或重置账本重试。
续期失败不会发外部通知，符合当前不搭建监控、人工检查的决定。

远端摘要 `/opt/rag-kb/state/renewal-readiness.json`；本地非敏感记录位于忽略目录
`rag-step5-local-remote-20261017` 的 `renew-dry-run.txt`、`renew-schedule-install.txt`、
`renew-schedule-verification.txt`。本记录于 2026-10-20 统一审查归档；续期配置阶段未改变应用源码和镜像。
