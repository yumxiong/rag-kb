"""
问答API
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.anonymous_session import require_identity, store
from app.api.auth import require_admin
from app.core.anonymous_session import SessionError
from app.core.config import settings
from app.core.deadline import QuestionDeadline, deadline_scope
from app.core.demo_content import DEMO_QUESTIONS
from app.core.qa_engine import QAEngine
from app.core.url_safety import is_safe_base_url
from app.core.vector_store import VectorStore
from app.models.schemas import QuestionRequest, QuestionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class QuotaResetRequest(BaseModel):
    model_config = {"extra": "forbid"}

    quota_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=200)


# 全局实例（延迟初始化）
vector_store = None
qa_engine = None


def _release_question_leases(leases):
    for lease in leases:
        lease.release()


def _is_timeout_error(error: BaseException) -> bool:
    """Recognize provider timeout classes without exposing provider details."""
    return isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower()


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
    names = {
        "api_key": "LLM-Api-Key",
        "provider": "LLM-Provider",
        "api_base_url": "LLM-Base-URL",
        "model": "LLM-Model",
    }
    overrides = {
        key: request.headers[name].strip()
        for key, name in names.items()
        if name in request.headers
    }
    if not overrides:
        return overrides
    if not overrides.get("api_key") or not all(overrides.values()):
        raise SessionError("invalid_request", 400)
    if "provider" in overrides and overrides["provider"] not in {
        "openai",
        "deepseek",
        "zhipu",
        "openrouter",
        "custom",
    }:
        raise SessionError("invalid_request", 400)
    if "api_base_url" in overrides:
        try:
            safe = is_safe_base_url(
                overrides["api_base_url"], settings.get_allowed_chat_base_urls()
            )
        except Exception:
            safe = False
        if not safe:
            raise SessionError("invalid_request", 400)
    return overrides


@router.post("/ask", response_model=QuestionResponse)
async def ask_question(
    payload: QuestionRequest,
    request: Request,
    http_response: Response,
    identity: dict = Depends(require_identity),
):
    """智能问答接口"""
    try:
        if not payload.question.strip():
            raise SessionError("invalid_request", 400)

        # 问题长度验证
        from app.core.config import settings

        if (
            len(payload.question) < settings.min_question_length
            or len(payload.question) > settings.max_question_length
        ):
            raise SessionError("invalid_request", 400)

        overrides = _extract_overrides_from_headers(request)
        has_custom_key = bool(overrides.get("api_key"))
        request.app.state.session_rate_limit.check_identity(
            identity["quota_ref"],
            "ask",
            settings.max_ask_requests_per_minute,
        )

        # 检查是否有文档数据
        collection_info = get_vector_store().get_collection_info()
        if collection_info.get("document_count", 0) == 0:
            raise SessionError("knowledge_base_unavailable", 503)

        limits = settings.budget_limits()

        engine = None
        if overrides.get("api_key"):
            # 用户提供了 Key，创建临时引擎（不影响全局实例与测试桩）
            engine = QAEngine(get_vector_store(), overrides=overrides)
        else:
            # 未提供自定义 Key 时只使用部署固定的默认引擎。
            if qa_engine is None and not settings.get_api_key():
                raise SessionError("service_unavailable", 503)
            engine = get_qa_engine()

        from app.core.concurrency import (
            get_identity_gate,
            get_llm_gate,
            get_qa_executor,
        )
        from app.core.global_budget import question_budget

        identity_lease = get_identity_gate().try_acquire(identity["quota_ref"])
        llm_lease = get_llm_gate().try_acquire()
        if identity_lease is None or llm_lease is None:
            if identity_lease is not None:
                identity_lease.release()
            if llm_lease is not None:
                llm_lease.release()
            logger.warning("Question concurrency exhausted, rejecting ask request")
            raise SessionError("service_busy", 503, 1)

        submitted = False
        try:
            store(request).admit(
                identity,
                byok=has_custom_key,
                personal_limit=(
                    settings.default_daily_quota
                    if settings.enable_quota_limit
                    else None
                ),
                limits=limits,
            )
            deadline = QuestionDeadline(
                overall_seconds=settings.question_deadline_seconds,
                embedding_seconds=settings.embedding_timeout_seconds,
                chat_seconds=settings.chat_timeout_seconds,
            )
            deadline.check()

            def run_question():
                with deadline_scope(deadline), question_budget(
                    store(request), byok=has_custom_key, limits=limits
                ):
                    return engine.ask(
                        question=payload.question,
                        max_sources=payload.max_sources,
                        document_id=payload.document_id,
                    )

            worker_future = get_qa_executor().submit(run_question)
            submitted = True
            worker_future.add_done_callback(
                lambda _: _release_question_leases((identity_lease, llm_lease))
            )
            worker = asyncio.wrap_future(worker_future)
            try:
                answer_response = await asyncio.wait_for(
                    asyncio.shield(worker), timeout=deadline.remaining()
                )
            except asyncio.TimeoutError:
                deadline.cancel()
                raise SessionError("upstream_timeout", 504) from None
            except asyncio.CancelledError:
                deadline.cancel()
                # The concurrent future still owns both leases until the thread exits.
                raise
            except SessionError:
                raise
            except Exception as error:
                if _is_timeout_error(error):
                    raise SessionError("upstream_timeout", 504) from None
                logger.error("Question provider failed")
                raise SessionError("upstream_error", 502) from None
        finally:
            if not submitted:
                _release_question_leases((identity_lease, llm_lease))

        request_id = str(uuid.uuid4())
        answer_response = answer_response.model_copy(update={"request_id": request_id})
        http_response.headers["X-Request-ID"] = request_id
        http_response.headers["Cache-Control"] = "no-store"
        logger.info(
            "ask request_id=%s identity=%s result=%s",
            request_id,
            identity["quota_ref"],
            "cache" if answer_response.from_cache else "answered",
        )
        return answer_response

    except (HTTPException, SessionError):
        raise
    except Exception:
        logger.error("Question processing failed")
        raise SessionError("internal_error", 500) from None


@router.post("/search")
async def search_documents(payload: QuestionRequest, request: Request):
    """文档检索接口（不生成答案）"""
    if not settings.anonymous_storage_development:
        raise SessionError("feature_disabled", 403)
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
            return {"suggestions": [], "document_count": 0}

        return {
            "suggestions": list(DEMO_QUESTIONS),
            "document_count": len(get_vector_store().list_documents()),
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
            "User feedback received - rating=%s, question_length=%s, "
            "answer_length=%s, has_feedback=%s",
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
    if (deep or with_qa) and not settings.anonymous_storage_development:
        raise SessionError("feature_disabled", 403)
    if not settings.anonymous_storage_development:
        deep = False
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
async def get_quota_info(
    request: Request,
    response: Response,
    identity: dict = Depends(require_identity),
):
    """获取当前用户配额信息"""
    try:
        from app.core.config import settings

        request.app.state.session_rate_limit.check_identity(
            identity["quota_ref"],
            "quota",
            settings.max_quota_requests_per_minute,
        )

        # 检查是否使用了自定义API Key
        overrides = _extract_overrides_from_headers(request)
        has_custom_key = bool(overrides.get("api_key"))

        snapshot = store(request).quota_snapshot(
            identity,
            byok=has_custom_key,
            personal_limit=(
                settings.default_daily_quota if settings.enable_quota_limit else None
            ),
            limits=settings.budget_limits(),
        )
        used = snapshot["used_count"]
        limit = (
            settings.default_daily_quota
            if (settings.enable_quota_limit and not has_custom_key)
            else None
        )
        reset_at = snapshot["global_budget"]["reset_at"]
        request_id = str(uuid.uuid4())
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        return {
            "quota_enabled": settings.enable_quota_limit,
            "has_custom_key": has_custom_key,
            "used_count": used,
            "daily_limit": limit,
            "remaining": max(0, limit - used) if limit is not None else None,
            "reset_at": reset_at,
            "global_budget": snapshot["global_budget"],
            "request_id": request_id,
        }

    except SessionError:
        raise
    except Exception:
        logger.error("Error getting quota info")
        raise SessionError("internal_error", 500) from None


@router.post("/quota/reset")
async def reset_quota(
    payload: QuotaResetRequest,
    request: Request,
    response: Response,
    admin: dict = Depends(require_admin),
):
    """Reset one anonymous identity's current UTC personal count."""
    request_id = str(uuid.uuid4())
    if not store(request).reset_personal(payload.quota_ref):
        raise SessionError("quota_not_found", 404)
    logger.info(
        "quota reset time=%s actor=%s identity=%s request_id=%s",
        datetime.now(timezone.utc).isoformat(),
        admin["sub"],
        payload.quota_ref,
        request_id,
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "request_id": request_id}


@router.get("/quota/stats")
async def get_all_quota_stats(
    request: Request, response: Response, _: dict = Depends(require_admin)
):
    """Return only current UTC counts keyed by token digest."""
    request_id = str(uuid.uuid4())
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    return {
        **store(request).quota_stats(settings.default_daily_quota),
        "request_id": request_id,
    }


@router.get("/budget")
async def get_budget(
    request: Request, response: Response, _: dict = Depends(require_admin)
):
    """Read the persisted global counters without invoking a provider."""
    request_id = str(uuid.uuid4())
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    return {
        **store(request).budget_snapshot(settings.budget_limits()),
        "request_id": request_id,
    }
