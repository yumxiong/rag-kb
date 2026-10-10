"""Execute actual client functions with HTTP/UI doubles, without a browser."""

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace[name]


@pytest.mark.parametrize("component", [False, True])
@pytest.mark.parametrize("byok", [False, True])
@pytest.mark.parametrize("status", ["available", "exhausted"])
def test_both_quota_clients_fetch_identity_and_global_status(
    monkeypatch, component, byok, status
):
    monkeypatch.syspath_prepend(str(ROOT / "frontend"))
    ui = Mock()
    ui.session_state = {"anonymous_token": "anon_v1_" + "x" * 43}
    if byok:
        ui.session_state["byok_api_key"] = "test-only"
    response = Mock(status_code=200)
    response.json.return_value = {
        "quota_enabled": True,
        "has_custom_key": byok,
        "used_count": 2,
        "daily_limit": None if byok else 5,
        "remaining": None if byok else 1,
        "reset_at": "2026-09-30T00:00:00Z",
        "global_budget": {"status": status, "reset_at": "2026-09-30T00:00:00Z"},
    }
    http = Mock()
    http.get.return_value = response
    byok_headers = {"LLM-Api-Key": "test-only"} if byok else {}
    namespace = {
        "st": ui,
        "requests": http,
        "BACKEND_URL_INTERNAL": "http://test.invalid",
        "SettingsStatus": SimpleNamespace(RESTORING=SimpleNamespace(value="restoring")),
        "build_byok_headers": lambda: byok_headers,
    }
    if component:
        function = load_function(
            "frontend/components/document_manager.py", "_render_quota_info", namespace
        )
        function(
            SimpleNamespace(
                backend_url_internal="http://test.invalid",
                _build_byok_headers=lambda: byok_headers,
            )
        )
    else:
        load_function("frontend/streamlit_app.py", "display_quota_info", namespace)()
    http.get.assert_called_once_with(
        "http://test.invalid/api/qa/quota",
        headers={
            **byok_headers,
            "X-Anonymous-Token": ui.session_state["anonymous_token"],
        },
        timeout=5,
    )
    messages = " ".join(str(call) for call in ui.mock_calls)
    assert "全站" in messages
    assert "2026-09-30T00:00:00Z" in messages
    if status == "exhausted":
        assert "当前模式暂不可提问" in messages
        assert "当前模式可用" not in messages
    if byok:
        assert "仍受全站预算限制" in messages
        assert "None" not in messages
    else:
        assert "剩余 1 次" in messages  # Use server remaining, not a local subtraction.


def reset_client():
    ui, http = Mock(), Mock()
    ui.session_state = {"admin_jwt": "test-admin"}
    http.post.return_value = Mock(status_code=200)
    http.post.return_value.json.return_value = {"success": True}
    function = load_function(
        "frontend/pages/Admin.py",
        "reset_quota",
        {
            "st": ui,
            "requests": http,
            "BACKEND": "http://test.invalid",
            "re": re,
        },
    )
    return function, ui, http


@pytest.mark.parametrize(
    "path,name,is_method",
    [
        ("frontend/streamlit_app.py", "build_byok_headers", False),
        ("frontend/components/chat_interface.py", "_build_byok_headers", True),
        ("frontend/components/document_manager.py", "_build_byok_headers", True),
    ],
)
def test_default_provider_without_key_sends_no_partial_byok(path, name, is_method):
    class State(dict):
        __getattr__ = dict.__getitem__

    state = State(
        byok_api_key="",
        byok_provider="openai",
        byok_model="gpt-3.5-turbo",
        byok_base_url="",
    )
    identity = {"X-Anonymous-Token": "synthetic-token"}
    function = load_function(
        path,
        name,
        {
            "st": SimpleNamespace(session_state=state),
            "identity_headers": lambda *_: dict(identity),
            "Dict": dict,
        },
    )
    result = (
        function(SimpleNamespace(backend_url="http://test.invalid"))
        if is_method
        else function()
    )
    assert result == (identity if "chat_interface" in path else {})


def test_admin_reset_sends_target_and_reason():
    function, ui, http = reset_client()
    function("a" * 64, "用户申请更正")
    http.post.assert_called_once_with(
        "http://test.invalid/api/qa/quota/reset",
        headers={"Authorization": "Bearer test-admin"},
        json={"quota_ref": "a" * 64, "reason": "用户申请更正"},
        timeout=10,
    )
    ui.success.assert_called_once()


@pytest.mark.parametrize(
    "reference, reason",
    [("A" * 64, "test"), ("a" * 63, "test"), ("a" * 64, " "), ("a" * 64, "x" * 201)],
)
def test_invalid_reset_never_posts(reference, reason):
    function, ui, http = reset_client()
    function(reference, reason)
    http.post.assert_not_called()
    ui.warning.assert_called_once()
