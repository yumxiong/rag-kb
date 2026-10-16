"""Exercise candidate provisioning with fresh synthetic data and no network."""

import datetime
import hashlib
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    run = ROOT / (
        "rag-step5-local-bootstrap-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    run.mkdir()
    (run / "data").mkdir()
    (run / "config").mkdir()
    env = {**os.environ, "COMPOSE_DISABLE_ENV_FILE": "1"}
    image = subprocess.check_output(
        [
            "docker",
            "image",
            "inspect",
            "rag-step5-backend:62d4cff",
            "--format",
            "{{.Id}}",
        ],
        text=True,
    ).strip()
    env.update(
        DEPLOY_ROOT=run.as_posix(),
        BACKEND_IMAGE=image,
        ANONYMOUS_MOUNT_SOURCE="not-a-real-source",
    )
    release = run / "release.env"
    release.write_text("# Synthetic test only\n")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(release),
        "-p",
        "rag-step5-bootstrap-check",
        "-f",
        str(ROOT / "docker/step5-candidate/compose.bootstrap.yml"),
    ]

    def execute(*args):
        return subprocess.run(
            command + list(args), env=env, capture_output=True, text=True
        )

    try:
        assert execute("config", "--quiet").returncode == 0
        probe = execute(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "bootstrap",
            "-B",
            "-c",
            "from pathlib import Path; "
            "print(next(x.split(' - ')[1].split()[1] "
            "for x in Path('/proc/self/mountinfo').read_text().splitlines() "
            "if x.split(' - ')[0].split()[4]=='/app/data'))",
        )
        assert probe.returncode == 0, probe.stderr
        source = re.sub(
            r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), probe.stdout.strip()
        )
        assert source and "\n" not in source
        failure = execute("run", "--rm", "--no-deps", "bootstrap")
        assert failure.returncode != 0 and "missing or mismatched" in failure.stderr
        assert not list((run / "data").iterdir())
        env["ANONYMOUS_MOUNT_SOURCE"] = source
        result = execute("run", "--rm", "--no-deps", "bootstrap")
        assert result.returncode == 0, result.stderr
        files = [
            run / "data/quotas/quota-state-v1.json",
            run / "data/quotas/initialized-v1.json",
            run / "config/anonymous-store-reference.json",
        ]
        before = [hashlib.sha256(p.read_bytes()).digest() for p in files]
        result = execute("run", "--rm", "--no-deps", "bootstrap")
        assert result.returncode != 0 and "Refusing to overwrite" in result.stderr
        assert before == [hashlib.sha256(p.read_bytes()).digest() for p in files]
        env["DEPLOY_ROOT"] = (run / "missing-root").as_posix()
        result = execute("run", "--rm", "--no-deps", "bootstrap")
        if result.returncode == 0 or (run / "missing-root").exists():
            print(
                "LIMIT: Docker Desktop created missing bind directories; "
                "host directory preflight is mandatory"
            )
        else:
            print("PASS: missing bind fails without directory creation")
        print(
            "PASS: production-mode synthetic bootstrap, mount mismatch, "
            "repeat refuses overwrite"
        )
    finally:
        env["DEPLOY_ROOT"] = run.as_posix()
        result = execute("down", "--remove-orphans")
        assert result.returncode == 0, result.stderr
    print("Synthetic evidence:", run)


if __name__ == "__main__":
    main()
