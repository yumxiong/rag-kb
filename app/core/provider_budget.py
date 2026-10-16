"""Admission at the physical HTTP boundary, including SDK-generated batches.

Prices and model input ceilings are reviewed constants, not client input. Reserve
the entire supported input window, not an unverified character/token estimate.
"""

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from app.core.anonymous_session import SessionError
from app.core.money_ledger import MoneyLedger

POLICY_ID = "cny-2026-10-16-full-context-v1"
POLICY_START = "2026-10-16"
POLICY_EXPIRES = "2026-10-23"  # Exclusive; re-review before extending.
CHAT_ENDPOINT = "https://api.deepseek.com/chat/completions"
EMBEDDING_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
_offline_ledger = ContextVar("offline_money_ledger", default=None)
_process_ledger = None
_registry_lock = threading.RLock()


def register_project_ledger(store) -> None:
    """Bind background work to the same single-owner ledger as HTTP questions."""
    global _process_ledger
    MoneyLedger(store).snapshot()  # Refuse legacy ledgers without monetary state.
    with _registry_lock:
        if _process_ledger is not None and _process_ledger is not store:
            raise SessionError("quota_storage_unavailable", 503)
        _process_ledger = store


def unregister_project_ledger(store) -> None:
    global _process_ledger
    with _registry_lock:
        if _process_ledger is store:
            _process_ledger = None


@contextmanager
def money_ledger_scope(store):
    """Trusted offline tools must open the same provisioned, process-locked store."""
    MoneyLedger(store).snapshot()
    token = _offline_ledger.set(store)
    try:
        yield
    finally:
        _offline_ledger.reset(token)


def current_money_ledger() -> MoneyLedger:
    from app.core.global_budget import current_question_ledger

    with _registry_lock:
        store = current_question_ledger() or _offline_ledger.get() or _process_ledger
        if store is None or (
            _process_ledger is not None and store is not _process_ledger
        ):
            raise SessionError("quota_storage_unavailable", 503)
    return MoneyLedger(store)


def quote_request(request: httpx.Request, kind: str) -> int:
    """Return integer microyuan at reviewed peak/no-cache prices; fail closed."""
    try:
        body = json.loads(request.content)
        if request.method != "POST" or not isinstance(body, dict):
            raise ValueError("Unreviewed request")
        if kind == "chat":
            if (
                str(request.url) != CHAT_ENDPOINT
                or body.get("model") != "deepseek-flash"
            ):
                raise ValueError("Unreviewed chat model or endpoint")
            if set(body) - {
                "model",
                "messages",
                "temperature",
                "max_tokens",
                "n",
                "stream",
                "thinking",
            }:
                raise ValueError("Unreviewed chat option")
            output = body.get("max_tokens")
            if type(output) is not int or not 1 <= output <= 800:
                raise ValueError("Unbounded output")
            if (
                body.get("thinking") != {"type": "disabled"}
                or body.get("stream", False) is not False
            ):
                raise ValueError("Unreviewed reasoning/streaming")
            if type(body.get("n", 1)) is not int or body.get("n", 1) != 1:
                raise ValueError("Multiple completions")
            messages = body["messages"]
            if not isinstance(messages, list) or not messages:
                raise ValueError("Invalid messages")
            if any(not isinstance(m.get("content"), str) for m in messages):
                raise ValueError("Only plain text is priced")
            if len(json.dumps(messages, ensure_ascii=True).encode()) > 32 * 1024:
                raise ValueError("Message byte limit exceeded")
            # 2 CNY / 1M input, 8 CNY / 1M output. 1.1M conservatively covers
            # both decimal 1M and binary 1Mi token context interpretations.
            return 1_100_000 * 2 + output * 8
        if kind != "embedding" or str(request.url) != EMBEDDING_ENDPOINT:
            raise ValueError("Unreviewed embedding endpoint")
        limits = {"qwen3.7-text-embedding": 128_000, "text-embedding-v3": 8192}
        maximum = limits[body["model"]]
        if set(body) - {"model", "input", "dimensions", "encoding_format"}:
            raise ValueError("Unreviewed embedding option")
        if body.get("dimensions") != 1024 or type(body.get("dimensions")) is not int:
            raise ValueError("Unreviewed dimensions")
        if body.get("encoding_format", "float") not in {"float", "base64"}:
            raise ValueError("Unreviewed format")
        texts = body["input"]
        texts = [texts] if isinstance(texts, str) else texts
        if not isinstance(texts, list) or not 1 <= len(texts) <= 10:
            raise ValueError("Unreviewed batch")
        if any(
            not isinstance(t, str) or not t or len(t.encode()) > maximum for t in texts
        ):
            raise ValueError("Invalid text input")
        # 0.5 CNY / 1M tokens, charged per item at its full context window.
        return len(texts) * maximum // 2
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SessionError("service_unavailable", 503) from None


def reserve_request(request, kind):
    money = current_money_ledger()
    if not POLICY_START <= money.store._day() < POLICY_EXPIRES:
        raise SessionError("service_unavailable", 503)
    amount = quote_request(request, kind)
    identifier = money.reserve(amount, policy=f"{POLICY_ID}:{kind}")
    return money, identifier


class BudgetedTransport(httpx.BaseTransport):
    """Each dispatched request has its own durable reservation, including retries."""

    def __init__(self, kind: str, delegate=None):
        self.kind = kind
        self.delegate = (
            delegate if delegate is not None else httpx.HTTPTransport(retries=0)
        )

    def handle_request(self, request):
        request.read()
        money, identifier = reserve_request(request, self.kind)
        response = self.delegate.handle_request(request)
        try:
            response.read()  # Header receipt alone does not end billing uncertainty.
            if response.is_success:
                money.complete(identifier)
        except BaseException:
            response.close()
            raise
        # Errors/timeouts retain pending reservations indefinitely, across days.
        return response

    def close(self):
        self.delegate.close()


class AsyncBudgetedTransport(httpx.AsyncBaseTransport):
    def __init__(self, kind: str, delegate=None):
        self.kind = kind
        self.delegate = (
            delegate if delegate is not None else httpx.AsyncHTTPTransport(retries=0)
        )

    async def handle_async_request(self, request):
        await request.aread()
        money, identifier = reserve_request(request, self.kind)
        response = await self.delegate.handle_async_request(request)
        try:
            await response.aread()
            if response.is_success:
                money.complete(identifier)
        except BaseException:
            await response.aclose()
            raise
        return response

    async def aclose(self):
        await self.delegate.aclose()


def provider_http_clients(kind: str) -> dict:
    """Use explicit transports so proxy environment cannot bypass admission."""
    return {
        "http_client": httpx.Client(
            transport=BudgetedTransport(kind), follow_redirects=False, trust_env=False
        ),
        "http_async_client": httpx.AsyncClient(
            transport=AsyncBudgetedTransport(kind),
            follow_redirects=False,
            trust_env=False,
        ),
    }


def reraise_budget_cause(error: Exception) -> None:
    """OpenAI SDK wraps transport errors; preserve controlled public rejection."""
    cause = error
    for _ in range(8):
        if isinstance(cause, SessionError):
            raise cause
        cause = getattr(cause, "__cause__", None)
        if cause is None:
            break
