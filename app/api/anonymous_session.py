"""Cookie and Header transports for the frozen anonymous identity contract."""

import math
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.anonymous_session import SessionError
from app.core.config import settings

router = APIRouter()
COOKIE_NAME = "rag_anonymous"


def timestamp(value: int) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def store(request: Request):
    result = getattr(request.app.state, "anonymous_store", None)
    if result is None:
        raise SessionError("quota_storage_unavailable", 503)
    return result


def validate_origin(request: Request, cookie_mode: bool) -> None:
    origin = request.headers.get("origin")
    if (origin is not None and origin not in settings.get_cors_origins()) or (
        cookie_mode and request.method != "GET" and origin is None
    ):
        raise SessionError("origin_not_allowed", 403)


def credentials(request: Request) -> tuple[str | None, str | None]:
    cookie = request.cookies.get(COOKIE_NAME)
    header = request.headers.get("x-anonymous-token")
    if cookie is not None and header is not None:
        raise SessionError("invalid_request", 400)
    return cookie, header


def require_identity(request: Request) -> dict:
    """Shared ask/quota parser; the remote IP is never an identity key."""
    cookie, header = credentials(request)
    validate_origin(request, cookie is not None)
    token = cookie if cookie is not None else header
    if token is None:
        raise SessionError("anonymous_session_required")
    return store(request).resolve(token)


class SessionRateLimit:
    """Bound all session requests, including failed credential verification."""

    def __init__(self):
        self.windows = defaultdict(deque)
        self.lock = Lock()

    def check(self, source: str):
        now = time.monotonic()
        with self.lock:
            for key in list(self.windows):
                if not self.windows[key] or self.windows[key][-1] <= now - 60:
                    del self.windows[key]
            window = self.windows[source]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= 30:
                raise SessionError(
                    "rate_limited", 429, max(1, math.ceil(window[0] + 60 - now))
                )
            window.append(now)


async def session_error_handler(request: Request, error: SessionError):
    request_id = str(uuid.uuid4())
    messages = {
        "anonymous_session_required": "请先连接匿名会话。",
        "anonymous_session_expired": "会话已过期，请重新连接。",
        "anonymous_session_invalid": "会话失效，请重新连接。",
        "quota_storage_unavailable": "服务暂不可用，请稍后再试。",
        "quota_exceeded": "今日免费提问次数已用完。",
        "rate_limited": "请求过于频繁，请稍后再试。",
        "origin_not_allowed": "请求来源不允许。",
        "invalid_request": "请求格式或凭证传输方式不正确。",
    }
    detail = {
        "code": error.code,
        "message": messages[error.code],
        "request_id": request_id,
    }
    headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if error.status == 429:
        wait = error.retry_after or 60
        detail["retry_after_seconds"] = wait
        headers["Retry-After"] = str(wait)
    response = JSONResponse(
        {"detail": detail}, status_code=error.status, headers=headers
    )
    if error.code in ("anonymous_session_expired", "anonymous_session_invalid"):
        if COOKIE_NAME in request.cookies:
            response.delete_cookie(
                COOKIE_NAME,
                path="/api",
                secure=settings.anonymous_cookie_secure,
                httponly=True,
                samesite="lax",
            )
    return response


@router.post("/anonymous")
async def initialize(request: Request):
    """Create a durable anonymous identity or reuse its fixed lifetime."""
    source = request.client.host if request.client else "unknown"
    request.app.state.session_rate_limit.check(source)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].lower()
        != "application/json"
    ):
        raise SessionError("invalid_request", 400)
    try:
        body = await request.json()
    except ValueError:
        raise SessionError("invalid_request", 400) from None
    if not isinstance(body, dict) or set(body) != {"transport"}:
        raise SessionError("invalid_request", 400)
    transport = body["transport"]
    if transport not in ("cookie", "header"):
        raise SessionError("invalid_request", 400)
    cookie, header = credentials(request)
    if (transport == "cookie" and header is not None) or (
        transport == "header" and cookie is not None
    ):
        raise SessionError("invalid_request", 400)
    validate_origin(request, transport == "cookie")
    token = cookie if transport == "cookie" else header
    ledger = store(request)
    if token is None:
        token, identity = ledger.create(source)
        status = 201
    else:
        identity = ledger.resolve(token)
        status = 200
    request_id = str(uuid.uuid4())
    body = {
        "transport": transport,
        "expires_at": timestamp(identity["expires_at"]),
        "request_id": request_id,
    }
    if transport == "header":
        body["token"] = token
    response = JSONResponse(
        body,
        status_code=status,
        headers={
            "X-Request-ID": request_id,
            "Cache-Control": "no-store",
        },
    )
    if transport == "cookie":
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=max(0, identity["expires_at"] - int(ledger.clock())),
            expires=datetime.fromtimestamp(identity["expires_at"], timezone.utc),
            path="/api",
            httponly=True,
            secure=settings.anonymous_cookie_secure,
            samesite="lax",
        )
    return response
