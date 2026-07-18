"""
并发保护：全局请求限流 + LLM 调用信号量
"""

import asyncio
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)

# LLM 调用专用信号量（跨请求共享，限制同时进行的 LLM 调用数）
_llm_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    """获取 LLM 信号量（懒初始化，确保在事件循环内创建）"""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.max_concurrent_llm_requests)
    return _llm_semaphore


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """全局并发请求上限中间件"""

    def __init__(self, app, max_concurrent: int):
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def dispatch(self, request: Request, call_next):
        acquired = self._semaphore._value > 0  # 快速判断，避免无谓等待
        if not acquired and self._semaphore.locked():
            logger.warning(f"Concurrency limit reached, rejecting {request.url.path}")
            return JSONResponse(
                status_code=503,
                content={"detail": "服务器繁忙，请稍后重试"},
            )
        async with self._semaphore:
            return await call_next(request)
