"""Focused step 4 rate, deadline, and response-lifetime checks."""

import asyncio

import pytest

from app.api.anonymous_session import SessionRateLimit
from app.core.anonymous_session import SessionError
from app.core.concurrency import ConcurrencyLimitMiddleware
from app.core.config import Settings
from app.core.deadline import QuestionDeadline


def test_provider_timeout_is_bounded_by_each_call_and_question_remainder():
    now = [0.0]
    deadline = QuestionDeadline(
        overall_seconds=60,
        embedding_seconds=15,
        chat_seconds=45,
        clock=lambda: now[0],
    )
    assert deadline.provider_timeout("embedding") == 15
    assert deadline.provider_timeout("chat") == 45
    now[0] = 30
    assert deadline.provider_timeout("embedding") == 15
    assert deadline.provider_timeout("chat") == 30
    now[0] = 59
    assert deadline.provider_timeout("embedding") == 1
    now[0] = 60
    with pytest.raises(SessionError, match="upstream_timeout"):
        deadline.provider_timeout("chat")


def test_cancelled_deadline_blocks_followup_provider_attempts():
    deadline = QuestionDeadline(
        overall_seconds=60, embedding_seconds=15, chat_seconds=45
    )
    deadline.cancel()
    with pytest.raises(SessionError, match="upstream_timeout"):
        deadline.provider_timeout("embedding")


def test_session_rate_limit_window_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.api.anonymous_session.time.monotonic", lambda: clock[0])
    limiter = SessionRateLimit()
    limiter.check("source", limit=2)
    limiter.check("source", limit=2)
    with pytest.raises(SessionError, match="rate_limited") as blocked:
        limiter.check("source", limit=2)
    assert blocked.value.retry_after == 60
    clock[0] += 60
    limiter.check("source", limit=2)


@pytest.mark.parametrize(
    "field",
    [
        "max_concurrent_llm_requests",
        "max_concurrent_requests",
        "max_concurrent_identity_questions",
        "max_session_requests_per_minute",
        "max_ask_requests_per_minute",
        "max_quota_requests_per_minute",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "0"])
def test_invalid_traffic_limits_fail_configuration(field, value):
    with pytest.raises(ValueError, match="Traffic limits"):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("question_deadline_seconds", 60),
        ("embedding_timeout_seconds", 15),
        ("chat_timeout_seconds", 45),
    ],
)
def test_provider_deadline_hard_caps(field, maximum):
    assert getattr(Settings(_env_file=None, **{field: str(maximum)}), field) == maximum
    for invalid in (0, maximum + 1, True, 1.5):
        with pytest.raises(ValueError, match=field):
            Settings(_env_file=None, **{field: invalid})


@pytest.mark.asyncio
async def test_global_http_slot_is_held_until_response_body_finishes():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        entered.set()
        await release.wait()
        await send({"type": "http.response.body", "body": b"done"})

    middleware = ConcurrencyLimitMiddleware(app, max_concurrent=1)
    scope = {"type": "http", "path": "/stream"}

    async def request():
        messages = []

        async def send(message):
            messages.append(message)

        await middleware(scope, lambda: None, send)
        return messages

    first = asyncio.create_task(request())
    await entered.wait()
    try:
        rejected = await request()
        assert rejected[0]["status"] == 503
        assert middleware._gate.active == 1
    finally:
        release.set()
    assert (await first)[-1]["body"] == b"done"
    assert middleware._gate.active == 0
