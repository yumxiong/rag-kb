# 🔐 本地 HTTPS 开发环境设置指南

> 部署主入口：[Docker 部署指南](../../docker/README.md)。以下命令从仓库根目录执行；HTTPS 实测留待启动验收阶段。

本指南将帮助你在本地设置完整的 HTTPS 开发环境。

## 📋 准备工作

### 1. 安装 mkcert（必需）

mkcert 是一个零配置的本地 CA 工具，能够生成浏览器信任的本地证书。

#### Windows 安装方式（任选一种）：

**方式 A: 使用 Chocolatey（推荐）**
```powershell
# 以管理员身份运行 PowerShell
choco install mkcert
```

**方式 B: 使用 Scoop**
```powershell
scoop bucket add extras
scoop install mkcert
```

**方式 C: 手动下载**
1. 访问: https://github.com/FiloSottile/mkcert/releases
2. 下载最新的 `mkcert-v*-windows-amd64.exe`
3. 重命名为 `mkcert.exe`
4. 放到 PATH 目录下（如 `C:\Windows\System32\`）

#### Mac 安装：
```bash
brew install mkcert
```

#### Linux 安装：
```bash
# Debian/Ubuntu
sudo apt install mkcert

# 或从源码安装
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
chmod +x mkcert-v*-linux-amd64
sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
```

### 2. 验证安装
```bash
mkcert -version
```

## 🚀 快速开始（3 步完成）

### 步骤 1: 生成本地证书

**Windows:**
```powershell
# 双击运行或在 PowerShell 中执行
.\scripts\setup-local-https.bat
```

**Linux/Mac:**
```bash
# 在项目根目录执行
bash scripts/setup-local-https.sh
```

**或使用 Make 命令:**
```bash
make setup-local-https
```

这个脚本会：
- ✅ 安装本地 CA 到系统信任库
- ✅ 生成 localhost、127.0.0.1 等域名的证书
- ✅ 将证书保存到 `docker/nginx/certs/` 目录

### 步骤 2: 配置环境变量（可选）

复制环境配置示例：
```bash
cp .env.local-https.example .env
```

编辑 `.env` 文件，配置你的 API Key：
```bash
# 推荐：使用环境变量
# 在命令行中设置: set OPENAI_API_KEY=sk-xxx (Windows)
# 或: export OPENAI_API_KEY=sk-xxx (Linux/Mac)

# 或使用密钥环（最安全）
python scripts/setup-keyring.py
```

### 步骤 3: 启动 HTTPS 开发环境

```bash
# 使用 Make 命令（推荐）
make dev-https

# 或直接使用 Docker Compose
cd docker
docker-compose -f docker-compose.local-https.yml up -d --build
```

## 🌐 访问应用

启动后，你可以通过以下地址访问（**无浏览器警告！**）：

- **主要地址**: https://localhost
- **备用地址**: https://127.0.0.1
- **自定义域名**: https://local.rag-kb.dev（需配置 hosts）

### 配置自定义域名（可选）

**Windows:**
1. 以管理员身份打开记事本
2. 打开文件: `C:\Windows\System32\drivers\etc\hosts`
3. 添加行: `127.0.0.1  local.rag-kb.dev`
4. 保存

**Linux/Mac:**
```bash
sudo sh -c 'echo "127.0.0.1  local.rag-kb.dev" >> /etc/hosts'
```

## 🧪 测试 HTTPS 配置

### 方法 1: 使用 Make 命令
```bash
make test-https
```

### 方法 2: 手动测试
```bash
# 测试 HTTPS 访问
curl -I https://localhost

# 测试健康检查
curl https://localhost/health

# 测试 HTTP 重定向
curl -I http://localhost
# 应该返回 301 重定向到 HTTPS
```

### 方法 3: 浏览器测试
1. 打开浏览器访问: https://localhost
2. 检查地址栏的锁图标 🔒
3. 点击锁图标，查看证书信息
4. 应该显示由 "mkcert" 签发，且标记为可信任

## 📊 查看日志和状态

```bash
# 查看所有服务日志
make docker-logs-https

# 查看服务状态
cd docker
docker-compose -f docker-compose.local-https.yml ps

# 查看 Nginx 日志
docker-compose -f docker-compose.local-https.yml logs nginx
```

## 🛑 停止服务

```bash
# 使用 Make 命令
make stop-https

# 或直接使用 Docker Compose
cd docker
docker-compose -f docker-compose.local-https.yml down
```

## 🔧 故障排除

### 问题 1: mkcert 未安装
**错误**: `mkcert: command not found`

**解决**:
1. 按照上面的安装说明安装 mkcert
2. 验证安装: `mkcert -version`
3. 重新运行设置脚本

### 问题 2: 证书不被信任（最常见❗）
**症状**: 浏览器显示 `NET::ERR_CERT_AUTHORITY_INVALID` 或"您的连接不是私密连接"

**根本原因**: mkcert 的本地 CA 还没有安装到系统信任库

**解决方法（Windows）**:
```bash
# 以管理员身份打开 PowerShell
# 1. 安装本地 CA 到系统信任库（关键步骤！）
mkcert -install

