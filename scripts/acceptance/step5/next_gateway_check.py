"""Prepare or probe the isolated HTTPS gateway; never load real configuration."""

import argparse
import concurrent.futures
import datetime
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "rag-step5-local-next-gateway"


def prepare():
    """Create a disposable self-signed certificate and rendered template."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    RUNTIME.mkdir(exist_ok=False)
    certs = RUNTIME / "certs"
    certs.mkdir()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        .sign(key, hashes.SHA256())
    )
    (certs / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (certs / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    text = (ROOT / "docker/nginx/conf.d/next.conf.template").read_text("utf-8")
    for variable, value in {
        "NEXT_DOMAIN": "localhost",
        "NEXT_TLS_CERT": "/etc/nginx/smoke-certs/cert.pem",
        "NEXT_TLS_KEY": "/etc/nginx/smoke-certs/key.pem",
    }.items():
        text = text.replace("${" + variable + "}", value)
    (RUNTIME / "next.conf").write_text(text, encoding="utf-8")
    print("Prepared disposable gateway configuration and certificate.")


def probe():
    """Assert transport behavior, not real backend admission or supplier behavior."""
    origin = "https://localhost:18443"
    context = ssl.create_default_context(cafile=str(RUNTIME / "certs/cert.pem"))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
    )

    def request(path, body=None, cookie=False, timeout=10):
        headers = {"Origin": origin, "X-Forwarded-For": "203.0.113.99"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = "rag_anonymous=synthetic-only"
        req = urllib.request.Request(
            origin + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        try:
            response = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    assert request("/")[0] == 200
    assert request("/icon.svg")[0] == 200
    status, headers, _ = request("/api/session/anonymous", {})
    assert status == 201
    assert "HttpOnly; Secure; SameSite=Lax; Path=/api" in headers["Set-Cookie"]
    before = json.loads(request("/api/__fixture/status")[2])["asks"]
    status, _, body = request("/api/qa/ask", {}, cookie=True)
    received = json.loads(body)
    assert status == 200 and received["cookieForwarded"]
    assert received["origin"] == origin and received["forwardedProto"] == "https"
    assert received["forwardedFor"] != "203.0.113.99"
    for expected, code in [
        (429, "quota_exceeded"),
        (503, "global_budget_exceeded"),
        (502, "upstream_error"),
        (504, "upstream_timeout"),
    ]:
        time.sleep(0.6)  # Exercise backend errors, not the gateway ask limiter.
        status, headers, body = request("/api/qa/ask", {"status": expected})
        assert status == expected and json.loads(body)["detail"]["code"] == code
        assert headers["X-Request-ID"] == "synthetic-gateway"
        assert headers["Cache-Control"] == "no-store"
        if status == 429:
            assert headers["Retry-After"] == "7"
    after = json.loads(request("/api/__fixture/status")[2])["asks"]
    assert after - before == 5
    for mode, expected, code in [
        ("disconnect", 502, "upstream_error"),
        ("timeout", 504, "upstream_timeout"),
    ]:
        time.sleep(0.6)
        started = time.monotonic()
        status, headers, body = request(
            "/api/qa/ask", {"mode": mode}, timeout=105
        )
        elapsed = time.monotonic() - started
        assert status == expected and json.loads(body)["detail"]["code"] == code
        assert headers["X-Request-ID"] != "synthetic-gateway"
        assert headers["X-Request-ID"] == json.loads(body)["detail"]["request_id"]
        assert headers["Cache-Control"] == "no-store"
        if mode == "timeout":
            assert 89 <= elapsed < 105, elapsed
    after = json.loads(request("/api/__fixture/status")[2])["asks"]
    assert after - before == 7, "Gateway must not replay failed asks"
    # Burst a public fixture route through the actual general API limiter.
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(lambda _: request("/api/__fixture/status"), range(80)))
    limited = [r for r in results if r[0] == 429]
    assert limited, "Expected gateway rate limiting"
    for _, headers, body in limited:
        assert json.loads(body)["detail"]["code"] == "rate_limited"
        assert headers["Retry-After"] == "1"
    assert request("/ws/unused")[0] == 404
    print("PASS: HTTPS routing, cookie/origin, trusted headers, backend errors,")
    print("single ask attempts, gateway 502/90s 504, rate limit, /ws/ 404.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "probe"])
    arguments = parser.parse_args()
    prepare() if arguments.action == "prepare" else probe()
