"""Local candidate acceptance only: synthetic data, loopback ports, no ACME calls."""

import datetime
import http.client
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / (
    "rag-step5-local-first-deployment-"
    + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
)
PROJECT = "rag-step5-first-check"
HOSTS = ("otocshow.xyz", "next.otocshow.xyz")
ENV = {
    key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")
}
ENV["COMPOSE_DISABLE_ENV_FILE"] = "1"


def docker(*args, check=True):
    result = subprocess.run(
        ["docker", *args], env=ENV, capture_output=True, text=True, encoding="utf-8"
    )
    if check and result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def compose(stage, *args, check=True):
    files = ["-f", str(RUN / "bundle" / f"compose.{stage}.yml")]
    if stage == "app":
        files += ["-f", str(RUN / "isolation.yml")]
    return docker(
        "compose",
        "--env-file",
        str(RUN / "release.env"),
        "-p",
        PROJECT,
        *files,
        *args,
        check=check,
    )


def certificate(host, serial):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = RUN / "certbot/conf/live" / host
    directory.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(serial)
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False)
        .sign(key, hashes.SHA256())
    )
    (directory / "fullchain.pem").write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
    )
    (directory / "privkey.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def tls_context(host):
    return ssl.create_default_context(
        cafile=str(RUN / "certbot/conf/live" / host / "fullchain.pem")
    )


def check_unknown_sni(port=18443):
    """Require a server unrecognized-name alert, not client certificate rejection."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Only this negative probe disables verification: a default certificate must
    # complete the handshake and fail the assertion, regardless of its identity.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname="www.otocshow.xyz"):
                raise AssertionError("www TLS must not terminate at app gateway")
    except ssl.SSLError as error:
        if error.reason != "TLSV1_UNRECOGNIZED_NAME":
            raise


def check_isolation():
    """Validate resolved synthetic mounts and ports before starting any service."""
    for stage in ("init", "app", "certbot"):
        config = json.loads(compose(stage, "config", "--format", "json").stdout)
        for name, service in config["services"].items():
            for volume in service.get("volumes", []):
                if volume["type"] != "bind":
                    raise RuntimeError("Unexpected non-bind acceptance volume")
                source = Path(volume["source"]).resolve()
                if not source.is_relative_to(RUN.resolve()):
                    raise RuntimeError("Acceptance bind escaped synthetic directory")
            for port in service.get("ports", []):
                if (
                    name != "nginx"
                    or port.get("host_ip") != "127.0.0.1"
                    or str(port["published"]) not in {"18080", "18443"}
                ):
                    raise RuntimeError("Unexpected acceptance port publication")


def request(host, path, body=None, cookie=None, secure=True, origin=None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", 18443 if secure else 18080, timeout=15
    )
    connection.connect()
    if secure:
        connection.sock = tls_context(host).wrap_socket(
            connection.sock, server_hostname=host
        )
    headers = {"Host": host, "Origin": origin or "https://" + host}
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection.request(
        "POST" if body is not None else "GET",
        path,
        None if body is None else json.dumps(body),
        headers,
    )
    response = connection.getresponse()
    result = (
        response.status,
        {key.lower(): value for key, value in response.getheaders()},
        response.read(),
    )
    connection.close()
    return result


def prepare():
    if RUN.exists():
        raise RuntimeError("Refusing to overwrite earlier acceptance directory")
    if docker(
        "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"
    ).stdout.strip():
        raise RuntimeError("Acceptance project already exists")
    networks = docker("network", "ls", "-q").stdout.split()
    for network in networks:
        value = json.loads(docker("network", "inspect", network).stdout)[0]
        for config in value.get("IPAM", {}).get("Config", []) or []:
            subnet = config.get("Subnet")
            if subnet and ipaddress.ip_network(subnet).version == 4:
                if ipaddress.ip_network(subnet).overlaps(
                    ipaddress.ip_network("172.30.0.0/24")
                ):
                    raise RuntimeError("Candidate subnet overlaps an existing network")
    for port in (18080, 18443):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    RUN.mkdir()
    print("Acceptance directory:", RUN, flush=True)
    shutil.copytree(ROOT / "docker/step5-candidate", RUN / "bundle")
    for directory in (
        "data",
        "secrets",
        "config",
        "state",
        "certbot/conf",
        "certbot/www/.well-known/acme-challenge",
    ):
        (RUN / directory).mkdir(parents=True, exist_ok=True)
    (RUN / "backend.env").write_text("# Synthetic empty acceptance input\n")
    (RUN / "config/anonymous-store-reference.json").write_text("{}\n")
    (RUN / "certbot/www/.well-known/acme-challenge/probe").write_text("synthetic-acme")
    images = {}
    for variable, image in {
        "BACKEND_IMAGE": "rag-step5-backend:62d4cff",
        "STREAMLIT_IMAGE": "rag-step5-streamlit:62d4cff",
        "NEXT_IMAGE": "rag-step5-next:62d4cff",
        "NGINX_IMAGE": "nginx:1.28-alpine",
        "CERTBOT_IMAGE": "certbot/certbot:latest",
    }.items():
        images[variable] = docker(
            "image", "inspect", image, "--format", "{{.Id}}"
        ).stdout.strip()
    values = {
        **images,
        "DEPLOY_ROOT": RUN.as_posix(),
        "BIND_IP": "127.0.0.1",
        "HTTP_PORT": "18080",
        "HTTPS_PORT": "18443",
        "ANONYMOUS_MOUNT_SOURCE": "synthetic-unused-fixture",
    }
    # Shell variables take precedence over --env-file in Compose.
    ENV.update(values)
    (RUN / "release.env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    (RUN / "images.json").write_text(json.dumps(images, indent=2))
    fixture = (ROOT / "scripts/acceptance/step5/real_gateway_fixture.py").read_text(
        "utf-8"
    )
    fixture = fixture.replace('"/workspace"', '"/app"').replace(
        '"172.30.245.3"', '"172.30.0.10"'
    )
    fixture = fixture.replace(
        '"https://localhost:18443"', '"https://otocshow.xyz,https://next.otocshow.xyz"'
    )
    fixture = fixture.replace(
        "class VectorFixture:\n",
        "class VectorFixture:\n    def list_documents(self):\n"
        '        return [{"filename": "synthetic.md", "chunk_count": 1}]\n\n',
    )
    (RUN / "fixture.py").write_text(fixture, encoding="utf-8")
    (RUN / "isolation.yml").write_text(
        """services:
  backend:
    entrypoint: [python, /fixture/fixture.py]
    command: []
    working_dir: /tmp
    read_only: true
    tmpfs: [/tmp]
    environment:
      PYTHONDONTWRITEBYTECODE: '1'
    volumes:
      - ./fixture.py:/fixture/fixture.py:ro
  nginx:
    networks:
      ingress: {}
networks:
  rag:
    internal: true
  ingress: {}
"""
    )
    # Override paths are relative to the first Compose file, not this file.
    isolation = (
        (RUN / "isolation.yml").read_text().replace("./fixture.py:", "../fixture.py:")
    )
    (RUN / "isolation.yml").write_text(isolation)
    check_isolation()


def check_init():
    compose("init", "config", "--quiet")
    compose("init", "up", "-d", "--wait")
    compose("init", "exec", "-T", "nginx", "nginx", "-t")
    for host in HOSTS:
        assert (
            request(host, "/.well-known/acme-challenge/probe", secure=False)[2]
            == b"synthetic-acme"
        )
        assert request(host, "/", secure=False)[0] == 503
        assert request(host, "/api/qa/ask", secure=False)[0] == 503
        assert (
            request(host, "/.well-known/acme-challenge/missing", secure=False)[0] == 404
        )
    assert request("www.otocshow.xyz", "/", secure=False)[0] == 404
    assert request("localhost", "/health", secure=False)[0] == 200
    assert not (RUN / "certbot/conf/live").exists()
    print(
        "PASS: certificate-free init, both ACME paths, no app exposure, www excluded",
        flush=True,
    )
    compose("init", "down")


def check_final():
    for index, host in enumerate(HOSTS):
        certificate(host, 1001 + index)
    compose("app", "config", "--quiet")
    compose("app", "up", "-d", "--wait", "--wait-timeout", "150")
    compose("app", "exec", "-T", "nginx", "nginx", "-t")
    for host in HOSTS:
        assert request(host, "/")[0] == 200
        assert (
            request(host, "/", secure=False)[1]["location"] == "https://" + host + "/"
        )
        assert (
            request(host, "/.well-known/acme-challenge/probe", secure=False)[2]
            == b"synthetic-acme"
        )
        for path, expected in (
            ("/api/documents/library", 200),
            ("/api/documents/test", 401),
            ("/ws/test", 404),
            ("/docs", 404),
        ):
            assert request(host, path)[0] == expected
    assert request(HOSTS[1], "/icon.svg")[0] == 200
    assert request(HOSTS[0], "/_stcore/health")[2] == b"ok"
    assert request("www.otocshow.xyz", "/", secure=False)[0] == 404
    check_unknown_sni()
    status, headers, _ = request(
        HOSTS[1], "/api/session/anonymous", {"transport": "cookie"}
    )
    assert status == 201
    cookie = headers["set-cookie"].split(";", 1)[0]
    assert all(
        value in headers["set-cookie"] for value in ("HttpOnly", "Secure", "Path=/api")
    )
    assert "Domain=" not in headers["set-cookie"]
    assert request(HOSTS[1], "/api/qa/ask", {"question": "normal"}, cookie)[0] == 200
    assert (
        request(
            HOSTS[1],
            "/api/qa/ask",
            {"question": "blocked"},
            cookie,
            origin="https://untrusted.invalid",
        )[0]
        == 403
    )
    assert (
        json.loads(request(HOSTS[1], "/api/qa/quota", cookie=cookie)[2])["used_count"]
        == 1
    )
    with socket.create_connection(("127.0.0.1", 18443), timeout=10) as raw:
        with tls_context(HOSTS[0]).wrap_socket(raw, server_hostname=HOSTS[0]) as stream:
            stream.sendall(
                b"GET /_stcore/stream HTTP/1.1\r\nHost: otocshow.xyz\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                b"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: streamlit\r\n"
                b"Origin: https://otocshow.xyz\r\n\r\n"
            )
            assert stream.recv(4096).startswith(b"HTTP/1.1 101")
    for identifier in compose("app", "ps", "-q").stdout.split():
        info = json.loads(docker("inspect", identifier).stdout)[0]
        ports = info["HostConfig"].get("PortBindings") or {}
        service = info["Config"]["Labels"]["com.docker.compose.service"]
        if service != "nginx":
            assert not ports
        else:
            assert all(
                v["HostIp"] == "127.0.0.1" for items in ports.values() for v in items
            )
    print(
        "PASS: final dual TLS/ACME, pages, websocket, "
        "identity/admission, Origin, ports",
        flush=True,
    )
    # Renewal artifact loading, without calling an ACME server.
    certificate(HOSTS[1], 2002)
    compose("app", "exec", "-T", "nginx", "nginx", "-t")
    compose("app", "exec", "-T", "nginx", "nginx", "-s", "reload")
    import time

    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", 18443), timeout=5) as raw:
                with tls_context(HOSTS[1]).wrap_socket(
                    raw, server_hostname=HOSTS[1]
                ) as stream:
                    assert int(stream.getpeercert()["serialNumber"], 16) == 2002
            break
        except ssl.SSLCertVerificationError:
            time.sleep(0.2)
    else:
        raise AssertionError("New certificate not served after reload")
    bad = RUN / "bundle/nginx/final/invalid.conf"
    bad.write_text("invalid_test_directive;\n")
    assert (
        compose("app", "exec", "-T", "nginx", "nginx", "-t", check=False).returncode
        != 0
    )
    assert request(HOSTS[1], "/")[0] == 200
    bad.unlink()
    compose("app", "exec", "-T", "nginx", "nginx", "-t")
    print(
        "PASS: synthetic certificate replacement/reload; "
        "invalid config rejected, old workers serve",
        flush=True,
    )


def main():
    prepare()
    try:
        check_init()
        check_final()
        compose("certbot", "config", "--quiet")
        # No account, certificate issuance, renewal, or provider network call.
        print(
            compose(
                "certbot", "run", "--rm", "--no-deps", "certbot", "--version"
            ).stdout.strip(),
            flush=True,
        )
    finally:
        compose("app", "down", "--remove-orphans")
        compose("init", "down", "--remove-orphans")
        compose("certbot", "down", "--remove-orphans")
    assert not docker(
        "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"
    ).stdout.strip()
    assert not docker(
        "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"
    ).stdout.strip()
    print(
        "PASS: project containers and networks cleaned; "
        "synthetic files retained in ignored directory"
    )


if __name__ == "__main__":
    main()
