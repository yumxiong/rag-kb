# Docker 部署指南

命令从仓库根目录执行，需要 Docker Engine 和 Compose v2。配置结构已核对，实际镜像构建、HTTPS 和问答尚待实测。

## 配置与端口

| 文件 | 用法 | 宿主机端口 |
| --- | --- | --- |
| `docker-compose.yml` | 基础服务定义，未给后端加载 env_file | 无；expose 8000/8501 仅供 Docker 网络内访问 |
| `docker-compose.dev.yml` | 与基础文件合并，加载 `.env.dev` | `127.0.0.1:8000`、`127.0.0.1:8501` |
| `docker-compose.local-https.yml` | 与基础文件合并，加载 `.env.local-https`，增加 Nginx | 80/443 绑定所有接口；5678/5679 调试端口仅绑定回环 |
| `docker-compose.production.yml` / `docker-compose.secrets.yml` | 未随仓库提供 | 不能直接执行 |

基础文件没有 Nginx、公开入口或有效模型凭证。根目录 `.env` 可供 Compose 插值，但不会自动注入容器；CLI 的 `--env-file` 同样不替代服务级 `env_file` / `environment`。

## 本地 HTTP 开发

先阅读 [模型配置](../SETUP_API_KEY.md)。首次创建配置，Bash：

```bash
cp .env.secure.example .env.dev
```

PowerShell：

```powershell
Copy-Item .env.secure.example .env.dev
```

编辑 `.env.dev`，填写聊天和嵌入 Key，不要覆盖已有配置。开发配置将宿主机 `secrets/` 只读挂载到 `/run/secrets/`，文件 Key 应填写容器内路径。基础配置的 environment 将上传和向量库存储路径覆盖为 `/app/data/...`。

Bash / PowerShell 通用：

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml config --quiet
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up -d --build
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml ps
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml logs --tail 100 backend frontend
```

访问 http://localhost:8501 和 http://localhost:8000/health。`/docs` 仅在 `.env.dev` 设置 `ENABLE_API_DOCS=True` 并重新创建容器后可用。开发覆盖文件没有完整 build 定义，不能单独使用。

停止服务：

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml down
```

修改 env_file 后重新 `up -d` 创建容器，单纯 restart 不会加载新环境。修改宿主机端口应调整开发覆盖文件。

## 本地 HTTPS

先安装 mkcert、生成并信任证书，见 [设置指南](../docs/deployment/HTTPS_SETUP_GUIDE.md) 和 [故障排除](../docs/deployment/HTTPS_TROUBLESHOOTING.md)。配置文件是根目录 `.env.local-https`，不能只创建 `.env`；填写后端 Settings 支持的字段，前端地址另行配置到容器环境。

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local-https.yml config --quiet
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local-https.yml up -d --build
```

访问 https://localhost。此模式不发布宿主机 8000/8501；80/443 当前绑定所有接口，不能宣称只允许本机访问。默认未挂载 secret 目录，使用文件 Key 时必须增加挂载。证书信任和完整调用流程仍需实测。

## 生产配置与生成文件

[生产模板](../.env.production.template) 需按部署环境编辑，包含 secret 路径和前端变量；不能直接复制为本地后端 `.env`，后端 Settings 会拒绝未知字段。其中阈值、配额和文件大小是模板覆盖值，不等于代码默认值。

`scripts/setup-production-https.sh` 只准备部分 Nginx 配置，并按需复制生产环境模板；不会生成 `docker/docker-compose.production.yml`。它输出的生产 Compose/Certbot 命令依赖另行准备的服务定义，当前不是直接可复现的部署步骤。

`scripts/setup-secrets.sh` 写入 secret 文件，不生成 `docker-compose.secrets.yml`。使用前须明确挂载和 `*_FILE` 配置。宿主机凭证不会自动进入容器。

对外部署还需反向代理、TLS、凭证注入、CORS 和前端地址配置；仅启动无对外端口的标准 Compose 不能让 SLB/ALB 连通应用。当前优先验证本地 HTTP 开发路径。

## 排查与相关文档

用 `config --quiet` 检查配置，避免显示插值后的 Key；故障日志使用同一组 `-f` 参数查看。健康接口只检查凭证存在和目录，不证明 Embedding/聊天调用成功。

- [项目 README](../README.md)
- [文档导航](../docs/README.md)
- [安全指南](../SECURITY.md)
- [HTTPS 快速操作](../docs/deployment/QUICK_START_HTTPS.md)
- [历史资料](../docs/archive/README.md)
- [GitHub Issues](https://github.com/yumxiong/rag-kb/issues)
