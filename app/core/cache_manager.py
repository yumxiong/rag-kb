"""
智能缓存管理模块 - 减少API调用成本
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class CacheManager:
    """智能缓存管理器"""

    def __init__(self, cache_db_path: str = None):
        self.cache_db_path = cache_db_path or os.path.join(
            settings.chroma_db_path, "cache.db"
        )
        self.embedding_cache_ttl = 7 * 24 * 3600  # 7天
        self.qa_cache_ttl = 1 * 24 * 3600  # 1天
        self._init_db()

    def _init_db(self):
        """初始化缓存数据库"""
        os.makedirs(os.path.dirname(self.cache_db_path), exist_ok=True)

        with sqlite3.connect(self.cache_db_path) as conn:
            # 嵌入缓存表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    text_hash TEXT PRIMARY KEY,
                    text_content TEXT,
                    embedding BLOB,
                    model_name TEXT,
                    created_at TIMESTAMP,
                    last_accessed TIMESTAMP,
                    access_count INTEGER DEFAULT 1
                )
            """
            )

            # 问答缓存表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qa_cache (
                    question_hash TEXT PRIMARY KEY,
                    question TEXT,
                    context_hash TEXT,
                    answer TEXT,
                    sources TEXT,
                    model_name TEXT,
                    created_at TIMESTAMP,
                    last_accessed TIMESTAMP,
                    access_count INTEGER DEFAULT 1
                )
            """
            )

            # 创建索引提高查询性能
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_embedding_model ON embedding_cache(model_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_qa_model ON qa_cache(model_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_embedding_access ON embedding_cache(last_accessed)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_qa_access ON qa_cache(last_accessed)"
            )

            conn.commit()

    def _get_text_hash(self, text: str, model: str = "") -> str:
        """生成文本哈希"""
        content = f"{text}:{model}"
        return hashlib.md5(content.encode()).hexdigest()

    def get_embedding_cache(self, text: str, model_name: str) -> Optional[List[float]]:
        """获取嵌入缓存"""
        text_hash = self._get_text_hash(text, model_name)

        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute(
                """
                SELECT embedding FROM embedding_cache 
                WHERE text_hash = ? AND model_name = ? 
                AND datetime(created_at, '+{} seconds') > datetime('now')
            """.format(
                    self.embedding_cache_ttl
                ),
                (text_hash, model_name),
            )

            result = cursor.fetchone()
            if result:
                # 更新访问信息
                conn.execute(
                    """
                    UPDATE embedding_cache 
                    SET last_accessed = ?, access_count = access_count + 1
                    WHERE text_hash = ?
                """,
                    (datetime.now().isoformat(), text_hash),
                )
                conn.commit()

                # 反序列化embedding
                try:
                    embedding = json.loads(result[0])
                    logger.debug(f"Embedding cache hit for text hash: {text_hash[:8]}")
                    return embedding
                except:
                    pass

        return None

    def set_embedding_cache(self, text: str, embedding: List[float], model_name: str):
        """设置嵌入缓存"""
        text_hash = self._get_text_hash(text, model_name)

        # 限制缓存的文本长度避免存储过大内容
        cached_text = text[:500] if len(text) > 500 else text

        with sqlite3.connect(self.cache_db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO embedding_cache 
                (text_hash, text_content, embedding, model_name, created_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    text_hash,
                    cached_text,
                    json.dumps(embedding),
                    model_name,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

        logger.debug(f"Embedding cached for text hash: {text_hash[:8]}")

    def get_qa_cache(
        self, question: str, context_hash: str, model_name: str
    ) -> Optional[Dict[str, Any]]:
        """获取问答缓存"""
        question_hash = self._get_text_hash(f"{question}:{context_hash}", model_name)

        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute(
                """
                SELECT answer, sources FROM qa_cache 
                WHERE question_hash = ? AND model_name = ?
                AND datetime(created_at, '+{} seconds') > datetime('now')
            """.format(
                    self.qa_cache_ttl
                ),
                (question_hash, model_name),
            )

            result = cursor.fetchone()
            if result:
                # 更新访问信息
                conn.execute(
                    """
                    UPDATE qa_cache 
                    SET last_accessed = ?, access_count = access_count + 1
                    WHERE question_hash = ?
                """,
                    (datetime.now().isoformat(), question_hash),
                )
                conn.commit()

                try:
                    sources = json.loads(result[1]) if result[1] else []
                    logger.info(f"QA cache hit for question hash: {question_hash[:8]}")
                    return {"answer": result[0], "sources": sources}
                except:
                    pass

        return None

    def set_qa_cache(
        self,
        question: str,
        context_hash: str,
        answer: str,
        sources: List[Dict],
        model_name: str,
    ):
        """设置问答缓存"""
        question_hash = self._get_text_hash(f"{question}:{context_hash}", model_name)

        # 限制缓存的问题长度
        cached_question = question[:300] if len(question) > 300 else question

        with sqlite3.connect(self.cache_db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO qa_cache 
                (question_hash, question, context_hash, answer, sources, model_name, created_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    question_hash,
                    cached_question,
                    context_hash,
                    answer,
                    json.dumps(sources),
                    model_name,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

        logger.info(f"QA result cached for question hash: {question_hash[:8]}")

    def get_context_hash(self, documents: List[Any]) -> str:
        """生成上下文文档的哈希（包含文档身份信息）"""
        content_texts = []
        for doc in documents:
            if hasattr(doc, "page_content"):
                # 包含文档内容和元数据信息确保唯一性
                content_part = doc.page_content[:200]  # 只取前200字符

                # 添加文档身份信息到哈希中
                doc_id = ""
                filename = ""
                if hasattr(doc, "metadata") and doc.metadata:
                    doc_id = doc.metadata.get("document_id", "")
                    filename = doc.metadata.get("filename", "")

                # 组合内容和身份信息
                combined_content = f"{content_part}|{doc_id}|{filename}"
                content_texts.append(combined_content)
            elif isinstance(doc, str):
                content_texts.append(doc[:200])

        combined = "|".join(sorted(content_texts))
        return hashlib.md5(combined.encode()).hexdigest()

    def cleanup_expired_cache(self):
        """清理过期缓存"""
        with sqlite3.connect(self.cache_db_path) as conn:
            # 清理过期的嵌入缓存
            embedding_cutoff = datetime.now() - timedelta(
                seconds=self.embedding_cache_ttl
            )
            conn.execute(
                """
                DELETE FROM embedding_cache 
                WHERE datetime(created_at) < ?
            """,
                (embedding_cutoff.isoformat(),),
            )

            # 清理过期的问答缓存
            qa_cutoff = datetime.now() - timedelta(seconds=self.qa_cache_ttl)
            conn.execute(
                """
                DELETE FROM qa_cache 
                WHERE datetime(created_at) < ?
            """,
                (qa_cutoff.isoformat(),),
            )

            conn.commit()

        logger.info("Expired cache entries cleaned up")

    def clear_all_cache(self):
        """清空所有缓存"""
        with sqlite3.connect(self.cache_db_path) as conn:
            # 清空嵌入缓存
            embedding_count = conn.execute(
                "SELECT COUNT(*) FROM embedding_cache"
            ).fetchone()[0]
            conn.execute("DELETE FROM embedding_cache")

            # 清空问答缓存
            qa_count = conn.execute("SELECT COUNT(*) FROM qa_cache").fetchone()[0]
            conn.execute("DELETE FROM qa_cache")

            conn.commit()

        logger.info(
            f"All cache cleared: {embedding_count} embedding entries, {qa_count} QA entries"
        )
        return {"embedding_cleared": embedding_count, "qa_cleared": qa_count}

    def clear_qa_cache(self):
        """仅清空问答缓存"""
        with sqlite3.connect(self.cache_db_path) as conn:
            qa_count = conn.execute("SELECT COUNT(*) FROM qa_cache").fetchone()[0]
            conn.execute("DELETE FROM qa_cache")
            conn.commit()

        logger.info(f"QA cache cleared: {qa_count} entries")
        return {"qa_cleared": qa_count}

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with sqlite3.connect(self.cache_db_path) as conn:
            # 嵌入缓存统计
            embedding_cursor = conn.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(access_count) as total_hits,
                    AVG(access_count) as avg_hits,
                    MAX(last_accessed) as last_access
                FROM embedding_cache
            """
            )
            embedding_stats = embedding_cursor.fetchone()

            # 问答缓存统计
            qa_cursor = conn.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(access_count) as total_hits,
                    AVG(access_count) as avg_hits,
                    MAX(last_accessed) as last_access
                FROM qa_cache
            """
            )
            qa_stats = qa_cursor.fetchone()

            return {
                "embedding_cache": {
                    "entries": embedding_stats[0] or 0,
                    "total_hits": embedding_stats[1] or 0,
                    "avg_hits": round(embedding_stats[2] or 0, 2),
                    "last_access": embedding_stats[3],
                },
                "qa_cache": {
                    "entries": qa_stats[0] or 0,
                    "total_hits": qa_stats[1] or 0,
                    "avg_hits": round(qa_stats[2] or 0, 2),
                    "last_access": qa_stats[3],
                },
            }


# 全局缓存管理器实例
cache_manager = CacheManager()
