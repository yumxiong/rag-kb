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
from typing import Any, Iterable, Mapping

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.document_processor import DocumentProcessor  # noqa: E402

EVAL_COLLECTION = "rag_eval_documents"
ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "data" / "eval_docs"
CHUNK_REF_VERSION = 1
MANIFEST_VERSION = 1
CHUNK_REF_PREFIX = f"cr{CHUNK_REF_VERSION}:"
SPLITTER_NAME = "RecursiveCharacterTextSplitter"
SPLITTER_SEPARATORS = ["\n\n", "\n", " ", ""]


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


def normalize_chunk_text(text: str) -> str:
    """Normalize line endings without changing other meaningful whitespace."""
    if not isinstance(text, str):
        raise TypeError("chunk text must be a string")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_sha256(text: str) -> str:
    """Hash the normalized text seen by the retrieval system."""
    normalized = normalize_chunk_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def make_chunk_ref(filename: str, chunk_index: int, text_digest: str) -> str:
    """Build a deterministic evaluation reference for one chunk."""
    if not isinstance(filename, str) or not filename:
        raise ValueError("chunk filename must be a non-empty string")
    if "\0" in filename:
        raise ValueError("chunk filename must not contain NUL")
    if isinstance(chunk_index, bool) or not isinstance(chunk_index, int):
        raise TypeError("chunk_index must be an integer")
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    if (
        not isinstance(text_digest, str)
        or len(text_digest) != 64
        or any(char not in "0123456789abcdef" for char in text_digest)
    ):
        raise ValueError("text_digest must be a lowercase SHA-256 hex digest")

    identity = f"{filename}\0{chunk_index}\0{text_digest}".encode("utf-8")
    return CHUNK_REF_PREFIX + hashlib.sha256(identity).hexdigest()


def splitter_info() -> dict[str, Any]:
    """Return the chunking configuration used by ``DocumentProcessor``."""
    return {
        "name": SPLITTER_NAME,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "separators": list(SPLITTER_SEPARATORS),
    }


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def chunk_manifest_hash(manifest: Mapping[str, Any]) -> str:
    """Hash manifest identity fields, excluding a previously stored hash."""
    payload = dict(manifest)
    payload.pop("chunk_manifest_hash", None)
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def build_chunk_manifest(
    chunks: Iterable[Any], splitter: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build a deterministic, text-free manifest from actual evaluation chunks."""
    entries = []
    seen_locations: set[tuple[str, int]] = set()
    seen_refs: set[str] = set()

    for chunk in chunks:
        text = getattr(chunk, "page_content", None)
        metadata = getattr(chunk, "metadata", None)
        if not isinstance(metadata, Mapping):
            raise ValueError("each chunk must have mapping metadata")

        filename = metadata.get("filename")
        chunk_index = metadata.get("chunk_index")
        if not isinstance(filename, str) or not filename:
            raise ValueError("each chunk must have a non-empty filename")
        if "\0" in filename:
            raise ValueError("chunk filename must not contain NUL")
        if isinstance(chunk_index, bool) or not isinstance(chunk_index, int):
            raise ValueError("each chunk must have an integer chunk_index")
        if chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")

        normalized_text = normalize_chunk_text(text)
        digest = text_sha256(normalized_text)
        chunk_ref = make_chunk_ref(filename, chunk_index, digest)
        location = (filename, chunk_index)
        if location in seen_locations:
            raise ValueError(
                "duplicate chunk location: "
                f"filename={filename!r}, index={chunk_index}"
            )
        if chunk_ref in seen_refs:
            raise ValueError(f"duplicate chunk_ref: {chunk_ref}")
        seen_locations.add(location)
        seen_refs.add(chunk_ref)
        entries.append(
            {
                "chunk_ref": chunk_ref,
                "filename": filename,
                "chunk_index": chunk_index,
                "text_sha256": digest,
                "chars": len(normalized_text),
            }
        )

    entries.sort(
        key=lambda entry: (
            entry["filename"],
            entry["chunk_index"],
            entry["chunk_ref"],
        )
    )
    splitter_source = splitter_info() if splitter is None else splitter
    splitter_payload = json.loads(
        _canonical_json_bytes(splitter_source).decode("utf-8")
    )
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "chunk_ref_version": CHUNK_REF_VERSION,
        "splitter": splitter_payload,
        "chunk_count": len(entries),
        "chunks": entries,
    }
    manifest["chunk_manifest_hash"] = chunk_manifest_hash(manifest)
    return manifest


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
