"""Exercise real HTTP deadline, lease, quota, and trusted-proxy boundaries."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

EVIDENCE = Path(os.environ["STEP4_EVIDENCE"])
CLIENT_IP = os.environ["STEP4_CLIENT_IP"]
FORGED_IP = "198.51.100.77"
RESULTS = {}


def events():
    path = EVIDENCE / "proxy-events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text("utf-8").splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith("\n")]


def await_event(predicate, timeout=12):
    expires = time.monotonic() + timeout
    while time.monotonic() < expires:
        for event in events():
            if predicate(event):
                return event
        time.sleep(0.1)
    raise AssertionError("Expected synthetic event was not observed")


def request(method, path, probe, *, token=None, body=None, direct=False):
    headers = {"X-Acceptance-Probe": probe, "X-Forwarded-For": FORGED_IP}
    if token is not None:
        headers["X-Anonymous-Token"] = token
    base = "http://backend:8000" if direct else "http://gateway:8080"
    started = time.monotonic()
    with httpx.Client(trust_env=False, timeout=85) as client:
        response = client.request(method, base + path, headers=headers, json=body)
    elapsed = time.monotonic() - started
    observation = await_event(lambda e: e.get("probe") == probe)
    assert observation["status"] == response.status_code
    assert (
        observation["response_sha256"] == hashlib.sha256(response.content).hexdigest()
    )
    assert observation["client_ip"] == CLIENT_IP
    assert observation["forwarded_for"] == (FORGED_IP if direct else CLIENT_IP)
    data = response.json()
    request_id = response.headers.get("x-request-id")
    if path != "/health":
        assert request_id
        assert request_id == observation["request_id"]
        assert request_id == data.get("detail", data)["request_id"]
    RESULTS[probe] = {
        "status": response.status_code,
        "elapsed": round(elapsed, 3),
        "request_id": request_id,
        "client_ip": observation["client_ip"],
        "forwarded_for": observation["forwarded_for"],
        "body_preserved": True,
        "budget_counts": observation["budget_counts"],
    }
    if "detail" in data:
        RESULTS[probe]["code"] = data["detail"]["code"]
        if "retry_after_seconds" in data["detail"]:
            assert response.headers["retry-after"] == str(
                data["detail"]["retry_after_seconds"]
            )
    if path == "/api/qa/quota" and response.status_code == 200:
        RESULTS[probe]["used_count"] = data["used_count"]
    print(probe, response.status_code, f"{elapsed:.3f}s", flush=True)
    return response, data


def ask(token, question):
    return request(
        "POST", "/api/qa/ask", question, token=token, body={"question": question}
    )


def quota(token, probe, expected):
    response, data = request("GET", "/api/qa/quota", probe, token=token)
    assert response.status_code == 200
    assert data["used_count"] == expected
    assert RESULTS[probe]["budget_counts"]["ask_default"] == expected


def run():
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                ready = client.get("http://gateway:8080/health")
            if ready.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        raise AssertionError("Temporary backend did not become ready")

    request("GET", "/health", "direct-spoof", direct=True)
    assert request("GET", "/api/qa/quota", "proxy-spoof")[0].status_code == 401
    response, data = request(
        "POST", "/api/session/anonymous", "session", body={"transport": "header"}
    )
    assert response.status_code == 201
    token = data["token"]  # Kept only in memory; never included in evidence.
    quota(token, "quota-initial", 0)
    assert ask(token, "initial")[0].status_code == 200
    quota(token, "quota-normal", 1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(ask, token, "timeout")
        await_event(
            lambda e: e["event"] == "worker_start" and e["question"] == "timeout"
        )
        response, data = ask(token, "busy-during")
        assert response.status_code == 503 and data["detail"]["code"] == "service_busy"
        quota(token, "quota-during", 2)
        response, data = pending.result(timeout=80)
        assert response.status_code == 504
        assert data["detail"]["code"] == "upstream_timeout"
        assert 58 <= RESULTS["timeout"]["elapsed"] < 68

    assert not any(
        e["event"] == "worker_finish" and e["question"] == "timeout" for e in events()
    )
    response, data = ask(token, "busy-after")
    assert response.status_code == 503 and data["detail"]["code"] == "service_busy"
    quota(token, "quota-after-504", 2)
    finished = await_event(
        lambda e: e["event"] == "worker_finish" and e["question"] == "timeout",
        timeout=20,
    )
    assert 69 <= finished["elapsed"] < 80
    time.sleep(0.2)
    assert ask(token, "recovery")[0].status_code == 200
    quota(token, "quota-recovered", 3)
    worker_questions = [e["question"] for e in events() if e["event"] == "worker_start"]
    assert worker_questions == ["initial", "timeout", "recovery"]
    counts = RESULTS["quota-recovered"]["budget_counts"]
    assert all(value == 0 for key, value in counts.items() if key != "ask_default")
    RESULTS["worker_timeout_seconds"] = round(finished["elapsed"], 3)
    RESULTS["passed"] = True


if __name__ == "__main__":
    try:
        run()
    finally:
        (EVIDENCE / "proxy-summary.json").write_text(
            json.dumps(RESULTS, indent=2, sort_keys=True), encoding="utf-8"
        )
