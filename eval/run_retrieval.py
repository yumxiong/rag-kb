"""Run retrieval once and persist replayable ranked contexts."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

sys.path.append(str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document  # noqa: E402

from app.core.vector_store import get_vector_store  # noqa: E402
from eval import harness  # noqa: E402

RUN_SCHEMA_VERSION = 1
K_VALUES = [1, 3, 5, 10]
EVAL_SET_PATH = harness.ROOT / "eval" / "eval_set_v3.json"


def _relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(harness.ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _manifest_entries(manifest: Mapping[str, Any]) -> dict[tuple[str, int], Any]:
    return {
        (entry["filename"], entry["chunk_index"]): entry for entry in manifest["chunks"]
    }


def _context_from_chunk(
    chunk: Any,
    rank: int,
    entries: Mapping[tuple[str, int], Mapping[str, Any]],
) -> dict[str, Any]:
    text = getattr(chunk, "page_content", None)
    metadata = getattr(chunk, "metadata", None)
    if not isinstance(text, str) or not text:
        raise RuntimeError(f"Retrieved context at rank {rank} has empty text")
    if not isinstance(metadata, Mapping):
        raise RuntimeError(f"Retrieved context at rank {rank} has no metadata")

    filename = metadata.get("filename")
    chunk_index = metadata.get("chunk_index")
    chunk_id = metadata.get("chunk_id")
    location = (filename, chunk_index)
    if not isinstance(chunk_id, str) or not chunk_id:
        raise RuntimeError(f"Retrieved context at rank {rank} has no chunk_id")
    if location not in entries:
        raise RuntimeError(
            f"Retrieved context at rank {rank} is absent from the chunk manifest"
        )

    entry = entries[location]
    digest = harness.text_sha256(text)
    if digest != entry["text_sha256"]:
        raise RuntimeError(
            f"Retrieved context at rank {rank} differs from the chunk manifest"
        )
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "chunk_ref": entry["chunk_ref"],
        "text_sha256": digest,
        "filename": filename,
        "chunk_index": chunk_index,
        "text": text,
    }


def collect_retrievals(
    eval_set: Sequence[Mapping[str, Any]],
    retriever: Callable[[str, int], list[Any]],
    k_max: int,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Retrieve each question once at k_max and attach stable identities."""
    if isinstance(k_max, bool) or not isinstance(k_max, int) or k_max < 1:
        raise ValueError("k_max must be a positive integer")
    entries = _manifest_entries(manifest)
    retrievals = []
    for item in eval_set:
        chunks = retriever(item["question"], k_max)
        if len(chunks) < k_max:
            raise RuntimeError(
                f"Retriever returned {len(chunks)} chunks for {item['id']}; "
                f"expected at least {k_max}"
            )
        contexts = [
            _context_from_chunk(chunk, rank, entries)
            for rank, chunk in enumerate(chunks[:k_max], start=1)
        ]
        retrievals.append(
            {
                "id": item["id"],
                "question": item["question"],
                "k_max": k_max,
                "contexts": contexts,
            }
        )
    return retrievals


def build_run_artifact(
    *,
    eval_set: Sequence[Mapping[str, Any]],
    eval_set_path: Path,
    collection_chunks: Sequence[Any],
    retriever: Callable[[str, int], list[Any]],
    retriever_name: str,
    k_values: Sequence[int],
    run_id: str,
    timestamp: str,
    git: Mapping[str, Any],
    env: Mapping[str, Any],
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a complete run artifact from fixed inputs and retrieval results."""
    if not k_values or any(
        isinstance(k, bool) or not isinstance(k, int) or k < 1 for k in k_values
    ):
        raise ValueError("k_values must contain positive integers")
    if not isinstance(retriever_name, str) or not retriever_name:
        raise ValueError("retriever_name must be a non-empty string")
    normalized_k_values = sorted(set(k_values))
    manifest = harness.build_chunk_manifest(collection_chunks)
    retrievals = collect_retrievals(
        eval_set,
        retriever,
        max(normalized_k_values),
        manifest,
    )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "timestamp": timestamp,
        "retriever": retriever_name,
        "k_values": normalized_k_values,
        "git": dict(git),
        "env": dict(env),
        "corpus": dict(corpus),
        "eval_set": {
            "path": _relative_to_root(eval_set_path),
            "sha256": harness.file_sha256(eval_set_path),
            "n": len(eval_set),
        },
        "chunk_manifest": manifest,
        "retrievals": retrievals,
    }


def _collection_chunks(collection: Any) -> list[Document]:
    count = collection._collection.count()
    raw = collection._collection.get(include=["documents", "metadatas"], limit=count)
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []
    if len(documents) != count or len(metadatas) != count:
        raise RuntimeError("Collection did not return all chunk bodies and metadata")
    return [
        Document(page_content=text, metadata=metadata)
        for text, metadata in zip(documents, metadatas)
    ]


def vector_retriever(question: str, k: int) -> list[Any]:
    return (
        get_vector_store()
        .get_chroma(harness.EVAL_COLLECTION)
        .similarity_search(query=question, k=k)
    )


def run() -> Path:
    """Execute vector retrieval and write an ignored run.json artifact."""
    eval_set = harness.load_eval_set(EVAL_SET_PATH)
    corpus = harness.corpus_info()
    collection = get_vector_store().get_chroma(harness.EVAL_COLLECTION)
    harness.validate_collection(collection, corpus)
    now = datetime.now().astimezone()
    run_id = now.strftime("%Y%m%dT%H%M%S%f")
    artifact = build_run_artifact(
        eval_set=eval_set,
        eval_set_path=EVAL_SET_PATH,
        collection_chunks=_collection_chunks(collection),
        retriever=vector_retriever,
        retriever_name="vector-only",
        k_values=K_VALUES,
        run_id=run_id,
        timestamp=now.isoformat(),
        git=harness.git_info(),
        env=harness.capture_env(collection),
        corpus=corpus,
    )
    run_dir = harness.ROOT / "eval" / "results" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    run_path = run_dir / "run.json"
    run_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Run artifact: {run_path}")
    return run_path


if __name__ == "__main__":
    run()
