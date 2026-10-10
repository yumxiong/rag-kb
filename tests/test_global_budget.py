"""Global budget admission is atomic with anonymous personal quota."""

import copy
import threading
from datetime import datetime, timezone

import pytest

from app.core.anonymous_session import AnonymousSessionStore, SessionError, bootstrap


@pytest.fixture
def ledger(tmp_path):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    bootstrap(storage, reference, development=True)
    result = AnonymousSessionStore(str(storage), str(reference), development=True)
    try:
        yield result
    finally:
        result.close()


@pytest.mark.parametrize("kind", ["ask", "default_llm", "llm", "query_embedding"])
@pytest.mark.parametrize("byok", [False, True])
def test_admission_and_snapshot_check_every_applicable_gate(ledger, kind, byok):
    _, identity = ledger.create("test")
    limits = {"ask": 10, "default_llm": 10, "llm": 10, "query_embedding": 10}
    limits[kind] = 1
    if kind == "ask":
        ledger.admit(identity, byok=False, personal_limit=5, limits=limits)
    else:
        ledger.record_attempt(
            "llm" if kind == "default_llm" else kind, byok=False, limits=limits
        )
    before = copy.deepcopy(ledger.state)
    snapshot = ledger.quota_snapshot(
        identity, byok=byok, personal_limit=5, limits=limits
    )
    if kind == "default_llm" and byok:
        assert snapshot["global_budget"]["status"] == "available"
        ledger.admit(identity, byok=True, personal_limit=5, limits=limits)
    else:
        assert snapshot["global_budget"]["status"] == "exhausted"
        with pytest.raises(SessionError, match="global_budget_exceeded"):
            ledger.admit(identity, byok=byok, personal_limit=5, limits=limits)
        assert ledger.state == before


def test_fractional_clock_reset_and_cross_midnight_accounting(ledger):
    now = datetime(2026, 9, 29, 12, 30, tzinfo=timezone.utc).timestamp() + 0.75
    ledger.clock = lambda: now
    _, identity = ledger.create("test")
    limits = {"ask": 10, "default_llm": 10, "llm": 10, "query_embedding": 10}
    assert ledger.reset_at() == "2026-09-30T00:00:00Z"
    assert ledger.seconds_until_reset() == 41400
    now = datetime(2026, 9, 29, 23, 59, 59, tzinfo=timezone.utc).timestamp() + 0.9
    assert ledger.seconds_until_reset() == 1
    ledger.admit(identity, byok=False, personal_limit=5, limits=limits)
    now += 0.2
    ledger.record_attempt("llm", byok=False, limits=limits)
    assert ledger.reset_at() == "2026-10-01T00:00:00Z"
    assert ledger.state["days"]["2026-09-29"]["budget"]["ask_default"] == 1
    assert ledger.budget_snapshot(limits)["counts"]["ask_default"] == 0
    assert ledger.budget_snapshot(limits)["counts"]["llm_default"] == 1


@pytest.mark.parametrize("kind", ["llm", "query_embedding"])
def test_concurrent_provider_attempts_cannot_exceed_limit(ledger, kind):
    limits = {"ask": 10, "default_llm": 2, "llm": 2, "query_embedding": 2}
    errors = []

    def attempt():
        try:
            ledger.record_attempt(kind, byok=False, limits=limits)
        except SessionError as error:
            errors.append(error.code)

    workers = [threading.Thread(target=attempt) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == ["global_budget_exceeded"] * 6
    assert ledger.budget_snapshot(limits)["counts"][f"{kind}_default"] == 2


def test_reset_does_not_refund_global_counters_or_extend_identity(ledger):
    token, identity = ledger.create("test")
    limits = {"ask": 10, "default_llm": 10, "llm": 10, "query_embedding": 10}
    ledger.admit(identity, byok=False, personal_limit=5, limits=limits)
    ledger.record_attempt("llm", byok=False, limits=limits)
    before = ledger.budget_snapshot(limits)
    assert ledger.reset_personal(identity["quota_ref"])
    assert ledger.reset_personal(identity["quota_ref"])
    assert ledger.personal_count(identity) == 0
    assert ledger.resolve(token) == identity
    assert ledger.budget_snapshot(limits) == before
    assert not ledger.reset_personal("0" * 64)


def test_budget_competition_and_restart_persistence(tmp_path):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    bootstrap(storage, reference, development=True)
    ledger = AnonymousSessionStore(str(storage), str(reference), development=True)
    try:
        _, identity = ledger.create("test")
        limits = {"ask": 2, "default_llm": 2, "llm": 2, "query_embedding": 2}
        errors = []

        def admit():
            try:
                ledger.admit(identity, byok=False, personal_limit=5, limits=limits)
            except SessionError as error:
                errors.append(error.code)

        workers = [threading.Thread(target=admit) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert errors == ["global_budget_exceeded"]
        assert ledger.budget_snapshot(limits)["counts"]["ask_default"] == 2
    finally:
        ledger.close()

    restored = AnonymousSessionStore(str(storage), str(reference), development=True)
    try:
        assert restored.budget_snapshot(limits)["counts"]["ask_default"] == 2
    finally:
        restored.close()


def test_byok_skips_personal_count_but_uses_global_budget(tmp_path):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    bootstrap(storage, reference, development=True)
    ledger = AnonymousSessionStore(str(storage), str(reference), development=True)
    try:
        _, identity = ledger.create("test")
        limits = {"ask": 2, "default_llm": 2, "llm": 2, "query_embedding": 2}
        ledger.admit(identity, byok=True, personal_limit=1, limits=limits)
        assert (
            ledger.quota_snapshot(identity, byok=True, personal_limit=1, limits=limits)[
                "used_count"
            ]
            == 0
        )
        assert ledger.budget_snapshot(limits)["counts"]["ask_byok"] == 1
    finally:
        ledger.close()


def test_provider_attempts_have_separate_default_and_total_limits(tmp_path):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    bootstrap(storage, reference, development=True)
    ledger = AnonymousSessionStore(str(storage), str(reference), development=True)
    limits = {"ask": 5, "default_llm": 1, "llm": 2, "query_embedding": 1}
    try:
        _, identity = ledger.create("test")
        ledger.admit(identity, byok=False, personal_limit=5, limits=limits)
        ledger.record_attempt("llm", byok=False, limits=limits)
        with pytest.raises(SessionError) as error:
            ledger.record_attempt("llm", byok=False, limits=limits)
        assert error.value.code == "global_budget_exceeded"
        ledger.record_attempt("query_embedding", byok=False, limits=limits)
        with pytest.raises(SessionError) as error:
            ledger.record_attempt("query_embedding", byok=True, limits=limits)
        assert error.value.code == "global_budget_exceeded"
        counts = ledger.budget_snapshot(limits)["counts"]
        assert counts["llm_default"] == 1
        assert counts["query_embedding_default"] == 1
    finally:
        ledger.close()
