"""Release access boundaries; external model/storage calls are mocked explicitly."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.demo_content import DEMO_QUESTIONS
from app.main import app
from app.models.schemas import QuestionResponse, SourceDocument

client = TestClient(app)
SECRET = "demo-test-only-signing-secret-32-bytes"
MANAGEMENT_ROUTES = [
    ("GET", "/api/documents/"),
    ("POST", "/api/documents/upload"),
    ("POST", "/api/documents/upload-async"),
    ("POST", "/api/documents/batch-upload"),
    ("GET", "/api/documents/status/job"),
    ("GET", "/api/documents/status/stream/job"),
    ("GET", "/api/documents/doc"),
    ("DELETE", "/api/documents/doc"),
    ("GET", "/api/documents/stats/overview"),
    ("GET", "/api/documents/pdf-info/doc"),
    ("POST", "/api/documents/cancel/job"),
    ("GET", "/api/documents/cancel-status/job"),
    ("GET", "/api/qa/health"),
    ("GET", "/api/qa/stats"),
    ("DELETE", "/api/qa/cache"),
    ("DELETE", "/api/qa/cache/all"),
    ("POST", "/api/qa/quota/reset"),
    ("GET", "/api/qa/quota/stats"),
    ("GET", "/api/cost/cache/stats"),
    ("GET", "/api/cost/embedding/stats"),
    ("POST", "/api/cost/cache/cleanup"),
    ("GET", "/api/cost/optimization/recommendations"),
]


def token(role="admin", secret=SECRET, expired=False):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "test-admin",
            "role": role,
            "iat": now - timedelta(hours=1),
            "exp": now + timedelta(minutes=-1 if expired else 30),
        },
        secret,
        algorithm="HS256",
    )


@pytest.mark.parametrize("method,path", MANAGEMENT_ROUTES)
@pytest.mark.parametrize(
    "identity,expected",
    [
        ("anonymous", 401),
        ("forged", 401),
        ("expired", 401),
        ("visitor", 403),
    ],
)
def test_management_rejects_non_admin(method, path, identity, expected, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    tokens = {
        "forged": token(secret="wrong-secret-for-tests-at-least-32"),
        "expired": token(expired=True),
        "visitor": token(role="visitor"),
    }
    headers = (
        {}
        if identity == "anonymous"
        else {"Authorization": f"Bearer {tokens[identity]}"}
    )
    response = client.request(method, path, headers=headers)
    assert response.status_code == expected, response.text


def test_admin_login_and_document_access(monkeypatch):
    from app.api.auth import ph
    from app.core.rate_limiter import limiter

    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "admin_username", "test-admin")
    monkeypatch.setattr(settings, "admin_password_hash", ph.hash("test-password"))
    bad = client.post(
        "/api/auth/login", data={"username": "test-admin", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    good = client.post(
        "/api/auth/login", data={"username": "test-admin", "password": "test-password"}
    )
    assert good.status_code == 200
    with patch("app.api.documents.get_vector_store") as get_store:
        get_store.return_value.list_documents.return_value = []
        response = client.get(
            "/api/documents/",
            headers={"Authorization": f"Bearer {good.json()['access_token']}"},
        )
    assert response.status_code == 200


def test_anonymous_demo_question_and_citations(monkeypatch):
    monkeypatch.setattr(settings, "enable_quota_limit", False)
    root = Path(__file__).resolve().parents[1]
    questions = json.loads(
        (root / "docs/demo-v0.1.0/questions.json").read_text(encoding="utf-8")
    )["questions"]
    assert list(DEMO_QUESTIONS) == [q["question"] for q in questions if q["homepage"]]
    example = questions[3]
    sources = [
        SourceDocument(
            document_name=Path(e["file"]).name, content=e["quote"], similarity_score=0.9
        )
        for e in example["evidence"]
    ]
    store = MagicMock()
    store.get_collection_info.return_value = {"document_count": 9}
    store.list_documents.return_value = [
        {
            "filename": sources[0].document_name,
            "id": "internal-id",
            "file_path": "private",
        }
    ]
    engine = MagicMock()
    engine.ask.return_value = QuestionResponse(
        answer="文件超过单文件上传限制，网页上传上限为 40 MB。",
        sources=sources,
        processing_time=0.1,
    )
    with patch("app.api.qa.get_vector_store", return_value=store), patch(
        "app.api.qa.get_qa_engine", return_value=engine
    ), patch("app.api.documents.get_vector_store", return_value=store):
        suggestions = client.get("/api/qa/suggestions")
        assert suggestions.json()["suggestions"] == list(DEMO_QUESTIONS)
        library = client.get("/api/documents/library")
        assert library.status_code == 200
        assert set(library.json()["documents"][0]) == {
            "filename",
            "file_type",
            "chunk_count",
        }
        response = client.post("/api/qa/ask", json={"question": example["question"]})
    assert response.status_code == 200
    assert response.json()["sources"] == [s.model_dump() for s in sources]
    engine.ask.assert_called_once_with(
        question=example["question"], max_sources=3, document_id=None
    )
