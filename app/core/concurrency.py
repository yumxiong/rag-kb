"""Process-local concurrency gates and the bounded QA worker pool."""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


class GateLease:
    """A one-shot lease that is released after the real worker exits."""

    def __init__(self, gate):
        self._gate = gate
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._gate.release()


class ConcurrencyGate:
    """Non-queueing concurrency gate used by the async event loop."""

    def __init__(self, limit: int):
        if type(limit) is not int or limit <= 0:
            raise ValueError("Concurrency limits must be positive integers")
        self.limit = limit
        self.active = 0
        self._lock = threading.Lock()

    def try_acquire(self):
        with self._lock:
            if self.active >= self.limit:
                return None
            self.active += 1
        return GateLease(self)

    def release(self) -> None:
        with self._lock:
            if self.active <= 0:
                raise RuntimeError("Concurrency gate released without an active lease")
            self.active -= 1


class IdentityConcurrencyGate:
    """One active question worker per anonymous identity."""

    def __init__(self, limit: int = 1):
        if type(limit) is not int or limit <= 0:
            raise ValueError("Identity concurrency limits must be positive integers")
        self.limit = limit
        self._active = {}
        self._lock = threading.Lock()

    def try_acquire(self, identity: str):
        with self._lock:
            if self._active.get(identity, 0) >= self.limit:
                return None
            self._active[identity] = self._active.get(identity, 0) + 1
        return GateLease(_IdentityLeaseAdapter(self, identity))

    def release(self, identity: str) -> None:
        with self._lock:
            current = self._active.get(identity, 0)
            if current <= 0:
                raise RuntimeError("Identity concurrency released without a lease")
            if current == 1:
                self._active.pop(identity, None)
            else:
                self._active[identity] = current - 1


class _IdentityLeaseAdapter:
    def __init__(self, owner, identity: str):
        self.owner = owner
        self.identity = identity

    def release(self) -> None:
        self.owner.release(self.identity)


_llm_gate = None
# Backward-compatible reset hook used by the existing test fixtures.
_llm_semaphore = None
_identity_gate = None
_qa_executor = None


def _configured_limit(name: str, fallback: int) -> int:
    value = getattr(settings, name, fallback)
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def get_llm_gate() -> ConcurrencyGate:
    global _llm_gate
    if _llm_gate is None:
        _llm_gate = ConcurrencyGate(_configured_limit("max_concurrent_llm_requests", 5))
    return _llm_gate


def get_identity_gate() -> IdentityConcurrencyGate:
    global _identity_gate
    if _identity_gate is None:
        _identity_gate = IdentityConcurrencyGate(
            _configured_limit("max_concurrent_identity_questions", 1)
        )
    return _identity_gate


def get_qa_executor() -> ThreadPoolExecutor:
    """Use a bounded pool so timed-out workers cannot create unbounded threads."""
    global _qa_executor
    if _qa_executor is None:
        _qa_executor = ThreadPoolExecutor(
            max_workers=_configured_limit("max_concurrent_llm_requests", 5),
            thread_name_prefix="qa_worker",
        )
    return _qa_executor


def shutdown_qa_executor(*, wait: bool = True) -> None:
    global _qa_executor, _llm_gate, _identity_gate
    executor, _qa_executor = _qa_executor, None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=False)
    _llm_gate = None
    _identity_gate = None


class ConcurrencyLimitMiddleware:
    """Reject requests immediately when the process-wide HTTP cap is full."""

    def __init__(self, app, max_concurrent: int):
        self.app = app
        self._gate = ConcurrencyGate(max_concurrent)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        lease = self._gate.try_acquire()
        if lease is None:
            request_id = str(uuid.uuid4())
            logger.warning("Concurrency limit reached, rejecting %s", scope["path"])
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": "service_busy",
                        "message": "Service is busy; try again later.",
                        "request_id": request_id,
                        "retry_after_seconds": 1,
                    }
                },
                headers={
                    "X-Request-ID": request_id,
                    "Retry-After": "1",
                    "Cache-Control": "no-store",
                },
            )
            return await response(scope, receive, send)
        try:
            return await self.app(scope, receive, send)
        finally:
            lease.release()
