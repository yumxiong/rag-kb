"""Streamlit interaction tests with explicit HTTP test doubles, no model calls."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from app.core.demo_content import DEMO_QUESTIONS

SCRIPT = """
from frontend.components.chat_interface import ChatInterface
ChatInterface('http://demo-test.invalid').render()
"""


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
        return_value=response(
            {
                "answer": "网页上传上限为 40 MB。",
                "sources": sources,
                "processing_time": 0.1,
            }
        ),
    ) as post:
        at = AppTest.from_string(SCRIPT).run()
        assert not at.exception
        assert len([b for b in at.button if b.key.startswith("suggestion_")]) == 4
        at.session_state.selected_doc_id = "stale-admin-scope"
        at.button(key="suggestion_0").click().run()
        assert not at.exception
        post.assert_called_once_with(
            "http://demo-test.invalid/api/qa/ask",
            json={"question": DEMO_QUESTIONS[0], "max_sources": 3},
            headers={},
            timeout=30,
        )
        assert at.session_state.messages[-1]["sources"] == sources
        assert any(e.label == "📚 参考来源" for e in at.expander)
        assert any(t.value == sources[0]["content"] for t in at.text)
        at.button(key="clear_chat").click().run()
        assert not at.exception
        assert at.session_state.messages == []
        assert not at.session_state.is_processing


def test_unavailable_suggestions_are_not_shown_as_empty_library():
    with patch("requests.get", return_value=response({}, status=503)):
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
    ), patch("requests.post", return_value=gateway):
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
        "utils.settings_loader._read_browser_settings", return_value={}
    ):
        at = AppTest.from_file(str(root / "frontend/streamlit_app.py")).run()
    assert not at.exception
    assert any("虚构产品文档" in info.value for info in at.info)
    assert len([b for b in at.button if (b.key or "").startswith("suggestion_")]) == 4
    assert not at.get("file_uploader")
    assert "admin_jwt" not in at.session_state
