#!/bin/bash
# Setup local HTTPS development environment with mkcert
# Linux/Mac version

set -e

echo "========================================"
echo "🔐 设置本地 HTTPS 开发环境"
echo "========================================"
echo ""

# Check if mkcert is installed
if ! command -v mkcert &> /dev/null; then
    echo "❌ mkcert 未安装"
    echo ""
    echo "请选择安装方式："
    echo "Mac:   brew install mkcert"
    echo "Linux: sudo apt install mkcert"
    echo "或从: https://github.com/FiloSottile/mkcert/releases"
    echo ""
    echo "安装后请重新运行此脚本"
    exit 1
fi

echo "✅ mkcert 已安装"
MKCERT_VERSION=$(mkcert -version 2>&1)
echo "   版本: $MKCERT_VERSION"
echo ""

# Create directories
echo "📁 创建必要的目录..."
mkdir -p docker/nginx/certs
mkdir -p docker/nginx/conf.d
echo "✅ 目录已创建"
echo ""

# Check if CA is already installed
echo "🔍 检查 mkcert CA 状态..."
CAROOT=$(mkcert -CAROOT)
if [ -f "$CAROOT/rootCA.pem" ]; then
    echo "✅ mkcert CA 根目录: $CAROOT"
else
    echo "⚠️  CA 根目录不存在，将创建新的 CA"
fi
echo ""

# Install local CA
echo "📝 安装本地 CA 证书到系统信任库..."
echo "（这一步可能需要输入系统密码）"
echo ""

if mkcert -install; then
    echo ""
    echo "✅ 本地 CA 已成功安装到系统信任库"
else
    echo ""
    echo "❌ 安装 CA 失败！"
    echo ""
    echo "可能的原因："
    echo "  1. 没有系统管理权限"
    echo "  2. 被安全软件阻止"
    echo ""
    echo "解决方法："
    echo "  手动执行: sudo mkcert -install"
    echo ""
    exit 1
fi
echo ""

# Verify CA installation
echo "🔍 验证 CA 安装..."
if [ -f "$CAROOT/rootCA.pem" ]; then
    echo "✅ CA 根证书文件存在"
else
    echo "⚠️  警告：CA 根证书文件未找到"
fi
echo ""

# Generate certificates
echo "🔑 生成本地证书..."
echo ""
cd docker/nginx/certs

echo "正在为以下域名生成证书："
echo "  - localhost"
echo "  - 127.0.0.1"
echo "  - ::1 (IPv6)"
echo "  - local.rag-kb.dev"
echo ""

if mkcert localhost 127.0.0.1 ::1 local.rag-kb.dev; then
    echo ""
    echo "✅ 证书生成成功"
else
    echo ""
    echo "❌ 证书生成失败"
    echo ""
    echo "请确保："
    echo "  1. mkcert CA 已正确安装 (mkcert -install)"
    echo "  2. CAROOT 目录可访问"
    echo ""
    cd ../../..
    exit 1
fi
echo ""

# Rename certificate files for easier reference
echo "📝 重命名证书文件..."

# Remove old files if exist
rm -f local-cert.pem local-key.pem

# Find and rename the generated files
CERT_FILE=$(ls localhost+*[0-9].pem 2>/dev/null | grep -v key | head -1)
KEY_FILE=$(ls localhost+*-key.pem 2>/dev/null | head -1)

if [ -n "$CERT_FILE" ] && [ -n "$KEY_FILE" ]; then
    mv "$CERT_FILE" local-cert.pem
    mv "$KEY_FILE" local-key.pem
    echo "✅ 证书文件: local-cert.pem"
    echo "✅ 密钥文件: local-key.pem"
else
    echo "⚠️  警告：找不到生成的证书文件"
    echo "请检查当前目录中的 localhost+*.pem 文件"
    ls -la
fi

cd ../../..

# Verify certificate files
echo ""
echo "🔍 验证证书文件..."
if [ -f "docker/nginx/certs/local-cert.pem" ]; then
    echo "✅ 证书文件存在: docker/nginx/certs/local-cert.pem"
else
    echo "❌ 证书文件不存在: docker/nginx/certs/local-cert.pem"
fi

if [ -f "docker/nginx/certs/local-key.pem" ]; then
    echo "✅ 密钥文件存在: docker/nginx/certs/local-key.pem"
else
    echo "❌ 密钥文件不存在: docker/nginx/certs/local-key.pem"
fi

echo ""
echo "========================================"
echo "✅ 本地 HTTPS 环境设置完成！"
echo "========================================"
echo ""
echo "📁 证书位置:"
echo "   - 证书: docker/nginx/certs/local-cert.pem"
echo "   - 密钥: docker/nginx/certs/local-key.pem"
echo "   - CA 根目录: $CAROOT"
echo ""
echo "🌐 你可以使用以下域名访问（均支持 HTTPS）："
echo "   - https://localhost"
echo "   - https://127.0.0.1"
echo "   - https://local.rag-kb.dev"
echo ""
echo "💡 重要提示："
echo "   1. 证书已生成，CA 已安装到系统信任库"
echo "   2. 首次访问时请完全重启浏览器（关闭所有窗口）"
echo "   3. 浏览器应显示 🔒 锁图标（灰色/黑色，不是绿色）"
echo "   4. 如仍提示不安全，请清除浏览器缓存"
echo ""
echo "🚀 下一步："
echo "   1. 启动服务: make dev-https"
echo "   2. 或使用: cd docker && docker-compose -f docker-compose.local-https.yml up -d"
echo "   3. 访问: https://localhost"
echo "   4. 测试: make test-https"
echo ""
echo "📚 如遇问题，查看文档："
echo "   - docs/deployment/QUICK_START_HTTPS.md"
echo "   - docs/deployment/HTTPS_SETUP_GUIDE.md"
echo ""


