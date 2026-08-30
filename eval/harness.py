"""Shared evaluation harness helpers.

This module contains environment, corpus, Git, and collection helpers used by
the retrieval evaluation entry point. Scoring rules deliberately live in
``eval.scoring`` so they can be tested without Chroma or network access.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.document_processor import DocumentProcessor  # noqa: E402

EVAL_COLLECTION = "rag_eval_documents"
ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "data" / "eval_docs"


def load_eval_set(path: Path) -> list[dict[str, Any]]:
    """Load an evaluation set JSON file."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_info(corpus_dir: Path = CORPUS_DIR) -> dict[str, Any]:
    """Describe supported evaluation files and compute a corpus fingerprint."""
    processor = DocumentProcessor()
    files = sorted(
        path
        for path in corpus_dir.iterdir()
        if path.is_file() and processor.is_supported_file(path.name)
    )
    entries = []
    combined = hashlib.sha256()
    for path in files:
        digest = file_sha256(path)
        size = path.stat().st_size
        entries.append({"name": path.name, "sha256": digest, "bytes": size})
        combined.update(path.name.encode("utf-8"))
        combined.update(b"\0")
        combined.update(digest.encode("ascii"))
        combined.update(b"\0")
        combined.update(str(size).encode("ascii"))
        combined.update(b"\n")
    return {
        "dir": "data/eval_docs",
        "files": entries,
        "corpus_hash": combined.hexdigest(),
    }


def capture_env(coll: Any) -> dict[str, Any]:
    """Capture model, chunking, and evaluation collection settings."""
    cfg = settings.get_model_config()
    raw = coll._collection.get(include=["embeddings"], limit=1)
    embeddings = raw.get("embeddings")
    embedding_dim = (
        len(embeddings[0]) if embeddings is not None and len(embeddings) else None
    )
    return {
        "embedding_provider": cfg.get("embedding_provider"),
        "embedding_model": cfg.get("embedding_model"),
        "embedding_dim": embedding_dim,
        "embedding_api_base_url": cfg.get("embedding_api_base_url"),
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "eval_collection": EVAL_COLLECTION,
        "collection_count": coll._collection.count(),
    }


def git_info() -> dict[str, Any]:
    """Capture the current commit and whether the worktree is dirty."""

    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return {
        "commit": run("rev-parse", "--short", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


def validate_collection(coll: Any, corpus: dict[str, Any]) -> None:
    """Validate that an evaluation collection matches the corpus files."""
    count = coll._collection.count()
    if count == 0:
        raise RuntimeError(f"Evaluation collection {EVAL_COLLECTION!r} is empty")
    raw = coll._collection.get(include=["metadatas"], limit=count)
    metadatas = raw.get("metadatas") or []
    if len(metadatas) != count:
        raise RuntimeError(
            f"Collection metadata count {len(metadatas)} does not match count {count}"
        )
    required = {"filename", "document_id", "chunk_id"}
    missing = [index for index, metadata in enumerate(metadatas) if not metadata]
    missing += [
        index
        for index, metadata in enumerate(metadatas)
        if metadata and not required.issubset(metadata)
    ]
    if missing:
        raise RuntimeError(
            f"Collection contains {len(missing)} rows with incomplete metadata; "
            "rebuild it with eval/ingest_docs.py"
        )
    expected_files = {entry["name"] for entry in corpus["files"]}
    actual_files = {metadata["filename"] for metadata in metadatas}
    if actual_files != expected_files:
        raise RuntimeError(
            "Collection/corpus file mismatch: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)}"
        )
