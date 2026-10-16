"""Run offline Linux probes and remove only this run's disposable volumes."""

import json
import subprocess
import uuid
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[3]
    output = root / "rag-step5-local-delivery-20261016"
    scripts = Path(__file__).parent
    prefix = "rag-delivery-" + uuid.uuid4().hex[:12]
    volumes = [
        f"{prefix}-{name}"
        for name in ("data", "ref", "backup", "new", "newref", "fault", "faultref")
    ]
    results = []

    def docker(*args):
        result = subprocess.run(["docker", *args], capture_output=True, text=True)
        with (output / "linux-check.txt").open("a", encoding="utf-8") as log:
            log.write(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"Docker probe failed: {args[-1]}; see linux-check.txt")
        return result.stdout

    def mount(volume, target):
        return ["--mount", f"type=volume,src={volume},dst={target},volume-nocopy"]

    def run(phase, restored=False):
        data, ref = (volumes[3], volumes[4]) if restored else volumes[:2]
        args = [
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            "PYTHONPATH=/app",
            "-v",
            f"{scripts}:/probe:ro",
        ]
        args += (
            mount(data, "/app/data")
            + mount(ref, "/reference")
            + mount(volumes[2], "/backup")
        )
        if phase == "restore":
            args += mount(data, "/restore/data") + mount(ref, "/restore/reference")
        archive = root / "rag-step5-local-v3-release-20261016/knowledge-base-v3.tar.gz"
        args += [
            "-v",
            f"{archive}:/input/knowledge-base-v3.tar.gz:ro",
        ]
        docker(
            *args,
            "rag-step5-backend:1e759cd",
            "python",
            "/probe/linux_delivery_check.py",
            phase,
        )
        results.append({"phase": phase, "restored": restored, "passed": True})

    try:
        for volume in volumes:
            docker("volume", "create", volume)
        run("install")
        run("check")
        run("backup")
        run("restore", True)
        run("check", True)
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            "PYTHONPATH=/app:/probe",
            "-v",
            f"{scripts}:/probe:ro",
            *mount(volumes[5], "/storage-tests"),
            *mount(volumes[6], "/reference-tests"),
            "rag-step5-backend:1e759cd",
            "python",
            "/probe/storage_checks.py",
        )
        results.append({"storage_fault_suite": "passed"})
    finally:
        for volume in volumes:
            docker("volume", "rm", volume)
        (output / "linux-results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results))


if __name__ == "__main__":
    main()
