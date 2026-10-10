"""Local-only synthetic acceptance. No dotenv, provider, or production ledger.

Run from the integration root: python scripts/acceptance/step5/local_dual_frontend.py
Starts loopback services, runs HTTP/AppTest checks, then stops owned services.
Use --serve for browser acceptance; Ctrl+C stops only owned services.
Serve-mode error injection tests UI presentation, not real admission accounting.
"""

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
BACKEND = "http://127.0.0.1:18080"
NEXT = "http://127.0.0.1:13010"
STREAMLIT = "http://127.0.0.1:18501"
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep synthetic services running until Ctrl+C",
    )
    args = parser.parse_args()
    import requests
    import uvicorn
    from pydantic_settings import BaseSettings
    from pydantic_settings.sources import DotEnvSettingsSource

    sys.stdout.reconfigure(encoding="utf-8")

    # Fail before starting anything if a port is already owned by another run.
    for port in (18080, 13010, 18501):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    if any((ROOT / "v0.app-rag").glob(".env*")):
        raise RuntimeError("Next dotenv file present; isolated launch required")

    with tempfile.TemporaryDirectory(
        prefix="rag-step5-local-", dir=ROOT, ignore_cleanup_errors=True
    ) as temporary:
        scratch = Path(temporary)
        config = {
            name: str(scratch / name)
            for name in (
                "upload_dir",
                "chroma_db_path",
                "temp_upload_dir",
                "job_status_dir",
            )
        }
        config.update(
            quota_storage_path=str(scratch / "ledger"),
            anonymous_store_reference=str(scratch / "reference.json"),
            anonymous_storage_development=True,
            anonymous_cookie_secure=False,
            allowed_origins=NEXT,
            default_daily_quota=50 if args.serve else 5,
            max_session_requests_per_minute=200,
            max_ask_requests_per_minute=100,
            max_quota_requests_per_minute=200,
        )
        # Disable dotenv reads at construction, and all ambient settings sources.
        with patch.object(
            DotEnvSettingsSource, "_read_env_files", return_value={}
        ), patch.object(
            BaseSettings,
            "settings_customise_sources",
            classmethod(lambda cls, *args, **kwargs: (lambda: config,)),
        ):
            from app.core.config import Settings, settings

        Settings.get_api_key = lambda self: "synthetic-not-a-provider-credential"

        class VectorFixture:
            def get_collection_info(self):
                return {"document_count": 1}

            def list_documents(self):
                return [
                    {
                        "document_id": "17fdbfdc-f737-4668-9993-3da6d4fa838d",
                        "filename": "synthetic-引用.md",
                        "chunk_count": 1,
                    }
                ]

        entered = threading.Event()
        release = threading.Event()
        scenario = {"mode": "normal", "ask_requests": 0, "engine_calls": 0}

        class EngineFixture:
            def __init__(self, *args, **kwargs):
                raise AssertionError("Unexpected provider engine construction")

            def ask(self, **kwargs):
                from app.models.schemas import QuestionResponse

                question = kwargs["question"]
                scenario["engine_calls"] += 1
                if scenario["mode"] == "slow":
                    time.sleep(4)
                if question == "hold":
                    entered.set()
                    assert release.wait(10)
                if question == "timeout":
                    raise TimeoutError("synthetic")
                if question == "failure":
                    raise RuntimeError("synthetic")
                return QuestionResponse(
                    answer="合成回答 <script>alert(1)</script>",
                    sources=[
                        {
                            "document_name": "synthetic-引用.md",
                            "content": "<img src=x onerror=alert(1)> 合成引用原文",
                            "similarity_score": 0.9,
                        }
                    ],
                    processing_time=0,
                    from_cache=question == "cached",
                )

        # No provider SDK/vector model is imported or constructed by these modules.
        for name, symbol, replacement in (
            ("app.core.vector_store", "VectorStore", VectorFixture),
            ("app.core.qa_engine", "QAEngine", EngineFixture),
        ):
            module = types.ModuleType(name)
            setattr(module, symbol, replacement)
            sys.modules[name] = module

        from app.core.anonymous_session import bootstrap

        bootstrap(
            Path(settings.quota_storage_path),
            Path(settings.anonymous_store_reference),
            development=True,
        )
        from app.api import documents, qa
        from app.main import app

        if args.serve:
            from fastapi import Request

            from app.api.anonymous_session import session_error_handler
            from app.core.anonymous_session import SessionError

            @app.post("/__fixture/control")
            async def control(request: Request):
                body = await request.json()
                mode = body.get("mode", "normal")
                assert mode in {
                    "normal",
                    "slow",
                    "quota_exceeded",
                    "rate_limited",
                    "global_budget_exceeded",
                    "service_busy",
                    "upstream_timeout",
                }
                scenario["mode"] = mode
                return dict(scenario)

            @app.get("/__fixture/status")
            async def fixture_status():
                return dict(scenario)

            @app.middleware("http")
            async def inject_ui_fault(request, call_next):
                if request.url.path == "/api/qa/ask":
                    scenario["ask_requests"] += 1
                    mode = scenario["mode"]
                    statuses = {
                        "quota_exceeded": 429,
                        "rate_limited": 429,
                        "global_budget_exceeded": 503,
                        "service_busy": 503,
                        "upstream_timeout": 504,
                    }
                    if mode in statuses:
                        return await session_error_handler(
                            request,
                            SessionError(
                                mode,
                                statuses[mode],
                                1 if mode in {"rate_limited", "service_busy"} else None,
                            ),
                        )
                return await call_next(request)

        qa.vector_store = documents.vector_store = VectorFixture()
        qa.qa_engine = object.__new__(EngineFixture)
        logging.disable(logging.CRITICAL)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=18080,
                log_level="critical",
                access_log=False,
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        children = []
        results = []

        def passed(name):
            results.append(name)
            print("PASS " + name, flush=True)

        def wait_ready(url, process=None):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process and process.poll() is not None:
                    print(
                        process.startup_log.read_text(
                            encoding="utf-8", errors="replace"
                        )[-3000:]
                    )
                    raise RuntimeError("Owned frontend exited during startup")
                try:
                    if requests.get(url, timeout=2).status_code == 200:
                        return
                except requests.RequestException:
                    pass
                time.sleep(0.25)
            if process:
                print(
                    process.startup_log.read_text(encoding="utf-8", errors="replace")[
                        -5000:
                    ]
                )
            raise RuntimeError("Loopback service readiness timeout")

        def launch(command, cwd, overrides):
            # Retain OS launch necessities only; no inherited supplier credentials.
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper()
                in {
                    "PATH",
                    "SYSTEMROOT",
                    "WINDIR",
                    "TEMP",
                    "TMP",
                    "COMSPEC",
                    "PATHEXT",
                    "APPDATA",
                    "LOCALAPPDATA",
                    "USERPROFILE",
                }
            }
            env.update(overrides)
            startup_log = scratch / f"startup-{len(children)}.txt"
            with startup_log.open("w", encoding="utf-8") as output:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=output,
                    stderr=output,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            process.startup_log = startup_log
            children.append(process)
            return process

        try:
            thread.start()
            wait_ready(BACKEND + "/health")
            st_process = launch(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(ROOT / "frontend/streamlit_app.py"),
                    "--server.address=127.0.0.1",
                    "--server.port=18501",
                    "--server.headless=true",
                    "--browser.gatherUsageStats=false",
                ],
                scratch,
                {"BACKEND_URL": BACKEND, "PYTHONPATH": str(ROOT)},
            )
            next_copy = scratch / "next-source"
            shutil.copytree(
                ROOT / "v0.app-rag",
                next_copy,
                ignore=shutil.ignore_patterns(
                    "node_modules", ".next", ".pnpm-store", ".git", ".env*"
                ),
            )
            # Junction is read-only by convention; Next writes only its isolated .next.
            junction = next_copy / "node_modules"
            junction_literal = "'" + str(junction).replace("'", "''") + "'"
            target_literal = (
                "'" + str(ROOT / "v0.app-rag/node_modules").replace("'", "''") + "'"
            )
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"New-Item -ItemType Junction -Path {junction_literal} "
                    f"-Target {target_literal} | Out-Null",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            next_process = launch(
                [
                    shutil.which("node"),
                    str(ROOT / "v0.app-rag/node_modules/next/dist/bin/next"),
                    "dev",
                    "--webpack",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    "13010",
                ],
                next_copy,
                {"RAG_BACKEND_ORIGIN": BACKEND, "NEXT_TELEMETRY_DISABLED": "1"},
            )
            wait_ready(STREAMLIT + "/_stcore/health", st_process)
            wait_ready(NEXT, next_process)
            assert requests.get(STREAMLIT, timeout=5).status_code == 200
            passed("three loopback services and both frontend homepages")
            if args.serve:
                print(
                    "SYNTHETIC READY: Next 13010, Streamlit 18501, backend 18080; "
                    "Ctrl+C stops owned services",
                    flush=True,
                )
                try:
                    while not server.should_exit:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
                return

            def client():
                session = requests.Session()
                session.headers["Origin"] = NEXT
                response = session.post(
                    NEXT + "/api/session/anonymous",
                    json={"transport": "cookie"},
                    timeout=10,
                )
                assert response.status_code == 201
                assert "HttpOnly" in response.headers["Set-Cookie"]
                assert "Path=/api" in response.headers["Set-Cookie"]
                assert "token" not in response.json()
                return session

            def quota(session):
                response = session.get(NEXT + "/api/qa/quota", timeout=10)
                assert response.status_code == 200
                return response.json()

            def ask(session, question="synthetic question"):
                return session.post(
                    NEXT + "/api/qa/ask", json={"question": question}, timeout=15
                )

            def error(response, status, code):
                assert response.status_code == status, (response.status_code, code)
                detail = response.json()["detail"]
                assert detail["code"] == code
                assert detail["request_id"] == response.headers["X-Request-ID"]
                assert response.headers["Cache-Control"] == "no-store"
                if code in ("quota_exceeded", "global_budget_exceeded"):
                    assert detail["reset_at"].endswith("Z")
                if code in ("rate_limited", "service_busy"):
                    assert int(response.headers["Retry-After"]) > 0

            a, b = client(), client()
            assert a.cookies.get("rag_anonymous") != b.cookies.get("rag_anonymous")
            assert quota(a)["used_count"] == quota(b)["used_count"] == 0
            response = ask(a)
            assert response.status_code == 200
            assert "<script>" in response.json()["answer"]
            assert "<img" in response.json()["sources"][0]["content"]
            assert quota(a)["used_count"] == 1 and quota(b)["used_count"] == 0
            token = a.cookies.get("rag_anonymous")
            assert a.get(NEXT, timeout=10).status_code == 200
            assert (
                a.post(
                    NEXT + "/api/session/anonymous",
                    json={"transport": "cookie"},
                    timeout=10,
                ).status_code
                == 200
            )
            assert (
                a.cookies.get("rag_anonymous") == token and quota(a)["used_count"] == 1
            )
            passed(
                "two HTTP cookie jars: identity/quota isolation and reload-style reuse"
            )
            assert (
                a.get(NEXT + "/api/qa/suggestions", timeout=10).json()["document_count"]
                == 1
            )
            library = a.get(NEXT + "/api/documents/library", timeout=10).json()
            assert (
                library["total"] == 1
                and library["documents"][0]["filename"] == "synthetic-引用.md"
            )
            assert (
                a.get(
                    NEXT + "/api/documents/17fdbfdc-f737-4668-9993-3da6d4fa838d",
                    timeout=10,
                ).status_code
                == 401
            )
            passed(
                "Next same-origin proxy: suggestions, public library metadata, "
                "ask/source payload; document detail remains admin-only"
            )
            for question, status, code in (
                ("timeout", 504, "upstream_timeout"),
                ("failure", 502, "upstream_error"),
            ):
                error(ask(a, question), status, code)
            assert quota(a)["used_count"] == 3
            assert ask(a, "cached").json()["from_cache"] is True
            assert ask(a).status_code == 200
            error(ask(a), 429, "quota_exceeded")
            assert quota(a)["used_count"] == 5 and quota(b)["used_count"] == 0
            passed(
                "timeout/failure/cache each count once; quota_exceeded does not refund"
            )
            error(ask(b, "😀" * 2001), 400, "invalid_request")
            assert quota(b)["used_count"] == 0
            assert ask(b, "😀" * 2000).status_code == 200
            passed("backend 2000 Unicode code-point boundary")
            settings.max_ask_requests_per_minute = 1
            error(ask(b), 429, "rate_limited")
            settings.max_ask_requests_per_minute = 100
            assert quota(b)["used_count"] == 1
            passed("real identity rate limit and Retry-After through Next")
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(ask, b, "hold")
                assert entered.wait(5)
                try:
                    error(ask(b), 503, "service_busy")
                finally:
                    release.set()
                assert pending.result().status_code == 200
            assert quota(b)["used_count"] == 2
            passed("real concurrent identity gate: service_busy before admission")
            settings.global_daily_ask_limit = 1
            error(ask(b), 503, "global_budget_exceeded")
            assert quota(b)["global_budget"]["status"] == "exhausted"
            settings.global_daily_ask_limit = 500
            passed("real ledger global budget rejection through Next")
            settings.enable_quota_limit = False
            assert quota(b)["daily_limit"] is None and quota(b)["remaining"] is None
            settings.enable_quota_limit = True
            passed("nullable quota fields preserved through proxy")

            from frontend.utils.anonymous_session import identity_headers

            state_a, state_b = {}, {}
            h_a, h_b = identity_headers(state_a, BACKEND), identity_headers(
                state_b, BACKEND
            )
            assert h_a != h_b and identity_headers(state_a, BACKEND) == h_a
            assert (
                requests.post(
                    BACKEND + "/api/qa/ask",
                    headers=h_a,
                    json={"question": "header question"},
                    timeout=10,
                ).status_code
                == 200
            )
            assert (
                requests.get(BACKEND + "/api/qa/quota", headers=h_a, timeout=5).json()[
                    "used_count"
                ]
                == 1
            )
            assert (
                requests.get(BACKEND + "/api/qa/quota", headers=h_b, timeout=5).json()[
                    "used_count"
                ]
                == 0
            )
            passed(
                "actual Streamlit identity helper: independent server states "
                "and X-Anonymous-Token quotas"
            )

            from streamlit.testing.v1 import AppTest

            sys.path.insert(0, str(ROOT / "frontend"))
            with patch.dict(os.environ, {"BACKEND_URL": BACKEND}), patch(
                "utils.settings_loader._read_browser_settings", return_value={}
            ):
                at = AppTest.from_file(str(ROOT / "frontend/streamlit_app.py")).run(
                    timeout=20
                )
                assert not at.exception
                at.button(key="suggestion_0").click().run(timeout=20)
                assert not at.exception
                assert (
                    at.session_state.messages[-1]["sources"][0]["document_name"]
                    == "synthetic-引用.md"
                )
                identity = at.session_state.anonymous_token
                at.run(timeout=20)
                assert not at.exception and at.session_state.anonymous_token == identity
                passed(
                    "Streamlit full homepage AppTest against live fixture: "
                    "suggestion click, answer/source and rerun identity"
                )
            print(
                json.dumps(
                    {
                        "passed": len(results),
                        "browser_interaction": "NOT EXECUTED",
                        "real_supplier": "NOT EXECUTED",
                        "ports": [18080, 18501, 13010],
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            release.set()
            for process in reversed(children):
                if process.poll() is None:
                    # Only the PIDs created above and their children;
                    # no existing services.
                    import psutil

                    owned = psutil.Process(process.pid)
                    descendants = owned.children(recursive=True)
                    for child in reversed(descendants):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    psutil.wait_procs(descendants, timeout=5)
                    process.wait(timeout=10)
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
