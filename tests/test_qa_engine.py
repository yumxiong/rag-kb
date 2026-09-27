"""
QA Engine 模块单元测试
"""

from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from app.core.qa_engine import QAEngine
from app.models.schemas import QuestionResponse, SourceDocument


class TestQAEngine:
    """QA Engine 测试类"""

    @pytest.fixture
    def mock_vector_store(self):
        """模拟向量存储"""
        vector_store = Mock()
        vector_store.as_retriever.return_value = Mock()
        vector_store.similarity_search.return_value = [
            Document(
                page_content="这是测试内容1",
                metadata={
                    "filename": "test1.txt",
                    "document_id": "doc1",
                    "chunk_index": 0,
                },
            ),
            Document(
                page_content="这是测试内容2",
                metadata={
                    "filename": "test2.txt",
                    "document_id": "doc2",
                    "chunk_index": 1,
                },
            ),
        ]
        vector_store.health_check.return_value = {"status": "healthy"}
        vector_store.get_collection_info.return_value = {"document_count": 5}
        return vector_store

    @pytest.fixture
    def qa_engine(self, mock_vector_store):
        """创建QA Engine实例（使用 yield 确保补丁在整个用例期间有效）"""

        # 模拟LLM初始化
        with patch("app.core.qa_engine.settings") as mock_settings, patch(
            "app.core.qa_engine.ChatOpenAI"
        ) as mock_chat_openai, patch(
            "app.core.qa_engine.RetrievalQA"
        ) as mock_retrieval_qa:

            mock_llm = Mock()
            mock_llm.predict.return_value = "Test response"
            mock_chat_openai.return_value = mock_llm

            mock_qa_chain = Mock()
            mock_retrieval_qa.from_chain_type.return_value = mock_qa_chain

            # 模拟设置（放在 with 块内以使用 mock_settings）
            mock_settings.get_api_key.return_value = "test-api-key"
            mock_settings.max_sources = 3
            mock_settings.retrieval_k_global = 6
            mock_settings.get_model_config.return_value = {
                "provider": "openai",
                "chat_model": "gpt-3.5-turbo",
                "api_base_url": "https://api.openai.com/v1",
            }

            engine = QAEngine(mock_vector_store)
            engine.qa_chain = mock_qa_chain
            yield engine

    def test_initialize_llm_success(self, mock_vector_store):
        """测试LLM初始化成功"""
        with patch("app.core.qa_engine.settings") as mock_settings, patch(
            "app.core.qa_engine.ChatOpenAI"
        ) as mock_chat_openai:

            mock_settings.get_api_key.return_value = "test-key"
            mock_settings.get_model_config.return_value = {
                "provider": "openai",
                "chat_model": "gpt-3.5-turbo",
                "api_base_url": "https://api.openai.com/v1",
            }

            mock_llm = Mock()
            mock_chat_openai.return_value = mock_llm

            with patch("app.core.qa_engine.RetrievalQA"):
                engine = QAEngine(mock_vector_store)
                assert engine.llm == mock_llm

    def test_initialize_llm_no_api_key(self, mock_vector_store):
        """测试没有API key时的错误处理"""
        with patch("app.core.qa_engine.settings") as mock_settings:
            mock_settings.get_api_key.return_value = None
            mock_settings.llm_provider = "openai"

            with pytest.raises(ValueError, match="API key not configured"):
                QAEngine(mock_vector_store)

    def test_initialize_llm_with_custom_base_url(self, mock_vector_store):
        """测试自定义API端点初始化"""
        with patch("app.core.qa_engine.settings") as mock_settings, patch(
            "app.core.qa_engine.ChatOpenAI"
        ) as mock_chat_openai:

            mock_settings.get_api_key.return_value = "test-key"
            mock_settings.get_model_config.return_value = {
                "provider": "deepseek",
                "chat_model": "deepseek-chat",
                "api_base_url": "https://api.deepseek.com/v1",
            }

            with patch("app.core.qa_engine.RetrievalQA"):
                QAEngine(mock_vector_store)

                # 验证ChatOpenAI被正确调用
                mock_chat_openai.assert_called_once()
                call_kwargs = mock_chat_openai.call_args[1]
                assert call_kwargs["base_url"] == "https://api.deepseek.com/v1"
                assert call_kwargs["organization"] == ""

    @patch("app.core.qa_engine.cache_manager")
    def test_ask_with_cache_hit(self, mock_cache_manager, qa_engine):
        """测试缓存命中的情况"""
        # 模拟缓存命中
        mock_cache_manager.get_context_hash.return_value = "test_hash"
        mock_cache_manager.get_qa_cache.return_value = {
            "answer": "缓存的答案",
            "sources": [
                {
                    "document_name": "test.txt",
                    "content": "内容",
                    "similarity_score": 0.9,
                }
            ],
        }

        response = qa_engine.ask("测试问题")

        assert isinstance(response, QuestionResponse)
        assert response.answer == "缓存的答案"
        assert response.from_cache is True
        assert len(response.sources) == 1

    @patch("app.core.qa_engine.cache_manager")
    def test_ask_with_cache_miss(self, mock_cache_manager, qa_engine):
        """测试缓存未命中的情况"""
        # 模拟缓存未命中
        mock_cache_manager.get_context_hash.return_value = "test_hash"
        mock_cache_manager.get_qa_cache.return_value = None

        # 模拟QA chain响应（invoke 返回字典）
        qa_engine.qa_chain.invoke.return_value = {
            "result": "新的答案",
            "source_documents": [
                Document(
                    page_content="测试内容",
                    metadata={"filename": "test.txt", "document_id": "doc1"},
                )
            ],
        }

        response = qa_engine.ask("测试问题")

        assert isinstance(response, QuestionResponse)
        assert response.answer == "新的答案"
        assert response.from_cache is False
        assert len(response.sources) == 1

        # 验证结果被缓存
        mock_cache_manager.set_qa_cache.assert_called_once()

    def test_ask_empty_question(self, qa_engine):
        """测试空问题"""
        response = qa_engine.ask("  ")

        assert isinstance(response, QuestionResponse)
        assert (
            "问题不能为空" in response.answer
            or "Question cannot be empty" in response.answer
        )
        assert len(response.sources) == 0

    def test_ask_with_error(self, qa_engine):
        """测试处理过程中发生错误"""
        # 模拟QA chain抛出异常
        qa_engine.qa_chain.side_effect = Exception("测试错误")

        with patch("app.core.qa_engine.cache_manager") as mock_cache_manager:
            mock_cache_manager.get_context_hash.return_value = "test_hash"
            mock_cache_manager.get_qa_cache.return_value = None

            response = qa_engine.ask("测试问题")

            assert isinstance(response, QuestionResponse)
            assert "错误" in response.answer
            assert len(response.sources) == 0

    def test_get_relevant_documents(self, qa_engine, mock_vector_store):
        """测试获取相关文档"""
        docs = qa_engine.get_relevant_documents("测试查询", k=5)

        assert len(docs) == 2
        assert all(isinstance(doc, Document) for doc in docs)
        mock_vector_store.similarity_search.assert_called_once_with(
            query="测试查询", k=5, filter_dict=None
        )

    def test_get_relevant_documents_with_error(self, qa_engine, mock_vector_store):
        """测试获取相关文档时发生错误"""
        mock_vector_store.similarity_search.side_effect = Exception("搜索错误")

        docs = qa_engine.get_relevant_documents("测试查询")

        assert docs == []

    def test_process_source_documents(self, qa_engine):
        """测试处理源文档"""
        source_docs = [
            Document(
                page_content="这是一个很长的测试内容" * 50 + "关键证据在末尾",
                metadata={"filename": "test1.txt", "page": 1},
            ),
            Document(page_content="短内容", metadata={"filename": "test2.txt"}),
        ]

        sources = qa_engine._process_source_documents(source_docs)

        assert len(sources) == 2
        assert all(isinstance(src, SourceDocument) for src in sources)

        # 引用必须保留完整分块，不能丢失末尾证据。
        assert sources[0].content == source_docs[0].page_content

        # 验证短内容未被截断
        assert sources[1].content == "短内容"

    def test_process_source_documents_with_invalid_doc(self, qa_engine):
        """测试处理包含无效文档的源文档列表"""
        source_docs = [
            Document(page_content="正常内容", metadata={"filename": "test.txt"}),
            None,  # 无效文档
            Document(page_content="", metadata={}),  # 空内容文档
        ]

        # 过滤掉None值
        valid_docs = [doc for doc in source_docs if doc is not None]
        sources = qa_engine._process_source_documents(valid_docs)

        assert len(sources) == 2

    def test_health_check_healthy(self, qa_engine, mock_vector_store):
        """测试健康检查 - 健康状态"""
        qa_engine.llm.predict.return_value = "Hello response"

        health = qa_engine.health_check(deep=True)

        assert health["status"] == "healthy"
        assert health["llm"] == "connected"
        assert health["vector_store"] == "healthy"
        assert "collection_info" in health

    def test_health_check_unhealthy(self, qa_engine, mock_vector_store):
        """测试健康检查 - 不健康状态"""
        qa_engine.llm.predict.side_effect = Exception("连接失败")

        health = qa_engine.health_check(deep=True)

        assert health["status"] == "unhealthy"
        assert "error" in health

    def test_health_check_with_qa_test(self, qa_engine, mock_vector_store):
        """测试健康检查包含QA测试"""
        qa_engine.llm.predict.return_value = "Hello response"

        # 模拟有文档的情况
        mock_vector_store.get_collection_info.return_value = {"document_count": 10}

        # 模拟ask方法成功
        with patch.object(qa_engine, "ask") as mock_ask:
            mock_ask.return_value = QuestionResponse(
                answer="测试回答", sources=[], processing_time=0.1
            )

            health = qa_engine.health_check(deep=True, with_qa=True)

            assert health["qa_chain"] == "working"

    def test_health_check_qa_test_failed(self, qa_engine, mock_vector_store):
        """测试健康检查QA测试失败"""
        qa_engine.llm.predict.return_value = "Hello response"
        mock_vector_store.get_collection_info.return_value = {"document_count": 10}

        # 模拟ask方法失败
        with patch.object(qa_engine, "ask") as mock_ask:
            mock_ask.side_effect = Exception("QA测试失败")

            health = qa_engine.health_check(deep=True, with_qa=True)

            assert health["qa_chain"] == "failed"

    def test_get_conversation_context_empty(self, qa_engine):
        """测试空对话历史"""
        context = qa_engine.get_conversation_context([])
        assert context == ""

    def test_get_conversation_context_with_history(self, qa_engine):
        """测试包含对话历史的上下文构建"""
        history = [
            {"question": "问题1", "answer": "答案1"},
            {"question": "问题2", "answer": "答案2"},
            {"question": "问题3", "answer": "答案3"},
            {"question": "问题4", "answer": "答案4"},  # 应该被截断
        ]

        context = qa_engine.get_conversation_context(history)

        # 应该只保留最近3轮对话
        lines = context.split("\n")
        assert len(lines) == 6  # 3轮对话 * 2行 (Q + A)
        assert "问题2" in context
        assert "问题3" in context
        assert "问题4" in context
        assert "问题1" not in context  # 被截断

    def test_get_conversation_context_incomplete_history(self, qa_engine):
        """测试包含不完整对话的历史"""
        history = [
            {"question": "问题1"},  # 缺少答案
            {"answer": "答案2"},  # 缺少问题
            {"question": "问题3", "answer": "答案3"},  # 完整的对话
        ]

        context = qa_engine.get_conversation_context(history)

        # 只有完整的对话应该被包含
        assert "问题3" in context
        assert "答案3" in context
        assert "问题1" not in context
        assert "答案2" not in context


