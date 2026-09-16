@echo off
REM Setup local HTTPS development environment with mkcert
REM Windows version

setlocal enabledelayedexpansion

echo ========================================
echo 🔐 设置本地 HTTPS 开发环境
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ⚠️  警告：未以管理员权限运行
    echo.
    echo 安装 mkcert CA 到系统信任库需要管理员权限
    echo.
    echo 请选择：
    echo   1. 按任意键继续（可能会提示需要管理员权限）
    echo   2. Ctrl+C 退出，右键此文件 -^> "以管理员身份运行"
    echo.
    pause
    echo.
)

REM Check if mkcert is installed
where mkcert >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ mkcert 未安装
    echo.
    echo 请选择安装方式：
    echo 1. 使用 Chocolatey: choco install mkcert
    echo 2. 使用 Scoop: scoop install mkcert
    echo 3. 手动下载: https://github.com/FiloSottile/mkcert/releases
    echo.
    echo 安装后请重新运行此脚本
    echo.
    pause
    exit /b 1
)

echo ✅ mkcert 已安装
for /f "tokens=*" %%i in ('mkcert -version 2^>^&1') do set MKCERT_VERSION=%%i
echo    版本: %MKCERT_VERSION%
echo.

REM Create directories
echo 📁 创建必要的目录...
if not exist "docker\nginx\certs" mkdir "docker\nginx\certs"
if not exist "docker\nginx\conf.d" mkdir "docker\nginx\conf.d"
echo ✅ 目录已创建
echo.

REM Check if CA is already installed
echo 🔍 检查 mkcert CA 状态...
for /f "tokens=*" %%i in ('mkcert -CAROOT 2^>^&1') do set CAROOT=%%i
if exist "%CAROOT%\rootCA.pem" (
    echo ✅ mkcert CA 根目录: %CAROOT%
) else (
    echo ⚠️  CA 根目录不存在，将创建新的 CA
)
echo.

REM Install local CA
echo 📝 安装本地 CA 证书到系统信任库...
echo （这一步需要管理员权限，可能会弹出 UAC 提示）
echo.
mkcert -install

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ 安装 CA 失败！
    echo.
    echo 可能的原因：
    echo   1. 未以管理员权限运行
    echo   2. 被防病毒软件阻止
    echo   3. 用户拒绝了 UAC 提示
    echo.
    echo 解决方法：
    echo   1. 右键此文件 -^> "以管理员身份运行"
    echo   2. 在 UAC 提示时点击"是"
    echo   3. 暂时禁用防病毒软件
    echo.
    echo 或手动执行：
    echo   以管理员身份打开 PowerShell
    echo   cd "%CD%"
    echo   mkcert -install
    echo.
    pause
    exit /b 1
)

echo ✅ 本地 CA 已成功安装到系统信任库
echo.

REM Verify CA installation
echo 🔍 验证 CA 安装...
if exist "%CAROOT%\rootCA.pem" (
    echo ✅ CA 根证书文件存在
) else (
    echo ⚠️  警告：CA 根证书文件未找到
)
echo.

REM Generate certificates
echo 🔑 生成本地证书...
echo.
cd docker\nginx\certs

echo 正在为以下域名生成证书：
echo   - localhost
echo   - 127.0.0.1
echo   - ::1 (IPv6)
echo   - local.rag-kb.dev
echo.

mkcert localhost 127.0.0.1 ::1 local.rag-kb.dev

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ 证书生成失败
    echo.
    echo 请确保：
    echo   1. mkcert CA 已正确安装 (mkcert -install)
    echo   2. CAROOT 目录可访问
    echo.
    cd ..\..\..
    pause
    exit /b 1
)

echo.
echo ✅ 证书生成成功
echo.

REM Rename certificate files for easier reference
echo 📝 重命名证书文件...
set CERT_RENAMED=0
for %%F in (localhost+*.pem) do (
    set "filename=%%F"
    if "!filename:~-8!"=="-key.pem" (
        if exist "local-key.pem" del "local-key.pem"
        move "%%F" "local-key.pem" >nul 2>&1
        if exist "local-key.pem" (
            echo ✅ 密钥文件: local-key.pem
            set CERT_RENAMED=1
        )
    ) else (
        if exist "local-cert.pem" del "local-cert.pem"
        move "%%F" "local-cert.pem" >nul 2>&1
        if exist "local-cert.pem" (
            echo ✅ 证书文件: local-cert.pem
            set CERT_RENAMED=1
        )
    )
)

if %CERT_RENAMED%==0 (
    echo ⚠️  警告：证书文件重命名失败
    echo 请手动重命名文件
)

cd ..\..\..

REM Verify certificate files
echo.
echo 🔍 验证证书文件...
if exist "docker\nginx\certs\local-cert.pem" (
    echo ✅ 证书文件存在: docker\nginx\certs\local-cert.pem
) else (
    echo ❌ 证书文件不存在: docker\nginx\certs\local-cert.pem
)

if exist "docker\nginx\certs\local-key.pem" (
    echo ✅ 密钥文件存在: docker\nginx\certs\local-key.pem
) else (
    echo ❌ 密钥文件不存在: docker\nginx\certs\local-key.pem
)

echo.
echo ========================================
echo ✅ 本地 HTTPS 环境设置完成！
echo ========================================
echo.
echo 📁 证书位置:
echo    - 证书: docker\nginx\certs\local-cert.pem
echo    - 密钥: docker\nginx\certs\local-key.pem
echo    - CA 根目录: %CAROOT%
echo.
echo 🌐 你可以使用以下域名访问（均支持 HTTPS）：
echo    - https://localhost
echo    - https://127.0.0.1
echo    - https://local.rag-kb.dev
echo.
echo 💡 重要提示：
echo    1. 证书已生成，CA 已安装到系统信任库
echo    2. 首次访问时请完全重启浏览器（关闭所有窗口）
echo    3. 浏览器应显示 🔒 锁图标（灰色/黑色，不是绿色）
echo    4. 如仍提示不安全，请清除浏览器 SSL 缓存：
echo       chrome://net-internals/#hsts (删除 localhost)
echo.
echo 🚀 下一步：
echo    1. 启动服务: make dev-https
echo    2. 或使用: cd docker ^&^& docker-compose -f docker-compose.local-https.yml up -d
echo    3. 访问: https://localhost
echo    4. 测试: make test-https
echo.
echo 📚 如遇问题，查看文档：
echo    - docs/deployment/QUICK_START_HTTPS.md
echo    - docs/deployment/HTTPS_SETUP_GUIDE.md
echo.
pause


