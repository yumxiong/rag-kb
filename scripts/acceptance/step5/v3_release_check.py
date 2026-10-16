"""Actual ASGI/provider regression, then separately gated public KB rebuild."""

import asyncio
import hashlib
import json
import math
import tarfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.acceptance.step5.paid_model_comparison import ROOT, STATE


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_review(path):
    """Rebuild requires review of the exact completed regression response file."""
    if not path or not path.is_file():
        raise ValueError("A completed response review is required")
    review = json.loads(path.read_text(encoding="utf-8"))
    summary = path.parent / "summary.json"
    result = json.loads(summary.read_text(encoding="utf-8"))
    if (
        review.get("summary_sha256") != digest(summary)
        or review.get("approved") is not True
        or result.get("workflow") != "v3-regression"
        or result.get("status") != "completed"
        or {row["id"] for row in review.get("questions", [])}
        != {f"demo-0{i}" for i in range(1, 6)}
        or not all(row.get("passed") is True for row in review["questions"])
    ):
        raise ValueError("Response review does not approve this regression")
    if result["questions_sha256"] != digest(ROOT / "docs/demo-v0.1.0/questions.json"):
        raise ValueError("Question set changed since regression")
    if result["corpus_manifest_sha256"] != digest(
        ROOT / "docs/demo-v0.1.0/manifest.json"
    ):
        raise ValueError("Corpus changed since regression")
    if {r["id"] for r in result.get("responses", [])} != {
        f"demo-0{i}" for i in range(1, 6)
    }:
        raise ValueError("Incomplete regression")


def prepare_chunks(chunks, output):
    """Stable IDs, real source filenames and portable deployment metadata."""
    uploads = output / "data/uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    if any(uploads.iterdir()):
        raise ValueError("Refusing to overwrite existing upload files")
    now = datetime.now(timezone.utc).isoformat()
    for doc in chunks:
        name = Path(doc.metadata["file"]).name
        source = ROOT / "docs/demo-v0.1.0" / doc.metadata["file"]
        destination = uploads / name
        if not destination.exists():
            destination.write_bytes(source.read_bytes())
        doc.metadata.update(
            filename=name,
            document_id=str(uuid.uuid5(uuid.NAMESPACE_URL, doc.metadata["file"])),
            content_hash=digest(source),
            processed_at=now,
            source=f"/app/data/uploads/{name}",
            file_path=f"/app/data/uploads/{name}",
        )


