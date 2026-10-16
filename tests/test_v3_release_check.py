"""Synthetic HTTP only; actual ASGI, model SDK and persisted Chroma workflows."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from scripts.acceptance.step5 import v3_release_check as runner
from scripts.acceptance.step5.paid_model_comparison import ROOT, public_inputs


def test_regression_then_gated_rebuild(tmp_path, monkeypatch):
    from app.api import qa
    from app.core.anonymous_session import bootstrap
    from app.core.cache_manager import CacheManager
    from app.core.config import settings
    from app.core.vector_store import VectorStore

    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    bootstrap(
        runner.STATE / "ledger",
        runner.STATE / "reference/anonymous-store-reference.json",
        development=True,
    )
    monkeypatch.setattr(VectorStore, "_instance", None)
    monkeypatch.setattr(qa, "vector_store", None)
    monkeypatch.setattr(qa, "qa_engine", None)
    cache = CacheManager(str(tmp_path / "cache/cache.db"))
    monkeypatch.setattr("app.core.cached_embeddings.cache_manager", cache)
    monkeypatch.setattr("app.core.qa_engine.cache_manager", cache)
    key = tmp_path / "synthetic-key"
    key.write_text("synthetic", encoding="utf-8")
    output = tmp_path / "regression"
    output.mkdir()
    args = SimpleNamespace(
        workflow="v3-regression",
        chat_key=key,
        embedding_key=key,
        output=output,
        review=None,
    )
    chunks, questions, _ = public_inputs()
    report = {
        "workflow": "v3-regression",
        "planned_max_micros": 11_183_552,
        "run_cap_micros": 12_000_000,
        "questions_sha256": runner.digest(ROOT / "docs/demo-v0.1.0/questions.json"),
        "corpus_manifest_sha256": runner.digest(
            ROOT / "docs/demo-v0.1.0/manifest.json"
        ),
    }

    def response(transport, request):
        body = json.loads(request.content)
        if "input" in body:
            texts = body["input"]
            texts = [texts] if isinstance(texts, str) else texts
            payload = {
                "data": [
                    {"index": i, "embedding": [0.1] * 1024} for i in range(len(texts))
                ]
            }
        else:
            payload = {
                "id": "synthetic",
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "synthetic response",
                        },
                    }
                ],
            }
        return httpx.Response(200, json=payload)

    with patch.dict(settings.__dict__, settings.__dict__.copy()), patch.object(
        httpx.HTTPTransport, "handle_request", response
    ):
        runner.run_v3(args, report, chunks, questions)
        assert report["status"] == "completed"
        assert len(report["responses"]) == 5
        assert report["after"]["reserved_today"] == 11_183_552
        assert report["after"]["pending_attempts"] == 0
        summary = output / "summary.json"
        summary.write_text(json.dumps(report), encoding="utf-8")
        review = output / "review.json"
        receipt = {
            "summary_sha256": runner.digest(summary),
            "approved": True,
            "questions": [{"id": q["id"], "passed": True} for q in questions],
        }
        review.write_text(json.dumps(receipt), encoding="utf-8")
        runner.check_review(review)
        receipt["approved"] = False
        review.write_text(json.dumps(receipt), encoding="utf-8")
        with pytest.raises(ValueError):
            runner.check_review(review)
        receipt["approved"] = True
        review.write_text(json.dumps(receipt), encoding="utf-8")
        args.workflow, args.review, args.output = (
            "v3-rebuild",
            review,
            tmp_path / "release",
        )
        args.output.mkdir()
        # New build must not inherit this regression's embedding cache.
        cache = CacheManager(str(tmp_path / "fresh/cache.db"))
        monkeypatch.setattr("app.core.cached_embeddings.cache_manager", cache)
        second = {"planned_max_micros": 131_072, "run_cap_micros": 1_000_000}
        runner.run_v3(args, second, *public_inputs()[:2])
        assert second["persisted_chunks"] == 32
        assert second["attempted_reservation_micros"] == 131_072
        assert second["archive_bytes"] > 0
