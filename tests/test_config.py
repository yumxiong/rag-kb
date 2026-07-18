"""
Config 模块单元测试
"""

import base64
import os
import tempfile
from unittest.mock import Mock, mock_open, patch

import pytest

from app.core.config import Settings


# 为本文件的测试隔离环境变量，避免 .env 或全局环境干扰默认值/优先级
@pytest.fixture(autouse=True)
def isolate_env_for_config_tests(mock_openai_key):
    # 仅保留对这些测试安全且必要的最小环境；
    # 依赖 conftest.py 的 mock_openai_key，随后再清空以避免其影响
    with patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "openai",
            "EMBEDDING_PROVIDER": "openai",
        },
        clear=True,
    ):
        # 禁用 pydantic-settings 对 .env 的读取，避免外部 .env 污染
        try:
            from pydantic_settings.sources import DotEnvSettingsSource

            with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
                # 默认屏蔽系统 keyring，避免读取真实密钥
                try:
                    import keyring  # noqa: F401

                    with patch("keyring.get_password", return_value=None):
                        yield
                except ImportError:
                    # 无 keyring 安装时，直接继续
                    yield
        except Exception:
            # 若 patch 失败，也至少保证环境变量已被清空
            yield


# 模块级临时目录fixture，供两个测试类共享
@pytest.fixture
def temp_dirs():
    """创建临时目录路径（子目录未实际创建）"""
    with tempfile.TemporaryDirectory() as temp_dir:
        upload_dir = os.path.join(temp_dir, "uploads")
        chroma_dir = os.path.join(temp_dir, "chroma")
        yield upload_dir, chroma_dir


