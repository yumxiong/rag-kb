"""Header identity client scoped exclusively to the current Streamlit state."""

import re
from datetime import datetime

import requests


class AnonymousConnectionError(Exception):
    """Safe frontend error; credentials and upstream responses are never printed."""


def error_code(response) -> str:
    try:
        detail = response.json().get("detail", {})
        return detail.get("code", "") if isinstance(detail, dict) else ""
    except (ValueError, AttributeError, TypeError):
        return ""


def clear_credential(state):
    state.pop("anonymous_token", None)
    state.pop("anonymous_expires_at", None)


def ensure_identity(state, backend_url: str, *, reconnect=False) -> str:
    """Bound startup recovery; a failed rerun cannot start a new recovery episode."""
    if reconnect:
        state.pop("anonymous_error", None)
    if state.get("anonymous_error"):
        raise AnonymousConnectionError(state["anonymous_error"])
    if state.get("anonymous_token"):
        return state["anonymous_token"]
    try:
        response = requests.post(
            f"{backend_url}/api/session/anonymous",
            json={"transport": "header"},
            timeout=10,
        )
        if response.status_code != 201:
            raise AnonymousConnectionError("无法连接会话，请稍后重新连接。")
        body = response.json()
        if not isinstance(body.get("token"), str) or not re.fullmatch(
            r"anon_v1_[A-Za-z0-9_-]{43}", body["token"]
        ):
            raise AnonymousConnectionError("无法连接会话，请稍后重新连接。")
        expiry = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Missing expiry timezone")
        state["anonymous_token"] = body["token"]
        state["anonymous_expires_at"] = body["expires_at"]
        return body["token"]
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        AnonymousConnectionError,
    ):
        state["anonymous_error"] = "无法连接会话，请稍后重新连接。"
        raise AnonymousConnectionError(state["anonymous_error"]) from None


def identity_headers(state, backend_url: str) -> dict:
    return {"X-Anonymous-Token": ensure_identity(state, backend_url)}


def recover_identity(state, backend_url: str, response) -> bool:
    """Recover once after definitive identity failure; never replay the ask."""
    code = error_code(response) if response.status_code == 401 else ""
    if code not in (
        "anonymous_session_required",
        "anonymous_session_expired",
        "anonymous_session_invalid",
    ):
        return False
    clear_credential(state)
    if state.get("anonymous_error"):
        return False
    if code == "anonymous_session_invalid":
        state["anonymous_error"] = "会话失效，请重新连接。"
        return False
    ensure_identity(state, backend_url)
    return True
