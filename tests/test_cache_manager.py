"""
Cache Manager 模块单元测试
"""

import json
import os
import pathlib
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from app.core.cache_manager import CacheManager


@pytest.fixture
def temp_db_path(tmp_path: pathlib.Path):
    """为 TestCacheManagerIntegration 提供模块级 temp_db_path（不依赖类内同名夹具）"""
    return str(tmp_path / "cache_test.db")


class TestCacheManager:
    """Cache Manager 测试类"""

    @pytest.fixture
    def temp_db_path(self):
        """创建临时数据库路径"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
            temp_path = temp_file.name
        yield temp_path
        # 清理临时文件
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def cache_manager(self, temp_db_path):
        """创建Cache Manager实例"""
        with patch("app.core.cache_manager.settings") as mock_settings:
            mock_settings.chroma_db_path = os.path.dirname(temp_db_path)
            return CacheManager(temp_db_path)

    def test_initialization_creates_database(self, temp_db_path):
        """测试初始化创建数据库"""
        cache_manager = CacheManager(temp_db_path)

        # 验证数据库文件存在
        assert os.path.exists(temp_db_path)

        # 验证表结构
        with sqlite3.connect(temp_db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            assert "embedding_cache" in tables
            assert "qa_cache" in tables

    def test_initialization_creates_indexes(self, temp_db_path):
        """测试初始化创建索引"""
        CacheManager(temp_db_path)

        with sqlite3.connect(temp_db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = [row[0] for row in cursor.fetchall()]

            assert any("idx_embedding_model" in idx for idx in indexes)
            assert any("idx_qa_model" in idx for idx in indexes)
            assert any("idx_embedding_access" in idx for idx in indexes)
            assert any("idx_qa_access" in idx for idx in indexes)

    def test_get_text_hash(self, cache_manager):
        """测试文本哈希生成"""
        text = "这是测试文本"
        model = "test-model"

        hash1 = cache_manager._get_text_hash(text, model)
        hash2 = cache_manager._get_text_hash(text, model)

        # 相同输入应该产生相同哈希
        assert hash1 == hash2
        assert len(hash1) == 32  # MD5哈希长度

        # 不同输入应该产生不同哈希
        hash3 = cache_manager._get_text_hash("不同文本", model)
        assert hash1 != hash3

    def test_set_and_get_embedding_cache(self, cache_manager):
        """测试设置和获取嵌入缓存"""
        text = "测试嵌入文本"
        embedding = [0.1, 0.2, 0.3] * 256  # 768维向量
        model_name = "test-model"

        # 设置缓存
        cache_manager.set_embedding_cache(text, embedding, model_name)

        # 获取缓存
        cached_embedding = cache_manager.get_embedding_cache(text, model_name)

        assert cached_embedding == embedding

    def test_get_embedding_cache_miss(self, cache_manager):
        """测试嵌入缓存未命中"""
        result = cache_manager.get_embedding_cache("不存在的文本", "test-model")
        assert result is None

    def test_get_embedding_cache_different_model(self, cache_manager):
        """测试不同模型的嵌入缓存隔离"""
        text = "相同文本"
        embedding1 = [0.1, 0.2, 0.3] * 256
        embedding2 = [0.4, 0.5, 0.6] * 256

        # 为不同模型设置缓存
        cache_manager.set_embedding_cache(text, embedding1, "model1")
        cache_manager.set_embedding_cache(text, embedding2, "model2")

        # 验证缓存隔离
        assert cache_manager.get_embedding_cache(text, "model1") == embedding1
        assert cache_manager.get_embedding_cache(text, "model2") == embedding2

    def test_embedding_cache_access_count_update(self, cache_manager):
        """测试嵌入缓存访问计数更新"""
        text = "测试文本"
        embedding = [0.1] * 768
        model_name = "test-model"

        # 设置缓存
        cache_manager.set_embedding_cache(text, embedding, model_name)

        # 多次访问
        for _ in range(3):
            cache_manager.get_embedding_cache(text, model_name)

        # 验证访问计数
        with sqlite3.connect(cache_manager.cache_db_path) as conn:
            cursor = conn.execute(
                """
                SELECT access_count FROM embedding_cache
                WHERE text_hash = ? AND model_name = ?
            """,
                (cache_manager._get_text_hash(text, model_name), model_name),
            )

            result = cursor.fetchone()
            assert result[0] == 4  # 1次初始设置 + 3次访问

    def test_embedding_cache_text_truncation(self, cache_manager):
        """测试嵌入缓存文本截断"""
        long_text = "很长的文本" * 100  # 超过500字符
        embedding = [0.1] * 768
        model_name = "test-model"

        cache_manager.set_embedding_cache(long_text, embedding, model_name)

        # 验证存储的文本被截断
        with sqlite3.connect(cache_manager.cache_db_path) as conn:
            cursor = conn.execute(
                """
                SELECT text_content FROM embedding_cache
                WHERE text_hash = ?
            """,
                (cache_manager._get_text_hash(long_text, model_name),),
            )

            result = cursor.fetchone()
            assert len(result[0]) <= 500

    def test_set_and_get_qa_cache(self, cache_manager):
        """测试设置和获取问答缓存"""
        question = "这是测试问题"
        context_hash = "test_context_hash"
        answer = "这是测试答案"
        sources = [
            {
                "document_name": "test.txt",
                "content": "测试内容",
                "similarity_score": 0.9,
            }
        ]
        model_name = "test-model"

        # 设置缓存
        cache_manager.set_qa_cache(question, context_hash, answer, sources, model_name)

        # 获取缓存
        cached_result = cache_manager.get_qa_cache(question, context_hash, model_name)

        assert cached_result["answer"] == answer
        assert cached_result["sources"] == sources

    def test_get_qa_cache_miss(self, cache_manager):
        """测试问答缓存未命中"""
        result = cache_manager.get_qa_cache(
            "不存在的问题", "不存在的上下文", "test-model"
        )
        assert result is None

    def test_qa_cache_different_context(self, cache_manager):
        """测试不同上下文的问答缓存隔离"""
        question = "相同问题"
        answer1 = "基于上下文1的答案"
        answer2 = "基于上下文2的答案"
        sources1 = [{"document_name": "doc1.txt"}]
        sources2 = [{"document_name": "doc2.txt"}]
        model_name = "test-model"

        # 为不同上下文设置缓存
        cache_manager.set_qa_cache(question, "context1", answer1, sources1, model_name)
        cache_manager.set_qa_cache(question, "context2", answer2, sources2, model_name)

        # 验证缓存隔离
        result1 = cache_manager.get_qa_cache(question, "context1", model_name)
        result2 = cache_manager.get_qa_cache(question, "context2", model_name)

        assert result1["answer"] == answer1
        assert result2["answer"] == answer2

    def test_qa_cache_access_count_update(self, cache_manager):
        """测试问答缓存访问计数更新"""
        question = "测试问题"
        context_hash = "test_context"
        answer = "测试答案"
        sources = []
        model_name = "test-model"

        # 设置缓存
        cache_manager.set_qa_cache(question, context_hash, answer, sources, model_name)

        # 多次访问
        for _ in range(2):
            cache_manager.get_qa_cache(question, context_hash, model_name)

        # 验证访问计数
        with sqlite3.connect(cache_manager.cache_db_path) as conn:
            cursor = conn.execute(
                """
                SELECT access_count FROM qa_cache
                WHERE question_hash = ?
            """,
                (
                    cache_manager._get_text_hash(
                        f"{question}:{context_hash}", model_name
                    ),
                ),
            )

            result = cursor.fetchone()
            assert result[0] == 3  # 1次初始设置 + 2次访问

    def test_qa_cache_question_truncation(self, cache_manager):
        """测试问答缓存问题截断"""
        long_question = "很长的问题" * 50  # 超过300字符
        context_hash = "test_context"
        answer = "答案"
        sources = []
        model_name = "test-model"

        cache_manager.set_qa_cache(
            long_question, context_hash, answer, sources, model_name
        )

        # 验证存储的问题被截断
        with sqlite3.connect(cache_manager.cache_db_path) as conn:
            cursor = conn.execute(
                """
                SELECT question FROM qa_cache
                WHERE question_hash = ?
            """,
                (
                    cache_manager._get_text_hash(
                        f"{long_question}:{context_hash}", model_name
                    ),
                ),
            )

            result = cursor.fetchone()
            assert len(result[0]) <= 300

    def test_get_context_hash_with_documents(self, cache_manager):
        """测试文档上下文哈希生成"""
        documents = [
            Document(
                page_content="这是第一个文档的内容" * 10,
                metadata={"filename": "doc1.txt"},
            ),
            Document(
                page_content="这是第二个文档的内容" * 10,
                metadata={"filename": "doc2.txt"},
            ),
        ]

        hash1 = cache_manager.get_context_hash(documents)
        hash2 = cache_manager.get_context_hash(documents)

        # 相同文档应该产生相同哈希
        assert hash1 == hash2
        assert len(hash1) == 32  # MD5哈希长度

        # 不同顺序的文档应该产生相同哈希（已排序）
        reversed_docs = list(reversed(documents))
        hash3 = cache_manager.get_context_hash(reversed_docs)
        assert hash1 == hash3

    def test_get_context_hash_with_strings(self, cache_manager):
        """测试字符串上下文哈希生成"""
        texts = ["文本1" * 50, "文本2" * 50]

        hash1 = cache_manager.get_context_hash(texts)

        assert isinstance(hash1, str)
        assert len(hash1) == 32

    def test_get_context_hash_empty_list(self, cache_manager):
        """测试空文档列表的上下文哈希"""
        hash_result = cache_manager.get_context_hash([])

        assert isinstance(hash_result, str)
        assert len(hash_result) == 32

    def test_cleanup_expired_cache(self, cache_manager):
        """测试清理过期缓存"""
        # 设置一些缓存项
        cache_manager.set_embedding_cache("文本1", [0.1] * 768, "model1")
        cache_manager.set_qa_cache("问题1", "context1", "答案1", [], "model1")

        # 模拟时间过去，使缓存过期
        past_time = (
            datetime.now() - timedelta(days=8)
        ).isoformat()  # 8天前（超过7天TTL）

        with sqlite3.connect(cache_manager.cache_db_path) as conn:
            # 更新创建时间为过期时间
            conn.execute("UPDATE embedding_cache SET created_at = ?", (past_time,))
            conn.execute("UPDATE qa_cache SET created_at = ?", (past_time,))
            conn.commit()

        # 清理过期缓存
        cache_manager.cleanup_expired_cache()

        # 验证缓存被清理
        assert cache_manager.get_embedding_cache("文本1", "model1") is None
        assert cache_manager.get_qa_cache("问题1", "context1", "model1") is None

    def test_cleanup_expired_cache_keeps_valid(self, cache_manager):
        """测试清理过期缓存保留有效缓存"""
        # 设置缓存项
        cache_manager.set_embedding_cache("有效文本", [0.1] * 768, "model1")
        cache_manager.set_qa_cache("有效问题", "context1", "有效答案", [], "model1")

        # 清理过期缓存
        cache_manager.cleanup_expired_cache()

        # 验证有效缓存仍然存在
        assert cache_manager.get_embedding_cache("有效文本", "model1") is not None
        assert cache_manager.get_qa_cache("有效问题", "context1", "model1") is not None

    def test_get_cache_stats_empty_cache(self, cache_manager):
        """测试空缓存的统计信息"""
        stats = cache_manager.get_cache_stats()

        assert stats["embedding_cache"]["entries"] == 0
        assert stats["embedding_cache"]["total_hits"] == 0
        assert stats["embedding_cache"]["avg_hits"] == 0
        assert stats["embedding_cache"]["last_access"] is None

        assert stats["qa_cache"]["entries"] == 0
        assert stats["qa_cache"]["total_hits"] == 0
        assert stats["qa_cache"]["avg_hits"] == 0
        assert stats["qa_cache"]["last_access"] is None

    def test_get_cache_stats_with_data(self, cache_manager):
        """测试有数据的缓存统计"""
        # 添加一些嵌入缓存
        cache_manager.set_embedding_cache("文本1", [0.1] * 768, "model1")
        cache_manager.set_embedding_cache("文本2", [0.2] * 768, "model1")

        # 添加一些问答缓存
        cache_manager.set_qa_cache("问题1", "context1", "答案1", [], "model1")

        # 访问一些缓存以增加命中计数
        cache_manager.get_embedding_cache("文本1", "model1")
        cache_manager.get_embedding_cache("文本1", "model1")  # 再次访问
        cache_manager.get_qa_cache("问题1", "context1", "model1")

        stats = cache_manager.get_cache_stats()

        # 验证嵌入缓存统计
        assert stats["embedding_cache"]["entries"] == 2
        assert stats["embedding_cache"]["total_hits"] == 4  # 2次设置 + 2次访问
        assert stats["embedding_cache"]["avg_hits"] == 2.0

        # 验证问答缓存统计
        assert stats["qa_cache"]["entries"] == 1
        assert stats["qa_cache"]["total_hits"] == 2  # 1次设置 + 1次访问
        assert stats["qa_cache"]["avg_hits"] == 2.0

    def test_cache_ttl_expiration(self, cache_manager):
        """测试缓存TTL过期"""
        # 修改TTL为很短的时间以便测试
        cache_manager.embedding_cache_ttl = 1  # 1秒
        cache_manager.qa_cache_ttl = 1  # 1秒

        # 设置缓存
        cache_manager.set_embedding_cache("测试文本", [0.1] * 768, "model1")
        cache_manager.set_qa_cache("测试问题", "context1", "测试答案", [], "model1")

        # 验证缓存存在
        assert cache_manager.get_embedding_cache("测试文本", "model1") is not None
        assert cache_manager.get_qa_cache("测试问题", "context1", "model1") is not None

        # 等待过期（在实际测试中可以通过修改数据库中的时间戳来模拟）
        import time

        time.sleep(2)

        # 由于SQLite查询中使用的是相对时间，我们需要验证过期逻辑
        # 这里我们直接测试清理功能
        cache_manager.cleanup_expired_cache()

        # 验证过期缓存被清理（在实际实现中，get方法应该检查过期时间）
        # 注意：当前的get_embedding_cache实现使用SQL查询来检查过期时间

    def test_invalid_json_in_cache_handling(self, cache_manager):
        """测试缓存中无效JSON的处理"""
        text_hash = cache_manager._get_text_hash("测试文本", "model1")

        # 手动插入无效JSON到数据库
        with sqlite3.connect(cache_manager.cache_db_path) as conn:
            conn.execute(
                """
                INSERT INTO embedding_cache
                (text_hash, text_content, embedding, model_name, created_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    text_hash,
                    "测试文本",
                    "无效JSON",
                    "model1",
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

        # 尝试获取缓存，应该返回None而不是抛出异常
        result = cache_manager.get_embedding_cache("测试文本", "model1")
        assert result is None


class TestCacheManagerIntegration:
    """Cache Manager 集成测试"""

    def test_complete_caching_workflow(self, temp_db_path):
        """测试完整的缓存工作流程"""
        cache_manager = CacheManager(temp_db_path)

        # 1. 设置嵌入缓存
        texts = ["文档1", "文档2", "文档3"]
        embeddings = [[i * 0.1] * 768 for i in range(1, 4)]
        model_name = "test-model"

        for text, embedding in zip(texts, embeddings):
            cache_manager.set_embedding_cache(text, embedding, model_name)

        # 2. 设置问答缓存
        questions = ["问题1", "问题2"]
        contexts = ["context1", "context2"]
        answers = ["答案1", "答案2"]

        for q, c, a in zip(questions, contexts, answers):
            cache_manager.set_qa_cache(q, c, a, [], model_name)

        # 3. 访问缓存
        for text in texts:
            retrieved = cache_manager.get_embedding_cache(text, model_name)
            expected = embeddings[texts.index(text)]
            assert retrieved == expected

        for q, c in zip(questions, contexts):
            result = cache_manager.get_qa_cache(q, c, model_name)
            expected_answer = answers[questions.index(q)]
            assert result is not None
            assert result["answer"] == expected_answer

        # 4. 检查统计信息
        stats = cache_manager.get_cache_stats()

        assert stats["embedding_cache"]["entries"] == 3
        assert stats["qa_cache"]["entries"] == 2
        assert stats["embedding_cache"]["total_hits"] == 6  # 3设置 + 3访问
        assert stats["qa_cache"]["total_hits"] == 4  # 2设置 + 2访问

        # 5. 清理过期缓存（应该不删除任何内容）
        cache_manager.cleanup_expired_cache()

        final_stats = cache_manager.get_cache_stats()
        assert final_stats["embedding_cache"]["entries"] == 3
        assert final_stats["qa_cache"]["entries"] == 2

    def test_concurrent_access_simulation(self, temp_db_path):
        """测试模拟并发访问"""
        cache_manager = CacheManager(temp_db_path)

        # 模拟多个"线程"设置和访问缓存
        base_text = "并发测试文本"
        base_embedding = [0.1] * 768

        # 设置多个相似的缓存项
        for i in range(10):
            text = f"{base_text}{i}"
            embedding = [0.1 + i * 0.01] * 768
            cache_manager.set_embedding_cache(text, embedding, f"model{i % 3}")

        # 访问所有缓存项
        for i in range(10):
            text = f"{base_text}{i}"
            model = f"model{i % 3}"
            result = cache_manager.get_embedding_cache(text, model)
            expected = [0.1 + i * 0.01] * 768
            assert result == expected

        # 验证统计信息
        stats = cache_manager.get_cache_stats()
        assert stats["embedding_cache"]["entries"] == 10
        assert stats["embedding_cache"]["total_hits"] == 20  # 10设置 + 10访问

    def test_large_data_handling(self, temp_db_path):
        """测试大数据处理"""
        cache_manager = CacheManager(temp_db_path)

        # 测试大向量
        large_embedding = [0.1] * 1536  # 更大的向量维度
        cache_manager.set_embedding_cache("大向量测试", large_embedding, "large-model")

        retrieved = cache_manager.get_embedding_cache("大向量测试", "large-model")
        assert retrieved == large_embedding

        # 测试大量源文档的问答缓存
        large_sources = [
            {"document_name": f"doc{i}.txt", "content": f"内容{i}" * 100}
            for i in range(50)
        ]

        cache_manager.set_qa_cache(
            "大源文档问题", "context", "答案", large_sources, "large-model"
        )

        result = cache_manager.get_qa_cache("大源文档问题", "context", "large-model")
        assert result is not None, "QA cache result should not be None"
        assert result["sources"] == large_sources

    @patch("app.core.cache_manager.settings")
    def test_default_initialization_with_settings(self, mock_settings, temp_db_path):
        """测试使用默认设置初始化"""
        mock_settings.chroma_db_path = os.path.dirname(temp_db_path)

        # 不提供cache_db_path参数，应该使用默认路径
        cache_manager = CacheManager()

        # 验证数据库被创建
        expected_path = os.path.join(os.path.dirname(temp_db_path), "cache.db")
        assert os.path.exists(expected_path)

        # 清理
        if os.path.exists(expected_path):
            os.unlink(expected_path)
