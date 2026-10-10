"""Step 3: real HTTP routes and LangChain, with offline provider boundaries."""

import ast
import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.api import qa
from app.api.auth import require_admin
from app.core import (
    anonymous_session,
    cached_embeddings,
    concurrency,
    qa_engine,
    vector_store,
)
from app.core.anonymous_session import SessionError, bootstrap
from app.core.cache_manager import CacheManager
from app.core.cached_embeddings import CachedEmbeddings
from app.core.config import Settings, settings
from app.core.global_budget import in_question_budget, question_budget
from app.main import app


class OfflineRetriever(BaseRetriever):
    embeddings: CachedEmbeddings
    documents: list[Document]

    def _get_relevant_documents(self, query, *, run_manager):
        self.embeddings.embed_query(query)
        return self.documents


@pytest.fixture
def contract(tmp_path, monkeypatch):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    bootstrap(storage, reference, development=True)
    overrides = {
        "quota_storage_path": str(storage),
        "anonymous_store_reference": str(reference),
        "anonymous_storage_development": True,
        "enable_quota_limit": True,
        "default_daily_quota": 5,
        "global_daily_ask_limit": 100,
        "global_daily_default_llm_limit": 100,
        "global_daily_llm_limit": 100,
        "global_daily_query_embedding_limit": 100,
        "quota_timezone": "UTC",
        "enable_qa_cache": True,
    }
    for name, value in overrides.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(Settings, "get_api_key", lambda self: "test-only-key")
    monkeypatch.setattr(concurrency, "_llm_semaphore", None)
    cache = CacheManager(str(tmp_path / "cache" / "test.db"))
    monkeypatch.setattr(cached_embeddings, "cache_manager", cache)
    monkeypatch.setattr(qa_engine, "cache_manager", cache)
    embedding_provider = Mock()
    embedding_provider.embed_query.return_value = [1.0, 0.0]
    embeddings = CachedEmbeddings(embedding_provider, "offline-embedding")
    documents = [
        Document(
            page_content="Test evidence",
            metadata={"filename": "test.txt", "document_id": str(uuid.uuid4())},
        )
    ]
    retriever = OfflineRetriever(embeddings=embeddings, documents=documents)
    vector = Mock()
    vector.get_collection_info.return_value = {"document_count": 1}
    vector.as_retriever.return_value = retriever
    vector.similarity_search.side_effect = lambda query, **kw: retriever.invoke(query)
    vector.similarity_search_with_score.side_effect = lambda query, **kw: [
        (doc, 0.1) for doc in retriever.invoke(query)
    ]
    provider = Mock()
    provider.create.return_value = {
        "model": "offline-chat",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Test answer"},
                "finish_reason": "stop",
                "index": 0,
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }

    def chat_model(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["cache"] is False
        return ChatOpenAI(client=provider, async_client=Mock(), **kwargs)

    monkeypatch.setattr(qa_engine, "ChatOpenAI", chat_model)
    monkeypatch.setattr(qa, "vector_store", vector)
    monkeypatch.setattr(qa, "qa_engine", None)
    with TestClient(app, base_url="https://testserver") as client:
        created = client.post("/api/session/anonymous", json={"transport": "header"})
        assert created.status_code == 201
        token = created.json()["token"]
        yield SimpleNamespace(
            client=client,
            ledger=app.state.anonymous_store,
            headers={"X-Anonymous-Token": token},
            identity=app.state.anonymous_store.resolve(token),
            provider=provider,
            embedding_provider=embedding_provider,
            embeddings=embeddings,
            vector=vector,
            cache=cache,
            storage=storage,
        )


def ask(contract, *, question="Test question", byok=False, **payload):
    headers = dict(contract.headers)
    if byok:
        headers["LLM-Api-Key"] = "byok-test-only"
    return contract.client.post(
        "/api/qa/ask", json={"question": question, **payload}, headers=headers
    )


def counts(contract):
    return contract.ledger.budget_snapshot(settings.budget_limits())["counts"]


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    return detail


def test_sixth_default_ask_denied_and_cache_counts_only_real_calls(contract):
    request_ids = set()
    for index in range(5):
        response = ask(contract)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert response.headers["Cache-Control"] == "no-store"
        assert body["from_cache"] == (index > 0)
        request_ids.add(body["request_id"])
    assert len(request_ids) == 5
    before = copy.deepcopy(contract.ledger.state)
    detail = assert_error(ask(contract), 429, "quota_exceeded")
    assert detail["reset_at"] == contract.ledger.reset_at()
    assert contract.ledger.state == before
    assert counts(contract)["ask_default"] == 5
    assert counts(contract)["llm_default"] == 1
    assert counts(contract)["query_embedding_default"] == 1
    assert contract.provider.create.call_count == 1
    assert contract.embedding_provider.embed_query.call_count == 1
    quota = contract.client.get("/api/qa/quota", headers=contract.headers)
    assert quota.status_code == 200
    assert quota.json()["used_count"] == 5
    assert quota.json()["remaining"] == 0
    assert quota.json()["request_id"] == quota.headers["X-Request-ID"]
    assert quota.json()["reset_at"] == quota.json()["global_budget"]["reset_at"]
    assert set(quota.json()["global_budget"]) == {"status", "reset_at"}
    second = contract.client.post(
        "/api/session/anonymous", json={"transport": "header"}
    ).json()["token"]
    assert (
        contract.client.get(
            "/api/qa/quota", headers={"X-Anonymous-Token": second}
        ).json()["used_count"]
        == 0
    )


def test_byok_keeps_personal_count_and_uses_shared_ask_budget(contract, monkeypatch):
    monkeypatch.setattr(settings, "global_daily_ask_limit", 2)
    assert ask(contract).status_code == 200
    assert ask(contract, question="BYOK question", byok=True).status_code == 200
    quota = contract.client.get(
        "/api/qa/quota", headers={**contract.headers, "LLM-Api-Key": "byok-test-only"}
    ).json()
    assert quota["used_count"] == 1
    assert quota["quota_enabled"] is True
    assert quota["daily_limit"] is None and quota["remaining"] is None
    assert quota["global_budget"]["status"] == "exhausted"
    before = counts(contract)
    assert_error(ask(contract, byok=True), 503, "global_budget_exceeded")
    assert counts(contract) == before
    assert before == {
        "ask_default": 1,
        "ask_byok": 1,
        "llm_default": 1,
        "llm_byok": 1,
        "query_embedding_default": 1,
        "query_embedding_byok": 1,
    }


@pytest.mark.parametrize("byok", [False, True])
@pytest.mark.parametrize("failure", ["chat", "embedding", "empty_chat"])
def test_provider_failure_is_counted_without_refund(contract, byok, failure):
    if failure == "chat":
        contract.provider.create.side_effect = RuntimeError("private-provider-error")
    elif failure == "embedding":
        contract.embedding_provider.embed_query.side_effect = RuntimeError(
            "private-provider-error"
        )
    else:
        contract.provider.create.return_value["choices"][0]["message"]["content"] = ""
    response = ask(contract, byok=byok)
    assert_error(response, 502, "upstream_error")
    assert "private-provider-error" not in response.text
    suffix = "byok" if byok else "default"
    assert counts(contract)[f"ask_{suffix}"] == 1
    assert counts(contract)[f"query_embedding_{suffix}"] == 1
    assert counts(contract)[f"llm_{suffix}"] == (failure != "embedding")
    assert contract.embedding_provider.embed_query.call_count == 1
    assert contract.provider.create.call_count == (failure != "embedding")
    assert contract.ledger.personal_count(contract.identity) == (not byok)


@pytest.mark.parametrize("boundary", ["admit", "query_embedding", "llm"])
@pytest.mark.parametrize("after_replace", [False, True])
def test_storage_failure_prevents_next_provider_call(
    contract, monkeypatch, boundary, after_replace
):
    original = anonymous_session._write_atomic

    def fail_write(path, state, development):
        budget = state["days"][contract.ledger._day()].get("budget", {})
        key = "ask_default" if boundary == "admit" else f"{boundary}_default"
        if budget.get(key, 0):
            if after_replace:
                original(path, state, development)
            raise OSError("simulated persistence failure")
        original(path, state, development)

    monkeypatch.setattr(anonymous_session, "_write_atomic", fail_write)
    assert_error(ask(contract), 503, "quota_storage_unavailable")
    assert contract.provider.create.call_count == 0
    assert contract.embedding_provider.embed_query.call_count == (boundary == "llm")
    assert not contract.ledger.healthy
    daily = contract.ledger.state["days"][contract.ledger._day()]
    assert daily.get("budget", {}).get("ask_default", 0) == (boundary != "admit")
    disk = json.loads((contract.storage / "quota-state-v1.json").read_text())
    key = "ask_default" if boundary == "admit" else f"{boundary}_default"
    assert disk["days"][contract.ledger._day()].get("budget", {}).get(key, 0) == (
        1 if after_replace else 0
    )
    assert_error(ask(contract), 503, "quota_storage_unavailable")
    assert contract.provider.create.call_count == 0


@pytest.mark.parametrize("scoped", [False, True])
def test_retrieval_does_not_swallow_budget_errors(contract, scoped):
    error = SessionError("global_budget_exceeded", 503, 1)
    contract.vector.similarity_search.side_effect = error
    contract.vector.similarity_search_with_score.side_effect = error
    payload = {"document_id": str(uuid.uuid4())} if scoped else {}
    assert_error(ask(contract, **payload), 503, "global_budget_exceeded")
    assert counts(contract)["ask_default"] == 1
    contract.provider.create.assert_not_called()


def test_exhausted_model_budget_rejects_even_cached_answer(contract, monkeypatch):
    monkeypatch.setattr(settings, "global_daily_default_llm_limit", 1)
    assert ask(contract).status_code == 200
    assert_error(ask(contract), 503, "global_budget_exceeded")
    assert counts(contract)["ask_default"] == 1
    quota = contract.client.get("/api/qa/quota", headers=contract.headers).json()
    assert quota["global_budget"]["status"] == "exhausted"
    assert ask(contract, question="Allowed BYOK", byok=True).status_code == 200


def test_competing_request_exhausts_llm_after_admission(contract, monkeypatch):
    monkeypatch.setattr(settings, "global_daily_llm_limit", 1)

    def consume_budget(text):
        contract.ledger.record_attempt(
            "llm", byok=True, limits=settings.budget_limits()
        )
        return [1.0, 0.0]

    contract.embedding_provider.embed_query.side_effect = consume_budget
    assert_error(ask(contract), 503, "global_budget_exceeded")
    assert counts(contract)["ask_default"] == 1
    assert counts(contract)["query_embedding_default"] == 1
    assert counts(contract)["llm_default"] == 0
    assert counts(contract)["llm_byok"] == 1
    contract.provider.create.assert_not_called()


def test_qa_cache_hit_still_counts_a_new_embedding_miss(contract, monkeypatch):
    assert ask(contract).status_code == 200
    monkeypatch.setattr(contract.cache, "get_embedding_cache", lambda *args: None)
    response = ask(contract)
    assert response.status_code == 200
    assert response.json()["from_cache"] is True
    assert counts(contract)["ask_default"] == 2
    assert counts(contract)["llm_default"] == 1
    # Both nearest and diversity retrieval are needed to identify cached evidence.
    assert counts(contract)["query_embedding_default"] == 3
    assert contract.embedding_provider.embed_query.call_count == 3


def test_admin_snapshots_and_reset_preserve_global_budget(
    contract, monkeypatch, caplog
):
    assert ask(contract).status_code == 200
    before = counts(contract)
    monkeypatch.setitem(
        app.dependency_overrides, require_admin, lambda: {"sub": "test-admin"}
    )
    for path in ("budget", "quota/stats"):
        response = contract.client.get(f"/api/qa/{path}")
        assert response.status_code == 200
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert response.headers["Cache-Control"] == "no-store"
        assert contract.headers["X-Anonymous-Token"] not in response.text
        assert "expires_at" not in response.text
        if path == "budget":
            assert response.json()["counts"] == before
            assert response.json()["usage"] is None
        else:
            assert response.json()["quotas"] == [
                {
                    "quota_ref": contract.identity["quota_ref"],
                    "used_count": 1,
                    "daily_limit": 5,
                }
            ]
    payload = {"quota_ref": contract.identity["quota_ref"], "reason": "private-reason"}
    with caplog.at_level("INFO", logger="app.api.qa"):
        for _ in range(2):
            response = contract.client.post("/api/qa/quota/reset", json=payload)
            assert response.status_code == 200
            assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "actor=test-admin" in caplog.text
    assert "private-reason" not in caplog.text
    assert counts(contract) == before
    assert contract.ledger.personal_count(contract.identity) == 0
    assert_error(
        contract.client.post(
            "/api/qa/quota/reset", json={**payload, "quota_ref": "0" * 64}
        ),
        404,
        "quota_not_found",
    )


@pytest.mark.parametrize("path", ["budget", "quota/stats", "quota/reset"])
def test_anonymous_token_cannot_manage_budget(contract, path):
    method = "POST" if path == "quota/reset" else "GET"
    response = contract.client.request(
        method, f"/api/qa/{path}", headers=contract.headers
    )
    assert response.status_code == 401


def test_empty_library_and_missing_default_key_do_not_charge(contract, monkeypatch):
    contract.vector.get_collection_info.return_value = {"document_count": 0}
    assert_error(ask(contract), 503, "knowledge_base_unavailable")
    contract.vector.get_collection_info.return_value = {"document_count": 1}
    monkeypatch.setattr(Settings, "get_api_key", lambda self: None)
    assert_error(ask(contract), 503, "service_unavailable")
    assert all(value == 0 for value in counts(contract).values())
    contract.provider.create.assert_not_called()
    contract.embedding_provider.embed_query.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": " "},
        {"question": "x" * 2001},
        {"question": 42},
        {"question": "Test", "max_sources": True},
        {"question": "Test", "max_sources": 1.0},
        {"question": "Test", "max_sources": "1"},
        {"question": "Test", "max_sources": 0},
        {"question": "Test", "max_sources": 6},
        {"question": "Test", "document_id": "not-a-uuid"},
        {"question": "Test", "quota_ref": "0" * 64},
        {"question": "Test", "max_tokens": 10000},
    ],
)
def test_invalid_payload_never_admitted(contract, payload):
    response = contract.client.post(
        "/api/qa/ask", json=payload, headers=contract.headers
    )
    assert_error(response, 400, "invalid_request")
    assert all(value == 0 for value in counts(contract).values())
    contract.provider.create.assert_not_called()
    contract.embedding_provider.embed_query.assert_not_called()


