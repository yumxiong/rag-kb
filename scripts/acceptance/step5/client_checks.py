"""Real HTTP clients and Streamlit AppTest sessions against Linux services."""

import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://nginx"
CA = "/certs/local-cert.pem"
ORIGIN = "https://local.rag-kb.dev"
PRIVATE = Path("/evidence/client-state.json")


def request(method, path, **kwargs):
    time.sleep(0.15)  # Stay below the existing Nginx API rate limit.
    return requests.request(method, BASE + path, verify=CA, timeout=15, **kwargs)


def quota(token):
    result = request("GET", "/api/qa/quota", headers={"X-Anonymous-Token": token})
    assert result.status_code == 200
    return result.json()["used_count"]


def ask(token):
    time.sleep(0.55)
    return request(
        "POST",
        "/api/qa/ask",
        headers={"X-Anonymous-Token": token},
        json={"question": "Identity isolation acceptance question"},
    )


def proxy():
    assert request("GET", "/").status_code == 200
    assert request("GET", "/api/qa/quota").status_code == 401
    sessions = [requests.Session(), requests.Session()]
    tokens = []
    for session in sessions:
        session.verify = CA
        session.headers.update(
            {
                "Origin": ORIGIN,
                "X-Forwarded-For": "198.51.100.99, 203.0.113.8",
                "X-Forwarded-Proto": "http",
                "X-Real-IP": "198.51.100.99",
            }
        )
        result = session.post(
            BASE + "/api/session/anonymous", json={"transport": "cookie"}, timeout=15
        )
        assert result.status_code == 201 and "token" not in result.json()
        cookie = result.headers["set-cookie"].lower()
        assert all(
            part in cookie
            for part in ("httponly", "secure", "samesite=lax", "path=/api")
        )
        assert "domain=" not in cookie
        token = session.cookies.get("rag_anonymous")
        tokens.append(token)
        expiry = result.json()["expires_at"]
        time.sleep(0.2)
        reused = session.post(
            BASE + "/api/session/anonymous", json={"transport": "cookie"}, timeout=15
        )
        assert reused.status_code == 200
        assert reused.json()["expires_at"] == expiry
    assert tokens[0] != tokens[1]
    for index in (0, 0, 1):
        time.sleep(0.55)
        result = sessions[index].post(
            BASE + "/api/qa/ask", json={"question": "Cookie identity check"}, timeout=15
        )
        assert result.status_code == 200
    assert [quota(token) for token in tokens] == [2, 1]
    for session, count in zip(sessions, (2, 1)):
        result = session.get(BASE + "/api/qa/quota", timeout=15)
        assert result.status_code == 200 and result.json()["used_count"] == count
        session.close()
    header = request("POST", "/api/session/anonymous", json={"transport": "header"})
    assert header.status_code == 201 and "set-cookie" not in header.headers
    header_token = header.json()["token"]
    assert ask(header_token).status_code == 200 and quota(header_token) == 1
    both = request(
        "GET",
        "/api/qa/quota",
        headers={
            "X-Anonymous-Token": header_token,
            "Cookie": f"rag_anonymous={header_token}",
        },
    )
    assert both.status_code == 400
    invalid = request(
        "GET", "/api/qa/quota", headers={"X-Anonymous-Token": "anon_v1_" + "x" * 43}
    )
    assert invalid.status_code == 401
    cross_origin = request(
        "POST",
        "/api/session/anonymous",
        headers={"Origin": "https://untrusted.invalid"},
        json={"transport": "cookie"},
    )
    assert cross_origin.status_code == 403
    PRIVATE.write_text(
        json.dumps({"tokens": tokens + [header_token], "counts": [2, 1, 1]})
    )
    print(json.dumps({"proxy": "passed", "isolated_counts": [2, 1, 1]}))


def restart():
    state = json.loads(PRIVATE.read_text())
    assert [quota(t) for t in state["tokens"]] == state["counts"]
    print(json.dumps({"restart_identity_and_counts": "passed"}))