def run_v3(args, report, chunks, questions):
    import httpx
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.core.global_budget import offline_provider_access
    from app.core.money_ledger import MoneyLedger
    from app.core.provider_budget import (
        AsyncBudgetedTransport,
        BudgetedTransport,
        quote_request,
    )

    rebuild = args.workflow == "v3-rebuild"
    if rebuild:
        check_review(args.review)
    keys = [
        p.read_text(encoding="utf-8-sig").strip()
        for p in (args.chat_key, args.embedding_key)
    ]
    if any(not k or not k.isascii() or any(c.isspace() for c in k) for k in keys):
        raise ValueError("Invalid credential file format")
    settings.api_key, settings.embedding_api_key = keys
    settings.llm_provider, settings.embedding_provider = "deepseek", "qwen"
    settings.chat_model, settings.embedding_model = (
        "deepseek-flash",
        "text-embedding-v3",
    )
    settings.api_base_url = "https://api.deepseek.com"
    settings.embedding_api_base_url = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    settings.embedding_dimensions = 1024
    settings.llm_max_tokens = 800
    settings.llm_temperature = 0.1
    settings.enable_qa_cache = False
    settings.anonymous_storage_development = True
    settings.enable_quota_limit = True
    settings.quota_storage_path = str(STATE / "ledger")
    settings.anonymous_store_reference = str(
        STATE / "reference/anonymous-store-reference.json"
    )
    settings.allowed_origins = "https://acceptance.invalid"
    settings.chroma_db_path = str(args.output / "data/chroma_v3_1024_v1")
    settings.upload_dir = str(args.output / "data/uploads")
    prepare_chunks(chunks, args.output)

    from app.api import qa
    from app.core.vector_store import VectorStore
    from app.main import app

    clients, calls = [], []
    attempted = 0
    lock = threading.Lock()
    report.update(calls=calls, responses=[])

    class LimitedTransport(BudgetedTransport):
        def handle_request(self, request):
            nonlocal attempted
            request.read()
            amount = quote_request(request, self.kind)
            with lock:
                if attempted + amount > report["run_cap_micros"] or len(calls) >= 80:
                    raise ValueError("Acceptance budget reached")
                attempted += amount
                row = {"kind": self.kind, "reserved_micros": amount}
                calls.append(row)
            response = super().handle_request(request)
            row["status"] = response.status_code
            return response

    def clients_for(kind):
        sync = httpx.Client(
            transport=LimitedTransport(kind), trust_env=False, follow_redirects=False
        )
        asynchronous = httpx.AsyncClient(
            transport=AsyncBudgetedTransport(kind),
            trust_env=False,
            follow_redirects=False,
        )
        clients.extend([sync, asynchronous])
        return {"http_client": sync, "http_async_client": asynchronous}

    VectorStore._instance = None
    qa.vector_store = qa.qa_engine = None
    vector = VectorStore()
    try:
        with patch("app.core.vector_store.provider_http_clients", clients_for), patch(
            "app.core.qa_engine.provider_http_clients", clients_for
        ), TestClient(app, base_url="https://acceptance.invalid") as client:
            ledger = app.state.anonymous_store
            money = MoneyLedger(ledger)
            report["before"] = money.snapshot()
            try:
                if report["before"]["remaining"] < report["planned_max_micros"]:
                    raise ValueError("Insufficient shared daily budget")
                with offline_provider_access(
                    reason="authorized v3 corpus build", ledger=ledger
                ):
                    vector._ensure_initialized()
                    vector.vectorstore.add_documents(
                        chunks, ids=[d.metadata["chunk_id"] for d in chunks]
                    )
                if vector._checked_collection("rag_documents").count() != len(chunks):
                    raise ValueError("Incomplete index")
                if not rebuild:
                    origin = {"Origin": "https://acceptance.invalid"}
                    session = client.post(
                        "/api/session/anonymous",
                        json={"transport": "cookie"},
                        headers=origin,
                    )
                    if session.status_code != 201:
                        raise ValueError("Anonymous session failed")
                    for question in questions:
                        response = client.post(
                            "/api/qa/ask",
                            json={"question": question["question"], "max_sources": 3},
                            headers=origin,
                        )
                        if response.status_code != 200:
                            report["failed_question"] = question["id"]
                            report["api_status"] = response.status_code
                            raise ValueError("Question route failed")
                        body = response.json()
                        if body["from_cache"]:
                            raise ValueError("Cached answer cannot pass regression")
                        report["responses"].append({"id": question["id"], **body})
                report["status"] = "completed"
            finally:
                report["after"] = money.snapshot()
                report["attempted_reservation_micros"] = attempted
    finally:
        if vector.chroma_client is not None:
            vector.chroma_client._system.stop()
        for client in clients:
            if isinstance(client, httpx.AsyncClient):
                asyncio.run(client.aclose())
            else:
                client.close()

    if rebuild:
        # Reopen without embedding credentials; verify exact persisted payload.
        import chromadb
        from chromadb.api.shared_system_client import SharedSystemClient
        from chromadb.config import Settings as ChromaSettings

        # Evict only this stopped acceptance client's system, not other clients.
        SharedSystemClient._identifier_to_system.pop(
            vector.chroma_client._identifier, None
        )
        reopened = chromadb.PersistentClient(
            path=settings.chroma_db_path,
            settings=ChromaSettings(
                anonymized_telemetry=False, allow_reset=True, is_persistent=True
            ),
        )
        try:
            collection = reopened.get_collection("rag_documents")
            saved = collection.get(include=["documents", "metadatas", "embeddings"])
            if collection.metadata != vector._index_identity():
                raise ValueError("Persisted identity mismatch")
            expected = {d.metadata["chunk_id"]: d for d in chunks}
            if set(saved["ids"]) != set(expected):
                raise ValueError("Persisted IDs mismatch")
            for identifier, text, metadata, embedding in zip(
                saved["ids"],
                saved["documents"],
                saved["metadatas"],
                saved["embeddings"],
            ):
                if (
                    text != expected[identifier].page_content
                    or metadata != expected[identifier].metadata
                ):
                    raise ValueError("Persisted corpus mismatch")
                if len(embedding) != 1024 or not all(
                    math.isfinite(v) for v in embedding
                ):
                    raise ValueError("Persisted dimension mismatch")
            report["persisted_chunks"] = len(saved["ids"])
        finally:
            reopened._system.stop()
        selected = [
            p
            for name in ("uploads", "chroma_v3_1024_v1")
            for p in (args.output / "data" / name).rglob("*")
            if p.is_file()
        ]
        manifest = {
            str(p.relative_to(args.output)).replace("\\", "/"): digest(p)
            for p in sorted(selected)
        }
        (args.output / "kb-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        archive = args.output / "knowledge-base-v3.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for p in selected + [args.output / "kb-manifest.json"]:
                tar.add(
                    p, arcname=p.relative_to(args.output).as_posix(), recursive=False
                )
        report["archive_sha256"] = digest(archive)
        report["archive_bytes"] = archive.stat().st_size