@pytest.mark.parametrize("path", ["ask", "quota"])
@pytest.mark.parametrize(
    "headers",
    [
        {"LLM-Api-Key": " "},
        {"LLM-Model": "other-model"},
        {"LLM-Provider": "openai"},
        {"LLM-Base-URL": "https://example.invalid/v1"},
        {"LLM-Api-Key": "test", "LLM-Provider": "unknown"},
        {"LLM-Api-Key": "test", "LLM-Base-URL": "http://127.0.0.1/v1"},
    ],
)
def test_invalid_byok_never_falls_back_or_charges(contract, path, headers):
    method = "POST" if path == "ask" else "GET"
    response = contract.client.request(
        method,
        f"/api/qa/{path}",
        json={"question": "Test"} if path == "ask" else None,
        headers={**contract.headers, **headers},
    )
    assert_error(response, 400, "invalid_request")
    assert all(value == 0 for value in counts(contract).values())
    contract.provider.create.assert_not_called()
    contract.embedding_provider.embed_query.assert_not_called()


def test_invalid_json_is_redacted_and_never_admitted(contract):
    response = contract.client.post(
        "/api/qa/ask",
        content='{"question": "private-input",',
        headers={**contract.headers, "Content-Type": "application/json"},
    )
    assert_error(response, 400, "invalid_request")
    assert "private-input" not in response.text
    assert all(value == 0 for value in counts(contract).values())


