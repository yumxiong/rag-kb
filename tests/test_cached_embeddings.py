"""
Cached Embeddings 模块单元测试
"""

from unittest.mock import Mock, patch

import pytest

from app.core.cached_embeddings import CachedEmbeddings


class TestCachedEmbeddings:
    """Cached Embeddings 测试类"""

    @pytest.fixture
    def mock_base_embeddings(self):
        """模拟基础嵌入模型"""
        embeddings = Mock()
        embeddings.embed_query.return_value = [0.1, 0.2, 0.3] * 256  # 768维向量
        embeddings.embed_documents.return_value = [
            [0.1, 0.2, 0.3] * 256,  # 文档1的向量
            [0.4, 0.5, 0.6] * 256,  # 文档2的向量
        ]
        return embeddings

    @pytest.fixture
    def mock_cache_manager(self):
        """模拟缓存管理器"""
        cache_manager = Mock()
        cache_manager.get_embedding_cache.return_value = None  # 默认缓存未命中
        cache_manager.set_embedding_cache.return_value = None
        return cache_manager

    @pytest.fixture
    def cached_embeddings(self, mock_base_embeddings, mock_cache_manager):
        """创建CachedEmbeddings实例"""
        with patch("app.core.cached_embeddings.cache_manager", mock_cache_manager):
            ce = CachedEmbeddings(mock_base_embeddings, "test-model")
            yield ce

    def test_initialization(self, mock_base_embeddings):
        """测试初始化"""
        cached_emb = CachedEmbeddings(mock_base_embeddings, "test-model")

        assert cached_emb.base_embeddings == mock_base_embeddings
        assert cached_emb.model_name == "test-model"
        assert cached_emb.cache_hits == 0
        assert cached_emb.api_calls == 0

    def test_embed_query_cache_miss(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试查询嵌入缓存未命中"""
        test_text = "这是测试文本"
        expected_embedding = [0.1, 0.2, 0.3] * 256

        # 模拟缓存未命中
        mock_cache_manager.get_embedding_cache.return_value = None

        result = cached_embeddings.embed_query(test_text)

        assert result == expected_embedding
        assert cached_embeddings.api_calls == 1
        assert cached_embeddings.cache_hits == 0

        # 验证缓存管理器被正确调用
        mock_cache_manager.get_embedding_cache.assert_called_once_with(
            test_text, "test-model"
        )
        mock_cache_manager.set_embedding_cache.assert_called_once_with(
            test_text, expected_embedding, "test-model"
        )

        # 验证基础嵌入模型被调用
        mock_base_embeddings.embed_query.assert_called_once_with(test_text)

    def test_embed_query_cache_hit(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试查询嵌入缓存命中"""
        test_text = "这是测试文本"
        cached_embedding = [0.7, 0.8, 0.9] * 256

        # 模拟缓存命中
        mock_cache_manager.get_embedding_cache.return_value = cached_embedding

        result = cached_embeddings.embed_query(test_text)

        assert result == cached_embedding
        assert cached_embeddings.api_calls == 0
        assert cached_embeddings.cache_hits == 1

        # 验证基础嵌入模型未被调用
        mock_base_embeddings.embed_query.assert_not_called()

        # 验证缓存未被设置（因为是缓存命中）
        mock_cache_manager.set_embedding_cache.assert_not_called()

    def test_embed_documents_all_cache_miss(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试文档嵌入全部缓存未命中"""
        test_texts = ["文档1", "文档2"]
        expected_embeddings = [[0.1, 0.2, 0.3] * 256, [0.4, 0.5, 0.6] * 256]

        # 模拟全部缓存未命中
        mock_cache_manager.get_embedding_cache.return_value = None

        results = cached_embeddings.embed_documents(test_texts)

        assert results == expected_embeddings
        assert cached_embeddings.api_calls == 2
        assert cached_embeddings.cache_hits == 0

        # 验证缓存查询被调用2次
        assert mock_cache_manager.get_embedding_cache.call_count == 2

        # 验证缓存设置被调用2次
        assert mock_cache_manager.set_embedding_cache.call_count == 2

        # 验证基础嵌入模型被调用
        mock_base_embeddings.embed_documents.assert_called_once_with(test_texts)

    def test_embed_documents_all_cache_hit(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试文档嵌入全部缓存命中"""
        test_texts = ["文档1", "文档2"]
        cached_embeddings_list = [[0.7, 0.8, 0.9] * 256, [1.0, 1.1, 1.2] * 256]

        # 模拟全部缓存命中
        mock_cache_manager.get_embedding_cache.side_effect = cached_embeddings_list

        results = cached_embeddings.embed_documents(test_texts)

        assert results == cached_embeddings_list
        assert cached_embeddings.api_calls == 0
        assert cached_embeddings.cache_hits == 2

        # 验证基础嵌入模型未被调用
        mock_base_embeddings.embed_documents.assert_not_called()

        # 验证缓存未被设置
        mock_cache_manager.set_embedding_cache.assert_not_called()

    def test_embed_documents_partial_cache_hit(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试文档嵌入部分缓存命中"""
        test_texts = ["文档1", "文档2", "文档3"]
        cached_embedding = [0.7, 0.8, 0.9] * 256
        new_embeddings = [
            [0.4, 0.5, 0.6] * 256,  # 文档2的新嵌入
            [1.0, 1.1, 1.2] * 256,  # 文档3的新嵌入
        ]

        # 模拟部分缓存命中：文档1命中，文档2和文档3未命中
        mock_cache_manager.get_embedding_cache.side_effect = [
            cached_embedding,  # 文档1缓存命中
            None,  # 文档2缓存未命中
            None,  # 文档3缓存未命中
        ]

        # 模拟基础嵌入模型只处理未缓存的文档
        mock_base_embeddings.embed_documents.return_value = new_embeddings

        results = cached_embeddings.embed_documents(test_texts)

        expected_results = [
            cached_embedding,  # 文档1来自缓存
            new_embeddings[0],  # 文档2来自API
            new_embeddings[1],  # 文档3来自API
        ]

        assert results == expected_results
        assert cached_embeddings.api_calls == 2  # 只有2个文档需要API调用
        assert cached_embeddings.cache_hits == 1  # 只有1个文档缓存命中

        # 验证基础嵌入模型只处理未缓存的文档
        mock_base_embeddings.embed_documents.assert_called_once_with(["文档2", "文档3"])

        # 验证只有新生成的嵌入被缓存
        assert mock_cache_manager.set_embedding_cache.call_count == 2

    def test_embed_documents_empty_list(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试空文档列表"""
        results = cached_embeddings.embed_documents([])

        assert results == []
        assert cached_embeddings.api_calls == 0
        assert cached_embeddings.cache_hits == 0

        # 验证缓存管理器和基础嵌入模型都未被调用
        mock_cache_manager.get_embedding_cache.assert_not_called()
        mock_cache_manager.set_embedding_cache.assert_not_called()
        mock_base_embeddings.embed_documents.assert_not_called()

    def test_embed_documents_single_document(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试单个文档嵌入"""
        test_texts = ["单个文档"]
        expected_embedding = [[0.1, 0.2, 0.3] * 256]

        mock_cache_manager.get_embedding_cache.return_value = None
        mock_base_embeddings.embed_documents.return_value = expected_embedding

        results = cached_embeddings.embed_documents(test_texts)

        assert results == expected_embedding
        assert cached_embeddings.api_calls == 1
        assert cached_embeddings.cache_hits == 0

    def test_get_cache_stats_initial(self, cached_embeddings):
        """测试初始缓存统计"""
        stats = cached_embeddings.get_cache_stats()

        assert stats["cache_hits"] == 0
        assert stats["api_calls"] == 0
        assert stats["total_requests"] == 0
        assert stats["cache_hit_rate"] == 0

    def test_get_cache_stats_with_activity(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试有活动后的缓存统计"""
        # 模拟一些活动：2次缓存命中，3次API调用
        cached_embeddings.cache_hits = 2
        cached_embeddings.api_calls = 3

        stats = cached_embeddings.get_cache_stats()

        assert stats["cache_hits"] == 2
        assert stats["api_calls"] == 3
        assert stats["total_requests"] == 5
        assert stats["cache_hit_rate"] == 40.0  # 2/5 * 100

    def test_get_cache_stats_perfect_cache(self, cached_embeddings):
        """测试100%缓存命中率统计"""
        cached_embeddings.cache_hits = 10
        cached_embeddings.api_calls = 0

        stats = cached_embeddings.get_cache_stats()

        assert stats["cache_hit_rate"] == 100.0

    def test_get_cache_stats_no_cache(self, cached_embeddings):
        """测试0%缓存命中率统计"""
        cached_embeddings.cache_hits = 0
        cached_embeddings.api_calls = 5

        stats = cached_embeddings.get_cache_stats()

        assert stats["cache_hit_rate"] == 0.0

    def test_multiple_operations_stats(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试多次操作后的统计"""
        # 第1次查询：缓存未命中
        mock_cache_manager.get_embedding_cache.return_value = None
        cached_embeddings.embed_query("查询1")

        # 第2次查询：缓存命中
        cached_embedding = [0.7, 0.8, 0.9] * 256
        mock_cache_manager.get_embedding_cache.return_value = cached_embedding
        cached_embeddings.embed_query("查询2")

        # 第3次文档嵌入：部分缓存命中
        mock_cache_manager.get_embedding_cache.side_effect = [None, cached_embedding]
        mock_base_embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3] * 256]
        cached_embeddings.embed_documents(["文档1", "文档2"])

        stats = cached_embeddings.get_cache_stats()

        # 总计：2次缓存命中（查询2 + 文档2），2次API调用（查询1 + 文档1）
        assert stats["cache_hits"] == 2
        assert stats["api_calls"] == 2
        assert stats["total_requests"] == 4
        assert stats["cache_hit_rate"] == 50.0  # 2/4 * 100

    def test_embed_query_with_api_error(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试API调用失败的错误处理"""
        mock_cache_manager.get_embedding_cache.return_value = None
        mock_base_embeddings.embed_query.side_effect = Exception("API调用失败")

        with pytest.raises(Exception, match="API调用失败"):
            cached_embeddings.embed_query("测试文本")

        # 失败时不计入API调用计数
        assert cached_embeddings.api_calls == 0
        assert cached_embeddings.cache_hits == 0

    def test_embed_documents_with_api_error(
        self, cached_embeddings, mock_cache_manager, mock_base_embeddings
    ):
        """测试批量嵌入时API调用失败"""
        mock_cache_manager.get_embedding_cache.return_value = None
        mock_base_embeddings.embed_documents.side_effect = Exception("批量API调用失败")

        with pytest.raises(Exception, match="批量API调用失败"):
            cached_embeddings.embed_documents(["文档1", "文档2"])

        # 失败时不计入API调用计数
        assert cached_embeddings.api_calls == 0
        assert cached_embeddings.cache_hits == 0


class TestCachedEmbeddingsIntegration:
    """Cached Embeddings 集成测试"""

    @patch("app.core.cached_embeddings.cache_manager")
    def test_realistic_caching_scenario(self, mock_cache_manager):
        """测试真实的缓存场景"""
        # 创建基础嵌入模型
        base_embeddings = Mock()
        base_embeddings.embed_query.side_effect = [
            [0.1, 0.2, 0.3] * 256,  # 第1次查询
            [0.4, 0.5, 0.6] * 256,  # 第3次查询（第2次来自缓存）
        ]
        base_embeddings.embed_documents.return_value = [
            [0.7, 0.8, 0.9] * 256,
            [1.0, 1.1, 1.2] * 256,
        ]

        cached_embeddings = CachedEmbeddings(base_embeddings, "integration-test-model")

        # 模拟缓存行为
        cache_storage = {}

        def mock_get_cache(text, model):
            key = f"{text}:{model}"
            return cache_storage.get(key)

        def mock_set_cache(text, embedding, model):
            key = f"{text}:{model}"
            cache_storage[key] = embedding

        mock_cache_manager.get_embedding_cache.side_effect = mock_get_cache
        mock_cache_manager.set_embedding_cache.side_effect = mock_set_cache

        # 第1次查询 - 缓存未命中
        result1 = cached_embeddings.embed_query("重复查询")
        assert len(result1) == 768
        assert cached_embeddings.api_calls == 1
        assert cached_embeddings.cache_hits == 0

        # 第2次相同查询 - 缓存命中
        result2 = cached_embeddings.embed_query("重复查询")
        assert result2 == result1  # 应该返回相同的结果
        assert cached_embeddings.api_calls == 1  # API调用次数不变
        assert cached_embeddings.cache_hits == 1

        # 第3次不同查询 - 缓存未命中
        result3 = cached_embeddings.embed_query("新查询")
        assert result3 != result1
        assert cached_embeddings.api_calls == 2
        assert cached_embeddings.cache_hits == 1

        # 批量文档嵌入 - 全部缓存未命中
        doc_results = cached_embeddings.embed_documents(["文档A", "文档B"])
        assert len(doc_results) == 2
        assert cached_embeddings.api_calls == 4  # 增加了2次
        assert cached_embeddings.cache_hits == 1

        # 重复批量文档嵌入 - 全部缓存命中
        doc_results2 = cached_embeddings.embed_documents(["文档A", "文档B"])
        assert doc_results2 == doc_results
        assert cached_embeddings.api_calls == 4  # 不变
        assert cached_embeddings.cache_hits == 3  # 增加了2次

        # 验证最终统计
        final_stats = cached_embeddings.get_cache_stats()
        assert final_stats["cache_hits"] == 3
        assert final_stats["api_calls"] == 4
        assert final_stats["total_requests"] == 7
        assert final_stats["cache_hit_rate"] == round(3 / 7 * 100, 2)

    def test_performance_with_large_batch(self):
        """测试大批量文档的性能"""
        # 创建模拟的基础嵌入模型
        base_embeddings = Mock()
        base_embeddings.embed_documents.return_value = [[0.1] * 768] * 100

        with patch("app.core.cached_embeddings.cache_manager") as mock_cache_manager:
            # 模拟50%缓存命中率
            cache_responses = [
                ([0.1] * 768) if i % 2 == 0 else None for i in range(100)
            ]
            mock_cache_manager.get_embedding_cache.side_effect = cache_responses

            cached_embeddings = CachedEmbeddings(base_embeddings, "perf-test-model")

            # 处理100个文档
            test_docs = [f"文档{i}" for i in range(100)]
            results = cached_embeddings.embed_documents(test_docs)

            assert len(results) == 100
            assert cached_embeddings.cache_hits == 50  # 50%命中率
            assert cached_embeddings.api_calls == 50  # 50个文档需要API调用

            # 验证基础嵌入模型只处理未缓存的文档
            base_embeddings.embed_documents.assert_called_once()
            called_docs = base_embeddings.embed_documents.call_args[0][0]
            assert len(called_docs) == 50
