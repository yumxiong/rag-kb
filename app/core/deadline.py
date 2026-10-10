"""Bounded deadlines shared by retrieval, embedding, and chat calls."""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event

from app.core.anonymous_session import SessionError

_current_deadline: ContextVar["QuestionDeadline | None"] = ContextVar(
    "question_deadline", default=None
)


class QuestionDeadline:
    def __init__(
        self,
        *,
        overall_seconds: float,
        embedding_seconds: float,
        chat_seconds: float,
        clock=time.monotonic,
    ):
        self.started_at = clock()
        self.overall_seconds = overall_seconds
        self.embedding_seconds = embedding_seconds
        self.chat_seconds = chat_seconds
        self.clock = clock
        self._cancelled = Event()

    def elapsed(self) -> float:
        return max(0.0, self.clock() - self.started_at)

    def remaining(self) -> float:
        return max(0.0, self.overall_seconds - self.elapsed())

    def check(self) -> None:
        if self._cancelled.is_set() or self.remaining() <= 0:
            raise SessionError("upstream_timeout", 504)

    def provider_timeout(self, phase: str) -> float:
        self.check()
        if phase == "embedding":
            limit = self.embedding_seconds
        elif phase == "chat":
            limit = self.chat_seconds
        else:
            raise ValueError("Unknown provider phase")
        timeout = min(self.remaining(), limit)
        if timeout <= 0:
            raise SessionError("upstream_timeout", 504)
        return timeout

    def check_provider_elapsed(self, started_at: float, phase: str) -> None:
        self.check()
        if phase not in ("embedding", "chat"):
            raise ValueError("Unknown provider phase")
        limit = self.embedding_seconds if phase == "embedding" else self.chat_seconds
        if self.clock() - started_at >= limit:
            raise SessionError("upstream_timeout", 504)

    def cancel(self) -> None:
        self._cancelled.set()


@contextmanager
def deadline_scope(deadline: QuestionDeadline):
    token = _current_deadline.set(deadline)
    try:
        yield deadline
    finally:
        _current_deadline.reset(token)


def current_deadline() -> QuestionDeadline | None:
    return _current_deadline.get()
