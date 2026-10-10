"""Streamlit interaction tests with explicit HTTP test doubles, no model calls."""

from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest
import requests

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402 - follows importorskip

from app.core.demo_content import DEMO_QUESTIONS  # noqa: E402

SCRIPT = """
from frontend.components.chat_interface import ChatInterface
ChatInterface('http://demo-test.invalid').render()
"""

TOKEN = "anon_v1_" + "x" * 43


def session_response():
    return response({"token": TOKEN, "expires_at": "2026-10-28T00:00:00Z"}, 201)


def session_or_answer(answer):
    def post(url, **kwargs):
        return session_response() if url.endswith("/session/anonymous") else answer

    return post


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


def test_example_submits_anonymously_and_preserves_sources():
    sources = [
        {
            "document_name": "atlas-03-document-ingestion.md",
            "content": "网页上传的单个文件大小上限为 40 MB。" + "原文" * 120,
        }
    ]
    with patch(
        "requests.get",
        return_value=response(
            {"suggestions": list(DEMO_QUESTIONS), "document_count": 9}
        ),
    ), patch(
        "requests.post",
        side_effect=session_or_answer(
            response(
                {
                    "answer": "网页上传上限为 40 MB。",
                    "sources": sources,
                    "processing_time": 0.1,
                }
            )
        ),
    ) as post:
        at = AppTest.from_string(SCRIPT).run()
        assert not at.exception
        assert len([b for b in at.button if b.key.startswith("suggestion_")]) == 4
        at.session_state.selected_doc_id = "stale-admin-scope"
        at.button(key="suggestion_0").click().run()
        assert not at.exception
        assert post.call_count == 2
        assert post.call_args == call(
            "http://demo-test.invalid/api/qa/ask",
            json={"question": DEMO_QUESTIONS[0], "max_sources": 3},
            headers={"X-Anonymous-Token": TOKEN},
            timeout=75,
        )
        assert at.session_state.messages[-1]["sources"] == sources
        assert any(e.label == "📚 参考来源" for e in at.expander)
        assert any(t.value == sources[0]["content"] for t in at.text)
        at.button(key="clear_chat").click().run()
        assert not at.exception
        assert at.session_state.messages == []
        assert not at.session_state.is_processing


def test_unavailable_suggestions_are_not_shown_as_empty_library():
    with patch("requests.get", return_value=response({}, status=503)), patch(
        "requests.post", return_value=session_response()
    ):
        at = AppTest.from_string(SCRIPT).run()
    assert not at.exception
    assert len(at.warning) == 1
    assert "暂时无法" in at.warning[0].value


def test_source_html_is_rendered_as_text():
    script = """
from frontend.components.chat_interface import ChatInterface
ChatInterface('http://demo-test.invalid')._render_sources([
    {'document_name': '<img src=x onerror=alert(1)>',
     'content': '<script>alert(1)</script>'}
])
"""
    at = AppTest.from_string(script).run()
    assert not at.exception
    markup = "\n".join(m.value for m in at.markdown)
    assert "<script>" not in markup
    assert "<img src=x" not in markup
    assert "&lt;script&gt;" in markup


def test_non_json_gateway_error_recovers_processing_state():
    gateway = response({}, status=502)
    gateway.json.side_effect = ValueError("not JSON")
    with patch(
        "requests.get",
        return_value=response(
            {"suggestions": list(DEMO_QUESTIONS), "document_count": 9}
        ),
    ), patch("requests.post", side_effect=session_or_answer(gateway)):
        at = AppTest.from_string(SCRIPT).run()
        at.button(key="suggestion_0").click().run()
    assert not at.exception
    assert not at.session_state.is_processing
    assert "HTTP 502" in at.session_state.messages[-1]["content"]


def test_full_homepage_is_available_without_login(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "frontend"))

    def get(url, **kwargs):
        if url.endswith("/health"):
            return response({"status": "healthy"})
        if url.endswith("/library"):
            return response({"total": 9, "documents": []})
        if url.endswith("/quota"):
            return response({"quota_enabled": True, "used_count": 0, "daily_limit": 10})
        if url.endswith("/suggestions"):
            return response({"document_count": 9, "suggestions": list(DEMO_QUESTIONS)})
        raise AssertionError(f"Unexpected HTTP request: {url}")

    with patch("requests.get", side_effect=get), patch(
        "requests.post", return_value=session_response()
    ), patch("utils.settings_loader._read_browser_settings", return_value={}):
        at = AppTest.from_file(str(root / "frontend/streamlit_app.py")).run()
    assert not at.exception
    assert any("虚构产品文档" in info.value for info in at.info)
    assert len([b for b in at.button if (b.key or "").startswith("suggestion_")]) == 4
    assert not at.get("file_uploader")
    assert "admin_jwt" not in at.session_state


@pytest.mark.parametrize("failure", [requests.ConnectionError, requests.Timeout])
def test_network_failure_waits_for_explicit_retry_without_rotating_identity(failure):
    with patch(
        "requests.get",
        return_value=response(
            {"suggestions": list(DEMO_QUESTIONS), "document_count": 9}
        ),
    ), patch(
        "requests.post",
        side_effect=[
            session_response(),
            failure("private-upstream-detail"),
            response({"answer": "retry answer", "sources": [], "processing_time": 0}),
        ],
    ) as post:
        at = AppTest.from_string(SCRIPT).run()
        at.button(key="suggestion_0").click().run()
        assert not at.exception
        assert post.call_count == 2
        assert "private-upstream-detail" not in str(at.session_state.messages)
        assert at.session_state.anonymous_token == TOKEN
        assert not at.session_state.is_processing
        at.run()
        assert post.call_count == 2
        at.button(key="retry_failed_question").click().run()
        assert not at.exception
        assert post.call_count == 3
        assert post.call_args.kwargs["headers"] == {"X-Anonymous-Token": TOKEN}
        assert at.session_state.messages[-1]["content"] == "retry answer"
        assert "retry_question" not in at.session_state


def test_processing_guard_rejects_reentrant_submission():
    script = """
import streamlit as st
from frontend.components.chat_interface import ChatInterface
chat = ChatInterface('http://demo-test.invalid')
st.session_state.is_processing = True
chat._process_question('duplicate')
"""
    with patch("requests.post") as post:
        at = AppTest.from_string(script).run()
    assert not at.exception
    post.assert_not_called()
    assert at.session_state.messages == []


@pytest.mark.parametrize(
    "question,accepted",
    [
        ("😀" * 2000, True),
        ("中" * 2000, True),
        ("😀" * 2001, False),
        ("中" * 2001, False),
        (" " + "中" * 2000, False),
    ],
)
def test_unicode_question_boundary_precedes_ask(question, accepted):
    with patch(
        "requests.get", return_value=response({"suggestions": [], "document_count": 1})
    ), patch(
        "requests.post",
        side_effect=session_or_answer(
            response({"answer": "boundary answer", "sources": [], "processing_time": 0})
        ),
    ) as post:
        at = AppTest.from_string(SCRIPT).run()
        at.chat_input[0].set_value(question).run()
    assert not at.exception
    asks = [c for c in post.call_args_list if c.args[0].endswith("/qa/ask")]
    assert len(asks) == int(accepted)
    if accepted:
        assert asks[0].kwargs["json"]["question"] == question
    else:
        assert any("2000" in w.value for w in at.warning)
