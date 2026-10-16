"""Bounded, explicit paid acceptance on the tracked public AtlasDesk corpus.

No dotenv, keyring, private corpus, raw provider logs, or automatic retries.
The persistent acceptance ledger MUST be reused, including failed attempts.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "rag-step5-local-paid-state"
MODELS = ("qwen3.7-text-embedding", "text-embedding-v3")
RUN_CAP = 6_000_000


def public_inputs():
    """Only the committed public manifest allowlist is eligible for transmission."""
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    base = ROOT / "docs/demo-v0.1.0"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=200, separators=["\n\n", "\n", " ", ""]
    )
    chunks = []
    for entry in manifest["files"]:
        name = entry["file"]
        path = (base / name).resolve()
        if name not in manifest["ingestion_allowlist"] or base not in path.parents:
            raise ValueError("Invalid public allowlist")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Public corpus hash changed")
        docs = splitter.split_documents(
            [Document(page_content=raw.decode("utf-8"), metadata={"file": name})]
        )
        for doc in docs:
            doc.metadata.update(chunk_id=str(len(chunks)), document_id=name)
            chunks.append(doc)
    questions = json.loads((base / "questions.json").read_text(encoding="utf-8"))[
        "questions"
    ]
    items = len(chunks) + len(questions) + 1  # one availability probe per model
    upper = items * (64_000 + 4096) + 2_206_400
    if upper > RUN_CAP:
        raise ValueError("Plan exceeds single-run budget")
    return chunks, questions, upper


def evidence_score(question, documents):
    """Require the exact evidence quote and correct source, not just topic overlap."""
    if not question["answerable"]:
        return None  # Retrieval alone cannot prove correct abstention.
    return all(
        any(
            doc.metadata["file"] == evidence["file"]
            and evidence["quote"] in doc.page_content
            for doc in documents
        )
        for evidence in question["evidence"]
    )


def run(args, report, chunks, questions):
    import httpx
    from openai import OpenAI

    from app.core.anonymous_session import AnonymousSessionStore, bootstrap
    from app.core.config import settings
    from app.core.global_budget import offline_provider_access
    from app.core.money_ledger import MoneyLedger
    from app.core.provider_budget import (
        AsyncBudgetedTransport,
        BudgetedTransport,
        quote_request,
    )
    from app.core.qa_engine import EvidenceRetriever
    from app.core.vector_store import VectorStore

    storage = STATE / "ledger"
    reference = STATE / "reference/anonymous-store-reference.json"
    if args.initialize_ledger:
        bootstrap(storage, reference, development=True)
    ledger = AnonymousSessionStore(str(storage), str(reference), development=True)
    money = MoneyLedger(ledger)
    clients = []
    spent = 0
    calls = []
    report.update(before=money.snapshot(), calls=calls, models={})

    class LimitedTransport(BudgetedTransport):
        def handle_request(self, request):
            nonlocal spent
            request.read()
            amount = quote_request(request, self.kind)
            if spent + amount > RUN_CAP or len(calls) >= 100:
                raise ValueError("Acceptance run limit reached")
            spent += amount
            body = json.loads(request.content)
            row = {"model": body["model"], "reserved_micros": amount}
            calls.append(row)
            started = time.monotonic()
            try:
                response = super().handle_request(request)
                row["http_status"] = response.status_code
                payload = response.json()
                usage = payload.get("usage", {})
                row["usage_tokens"] = {
                    k: v for k, v in usage.items() if type(v) is int and v >= 0
                }
                return response
            finally:
                row["seconds"] = round(time.monotonic() - started, 3)

    def clients_for(kind):
        client = httpx.Client(
            transport=LimitedTransport(kind), trust_env=False, follow_redirects=False
        )
        clients.append(client)
        # This runner only uses sync SDK methods; async client is never dispatched.
        async_client = httpx.AsyncClient(
            transport=AsyncBudgetedTransport(kind),
            trust_env=False,
            follow_redirects=False,
        )
        clients.append(async_client)
        return {"http_client": client, "http_async_client": async_client}

    try:
        if money.snapshot()["remaining"] < report["planned_max_micros"]:
            raise ValueError("Insufficient shared daily headroom for the plan")
        # Explicit files only: no fallback to other files/environment/keyring.
        keys = [
            p.read_text(encoding="utf-8-sig").strip()
            for p in (args.chat_key, args.embedding_key)
        ]
        if any(not k or not k.isascii() or any(c.isspace() for c in k) for k in keys):
            raise ValueError("Invalid credential file format")
        settings.api_key, settings.embedding_api_key = keys
        settings.llm_provider = "deepseek"
        settings.api_base_url = "https://api.deepseek.com"
        settings.chat_model = "deepseek-flash"
        settings.embedding_provider = "qwen"
        settings.embedding_api_base_url = (
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        settings.embedding_dimensions = 1024
        settings.embedding_timeout_seconds = 15
        with offline_provider_access(
            reason="authorized public comparison", ledger=ledger
        ):
            for model in MODELS:
                report["phase"] = model
                settings.embedding_model = model
                settings.chroma_db_path = str(args.output / model)
                VectorStore._instance = None
                store = VectorStore()
                try:
                    with patch(
                        "app.core.vector_store.provider_http_clients", clients_for
                    ):
                        store._ensure_initialized()
                    probe = store.embeddings.embed_query("公开模型接口连通性验收")
                    if len(probe) != 1024 or not all(math.isfinite(v) for v in probe):
                        raise ValueError("Invalid provider vector")
                    store.vectorstore.add_documents(
                        chunks, ids=[doc.metadata["chunk_id"] for doc in chunks]
                    )
                    retriever = EvidenceRetriever(
                        nearest=store.vectorstore.as_retriever(search_kwargs={"k": 2}),
                        diverse=store.vectorstore.as_retriever(
                            search_type="mmr",
                            search_kwargs={"k": 6, "fetch_k": 24, "lambda_mult": 0.3},
                        ),
                        k=6,
                    )
                    results = []
                    for question in questions:
                        started = time.monotonic()
                        docs = retriever.invoke(question["question"])
                        results.append(
                            {
                                "id": question["id"],
                                "all_evidence_at_6": evidence_score(question, docs),
                                "seconds": round(time.monotonic() - started, 3),
                                "chunks": [doc.metadata["chunk_id"] for doc in docs],
                                "sources": [doc.metadata["file"] for doc in docs],
                            }
                        )
                    report["models"][model] = results
                finally:
                    if store.chroma_client is not None:
                        store.chroma_client._system.stop()
            report["phase"] = "deepseek-flash"
            http_clients = clients_for("chat")
            client = OpenAI(
                api_key=settings.get_api_key(),
                base_url="https://api.deepseek.com",
                http_client=http_clients["http_client"],
                max_retries=0,
                timeout=45,
            )
            result = client.chat.completions.create(
                model="deepseek-flash",
                max_tokens=800,
                temperature=0.1,
                messages=[{"role": "user", "content": "这是接口验收，请仅回复 OK。"}],
                extra_body={"thinking": {"type": "disabled"}},
            )
            report["chat_smoke_ok"] = result.choices[0].message.content.strip() == "OK"
            if not report["chat_smoke_ok"]:
                raise ValueError("Unexpected chat smoke response")
            report["status"] = "completed"
    finally:
        report["attempted_reservation_micros"] = spent
        report["after"] = money.snapshot()
        ledger.close()
        for client in clients:
            if isinstance(client, httpx.AsyncClient):
                asyncio.run(client.aclose())
            else:
                client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--check-environment", action="store_true")
    parser.add_argument("--initialize-ledger", action="store_true")
    parser.add_argument("--chat-key", type=Path)
    parser.add_argument("--embedding-key", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    chunks, questions, upper = public_inputs()
    report = {
        "status": "planned",
        "documents": 9,
        "chunks": len(chunks),
        "questions": len(questions),
        "planned_max_micros": upper,
        "run_cap_micros": RUN_CAP,
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "questions_sha256": hashlib.sha256(
            (ROOT / "docs/demo-v0.1.0/questions.json").read_bytes()
        ).hexdigest(),
    }
    if not args.execute and not args.check_environment:
        print(json.dumps(report))
        return 0
    if not args.output or (
        args.execute and (not args.chat_key or not args.embedding_key)
    ):
        parser.error("Execution requires output and both key file paths")
    args.output = args.output.resolve()
    if args.output.parent != ROOT or not args.output.name.startswith(
        "rag-step5-local-"
    ):
        parser.error("Output must be a new ignored acceptance directory")
    if args.execute:
        args.chat_key = args.chat_key.resolve()
        args.embedding_key = args.embedding_key.resolve()
    args.output.mkdir(exist_ok=False)
    # Never import application settings while real dotenv/environment is available.
    from pydantic_settings.sources import DotEnvSettingsSource

    environment = {
        k: v
        for k, v in os.environ.items()
        if k in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    environment.update(
        ANONYMIZED_TELEMETRY="False",
        HOME=str(args.output),
        USERPROFILE=str(args.output),
        APPDATA=str(args.output / "appdata"),
        LOCALAPPDATA=str(args.output / "localappdata"),
        TEMP_UPLOAD_DIR=str(args.output / "uploads"),
    )
    os.chdir(args.output)
    logging.disable(logging.CRITICAL)
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        stack.enter_context(
            patch.object(DotEnvSettingsSource, "_read_env_files", return_value={})
        )
        stack.enter_context(patch("keyring.get_password", return_value=None))
        try:
            if args.check_environment:
                from app.core.qa_engine import EvidenceRetriever  # noqa: F401
                from app.core.vector_store import VectorStore  # noqa: F401

                report["status"] = "completed"
                report["mode"] = "environment_only_no_provider_calls"
            else:
                run(args, report, chunks, questions)
        except Exception as error:
            report.update(status="stopped", error_type=type(error).__name__)
            trace = error.__traceback__
            frames = []
            while trace is not None:
                frames.append(
                    {
                        "file": Path(trace.tb_frame.f_code.co_filename).name,
                        "line": trace.tb_lineno,
                    }
                )
                trace = trace.tb_next
            report["error_frames"] = frames
            status = getattr(error, "status_code", None)
            if type(status) is int:
                report["http_status"] = status
            # Never print exception text, request headers, keys, or provider bodies.
        finally:
            (args.output / "summary.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
