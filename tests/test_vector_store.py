"""
Vector Store 模块单元测试
"""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from app.core.vector_store import VectorStore


class TestVectorStore:
    """Vector Store 测试类"""

    @pytest.fixture
    def temp_db_path(self):
        """创建临时数据库路径"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield os.path.join(temp_dir, "test_chroma")

    @pytest.fixture
    def mock_settings(self, temp_db_path):
        """模拟设置（使用 yield 确保补丁在整个用例期间有效）"""
        with patch("app.core.vector_store.settings") as mock_settings_patch:
            mock_settings_patch.chroma_db_path = temp_db_path
            mock_settings_patch.get_embedding_api_key.return_value = (
                "test-embedding-key"
            )
            mock_settings_patch.embedding_provider = "openai"
            mock_settings_patch.get_model_config.return_value = {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-ada-002",
                "embedding_api_base_url": None,
            }
            mock_settings_patch.similarity_threshold = 0.7
            # 使用 yield 维持 patch 的生命周期覆盖整个测试
            yield mock_settings_patch

    @pytest.fixture
    def mock_embeddings(self):
        """模拟嵌入模型"""
        embeddings = Mock()
        embeddings.embed_query.return_value = [0.1, 0.2, 0.3] * 256  # 768维
        embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3] * 256] * 2
        return embeddings

    @pytest.fixture
    def vector_store_instance(self, mock_settings, mock_embeddings):
        """创建Vector Store实例"""
        # 重置单例
        VectorStore._instance = None

        with patch(
            "app.core.vector_store.OpenAIEmbeddings"
        ) as mock_openai_embeddings, patch(
            "app.core.vector_store.CachedEmbeddings"
        ) as mock_cached_embeddings, patch(
            "app.core.vector_store.Chroma"
        ) as mock_chroma:

            mock_openai_embeddings.return_value = mock_embeddings
            mock_cached_embeddings.return_value = mock_embeddings

            # 模拟Chroma vectorstore
            mock_vectorstore = Mock()
            mock_vectorstore._client = Mock()
            mock_chroma.return_value = mock_vectorstore

            vector_store = VectorStore()
            vector_store.vectorstore = mock_vectorstore
            vector_store.chroma_client = mock_vectorstore._client
            vector_store.embeddings = mock_embeddings
            vector_store._initialized = True

            return vector_store

    def test_singleton_pattern(self, mock_settings):
        """测试单例模式"""
        # 重置单例
        VectorStore._instance = None

        with patch("app.core.vector_store.OpenAIEmbeddings"), patch(
            "app.core.vector_store.CachedEmbeddings"
        ), patch("app.core.vector_store.Chroma"):

            instance1 = VectorStore()
            instance2 = VectorStore()

            assert instance1 is instance2

    def test_initialize_embeddings_success(self, mock_settings):
        """测试嵌入模型初始化成功"""
        VectorStore._instance = None

        with patch(
            "app.core.vector_store.OpenAIEmbeddings"
        ) as mock_openai_embeddings, patch(
            "app.core.vector_store.CachedEmbeddings"
        ) as mock_cached_embeddings, patch(
            "app.core.vector_store.Chroma"
        ):

            mock_base_embeddings = Mock()
            mock_openai_embeddings.return_value = mock_base_embeddings

            mock_cached = Mock()
            mock_cached_embeddings.return_value = mock_cached

            vector_store = VectorStore()
            vector_store._initialize_embeddings()

            # 验证OpenAIEmbeddings被正确调用
            mock_openai_embeddings.assert_called_once_with(
                api_key="test-embedding-key", model="text-embedding-ada-002"
            )

            # 验证CachedEmbeddings被创建（新实现包含 base URL 后缀）
            args, kwargs = mock_cached_embeddings.call_args
            assert kwargs["base_embeddings"] is mock_base_embeddings
            assert kwargs["model_name"].startswith("openai/text-embedding-ada-002@")

    def test_initialize_embeddings_no_api_key(self, mock_settings):
        """测试没有API key时的错误处理"""
        VectorStore._instance = None
        mock_settings.get_embedding_api_key.return_value = None
        mock_settings.embedding_provider = "openai"

        with patch("app.core.vector_store.Chroma"):
            vector_store = VectorStore()

            with pytest.raises(ValueError, match="API key not configured"):
                vector_store._initialize_embeddings()

    def test_initialize_embeddings_with_custom_base_url(self, mock_settings):
        """测试自定义API端点初始化"""
        VectorStore._instance = None
        mock_settings.get_model_config.return_value = {
            "embedding_provider": "deepseek",
            "embedding_model": "text-embedding-ada-002",
            "embedding_api_base_url": "https://api.deepseek.com/v1",
        }

        with patch(
            "app.core.vector_store.OpenAIEmbeddings"
        ) as mock_openai_embeddings, patch(
            "app.core.vector_store.CachedEmbeddings"
        ), patch(
            "app.core.vector_store.Chroma"
        ):

            vector_store = VectorStore()
            vector_store._initialize_embeddings()

            # 验证自定义端点被设置
            call_kwargs = mock_openai_embeddings.call_args[1]
            assert call_kwargs["base_url"] == "https://api.deepseek.com/v1"
            assert call_kwargs["organization"] == ""

    def test_initialize_vectorstore_success(self, mock_settings, temp_db_path):
        """测试向量存储初始化成功"""
        VectorStore._instance = None

        with patch("app.core.vector_store.Chroma") as mock_chroma:
            mock_vectorstore = Mock()
            mock_vectorstore._client = Mock()
            mock_chroma.return_value = mock_vectorstore

            vector_store = VectorStore()
            vector_store.embeddings = Mock()  # 设置embeddings
            vector_store._initialize_vectorstore()

            # 验证Chroma被正确初始化
            mock_chroma.assert_called_once()
            call_kwargs = mock_chroma.call_args[1]
            assert call_kwargs["collection_name"] == "rag_documents"
            assert call_kwargs["persist_directory"] == temp_db_path

    def test_get_chroma_returns_default_vectorstore(self, vector_store_instance):
        """默认集合应复用现有VectorStore。"""
        with patch.object(
            vector_store_instance, "_ensure_initialized"
        ) as mock_ensure_initialized:
            result = vector_store_instance.get_chroma(
                vector_store_instance.collection_name
            )

        assert result is vector_store_instance.vectorstore
        mock_ensure_initialized.assert_called_once_with()

    def test_get_chroma_creates_named_collection(self, vector_store_instance):
        """指定集合应复用当前embeddings和Chroma client。"""
        mock_eval_collection = Mock()

        with patch("app.core.vector_store.Chroma") as mock_chroma:
            mock_chroma.return_value = mock_eval_collection

            result = vector_store_instance.get_chroma("rag_eval_documents")

        assert result is mock_eval_collection
        mock_chroma.assert_called_once_with(
            collection_name="rag_eval_documents",
            embedding_function=vector_store_instance.embeddings,
            client=vector_store_instance.chroma_client,
        )

    def test_get_chroma_propagates_initialization_error(self, vector_store_instance):
        """初始化失败时不应掩盖原始异常。"""
        with patch.object(
            vector_store_instance,
            "_ensure_initialized",
            side_effect=RuntimeError("initialization failed"),
        ), patch("app.core.vector_store.Chroma") as mock_chroma:
            with pytest.raises(RuntimeError, match="initialization failed"):
                vector_store_instance.get_chroma("rag_eval_documents")

        mock_chroma.assert_not_called()

    def test_add_documents_success(self, vector_store_instance):
        """测试成功添加文档"""
        documents = [
            Document(
                page_content="测试内容1",
                metadata={"filename": "test1.txt", "document_id": "doc1"},
            ),
            Document(
                page_content="测试内容2",
                metadata={"filename": "test2.txt", "document_id": "doc2"},
            ),
        ]

        vector_store_instance.vectorstore.add_documents.return_value = None
        vector_store_instance.vectorstore.persist.return_value = None

        doc_ids = vector_store_instance.add_documents(documents)

        assert len(doc_ids) == 2
        assert all(isinstance(doc_id, str) for doc_id in doc_ids)

        # 验证每个文档都有chunk_id
        for doc in documents:
            assert "chunk_id" in doc.metadata
            assert isinstance(doc.metadata["chunk_id"], str)

        vector_store_instance.vectorstore.add_documents.assert_called_once()
        vector_store_instance.vectorstore.persist.assert_called_once()

    def test_add_documents_empty_list(self, vector_store_instance):
        """测试添加空文档列表"""
        doc_ids = vector_store_instance.add_documents([])
        assert doc_ids == []

    def test_add_documents_batch_failure_fallback(self, vector_store_instance):
        """测试批量添加失败时的回退机制"""
        documents = [
            Document(page_content="内容1", metadata={"filename": "test1.txt"}),
            Document(page_content="内容2", metadata={"filename": "test2.txt"}),
        ]

        # 模拟批量添加失败，但单个添加成功
        vector_store_instance.vectorstore.add_documents.side_effect = [
            Exception("批量添加失败"),  # 第一次调用失败
            None,
            None,  # 后续单个调用成功
        ]

        doc_ids = vector_store_instance.add_documents(documents)

        assert len(doc_ids) == 2
        # 验证总共调用了3次：1次批量失败 + 2次单个成功
        assert vector_store_instance.vectorstore.add_documents.call_count == 3

    def test_add_documents_complete_failure(self, vector_store_instance):
        """测试完全添加失败"""
        documents = [Document(page_content="内容1", metadata={"filename": "test1.txt"})]

        # 模拟所有添加都失败
        vector_store_instance.vectorstore.add_documents.side_effect = Exception(
            "添加失败"
        )

        with pytest.raises(Exception, match="Failed to add any documents"):
            vector_store_instance.add_documents(documents)

    def test_similarity_search_success(self, vector_store_instance):
        """测试相似度搜索成功"""
        mock_results = [
            Document(page_content="相关内容1", metadata={"filename": "test1.txt"}),
            Document(page_content="相关内容2", metadata={"filename": "test2.txt"}),
        ]
        vector_store_instance.vectorstore.similarity_search.return_value = mock_results

        results = vector_store_instance.similarity_search("查询文本", k=5)

        assert len(results) == 2
        assert all(isinstance(doc, Document) for doc in results)
        vector_store_instance.vectorstore.similarity_search.assert_called_once_with(
            query="查询文本", k=5, filter=None
        )

    def test_similarity_search_with_filter(self, vector_store_instance):
        """测试带过滤条件的相似度搜索"""
        filter_dict = {"filename": "test.txt"}
        vector_store_instance.vectorstore.similarity_search.return_value = []

        vector_store_instance.similarity_search(
            "查询文本", k=3, filter_dict=filter_dict
        )

        vector_store_instance.vectorstore.similarity_search.assert_called_once_with(
            query="查询文本", k=3, filter=filter_dict
        )

    def test_similarity_search_with_error(self, vector_store_instance):
        """测试相似度搜索错误处理"""
        vector_store_instance.vectorstore.similarity_search.side_effect = Exception(
            "搜索失败"
        )

        with pytest.raises(Exception, match="搜索失败"):
            vector_store_instance.similarity_search("查询文本")

    def test_similarity_search_with_score(self, vector_store_instance):
        """测试带分数的相似度搜索"""
        mock_results = [
            (
                Document(page_content="高相关内容", metadata={"filename": "test1.txt"}),
                0.9,
            ),
            (
                Document(page_content="低相关内容", metadata={"filename": "test2.txt"}),
                0.5,
            ),
        ]
        vector_store_instance.vectorstore.similarity_search_with_score.return_value = (
            mock_results
        )

        results = vector_store_instance.similarity_search_with_score("查询文本", k=5)

        # 仅保留距离（越小越好）小于等于阈值0.7的结果
        assert len(results) == 1
        assert results[0][1] == 0.5

    def test_delete_documents_by_metadata_success(self, vector_store_instance):
        """测试根据元数据删除文档成功"""
        # 模拟collection
        mock_collection = Mock()
        mock_collection.get.return_value = {"ids": ["id1", "id2"]}
        mock_collection.delete.return_value = None
        vector_store_instance.chroma_client.get_collection.return_value = (
            mock_collection
        )

        result = vector_store_instance.delete_documents_by_metadata(
            {"filename": "test.txt"}
        )

        assert result is True
        mock_collection.get.assert_called_once_with(where={"filename": "test.txt"})
        mock_collection.delete.assert_called_once_with(ids=["id1", "id2"])

    def test_delete_documents_by_metadata_not_found(self, vector_store_instance):
        """测试删除不存在的文档"""
        mock_collection = Mock()
        mock_collection.get.return_value = {"ids": []}
        vector_store_instance.chroma_client.get_collection.return_value = (
            mock_collection
        )

        result = vector_store_instance.delete_documents_by_metadata(
            {"filename": "nonexistent.txt"}
        )

        assert result is False

    def test_delete_documents_by_metadata_error(self, vector_store_instance):
        """测试删除文档时发生错误"""
        vector_store_instance.chroma_client.get_collection.side_effect = Exception(
            "删除错误"
        )

        with pytest.raises(Exception, match="删除错误"):
            vector_store_instance.delete_documents_by_metadata({"filename": "test.txt"})

    def test_delete_document_by_id(self, vector_store_instance):
        """测试根据文档ID删除"""
        with patch.object(
            vector_store_instance, "delete_documents_by_metadata"
        ) as mock_delete:
            mock_delete.return_value = True

            result = vector_store_instance.delete_document_by_id("doc123")

            assert result is True
            mock_delete.assert_called_once_with({"document_id": "doc123"})

    def test_get_collection_info_success(self, vector_store_instance):
        """测试获取集合信息成功"""
        # 避免使用 Mock 对象的 _collection（会被动态创建为 MagicMock）
        vector_store_instance.vectorstore._collection = None

        mock_collection = Mock()
        mock_collection.count.return_value = 100
        vector_store_instance.chroma_client.get_collection.return_value = (
            mock_collection
        )

        info = vector_store_instance.get_collection_info()

        assert info["collection_name"] == "rag_documents"
        assert info["document_count"] == 100
        assert "embedding_model" in info

    def test_get_collection_info_error(self, vector_store_instance):
        # 避免使用 Mock 对象的 _collection（会被动态创建为 MagicMock）
        vector_store_instance.vectorstore._collection = None

        """测试获取集合信息错误"""
        vector_store_instance.chroma_client.get_collection.side_effect = Exception(
            "获取信息失败"
        )

        info = vector_store_instance.get_collection_info()

        assert "error" in info

    def test_list_documents_success(self, vector_store_instance):
        """测试列出文档成功"""
        # 避免使用 Mock 对象的 _collection（会被动态创建为 MagicMock）
        vector_store_instance.vectorstore._collection = None

        mock_collection = Mock()
        mock_collection.get.return_value = {
            "metadatas": [
                {
                    "document_id": "doc1",
                    "filename": "test1.txt",
                    "processed_at": "2023-01-01",
                },
                {
                    "document_id": "doc1",
                    "filename": "test1.txt",
                    "processed_at": "2023-01-01",
                },  # 同一文档的另一chunk
                {
                    "document_id": "doc2",
                    "filename": "test2.txt",
                    "processed_at": "2023-01-02",
                },
            ]
        }
        vector_store_instance.chroma_client.get_collection.return_value = (
            mock_collection
        )

        documents = vector_store_instance.list_documents()

        assert len(documents) == 2  # 按document_id分组后应该只有2个文档

        doc1 = next(doc for doc in documents if doc["document_id"] == "doc1")
        assert doc1["filename"] == "test1.txt"
        assert doc1["chunk_count"] == 2

        doc2 = next(doc for doc in documents if doc["document_id"] == "doc2")
        assert doc2["filename"] == "test2.txt"
        assert doc2["chunk_count"] == 1

    def test_list_documents_empty(self, vector_store_instance):
        """测试列出空文档列表"""
        mock_collection = Mock()
        mock_collection.get.return_value = {"metadatas": []}
        vector_store_instance.chroma_client.get_collection.return_value = (
            mock_collection
        )

        documents = vector_store_instance.list_documents()

        assert documents == []

    def test_list_documents_error(self, vector_store_instance):
        """测试列出文档错误"""
        vector_store_instance.chroma_client.get_collection.side_effect = Exception(
            "列出失败"
        )

        documents = vector_store_instance.list_documents()

        assert documents == []

    def test_health_check_healthy(self, vector_store_instance):
        """测试健康检查成功"""
        # 模拟get_collection_info成功
        with patch.object(
            vector_store_instance, "get_collection_info"
        ) as mock_get_info:
            mock_get_info.return_value = {"document_count": 10}

            # 模拟embedding测试成功
            vector_store_instance.embeddings.embed_query.return_value = [0.1] * 768

            health = vector_store_instance.health_check()

            assert health["status"] == "healthy"
            assert health["vector_store"] == "connected"
            assert health["embedding_model"] == "working"
            assert health["embedding_dimension"] == 768
            assert health["collection_info"]["document_count"] == 10

    def test_health_check_unhealthy(self, vector_store_instance):
        """测试健康检查失败"""
        vector_store_instance.embeddings.embed_query.side_effect = Exception(
            "健康检查失败"
        )

        health = vector_store_instance.health_check()

        assert health["status"] == "unhealthy"
        assert "error" in health

    def test_as_retriever(self, vector_store_instance):
        """测试返回检索器接口"""
        mock_retriever = Mock()
        vector_store_instance.vectorstore.as_retriever.return_value = mock_retriever

        retriever = vector_store_instance.as_retriever(search_kwargs={"k": 5})

        assert retriever == mock_retriever
        vector_store_instance.vectorstore.as_retriever.assert_called_once_with(
            search_kwargs={"k": 5}
        )

    def test_ensure_initialized_lazy_loading(self, mock_settings):
        """测试延迟初始化"""
        VectorStore._instance = None

        with patch("app.core.vector_store.OpenAIEmbeddings"), patch(
            "app.core.vector_store.CachedEmbeddings"
        ), patch("app.core.vector_store.Chroma"):

            vector_store = VectorStore()
            assert not vector_store._initialized

            # 调用需要初始化的方法
            with patch.object(
                vector_store, "_initialize_embeddings"
            ) as mock_init_emb, patch.object(
                vector_store, "_initialize_vectorstore"
            ) as mock_init_vs:

                vector_store._ensure_initialized()

                mock_init_emb.assert_called_once()
                mock_init_vs.assert_called_once()
                assert vector_store._initialized is True


class TestVectorStoreIntegration:
    """Vector Store 集成测试"""

    def test_complete_document_workflow(self, tmp_path):
        """测试完整的文档工作流程"""
        VectorStore._instance = None

        with patch("app.core.vector_store.settings") as mock_settings, patch(
            "app.core.vector_store.OpenAIEmbeddings"
        ) as mock_openai_emb, patch(
            "app.core.vector_store.CachedEmbeddings"
        ) as mock_cached_emb, patch(
            "app.core.vector_store.Chroma"
        ) as mock_chroma:

            # 模拟设置
            mock_settings.chroma_db_path = str(tmp_path / "test_chroma")
            mock_settings.get_embedding_api_key.return_value = "test-key"
            mock_settings.get_model_config.return_value = {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-ada-002",
                "embedding_api_base_url": None,
            }
            mock_settings.similarity_threshold = 0.7

            # 模拟嵌入模型
            mock_embeddings = Mock()
            mock_embeddings.embed_query.return_value = [0.1] * 768
            mock_embeddings.embed_documents.return_value = [[0.1] * 768] * 2
            mock_openai_emb.return_value = mock_embeddings
            mock_cached_emb.return_value = mock_embeddings

            # 模拟向量存储
            mock_vectorstore = Mock()
            mock_vectorstore._client = Mock()
            mock_chroma.return_value = mock_vectorstore

            # 创建Vector Store
            vector_store = VectorStore()

            # 测试添加文档
            documents = [
                Document(page_content="测试文档1", metadata={"filename": "test1.txt"}),
                Document(page_content="测试文档2", metadata={"filename": "test2.txt"}),
            ]

            doc_ids = vector_store.add_documents(documents)
            assert len(doc_ids) == 2

            # 测试搜索文档
            mock_vectorstore.similarity_search.return_value = documents
            results = vector_store.similarity_search("测试查询")
            assert len(results) == 2

            # 测试删除文档
            mock_collection = Mock()
            mock_collection.get.return_value = {"ids": doc_ids}
            mock_vectorstore._client.get_collection.return_value = mock_collection

            delete_result = vector_store.delete_documents_by_metadata(
                {"filename": "test1.txt"}
            )
            assert delete_result is True
