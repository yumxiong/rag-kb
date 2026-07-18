"""
API接口测试
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.core.config import settings
from app.core.qa_engine import QAEngine
from app.main import app
from app.models.schemas import SourceDocument

client = TestClient(app)


def _admin_headers() -> dict:
    settings.jwt_secret = "test-jwt-secret"
    exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    token = jwt.encode(
        {
            "sub": settings.admin_username,
            "role": "admin",
            "iat": datetime.now(timezone.utc),
            "exp": exp,
        },
        settings.get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


class TestHealthAPI:
    """健康检查API测试"""

    def test_root_endpoint(self):
        """测试根端点"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "timestamp" in data

    @patch("app.main.settings")
    @patch("os.path.exists")
    def test_health_check_healthy(self, mock_exists, mock_settings):
        """测试健康检查 - 正常状态"""
        # 模拟配置
        mock_settings.openai_api_key = "test-key"
        mock_settings.app_version = "1.0.0"
        mock_exists.return_value = True

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"

    @patch("app.main.settings")
    @patch("os.path.exists")
    def test_health_check_degraded(self, mock_exists, mock_settings):
        """测试健康检查 - 降级状态"""
        # 模拟部分配置缺失
        mock_settings.openai_api_key = None
        mock_settings.get_api_key.return_value = None  # 确保健康检查读取到无API Key
        mock_settings.app_version = "1.0.0"
        mock_exists.return_value = True

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    def test_info_endpoint(self):
        """测试系统信息端点"""
        response = client.get("/info")
        assert response.status_code == 200
        data = response.json()
        assert "app_name" in data
        assert "version" in data
        assert "chunk_size" in data
        assert "debug" not in data

    def test_api_docs_disabled_in_current_app(self):
        """测试当前应用默认关闭 Swagger/ReDoc/OpenAPI 文档"""
        assert app.docs_url is None
        assert app.redoc_url is None
        assert app.openapi_url is None

        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


