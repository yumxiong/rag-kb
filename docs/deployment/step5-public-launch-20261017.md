# 应用启动及公网验收（2026-10-17）

> 阶段记录：下文“当前”“下一步”“本轮”均指 2026-10-17 对应阶段，不代表后续最终状态。
> 部署已完成并修复 Streamlit，当前基线及证据范围见[部署收尾总览](step5-deployment-baseline-20261020.md)。

用户明确授权应用启动及公网验收。前置[启动前准备](step5-prestart-readiness-20261017.md)
已完成。本轮停止 HTTP 初始化栈，使用独立 compose.app.yml 启动固定四服务栈；
`up -d --wait` 返回 0，backend、frontend、next、nginx 全部 healthy。
应用镜像源提交 `4d1ba85b46ade64bae52d5c200e3660c2671de0b`，只有 Nginx 发布 80/443。
本地输出解码曾报 GBK 错误，UTF-8 读取记录确认启动成功，不是服务器启动失败。

## 验收覆盖修正

2026-10-19 用户浏览器发现 Streamlit 导入错误，说明本阶段的 HTTP 200、WebSocket 101
及 header 身份 API 问答未覆盖 Streamlit 页面实际执行，不能称为完整浏览器问答验收。
随后完成[镜像修复与真实页面验证](step5-streamlit-import-fix-20261019.md)；
2026-10-20 用户报告两套前端在手机与电脑均可回答、带引用、拒答并提示额度。
后者为用户手动验收，不是本阶段自动化结果。

## 公网结果

- `https://otocshow.xyz`（Streamlit）和 `https://next.otocshow.xyz`（Next）页面 200。
  使用系统 CA 和各自真实主机名校验证书；HTTP 正确 301 到对应 HTTPS。
- 本机 DNS 受代理影响，验收直连 `191.40.41.77` 并保持真实 TLS SNI/Host，
  不关闭正常证书验证。此前 CA staging/正式签发提供独立域名 HTTP-01 验证。
- Next 静态资源 200，Streamlit WebSocket upgrade 101。
- 公开 library 正常，9 文档；匿名 document detail 401，docs 和旧 ws 路径 404。
- Next cookie 包含 HttpOnly、Secure、SameSite=Lax、Path=/api，无 Domain。
  非法 Origin 403；cookie 与 header 身份独立计次分别为 2、1。
- 未知 HTTP Host 404，未知 HTTPS SNI 返回 unrecognized_name；HSTS 不含 includeSubDomains。

## 受限真实问答

最多三次 ask，均经公网 Nginx、正式后端、真实供应商及远端金额账本准入，未自动重试。
三次均 HTTP 200、from_cache=false：

| 公开 AtlasDesk 用例 | 结果 | 端到端秒数 |
| --- | --- | --- |
| 网页单文件上限 | 回答 40 MB，并返回接入文档引用 | 3.16 |
| 私有化报价 | 明确文档无报价信息，未编造价格 | 2.12 |
| 更名后重复判断 | 回答规范化内容 SHA-256、非文件名，返回相关引用 | 2.30 |

程序只输出正式账本金额汇总，不输出身份或账本明细：2026-10-17 UTC 保守预留
6.631488 元，剩余 43.368512 元，未决请求 0；历史 2026-10-16 的 16.108672 元保留。
这是预留金额，不是供应商实际账单，未来公众访问会继续改变余额。

## 运行状态与范围

验收后四容器 healthy、restart_count=0、OOMKilled=false。一次空闲资源样本约为
backend 193.8 MiB、Streamlit 36.3 MiB、Next 79.67 MiB、Nginx 7.992 MiB。
这只是验收后的样本，不是并发容量或峰值验证。没有重做浏览器交互/IME 回归、
没有宣称历史前端全范围 lint 通过，也没有对运行中的正式账本做回滚恢复测试。

补充探针曾假定公开 library 暴露 document ID；实际仅含 filename/file_type/chunk_count。
改用任意 detail 路径确认匿名认证先于资源查找返回 401；未因此重复付费问答。
所有探针会话令牌仅存内存，没有写入公开记录。

## 下一步

优先落实自动续期：配置唯一调度、日志轮转，执行真实 renew dry-run 及脚本控制路径验证；
当前正式证书到期日为 2027-01-15 UTC，尚未安装续期 cron。
继续按用户决定人工每周及变更后检查证书与续期结果，不依赖邮件。
随后由用户在日常浏览器实测两入口；如需并发容量验收，应单独制定受限请求和费用预算。
每日备份任务仍未启用，现有启动前备份不能回滚后续真实消费。

本地非敏感证据位于忽略目录 `rag-step5-local-remote-20261017`：
`public-acceptance.json`、`public-extra.json`、`public-answers.json`、
`application-runtime-verification.txt`。服务保持运行，无回退或账本重置。
本记录与其余远端阶段记录于 2026-10-20 统一审查归档。
