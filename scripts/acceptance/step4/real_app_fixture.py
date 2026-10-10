"""Temporary Step 4 fixture: current FastAPI app with local QA doubles."""

import json
import os
import sys
import time
import types
from pathlib import Path

# The Windows validation environment has chromadb but not the optional
# langchain-chroma adapter. The real app only needs the symbol at import time
# because this fixture replaces the constructed vector store before requests.
if "langchain_chroma" not in sys.modules:
    chroma_module = types.ModuleType("langchain_chroma")
    chroma_module.Chroma = type("Chroma", (), {})
    sys.modules["langchain_chroma"] = chroma_module

from app.core.anonymous_session import bootstrap

_storage = Path(os.environ["QUOTA_STORAGE_PATH"])
_reference = Path(os.environ["ANONYMOUS_STORE_REFERENCE"])
if not _storage.exists() and not _reference.exists():
    bootstrap(_storage, _reference, development=True)

# Bootstrap the isolated ledger before importing the application.
from app.api import qa  # noqa: E402
from app.main import app  # noqa: E402,F401 -- exported for Uvicorn
from app.models.schemas import QuestionResponse  # noqa: E402

EVIDENCE = Path("D:/claudeCode/rag_kb-deploy/.step4-evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)


class VectorFixture:
    def get_collection_info(self):
        return {"document_count": 1}


class EngineFixture:
    def ask(self, **kwargs):
        question = kwargs["question"]
        started = time.monotonic()
        with (EVIDENCE / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": "start", "question": question}) + "\n")
        if question == "slow":
            time.sleep(4)
        elif question == "timeout":
            time.sleep(70)
        with (EVIDENCE / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": "finish",
                        "question": question,
                        "elapsed": time.monotonic() - started,
                    }
                )
                + "\n"
            )
        return QuestionResponse(answer="fixture answer", sources=[], processing_time=0)


qa.vector_store = VectorFixture()
qa.qa_engine = EngineFixture()