class TestSettings:
    """Settings 测试类"""

    def test_default_initialization(self, temp_dirs):
        """测试默认初始化"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(upload_dir=upload_dir, chroma_db_path=chroma_dir)

        # 验证默认值
        assert settings.app_name == "RAG Knowledge Base"
        assert settings.app_version == "1.0.0"
        assert settings.llm_provider == "openai"
        assert settings.embedding_provider == "openai"
        assert settings.chat_model == "gpt-3.5-turbo"
        assert settings.embedding_model == "text-embedding-ada-002"
        assert settings.chunk_size == 1000
        assert settings.chunk_overlap == 200
        assert settings.max_sources == 3
        assert settings.similarity_threshold == 1.5
        assert settings.debug is False
        assert settings.enable_api_docs is False

        # 验证目录创建
        assert os.path.exists(upload_dir)
        assert os.path.exists(chroma_dir)

    def test_custom_initialization(self, temp_dirs):
        """测试自定义初始化"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            app_name="Custom RAG",
            llm_provider="deepseek",
            embedding_provider="zhipu",
            chat_model="deepseek-chat",
            chunk_size=2000,
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.app_name == "Custom RAG"
        assert settings.llm_provider == "deepseek"
        assert settings.embedding_provider == "zhipu"
        assert settings.chat_model == "deepseek-chat"
        assert settings.chunk_size == 2000

    def test_get_api_key_from_direct_config(self, temp_dirs):
        """测试从直接配置获取API key"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            api_key="direct-api-key", upload_dir=upload_dir, chroma_db_path=chroma_dir
        )

        assert settings.get_api_key() == "direct-api-key"

    def test_get_api_key_from_file(self, temp_dirs):
        """测试从文件获取API key"""
        upload_dir, chroma_dir = temp_dirs

        # 创建临时API key文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as key_file:
            key_file.write("file-api-key")
            key_file_path = key_file.name

        try:
            settings = Settings(
                api_key_file=key_file_path,
                upload_dir=upload_dir,
                chroma_db_path=chroma_dir,
            )

            assert settings.get_api_key() == "file-api-key"
        finally:
            os.unlink(key_file_path)

    def test_get_api_key_from_file_error(self, temp_dirs):
        """测试从不存在的文件获取API key"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            api_key_file="/nonexistent/path/key.txt",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        # 应该返回None而不是抛出异常
        assert settings.get_api_key() is None

    def test_get_api_key_from_base64(self, temp_dirs):
        """测试从base64编码获取API key"""
        upload_dir, chroma_dir = temp_dirs

        # base64编码的API key
        original_key = "base64-test-key"
        encoded_key = base64.b64encode(original_key.encode()).decode()

        settings = Settings(
            api_key_base64=encoded_key, upload_dir=upload_dir, chroma_db_path=chroma_dir
        )

        assert settings.get_api_key() == original_key

    def test_get_api_key_from_base64_invalid(self, temp_dirs):
        """测试无效base64编码的API key"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            api_key_base64="invalid-base64",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        # 应该返回None而不是抛出异常
        assert settings.get_api_key() is None

    def test_get_jwt_secret_from_direct_config(self, temp_dirs):
        """测试从直接配置获取JWT密钥"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            jwt_secret="test-jwt-secret",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.get_jwt_secret() == "test-jwt-secret"

    def test_get_jwt_secret_missing_raises(self, temp_dirs):
        """测试JWT密钥缺失时抛出异常"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(upload_dir=upload_dir, chroma_db_path=chroma_dir)

        with pytest.raises(RuntimeError):
            settings.get_jwt_secret()

    def test_get_admin_password_hash_from_base64(self, temp_dirs):
        """测试从base64获取管理员密码哈希"""
        upload_dir, chroma_dir = temp_dirs

        encoded_hash = base64.b64encode(
            b"$argon2id$v=19$m=65536,t=3,p=4$base64$hash"
        ).decode()
        settings = Settings(
            admin_password_hash_base64=encoded_hash,
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert (
            settings.get_admin_password_hash()
            == "$argon2id$v=19$m=65536,t=3,p=4$base64$hash"
        )

    def test_get_admin_password_hash_missing_raises(self, temp_dirs):
        """测试管理员密码哈希缺失时抛出异常"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(upload_dir=upload_dir, chroma_db_path=chroma_dir)

        with pytest.raises(RuntimeError):
            settings.get_admin_password_hash()

    def test_get_api_key_backward_compatibility(self, temp_dirs):
        """测试向后兼容的OpenAI API key"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            openai_api_key="legacy-openai-key",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.get_api_key() == "legacy-openai-key"
        assert settings.get_openai_api_key() == "legacy-openai-key"

    def test_get_api_key_priority_order(self, temp_dirs):
        """测试API key获取的优先级"""
        upload_dir, chroma_dir = temp_dirs

        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as key_file:
            key_file.write("file-key")
            key_file_path = key_file.name

        try:
            settings = Settings(
                api_key="direct-key",  # 应该优先使用这个
                api_key_file=key_file_path,
                api_key_base64=base64.b64encode(b"base64-key").decode(),
                openai_api_key="openai-key",
                upload_dir=upload_dir,
                chroma_db_path=chroma_dir,
            )

            # 应该返回direct-key（优先级最高）
            assert settings.get_api_key() == "direct-key"
        finally:
            os.unlink(key_file_path)

    def test_get_api_key_fallback_chain(self, temp_dirs):
        """测试API key回退链"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            # 不设置直接的api_key
            openai_api_key="fallback-openai-key",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        # 应该回退到openai_api_key
        assert settings.get_api_key() == "fallback-openai-key"

    @patch("os.path.exists")
    def test_get_api_key_from_docker_secrets(self, mock_exists, temp_dirs):
        """测试从Docker secrets获取API key"""
        upload_dir, chroma_dir = temp_dirs

        # 模拟Docker secret文件存在
        mock_exists.return_value = True

        with patch("builtins.open", mock_open(read_data="docker-secret-key")):
            settings = Settings(
                llm_provider="deepseek",
                upload_dir=upload_dir,
                chroma_db_path=chroma_dir,
            )

            api_key = settings.get_api_key()
            assert api_key == "docker-secret-key"

            # 验证正确的secret路径被检查
            mock_exists.assert_called_with(
                "/run/secrets/openai_api_key/deepseek_api_key"
            )

    @patch("os.path.exists")
    def test_get_api_key_from_docker_secrets_openai(self, mock_exists, temp_dirs):
        """测试从Docker secrets获取OpenAI API key"""
        upload_dir, chroma_dir = temp_dirs

        mock_exists.return_value = True

        with patch("builtins.open", mock_open(read_data="openai-docker-key")):
            settings = Settings(
                llm_provider="openai", upload_dir=upload_dir, chroma_db_path=chroma_dir
            )

            api_key = settings.get_api_key()
            assert api_key == "openai-docker-key"

            # OpenAI应该使用标准名称
            mock_exists.assert_called_with(
                "/run/secrets/openai_api_key/deepseek_api_key"
            )

    @patch("keyring.get_password")
    def test_get_api_key_from_keyring(self, mock_get_password, temp_dirs):
        """测试从系统keyring获取API key"""
        upload_dir, chroma_dir = temp_dirs

        mock_get_password.return_value = "keyring-api-key"

        settings = Settings(
            llm_provider="deepseek", upload_dir=upload_dir, chroma_db_path=chroma_dir
        )

        api_key = settings.get_api_key()
        assert api_key == "keyring-api-key"

        # 验证keyring被正确调用
        mock_get_password.assert_called_with("rag-kb", "deepseek_api_key")

    @patch("keyring.get_password")
    def test_get_api_key_from_keyring_fallback_to_openai(
        self, mock_get_password, temp_dirs
    ):
        """测试keyring回退到OpenAI配置"""
        upload_dir, chroma_dir = temp_dirs

        # 第一次调用返回None，第二次调用返回OpenAI key
        mock_get_password.side_effect = [None, "openai-keyring-key"]

        settings = Settings(
            llm_provider="deepseek", upload_dir=upload_dir, chroma_db_path=chroma_dir
        )

        api_key = settings.get_api_key()
        assert api_key == "openai-keyring-key"

        # 验证两次调用
        assert mock_get_password.call_count == 2

    @patch("keyring.get_password", side_effect=ImportError())
    def test_get_api_key_keyring_not_available(self, mock_get_password, temp_dirs):
        """测试keyring不可用时的处理"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(upload_dir=upload_dir, chroma_db_path=chroma_dir)

        # 应该优雅处理ImportError（或其他异常）
        api_key = settings.get_api_key()
        assert api_key is None

    def test_get_embedding_api_key_same_provider(self, temp_dirs):
        """测试相同提供商的嵌入API key"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            api_key="test-key",
            llm_provider="openai",
            embedding_provider="openai",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.get_embedding_api_key() == "test-key"

    def test_get_embedding_api_key_zhipu_provider(self, temp_dirs):
        """测试智谱AI嵌入提供商"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            embedding_provider="zhipu",
            zhipu_api_key="zhipu-key",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.get_embedding_api_key() == "zhipu-key"

    def test_get_model_config_openai(self, temp_dirs):
        """测试OpenAI模型配置"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            llm_provider="openai",
            embedding_provider="openai",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        config = settings.get_model_config()

        assert config["provider"] == "openai"
        assert config["embedding_provider"] == "openai"
        assert config["chat_model"] == "gpt-3.5-turbo"
        assert config["embedding_model"] == "text-embedding-ada-002"
        assert config["api_base_url"] == "https://api.openai.com/v1"
        assert config["embedding_api_base_url"] == "https://api.openai.com/v1"

    def test_get_model_config_deepseek(self, temp_dirs):
        """测试DeepSeek模型配置"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            llm_provider="deepseek",
            embedding_provider="openai",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        config = settings.get_model_config()

        assert config["provider"] == "deepseek"
        assert config["chat_model"] == "deepseek-chat"  # 应该自动替换默认值
        assert config["api_base_url"] == "https://api.deepseek.com"
        assert config["embedding_api_base_url"] == "https://api.openai.com/v1"

    def test_get_model_config_zhipu(self, temp_dirs):
        """测试智谱AI模型配置"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            llm_provider="zhipu",
            embedding_provider="zhipu",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        config = settings.get_model_config()

        assert config["provider"] == "zhipu"
        assert config["chat_model"] == "glm-4"  # 应该自动替换默认值
        assert config["embedding_model"] == "embedding-3"  # 应该自动替换
        assert config["api_base_url"] == "https://open.bigmodel.cn/api/paas/v4"
        assert (
            config["embedding_api_base_url"] == "https://open.bigmodel.cn/api/paas/v4"
        )

    def test_get_model_config_custom_values(self, temp_dirs):
        """测试自定义模型配置值"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            llm_provider="deepseek",
            chat_model="custom-chat-model",
            api_base_url="https://custom.api.com",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        config = settings.get_model_config()

        # 自定义值应该被保留
        assert config["chat_model"] == "custom-chat-model"
        assert config["api_base_url"] == "https://custom.api.com"

    def test_get_model_config_mixed_providers(self, temp_dirs):
        """测试混合提供商配置"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            llm_provider="deepseek",
            embedding_provider="openai",
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        config = settings.get_model_config()

        assert config["provider"] == "deepseek"
        assert config["embedding_provider"] == "openai"
        assert config["api_base_url"] == "https://api.deepseek.com"
        assert config["embedding_api_base_url"] == "https://api.openai.com/v1"

    def test_directory_creation_on_init(self, temp_dirs):
        """测试初始化时目录创建"""
        upload_dir, chroma_dir = temp_dirs

        # 确保目录不存在
        assert not os.path.exists(upload_dir)
        assert not os.path.exists(chroma_dir)

        # 创建设置实例应该创建目录
        settings = Settings(upload_dir=upload_dir, chroma_db_path=chroma_dir)

        assert os.path.exists(upload_dir)
        assert os.path.exists(chroma_dir)

    def test_cost_optimization_config(self, temp_dirs):
        """测试成本优化配置"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            enable_embedding_cache=False,
            enable_qa_cache=True,
            embedding_cache_ttl_days=14,
            qa_cache_ttl_hours=48,
            embedding_batch_size=200,
            max_context_length=8000,
            llm_temperature=0.2,
            llm_max_tokens=1200,
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.enable_embedding_cache is False
        assert settings.enable_qa_cache is True
        assert settings.embedding_cache_ttl_days == 14
        assert settings.qa_cache_ttl_hours == 48
        assert settings.embedding_batch_size == 200
        assert settings.max_context_length == 8000
        assert settings.llm_temperature == 0.2
        assert settings.llm_max_tokens == 1200

    def test_rag_config_parameters(self, temp_dirs):
        """测试RAG配置参数"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            chunk_size=1500,
            chunk_overlap=300,
            max_sources=5,
            similarity_threshold=0.8,
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.chunk_size == 1500
        assert settings.chunk_overlap == 300
        assert settings.max_sources == 5
        assert settings.similarity_threshold == 0.8

    def test_server_config_parameters(self, temp_dirs):
        """测试服务器配置参数"""
        upload_dir, chroma_dir = temp_dirs

        settings = Settings(
            backend_host="127.0.0.1",
            backend_port=9000,
            frontend_host="localhost",
            frontend_port=8502,
            upload_dir=upload_dir,
            chroma_db_path=chroma_dir,
        )

        assert settings.backend_host == "127.0.0.1"
        assert settings.backend_port == 9000
        assert settings.frontend_host == "localhost"
        assert settings.frontend_port == 8502


