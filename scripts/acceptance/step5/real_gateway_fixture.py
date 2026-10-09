"""Real FastAPI admission with disposable storage and synthetic engine only."""

import logging
import os
import socket
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/workspace")
os.chdir("/tmp")
os.environ.clear()
os.environ["PATH"] = "/usr/local/bin:/usr/bin:/bin"
logging.disable(logging.CRITICAL)

from pydantic_settings import BaseSettings  # noqa: E402
from pydantic_settings.sources import DotEnvSettingsSource  # noqa: E402

config = {
    "quota_storage_path": "/tmp/ledger",
    "anonymous_store_reference": "/tmp/reference.json",
    "anonymous_storage_development": True,
    "anonymous_cookie_secure": True,
    "allowed_origins": "https://localhost:18443",
    "upload_dir": "/tmp/uploads",
    "chroma_db_path": "/tmp/chroma",
    "temp_upload_dir": "/tmp/uploads-temp",
    "job_status_dir": "/tmp/jobs",
    "default_daily_quota": 5,
    "max_ask_requests_per_minute": 100,
    "max_session_requests_per_minute": 100,
    "max_quota_requests_per_minute": 200,
}
with patch.object(
    DotEnvSettingsSource, "_read_env_files", return_value={}
), patch.object(
    BaseSettings,
    "settings_customise_sources",
    classmethod(lambda cls, *args, **kwargs: (lambda: config,)),
):
    from app.core.config import Settings

Settings.get_api_key = lambda self: "synthetic-only"
state = {"started": 0, "finished": 0}
lock = threading.Lock()


class VectorFixture:
    def get_collection_info(self):
        return {"document_count": 1}


class EngineFixture:
    def ask(self, **kwargs):
        from app.models.schemas import QuestionResponse

        with lock:
            state["started"] += 1
        try:
            question = kwargs["question"]
            if question == "cancel-slow":
                time.sleep(8)
            if question == "deadline-slow":
                time.sleep(70)
            if question == "failure":
                raise RuntimeError("synthetic")
            return QuestionResponse(
                answer="synthetic answer", sources=[], processing_time=0,
                from_cache=question == "cached",
            )
        finally:
            with lock:
                state["finished"] += 1


for name, symbol, replacement in (
    ("app.core.vector_store", "VectorStore", VectorFixture),
    ("app.core.qa_engine", "QAEngine", EngineFixture),
):
    module = types.ModuleType(name)
    setattr(module, symbol, replacement)
    sys.modules[name] = module

from app.core.anonymous_session import bootstrap  # noqa: E402

bootstrap(Path("/tmp/ledger"), Path("/tmp/reference.json"), development=True)
from app.api import documents, qa  # noqa: E402
from app.main import app  # noqa: E402

qa.vector_store = documents.vector_store = VectorFixture()
qa.qa_engine = EngineFixture()


@app.get("/api/__fixture/status")
def status():
    with lock:
        return dict(state)


def deny_network(*args, **kwargs):
    raise OSError("Synthetic backend cannot make outbound connections")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app, host="0.0.0.0", port=8000, workers=1, access_log=False,
        log_level="critical", proxy_headers=True,
        forwarded_allow_ips="172.30.245.3",
    )