@pytest.mark.parametrize("provider_name", ["openai", "qwen", "zhipu"])
def test_embedding_sdk_sends_one_unsplit_query_without_retries(
    contract, monkeypatch, provider_name
):
    provider = Mock()
    provider.create.return_value = {"data": [{"embedding": [1.0, 0.0]}]}

    def embeddings_model(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["check_embedding_ctx_length"] is False
        return OpenAIEmbeddings(client=provider, async_client=Mock(), **kwargs)

    monkeypatch.setattr(vector_store, "OpenAIEmbeddings", embeddings_model)
    monkeypatch.setattr(Settings, "get_embedding_api_key", lambda self: "test-only")
    monkeypatch.setattr(
        Settings,
        "get_model_config",
        lambda self: {
            "embedding_provider": provider_name,
            "embedding_model": "text-embedding-3-small",
            "embedding_api_base_url": "https://example.invalid/v1",
        },
    )
    vector = object.__new__(vector_store.VectorStore)
    vector._initialize_embeddings()
    query = "查询" * 1000
    with question_budget(contract.ledger, byok=False, limits=settings.budget_limits()):
        assert vector.embeddings.embed_query(query) == [1.0, 0.0]
    assert provider.create.call_count == 1
    assert provider.create.call_args.kwargs["input"] == query
    assert counts(contract)["query_embedding_default"] == 1


def test_production_paid_probes_disabled_and_shallow_probe_is_free(
    contract, monkeypatch
):
    monkeypatch.setattr(settings, "anonymous_storage_development", False)
    monkeypatch.setitem(
        app.dependency_overrides, require_admin, lambda: {"sub": "test"}
    )
    engine = Mock()
    engine.health_check.return_value = {"status": "healthy"}
    monkeypatch.setattr(qa, "get_qa_engine", lambda: engine)
    assert_error(
        contract.client.post("/api/qa/search", json={"question": "Test"}),
        403,
        "feature_disabled",
    )
    for query in ("deep=true", "with_qa=true"):
        assert_error(
            contract.client.get(f"/api/qa/health?{query}"), 403, "feature_disabled"
        )
    assert contract.client.get("/api/qa/health").status_code == 200
    engine.health_check.assert_called_once_with(deep=False, with_qa=None)
    assert all(value == 0 for value in counts(contract).values())


def test_budget_context_restores_after_error(contract):
    assert not in_question_budget()
    with pytest.raises(RuntimeError):
        with question_budget(
            contract.ledger, byok=False, limits=settings.budget_limits()
        ):
            assert in_question_budget()
            raise RuntimeError("test")
    assert not in_question_budget()


@pytest.mark.parametrize("operation", ["embedding", "ask", "chat_callback"])
def test_production_missing_context_blocks_provider(contract, monkeypatch, operation):
    from app.core.global_budget import ChatAttemptCallback

    monkeypatch.setattr(settings, "anonymous_storage_development", False)
    engine = qa_engine.QAEngine(contract.vector)
    with pytest.raises(SessionError, match="service_unavailable"):
        if operation == "embedding":
            contract.embeddings.embed_query("missing context")
        elif operation == "ask":
            engine.ask("missing context")
        else:
            engine.llm.invoke(
                "missing context", config={"callbacks": [ChatAttemptCallback()]}
            )
    contract.embedding_provider.embed_query.assert_not_called()
    contract.provider.create.assert_not_called()


def test_context_lost_in_worker_is_not_an_offline_permission(contract, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(settings, "anonymous_storage_development", False)
    with question_budget(contract.ledger, byok=False, limits=settings.budget_limits()):
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = executor.submit(contract.embeddings.embed_query, "lost context")
            with pytest.raises(SessionError, match="service_unavailable"):
                task.result()
    contract.embedding_provider.embed_query.assert_not_called()


def test_http_worker_missing_budget_scope_fails_closed(contract, monkeypatch):
    from contextlib import nullcontext

    from app.core import global_budget

    monkeypatch.setattr(settings, "anonymous_storage_development", False)
    monkeypatch.setattr(
        global_budget, "question_budget", lambda *a, **kw: nullcontext()
    )
    assert_error(ask(contract), 503, "service_unavailable")
    assert counts(contract)["ask_default"] == 1  # Admission is not refunded.
    assert counts(contract)["llm_default"] == 0
    assert counts(contract)["query_embedding_default"] == 0
    contract.embedding_provider.embed_query.assert_not_called()
    contract.provider.create.assert_not_called()


def test_explicit_offline_scope_restores_and_cannot_bypass_ledger(
    contract, monkeypatch
):
    from app.core.global_budget import offline_provider_access

    monkeypatch.setattr(settings, "anonymous_storage_development", False)
    with offline_provider_access(reason="isolated offline evaluation"):
        assert contract.embeddings.embed_query("offline") == [1.0, 0.0]
        with question_budget(
            contract.ledger, byok=True, limits=settings.budget_limits()
        ):
            contract.embeddings.embed_query("public question")
    assert counts(contract)["query_embedding_byok"] == 1
    with pytest.raises(SessionError):
        contract.embeddings.embed_query("outside scope")


@pytest.mark.parametrize("path", ["ask", "quota"])
def test_byok_host_prefix_attack_is_rejected_before_admission(
    contract, monkeypatch, path
):
    monkeypatch.setattr(settings, "allowed_chat_base_urls", "https://allowed.example")
    response = contract.client.request(
        "POST" if path == "ask" else "GET",
        f"/api/qa/{path}",
        json={"question": "Test"} if path == "ask" else None,
        headers={
            **contract.headers,
            "LLM-Api-Key": "test-only",
            "LLM-Base-URL": "https://allowed.example.untrusted.invalid/v1",
        },
    )
    assert_error(response, 400, "invalid_request")
    assert not any(counts(contract).values())
    contract.provider.create.assert_not_called()
    contract.embedding_provider.embed_query.assert_not_called()


@pytest.mark.parametrize(
    "path", ["upload", "upload?async_processing=true", "upload-async", "batch-upload"]
)
def test_closed_maintenance_rejects_admin_before_any_work(contract, monkeypatch, path):
    from fastapi import BackgroundTasks

    from app.api import documents

    monkeypatch.setattr(settings, "enable_document_maintenance", False)
    monkeypatch.setitem(
        app.dependency_overrides, require_admin, lambda: {"sub": "test"}
    )
    processor, vector, submit, enqueue = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(documents, "doc_processor", processor)
    monkeypatch.setattr(documents, "get_vector_store", vector)
    monkeypatch.setattr(documents.async_processor, "submit_task", submit)
    monkeypatch.setattr(BackgroundTasks, "add_task", enqueue)
    field = "files" if path == "batch-upload" else "file"
    response = contract.client.post(
        f"/api/documents/{path}", files={field: ("test.txt", b"test", "text/plain")}
    )
    assert_error(response, 403, "feature_disabled")
    assert not processor.mock_calls
    vector.assert_not_called()
    submit.assert_not_called()
    enqueue.assert_not_called()
    assert not any(counts(contract).values())


def test_document_embedding_requires_window_or_explicit_offline_scope(
    contract, monkeypatch
):
    from app.core.global_budget import offline_provider_access

    monkeypatch.setattr(settings, "enable_document_maintenance", False)
    contract.embedding_provider.embed_documents.return_value = [[1.0, 0.0]]
    with pytest.raises(SessionError, match="feature_disabled"):
        contract.embeddings.embed_documents(["maintenance document"])
    contract.embedding_provider.embed_documents.assert_not_called()
    monkeypatch.setattr(settings, "enable_document_maintenance", True)
    assert contract.embeddings.embed_documents(["maintenance document"]) == [[1.0, 0.0]]
    with question_budget(contract.ledger, byok=False, limits=settings.budget_limits()):
        with pytest.raises(SessionError, match="feature_disabled"):
            contract.embeddings.embed_documents(["public request cannot import"])
    monkeypatch.setattr(settings, "enable_document_maintenance", False)
    with offline_provider_access(reason="isolated offline import"):
        contract.embeddings.embed_documents(["offline document"])
    assert not any(counts(contract).values())


def test_queued_maintenance_rechecks_window_before_processing(contract, monkeypatch):
    import asyncio

    from app.api import documents
    from app.core import async_processor, document_processor, job_status

    monkeypatch.setattr(settings, "enable_document_maintenance", False)
    processor, jobs = Mock(), Mock()
    monkeypatch.setattr(documents, "doc_processor", processor)
    monkeypatch.setattr(document_processor, "doc_processor", processor)
    monkeypatch.setattr(documents, "job_status", jobs)
    monkeypatch.setattr(job_status, "job_status", jobs)
    worker = async_processor.async_processor
    enqueue = Mock()
    monkeypatch.setattr(worker.executor, "submit", enqueue)
    with pytest.raises(SessionError, match="feature_disabled"):
        worker.submit_task("test-job", "unused", "test.txt")
    enqueue.assert_not_called()
    result = worker._process_document_safe("test-job", "unused", "test.txt")
    assert not result["success"]
    asyncio.run(documents.process_document_background("unused", "test.txt", "test-job"))
    assert not processor.mock_calls
    contract.embedding_provider.embed_documents.assert_not_called()


@pytest.mark.parametrize("byok", [False, True])
def test_messages_fit_cost_cap_and_citations_match_selected_evidence(contract, byok):
    import httpx

    from app.core.question_cost import MAX_MESSAGES_BYTES

    docs = [
        Document(
            page_content="too-large" * 6000, metadata={"filename": "oversized.txt"}
        ),
        *[
            Document(
                page_content=f"evidence-{i}:" + '中文"\\\n' * 650,
                metadata={"filename": f"file-{i}.txt"},
            )
            for i in range(5)
        ],
    ]
    contract.vector.as_retriever.return_value.documents = docs
    question = "保留完整问题" * 300
    response = ask(contract, byok=byok, question=question, max_sources=5)
    assert response.status_code == 200
    payload = contract.provider.create.call_args.kwargs
    messages = payload["messages"]
    assert (
        len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        <= MAX_MESSAGES_BYTES
    )
    assert (
        len(httpx.Request("POST", "https://test.invalid", json=messages).content)
        <= MAX_MESSAGES_BYTES
    )
    assert payload["max_tokens"] <= 800
    content = messages[0]["content"]
    assert question in content
    sources = response.json()["sources"]
    assert 0 < len(sources) < 5
    assert sources[0]["document_name"] == "file-0.txt"
    for source in sources:
        assert source["content"] in content
        assert (
            next(
                d.page_content
                for d in docs
                if d.metadata["filename"] == source["document_name"]
            )
            == source["content"]
        )
    selected = {source["document_name"] for source in sources}
    for doc in docs:
        if doc.metadata["filename"] not in selected:
            assert doc.page_content not in content
    cached = ask(contract, byok=byok, question=question, max_sources=5)
    assert cached.json()["from_cache"] is True
    assert cached.json()["sources"] == sources
    assert contract.provider.create.call_count == 1
    # A change beyond the old 200-character hash prefix must miss the QA cache.
    docs[1].page_content = docs[1].page_content[:-1] + "新"
    changed = ask(contract, byok=byok, question=question, max_sources=5)
    assert changed.status_code == 200
    assert changed.json()["from_cache"] is False
    assert contract.provider.create.call_count == 2


def test_oversized_complete_messages_rejected_at_chat_boundary(contract):
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.core.global_budget import ChatAttemptCallback

    engine = qa_engine.QAEngine(contract.vector)
    with question_budget(contract.ledger, byok=False, limits=settings.budget_limits()):
        with pytest.raises(SessionError, match="invalid_request"):
            engine.llm.invoke(
                [
                    SystemMessage(content="policy" * 4000),
                    HumanMessage(content="上下文" * 1500),
                ],
                config={"callbacks": [ChatAttemptCallback()]},
            )
    contract.provider.create.assert_not_called()
    assert counts(contract)["llm_default"] == 0


@pytest.mark.parametrize("value", [0, -1, 801, 2000, True, 1.5, "801", "1.0"])
def test_output_limit_configuration_rejects_values_outside_hard_cap(value):
    with pytest.raises(ValueError, match="llm_max_tokens"):
        Settings(_env_file=None, llm_max_tokens=value)


@pytest.mark.parametrize("value", [1, 800, "800"])
def test_output_limit_configuration_accepts_reduced_or_exact_cap(value):
    assert Settings(_env_file=None, llm_max_tokens=value).llm_max_tokens == int(value)


def test_document_maintenance_defaults_closed():
    assert Settings.model_fields["enable_document_maintenance"].default is False


@pytest.mark.parametrize(
    "field",
    [
        "default_daily_quota",
        "global_daily_ask_limit",
        "global_daily_default_llm_limit",
        "global_daily_llm_limit",
        "global_daily_query_embedding_limit",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "0", "1.0"])
def test_invalid_daily_configuration_is_rejected(field, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


def test_timezone_and_production_personal_quota_checked_at_startup(
    contract, monkeypatch
):
    monkeypatch.setattr(settings, "quota_timezone", "Asia/Shanghai")
    with pytest.raises(ValueError, match="timezone UTC"):
        with TestClient(app):
            pass
    monkeypatch.setattr(settings, "quota_timezone", "UTC")
    monkeypatch.setattr(settings, "anonymous_storage_development", False)
    monkeypatch.setattr(settings, "enable_quota_limit", False)
    with pytest.raises(ValueError, match="personal quota"):
        with TestClient(app):
            pass


def test_all_literal_session_error_codes_have_public_messages():
    root = Path(__file__).resolve().parents[1] / "app"
    handler = ast.parse((root / "api" / "anonymous_session.py").read_text("utf-8"))
    messages = next(
        node.value
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "messages" for t in node.targets)
    )
    codes = {key.value for key in messages.keys}
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SessionError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in codes, path


def test_identity_rate_windows_reject_without_budget_admission(contract, monkeypatch):
    monkeypatch.setattr(settings, "max_ask_requests_per_minute", 2)
    monkeypatch.setattr(settings, "max_quota_requests_per_minute", 2)
    assert ask(contract, question="rate one").status_code == 200
    assert ask(contract, question="rate two").status_code == 200
    denied = ask(contract, question="rate three")
    assert_error(denied, 429, "rate_limited")
    assert denied.headers["Retry-After"] == str(
        denied.json()["detail"]["retry_after_seconds"]
    )
    assert counts(contract)["ask_default"] == 2
    for _ in range(2):
        assert (
            contract.client.get("/api/qa/quota", headers=contract.headers).status_code
            == 200
        )
    quota = contract.client.get("/api/qa/quota", headers=contract.headers)
    assert_error(quota, 429, "rate_limited")


def test_session_ip_window_limits_reuse_without_creating_identity(
    contract, monkeypatch
):
    monkeypatch.setattr(settings, "max_session_requests_per_minute", 2)
    reused = contract.client.post(
        "/api/session/anonymous",
        json={"transport": "header"},
        headers=contract.headers,
    )
    assert reused.status_code == 200
    limited = contract.client.post(
        "/api/session/anonymous",
        json={"transport": "header"},
        headers=contract.headers,
    )
    assert_error(limited, 429, "rate_limited")
    assert contract.ledger.resolve(contract.headers["X-Anonymous-Token"])
    assert not any(counts(contract).values())


def test_global_question_gate_applies_across_identities(contract, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    started = threading.Event()
    release = threading.Event()
    response = contract.provider.create.return_value

    def blocked_provider(**kwargs):
        started.set()
        assert release.wait(5)
        return response

    monkeypatch.setattr(settings, "max_concurrent_llm_requests", 1)
    contract.provider.create.side_effect = blocked_provider
    other = contract.client.post("/api/session/anonymous", json={"transport": "header"})
    assert other.status_code == 201
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(ask, contract, question="global slot owner")
        try:
            assert started.wait(5)
            denied = contract.client.post(
                "/api/qa/ask",
                json={"question": "different identity"},
                headers={"X-Anonymous-Token": other.json()["token"]},
            )
            assert_error(denied, 503, "service_busy")
            assert counts(contract)["ask_default"] == 1
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 200


def test_timed_out_question_keeps_worker_slots_until_thread_exits(
    contract, monkeypatch
):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    started = threading.Event()
    release = threading.Event()
    response = contract.provider.create.return_value

    def blocked_provider(**kwargs):
        started.set()
        assert release.wait(5)
        return response

    contract.provider.create.side_effect = blocked_provider
    monkeypatch.setattr(settings, "question_deadline_seconds", 0.2)
    monkeypatch.setattr(settings, "max_ask_requests_per_minute", 20)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(ask, contract, question="held question")
        try:
            assert started.wait(5)
            denied = ask(contract, question="concurrent question")
            assert_error(denied, 503, "service_busy")
            timed_out = pending.result(timeout=5)
            assert_error(timed_out, 504, "upstream_timeout")
            denied_again = ask(contract, question="still held question")
            assert_error(denied_again, 503, "service_busy")
            assert counts(contract)["ask_default"] == 1
        finally:
            release.set()
    for _ in range(100):
        if concurrency.get_llm_gate().active == 0:
            break
        time.sleep(0.01)
    assert concurrency.get_llm_gate().active == 0
    assert contract.ledger.personal_count(contract.identity) == 1
    assert ask(contract, question="after worker exits").status_code == 200


def test_sdk_provider_timeouts_use_remaining_question_deadline(contract, monkeypatch):
    import httpx

    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "test-embedding",
                    "data": [{"object": "embedding", "index": 0, "embedding": [1, 0]}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Test answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            },
        )

    transport = httpx.MockTransport(respond)
    embedding_client = httpx.Client(transport=transport)
    chat_client = httpx.Client(transport=transport, follow_redirects=False)
    monkeypatch.setattr(settings, "question_deadline_seconds", 1)
    contract.embeddings.base_embeddings = OpenAIEmbeddings(
        api_key="test-only",
        model="test-embedding",
        max_retries=0,
        check_embedding_ctx_length=False,
        http_client=embedding_client,
    )
    engine = qa_engine.QAEngine(contract.vector)
    engine.llm = ChatOpenAI(
        api_key="test-only",
        model="test-model",
        max_retries=0,
        http_client=chat_client,
    )
    monkeypatch.setattr(qa, "qa_engine", engine)
    try:
        assert ask(contract, question="SDK deadline question").status_code == 200
        assert len(requests) >= 2
        for request in requests:
            assert 0 < request.extensions["timeout"]["read"] <= 1
    finally:
        embedding_client.close()
        chat_client.close()


def test_cancelled_http_ask_holds_worker_slots(contract, monkeypatch):
    import asyncio
    import threading
    import time

    import httpx

    started = threading.Event()
    release = threading.Event()
    response = contract.provider.create.return_value

    def blocked_provider(**kwargs):
        started.set()
        assert release.wait(5)
        return response

    contract.provider.create.side_effect = blocked_provider
    monkeypatch.setattr(settings, "max_ask_requests_per_minute", 20)

    async def cancel_request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            pending = asyncio.create_task(
                client.post(
                    "/api/qa/ask",
                    json={"question": "cancelled question"},
                    headers=contract.headers,
                )
            )
            assert await asyncio.to_thread(started.wait, 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            denied = await client.post(
                "/api/qa/ask",
                json={"question": "while cancelled worker runs"},
                headers=contract.headers,
            )
            assert_error(denied, 503, "service_busy")

    try:
        asyncio.run(cancel_request())
        assert counts(contract)["ask_default"] == 1
    finally:
        release.set()
    for _ in range(100):
        if concurrency.get_llm_gate().active == 0:
            break
        time.sleep(0.01)
    assert concurrency.get_llm_gate().active == 0
