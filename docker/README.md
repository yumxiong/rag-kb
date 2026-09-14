# Docker 部署指南

本文件是部署主入口。专题说明：[本地 HTTPS 设置](../docs/deployment/HTTPS_SETUP_GUIDE.md)、[快速操作](../docs/deployment/QUICK_START_HTTPS.md)、[HTTPS 故障排除](../docs/deployment/HTTPS_TROUBLESHOOTING.md)。历史实施记录见 [归档](../docs/archive/README.md)，其他主题见 [文档导航](../docs/README.md)。

本文保留现有部署说明；端口、生成配置和依赖仍待核对，启动路径尚待实测。

本目录包含 RAG 知识库系统的 Docker 部署配置。

## 📋 可用配置

### 1. 标准 Docker 部署
**文件**: `docker-compose.yml`

基础的 Docker 部署配置，适用于开发和测试。

```bash
cd docker
docker-compose up -d
```

访问:
- 前端: http://localhost:8501
- 后端: http://localhost:8000

### 2. 开发模式
**文件**: `docker-compose.dev.yml`

支持代码热重载的开发模式。

```bash
cd docker
docker-compose -f docker-compose.dev.yml up -d
```

### 3. 本地 HTTPS 开发 ⭐
**文件**: `docker-compose.local-https.yml`

使用 mkcert 证书的本地 HTTPS 开发环境，零信任警告！

**首次设置**:
```bash
# 1. 安装 mkcert
# Windows: choco install mkcert
# Mac: brew install mkcert
# Linux: sudo apt install mkcert

# 2. 生成本地证书
make setup-local-https
# 或: scripts/setup-local-https.bat (Windows)
# 或: bash scripts/setup-local-https.sh (Linux/Mac)

# 3. 启动 HTTPS 服务
make dev-https
```

访问:
- https://localhost
- https://127.0.0.1
- https://local.rag-kb.dev (需要配置 hosts)

**优势**:
- ✅ 真实的 HTTPS 环境
- ✅ 零浏览器警告
- ✅ 与生产环境配置一致
- ✅ 测试 HTTPS 特性（CORS、安全头等）

### 4. 生产环境部署
**文件**: `docker-compose.production.yml`

生产环境配置，支持多种 SSL 证书策略。

#### 方案 A: 云厂商 SLB/ALB（推荐）

**最简单的生产方案**：SSL 由云厂商处理，应用只需 HTTP。

```bash
# 1. 在云厂商控制台申请 SSL 证书
# 2. 配置负载均衡器 HTTPS 监听
# 3. 如需新建生产配置，可由 .env.production.template 复制为 .env.production
ALLOWED_ORIGINS=https://yourdomain.com
DEBUG=False

# 4. 使用标准配置启动
cd docker
docker-compose up -d
```

#### 方案 B: Let's Encrypt

**免费 SSL 证书，自动续期**。

```bash
# 运行配置向导
make setup-production-https
# 选择方案 1，按提示操作

# 启动服务
cd docker
docker-compose -f docker-compose.production.yml up -d
```

#### 方案 C: 云厂商证书 + Nginx

**灵活的中间方案**。

```bash
# 1. 下载证书文件
# 2. 放置到 docker/nginx/certs/
# 3. 运行配置向导
make setup-production-https
# 选择方案 3

# 4. 启动服务
cd docker
docker-compose -f docker-compose.production.yml up -d
```

## 🗂️ 目录结构

```
docker/
├── docker-compose.yml              # 标准配置
├── docker-compose.dev.yml          # 开发模式
├── docker-compose.local-https.yml  # 本地HTTPS（推荐开发）
├── docker-compose.production.yml   # 生产环境
├── docker-compose.secrets.yml      # Docker Secrets配置
├── Dockerfile.backend              # 后端镜像
├── Dockerfile.frontend             # 前端镜像
├── nginx/                          # Nginx配置
│   ├── conf.d/
│   │   ├── local-https.conf       # 本地HTTPS配置
│   │   └── production.conf.template # 生产配置模板
│   └── certs/                      # SSL证书目录
│       ├── local-cert.pem         # mkcert生成（本地）
│       ├── local-key.pem          # mkcert生成（本地）
│       ├── production-cert.pem    # 生产证书（需要手动放置）
│       └── production-key.pem     # 生产密钥（需要手动放置）
└── README.md                       # 本文件
```

