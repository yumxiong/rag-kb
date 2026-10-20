# 正式证书签发记录（2026-10-17）

> 阶段记录：下文“当前”“下一步”“本轮”均指 2026-10-17 对应阶段，不代表后续最终状态。
> 部署已完成并修复 Streamlit，当前基线及证据范围见[部署收尾总览](step5-deployment-baseline-20261020.md)。

用户明确授权正式签发两张证书；前置 [staging 验证](step5-acme-staging-20261017.md)
已通过。使用固定 Certbot 5.5.0 镜像，生产端点
`https://acme-v02.api.letsencrypt.org/directory`，webroot 为 `/var/www/certbot`，
注册邮箱为 `xihuyue@gmail.com`。分别指定独立 cert-name 和单一域名，不含 www。
两个 `certonly` 请求均成功，退出码 0，没有使用 dry-run。

| 证书/SAN | 生效时间（UTC） | 到期时间（UTC） |
| --- | --- | --- |
| otocshow.xyz | 2026-10-17 03:43:56 | 2027-01-15 03:43:55 |
| next.otocshow.xyz | 2026-10-17 03:44:07 | 2027-01-15 03:44:06 |

签发者均为 Let's Encrypt YE2。逐张核验 SAN 仅含对应域名、当前处于有效期内，
通过服务器系统信任根执行 `openssl verify -purpose sslserver -verify_hostname`，
链与主机名验证通过。检查 live 下四个文件的链接均指向各自 archive 目录；
私钥仅检查存在性、链接和权限元数据，没有读取或输出其内容。

正式证书保存在 `/opt/rag-kb/certbot/conf/live/<域名>/`。
两份 renewal 配置均指向生产 ACME endpoint，使用 webroot 和正确 challenge 路径。
这证明续期配置已生成，不代表定时续期已启用或续期 dry-run 已验收。

本次 Certbot 容器和空项目网络已清理。最终仅 `rag-step5-nginx-1` 运行，healthy，
仅发布 80；应用、443 和正式 HTTPS 服务尚未启动，账本仍未激活。
没有安装自动续期调度，没有执行公网 TLS 服务验收。

## 下一步

先完成应用启动前准备：明确授权向目标服务器传输两个供应商 API key（仅程序处理，
不显示内容）、安全生成并保存 JWT secret 和管理员凭据；停止本地付费写入后重新核对
账本副本，保留全部消费及未决金额，完成最终同步与所有权切换，验证生产模式存储。
之后单独授权应用启动，切换至最终 Nginx，再验收两入口公网 TLS、API、供应商与资源容量。

应用就绪后配置并验证续期调度和 `renew --dry-run`；按既有决定人工检查证书有效期，
不依赖到期邮件。正式证书已开始计时，应在到期前完成续期安排。

远端结果：`/opt/rag-kb/state/issuance-results.json`、
`/opt/rag-kb/state/production-certificate-verification.json`。
本地非敏感结果在忽略目录 `rag-step5-local-remote-20261017` 的
`issuance-output.txt` 和 `production-certificate-verification.txt`。
