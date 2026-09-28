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
- 只运行一个 Uvicorn worker。生产代理、HTTPS、Cookie、限流、预算和写入阶段故障注入按共享契约另行验收。当前默认 Docker 模板并未提供上述完整生产配置，不能仅靠本步骤启动公网 Demo。
