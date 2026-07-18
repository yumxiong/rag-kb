"""
问答API
"""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from langchain_openai import ChatOpenAI

from app.api.auth import require_admin
from app.core.config import settings
from app.core.qa_engine import QAEngine
from app.core.url_safety import is_safe_base_url
from app.core.vector_store import VectorStore
from app.models.schemas import QuestionRequest, QuestionResponse, SourceDocument

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局实例（延迟初始化）
vector_store = None
qa_engine = None


def get_vector_store():
    """获取向量存储实例（延迟初始化）"""
    global vector_store
    if vector_store is None:
        vector_store = VectorStore()
    return vector_store


def get_qa_engine():
    """获取QA引擎实例（延迟初始化）"""
    global qa_engine
    if qa_engine is None:
        qa_engine = QAEngine(get_vector_store())
    return qa_engine


def _extract_overrides_from_headers(request) -> dict:
    """从请求头提取按请求覆盖配置（BYOK）
    支持的请求头：
    - LLM-Api-Key： BYOK 专用头部
    - LLM-Provider: openai/deepseek/zhipu/openrouter/custom
    - LLM-Base-URL: 自定义兼容 OpenAI 的 API Base URL
    - LLM-Model: 聊天模型名称
    """
    overrides = {}
    try:
        api_key = request.headers.get("LLM-Api-Key")
        if api_key:
            overrides["api_key"] = api_key.strip()

        provider = request.headers.get("LLM-Provider")
        if provider:
            overrides["provider"] = (
                provider.strip()
                if provider.strip()
                in ["openai", "deepseek", "zhipu", "openrouter", "custom"]
                else "openai"
            )

        base_url = request.headers.get("LLM-Base-URL")
        if base_url:
            if not api_key:
                raise HTTPException(status_code=400, detail="需提供LLM-Api-Key")
            if not is_safe_base_url(base_url, settings.get_allowed_chat_base_urls()):
                raise HTTPException(status_code=400, detail="LLM-Base-URL 不安全")
            overrides["api_base_url"] = base_url

        model = request.headers.get("LLM-Model")
        if model:
            overrides["model"] = model
    except Exception:
        # 安全兜底：出现异常则返回当前累积的 overrides
        pass
    return overrides


