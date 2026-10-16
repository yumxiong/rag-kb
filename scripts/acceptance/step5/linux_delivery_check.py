"""Offline Linux delivery/restore probe; only disposable named volumes are allowed."""

import hashlib
import json
import math
import sys
import tarfile
from pathlib import Path, PurePosixPath

import chromadb
from chromadb.config import Settings

from app.core.anonymous_session import AnonymousSessionStore, SessionError, bootstrap
from app.core.money_ledger import MoneyLedger

ARCHIVE_SHA = "c23c565b3bf5987c6d6d82b344c994912bf9cd72023680385a56b8eca21ff640"
DATA = Path("/app/data")
REFERENCE = Path("/reference")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(archive, target, allowed):
    """Reject links, traversal, duplicate members and unexpected paths."""
    with tarfile.open(archive) as bundle:
        names = set()
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute()
            assert ".." not in path.parts and member.name not in names
            assert allowed(member.name), member.name
            names.add(member.name)
        bundle.extractall(target, filter="data")


def hashes(root):
    return {
        str(p.relative_to(root)): digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def options():
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        if left.split()[4] == str(DATA):
            filesystem, source, *_ = right.split()
            assert filesystem not in ("9p", "virtiofs", "fuse.grpcfuse")
            return {"mount_path": str(DATA), "mount_source": source}
    raise AssertionError("Native data volume missing")


def check_kb():
    client = chromadb.PersistentClient(
        path=str(DATA / "chroma_v3_1024_v1"),
        settings=Settings(anonymized_telemetry=False, allow_reset=True),
    )
    try:
        collection = client.get_collection("rag_documents")
        saved = collection.get(include=["documents", "metadatas", "embeddings"])
        assert len(saved["ids"]) == 32
        assert len(list((DATA / "uploads").glob("*.md"))) == 9
        assert collection.metadata == {
            "rag_identity_schema": 1,
            "rag_embedding_provider": "qwen",
            "rag_embedding_model": "text-embedding-v3",
            "rag_embedding_endpoint": (
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            "rag_embedding_dimensions": 1024,
            "rag_index_version": 1,
        }
        for vector in saved["embeddings"]:
            assert len(vector) == 1024 and all(math.isfinite(v) for v in vector)
        # Self-vector lookup tests persisted ANN readability, not semantic quality.
        for identifier, vector in zip(saved["ids"], saved["embeddings"]):
            result = collection.query(query_embeddings=[vector.tolist()], n_results=4)
            assert identifier in result["ids"][0]
    finally:
        client._system.stop()


def run(phase):
    reference = REFERENCE / "reference.json"
    if phase == "install":
        assert not any(DATA.iterdir()) and not any(REFERENCE.iterdir())
        assert digest(Path("/input/knowledge-base-v3.tar.gz")) == ARCHIVE_SHA
        extract(
            "/input/knowledge-base-v3.tar.gz",
            "/app",
            lambda n: n.startswith(("data/uploads/", "data/chroma_v3_1024_v1/"))
            or n == "kb-manifest.json",
        )
        manifest = json.loads(Path("/app/kb-manifest.json").read_text())
        assert hashes(DATA) == {k.removeprefix("data/"): v for k, v in manifest.items()}
        bootstrap(DATA / "quotas", reference, **options())
        store = AnonymousSessionStore(str(DATA / "quotas"), str(reference), **options())
        try:
            token, identity = store.create("192.0.2.1")
            store.personal_count(identity, increment=True)
            ledger = MoneyLedger(store)
            ledger.complete(ledger.reserve(1_000_000, policy="synthetic"))
            ledger.reserve(2_000_000, policy="synthetic")
            (REFERENCE / "probe.json").write_text(json.dumps({"token": token}))
        finally:
            store.close()
    if phase in ("install", "check"):
        check_kb()
        store = AnonymousSessionStore(str(DATA / "quotas"), str(reference), **options())
        try:
            token = json.loads((REFERENCE / "probe.json").read_text())["token"]
            assert store.personal_count(store.resolve(token)) == 1
            ledger = MoneyLedger(store)
            snapshot = ledger.snapshot()
            assert snapshot["reserved_today"] == 3_000_000
            assert snapshot["remaining"] == 47_000_000
            assert snapshot["pending_attempts"] == 1
            try:
                ledger.reserve(47_000_001, policy="synthetic")
            except SessionError as exc:
                assert exc.code == "global_budget_exceeded"
            else:
                raise AssertionError("Budget overrun accepted")
        finally:
            store.close()
    elif phase == "backup":
        manifest = {"data": hashes(DATA), "reference": hashes(REFERENCE)}
        with tarfile.open("/backup/restore.tar", "w") as bundle:
            for root, prefix in ((DATA, "data"), (REFERENCE, "reference")):
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        bundle.add(path, arcname=f"{prefix}/{path.relative_to(root)}")
        Path("/backup/hashes.json").write_text(json.dumps(manifest))
    elif phase == "restore":
        assert not any(DATA.iterdir()) and not any(REFERENCE.iterdir())
        extract(
            "/backup/restore.tar",
            "/restore",
            lambda n: n.startswith(("data/", "reference/")),
        )
        manifest = json.loads(Path("/backup/hashes.json").read_text())
        assert hashes(DATA) == manifest["data"]
        assert hashes(REFERENCE) == manifest["reference"]
    else:
        raise ValueError(phase)
    print(json.dumps({"phase": phase, "passed": True}))


if __name__ == "__main__":
    run(sys.argv[1])
