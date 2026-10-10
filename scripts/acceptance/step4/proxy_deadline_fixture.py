"""Isolated Linux fixture; preserve the real app and observe synthetic requests."""

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from app.core.anonymous_session import bootstrap

bootstrap(
    Path(os.environ["QUOTA_STORAGE_PATH"]),
    Path(os.environ["ANONYMOUS_STORE_REFERENCE"]),
    development=True,
)

# Provision the fresh temporary ledger before importing the real application.
from app.api import qa  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import QuestionResponse  # noqa: E402

EVIDENCE = Path(os.environ["STEP4_EVIDENCE"])
LOCK = threading.Lock()


def emit(event, **values):
    """Record only allowlisted synthetic observations, never request credentials."""
    record = {"event": event, "monotonic": time.monotonic(), **values}
    with LOCK, (EVIDENCE / "proxy-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()


class VectorFixture:
    def get_collection_info(self):
        return {"document_count": 1}


class EngineFixture:
    def ask(self, **kwargs):
        question = kwargs["question"]
        if question not in {
            "initial",
            "timeout",
            "busy-during",
            "busy-after",
            "recovery",
        }:
            raise ValueError("Unexpected synthetic question")
        started = time.monotonic()
        emit("worker_start", question=question)
        if question == "timeout":
            time.sleep(70)
        emit("worker_finish", question=question, elapsed=time.monotonic() - started)
        return QuestionResponse(answer="fixture answer", sources=[], processing_time=0)


class ObserveMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        probe = headers.get(b"x-acceptance-probe", b"").decode("ascii", errors="ignore")
        if not re.fullmatch(r"[a-z0-9-]{1,40}", probe):
            return await self.app(scope, receive, send)
        status, request_id = None, None
        digest = hashlib.sha256()

        async def observe_send(message):
            nonlocal status, request_id
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = dict(message["headers"])
                request_id = response_headers.get(b"x-request-id", b"").decode()
            elif message["type"] == "http.response.body":
                digest.update(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, observe_send)
        emit(
            "response",
            probe=probe,
            status=status,
            request_id=request_id,
            response_sha256=digest.hexdigest(),
            client_ip=scope["client"][0],
            forwarded_for=headers.get(b"x-forwarded-for", b"").decode()[:64],
            budget_counts=app.state.anonymous_store.budget_snapshot(
                settings.budget_limits()
            )["counts"],
        )


qa.vector_store = VectorFixture()
qa.qa_engine = EngineFixture()
app.add_middleware(ObserveMiddleware)
emit("fixture_config", deadline=settings.question_deadline_seconds, worker_seconds=70)
