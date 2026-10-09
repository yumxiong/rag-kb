"""Probe real admission through the local HTTPS gateway, no provider calls."""

import http.client
import http.cookiejar
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://localhost:18443"
TLS = ssl.create_default_context(
    cafile=str(ROOT / "rag-step5-local-next-gateway/certs/cert.pem")
)


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=TLS),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def request(self, path, body=None, origin=ORIGIN):
        headers = {"Origin": origin}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            ORIGIN + path, headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        try:
            response = self.opener.open(req, timeout=80)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            result = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"
            return response.status, result

    def connect(self):
        status, _ = self.request("/api/session/anonymous", {"transport": "cookie"})
        assert status in (200, 201)

    def used(self):
        status, body = self.request("/api/qa/quota")
        assert status == 200
        return body["used_count"]

    def ask(self, question, expected=200, code=None):
        time.sleep(0.6)
        status, body = self.request("/api/qa/ask", {"question": question})
        assert status == expected, (status, body)
        if code:
            assert body["detail"]["code"] == code
        return body


def main():
    a, b = Client(), Client()
    a.connect()
    b.connect()
    assert a.used() == b.used() == 0
    a.ask("normal")
    assert a.used() == 1 and b.used() == 0
    a.connect()
    assert a.used() == 1
    time.sleep(0.6)
    status, body = a.request(
        "/api/qa/ask", {"question": "blocked-origin"}, "https://untrusted.invalid"
    )
    assert status == 403 and body["detail"]["code"] == "origin_not_allowed"
    assert a.used() == 1
    a.ask("failure", 502, "upstream_error")
    assert a.ask("cached")["from_cache"] is True
    assert a.used() == 3
    a.ask("normal")
    a.ask("normal")
    a.ask("normal", 429, "quota_exceeded")
    assert a.used() == 5 and b.used() == 0
    print(
        "PASS: identity isolation/reuse, Origin rejection, failure/cache counts, quota",
        flush=True,
    )

    # Close an admitted request before the synthetic worker completes.
    cookie = "; ".join(f"{c.name}={c.value}" for c in b.jar)
    connection = http.client.HTTPSConnection("localhost", 18443, context=TLS)
    connection.request(
        "POST", "/api/qa/ask", json.dumps({"question": "cancel-slow"}),
        {"Origin": ORIGIN, "Cookie": cookie, "Content-Type": "application/json"},
    )
    time.sleep(1)
    assert b.used() == 1
    connection.close()
    b.ask("while-cancelled", 503, "service_busy")
    assert b.used() == 1
    time.sleep(8)
    assert b.used() == 1
    b.ask("explicit-retry")
    assert b.used() == 2
    print(
        "PASS: disconnect counted once, no replay/refund, slot held, explicit retry",
        flush=True,
    )

    start = time.monotonic()
    b.ask("deadline-slow", 504, "upstream_timeout")
    assert 59 <= time.monotonic() - start < 75
    assert b.used() == 3
    b.ask("while-worker-finishes", 503, "service_busy")
    assert b.used() == 3
    time.sleep(11)
    b.ask("after-worker")
    assert b.used() == 4 and a.used() == 5
    print(
        "PASS: real 60s deadline, worker slot retained, recovery without refund",
        flush=True,
    )


if __name__ == "__main__":
    main()
