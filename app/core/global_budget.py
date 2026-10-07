"""Per-question provider accounting context for the shared persistent ledger."""

from contextlib import contextmanager
from contextvars import ContextVar

from langchain_core.callbacks import BaseCallbackHandler

from app.core.anonymous_session import SessionError
from app.core.config import settings
from app.core.deadline import current_deadline
from app.core.question_cost import MAX_MESSAGES_BYTES, serialized_messages_size

_budget_context = ContextVar("budget_context", default=None)
_offline_context = ContextVar("offline_provider_access", default=False)


@contextmanager
def offline_provider_access(*, reason: str):
    """Explicit trusted-tool scope; never derive this permission from HTTP input.

    Offline costs require independent provider limits and are not public quota.
    A question ledger, when present, always takes precedence over this scope.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("An offline operation reason is required")
    token = _offline_context.set(True)
    try:
        yield
    finally:
        _offline_context.reset(token)


def require_query_context() -> None:
    """Fail closed in production when a caller loses its accounting context."""
    if not (
        in_question_budget()
        or _offline_context.get()
        or settings.anonymous_storage_development
    ):
        raise SessionError("service_unavailable", 503)


def require_document_maintenance() -> None:
    """HTTP uploads and queued workers require an explicitly open window."""
    if not settings.enable_document_maintenance:
        raise SessionError("feature_disabled", 403)


def require_document_provider_access() -> None:
    """Document costs are separate; a public query cannot use this path."""
    if in_question_budget():
        raise SessionError("feature_disabled", 403)
    if not _offline_context.get():
        require_document_maintenance()


@contextmanager
def question_budget(ledger, *, byok: bool, limits: dict):
    token = _budget_context.set((ledger, byok, limits))
    try:
        yield
    finally:
        _budget_context.reset(token)


def record_provider_attempt(kind: str) -> None:
    context = _budget_context.get()
    if context is None:
        require_query_context()
        return
    ledger, byok, limits = context
    ledger.record_attempt(kind, byok=byok, limits=limits)


def in_question_budget() -> bool:
    return _budget_context.get() is not None


class ChatAttemptCallback(BaseCallbackHandler):
    """Reserve chat budget at the actual model boundary, after retrieval."""

    raise_error = True

    def on_chat_model_start(self, serialized, messages, **kwargs):
        require_query_context()
        deadline = current_deadline()
        if deadline is not None:
            deadline.check()
        if (
            len(messages) != 1
            or serialized_messages_size(messages[0]) > MAX_MESSAGES_BYTES
        ):
            raise SessionError("invalid_request", 400)
        record_provider_attempt("llm")
