"""Local synthetic-only response-loss probe; requires local_dual_frontend --serve.

Proxy 18081 forwards only to the synthetic fixture on 18080. Streamlit 18502
uses that proxy. POST /__probe/arm drops the next ask response after admission;
GET /__probe/status exposes counters only. Ctrl+C stops both owned listeners.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
BACKEND = "http://127.0.0.1:18080"


def main():
    # Require the fixture-only marker before forwarding any traffic.
    marker = requests.get(BACKEND + "/__fixture/status", timeout=5)
    marker.raise_for_status()
    assert "engine_calls" in marker.json()
    for port in (18081, 18502):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    state = {"armed": False, "asks": 0, "dropped": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log request bodies, credentials, or arbitrary headers.

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            if self.path in ("/__probe/status", "/__probe/arm"):
                with lock:
                    if self.command == "POST" and self.path == "/__probe/arm":
                        state["armed"] = True
                    data = json.dumps(state).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not self.path.startswith(("/api/", "/health")):
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() in {"content-type", "x-anonymous-token"}
            }
            is_ask = self.command == "POST" and self.path == "/api/qa/ask"
            with lock:
                drop = is_ask and state["armed"]
                if is_ask:
                    state["asks"] += 1
                if drop:
                    state["armed"] = False
            response = requests.request(
                self.command,
                BACKEND + self.path,
                data=body,
                headers=headers,
                timeout=20,
                allow_redirects=False,
            )
            if drop:
                with lock:
                    state["dropped"] += 1
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(response.status_code)
            for key in ("Content-Type", "Retry-After", "X-Request-ID", "Cache-Control"):
                if key in response.headers:
                    self.send_header(key, response.headers[key])
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

    proxy = ThreadingHTTPServer(("127.0.0.1", 18081), Handler)
    worker = threading.Thread(target=proxy.serve_forever, daemon=True)
    with tempfile.TemporaryDirectory(prefix="rag-network-probe-") as scratch:
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
        env.update(BACKEND_URL="http://127.0.0.1:18081", PYTHONPATH=str(ROOT))
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "frontend/streamlit_app.py"),
                "--server.address=127.0.0.1",
                "--server.port=18502",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
            ],
            cwd=scratch,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        worker.start()
        print(
            "PROBE READY: proxy 18081, Streamlit 18502; Ctrl+C stops owned services",
            flush=True,
        )
        try:
            while process.poll() is None:
                worker.join(timeout=1)
        except KeyboardInterrupt:
            pass
        finally:
            proxy.shutdown()
            proxy.server_close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