class TestQAEngineIntegration:
    """QA Engine 集成测试"""

    @patch("app.core.qa_engine.settings")
    @patch("app.core.qa_engine.ChatOpenAI")
    @patch("app.core.qa_engine.RetrievalQA")
    def test_full_qa_workflow(self, mock_retrieval_qa, mock_chat_openai, mock_settings):
        """测试完整的问答工作流程"""
        # 模拟设置
        mock_settings.get_api_key.return_value = "test-key"
        mock_settings.max_sources = 3
        mock_settings.retrieval_k_global = 6
        mock_settings.get_model_config.return_value = {
            "provider": "openai",
            "chat_model": "gpt-3.5-turbo",
            "api_base_url": "https://api.openai.com/v1",
        }

        # 模拟向量存储
        mock_vector_store = Mock()
        mock_vector_store.as_retriever.return_value = Mock()
        mock_vector_store.similarity_search.return_value = [
            Document(page_content="相关内容", metadata={"filename": "test.txt"})
        ]
        mock_vector_store.health_check.return_value = {"status": "healthy"}
        mock_vector_store.get_collection_info.return_value = {"document_count": 1}

        # 模拟LLM和QA chain
        mock_llm = Mock()
        mock_llm.predict.return_value = "Test response"
        mock_chat_openai.return_value = mock_llm

        mock_qa_chain = Mock()
        mock_qa_chain.invoke.return_value = {
            "result": "集成测试答案",
            "source_documents": [
                Document(page_content="源文档内容", metadata={"filename": "source.txt"})
            ],
        }
        mock_retrieval_qa.from_chain_type.return_value = mock_qa_chain

        # 模拟缓存管理器
        with patch("app.core.qa_engine.cache_manager") as mock_cache_manager:
            mock_cache_manager.get_context_hash.return_value = "test_hash"
            mock_cache_manager.get_qa_cache.return_value = None

            # 创建QA Engine并执行查询
            engine = QAEngine(mock_vector_store)
            response = engine.ask("集成测试问题")

            # 验证响应
            assert isinstance(response, QuestionResponse)
            assert response.answer == "集成测试答案"
            assert len(response.sources) == 1
            assert response.from_cache is False

            # 验证缓存被调用
            mock_cache_manager.set_qa_cache.assert_called_once()