class TestSettingsIntegration:
    """Settings 集成测试"""

    def test_complete_configuration_workflow(self, temp_dirs):
        """测试完整的配置工作流程"""
        upload_dir, chroma_dir = temp_dirs

        # 创建API key文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as key_file:
            key_file.write("integration-test-key")
            key_file_path = key_file.name

        try:
            # 创建完整配置
            settings = Settings(
                app_name="Integration Test RAG",
                llm_provider="deepseek",
                embedding_provider="openai",
                api_key_file=key_file_path,
                chat_model="custom-deepseek-model",
                chunk_size=1500,
                max_sources=4,
                enable_embedding_cache=True,
                upload_dir=upload_dir,
                chroma_db_path=chroma_dir,
            )

            # 验证基本配置
            assert settings.app_name == "Integration Test RAG"

            # 验证API key获取
            assert settings.get_api_key() == "integration-test-key"
            assert settings.get_embedding_api_key() == "integration-test-key"

            # 验证模型配置
            model_config = settings.get_model_config()
            assert model_config["provider"] == "deepseek"
            assert model_config["embedding_provider"] == "openai"
            assert model_config["chat_model"] == "custom-deepseek-model"
            assert model_config["api_base_url"] == "https://api.deepseek.com"
            assert model_config["embedding_api_base_url"] == "https://api.openai.com/v1"

            # 验证RAG配置
            assert settings.chunk_size == 1500
            assert settings.max_sources == 4

            # 验证目录创建
            assert os.path.exists(upload_dir)
            assert os.path.exists(chroma_dir)

        finally:
            os.unlink(key_file_path)

    def test_environment_variable_loading(self, temp_dirs):
        """测试环境变量加载"""
        upload_dir, chroma_dir = temp_dirs

        # 模拟环境变量
        env_vars = {
            "LLM_PROVIDER": "zhipu",
            "CHAT_MODEL": "glm-4-test",
            "CHUNK_SIZE": "2000",
            "MAX_SOURCES": "5",
            "DEBUG": "false",
            "ENABLE_API_DOCS": "true",
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings(upload_dir=upload_dir, chroma_db_path=chroma_dir)

            # 验证环境变量被正确加载
            assert settings.llm_provider == "zhipu"
            assert settings.chat_model == "glm-4-test"
            assert settings.chunk_size == 2000
            assert settings.max_sources == 5
            assert settings.debug is False
            assert settings.enable_api_docs is True

    def test_multiple_api_key_sources_priority(self, temp_dirs):
        """测试多个API key源的优先级"""
        upload_dir, chroma_dir = temp_dirs

        # 创建API key文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as key_file:
            key_file.write("file-key")
            key_file_path = key_file.name

        try:
            # 模拟环境变量
            base64_key = base64.b64encode(b"env-base64-key").decode()
            env_vars = {
                "API_KEY": "env-direct-key",  # 应该有最高优先级
                "API_KEY_BASE64": base64_key,
                "OPENAI_API_KEY": "env-openai-key",
            }

            with patch.dict(os.environ, env_vars):
                settings = Settings(
                    api_key_file=key_file_path,  # 文件key应该被忽略
                    openai_api_key="config-openai-key",  # 配置key应该被忽略
                    upload_dir=upload_dir,
                    chroma_db_path=chroma_dir,
                )

                # 应该使用环境变量中的直接API key
                assert settings.get_api_key() == "env-direct-key"

        finally:
            os.unlink(key_file_path)

    @patch("keyring.get_password")
    def test_keyring_integration(self, mock_get_password, temp_dirs):
        """测试keyring集成"""
        upload_dir, chroma_dir = temp_dirs

        # 模拟keyring返回不同提供商的密钥
        def mock_get_password_impl(service, username):
            keyring_keys = {
                ("rag-kb", "deepseek_api_key"): "keyring-deepseek-key",
                ("rag-kb", "openai_api_key"): "keyring-openai-key",
                ("rag-kb", "zhipu_api_key"): "keyring-zhipu-key",
            }
            return keyring_keys.get((service, username))

        mock_get_password.side_effect = mock_get_password_impl

        # 测试不同提供商
        providers_and_keys = [
            ("deepseek", "keyring-deepseek-key"),
            ("openai", "keyring-openai-key"),
        ]

        for provider, expected_key in providers_and_keys:
            settings = Settings(
                llm_provider=provider, upload_dir=upload_dir, chroma_db_path=chroma_dir
            )

            api_key = settings.get_api_key()
            assert api_key == expected_key

    def test_docker_secrets_integration(self, temp_dirs):
        """测试Docker secrets集成"""
        upload_dir, chroma_dir = temp_dirs

        # 模拟Docker secrets文件
        secrets_content = {
            "/run/secrets/openai_api_key/deepseek_api_key": "docker-deepseek-key"
        }

        def mock_exists(path):
            return path in secrets_content

        # 记录真实 open 以便对非 secrets 文件走真实分支
        real_open = open

        def mock_open_func(path, mode="r", **kwargs):
            p = str(path)
            if p in secrets_content:
                return mock_open(read_data=secrets_content[p]).return_value
            # 其它文件（如 .env）走真实 open，避免 TypeError/编码问题
            return real_open(path, mode, **kwargs)

        with patch("os.path.exists", side_effect=mock_exists), patch(
            "builtins.open", side_effect=mock_open_func
        ):

            # 测试DeepSeek Docker secret
            settings = Settings(
                llm_provider="deepseek",
                upload_dir=upload_dir,
                chroma_db_path=chroma_dir,
            )

            api_key = settings.get_api_key()
            assert api_key == "docker-deepseek-key"