## 🔧 常用命令

### 基础操作
```bash
# 构建镜像
make docker-build

# 启动服务
make docker-run

# 停止服务
make docker-stop

# 查看日志
make docker-logs

# 查看状态
make docker-ps
```

### HTTPS 操作
```bash
# 设置本地HTTPS
make setup-local-https

# 启动HTTPS开发环境
make dev-https

# 停止HTTPS服务
make stop-https

# 测试HTTPS配置
make test-https

# 配置生产环境HTTPS
make setup-production-https
```

## 🔐 安全配置

### 环境变量
创建 `.env` 文件（开发环境）、`.env.production.template`（生产模板）或 `.env.production`（生产实际配置）：

```bash
# API配置（使用安全方式）
OPENAI_API_KEY=sk-xxx  # 或使用其他安全方式

# CORS配置
ALLOWED_ORIGINS=https://yourdomain.com
ALLOWED_METHODS=GET,POST,DELETE
ALLOWED_HEADERS=Content-Type,Authorization

# 安全配置
DEBUG=False  # 生产环境必须为False
```

### Docker Secrets（推荐生产环境）

```bash
# 设置secrets
./scripts/setup-secrets.sh

# 使用secrets启动
cd docker
docker-compose -f docker-compose.secrets.yml up -d
```

## 📊 监控和日志

### 查看日志
```bash
# 所有服务
docker-compose logs -f

# 特定服务
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f nginx
```

### 健康检查
```bash
# 后端健康检查
curl http://localhost:8000/health
# 或 HTTPS: curl https://localhost/health

# 前端健康检查
curl http://localhost:8501/_stcore/health
```

### 服务状态
```bash
docker-compose ps
```

## 🐛 故障排除

### 问题 1: 端口被占用
```bash
# 检查端口占用
netstat -ano | findstr :8000  # Windows
lsof -i :8000                 # Linux/Mac

# 修改端口
# 编辑 docker-compose.yml 中的 ports 配置
```

### 问题 2: 证书错误（HTTPS）
```bash
# 检查证书是否存在
ls -la docker/nginx/certs/

# 重新生成证书
make setup-local-https

# 检查Nginx配置
docker exec rag-kb-nginx nginx -t
```

### 问题 3: 容器无法启动
```bash
# 查看详细错误
docker-compose logs backend
docker-compose logs frontend

# 检查配置文件
docker-compose config

# 重新构建
docker-compose build --no-cache
docker-compose up -d
```

### 问题 4: CORS 错误
```bash
# 更新CORS配置
python scripts/setup-cors.py

# 或手动编辑 .env
ALLOWED_ORIGINS=https://your-domain.com

# 重启服务
docker-compose restart backend
```

## 📚 最佳实践

### 开发环境
1. 使用 `docker-compose.local-https.yml` 进行 HTTPS 开发
2. 使用 mkcert 生成可信任的本地证书
3. 启用 DEBUG=True 和详细日志
4. 使用 volume 挂载以支持热重载

### 生产环境
1. **推荐**: 使用云厂商 SLB/ALB 做 SSL 终结
2. 设置 DEBUG=False
3. 配置严格的 CORS 策略
4. 使用 Docker Secrets 管理敏感信息
5. 启用日志轮转
6. 配置健康检查和自动重启
7. 定期备份 data 目录
8. 设置资源限制（CPU、内存）

### 安全建议
1. ✅ 使用 HTTPS（生产环境必须）
2. ✅ 定期更新 Docker 镜像
3. ✅ 限制 CORS 到特定域名
4. ✅ 使用强密码和密钥轮换
5. ✅ 启用防火墙，只开放必要端口
6. ✅ 监控异常访问和 API 使用
7. ✅ 定期审计安全配置

## 🔗 相关文档

- [主 README](../README.md)
- [安全配置指南](../SECURITY.md)
- [API 文档](http://localhost:8000/docs)
- [Nginx 官方文档](https://nginx.org/en/docs/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [Let's Encrypt](https://letsencrypt.org/)
- [mkcert](https://github.com/FiloSottile/mkcert)

## 🆘 获取帮助

如果遇到问题：
1. 查看本文档的故障排除部分
2. 检查日志: `make docker-logs`
3. 查看 [GitHub Issues](https://github.com/yumxiong/rag-kb/issues)
4. 运行健康检查: `make test-https`