# 2. 验证 CA 已安装
mkcert -CAROOT
# 应该显示 CA 目录路径，例如：C:\Users\...\AppData\Local\mkcert

# 3. 重启浏览器（关闭所有窗口）

# 4. 重新访问 https://localhost
```

**解决方法（Linux/Mac）**:
```bash
# 1. 安装本地 CA（可能需要输入密码）
mkcert -install

# 2. 重启浏览器

# 3. 重新访问 https://localhost
```

**为什么会发生这个问题？**
- 证书文件生成了 ✅
- 但签发证书的 CA 没有被系统信任 ❌
- 必须运行 `mkcert -install` 将 CA 添加到系统信任库
- **Windows 需要管理员权限**执行这一步

**验证 CA 已安装**:
```bash
# 查看 CA 根目录
mkcert -CAROOT

# Windows: 打开证书管理器
# 按 Win+R，输入 certmgr.msc
# 展开 "受信任的根证书颁发机构" -> "证书"
# 查找名为 "mkcert" 开头的证书
```

### 问题 3: 端口被占用
**错误**: `Bind for 0.0.0.0:443 failed: port is already allocated`

**解决**:
```bash
# Windows: 检查端口占用
netstat -ano | findstr :443
# 停止占用进程或修改 docker-compose 中的端口映射

# Linux/Mac: 检查端口占用
lsof -i :443
sudo kill -9 <PID>
```

### 问题 4: Docker 无法访问证书
**错误**: `nginx: [emerg] cannot load certificate`

**解决**:
```bash
# 检查证书文件是否存在
dir docker\nginx\certs\  # Windows
ls -la docker/nginx/certs/  # Linux/Mac

# 应该看到:
# - local-cert.pem
# - local-key.pem

# 如果缺失，重新生成
make setup-local-https
```

### 问题 5: CORS 错误
**错误**: 浏览器控制台显示 CORS 错误

**解决**:
1. 检查 `.env` 文件中的 `ALLOWED_ORIGINS`
2. 确保包含你访问的域名（https://localhost）
3. 重启服务: `make stop-https && make dev-https`

### 问题 6: 浏览器不显示绿色锁
**症状**: 地址栏显示灰色/黑色锁 🔒，不是绿色

**这不是问题！** 
- 现代浏览器（Chrome、Edge 等）从 2019 年开始不再显示绿色锁
- 灰色/黑色锁 🔒 = 连接安全（这是正确的）
- 红色 ❌ 或 ⚠️ = 连接不安全

**验证连接确实安全**:
1. 点击地址栏的锁图标
2. 应该显示"连接是安全的"或"Connection is secure"
3. 证书颁发者应该是"mkcert"

## 🎯 与生产环境的对比

| 配置项 | 本地开发 | 生产环境 |
|--------|----------|----------|
| SSL 证书 | mkcert 自签名 | Let's Encrypt 或云厂商证书 |
| 域名 | localhost | 实际域名 |
| DEBUG | True | False |
| CORS | 包含 localhost | 仅生产域名 |
| HSTS | 关闭 | 启用 |
| 证书续期 | 无需续期 | 自动或手动 |

**核心配置结构完全一致**，迁移到生产环境只需：
1. 更换 SSL 证书来源
2. 修改域名配置
3. 更新安全参数

## 📚 相关文档

- [Docker 部署指南](../../docker/README.md)
- [生产环境 HTTPS 配置](../../docker/nginx/conf.d/production.conf.template)
- [安全配置指南](../../SECURITY.md)
- [mkcert 官方文档](https://github.com/FiloSottile/mkcert)

## ✅ 配置完成检查清单

设置完成后，确认以下项目：

- [ ] mkcert 已安装并可以运行
- [ ] 本地 CA 已安装到系统（`mkcert -install`）
- [ ] 证书文件已生成（`docker/nginx/certs/local-cert.pem`）
- [ ] Docker 服务已启动（`make dev-https`）
- [ ] 可以通过 https://localhost 访问，无证书警告
- [ ] 健康检查端点正常（`https://localhost/health`）
- [ ] HTTP 自动重定向到 HTTPS
- [ ] API 端点可以访问（`https://localhost/api/...`）
- [ ] WebSocket 连接正常（Streamlit 实时更新）

## 🎉 成功！

恭喜！你现在拥有了一个完整的本地 HTTPS 开发环境：

- ✅ 真实的 HTTPS 加密连接
- ✅ 零浏览器警告
- ✅ 与生产环境配置一致
- ✅ 可以测试所有 HTTPS 特性
- ✅ 便于未来迁移到生产环境

现在你可以开始开发了！🚀

---

**需要帮助？** 查看 [故障排除](#-故障排除) 部分或提交 [GitHub Issue](https://github.com/your-repo/issues)。


