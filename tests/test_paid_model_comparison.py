"""Exercise paid-runner planning and actual SDK paths without external traffic."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_core.documents import Document

from scripts.acceptance.step5 import paid_model_comparison as runner


def test_public_plan_and_exact_evidence():
    chunks, questions, upper = runner.public_inputs()
    assert len(chunks) == 32 and len(questions) == 5
    assert upper == 4_794_048 < runner.RUN_CAP
    assert runner.evidence_score(questions[0], chunks)
    assert not runner.evidence_score(
        questions[0], [Document(page_content="AtlasDesk", metadata={"file": "wrong"})]
    )
    assert runner.evidence_score(questions[-1], chunks) is None


def test_runner_real_sdk_and_chroma_use_one_ledger(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.core.vector_store import VectorStore

    output = tmp_path / "output"
    output.mkdir()
    key = tmp_path / "synthetic-key"
    key.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    original_instance = VectorStore._instance
    args = SimpleNamespace(
        initialize_ledger=True, output=output, chat_key=key, embedding_key=key
    )
    chunks, questions, upper = runner.public_inputs()
    report = {"planned_max_micros": upper}

    def response(transport, request):
        body = json.loads(request.content)
        if "input" in body:
            texts = body["input"]
            texts = [texts] if isinstance(texts, str) else texts
            payload = {
                "data": [
                    {"index": i, "embedding": [0.1] * 1024} for i in range(len(texts))
                ],
                "usage": {"total_tokens": len(texts)},
            }
        else:
            payload = {
                "id": "synthetic",
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
            }
        return httpx.Response(200, json=payload)

    try:
        with patch.dict(settings.__dict__, settings.__dict__.copy()), patch.object(
            httpx.HTTPTransport, "handle_request", response
        ):
            runner.run(args, report, chunks, questions)
    finally:
        VectorStore._instance = original_instance
    assert report["status"] == "completed"
    assert len(report["models"]) == 2
    assert report["after"]["reserved_today"] == upper
    assert report["after"]["pending_attempts"] == 0
    assert len(report["calls"]) == 77
