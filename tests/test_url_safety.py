"""Offline URL and redirect regression tests; no external DNS or HTTP."""

import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIStatusError

from app.core import qa_engine
from app.core.config import Settings
from app.core.qa_engine import QAEngine
from app.core.url_safety import is_safe_base_url


@pytest.fixture
def public_dns(monkeypatch):
    resolver = Mock(return_value=[(socket.AF_INET, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    return resolver


@pytest.mark.parametrize(
    "url, allowed",
    [
        ("https://allowed.example/v1", True),
        ("https://ALLOWED.example:443/v1/", True),
        ("https://allowed.example.untrusted.invalid/v1", False),
        ("https://allowed.example:444/v1", False),
        ("https://allowed.example:0/v1", False),
        ("https://allowed.example:/v1", False),
        ("https://allowed.example:65536/v1", False),
        ("http://allowed.example/v1", False),
        ("https://user@allowed.example/v1", False),
        ("https://allowed.example@evil.invalid/v1", False),
        ("https://allowed.example/v10", False),
        ("https://allowed.example/v1/other", False),
        ("https://allowed.example/v1/../other", False),
        ("https://allowed.example/v1/%2e%2e/other", False),
        ("https://allowed.example//v1", False),
        ("https://allowed.example/v1?target=other", False),
        ("https://allowed.example/v1#other", False),
        ("https://allowed.example\\@evil.invalid/v1", False),
        ("https://allowed.example./v1", False),
        (" https://allowed.example/v1", False),
        ("https://allowed.example/v1\n", False),
        ("https://allowed.example:bad/v1", False),
    ],
)
def test_exact_origin_and_base_path(public_dns, url, allowed):
    assert is_safe_base_url(url, ["https://allowed.example/v1"]) is allowed
    if not allowed:
        public_dns.assert_not_called()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "224.0.0.1",
        "0.0.0.0",
    ],
)
def test_any_nonpublic_dns_answer_rejects(public_dns, address):
    public_dns.return_value.append((socket.AF_INET, 1, 6, "", (address, 443)))
    assert not is_safe_base_url(
        "https://allowed.example/v1", ["https://allowed.example/v1"]
    )


def test_dns_failure_and_empty_answer_reject(public_dns):
    public_dns.side_effect = socket.gaierror()
    assert not is_safe_base_url("https://allowed.example", ["https://allowed.example"])
    public_dns.side_effect = None
    public_dns.return_value = []
    assert not is_safe_base_url("https://allowed.example", ["https://allowed.example"])


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_chat_sdk_never_follows_redirect(monkeypatch, asynchronous, status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status, headers={"Location": "https://untrusted.invalid/target"}
        )

    client_class, async_class = httpx.Client, httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        qa_engine,
        "httpx",
        SimpleNamespace(
            Client=lambda **kw: client_class(transport=transport, **kw),
            AsyncClient=lambda **kw: async_class(transport=transport, **kw),
        ),
    )
    monkeypatch.setattr(
        Settings,
        "get_model_config",
        lambda *a: {
            "provider": "openai",
            "chat_model": "test-model",
            "api_base_url": "https://allowed.example/v1",
        },
    )
    engine = QAEngine.__new__(QAEngine)
    engine._overrides = {"api_key": "test-only"}
    engine._initialize_llm()
    try:
        with pytest.raises(APIStatusError):
            if asynchronous:
                asyncio.run(engine.llm.ainvoke("test"))
            else:
                engine.llm.invoke("test")
        assert len(requests) == 1
        assert requests[0].url.host == "allowed.example"
    finally:
        engine.llm.http_client.close()
        asyncio.run(engine.llm.http_async_client.aclose())
