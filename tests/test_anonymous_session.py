"""Step 2 contract checks without real model calls."""

import hashlib
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from app.core.anonymous_session import AnonymousSessionStore, SessionError, bootstrap
from app.core.config import settings
from app.main import app
from app.models.schemas import QuestionResponse
from fastapi.testclient import TestClient
from frontend.utils.anonymous_session import ensure_identity, recover_identity


@pytest.fixture
def client(tmp_path, monkeypatch):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    bootstrap(storage, reference, development=True)
    monkeypatch.setattr(settings, "quota_storage_path", str(storage))
    monkeypatch.setattr(settings, "anonymous_store_reference", str(reference))
    monkeypatch.setattr(settings, "anonymous_storage_development", True)
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client, storage, reference


def _header(client):
    result = client.post("/api/session/anonymous", json={"transport": "header"})
    assert result.status_code == 201
    return result.json()["token"]


def test_header_identity_is_persistent_and_private(client):
    test_client, storage, reference = client
    first, second = _header(test_client), _header(test_client)
    assert first != second
    assert first.startswith("anon_v1_")
    assert len(first) == 51
    reused = test_client.post(
        "/api/session/anonymous",
        json={"transport": "header"},
        headers={"X-Anonymous-Token": first},
    )
    assert reused.status_code == 200
    assert reused.json()["token"] == first
    assert first not in (storage / "quota-state-v1.json").read_text()
    digest = hashlib.sha256(first.encode()).hexdigest()
    assert digest in (storage / "quota-state-v1.json").read_text()
    test_client.app.state.anonymous_store.close()
    persisted = AnonymousSessionStore(str(storage), str(reference), development=True)
    try:
        assert persisted.resolve(first)["quota_ref"] == digest
    finally:
        persisted.close()


def test_cookie_origin_and_expiry(client):
    test_client, storage, _ = client
    origin = {"Origin": settings.get_cors_origins()[0]}
    assert (
        test_client.post(
            "/api/session/anonymous", json={"transport": "cookie"}
        ).status_code
        == 403
    )
    created = test_client.post(
        "/api/session/anonymous", json={"transport": "cookie"}, headers=origin
    )
    assert created.status_code == 201
    assert "token" not in created.json()
    assert "httponly" in created.headers["set-cookie"].lower()
    assert "secure" in created.headers["set-cookie"].lower()
    token = test_client.cookies.get("rag_anonymous")
    test_client.cookies.clear()
    assert (
        test_client.post(
            "/api/session/anonymous",
            json={"transport": "header"},
            headers={"X-Anonymous-Token": token, "Cookie": f"rag_anonymous={token}"},
        ).status_code
        == 400
    )
    ledger = json.loads((storage / "quota-state-v1.json").read_text())
    ledger["sessions"][hashlib.sha256(token.encode()).hexdigest()]["expires_at"] = (
        int(time.time()) - 1
    )
    (storage / "quota-state-v1.json").write_text(json.dumps(ledger))
    test_client.app.state.anonymous_store.state = ledger
    expired = test_client.post(
        "/api/session/anonymous",
        json={"transport": "cookie"},
        headers={**origin, "Cookie": f"rag_anonymous={token}"},
    )
    assert expired.status_code == 401
    assert expired.json()["detail"]["code"] == "anonymous_session_expired"
    assert "max-age=0" in expired.headers["set-cookie"].lower()


def test_identity_drives_quota_not_peer_address(client):
    test_client, _, _ = client
    first, second = _header(test_client), _header(test_client)
    store = test_client.app.state.anonymous_store
    identity = store.resolve(first)
    assert store.personal_count(identity, increment=True) == 1
    for token, expected in ((first, 1), (second, 0)):
        result = test_client.get("/api/qa/quota", headers={"X-Anonymous-Token": token})
        assert result.status_code == 200
        assert result.json()["used_count"] == expected
    assert (
        test_client.get("/api/qa/quota").json()["detail"]["code"]
        == "anonymous_session_required"
    )
    assert (
        test_client.get(
            "/api/qa/quota", headers={"X-Anonymous-Token": "anon_v1_" + "x" * 43}
        ).json()["detail"]["code"]
        == "anonymous_session_invalid"
    )


def test_missing_store_or_mismatched_reference_refuses_start(tmp_path):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    with pytest.raises(SessionError):
        AnonymousSessionStore(str(storage), str(reference), development=True)
    bootstrap(storage, reference, development=True)
    (storage / "quota-state-v1.json").unlink()
    (storage / "initialized-v1.json").unlink()
    with pytest.raises(SessionError):
        AnonymousSessionStore(str(storage), str(reference), development=True)


def test_production_bootstrap_refuses_without_verified_mount(tmp_path):
    storage = tmp_path / "volume" / "quotas"
    reference = tmp_path / "reference" / "store.json"
    with pytest.raises(ValueError):
        bootstrap(storage, reference)
    assert not storage.exists()
    assert not reference.exists()


def test_streamlit_rerun_reuses_token_and_expiry_recovers_once():
    state = {}

    class Result:
        status_code = 201

        def json(self):
            return {
                "token": "anon_v1_" + "x" * 43,
                "expires_at": "2026-10-28T00:00:00Z",
            }

    with patch(
        "frontend.utils.anonymous_session.requests.post", return_value=Result()
    ) as post:
        first = ensure_identity(state, "http://backend")
        assert ensure_identity(state, "http://backend") == first
        assert post.call_count == 1

        class Expired:
            status_code = 401

            def json(self):
                return {"detail": {"code": "anonymous_session_expired"}}

        assert recover_identity(state, "http://backend", Expired())
        assert post.call_count == 2


