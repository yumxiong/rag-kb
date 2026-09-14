# 🔧 HTTPS 配置故障排除指南

> 部署主入口：[Docker 部署指南](../../docker/README.md)。以下命令从仓库根目录执行；HTTPS 实测留待启动验收阶段。

本文档专门针对本地 HTTPS 开发环境的常见问题和解决方案。

## 🚨 最常见问题

### ❌ NET::ERR_CERT_AUTHORITY_INVALID

**完整错误信息**:
```
您的连接不是私密连接
攻击者可能会试图从 localhost 窃取您的信息
NET::ERR_CERT_AUTHORITY_INVALID
```

#### 🔍 根本原因

这是**最常见**的问题，原因是：
1. ✅ 证书文件已生成（`docker/nginx/certs/local-cert.pem`）
2. ❌ **mkcert 的 CA 没有安装到系统信任库**
3. ❌ 浏览器不信任签发证书的 CA

#### ✅ 完整解决方案

**步骤 1: 停止服务（如果正在运行）**
```bash
cd docker
docker-compose -f docker-compose.local-https.yml down
cd ..
```

**步骤 2: 以管理员身份安装 CA**

**Windows:**
```powershell
# 方法 1: 右键 PowerShell -> "以管理员身份运行"
# 然后执行：
cd D:\claudeCode\rag_kb  # 替换为你的项目路径
mkcert -install

# 方法 2: 在当前 PowerShell 中
# 以管理员身份重新打开，然后运行上面的命令
```

**Mac/Linux:**
```bash
# 可能需要输入系统密码
mkcert -install
```

**预期输出**:
```
The local CA is now installed in the system trust store! ⚡️
```

**步骤 3: 验证 CA 已安装**

```bash
# 查看 CA 根目录
mkcert -CAROOT
# 应该显示类似: C:\Users\YourName\AppData\Local\mkcert
```

**Windows 手动验证：**
1. 按 `Win + R`
2. 输入 `certmgr.msc`，回车
3. 展开 **"受信任的根证书颁发机构"** → **"证书"**
4. 查找名为 **"mkcert"** 开头的证书
5. 如果找到，说明 CA 已安装 ✅

**步骤 4: 清除浏览器 SSL 缓存**

**Chrome/Edge:**
```
1. 在地址栏输入: chrome://net-internals/#hsts
2. 找到 "Delete domain security policies" 部分
3. 输入: localhost
4. 点击 "Delete"
5. 关闭所有浏览器窗口（包括后台）
```

**步骤 5: 重启服务**
```bash
make dev-https
```

**步骤 6: 重新访问**
- 打开新的浏览器窗口
- 访问 https://localhost
- 应该看到 🔒 锁图标，无任何警告

---

## 🔒 "为什么没有绿色锁？"

### 这不是问题！

**正常显示**:
- ✅ 灰色或黑色的 🔒 锁图标 = **连接安全**
- ❌ 红色的 ⚠️ 或叉号 = 连接不安全

**历史背景**:
- Chrome/Edge 从 2019 年起取消了绿色锁
- 原因：HTTPS 应该是默认状态，不需要特别标注
- 灰色/黑色锁已经表示连接安全

**如何确认连接真的安全**:
1. 点击地址栏的 🔒 锁图标
2. 应该看到：
   - "连接是安全的"
   - 或 "Connection is secure"
3. 点击"证书"查看详情：
   - 颁发者：mkcert [你的用户名]
   - 主题：localhost
   - 有效期：通常 10 年

---

## 🔐 证书问题排查清单

### 1. 检查证书文件是否存在

```bash
# Windows
dir docker\nginx\certs\

# Linux/Mac
ls -la docker/nginx/certs/

# 应该看到：
# local-cert.pem
# local-key.pem
```

**如果文件不存在**:
```bash
# 重新运行设置脚本
.\scripts\setup-local-https.bat  # Windows
bash scripts/setup-local-https.sh  # Linux/Mac
```

### 2. 检查 CA 是否已安装

```bash
# 查看 CA 根目录
mkcert -CAROOT

# 检查 CA 文件是否存在
# Windows:
dir "%LocalAppData%\mkcert\rootCA.pem"

# Linux/Mac:
ls -la "$(mkcert -CAROOT)/rootCA.pem"
```

**如果 CA 不存在或显示错误**:
```bash
# 以管理员身份重新安装 CA
mkcert -install
```

### 3. 检查 Nginx 配置

```bash
# 启动服务后，检查 Nginx 日志
cd docker
docker-compose -f docker-compose.local-https.yml logs nginx

# 查找证书相关错误
docker-compose -f docker-compose.local-https.yml logs nginx | grep -i "certificate\|ssl\|error"
```

**常见错误**:
- `cannot load certificate`: 证书文件路径错误或不存在
- `SSL_CTX_use_PrivateKey_file() failed`: 私钥文件问题

### 4. 验证 Docker 容器可以访问证书

```bash
# 进入 Nginx 容器
docker exec -it rag-kb-nginx sh

# 查看证书文件
ls -la /etc/nginx/certs/

# 应该看到：
# local-cert.pem
# local-key.pem

# 退出容器
exit
```

---

## 🌐 浏览器特定问题

### Chrome/Edge - HSTS 缓存问题

**症状**: 明明 CA 已安装，但仍然显示证书错误

**原因**: 浏览器缓存了之前的 HSTS 设置

