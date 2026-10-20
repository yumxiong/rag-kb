# HTTP 初始化与 ACME staging 验证（2026-10-17）

> 阶段记录：下文“当前”“下一步”“本轮”均指 2026-10-17 对应阶段，不代表后续最终状态。
> 部署已完成并修复 Streamlit，当前基线及证据范围见[部署收尾总览](step5-deployment-baseline-20261020.md)。

用户明确授权启动仅 HTTP 初始化入口并执行 ACME staging。本轮未正式签证或启动应用。
目标服务器沿用已核对的 ED25519 固定指纹，前置准备见
[远端准备记录](step5-remote-preparation-20261017.md)。

## 已执行和验证

- 独立 `compose.init.yml`，项目名 `rag-step5`，仅 `rag-step5-nginx-1` 运行。
  Nginx healthy，`nginx -t` 通过，仅发布 `0.0.0.0:80`。
- 服务器 DNS 解析 root/next 均只有 `191.40.41.77`。本机 DNS 返回代理保留地址
  `198.18.1.145`，因此本机探针使用目标公网 IP 并显式设置 Host，不将此冒称本机
  普通域名解析链路验证。随后 CA staging 成功提供了独立的域名 HTTP-01 验证证据。
- 本机对两 Host 的公网请求分别确认：随机 challenge 200 且内容完全匹配、
  不存在的 challenge 404、页面 503。
- 首次探针 404 是因为 `docker compose exec -T` 消耗了远端 Bash 的后续 stdin，
  导致探针文件创建命令未执行；改为独立 Python 创建后全部通过。
  后续远端编排子进程显式使用 DEVNULL，不再复用脚本 stdin。
- 固定 Certbot 5.5.0 镜像，分别对 `otocshow.xyz` 和 `next.otocshow.xyz` 执行
  `certonly --dry-run --server https://acme-staging-v02.api.letsencrypt.org/directory`
  与 `--webroot -w /var/www/certbot --non-interactive --agree-tos`，注册邮箱
  `xihuyue@gmail.com`。两次均返回 `The dry run was successful.`，退出码 0。
  www 未列入请求。staging 账户已注册，其私有材料仅留在服务器受限证书目录。
- dry-run 后未发现 `live/*/fullchain.pem` 或 `renewal/*.conf`，未安装正式证书。
  临时 Certbot 容器自动删除，空 Certbot 项目网络和本次手动随机探针已清理。

## 当前状态和下一步

仅 HTTP 初始化 Nginx 留在运行，两域名应用页面继续返回 503；HTTPS 和应用均未启动。
账本仍为暂存副本，未激活；真实应用 secrets 尚未准备。未安装续期 cron。

下一步单独授权正式签发两张证书。正式签发须明确切换到生产 ACME endpoint，
去掉 `--dry-run`，保留各自独立 cert-name 与单域名 SAN，不能误用 staging server。
正式证书签发和核验完成后也不自动启动应用；应用 secrets、账本最终同步与所有权切换
仍须在应用启动前完成。

本地非敏感结果在忽略目录 `rag-step5-local-remote-20261017` 的
`http-public-results.json`、`staging-output.txt`、`staging-verification.txt`。
远端结果为 `/opt/rag-kb/state/staging-results.json` 与 `staging-verification.json`。
本记录不含证书私钥、账户私钥或账本内容。
