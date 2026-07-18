"""
成本优化和监控API
"""

import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_admin
from app.core.cache_manager import cache_manager
from app.core.vector_store import VectorStore
from app.models.schemas import ApiResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cost-optimization"], dependencies=[Depends(require_admin)])


@router.get("/cache/stats", response_model=Dict[str, Any])
async def get_cache_stats():
    """获取缓存统计信息"""
    try:
        stats = cache_manager.get_cache_stats()

        # 计算节省的成本估算
        total_requests = (
            stats["embedding_cache"]["entries"] + stats["qa_cache"]["entries"]
        )
        cache_hits = (
            stats["embedding_cache"]["total_hits"] + stats["qa_cache"]["total_hits"]
        )

        # 简单的成本估算 (假设每次embedding调用$0.0001, 每次LLM调用$0.001)
        embedding_savings = stats["embedding_cache"]["total_hits"] * 0.0001
        qa_savings = stats["qa_cache"]["total_hits"] * 0.001
        total_savings = embedding_savings + qa_savings

        stats["cost_savings"] = {
            "embedding_savings_usd": round(embedding_savings, 4),
            "qa_savings_usd": round(qa_savings, 4),
            "total_savings_usd": round(total_savings, 4),
            "total_requests": total_requests,
            "total_cache_hits": cache_hits,
        }

        return stats
    except Exception as e:
        logger.error(f"Error getting cache stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embedding/stats", response_model=Dict[str, Any])
async def get_embedding_stats():
    """获取嵌入模型的缓存统计"""
    try:
        vector_store = VectorStore()
        if (
            hasattr(vector_store.embeddings, "get_cache_stats")
            and vector_store.embeddings is not None
        ):
            stats = vector_store.embeddings.get_cache_stats()
            return {
                "success": True,
                "embedding_stats": stats,
                "message": f"Cache hit rate: {stats['cache_hit_rate']}%",
            }
        else:
            return {"success": False, "message": "Embedding cache stats not available"}
    except Exception as e:
        logger.error(f"Error getting embedding stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/cleanup", response_model=ApiResponse)
async def cleanup_expired_cache():
    """清理过期的缓存"""
    try:
        cache_manager.cleanup_expired_cache()
        return ApiResponse(
            success=True, message="Expired cache entries cleaned up successfully"
        )
    except Exception as e:
        logger.error(f"Error cleaning up cache: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimization/recommendations", response_model=Dict[str, Any])
async def get_optimization_recommendations():
    """获取成本优化建议"""
    try:
        cache_stats = cache_manager.get_cache_stats()

        recommendations = []

        # 分析缓存使用情况
        embedding_hit_rate = 0
        qa_hit_rate = 0

        if cache_stats["embedding_cache"]["entries"] > 0:
            embedding_hit_rate = (
                cache_stats["embedding_cache"]["total_hits"]
                / cache_stats["embedding_cache"]["entries"]
            )

        if cache_stats["qa_cache"]["entries"] > 0:
            qa_hit_rate = (
                cache_stats["qa_cache"]["total_hits"]
                / cache_stats["qa_cache"]["entries"]
            )

        # 根据统计数据提供建议
        if embedding_hit_rate < 1.5:
            recommendations.append(
                {
                    "type": "embedding_cache",
                    "priority": "high",
                    "title": "嵌入缓存使用率较低",
                    "description": "考虑增加缓存过期时间或优化文档分块策略",
                    "current_hit_rate": round(embedding_hit_rate, 2),
                }
            )

        if qa_hit_rate < 2.0:
            recommendations.append(
                {
                    "type": "qa_cache",
                    "priority": "medium",
                    "title": "问答缓存效果一般",
                    "description": "用户问题重复率较低，考虑增加FAQ或相似问题匹配",
                    "current_hit_rate": round(qa_hit_rate, 2),
                }
            )

        if len(recommendations) == 0:
            recommendations.append(
                {
                    "type": "general",
                    "priority": "low",
                    "title": "缓存运行良好",
                    "description": "当前缓存策略运行良好，继续保持",
                }
            )

        return {
            "recommendations": recommendations,
            "cache_summary": cache_stats,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting optimization recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