**解决**:
```
1. 访问: chrome://net-internals/#hsts
2. 在 "Delete domain security policies" 输入: localhost
3. 点击 Delete
4. 关闭所有浏览器窗口
5. 重新打开浏览器
```

### Firefox - 单独的证书存储

**注意**: Firefox 使用自己的证书存储，不使用系统证书

**mkcert -install 会自动处理 Firefox**，但如果有问题：

```bash
# 重新安装，确保 Firefox 支持
mkcert -install

# 查看输出，应该包含：
# The local CA is now installed in the Firefox trust store! 🦊
```

### Safari (Mac)

**如果 Safari 仍然不信任**:

1. 打开"钥匙串访问"应用
2. 在左侧选择"系统"
3. 查找"mkcert"证书
4. 双击证书
5. 展开"信任"部分
6. 将"使用此证书时"改为"始终信任"

---

## 🔧 高级故障排除

### 完全重置 mkcert

**如果所有方法都不行，尝试完全重置**:

```bash
# 1. 卸载现有 CA
mkcert -uninstall

# 2. 删除旧的 CA 文件
# Windows:
rd /s /q "%LocalAppData%\mkcert"

# Linux/Mac:
rm -rf "$(mkcert -CAROOT)"

# 3. 重新安装 CA（以管理员身份）
mkcert -install

# 4. 删除旧证书
rm docker/nginx/certs/local-*.pem

# 5. 重新生成证书
make setup-local-https

# 6. 重启服务
make dev-https
```

### 检查防病毒软件干扰

某些防病毒软件可能会：
- 阻止 mkcert 安装 CA
- 拦截本地证书
- 修改 HTTPS 连接

**临时禁用防病毒软件**，然后重新运行：
```bash
mkcert -install
```

### 检查系统代理设置

如果使用了代理软件（VPN、代理工具等）:

1. 临时禁用代理
2. 重新访问 https://localhost
3. 如果成功，需要配置代理忽略 localhost

---

## 📝 完整诊断脚本

运行以下命令收集诊断信息：

**Windows (PowerShell):**
```powershell
Write-Host "=== HTTPS 诊断信息 ===" -ForegroundColor Cyan

Write-Host "`n1. mkcert 版本:" -ForegroundColor Yellow
mkcert -version

Write-Host "`n2. CA 根目录:" -ForegroundColor Yellow
mkcert -CAROOT

Write-Host "`n3. CA 文件存在:" -ForegroundColor Yellow
Test-Path "$env:LocalAppData\mkcert\rootCA.pem"

Write-Host "`n4. 证书文件:" -ForegroundColor Yellow
Get-ChildItem docker\nginx\certs\ -ErrorAction SilentlyContinue

Write-Host "`n5. Docker 容器状态:" -ForegroundColor Yellow
cd docker
docker-compose -f docker-compose.local-https.yml ps

Write-Host "`n6. Nginx 最近日志:" -ForegroundColor Yellow
docker-compose -f docker-compose.local-https.yml logs --tail=20 nginx
```

**Linux/Mac (Bash):**
```bash
echo "=== HTTPS 诊断信息 ==="

echo -e "\n1. mkcert 版本:"
mkcert -version

echo -e "\n2. CA 根目录:"
mkcert -CAROOT

echo -e "\n3. CA 文件存在:"
ls -la "$(mkcert -CAROOT)/rootCA.pem" 2>&1

echo -e "\n4. 证书文件:"
ls -la docker/nginx/certs/ 2>&1

echo -e "\n5. Docker 容器状态:"
cd docker
docker-compose -f docker-compose.local-https.yml ps

echo -e "\n6. Nginx 最近日志:"
docker-compose -f docker-compose.local-https.yml logs --tail=20 nginx
```

---

## 🆘 仍然无法解决？

### 收集信息后提问

如果尝试了所有方法仍然不行，请收集以下信息：

1. **操作系统版本**:
   - Windows: `winver`
   - Mac: `sw_vers`
   - Linux: `lsb_release -a`

2. **mkcert 版本**: `mkcert -version`

3. **CA 状态**: `mkcert -CAROOT`

4. **证书文件**: `ls docker/nginx/certs/`

5. **浏览器版本**: 在浏览器地址栏输入 `chrome://version` 或 `about:`

6. **完整错误截图**: 包括浏览器地址栏和错误信息

7. **Nginx 日志**:
   ```bash
   cd docker
   docker-compose -f docker-compose.local-https.yml logs nginx
   ```

### 临时解决方案

如果急需测试，可以临时**跳过证书验证**（不推荐）:

**Chrome/Edge 启动参数**:
```bash
# Windows
chrome.exe --ignore-certificate-errors --allow-insecure-localhost

# Mac
open -a "Google Chrome" --args --ignore-certificate-errors --allow-insecure-localhost
```

**注意**: 这只是临时测试用，正式开发还是要正确配置证书！

---

## 📚 相关文档

- [快速开始指南](QUICK_START_HTTPS.md)
- [完整设置指南](HTTPS_SETUP_GUIDE.md)
- [实施总结](../archive/HTTPS_IMPLEMENTATION_SUMMARY.md)
- [Docker 部署指南](../../docker/README.md)

---

**最后的提醒**: 90% 的证书问题都是因为**忘记运行 `mkcert -install` 或没有以管理员权限运行**。记住这一点就能避免大部分问题！