@router.post("/ask", response_model=QuestionResponse)
async def ask_question(payload: QuestionRequest, request: Request):
    """智能问答接口"""
    try:
        if not payload.question.strip():
            raise HTTPException(status_code=400, detail="Question cannot be empty")

        # 问题长度验证
        from app.core.config import settings

        if (
            len(payload.question) < settings.min_question_length
            or len(payload.question) > settings.max_question_length
        ):
            raise HTTPException(status_code=400, detail="Question length out of range")

        # 检查是否有文档数据
        collection_info = get_vector_store().get_collection_info()
        if collection_info.get("document_count", 0) == 0:
            return QuestionResponse(
                answer="抱歉，知识库中暂时没有文档。请先上传一些文档后再提问。",
                sources=[],
                processing_time=0.0,
            )

        # 提取BYOK覆盖，并按需选择引擎
        overrides = _extract_overrides_from_headers(request)
        has_custom_key = bool(overrides.get("api_key"))

        # 配额检查（仅对未提供自定义API Key的用户）
        from app.core.config import settings

        if settings.enable_quota_limit:
            from app.core.quota_manager import get_quota_manager

            quota_manager = get_quota_manager()

            # 构建请求信息
            request_info = {
                "client_ip": request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("user-agent", ""),
            }

            # 检查配额
            can_use, quota_info = quota_manager.check_and_increment(
                request_info, has_custom_key
            )

            if not can_use:
                return QuestionResponse(
                    answer=(
                        f"🚫 **配额已用完**\n\n"
                        f"您今日的免费提问次数已达上限（{quota_info.daily_limit}次），明天将自动重置。\n\n"
                        f"💡 **解决方案**：\n"
                        f"1. 等待明天配额重置\n"
                        f'2. 在左侧"模型设置(BYOK)"中填写您的API Key，即可无限制使用\n\n'
                        f"📊 **当前使用情况**：{quota_info.used_count}/{quota_info.daily_limit}"
                    ),
                    sources=[],
                    processing_time=0.0,
                )

            # 在响应中添加配额信息（用于前端显示）
            remaining_quota = max(0, quota_info.daily_limit - quota_info.used_count)
            logger.info(
                f"User quota: {quota_info.used_count}/{quota_info.daily_limit}, remaining: {remaining_quota}"
            )

        engine = None
        if overrides.get("api_key"):
            # 用户提供了 Key，创建临时引擎（不影响全局实例与测试桩）
            engine = QAEngine(get_vector_store(), overrides=overrides)
        else:
            # 未提供 Key：若全局尚未初始化且也无默认 Key，则走 Demo 回退；
            # 若测试中已用 mock 注入了 qa_engine，则直接复用以保持单测稳定。
            if qa_engine is None and not settings.get_api_key():
                try:
                    k = payload.max_sources or settings.max_sources
                    fallback_note = ""

                    # 使用带分数检索进行判定（更稳健）
                    docs = []
                    if payload.document_id:
                        try:
                            restricted_scored = (
                                get_vector_store().similarity_search_with_score(
                                    query=payload.question,
                                    k=max(k, settings.max_sources * 2),
                                    filter_dict={"document_id": payload.document_id},
                                    threshold=settings.relevance_fallback_threshold,
                                )
                            )
                        except Exception as _e:
                            logger.warning(f"Demo scored restricted failed: {_e}")
                            restricted_scored = []
                        try:
                            global_scored = (
                                get_vector_store().similarity_search_with_score(
                                    query=payload.question,
                                    k=max(k, settings.max_sources * 2),
                                    filter_dict=None,
                                    threshold=settings.relevance_fallback_threshold,
                                )
                            )
                        except Exception as _e:
                            logger.warning(f"Demo scored global failed: {_e}")
                            global_scored = []

                        best_restricted = min(
                            [s for (_, s) in restricted_scored], default=None
                        )
                        best_global = min([s for (_, s) in global_scored], default=None)

                        should_fallback = False
                        if best_restricted is None and best_global is not None:
                            should_fallback = True
                        elif best_restricted is not None and best_global is not None:
                            margin = getattr(settings, "relevance_fallback_margin", 0.1)
                            if best_global + margin < best_restricted:
                                should_fallback = True

                        if should_fallback:
                            if len(global_scored) > 0:
                                docs = [doc for (doc, _) in global_scored][
                                    : max(k, settings.max_sources)
                                ]
                                fallback_note = "提示：在您选定的文档中未检索到更相关的内容，已自动在全库中扩大检索范围。\n\n"
                            else:
                                docs = []
                                fallback_note = "提示：在您选定的文档以及全库中均未检索到相关内容。\n\n"
                        else:
                            docs = [doc for (doc, _) in restricted_scored][:k]
                    else:
                        # 全库检索（不加阈值过滤，直接返回 top-k）
                        docs = get_vector_store().similarity_search(
                            query=payload.question, k=max(k, settings.max_sources)
                        )
                    sources = []
                    for doc in docs:
                        content = doc.page_content
                        if len(content) > 300:
                            content = content[:300] + "..."
                        sources.append(
                            SourceDocument(
                                document_name=doc.metadata.get("filename", "Unknown"),
                                content=content,
                                similarity_score=1.0,
                                page_number=doc.metadata.get("page"),
                            )
                        )
                    return QuestionResponse(
                        answer=(
                            f"{fallback_note}"
                            + "当前处于 Demo 模式，尚未提供 LLM API Key，因此仅展示检索到的相关内容片段。\n"
                            "请在左侧“模型设置(BYOK)”中填写 API Key 后重试，以生成完整答案。"
                        ),
                        sources=sources,
                        processing_time=0.0,
                    )
                except Exception as demo_e:
                    return QuestionResponse(
                        answer=f"当前处于 Demo 模式且未配置 API Key。无法进行生成，仅提示：{str(demo_e)}",
                        sources=[],
                        processing_time=0.0,
                    )
            # 使用默认全局引擎（便于单元测试使用 mock）
            engine = get_qa_engine()

        # 执行问答（信号量保护，防止 LLM 并发过载）
        import asyncio

        from app.core.concurrency import get_llm_semaphore

        semaphore = get_llm_semaphore()
        if semaphore._value == 0:
            logger.warning("LLM semaphore exhausted, rejecting ask request")
            raise HTTPException(status_code=503, detail="服务器繁忙，请稍后重试")
        async with semaphore:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: engine.ask(
                    question=payload.question,
                    max_sources=payload.max_sources,
                    document_id=payload.document_id,
                ),
            )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ask_question: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Question processing failed: {str(e)}"
        )


