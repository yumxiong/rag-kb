"""
配置管理模块
"""

import base64
import logging
import os
from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.url_safety import is_safe_base_url

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)
    # 应用基本配置
    app_name: str = "RAG Knowledge Base"
    app_version: str = "1.0.0"
    debug: bool = False
    # 生产环境默认关闭 FastAPI 自动文档和 OpenAPI Schema
    enable_api_docs: bool = False

    # LLM配置 - 支持多种模型提供商
    llm_provider: str = "openai"  # 支持: openai, deepseek, zhipu, etc.
    embedding_provider: str = "openai"  # 嵌入模型提供商，可以与LLM提供商不同

    # Base URL配置
    allowed_chat_base_urls: str = (
        "https://api.openai.com/v1,https://api.deepseek.com,"
        "https://open.bigmodel.cn/api/paas/v4,https://openrouter.ai/api/v1"
    )

    # API配置 - 支持多种获取方式
    api_key: Optional[str] = None
    api_key_file: Optional[str] = None
    api_key_base64: Optional[str] = None

    # 智谱AI配置
    zhipu_api_key: Optional[str] = None

    # 向后兼容的OpenAI配置
    openai_api_key: Optional[str] = None
    openai_api_key_file: Optional[str] = None
    openai_api_key_base64: Optional[str] = None

    # 嵌入模型专用API Key（与LLM解耦）
    embedding_api_key: Optional[str] = None
    embedding_api_key_file: Optional[str] = None
    embedding_api_key_base64: Optional[str] = None

    # 模型配置
    api_base_url: Optional[str] = None  # 自定义API端点（聊天模型）
    embedding_api_base_url: Optional[str] = None  # 嵌入模型API端点
    chat_model: str = "gpt-3.5-turbo"  # 聊天模型
    embedding_model: str = "text-embedding-ada-002"  # 嵌入模型

    # 存储配置
    upload_dir: str = "./data/uploads"
    chroma_db_path: str = "./data/chroma_db"
    # 临时上传目录（容器本地，写入更快，用于先写临时再后台搬迁）
    temp_upload_dir: str = "/tmp/rag_uploads"
    # 作业状态目录（用于持久化处理进度/错误）
    job_status_dir: str = "./data/job_status"
    max_file_size_mb: int = 50  # 最大文件上传大小（MB）

    # 服务器配置
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 8501

    # CORS配置
    allowed_origins: str = (
        "http://localhost:8501,http://127.0.0.1:8501"  # 允许的前端域名，逗号分隔
    )
    allowed_methods: str = "GET,POST,DELETE"  # 允许的HTTP方法
    # 允许的请求头（含BYOK和SSE）
    allowed_headers: str = (
        "Content-Type,Authorization,LLM-API-Key,LLM-Provider,LLM-Base-URL,"
        "LLM-Model,Cache-Control,Connection,X-Anonymous-Token"
    )

    # RAG配置
    chunk_size: int = 1000
    chunk_overlap: int = 200
    min_source_limit: int = 1
    max_source_limit: int = 5
    max_sources: int = 3

    retrieval_precheck_k: int = 6
    retrieval_k_scoped: int = 3
    retrieval_k_global: int = 6
    retrieval_fetch_k_global: int = 24
    retrieval_mmr_lambda_mult: float = 0.3

    similarity_threshold: float = 1.5  # ChromaDB距离分数,值越小越相似,1.5以下通常为相关

    # 回退/过滤相关
    relevance_fallback_threshold: float = (
        0.5  # 更严格的相似度阈值（距离<=该值视为强相关），无强相关则回退到全库
    )
    relevance_fallback_margin: float = (
        0.1  # 当全库最佳结果优于限定范围最佳结果超过该边际时触发回退
    )
    # 输入限制设置
    max_question_length: int = 2000
    min_question_length: int = 1
    # 成本优化配置
    enable_embedding_cache: bool = True
    enable_qa_cache: bool = True
    embedding_cache_ttl_days: int = 7  # 嵌入缓存过期时间（天）
    qa_cache_ttl_hours: int = 24  # 问答缓存过期时间（小时）

    # 智能批处理配置
    embedding_batch_size: int = 100  # 嵌入批处理大小
    max_context_length: int = 4000  # 最大上下文长度（tokens）

    # LLM优化配置
    llm_temperature: float = 0.1  # 降低随机性提高缓存命中
    llm_max_tokens: int = 800  # 减少生成token数

    # 并发保护配置
    max_concurrent_llm_requests: int = 5  # LLM 调用最大并发数
    max_concurrent_requests: int = 20  # 全局最大并发请求数
    max_concurrent_identity_questions: int = 1
    question_deadline_seconds: int = 60
    embedding_timeout_seconds: int = 15
    chat_timeout_seconds: int = 45

    # Application rolling-window limits; the reverse proxy has independent limits.
    max_session_requests_per_minute: int = 30
    max_ask_requests_per_minute: int = 6
    max_quota_requests_per_minute: int = 60

    # 配额限制配置
    enable_quota_limit: bool = True  # 是否启用配额限制
    enable_document_maintenance: bool = False
    default_daily_quota: int = 5  # 默认每日配额（未提供自定义API Key的用户）
    global_daily_ask_limit: int = 500
    global_daily_default_llm_limit: int = 200
    global_daily_llm_limit: int = 500
    global_daily_query_embedding_limit: int = 1000
    quota_timezone: str = "UTC"
    quota_storage_path: str = "./data/quotas"  # 配额数据存储路径
    anonymous_store_reference: str = ""
    anonymous_storage_development: bool = False
    anonymous_mount_path: str = "/app/data"
    anonymous_mount_source: str = ""
    anonymous_cookie_secure: bool = True

    @field_validator("llm_max_tokens", mode="before")
    @classmethod
    def validate_output_limit(cls, value):
        """Environment configuration may lower, but never raise, the hard cap."""
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            value = int(value)
        if type(value) is not int or not 1 <= value <= 800:
            raise ValueError("llm_max_tokens must be an integer from 1 to 800")
        return value

    @field_validator(
        "max_concurrent_llm_requests",
        "max_concurrent_requests",
        "max_concurrent_identity_questions",
        "max_session_requests_per_minute",
        "max_ask_requests_per_minute",
        "max_quota_requests_per_minute",
        mode="before",
    )
    @classmethod
    def validate_traffic_limit(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            value = int(value)
        if type(value) is not int or value <= 0:
            raise ValueError("Traffic limits must be positive integers")
        return value

    @field_validator(
        "question_deadline_seconds",
        "embedding_timeout_seconds",
        "chat_timeout_seconds",
        mode="before",
    )
    @classmethod
    def validate_provider_deadline(cls, value, info):
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            value = int(value)
        maximum = {
            "question_deadline_seconds": 60,
            "embedding_timeout_seconds": 15,
            "chat_timeout_seconds": 45,
        }[info.field_name]
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{info.field_name} must be from 1 to {maximum} seconds")
        return value

    @field_validator(
        "default_daily_quota",
        "global_daily_ask_limit",
        "global_daily_default_llm_limit",
        "global_daily_llm_limit",
        "global_daily_query_embedding_limit",
        mode="before",
    )
    @classmethod
    def validate_daily_limit(cls, value):
        """Accept positive integer settings, including environment strings."""
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            value = int(value)
        if type(value) is not int or value <= 0:
            raise ValueError("Daily limits must be positive integers")
        return value

    def budget_limits(self) -> dict[str, int]:
        """Return the configured UTC daily hard limits."""
        self.validate_output_limit(self.llm_max_tokens)
        limits = {
            "ask": self.global_daily_ask_limit,
            "default_llm": self.global_daily_default_llm_limit,
            "llm": self.global_daily_llm_limit,
            "query_embedding": self.global_daily_query_embedding_limit,
        }
        if self.quota_timezone != "UTC" or any(
            type(value) is not int or value <= 0
            for value in (*limits.values(), self.default_daily_quota)
        ):
            raise ValueError("Daily budget limits must be positive and timezone UTC")
        if not self.anonymous_storage_development and not self.enable_quota_limit:
            raise ValueError("Production requires personal quota enforcement")
        return limits

    # jwt认证相关
    jwt_algorithm: str = "HS256"
    jwt_secret: str | None = None
    jwt_secret_file: str | None = None
    jwt_secret_base64: str | None = None

    # 管理员密钥配置
    admin_username: str = "admin"
    admin_password_hash: str | None = None
    admin_password_hash_file: str | None = None
    admin_password_hash_base64: str | None = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 确保目录存在
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.chroma_db_path, exist_ok=True)
        # 确保临时目录存在
        try:
            os.makedirs(self.temp_upload_dir, exist_ok=True)
        except Exception as e:
            logger.warning(
                f"Failed to create temp upload dir {self.temp_upload_dir}: {e}"
            )
        # 确保作业状态目录存在
        try:
            os.makedirs(self.job_status_dir, exist_ok=True)
        except Exception as e:
            logger.warning(
                f"Failed to create job status dir {self.job_status_dir}: {e}"
            )

    def get_allowed_chat_base_urls(self) -> list[str]:
        """获取允许的聊天模型API端点列表"""
        return [
            url.strip() for url in self.allowed_chat_base_urls.split(",") if url.strip()
        ]

    def get_api_key(self) -> Optional[str]:
        """安全地获取API Key（支持多种提供商）"""
        # 方式1: 新的通用API key配置
        if self.api_key:
            return self.api_key

        # 方式2: 从文件读取
        if self.api_key_file:
            try:
                with open(self.api_key_file, "r") as f:
                    key = f.read().strip()
                    if key:
                        return key
            except Exception:
                logger.warning("Failed to read API key from configured file")

        # 方式3: 从base64编码的环境变量
        if self.api_key_base64:
            try:
                key = base64.b64decode(self.api_key_base64).decode("utf-8").strip()
                if key:
                    return key
            except Exception:
                logger.warning("Failed to decode base64 API key")

        # 向后兼容：方式4: 检查OpenAI特定配置
        if self.openai_api_key:
            return self.openai_api_key

        if self.openai_api_key_file:
            try:
                with open(self.openai_api_key_file, "r") as f:
                    key = f.read().strip()
                    if key:
                        return key
            except Exception:
                logger.warning("Failed to read OpenAI API key from configured file")

        if self.openai_api_key_base64:
            try:
                key = (
                    base64.b64decode(self.openai_api_key_base64).decode("utf-8").strip()
                )
                if key:
                    return key
            except Exception:
                logger.warning("Failed to decode configured OpenAI API key")

        # 方式5: 从Docker secrets
        if self.llm_provider in {"openai", "deepseek"}:
            docker_secret_path = "/run/secrets/openai_api_key/deepseek_api_key"
        else:
            secret_name = f"{self.llm_provider}_api_key"
            docker_secret_path = f"/run/secrets/{secret_name}"
        if os.path.exists(docker_secret_path):
            try:
                with open(docker_secret_path, "r") as f:
                    key = f.read().strip()
                    if key:
                        return key
            except Exception:
                logger.warning("Failed to read API key from Docker secret")

        # 方式6: 从系统密钥环 (仅Linux/Mac)
        try:
            import keyring

            key = keyring.get_password("rag-kb", f"{self.llm_provider}_api_key")
            if not key and self.llm_provider != "openai":
                # 回退到openai密钥环配置
                key = keyring.get_password("rag-kb", "openai_api_key")
            if key:
                return key
        except ImportError:
            pass
        except Exception:
            logger.warning("Failed to get API key from system keyring")

        logger.warning("No valid API key configured")
        return None

    def get_openai_api_key(self) -> Optional[str]:
        """向后兼容：获取OpenAI API Key"""
        return self.get_api_key()

    def _read_secret_from_sources(
        self,
        *,
        direct_value: Optional[str],
        file_path: Optional[str],
        base64_value: Optional[str],
        secret_name: str,
    ) -> Optional[str]:
        """从直接值/文件/base64中读取敏感配置。"""
        if direct_value and direct_value.strip():
            return direct_value.strip()

        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    value = f.read().strip()
                    if value:
                        logger.info(f"{secret_name} loaded from file: {file_path}")
                        return value
            except Exception as e:
                logger.warning(
                    f"Failed to read {secret_name} from file {file_path}: {e}"
                )

        if base64_value:
            try:
                value = base64.b64decode(base64_value).decode("utf-8").strip()
                if value:
                    logger.info(
                        f"{secret_name} loaded from base64 environment variable"
                    )
                    return value
            except Exception as e:
                logger.warning(f"Failed to decode base64 {secret_name}: {e}")

        return None

    def get_jwt_secret(self) -> str:
        """获取JWT密钥，不存在时抛出异常以阻止不安全启动。"""
        secret = self._read_secret_from_sources(
            direct_value=self.jwt_secret,
            file_path=self.jwt_secret_file,
            base64_value=self.jwt_secret_base64,
            secret_name="JWT secret",
        )

        if not secret:
            raise RuntimeError(
                "JWT secret is not configured. Please set JWT_SECRET, "
                "JWT_SECRET_FILE, or JWT_SECRET_BASE64."
            )

        return secret

    def get_admin_password_hash(self) -> str:
        """获取管理员密码哈希，不存在时抛出异常以阻止不安全登录。"""
        password_hash = self._read_secret_from_sources(
            direct_value=self.admin_password_hash,
            file_path=self.admin_password_hash_file,
            base64_value=self.admin_password_hash_base64,
            secret_name="admin password hash",
        )

        if not password_hash:
            raise RuntimeError(
                "Admin password hash is not configured. Please set "
                "ADMIN_PASSWORD_HASH, ADMIN_PASSWORD_HASH_FILE, or "
                "ADMIN_PASSWORD_HASH_BASE64."
            )

        return password_hash

    def get_embedding_api_key(self) -> Optional[str]:
        """获取嵌入模型的API Key（优先使用专用配置，其次按提供商回退，最后复用通用API Key）"""
        # 1) 专用嵌入 Key
        if self.embedding_api_key:
            return self.embedding_api_key
        # 2) 从文件读取
        if self.embedding_api_key_file:
            try:
                with open(self.embedding_api_key_file, "r") as f:
                    key = f.read().strip()
                    if key:
                        return key
            except Exception:
                logger.warning("Failed to read embedding API key from configured file")
        # 3) 从base64
        if self.embedding_api_key_base64:
            try:
                key = (
                    base64.b64decode(self.embedding_api_key_base64)
                    .decode("utf-8")
                    .strip()
                )
                if key:
                    return key
            except Exception:
                logger.warning("Failed to decode configured embedding API key")
        # 4) 提供商专用（zhipu 兼容旧行为）
        if self.embedding_provider == "zhipu" and self.zhipu_api_key:
            return self.zhipu_api_key
        # 5) 回退到通用 API Key（与 LLM 共享）
        return self.get_api_key()

    def detect_provider_from_api_key(self, api_key: str) -> str:
        """根据API Key格式自动检测提供商"""
        if not api_key:
            return self.llm_provider

        api_key = api_key.strip()

        # Zhipu keys use: 32 hexadecimal characters, a dot, then 16 characters.
        # Check this first since it has a unique format
        if "." in api_key and len(api_key.split(".")) == 2:
            parts = api_key.split(".")
            if len(parts[0]) == 32 and len(parts[1]) == 16:
                return "zhipu"

        # OpenAI API keys start with "sk-" and are longer (51-55 chars typically)
        if api_key.startswith("sk-") and len(api_key) >= 48:
            return "openai"

        # DeepSeek API keys start with "sk-" and are shorter than OpenAI keys
        if api_key.startswith("sk-") and len(api_key) <= 47:
            return "deepseek"

        # Default to current provider if pattern doesn't match
        return self.llm_provider

    def get_model_config(self, overrides: Optional[dict] = None) -> Dict[str, Any]:
        """获取当前模型配置，支持按请求覆盖"""
        overrides = overrides or {}

        config = {
            "provider": self.llm_provider,
            "embedding_provider": self.embedding_provider,
            "chat_model": self.chat_model,
            "embedding_model": self.embedding_model,
            "api_base_url": self.api_base_url,
            "embedding_api_base_url": self.embedding_api_base_url,
        }

        # 应用覆盖项
        if overrides.get("provider"):
            config["provider"] = overrides["provider"]
        if overrides.get("api_base_url"):
            url = overrides["api_base_url"]
            if not is_safe_base_url(url, self.get_allowed_chat_base_urls()):
                raise HTTPException(status_code=400, detail="LLM-Base-URL 不安全")
            config["api_base_url"] = url
        if overrides.get("model"):
            config["chat_model"] = overrides["model"]

        # 如果提供了API key但没有明确指定provider，尝试自动检测
        auto_detected = False
        if overrides.get("api_key") and not overrides.get("provider"):
            detected_provider = self.detect_provider_from_api_key(overrides["api_key"])
            config["provider"] = detected_provider
            auto_detected = True
            if detected_provider != self.llm_provider:
                logger.info(
                    f"Auto-detected provider '{detected_provider}' "
                    "based on API key format"
                )

        # 根据不同提供商设置默认值
        # 如果provider被覆盖/自动检测且没有明确指定base_url，则使用provider对应的默认URL
        provider_changed = (
            overrides.get("provider") and overrides["provider"] != self.llm_provider
        ) or auto_detected

        if config["provider"] == "deepseek":
            # 当provider变更或自动检测为DeepSeek时，如果没有明确指定URL，使用DeepSeek的URL
            if not overrides.get("api_base_url") and (
                provider_changed or auto_detected
            ):
                config["api_base_url"] = "https://api.deepseek.com"
            elif not overrides.get("api_base_url") and not config["api_base_url"]:
                config["api_base_url"] = "https://api.deepseek.com"
            if config["chat_model"] == "gpt-3.5-turbo":  # 如果还是默认值
                config["chat_model"] = "deepseek-flash"
        elif config["provider"] == "zhipu":
            if not overrides.get("api_base_url") and (
                provider_changed or auto_detected
            ):
                config["api_base_url"] = "https://open.bigmodel.cn/api/paas/v4"
            elif not overrides.get("api_base_url") and not config["api_base_url"]:
                config["api_base_url"] = "https://open.bigmodel.cn/api/paas/v4"
            if config["chat_model"] == "gpt-3.5-turbo":
                config["chat_model"] = "glm-4"
        elif config["provider"] == "openai":
            if not overrides.get("api_base_url") and (
                provider_changed or auto_detected
            ):
                config["api_base_url"] = "https://api.openai.com/v1"
            elif not overrides.get("api_base_url") and not config["api_base_url"]:
                config["api_base_url"] = "https://api.openai.com/v1"

        # 嵌入模型配置
        if self.embedding_provider == "zhipu":
            if not config["embedding_api_base_url"]:
                config["embedding_api_base_url"] = (
                    "https://open.bigmodel.cn/api/paas/v4"
                )
            if self.embedding_model == "text-embedding-ada-002":
                config["embedding_model"] = "embedding-3"
        elif self.embedding_provider == "openai":
            if not config["embedding_api_base_url"]:
                config["embedding_api_base_url"] = "https://api.openai.com/v1"
        elif self.embedding_provider == "qwen":
            # Ali Qwen (DashScope) OpenAI-compatible endpoint
            if not config["embedding_api_base_url"]:
                config["embedding_api_base_url"] = (
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
            # 若仍是默认OpenAI旧值，替换为Qwen的默认嵌入模型
            if self.embedding_model == "text-embedding-ada-002":
                config["embedding_model"] = "text-embedding-v3"

        return config

    def get_cors_origins(self) -> list:
        """获取CORS允许的源域名列表"""
        if self.allowed_origins == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]

    def get_cors_methods(self) -> list:
        """获取CORS允许的HTTP方法列表"""
        if self.allowed_methods == "*":
            return ["*"]
        return [
            method.strip()
            for method in self.allowed_methods.split(",")
            if method.strip()
        ]

    def get_cors_headers(self) -> list:
        """获取CORS允许的请求头列表"""
        if self.allowed_headers == "*":
            return ["*"]
        return [
            header.strip()
            for header in self.allowed_headers.split(",")
            if header.strip()
        ]


# 全局配置实例
settings = Settings()
