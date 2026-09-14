# 🚀 本地 HTTPS 快速开始

> 部署主入口：[Docker 部署指南](../../docker/README.md)。以下命令从仓库根目录执行；HTTPS 实测留待启动验收阶段。

## ⚡ 3 分钟快速设置

### 第 1 步: 安装 mkcert（仅首次需要）

**Windows - 使用 Chocolatey（推荐）:**
```powershell
# 以管理员身份运行 PowerShell
choco install mkcert
```

**Windows - 手动下载:**
1. 访问: https://github.com/FiloSottile/mkcert/releases
2. 下载 `mkcert-v*-windows-amd64.exe`
3. 重命名为 `mkcert.exe`
4. 放到 `C:\Windows\System32\` 目录

**验证安装:**
```bash
mkcert -version
```

### 第 2 步: 生成证书并安装 CA
```powershell
# 在项目根目录运行（会自动安装 CA 到系统）
.\scripts\setup-local-https.bat

# 重要：脚本会执行 mkcert -install
# Windows 需要管理员权限，可能会弹出 UAC 提示
# 请点击"是"允许安装
```

**如果遇到权限问题：**
- 右键点击 `setup-local-https.bat`
- 选择"以管理员身份运行"

### 第 3 步: 启动服务
```bash
make dev-https
```

### 第 4 步: 访问
打开浏览器访问: **https://localhost** 🎉

## 📝 详细说明

如果遇到问题，请查看 [HTTPS_SETUP_GUIDE.md](HTTPS_SETUP_GUIDE.md)

## 🔧 常用命令

```bash
# 设置证书（首次）
make setup-local-https

# 启动 HTTPS 服务
make dev-https

# 测试 HTTPS
make test-https

# 查看日志
make docker-logs-https

# 停止服务
make stop-https
```

## ✅ 成功标志

- 浏览器地址栏显示 🔒 **灰色/黑色**锁图标（不是绿色，这是正常的）
- **无**证书警告（没有 "不是私密连接" 错误）
- 可以访问 https://localhost
- 健康检查正常: https://localhost/health
- 点击锁图标显示"连接是安全的"

**注意**: 现代浏览器不再显示绿色锁，灰色/黑色锁就是安全标志！

## 📚 更多文档

- [完整 HTTPS 设置指南](HTTPS_SETUP_GUIDE.md)
- [Docker 部署指南](../../docker/README.md)
- [生产环境配置](../../docker/nginx/conf.d/production.conf.template)


