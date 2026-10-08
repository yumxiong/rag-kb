"""Run repository pytest with synthetic configuration and no outbound network.

Run using a Python environment with both repository requirements files installed.
This runner does not replace application modules or relax the coverage gate.
"""

import os
import socket
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    """Keep configuration, generated data and coverage in a disposable cwd."""
    safe_env = {
        name: os.environ[name]
        for name in (
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
        )
        if name in os.environ
    }
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="rag-repository-checks-") as directory:
        runtime = Path(directory).resolve()
        safe_env.update(
            USERPROFILE=str(runtime),
            HOME=str(runtime),
            APPDATA=str(runtime / "appdata"),
            LOCALAPPDATA=str(runtime / "localappdata"),
            TEMP_UPLOAD_DIR=str(runtime / "uploads"),
            COVERAGE_FILE=str(runtime / ".coverage"),
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            ANONYMIZED_TELEMETRY="False",
        )

        def audit(event, args):
            if event != "open" or not isinstance(args[0], (str, bytes)):
                return
            path = Path(os.fsdecode(args[0])).resolve()
            if path.is_relative_to(runtime):
                return
            protected = any(
                path.is_relative_to(ROOT / name) for name in ("data", "logs", "secrets")
            )
            if protected or path.name.startswith(".env") or "secrets" in path.parts:
                raise PermissionError("Isolated checks prohibit sensitive file access")

        original_connect = socket.socket.connect

        def deny_network(sock, address):
            caller = sys._getframe(1)
            # Windows implements asyncio's internal socketpair using TCP.
            if (
                caller.f_code.co_filename == socket.__file__
                and caller.f_code.co_name == "socketpair"
                and address[0] in ("127.0.0.1", "::1")
            ):
                return original_connect(sock, address)
            raise OSError("Outbound connections disabled by repository checks")

        try:
            os.chdir(runtime)
            sys.path.insert(0, str(ROOT))
            with patch.dict(os.environ, safe_env, clear=True), ExitStack() as stack:
                from pydantic_settings.sources import DotEnvSettingsSource

                stack.enter_context(
                    patch.object(
                        DotEnvSettingsSource, "_read_env_files", return_value={}
                    )
                )
                stack.enter_context(patch("keyring.get_password", return_value=None))
                stack.enter_context(
                    patch.object(socket.socket, "connect", deny_network)
                )
                stack.enter_context(
                    patch.object(socket.socket, "connect_ex", deny_network)
                )
                sys.addaudithook(audit)
                import pytest

                return int(
                    pytest.main(
                        [
                            "-c",
                            str(ROOT / "pytest.ini"),
                            str(ROOT / "tests"),
                            "-p",
                            "pytest_asyncio.plugin",
                            "-p",
                            "pytest_cov.plugin",
                            "-o",
                            f"cache_dir={runtime / 'pytest-cache'}",
                            "--basetemp",
                            str(runtime / "pytest-tmp"),
                        ]
                    )
                )
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    raise SystemExit(main())
