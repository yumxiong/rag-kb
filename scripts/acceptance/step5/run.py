"""Opt-in Docker Linux identity acceptance; never uses deployment data or secrets.

Run from the deploy workspace: python scripts/acceptance/step5/run.py
Requires local docker-backend:latest, docker-frontend:latest, nginx:alpine and PyYAML.
Only this run's randomly named containers, volumes and network are removed.
"""

import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
CHECKS = Path(__file__).resolve().parent
PREFIX = "step5-" + uuid.uuid4().hex[:10]
OUTPUT = ROOT / "logs" / PREFIX
OUTPUT.mkdir(parents=True)
REPORT = {
    "run_id": PREFIX,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "scope": "Docker Desktop Linux, not production acceptance",
    "model_and_retrieval": "test doubles; no external model calls",
    "checks": [],
}
RESOURCES = {"containers": [], "volumes": [], "networks": []}


def docker(*args, check=True):
    result = subprocess.run(
        ["docker", *map(str, args)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if check and result.returncode:
        # Do not expose runtime credentials even on an assertion failure.
        safe = re.sub(r"anon_v1_[A-Za-z0-9_-]{43}", "<redacted>", result.stderr)
        raise RuntimeError(f"docker {args[0]} failed: {safe[-5000:]}")
    return result


def container(
    name,
    image,
    command=(),
    mounts=(),
    env=None,
    network=True,
    address=None,
    alias=None,
    extra=(),
    detach=False,
):
    full_name = PREFIX + "-" + name
    args = ["run", "--name", full_name, "--label", f"step5.run={PREFIX}"]
    args += ["--network", PREFIX if network else "none"]
    if detach:
        args += ["-d"]
    if address:
        args += ["--ip", address]
    if alias:
        args += ["--network-alias", alias]
    for mount in mounts:
        args += ["--mount", mount]
    for key, value in (env or {}).items():
        args += ["-e", f"{key}={value}"]
    RESOURCES["containers"].append(full_name)
    return docker(*args, *extra, image, *command)


def volume(name, target, readonly=False):
    return f"type=volume,source={PREFIX}-{name},target={target}" + (
        ",readonly" if readonly else ""
    )


def bind(path, target):
    return f"type=bind,source={path},target={target},readonly"


SOURCE = [bind(ROOT / "app", "/app/app"), bind(CHECKS, "/checks")]
ENV = {"PYTHONPATH": "/checks:/app", "PYTHONDONTWRITEBYTECODE": "1"}


def record(name, result):
    safe = re.sub(
        r"anon_v1_[A-Za-z0-9_-]{43}", "<redacted>", result.stdout + result.stderr
    )
    (OUTPUT / f"{name}.log").write_text(safe, encoding="utf-8")
    entry = {"name": name, "exit_code": result.returncode}
    for line in result.stdout.splitlines():
        try:
            entry["result"] = json.loads(line)
        except ValueError:
            pass
    test_count = re.search(r"Ran (\d+) tests", result.stderr)
    if test_count:
        entry["tests_run"] = int(test_count[1])
    REPORT["checks"].append(entry)
    print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)


def execute(service, *args):
    return docker("exec", PREFIX + "-" + service, *args)


def wait_backend():
    for _ in range(60):
        result = docker(
            "exec",
            PREFIX + "-backend",
            "python",
            "-c",
            "import urllib.request; "
            "urllib.request.urlopen('http://localhost:8000/health', timeout=1)",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("Backend did not start; inspect sanitized backend log")


def main():
    base = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text("utf-8"))
    sim = yaml.safe_load(
        (ROOT / "docker/docker-compose.public-sim.yml").read_text("utf-8")
    )
    prod = yaml.safe_load(
        (ROOT / "docker/docker-compose.production.yml.template").read_text("utf-8")
    )
    subnet = base["networks"]["rag_network"]["ipam"]["config"][0]["subnet"]
    proxy_ip = sim["services"]["nginx"]["networks"]["rag_network"]["ipv4_address"]
    for config in (sim, prod):
        assert (
            config["services"]["backend"]["environment"]["TRUSTED_PROXY_IPS"]
            == proxy_ip
        )
        assert (
            config["services"]["nginx"]["networks"]["rag_network"]["ipv4_address"]
            == proxy_ip
        )
        assert isinstance(config["services"]["frontend"]["networks"], list)
    existing = json.loads(
        docker(
            "network", "inspect", *docker("network", "ls", "-q").stdout.split()
        ).stdout
    )
    networks = []
    for network in existing:
        for entry in network["IPAM"].get("Config") or []:
            candidate = entry.get("Subnet")
            if candidate:
                networks.append({"name": network["Name"], "subnet": candidate})
                assert not ipaddress.ip_network(subnet).overlaps(
                    ipaddress.ip_network(candidate)
                ), (
                    "Configured subnet overlaps an existing network; "
                    "choose and document a different subnet"
                )
    REPORT["existing_networks"] = networks
    REPORT["test_network"] = {"subnet": subnet, "nginx": proxy_ip, "internal": True}
    REPORT["docker"] = docker(
        "info", "--format", "{{.OSType}} {{.KernelVersion}}"
    ).stdout.strip()
    REPORT["head"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    source_paths = (
        set((ROOT / "app").rglob("*.py"))
        | set((ROOT / "frontend").rglob("*.py"))
        | set(CHECKS.glob("*.py"))
        | {
            ROOT / "docker/docker-compose.yml",
            ROOT / "docker/docker-compose.public-sim.yml",
            ROOT / "docker/docker-compose.production.yml.template",
            ROOT / "docker/Dockerfile.backend",
            ROOT / "docker/nginx/conf.d/public-sim.conf",
        }
    )
    REPORT["source_sha256"] = {
        str(path.relative_to(ROOT))
        .replace("\\", "/"): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in sorted(source_paths)
    }
    REPORT["images"] = {}
    for image in ("docker-backend:latest", "docker-frontend:latest", "nginx:alpine"):
        details = json.loads(docker("image", "inspect", image).stdout)[0]
        REPORT["images"][image] = details["Id"]
    image_cmd = json.loads(docker("image", "inspect", "docker-backend:latest").stdout)[
        0
    ]["Config"]["Cmd"]
    assert (
        "--proxy-headers" in image_cmd[-1] and "--forwarded-allow-ips" in image_cmd[-1]
    )
    assert "TRUSTED_PROXY_IPS" in image_cmd[-1] and "*" not in image_cmd[-1]
    for name in (
        "data",
        "reference",
        "evidence",
        "certs",
        "storage-tests",
        "reference-tests",
    ):
        full = PREFIX + "-" + name
        docker("volume", "create", "--label", f"step5.run={PREFIX}", full)
        RESOURCES["volumes"].append(full)
    docker(
        "network",
        "create",
        "--internal",
        "--subnet",
        subnet,
        "--label",
        f"step5.run={PREFIX}",
        PREFIX,
    )
    RESOURCES["networks"].append(PREFIX)
    prefix_ip = proxy_ip.rsplit(".", 1)[0]
    backend_ip, frontend_ip, client_ip = (
        prefix_ip + suffix for suffix in (".20", ".30", ".40")
    )

    provision = """
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from app.core.anonymous_session import bootstrap
from storage_checks import mount_record
mount = mount_record(Path('/app/data'))
assert mount['filesystem'] not in ('9p', 'virtiofs', 'fuse.grpcfuse')
bootstrap(Path('/app/data/quotas'), Path('/reference/store.json'),
          mount_path='/app/data', mount_source=mount['source'])
Path('/evidence/mount.json').write_text(json.dumps(mount))
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Step 5 isolated test')])
now = datetime.now(timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('nginx'),
                       x509.DNSName('local.rag-kb.dev')]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
Path('/certs/local-cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
Path('/certs/local-key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
Path('/certs/local-key.pem').chmod(0o600)
print(json.dumps(mount))
"""
    provisioned = container(
        "provision",
        "docker-backend:latest",
        ["python", "-c", provision],
        mounts=SOURCE
        + [
            volume("data", "/app/data"),
            volume("reference", "/reference"),
            volume("evidence", "/evidence"),
            volume("certs", "/certs"),
        ],
        env=ENV,
        network=False,
    )
    REPORT["linux_data_mount"] = json.loads(provisioned.stdout.strip())
    record("bootstrap", provisioned)
    storage = container(
        "storage",
        "docker-backend:latest",
        ["python", "/checks/storage_checks.py"],
        mounts=SOURCE
        + [
            volume("storage-tests", "/storage-tests"),
            volume("reference-tests", "/reference-tests"),
        ],
        env=ENV,
        network=False,
    )
    record("linux-storage", storage)
    backend_env = ENV | {
        "QUOTA_STORAGE_PATH": "/app/data/quotas",
        "ANONYMOUS_STORE_REFERENCE": "/reference/store.json",
        "ANONYMOUS_MOUNT_PATH": "/app/data",
        "ANONYMOUS_MOUNT_SOURCE": REPORT["linux_data_mount"]["source"],
        "ANONYMOUS_STORAGE_DEVELOPMENT": "false",
        "ANONYMOUS_COOKIE_SECURE": "true",
        "ALLOWED_ORIGINS": "https://local.rag-kb.dev",
        "TRUSTED_PROXY_IPS": proxy_ip,
        "ENABLE_QUOTA_LIMIT": "true",
        "DEFAULT_DAILY_QUOTA": "5",
    }
    mounts = SOURCE + [
        volume("data", "/app/data"),
        volume("reference", "/reference", True),
        volume("evidence", "/evidence"),
    ]
    command = [
        part.replace("app.main:app", "backend_fixture:app") for part in image_cmd
    ]
    container(
        "backend",
        "docker-backend:latest",
        command,
        mounts=mounts,
        env=backend_env,
        address=backend_ip,
        alias="backend",
        detach=True,
    )
    wait_backend()
    frontend_mounts = [
        bind(ROOT / "frontend", "/app/frontend"),
        bind(CHECKS, "/checks"),
        volume("evidence", "/evidence"),
        volume("certs", "/certs", True),
    ]
    container(
        "frontend",
        "docker-frontend:latest",
        mounts=frontend_mounts,
        env=ENV | {"BACKEND_URL": "http://backend:8000"},
        address=frontend_ip,
        alias="frontend",
        detach=True,
    )
    for _ in range(40):
        ready = docker(
            "exec",
            PREFIX + "-frontend",
            "python",
            "-c",
            "import urllib.request; "
            "urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=1)",
            check=False,
        )
        if ready.returncode == 0:
            break
        time.sleep(0.5)
    assert ready.returncode == 0
    container(
        "nginx",
        "nginx:alpine",
        mounts=[
            bind(
                ROOT / "docker/nginx/conf.d/public-sim.conf",
                "/etc/nginx/conf.d/default.conf",
            ),
            volume("certs", "/etc/nginx/certs", True),
        ],
        address=proxy_ip,
        alias="nginx",
        detach=True,
    )
    record("nginx-config", execute("nginx", "nginx", "-t"))
    container(
        "client",
        "docker-frontend:latest",
        ["sleep", "infinity"],
        mounts=frontend_mounts,
        env=ENV,
        address=client_ip,
        detach=True,
    )
    record(
        "https-proxy", execute("client", "python", "/checks/client_checks.py", "proxy")
    )
    record(
        "streamlit-http",
        execute("frontend", "python", "/checks/client_checks.py", "frontend"),
    )

    # Check what Uvicorn actually placed in the ASGI scope, not an echo of XFF.
    observations = execute("backend", "cat", "/evidence/requests.jsonl").stdout
    (OUTPUT / "proxy-observations.jsonl").write_text(observations, encoding="utf-8")
    events = [json.loads(line) for line in observations.splitlines()]
    session_events = [
        e
        for e in events
        if e["path"] == "/api/session/anonymous" and e["status"] in (200, 201)
    ]
    assert {e["peer"] for e in session_events} == {client_ip, frontend_ip}
    assert all(
        e["scheme"] == ("https" if e["peer"] == client_ip else "http")
        for e in session_events
    )
    assert all(e["peer"] != proxy_ip for e in session_events)
    REPORT["proxy_scope"] = {
        "nginx_client_peer": client_ip,
        "streamlit_direct_peer": frontend_ip,
        "spoofed_xff_ignored": True,
        "schemes": ["https", "http"],
    }
    state = json.loads(
        execute("backend", "cat", "/app/data/quotas/quota-state-v1.json").stdout
    )
    sources = next(iter(state["days"].values()))["session_ip"]
    assert set(sources) == {
        hashlib.sha256(ip.encode()).hexdigest() for ip in (client_ip, frontend_ip)
    }
    for method in ("restart", "kill", "recreate"):
        if method == "kill":
            docker("kill", "--signal", "KILL", PREFIX + "-backend")
            docker("start", PREFIX + "-backend")
        elif method == "recreate":
            logs = docker("logs", PREFIX + "-backend")
            assert not re.search(
                r"anon_v1_[A-Za-z0-9_-]{43}", logs.stdout + logs.stderr
            ), "Credential in service logs"
            record("backend-before-recreate", logs)
            docker("rm", "-f", PREFIX + "-backend")
            RESOURCES["containers"].remove(PREFIX + "-backend")
            container(
                "backend",
                "docker-backend:latest",
                command,
                mounts=mounts,
                env=backend_env,
                address=backend_ip,
                alias="backend",
                detach=True,
            )
        else:
            docker("restart", PREFIX + "-backend")
        wait_backend()
        persisted = json.loads(
            execute("backend", "cat", "/app/data/quotas/quota-state-v1.json").stdout
        )
        assert persisted == state  # Includes daily creation counts and expiry.
        record(
            method + "-persistence",
            execute("client", "python", "/checks/client_checks.py", "restart"),
        )
    record(
        "session-rate", execute("client", "python", "/checks/client_checks.py", "rate")
    )
    docker("restart", PREFIX + "-backend")
    wait_backend()
    record(
        "direct-session-rate",
        execute("frontend", "python", "/checks/client_checks.py", "direct-rate"),
    )
    for stage in ("temporary", "file_fsync", "replace", "directory_fsync"):
        docker("restart", PREFIX + "-backend")
        wait_backend()
        execute(
            "backend",
            "python",
            "-c",
            "from pathlib import Path; "
            f"Path('/evidence/fault.txt').write_text('{stage}')",
        )
        record(
            "http-fault-" + stage,
            execute("client", "python", "/checks/client_checks.py", "fault", stage),
        )
        docker("restart", PREFIX + "-backend")
        wait_backend()
        record(
            "recovery-" + stage,
            execute("client", "python", "/checks/client_checks.py", "restart"),
        )

    # The same production process must refuse a genuinely read-only Linux volume.
    docker("stop", PREFIX + "-backend")
    readonly = container(
        "readonly",
        "docker-backend:latest",
        image_cmd,
        mounts=SOURCE
        + [volume("data", "/app/data", True), volume("reference", "/reference", True)],
        env=backend_env,
        network=False,
        detach=True,
    )
    assert readonly.returncode == 0
    code = int(docker("wait", PREFIX + "-readonly").stdout.strip())
    logs = docker("logs", PREFIX + "-readonly").stderr
    assert code != 0 and "quota_storage_unavailable" in logs
    REPORT["checks"].append(
        {"name": "readonly-volume-startup", "exit_code": 0, "backend_exit_code": code}
    )
    print("readonly-volume-startup: PASS", flush=True)
    # Missing the volume must fail even though the image has /app/data directories.
    container(
        "missing-volume",
        "docker-backend:latest",
        image_cmd,
        mounts=SOURCE + [volume("reference", "/reference", True)],
        env=backend_env,
        network=False,
        detach=True,
    )
    code = int(docker("wait", PREFIX + "-missing-volume").stdout.strip())
    logs = docker("logs", PREFIX + "-missing-volume").stderr
    assert code != 0 and "quota_storage_unavailable" in logs
    REPORT["checks"].append(
        {"name": "missing-volume-startup", "exit_code": 0, "backend_exit_code": code}
    )
    print("missing-volume-startup: PASS", flush=True)
    for service in ("backend", "frontend", "nginx"):
        result = docker("logs", PREFIX + "-" + service)
        assert not re.search(
            r"anon_v1_[A-Za-z0-9_-]{43}", result.stdout + result.stderr
        ), "Credential in service logs"
    REPORT["service_logs_contain_no_anonymous_credentials"] = True
    REPORT["passed"] = True


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        REPORT["passed"] = False
        REPORT["error"] = re.sub(r"anon_v1_[A-Za-z0-9_-]{43}", "<redacted>", str(error))
        print(REPORT["error"], file=sys.stderr)
    finally:
        for service in ("backend", "frontend", "nginx"):
            result = docker("logs", PREFIX + "-" + service, check=False)
            safe = re.sub(
                r"anon_v1_[A-Za-z0-9_-]{43}",
                "<redacted>",
                result.stdout + result.stderr,
            )
            (OUTPUT / f"{service}.log").write_text(safe, encoding="utf-8")
        cleanup = []
        for resource in reversed(RESOURCES["containers"]):
            cleanup.append(docker("rm", "-f", resource, check=False).returncode == 0)
        for resource in RESOURCES["networks"]:
            cleanup.append(
                docker("network", "rm", resource, check=False).returncode == 0
            )
        for resource in RESOURCES["volumes"]:
            cleanup.append(
                docker("volume", "rm", resource, check=False).returncode == 0
            )
        REPORT["cleanup_complete"] = all(cleanup)
        REPORT["finished_at"] = datetime.now(timezone.utc).isoformat()
        (OUTPUT / "report.json").write_text(
            json.dumps(REPORT, indent=2), encoding="utf-8"
        )
        print(f"Report: {OUTPUT / 'report.json'}", flush=True)
    sys.exit(0 if REPORT.get("passed") and REPORT["cleanup_complete"] else 1)
