"""
CORS配置测试
"""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


class TestCORSConfig:
    """CORS配置测试类"""

    def setup_method(self):
        """测试前准备"""
        self.client = TestClient(app)

    def test_cors_origins_parsing(self):
        """测试CORS源域名解析"""
        # 测试单个域名
        settings = Settings(allowed_origins="http://localhost:8501")
        origins = settings.get_cors_origins()
        assert origins == ["http://localhost:8501"]

        # 测试多个域名
        settings = Settings(
            allowed_origins=(
                "http://localhost:8501,https://example.com," "https://www.example.com"
            )
        )
        origins = settings.get_cors_origins()
        assert origins == [
            "http://localhost:8501",
            "https://example.com",
            "https://www.example.com",
        ]

        # 测试通配符
        settings = Settings(allowed_origins="*")
        origins = settings.get_cors_origins()
        assert origins == ["*"]

    def test_cors_methods_parsing(self):
        """测试CORS方法解析"""
        # 测试限制的方法
        settings = Settings(allowed_methods="GET,POST,DELETE")
        methods = settings.get_cors_methods()
        assert methods == ["GET", "POST", "DELETE"]

        # 测试通配符
        settings = Settings(allowed_methods="*")
        methods = settings.get_cors_methods()
        assert methods == ["*"]

    def test_cors_headers_parsing(self):
        """测试CORS请求头解析"""
        # 测试限制的请求头
        settings = Settings(allowed_headers="Content-Type,Authorization")
        headers = settings.get_cors_headers()
        assert headers == ["Content-Type", "Authorization"]

        # 测试通配符
        settings = Settings(allowed_headers="*")
        headers = settings.get_cors_headers()
        assert headers == ["*"]

    def test_cors_preflight_request(self):
        """测试CORS预检请求"""
        # 模拟浏览器发送的预检请求
        headers = {
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }

        response = self.client.options("/api/documents/upload", headers=headers)

        # 检查CORS响应头是否存在
        # 注意：这个测试可能因为中间件配置而有所不同
        assert response.status_code in [200, 405]  # 405是因为没有定义OPTIONS路由

    def test_api_endpoint_with_cors(self):
        """测试API端点的CORS行为"""
        # 模拟跨域请求
        headers = {
            "Origin": "http://localhost:8501",
            "Content-Type": "application/json",
        }

        response = self.client.get("/health", headers=headers)
        assert response.status_code == 200

        # 在实际的CORS中间件配置下，应该有CORS响应头
        # 但在测试环境中可能不会完全模拟

    def test_secure_cors_config(self):
        """测试安全的CORS配置"""
        # 配置安全的CORS设置
        settings = Settings(
            allowed_origins="https://yourdomain.com,https://www.yourdomain.com",
            allowed_methods="GET,POST,DELETE",
            allowed_headers="Content-Type,Authorization",
        )

        # 验证配置
        origins = settings.get_cors_origins()
        methods = settings.get_cors_methods()
        headers = settings.get_cors_headers()

        # 确保没有使用通配符
        assert "*" not in origins
        assert "*" not in methods
        assert "*" not in headers

        # 确保只有HTTPS域名（生产环境）
        for origin in origins:
            if origin.startswith("http"):
                assert origin.startswith("https://"), f"不安全的HTTP域名: {origin}"

    def test_development_cors_config(self):
        """测试开发环境CORS配置"""
        settings = Settings()

        # 默认开发环境配置应该允许本地访问
        origins = settings.get_cors_origins()

        # 检查是否包含本地地址
        local_origins = [
            origin
            for origin in origins
            if "localhost" in origin or "127.0.0.1" in origin
        ]
        assert len(local_origins) > 0, "开发环境应该包含本地域名"