def test_real_ask_and_quota_share_identity_behind_proxy(client, monkeypatch):
    test_client, _, _ = client
    monkeypatch.setattr(settings, "enable_quota_limit", True)
    monkeypatch.setattr(settings, "default_daily_quota", 5)
    first, second = _header(test_client), _header(test_client)
    vector = MagicMock()
    vector.get_collection_info.return_value = {"document_count": 1}
    engine = MagicMock()
    engine.ask.return_value = QuestionResponse(
        answer="test", sources=[], processing_time=0
    )
    with patch("app.api.qa.vector_store", vector), patch(
        "app.api.qa.qa_engine", engine
    ):
        for token in (first, first, second):
            result = test_client.post(
                "/api/qa/ask",
                json={"question": "测试问题"},
                headers={"X-Anonymous-Token": token, "X-Forwarded-For": "203.0.113.1"},
            )
            assert result.status_code == 200
        for token, count in ((first, 2), (second, 1)):
            result = test_client.get(
                "/api/qa/quota", headers={"X-Anonymous-Token": token}
            )
            assert result.json()["used_count"] == count
        denied = test_client.post("/api/qa/ask", json={"question": "测试问题"})
        assert denied.status_code == 401
        assert engine.ask.call_count == 3


def test_independent_cookie_clients_keep_separate_quota(client, monkeypatch):
    first_client, _, _ = client
    second_client = TestClient(app, base_url="https://testserver")
    monkeypatch.setattr(settings, "enable_quota_limit", True)
    monkeypatch.setattr(settings, "default_daily_quota", 2)
    origin = {"Origin": settings.get_cors_origins()[0]}
    vector = MagicMock()
    vector.get_collection_info.return_value = {"document_count": 1}
    engine = MagicMock()
    engine.ask.return_value = QuestionResponse(
        answer="test", sources=[], processing_time=0
    )

    with patch("app.api.qa.vector_store", vector), patch(
        "app.api.qa.qa_engine", engine
    ):
        for visitor in (first_client, second_client):
            created = visitor.post(
                "/api/session/anonymous", json={"transport": "cookie"}, headers=origin
            )
            assert created.status_code == 201
            assert "token" not in created.json()
            assert visitor.get("/api/qa/quota").json()["used_count"] == 0

        assert first_client.cookies.get("rag_anonymous") != second_client.cookies.get(
            "rag_anonymous"
        )
        for visitor, expected in (
            (first_client, 1),
            (first_client, 2),
            (second_client, 1),
        ):
            response = visitor.post(
                "/api/qa/ask", json={"question": "测试问题"}, headers=origin
            )
            assert response.status_code == 200
            assert visitor.get("/api/qa/quota").json()["used_count"] == expected

        denied = first_client.post(
            "/api/qa/ask", json={"question": "测试问题"}, headers=origin
        )
        assert denied.status_code == 429
        assert denied.json()["detail"]["code"] == "quota_exceeded"
        assert second_client.get("/api/qa/quota").json()["remaining"] == 1
        assert engine.ask.call_count == 3


def test_write_failure_never_issues_identity_and_latches_unhealthy(client):
    test_client, _, _ = client
    ledger = test_client.app.state.anonymous_store
    before = json.dumps(ledger.state, sort_keys=True)
    with patch("app.core.anonymous_session._write_atomic", side_effect=OSError("disk")):
        response = test_client.post(
            "/api/session/anonymous", json={"transport": "header"}
        )
    assert response.status_code == 503
    assert "token" not in response.json()
    assert not ledger.healthy
    assert json.dumps(ledger.state, sort_keys=True) == before
    assert (
        test_client.post(
            "/api/session/anonymous", json={"transport": "header"}
        ).status_code
        == 503
    )
    assert test_client.get("/health").json()["status"] == "degraded"


def test_store_rejects_second_owner_and_wrong_uuid(client):
    test_client, storage, reference = client
    with pytest.raises(SessionError):
        AnonymousSessionStore(str(storage), str(reference), development=True)
    test_client.app.state.anonymous_store.close()
    reference.write_text(
        json.dumps({"store_id": "00000000-0000-0000-0000-000000000000"})
    )
    with pytest.raises(SessionError):
        AnonymousSessionStore(str(storage), str(reference), development=True)


def test_streamlit_failure_latch_and_invalid_require_explicit_reconnect():
    state = {"anonymous_token": "anon_v1_" + "x" * 43}
    invalid = MagicMock(status_code=401)
    invalid.json.return_value = {"detail": {"code": "anonymous_session_invalid"}}
    from frontend.utils.anonymous_session import AnonymousConnectionError

    with patch("frontend.utils.anonymous_session.requests.post") as post:
        assert not recover_identity(state, "http://backend", invalid)
        for _ in range(3):
            with pytest.raises(AnonymousConnectionError):
                ensure_identity(state, "http://backend")
        post.assert_not_called()
        post.return_value.status_code = 503
        with pytest.raises(AnonymousConnectionError):
            ensure_identity(state, "http://backend", reconnect=True)
        with pytest.raises(AnonymousConnectionError):
            ensure_identity(state, "http://backend")
        assert post.call_count == 1