def rate(direct=False):
    statuses = []
    for index in range(31):
        kwargs = {
            "json": {"transport": "header"},
            "headers": {"X-Forwarded-For": f"198.51.100.{index + 1}"},
        }
        if direct:
            result = requests.post(
                "http://backend:8000/api/session/anonymous", timeout=15, **kwargs
            )
        else:
            result = request("POST", "/api/session/anonymous", **kwargs)
        statuses.append(result.status_code)
    assert statuses == [201] * 30 + [429]
    assert result.json()["detail"]["code"] == "rate_limited"
    assert int(result.headers["Retry-After"]) > 0
    print(
        json.dumps(
            {
                "spoofed_xff_cannot_bypass_session_limit": "passed",
                "route": "direct" if direct else "nginx",
            }
        )
    )


def frontend():
    from streamlit.testing.v1 import AppTest

    script = """
import requests
import streamlit as st
from frontend.components.chat_interface import ChatInterface
from frontend.utils.anonymous_session import identity_headers
base = 'http://backend:8000'
ChatInterface(base).render()
st.session_state.observed_quota = requests.get(
    base + '/api/qa/quota', headers=identity_headers(st.session_state, base), timeout=10
).json()['used_count']
"""
    first, second = (AppTest.from_string(script).run(timeout=20) for _ in range(2))
    assert not first.exception and not second.exception
    tokens = [at.session_state.anonymous_token for at in (first, second)]
    assert tokens[0] != tokens[1]
    for at in (first, second):
        at.button(key="suggestion_0").click().run(timeout=20)
        assert not at.exception
        assert at.session_state.observed_quota == 1
    first.chat_input[0].set_value("Second identity acceptance question").run(timeout=20)
    assert not first.exception
    for at, token, count in zip((first, second), tokens, (2, 1)):
        at.run(timeout=20)
        assert not at.exception
        assert at.session_state.anonymous_token == token
        assert at.session_state.observed_quota == count
    # Direct service calls must ignore self-reported client address and scheme.
    forged = requests.post(
        "http://backend:8000/api/session/anonymous",
        timeout=10,
        json={"transport": "header"},
        headers={
            "X-Forwarded-For": "198.51.100.99",
            "X-Forwarded-Proto": "https",
        },
    )
    assert forged.status_code == 201
    print(
        json.dumps(
            {
                "streamlit_real_http_sessions": "passed",
                "counts": [2, 1],
                "rerun_preserves_identity": True,
            }
        )
    )


def fault():
    state = json.loads(PRIVATE.read_text())
    before = len(Path("/evidence/engine-calls.jsonl").read_text().splitlines())
    response = ask(state["tokens"][0])
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "quota_storage_unavailable"
    assert len(Path("/evidence/engine-calls.jsonl").read_text().splitlines()) == before
    for method, path, kwargs in (
        (
            "GET",
            "/api/qa/quota",
            {"headers": {"X-Anonymous-Token": state["tokens"][0]}},
        ),
        ("POST", "/api/session/anonymous", {"json": {"transport": "header"}}),
    ):
        result = request(method, path, **kwargs)
        assert result.status_code == 503 and "token" not in result.json()
    # Directory-fsync failure can retain the replace, without acknowledging it.
    if sys.argv[2] == "directory_fsync":
        state["counts"][0] += 1
        PRIVATE.write_text(json.dumps(state))
    print(
        json.dumps(
            {
                "write_failure": sys.argv[2],
                "status": 503,
                "engine_calls_after_failure": 0,
                "latched_closed": True,
            }
        )
    )


if __name__ == "__main__":
    {
        "proxy": proxy,
        "restart": restart,
        "frontend": frontend,
        "rate": rate,
        "direct-rate": lambda: rate(direct=True),
        "fault": fault,
    }[sys.argv[1]]()