class TestDocumentAPI:
    """文档管理API测试"""

    def test_document_endpoints_require_admin(self):
        """测试文档管理接口需要管理员鉴权"""
        response = client.get("/api/documents/")
        assert response.status_code == 401

    @patch("app.api.documents.async_processor")
    @patch("app.api.documents.job_status")
    @patch("app.api.documents.doc_processor")
    def test_upload_document_async_returns_job_id(
        self, mock_processor, mock_job_status, mock_async_processor
    ):
        """测试异步上传返回 job_id 而不是 document_id"""
        mock_processor.validate_filename.return_value = "test.txt"
        mock_processor.is_supported_file.return_value = True
        mock_processor.compute_content_hash.return_value = "hash-async-1"
        mock_processor.save_to_temp_file.return_value = "/tmp/test.txt"

        with patch("app.api.documents.get_vector_store") as mock_get_vs:
            mock_vs = MagicMock()
            mock_vs.document_exists_by_content_hash.return_value = False
            mock_get_vs.return_value = mock_vs

            files = {"file": ("test.txt", b"test content", "text/plain")}
            response = client.post(
                "/api/documents/upload-async", files=files, headers=_admin_headers()
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["job_id"]
        assert data["document_id"] is None
        assert data["status"] == "queued"
        assert data["processing_mode"] == "async"
        assert data["filename"] == "test.txt"
        mock_job_status.init_job.assert_called_once()
        assert mock_async_processor.submit_task.call_args.args[0] == data["job_id"]

    @patch("app.api.documents.doc_processor")
    def test_upload_document_success(self, mock_processor):
        """测试成功上传文档"""
        mock_processor.validate_filename.return_value = "test.txt"
        # 模拟处理器
        mock_processor.is_supported_file.return_value = True
        mock_processor.compute_content_hash.return_value = "hash-1"
        mock_processor.save_uploaded_file.return_value = "/path/to/file.txt"
        mock_processor.get_document_info.return_value = {
            "file_type": ".txt",
            "file_size": 1024,
        }
        # 返回同步处理完成的结果
        mock_processor.process_document.return_value = {
            "status": "completed",
            "chunks": [],
            "chunk_count": 1,
            "document_id": "doc-123",
        }

        # 模拟向量存储（避免真实初始化）
        with patch("app.api.documents.get_vector_store") as mock_get_vs:
            mock_vs = MagicMock()
            mock_vs.add_documents.return_value = True
            mock_vs.document_exists_by_content_hash.return_value = False
            mock_get_vs.return_value = mock_vs

            # 模拟文件上传
            files = {"file": ("test.txt", b"test content", "text/plain")}
            response = client.post(
                "/api/documents/upload", files=files, headers=_admin_headers()
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "document" in data

    @patch("app.api.documents.doc_processor")
    def test_upload_unsupported_file(self, mock_processor):
        """测试上传不支持的文件格式"""
        mock_processor.validate_filename.return_value = "test.xyz"
        mock_processor.is_supported_file.return_value = False

        files = {"file": ("test.xyz", b"test content", "application/xyz")}
        response = client.post(
            "/api/documents/upload", files=files, headers=_admin_headers()
        )

        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_upload_large_file(self):
        """测试上传超大文件"""
        with patch.object(settings, "max_file_size_mb", 1):
            # 使用较小内容稳定触发超限，避免进入耗时文档处理流程
            large_content = b"x" * (2 * 1024 * 1024)  # 2MB

            files = {"file": ("large.txt", large_content, "text/plain")}
            response = client.post(
                "/api/documents/upload", files=files, headers=_admin_headers()
            )

        assert response.status_code == 400
        assert "File size too large" in response.json()["detail"]

    def test_upload_reject_path_traversal_filename(self):
        """测试危险文件名被拒绝"""
        files = {"file": ("../../evil.txt", b"test content", "text/plain")}
        response = client.post(
            "/api/documents/upload", files=files, headers=_admin_headers()
        )

        assert response.status_code == 400
        assert "Invalid filename" in response.json()["detail"]

    @patch("app.api.documents.doc_processor")
    def test_upload_duplicate_content_hash_conflict(self, mock_processor):
        """测试同内容不同文件名上传返回409"""
        mock_processor.validate_filename.side_effect = ["a.txt", "b.md"]
        mock_processor.is_supported_file.return_value = True
        mock_processor.compute_content_hash.return_value = "same-hash"
        mock_processor.save_uploaded_file.return_value = "/path/to/file.txt"
        mock_processor.get_document_info.return_value = {
            "file_type": ".txt",
            "file_size": 12,
        }
        mock_processor.process_document.return_value = {
            "status": "completed",
            "chunks": [],
            "chunk_count": 1,
            "document_id": "doc-123",
        }

        with patch("app.api.documents.get_vector_store") as mock_get_vs:
            mock_vs = MagicMock()
            mock_vs.add_documents.return_value = True
            mock_vs.document_exists_by_content_hash.side_effect = [False, True]
            mock_get_vs.return_value = mock_vs

            files1 = {"file": ("a.txt", b"same content", "text/plain")}
            response1 = client.post(
                "/api/documents/upload", files=files1, headers=_admin_headers()
            )
            assert response1.status_code == 200

            files2 = {"file": ("b.md", b"same content", "text/markdown")}
            response2 = client.post(
                "/api/documents/upload", files=files2, headers=_admin_headers()
            )
            assert response2.status_code == 409
            assert "identical content" in response2.json()["detail"]

    @patch("app.api.documents.vector_store")
    def test_list_documents(self, mock_vector_store):
        """测试获取文档列表"""
        # 模拟向量存储返回的文档列表
        mock_vector_store.list_documents.return_value = [
            {
                "document_id": "doc1",
                "filename": "test1.txt",
                "chunk_count": 5,
                "processed_at": "2023-01-01T00:00:00",
            }
        ]

        response = client.get("/api/documents/", headers=_admin_headers())
        assert response.status_code == 200
        documents = response.json()
        assert len(documents) == 1
        assert documents[0]["filename"] == "test1.txt"

    @patch("app.api.documents.vector_store")
    def test_get_document_found(self, mock_vector_store):
        """测试获取文档详情 - 找到文档"""
        mock_vector_store.list_documents.return_value = [
            {"document_id": "doc1", "filename": "test1.txt", "chunk_count": 5}
        ]

        response = client.get("/api/documents/doc1", headers=_admin_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["document"]["filename"] == "test1.txt"

    @patch("app.api.documents.vector_store")
    def test_get_document_not_found(self, mock_vector_store):
        """测试获取文档详情 - 文档不存在"""
        mock_vector_store.list_documents.return_value = []

        response = client.get("/api/documents/nonexistent", headers=_admin_headers())
        assert response.status_code == 404
        assert "Document not found" in response.json()["detail"]

    @patch("app.api.documents.vector_store")
    def test_delete_document_success(self, mock_vector_store):
        """测试成功删除文档"""
        mock_vector_store.delete_document_by_id.return_value = True

        response = client.delete("/api/documents/doc1", headers=_admin_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch("app.api.documents.vector_store")
    def test_delete_document_not_found(self, mock_vector_store):
        """测试删除不存在的文档"""
        mock_vector_store.delete_document_by_id.return_value = False

        response = client.delete("/api/documents/nonexistent", headers=_admin_headers())
        assert response.status_code == 404

    @patch("app.api.documents.async_processor")
    @patch("app.api.documents.job_status")
    def test_get_processing_status_not_found_returns_job_fields(
        self, mock_job_status, mock_async_processor
    ):
        mock_async_processor.get_task_status.return_value = None
        mock_job_status.get_job_status.return_value = None

        response = client.get(
            "/api/documents/status/nonexistent-job", headers=_admin_headers()
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"
        assert data["message"] == "Job not found"
        assert data["job_id"] == "nonexistent-job"
        assert data["document_id"] is None


class TestQAAPI:
    """问答API测试"""

    @patch("app.api.qa.vector_store")
    @patch("app.api.qa.qa_engine")
    def test_ask_question_success(self, mock_qa_engine, mock_vector_store):
        """测试成功回答问题"""
        # 模拟有文档数据
        mock_vector_store.get_collection_info.return_value = {"document_count": 5}

        # 模拟问答引擎响应
        from app.models.schemas import QuestionResponse, SourceDocument

        mock_response = QuestionResponse(
            answer="这是测试答案",
            sources=[
                SourceDocument(
                    document_name="test.txt", content="相关内容", similarity_score=0.9
                )
            ],
            processing_time=1.5,
        )
        mock_qa_engine.ask.return_value = mock_response

        # 关闭配额限制，避免用例因默认配额耗尽而失败
        from app.core import config as config_module

        config_module.settings.enable_quota_limit = False

        # 发送请求
        request_data = {"question": "测试问题", "max_sources": 3}
        response = client.post("/api/qa/ask", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "这是测试答案"
        assert len(data["sources"]) == 1
        assert data["processing_time"] == 1.5

    @patch("app.api.qa.vector_store")
    def test_ask_question_no_documents(self, mock_vector_store):
        """测试没有文档时的问答"""
        # 模拟没有文档数据
        mock_vector_store.get_collection_info.return_value = {"document_count": 0}

        request_data = {"question": "测试问题"}
        response = client.post("/api/qa/ask", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert "知识库中暂时没有文档" in data["answer"]
        assert len(data["sources"]) == 0

    def test_ask_empty_question(self):
        """测试空问题"""
        request_data = {"question": "  "}
        response = client.post("/api/qa/ask", json=request_data)

        assert response.status_code == 400
        assert "Question cannot be empty" in response.json()["detail"]

    def test_ask_question_too_long(self):
        """测试问题过长"""
        long_question = "a" * 2001
        request_data = {"question": long_question}
        response = client.post("/api/qa/ask", json=request_data)
        assert response.status_code in [400, 422]
        data = response.json()
        if response.status_code == 400:
            assert "Question length out of range" in data["detail"]
        else:
            assert (
                "question length can not exceed 2000 characters"
                in data["detail"][0]["msg"]
            )

    def test_ask_question_max_sources_too_small(self):
        request_data = {"question": "测试问题", "max_sources": 0}
        response = client.post("/api/qa/ask", json=request_data)

        assert response.status_code == 422
        data = response.json()
        assert any("max_sources" in str(item.get("loc", "")) for item in data["detail"])

    def test_ask_question_max_sources_too_large(self):
        request_data = {"question": "测试问题", "max_sources": 6}
        response = client.post("/api/qa/ask", json=request_data)

        assert response.status_code == 422
        data = response.json()
        assert any("max_sources" in str(item.get("loc", "")) for item in data["detail"])

    def test_search_documents_max_sources_too_large(self):
        request_data = {"question": "测试查询", "max_sources": 6}
        response = client.post("/api/qa/search", json=request_data)

        assert response.status_code == 422
        data = response.json()
        assert any("max_sources" in str(item.get("loc", "")) for item in data["detail"])

    @patch("app.api.qa.vector_store")
    @patch("app.api.qa.qa_engine")
    def test_ask_question_default_max_sources(self, mock_qa_engine, mock_vector_store):
        mock_vector_store.get_collection_info.return_value = {"document_count": 1}

        from app.models.schemas import QuestionResponse

        mock_qa_engine.ask.return_value = QuestionResponse(
            answer="默认值测试", sources=[], processing_time=0.1
        )

        from app.core import config as config_module

        config_module.settings.enable_quota_limit = False

        response = client.post("/api/qa/ask", json={"question": "测试问题"})
        assert response.status_code == 200

    def test_search_documents_max_sources_too_small(self):
        request_data = {"question": "测试查询", "max_sources": 0}
        response = client.post("/api/qa/search", json=request_data)

        assert response.status_code == 422
        data = response.json()
        assert any("max_sources" in str(item.get("loc", "")) for item in data["detail"])

    @patch("app.api.qa.qa_engine")
    def test_search_documents(self, mock_qa_engine):
        """测试文档检索"""
        from langchain_core.documents import Document

        # 模拟检索结果
        mock_docs = [
            Document(
                page_content="相关内容1",
                metadata={
                    "filename": "test1.txt",
                    "document_id": "doc1",
                    "chunk_index": 0,
                },
            ),
            Document(
                page_content="相关内容2",
                metadata={
                    "filename": "test2.txt",
                    "document_id": "doc2",
                    "chunk_index": 1,
                },
            ),
        ]
        mock_qa_engine.get_relevant_documents.return_value = mock_docs

        request_data = {"question": "测试查询", "max_sources": 5}
        response = client.post("/api/qa/search", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 2
        assert data["total_found"] == 2

    @patch("app.api.qa.vector_store")
    def test_get_suggestions_no_documents(self, mock_vector_store):
        """测试获取问题建议 - 无文档"""
        mock_vector_store.get_collection_info.return_value = {"document_count": 0}

        response = client.get("/api/qa/suggestions")
        assert response.status_code == 200
        data = response.json()
        assert "请先上传一些文档" in data["suggestions"]

    @patch("app.api.qa.vector_store")
    def test_get_suggestions_with_documents(self, mock_vector_store):
        """测试获取问题建议 - 有文档"""
        mock_vector_store.get_collection_info.return_value = {"document_count": 5}

        response = client.get("/api/qa/suggestions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["suggestions"]) > 0
        assert data["document_count"] == 5

    def test_submit_feedback_valid(self):
        """测试提交有效反馈"""
        feedback_data = {
            "question": "测试问题",
            "answer": "测试答案",
            "rating": 4,
            "feedback": "很好的答案",
        }

        # 该端点参数为查询参数，使用 params 传参以满足 FastAPI 验证
        response = client.post("/api/qa/feedback", params=feedback_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_submit_feedback_invalid_rating(self):
        """测试提交无效评分"""
        feedback_data = {
            "question": "测试问题",
            "answer": "测试答案",
            "rating": 6,  # 无效评分
        }

        # 该端点参数为查询参数，使用 params 传参以满足 FastAPI 验证
        response = client.post("/api/qa/feedback", params=feedback_data)
        assert response.status_code == 400
        assert "Rating must be between 1 and 5" in response.json()["detail"]


class TestQAEngineRetrievalDecoupling:
    @staticmethod
    def _make_docs(count: int, document_id: str = "doc-1") -> list[Document]:
        return [
            Document(
                page_content=f"相关内容{i}",
                metadata={
                    "filename": f"test-{i}.txt",
                    "document_id": document_id,
                    "page": i,
                },
            )
            for i in range(count)
        ]

    @staticmethod
    def _make_cached_sources(count: int) -> list[dict]:
        return [
            SourceDocument(
                document_name=f"test-{i}.txt",
                content=f"相关内容{i}",
                similarity_score=1.0,
                page_number=i,
            ).model_dump()
            for i in range(count)
        ]

    @staticmethod
    def _build_engine(vector_store: MagicMock, source_docs: list[Document]) -> QAEngine:
        with patch.object(QAEngine, "_initialize_llm", return_value=None), patch.object(
            QAEngine, "_build_qa_chain", return_value=MagicMock()
        ):
            engine = QAEngine(vector_store)
        engine._effective_model_config = {
            "api_base_url": "https://api.openai.com/v1",
            "provider": "openai",
            "chat_model": "test-model",
        }
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = {
            "result": "测试答案",
            "source_documents": source_docs,
        }
        engine._build_qa_chain = MagicMock(return_value=mock_chain)
        return engine

    def test_qa_engine_global_mmr_params_ignore_user_max_sources(self):
        docs = self._make_docs(4, document_id="doc-global")
        vector_store = MagicMock()
        vector_store.similarity_search.return_value = docs
        vector_store.as_retriever.return_value = MagicMock()
        engine = self._build_engine(vector_store, docs)

        with patch(
            "app.core.qa_engine.cache_manager.get_context_hash", return_value="ctx"
        ), patch(
            "app.core.qa_engine.cache_manager.get_qa_cache", return_value=None
        ), patch(
            "app.core.qa_engine.cache_manager.set_qa_cache"
        ):
            response_one = engine.ask("测试问题", max_sources=1)
            first_call = vector_store.as_retriever.call_args
            vector_store.as_retriever.reset_mock()
            response_two = engine.ask("测试问题", max_sources=5)
            second_call = vector_store.as_retriever.call_args

        assert len(response_one.sources) == 1
        assert len(response_two.sources) == 4
        assert first_call == second_call
        assert first_call.kwargs == {
            "search_type": "mmr",
            "search_kwargs": {
                "k": settings.retrieval_k_global,
                "fetch_k": settings.retrieval_fetch_k_global,
                "lambda_mult": settings.retrieval_mmr_lambda_mult,
            },
        }

    def test_qa_engine_scoped_params_ignore_user_max_sources(self):
        restricted_docs = self._make_docs(3, document_id="doc-1")
        global_docs = self._make_docs(2, document_id="doc-2")
        restricted_scored = [(restricted_docs[0], 0.1), (restricted_docs[1], 0.2)]
        global_scored = [(global_docs[0], 0.35), (global_docs[1], 0.4)]
        vector_store = MagicMock()
        vector_store.similarity_search_with_score.side_effect = lambda **kwargs: (
            restricted_scored if kwargs.get("filter_dict") else global_scored
        )
        vector_store.as_retriever.return_value = MagicMock()
        engine = self._build_engine(vector_store, restricted_docs)

        with patch(
            "app.core.qa_engine.cache_manager.get_context_hash", return_value="ctx"
        ), patch(
            "app.core.qa_engine.cache_manager.get_qa_cache", return_value=None
        ), patch(
            "app.core.qa_engine.cache_manager.set_qa_cache"
        ):
            response_one = engine.ask("测试问题", max_sources=1, document_id="doc-1")
            first_call = vector_store.as_retriever.call_args
            vector_store.as_retriever.reset_mock()
            response_two = engine.ask("测试问题", max_sources=5, document_id="doc-1")
            second_call = vector_store.as_retriever.call_args

        assert len(response_one.sources) == 1
        assert len(response_two.sources) == 3
        assert first_call == second_call
        assert first_call.kwargs == {
            "search_kwargs": {
                "k": settings.retrieval_k_scoped,
                "filter": {"document_id": "doc-1"},
            }
        }
        assert vector_store.similarity_search_with_score.call_count == 4
        for call in vector_store.similarity_search_with_score.call_args_list:
            assert call.kwargs["k"] == settings.retrieval_precheck_k

    def test_qa_engine_cache_miss_truncates_visible_sources_only(self):
        docs = self._make_docs(4, document_id="doc-global")
        vector_store = MagicMock()
        vector_store.similarity_search.return_value = docs
        vector_store.as_retriever.return_value = MagicMock()
        engine = self._build_engine(vector_store, docs)

        with patch(
            "app.core.qa_engine.cache_manager.get_context_hash", return_value="ctx"
        ), patch(
            "app.core.qa_engine.cache_manager.get_qa_cache", return_value=None
        ), patch(
            "app.core.qa_engine.cache_manager.set_qa_cache"
        ) as mock_set_cache:
            response = engine.ask("测试问题", max_sources=2)

        cached_sources = mock_set_cache.call_args.args[3]
        assert response.from_cache is False
        assert len(response.sources) == 2
        assert len(cached_sources) == 4

    def test_qa_engine_cache_hit_truncates_visible_sources(self):
        docs = self._make_docs(4, document_id="doc-global")
        cached_sources = self._make_cached_sources(4)
        vector_store = MagicMock()
        vector_store.similarity_search.return_value = docs
        engine = self._build_engine(vector_store, docs)

        with patch(
            "app.core.qa_engine.cache_manager.get_context_hash", return_value="ctx"
        ), patch(
            "app.core.qa_engine.cache_manager.get_qa_cache",
            return_value={"answer": "缓存答案", "sources": cached_sources},
        ), patch(
            "app.core.qa_engine.cache_manager.set_qa_cache"
        ) as mock_set_cache:
            response = engine.ask("测试问题", max_sources=2)

        assert response.from_cache is True
        assert len(response.sources) == 2
        vector_store.as_retriever.assert_not_called()
        mock_set_cache.assert_not_called()


class TestAPIIntegration:
    """集成测试"""

    @patch("app.api.documents.doc_processor")
    @patch("app.api.documents.vector_store")
    @patch("app.api.qa.qa_engine")
    def test_full_workflow(self, mock_qa_engine, mock_vector_store, mock_processor):
        """测试完整工作流程：上传文档 -> 问答"""
        # 1. 模拟文档上传
        mock_processor.validate_filename.return_value = "test.txt"
        mock_processor.is_supported_file.return_value = True
        mock_processor.compute_content_hash.return_value = "hash-1"
        mock_processor.save_uploaded_file.return_value = "/path/to/file.txt"
        mock_processor.get_document_info.return_value = {
            "file_type": ".txt",
            "file_size": 1024,
        }

        # 返回同步处理完成的结果，避免接口返回失败
        mock_processor.process_document.return_value = {
            "status": "completed",
            "chunks": [],
            "chunk_count": 1,
            "document_id": "doc-123",
        }
        # 避免重复文件冲突
        # ensure QA endpoint sees existing documents
        from app.api import qa as qa_module

        qa_module.vector_store = MagicMock()
        qa_module.vector_store.get_collection_info.return_value = {"document_count": 1}

        mock_vector_store.document_exists_by_content_hash.return_value = False
        mock_vector_store.add_documents.return_value = True

        files = {"file": ("test.txt", b"test content", "text/plain")}
        upload_response = client.post(
            "/api/documents/upload", files=files, headers=_admin_headers()
        )
        assert upload_response.status_code == 200

        # disable quota limit for this integration test
        from app.core import config as config_module

        config_module.settings.enable_quota_limit = False

        # 2. 模拟问答
        mock_vector_store.get_collection_info.return_value = {"document_count": 1}

        from app.models.schemas import QuestionResponse, SourceDocument

        mock_response = QuestionResponse(
            answer="基于文档的答案",
            sources=[
                SourceDocument(
                    document_name="test.txt", content="相关内容", similarity_score=0.8
                )
            ],
            processing_time=1.0,
        )
        mock_qa_engine.ask.return_value = mock_response

        qa_request = {"question": "关于文档的问题"}
        qa_response = client.post("/api/qa/ask", json=qa_request)
        assert qa_response.status_code == 200

        qa_data = qa_response.json()
        assert "基于文档的答案" in qa_data["answer"]
        assert len(qa_data["sources"]) > 0