@router.post("/search")
async def search_documents(payload: QuestionRequest, request: Request):
    """文档检索接口（不生成答案）"""
    try:
        if not payload.question.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        # 选择引擎（当提供 BYOK 时使用临时引擎，否则使用全局，以保持与测试兼容）
        overrides = _extract_overrides_from_headers(request)
        engine = (
            get_qa_engine()
            if not overrides.get("api_key")
            else QAEngine(get_vector_store(), overrides=overrides)
        )

        # 执行相似度搜索
        relevant_docs = engine.get_relevant_documents(
            question=payload.question,
            k=payload.max_sources or 5,
            document_id=payload.document_id,
        )

        # 处理结果
        results = []
        for doc in relevant_docs:
            result = {
                "document_name": doc.metadata.get("filename", "Unknown"),
                "content": (
                    doc.page_content[:300] + "..."
                    if len(doc.page_content) > 300
                    else doc.page_content
                ),
                "metadata": {
                    "document_id": doc.metadata.get("document_id"),
                    "chunk_index": doc.metadata.get("chunk_index"),
                    "page": doc.metadata.get("page"),
                },
            }
            results.append(result)

        return {
            "success": True,
            "query": payload.question,
            "results": results,
            "total_found": len(results),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/suggestions")
async def get_question_suggestions():
    """获取问题建议"""
    try:
        # 检查是否有文档
        collection_info = get_vector_store().get_collection_info()

        if collection_info.get("document_count", 0) == 0:
            return {"suggestions": ["请先上传一些文档", "知识库目前为空"]}

        # 返回一些通用的问题模板
        suggestions = [
            "这个文档讲的是什么？",
            "有什么重要的信息？",
            "能总结一下主要内容吗？",
            "有哪些关键要点？",
            "这个主题的详细说明是什么？",
        ]

        return {
            "suggestions": suggestions,
            "document_count": collection_info.get("document_count", 0),
        }

    except Exception as e:
        logger.error(f"Error getting suggestions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get suggestions: {str(e)}"
        )


@router.post("/feedback")
async def submit_feedback(
    question: str, answer: str, rating: int, feedback: Optional[str] = None  # 1-5
):
    """提交用户反馈"""
    try:
        if rating not in range(1, 6):
            raise HTTPException(
                status_code=400, detail="Rating must be between 1 and 5"
            )

        logger.info(
            "User feedback received - rating=%s, question_length=%s, answer_length=%s, has_feedback=%s",
            rating,
            len(question or ""),
            len(answer or ""),
            bool(feedback),
        )

        return {"success": True, "message": "Thank you for your feedback!"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to submit feedback: {str(e)}"
        )


@router.get("/health")
async def qa_health_check(
    deep: Optional[bool] = None,
    with_qa: Optional[bool] = None,
    _: dict = Depends(require_admin),
):
    """问答系统健康检查"""
    try:
        health_info = get_qa_engine().health_check(deep=deep, with_qa=with_qa)

        return {"success": True, "health": health_info}

    except Exception as e:
        logger.error(f"QA health check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get("/stats")
async def get_qa_stats(_: dict = Depends(require_admin)):
    """获取问答系统统计信息"""
    try:
        from app.core.cache_manager import cache_manager
        from app.core.config import settings

        collection_info = get_vector_store().get_collection_info()
        cache_stats = cache_manager.get_cache_stats()

        stats = {
            "vector_store": {
                "collection_name": collection_info.get("collection_name"),
                "document_count": collection_info.get("document_count", 0),
                "embedding_model": collection_info.get("embedding_model"),
            },
            "qa_settings": {
                "max_sources": settings.max_sources,
                "similarity_threshold": settings.similarity_threshold,
                "model": settings.chat_model,
            },
            "cache": cache_stats,
        }

        return stats

    except Exception as e:
        logger.error(f"Error getting QA stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.delete("/cache")
async def clear_cache(_: dict = Depends(require_admin)):
    """清空问答缓存"""
    try:
        from app.core.cache_manager import cache_manager

        result = cache_manager.clear_qa_cache()

        return {
            "success": True,
            "message": "QA cache cleared successfully",
            "cleared_entries": result["qa_cleared"],
        }

    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@router.delete("/cache/all")
async def clear_all_cache(_: dict = Depends(require_admin)):
    """清空所有缓存"""
    try:
        from app.core.cache_manager import cache_manager

        result = cache_manager.clear_all_cache()

        return {
            "success": True,
            "message": "All cache cleared successfully",
            "cleared_entries": result,
        }

    except Exception as e:
        logger.error(f"Error clearing all cache: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to clear all cache: {str(e)}"
        )


@router.get("/quota")
async def get_quota_info(request: Request):
    """获取当前用户配额信息"""
    try:
        from app.core.config import settings

        if not settings.enable_quota_limit:
            return {"quota_enabled": False, "message": "Quota limit is disabled"}

        from app.core.quota_manager import get_quota_manager

        quota_manager = get_quota_manager()

        # 构建请求信息
        request_info = {
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", ""),
        }

        # 检查是否使用了自定义API Key
        overrides = _extract_overrides_from_headers(request)
        has_custom_key = bool(overrides.get("api_key"))

        if has_custom_key:
            return {
                "quota_enabled": True,
                "has_custom_key": True,
                "used_count": 0,
                "daily_limit": "unlimited",
                "remaining": "unlimited",
                "message": "Using custom API key - no quota limit",
            }

        # 获取配额信息
        quota_info = quota_manager.get_quota_info(request_info)
        remaining = max(0, quota_info.daily_limit - quota_info.used_count)

        return {
            "quota_enabled": True,
            "has_custom_key": False,
            "used_count": quota_info.used_count,
            "daily_limit": quota_info.daily_limit,
            "remaining": remaining,
            "last_reset_date": quota_info.last_reset_date,
            "message": f"Using default API key - {remaining}/{quota_info.daily_limit} questions remaining today",
        }

    except Exception as e:
        logger.error(f"Error getting quota info: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get quota info: {str(e)}"
        )


@router.post("/quota/reset")
async def reset_quota(request: Request, _: dict = Depends(require_admin)):
    """重置当前用户配额（管理员功能）"""
    try:
        from app.core.config import settings

        if not settings.enable_quota_limit:
            raise HTTPException(status_code=400, detail="Quota limit is disabled")

        from app.core.quota_manager import get_quota_manager

        quota_manager = get_quota_manager()

        # 构建请求信息
        request_info = {
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", ""),
        }

        # 重置配额
        success = quota_manager.reset_user_quota(request_info)

        if success:
            return {"success": True, "message": "User quota reset successfully"}
        else:
            return {
                "success": False,
                "message": "User not found or quota already at zero",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting quota: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to reset quota: {str(e)}")


@router.get("/quota/stats")
async def get_all_quota_stats(_: dict = Depends(require_admin)):
    """获取所有用户配额统计（管理员功能）"""
    try:
        from app.core.config import settings

        if not settings.enable_quota_limit:
            raise HTTPException(status_code=400, detail="Quota limit is disabled")

        from app.core.quota_manager import get_quota_manager

        quota_manager = get_quota_manager()

        all_quotas = quota_manager.get_all_quotas()

        return {
            "success": True,
            "total_users": len(all_quotas),
            "quotas": all_quotas,
            "default_daily_limit": settings.default_daily_quota,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting quota stats: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get quota stats: {str(e)}"
        )
