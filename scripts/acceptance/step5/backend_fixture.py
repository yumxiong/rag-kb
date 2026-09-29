"""Test-only model doubles and observations; never imported by production."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

from app.api import qa
from app.main import app
from app.models.schemas import QuestionResponse

EVIDENCE = Path("/evidence")


class VectorFixture:
    def get_collection_info(self):
        return {"document_count": 1}

    def list_documents(self):
        return [{"id": "fixture", "filename": "identity-fixture.md"}]


class EngineFixture:
    def ask(self, **kwargs):
        with (EVIDENCE / "engine-calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"called": True}) + "\n")
        return QuestionResponse(
            answer="Identity acceptance fixture response.",
            sources=[],
            processing_time=0,
        )


qa.vector_store = VectorFixture()
qa.qa_engine = EngineFixture()


def fail(*args, **kwargs):
    raise OSError("injected storage boundary failure")


def fault_patch(stage):
    """Fail one real write boundary, retaining all preceding filesystem calls."""
    if stage == "temporary":
        return patch("app.core.anonymous_session.tempfile.mkstemp", side_effect=fail)
    if stage == "replace":
        return patch("app.core.anonymous_session.os.replace", side_effect=fail)
    original = os.fsync

    def fsync(fd):
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if is_directory == (stage == "directory_fsync"):
            fail()
        return original(fd)

    assert stage in ("file_fsync", "directory_fsync")
    return patch("app.core.anonymous_session.os.fsync", side_effect=fsync)


@app.middleware("http")
async def observe_and_inject(request, call_next):
    # Never retain credentials, questions, or arbitrary request header values.
    observation = {
        "path": request.url.path,
        "peer": request.client.host,
        "scheme": request.url.scheme,
        "cookie_present": "rag_anonymous" in request.cookies,
        "token_header_present": "x-anonymous-token" in request.headers,
    }
    fault = EVIDENCE / "fault.txt"
    if fault.exists() and request.url.path in ("/api/qa/ask", "/api/session/anonymous"):
        stage = fault.read_text().strip()
        fault.unlink()
        with fault_patch(stage):
            response = await call_next(request)
    else:
        response = await call_next(request)
    observation["status"] = response.status_code
    with (EVIDENCE / "requests.jsonl").open("a") as stream:
        stream.write(json.dumps(observation) + "\n")
    return response
