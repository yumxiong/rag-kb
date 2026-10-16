"""Synthetic durable ledgers + real SDK/HTTP paths; never contact providers."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import httpx
import pytest
from langchain_openai import OpenAIEmbeddings
from openai import AsyncOpenAI, OpenAI

from app.core.anonymous_session import AnonymousSessionStore, SessionError, bootstrap
from app.core.global_budget import offline_provider_access, question_budget
from app.core.money_ledger import DAILY_CAP_MICROS, MoneyLedger
from app.core.provider_budget import (
    POLICY_ID,
    AsyncBudgetedTransport,
    BudgetedTransport,
    money_ledger_scope,
    quote_request,
    register_project_ledger,
    reraise_budget_cause,
    unregister_project_ledger,
)


@pytest.fixture
def account(tmp_path):
    storage, reference = tmp_path / "data", tmp_path / "reference.json"
    bootstrap(storage, reference, development=True)
    now = [datetime(2026, 10, 16, 12, tzinfo=timezone.utc).timestamp()]
    store = AnonymousSessionStore(
        str(storage), str(reference), development=True, clock=lambda: now[0]
    )
    try:
        yield store, now
    finally:
        unregister_project_ledger(store)
        store.close()


def chat_body(**updates):
    return {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "synthetic"}],
        "max_tokens": 800,
        "thinking": {"type": "disabled"},
        **updates,
    }


def chat_request(**updates):
    return httpx.Request(
        "POST", "https://api.deepseek.com/chat/completions", json=chat_body(**updates)
    )


def success(request):
    return httpx.Response(200, json={"synthetic": True})


def test_concurrent_exact_cap_and_no_refunds(account):
    store, _ = account
    money = MoneyLedger(store)

    def attempt(_):
        try:
            return money.reserve(1_000_000, policy=POLICY_ID)
        except SessionError as error:
            assert error.code == "global_budget_exceeded"
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        ids = [x for x in pool.map(attempt, range(80)) if x]
    assert len(ids) == 50
    for identifier in ids:
        money.complete(identifier)
    assert money.snapshot()["reserved_today"] == DAILY_CAP_MICROS
    assert money.snapshot()["remaining"] == 0
    assert money.snapshot()["pending_attempts"] == 0


def test_pending_survives_midnight_restart_and_late_completion(account):
    store, now = account
    money = MoneyLedger(store)
    first = money.reserve(30_000_000, policy=POLICY_ID)
    now[0] += 86400
    store.close()
    reopened = AnonymousSessionStore(
        str(store.storage), str(store.reference), development=True, clock=lambda: now[0]
    )
    try:
        money = MoneyLedger(reopened)
        assert money.snapshot()["remaining"] == 20_000_000
        money.reserve(20_000_000, policy=POLICY_ID)
        with pytest.raises(SessionError):
            money.reserve(1, policy=POLICY_ID)
        money.complete(first)
        assert money.snapshot()["reserved_today"] == DAILY_CAP_MICROS
        assert reopened.state["money"]["days"]["2026-10-16"] == 30_000_000
    finally:
        reopened.close()


def test_personal_reset_does_not_refund_money(account):
    store, _ = account
    _, identity = store.create("synthetic")
    store.personal_count(identity, increment=True)
    money = MoneyLedger(store)
    money.reserve(1_000_000, policy=POLICY_ID)
    assert store.reset_personal(identity["quota_ref"])
    assert money.snapshot()["reserved_today"] == 1_000_000


def test_failed_commit_never_dispatches(account):
    store, _ = account
    handler = Mock(side_effect=success)
    transport = BudgetedTransport("chat", httpx.MockTransport(handler))
    with money_ledger_scope(store), patch(
        "app.core.anonymous_session._write_atomic", side_effect=OSError("synthetic")
    ):
        with pytest.raises(SessionError, match="quota_storage_unavailable"):
            transport.handle_request(chat_request())
    handler.assert_not_called()
    assert not store.healthy


@pytest.mark.parametrize("failure", ["timeout", "500", "read"])
def test_uncertain_failures_keep_reservation_across_days(account, failure):
    store, now = account

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadError("synthetic")
            yield b""

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic")
        if failure == "read":
            return httpx.Response(200, stream=BrokenStream())
        return httpx.Response(500)

    transport = BudgetedTransport("chat", httpx.MockTransport(handler))
    with money_ledger_scope(store):
        try:
            transport.handle_request(chat_request())
        except httpx.HTTPError:
            pass
    now[0] += 86400
    snap = MoneyLedger(store).snapshot()
    assert snap["unresolved_previous_days"] == 2_206_400
    assert snap["pending_attempts"] == 1


def test_success_across_midnight_charged_both_days(account):
    store, now = account

    def handler(request):
        now[0] += 86400
        return success(request)

    with money_ledger_scope(store):
        BudgetedTransport("chat", httpx.MockTransport(handler)).handle_request(
            chat_request()
        )
    assert list(store.state["money"]["days"].values()) == [2_206_400, 2_206_400]
    assert MoneyLedger(store).snapshot()["pending_attempts"] == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"model": "unreviewed"},
        {"max_tokens": 801},
        {"max_tokens": True},
        {"n": 2},
        {"stream": True},
        {"thinking": {"type": "enabled"}},
        {"tools": []},
        {"messages": [{"role": "user", "content": [{"type": "image"}]}]},
    ],
)
def test_unreviewed_parameters_rejected_without_dispatch(account, updates):
    store, _ = account
    handler = Mock(side_effect=success)
    with money_ledger_scope(store), pytest.raises(SessionError):
        BudgetedTransport("chat", httpx.MockTransport(handler)).handle_request(
            chat_request(**updates)
        )
    handler.assert_not_called()
    assert MoneyLedger(store).snapshot()["reserved_today"] == 0


def test_expired_price_policy_and_clock_rollback_fail_closed(account):
    store, now = account
    money = MoneyLedger(store)
    money.reserve(1, policy=POLICY_ID)
    now[0] -= 86400
    with pytest.raises(SessionError):
        money.reserve(1, policy=POLICY_ID)
    now[0] += 8 * 86400
    handler = Mock(side_effect=success)
    with money_ledger_scope(store), pytest.raises(SessionError):
        BudgetedTransport("chat", httpx.MockTransport(handler)).handle_request(
            chat_request()
        )
    handler.assert_not_called()


def test_missing_money_state_is_not_initialized(account):
    store, _ = account
    del store.state["money"]
    with pytest.raises(SessionError):
        MoneyLedger(store).reserve(1, policy=POLICY_ID)
    assert "money" not in store.state


def test_offline_permission_alone_cannot_bypass_budget():
    handler = Mock(side_effect=success)
    with offline_provider_access(reason="synthetic"), pytest.raises(SessionError):
        BudgetedTransport("chat", httpx.MockTransport(handler)).handle_request(
            chat_request()
        )
    handler.assert_not_called()


def test_background_threads_share_registered_ledger(account):
    store, _ = account
    register_project_ledger(store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda _: BudgetedTransport(
                    "chat", httpx.MockTransport(success)
                ).handle_request(chat_request()),
                range(4),
            )
        )
    assert MoneyLedger(store).snapshot()["reserved_today"] == 4 * 2_206_400


def test_actual_sdk_document_batches_and_byok_query_are_charged(account):
    store, _ = account
    calls = []

    def handler(request):
        body = json.loads(request.content)
        texts = body["input"]
        texts = [texts] if isinstance(texts, str) else texts
        calls.append(len(texts))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1] * 1024, "index": i} for i in range(len(texts))
                ],
                "model": "qwen3.7-text-embedding",
                "usage": {"total_tokens": len(texts)},
            },
        )

    with httpx.Client(
        transport=BudgetedTransport("embedding", httpx.MockTransport(handler))
    ) as client:
        embeddings = OpenAIEmbeddings(
            api_key="synthetic",
            model="qwen3.7-text-embedding",
            dimensions=1024,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            chunk_size=10,
            check_embedding_ctx_length=False,
            max_retries=0,
            http_client=client,
        )
        with offline_provider_access(reason="synthetic import", ledger=store):
            assert (
                len(embeddings.embed_documents([f"synthetic {i}" for i in range(11)]))
                == 11
            )
        with question_budget(store, byok=True, limits={}):
            embeddings.embed_query("synthetic byok")
    # Installed LangChain sends individual texts with ctx-length checking off.
    assert calls == [1] * 12
    assert MoneyLedger(store).snapshot()["reserved_today"] == 12 * 64_000


@pytest.mark.parametrize("count", [1, 10])
def test_physical_embedding_batch_reserves_every_item(account, count):
    store, _ = account
    request = httpx.Request(
        "POST",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        json={
            "model": "qwen3.7-text-embedding",
            "dimensions": 1024,
            "input": ["synthetic"] * count,
        },
    )
    with money_ledger_scope(store):
        BudgetedTransport("embedding", httpx.MockTransport(success)).handle_request(
            request
        )
    assert MoneyLedger(store).snapshot()["reserved_today"] == count * 64_000


def test_sdk_error_preserves_budget_rejection_without_retry(account):
    store, _ = account
    MoneyLedger(store).reserve(DAILY_CAP_MICROS, policy=POLICY_ID)
    handler = Mock(side_effect=success)
    with httpx.Client(
        transport=BudgetedTransport("chat", httpx.MockTransport(handler))
    ) as http:
        client = OpenAI(
            api_key="synthetic",
            base_url="https://api.deepseek.com",
            http_client=http,
            max_retries=0,
        ).with_options(timeout=1)
        with money_ledger_scope(store), pytest.raises(
            SessionError, match="global_budget_exceeded"
        ):
            try:
                client.chat.completions.create(
                    **{k: v for k, v in chat_body().items() if k != "thinking"},
                    extra_body={"thinking": {"type": "disabled"}},
                )
            except Exception as error:
                reraise_budget_cause(error)
                raise
    handler.assert_not_called()


def test_async_sdk_uses_same_cap(account):
    store, _ = account

    async def run():
        async with httpx.AsyncClient(
            transport=AsyncBudgetedTransport("chat", httpx.MockTransport(success))
        ) as http:
            client = AsyncOpenAI(
                api_key="synthetic",
                base_url="https://api.deepseek.com",
                http_client=http,
                max_retries=0,
            )
            with money_ledger_scope(store):
                await client.chat.completions.create(
                    model="deepseek-flash",
                    messages=[{"role": "user", "content": "synthetic"}],
                    max_tokens=800,
                    extra_body={"thinking": {"type": "disabled"}},
                )

    asyncio.run(run())
    assert MoneyLedger(store).snapshot()["reserved_today"] == 2_206_400


def test_quote_rejects_wrong_endpoint():
    with pytest.raises(SessionError):
        quote_request(
            httpx.Request("POST", "https://other.invalid", json=chat_body()), "chat"
        )


@pytest.mark.parametrize("key", [None, "project-synthetic", "user-synthetic"])
def test_qa_client_project_key_classification_and_real_langchain_request(account, key):
    from app.core.qa_engine import QAEngine

    store, _ = account
    engine = QAEngine.__new__(QAEngine)
    engine._overrides = {"api_key": key} if key else {}
    with patch("app.core.qa_engine.settings") as settings:
        settings.get_api_key.return_value = "project-synthetic"
        settings.get_model_config.return_value = {
            "provider": "deepseek",
            "chat_model": "deepseek-flash",
            "api_base_url": "https://api.deepseek.com",
        }
        settings.llm_temperature = 0.1
        settings.llm_max_tokens = 800
        settings.chat_timeout_seconds = 45
        engine._initialize_llm()
    http = engine.llm.http_client
    async_http = engine.llm.http_async_client
    try:
        if key == "user-synthetic":
            assert not isinstance(http._transport, BudgetedTransport)
            assert MoneyLedger(store).snapshot()["reserved_today"] == 0
            return
        assert isinstance(http._transport, BudgetedTransport)
        http._transport.delegate.close()
        http._transport.delegate = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": "synthetic",
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "synthetic"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        with money_ledger_scope(store):
            assert engine.llm.with_config({}).invoke("synthetic").content == "synthetic"
        assert MoneyLedger(store).snapshot()["reserved_today"] == 2_206_400
    finally:
        http.close()
        asyncio.run(async_http.aclose())


def test_registered_ledger_rejects_different_offline_store(account, tmp_path):
    store, _ = account
    register_project_ledger(store)
    storage, reference = tmp_path / "other", tmp_path / "other.json"
    bootstrap(storage, reference, development=True)
    other = AnonymousSessionStore(
        str(storage), str(reference), development=True, clock=store.clock
    )
    try:
        handler = Mock(side_effect=success)
        with money_ledger_scope(other), pytest.raises(SessionError):
            BudgetedTransport("chat", httpx.MockTransport(handler)).handle_request(
                chat_request()
            )
        handler.assert_not_called()
    finally:
        other.close()
