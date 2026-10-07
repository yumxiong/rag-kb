"""
带缓存的嵌入模型包装器
"""

import logging
from typing import List

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.core.cache_manager import cache_manager
from app.core.deadline import current_deadline
from app.core.global_budget import (
    record_provider_attempt,
    require_document_provider_access,
    require_query_context,
)

logger = logging.getLogger(__name__)


class CachedEmbeddings(Embeddings):
    """带缓存的嵌入模型包装器"""

    def __init__(self, base_embeddings: Embeddings, model_name: str):
        self.base_embeddings = base_embeddings
        self.model_name = model_name
        self.cache_hits = 0
        self.api_calls = 0

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """嵌入文档列表（支持批量缓存）"""
        embeddings = []
        texts_to_embed = []
        indices_to_embed = []

        # 检查缓存
        for i, text in enumerate(texts):
            cached_embedding = cache_manager.get_embedding_cache(text, self.model_name)
            if cached_embedding is not None:
                embeddings.append(cached_embedding)
                self.cache_hits += 1
                logger.debug(f"Cache hit for document {i+1}/{len(texts)}")
            else:
                embeddings.append(None)  # 占位符
                texts_to_embed.append(text)
                indices_to_embed.append(i)

        # 批量获取未缓存的嵌入
        if texts_to_embed:
            require_document_provider_access()
            logger.info(
                f"Generating embeddings for {len(texts_to_embed)}/{len(texts)} texts"
            )
            new_embeddings = self.base_embeddings.embed_documents(texts_to_embed)
            self.api_calls += len(texts_to_embed)

            # 更新结果和缓存
            for idx, embedding in zip(indices_to_embed, new_embeddings):
                embeddings[idx] = embedding
                cache_manager.set_embedding_cache(
                    texts[idx], embedding, self.model_name
                )

        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """嵌入单个查询"""
        require_query_context()
        deadline = current_deadline()
        if deadline is not None:
            deadline.check()
        # 检查缓存
        cached_embedding = cache_manager.get_embedding_cache(text, self.model_name)
        if cached_embedding is not None:
            self.cache_hits += 1
            logger.debug("Cache hit for query embedding")
            return cached_embedding

        # 生成新的嵌入
        logger.debug("Generating new embedding for query")
        record_provider_attempt("query_embedding")
        provider = self.base_embeddings
        if deadline is not None:
            timeout = deadline.provider_timeout("embedding")
            if isinstance(provider, OpenAIEmbeddings):
                root_client = provider.client._client
                client = root_client.with_options(timeout=timeout)
                provider = provider.model_copy(update={"client": client.embeddings})
        started_at = deadline.clock() if deadline is not None else None
        embedding = provider.embed_query(text)
        if deadline is not None:
            deadline.check_provider_elapsed(started_at, "embedding")
        self.api_calls += 1

        # 缓存结果
        cache_manager.set_embedding_cache(text, embedding, self.model_name)

        return embedding

    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        total_requests = self.cache_hits + self.api_calls
        cache_hit_rate = (
            (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        )

        return {
            "cache_hits": self.cache_hits,
            "api_calls": self.api_calls,
            "total_requests": total_requests,
            "cache_hit_rate": round(cache_hit_rate, 2),
        }
