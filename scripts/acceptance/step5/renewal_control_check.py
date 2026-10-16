"""Offline control-flow tests for the host renewal script; Docker calls are fake."""

import json
import os
import subprocess
import tempfile
from pathlib import Path


def main():
    script = Path("/candidate/scripts/deployment/renew-step5-certificates.sh")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "state").mkdir()
        (root / "release.env").write_text("# no secrets\n")
        executable = root / "docker"
        executable.write_text(
            """#!/usr/local/bin/python
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
p=Path(os.environ['FAKE_LOG'])
with p.open('a') as f: f.write(json.dumps(args)+'\\n')
calls=[json.loads(x) for x in p.read_text().splitlines()]
mode=os.environ['FAKE_MODE']
is_test=args[-3:]==['nginx','nginx','-t']
tests=sum(c[-3:]==['nginx','nginx','-t'] for c in calls)
if mode=='renew-failure' and 'renew' in args: sys.exit(9)
if mode=='preflight-failure' and is_test: sys.exit(10)
if mode=='post-renew-failure' and is_test and tests==2: sys.exit(11)
if mode=='reload-failure' and args[-2:]==['-s','reload']: sys.exit(12)
"""
        )
        executable.chmod(0o700)
        for mode, exit_code, expected_renew, expected_reload in (
            ("success", 0, True, True),
            ("renew-failure", 9, True, False),
            ("preflight-failure", 10, False, False),
            ("post-renew-failure", 11, True, False),
            ("reload-failure", 12, True, True),
        ):
            log = root / (mode + ".jsonl")
            env = {
                **os.environ,
                "PATH": str(root) + ":" + os.environ["PATH"],
                "FAKE_MODE": mode,
                "FAKE_LOG": str(log),
            }
            result = subprocess.run(
                ["bash", str(script), str(root)], env=env, capture_output=True
            )
            assert result.returncode == exit_code, (mode, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            assert any("renew" in c for c in calls) == expected_renew
            assert any(c[-2:] == ["-s", "reload"] for c in calls) == expected_reload
            assert all("up" not in c for c in calls)
            if mode == "success":
                assert [c[-1] for c in calls] == [
                    "--quiet",
                    "--quiet",
                    "-t",
                    "--quiet",
                    "-t",
                    "reload",
                ]
        # A concurrent scheduler must stop before invoking Docker.
        import fcntl

        with (root / "state/certbot-renew.lock").open("w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            log = root / "locked.jsonl"
            env = {**env, "FAKE_LOG": str(log)}
            result = subprocess.run(
                ["bash", str(script), str(root)], env=env, capture_output=True
            )
            assert result.returncode != 0 and not log.exists()
    print(
        "PASS: renewal success order, preflight/renew/postcheck/reload failures, "
        "concurrency lock; no app startup"
    )


if __name__ == "__main__":
    main()
