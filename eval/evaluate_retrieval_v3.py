"""Retrieval evaluation harness with multi-k sweeps and pinned artifacts.

The scoring rules intentionally mirror ``evaluate_retrieval_v2.py``.  Retrieval
is performed once at the largest requested k and every smaller k is scored from
that ranked prefix, keeping the sweep deterministic and inexpensive.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.document_processor import DocumentProcessor  # noqa: E402
from app.core.vector_store import get_vector_store  # noqa: E402

EVAL_COLLECTION = "rag_eval_documents"
K_VALUES = [1, 3, 5, 10]
ROOT = Path(__file__).resolve().parents[1]
EVAL_SET_PATH = ROOT / "eval" / "eval_set_v2.json"
CORPUS_DIR = ROOT / "data" / "eval_docs"


def load_eval_set(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# These helpers are deliberately kept equivalent to v2's scoring semantics.
def _norm(t: Any) -> str:
    return "".join(str(t).split()).lower()


def _match_parts(match: dict[str, Any] | None) -> tuple[list[str], list[str], int]:
    match = match or {}
    return (
        match.get("required") or [],
        match.get("any_of") or [],
        match.get("any_of_min", 1),
    )


def hits_in_chunk(chunk: Any, snippets: Iterable[str]) -> set[str]:
    content = _norm(chunk.page_content)
    return {snippet for snippet in snippets if _norm(snippet) in content}


def is_hit(found: set[str], match: dict[str, Any] | None) -> bool:
    required, any_pool, min_any = _match_parts(match)
    req_ok = all(snippet in found for snippet in required)
    any_hit = sum(1 for snippet in any_pool if snippet in found)
    any_ok = (not any_pool) or any_hit >= min_any
    return req_ok and any_ok


def coverage_scores(found: set[str], match: dict[str, Any] | None) -> dict[str, float]:
    required, any_pool, min_any = _match_parts(match)
    req_cov = (
        len([snippet for snippet in required if snippet in found]) / len(required)
        if required
        else 1.0
    )
    any_hit = sum(1 for snippet in any_pool if snippet in found)
    if any_pool:
        any_cov = 1.0 if any_hit >= min_any else any_hit / min_any
    else:
        any_cov = 1.0
    parts = []
    if required:
        parts.append(req_cov)
    if any_pool:
        parts.append(any_cov)
    overall = sum(parts) / len(parts) if parts else 1.0
    return {
        "required": round(req_cov, 3),
        "any_of": round(any_cov, 3),
        "overall": round(overall, 3),
    }


def score_question(item: dict[str, Any], chunks: list[Any], k: int) -> dict[str, Any]:
    match = item.get("match") or {}
    required, any_pool, _ = _match_parts(match)
    all_snippets = required + any_pool

    cumulative: set[str] = set()
    first_rank = None
    for rank, chunk in enumerate(chunks[:k], start=1):
        cumulative |= hits_in_chunk(chunk, all_snippets)
        if first_rank is None and is_hit(cumulative, match):
            first_rank = rank

    hit = is_hit(cumulative, match)
    cov = coverage_scores(cumulative, match)
    return {
        "id": item["id"],
        "type": item.get("type", "-"),
        "hit": hit,
        "first_rank": first_rank,
        "coverage": cov["overall"],
        "cov_required": cov["required"],
        "cov_any_of": cov["any_of"],
        "fully_covered": cov["overall"] == 1.0,
        "has_required": bool(required),
        "has_any_of": bool(any_pool),
    }


def aggregate(per_q: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_q:
        by_type[row["type"]].append(row)

    result: dict[str, dict[str, Any]] = {}
    for question_type, rows in by_type.items():
        n = len(rows)
        hit = sum(1 for row in rows if row["hit"])
        mrr = sum(1.0 / row["first_rank"] for row in rows if row["first_rank"])
        coverage = sum(row["coverage"] for row in rows)
        fully_covered = sum(1 for row in rows if row["fully_covered"])
        entry: dict[str, Any] = {
            "n": n,
            "Hit": round(hit / n, 3),
            "Coverage": round(coverage / n, 3),
            "FullyCovered": round(fully_covered / n, 3),
        }
        if question_type in ("exact", "semantic"):
            entry["MRR"] = round(mrr / n, 3)
        result[question_type] = entry
    return result


def evaluate_sweep(
    retriever: Callable[[str, int], list[Any]],
    eval_set: list[dict[str, Any]],
    k_values: list[int],
) -> list[dict[str, Any]]:
    if not k_values or any(k < 1 for k in k_values):
        raise ValueError("k_values must contain positive integers")
    k_max = max(k_values)
    pools = {item["id"]: retriever(item["question"], k_max) for item in eval_set}
    shortfalls = {
        item["id"]: len(pools[item["id"]])
        for item in eval_set
        if len(pools[item["id"]]) < k_max
    }
    if shortfalls:
        raise RuntimeError(
            f"Retriever returned fewer than k_max={k_max} chunks: {shortfalls}"
        )

    results = []
    for k in k_values:
        rows = [score_question(item, pools[item["id"]], k) for item in eval_set]
        results.append({"k": k, "by_type": aggregate(rows), "rows": rows})
    return results


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_info() -> dict[str, Any]:
    processor = DocumentProcessor()
    files = sorted(
        path
        for path in CORPUS_DIR.iterdir()
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


def _fmt_sub_cov(value: float, applicable: bool) -> str:
    return "-" if not applicable else str(value)


def print_report(results: list[dict[str, Any]], artifact_path: Path) -> None:
    for result in results:
        k = result["k"]
        for question_type, entry in result["by_type"].items():
            fields = [
                f"n={entry['n']}",
                f"Hit@{k}={entry['Hit']}",
                f"Coverage@{k}={entry['Coverage']}",
            ]
            if "MRR" in entry:
                fields.insert(2, f"MRR@{k}={entry['MRR']}")
            if question_type == "multihop":
                fields.append(f"FullyCovered@{k}={entry['FullyCovered']}")
            print(f"[{question_type}] " + "  ".join(fields))

    max_result = max(results, key=lambda result: result["k"])
    print(f"\nPer question (k={max_result['k']}):")
    print(
        f"{'id':<4} {'type':<9} {'hit':<5} {'rank':<5} {'cov':<6} {'req':<6} {'any':<6}"
    )
    for row in max_result["rows"]:
        print(
            f"{row['id']:<4} {row['type']:<9} {str(row['hit']):<5} "
            f"{row['first_rank'] or '-':<5} {row['coverage']:<6} "
            f"{_fmt_sub_cov(row['cov_required'], row['has_required']):<6} "
            f"{_fmt_sub_cov(row['cov_any_of'], row['has_any_of']):<6}"
        )
    print(f"\nArtifact: {artifact_path}")


def vector_retriever(question: str, k: int) -> list[Any]:
    return (
        get_vector_store()
        .get_chroma(EVAL_COLLECTION)
        .similarity_search(query=question, k=k)
    )


def run() -> Path:
    eval_set = load_eval_set(EVAL_SET_PATH)
    corpus = corpus_info()
    store = get_vector_store()
    coll = store.get_chroma(EVAL_COLLECTION)
    validate_collection(coll, corpus)
    results = evaluate_sweep(vector_retriever, eval_set, K_VALUES)

    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    artifact = {
        "run_id": run_id,
        "timestamp": datetime.now().astimezone().isoformat(),
        "retriever": "vector-only",
        "k_values": K_VALUES,
        "git": git_info(),
        "env": capture_env(coll),
        "corpus": corpus,
        "eval_set": {
            "path": "eval/eval_set_v2.json",
            "sha256": file_sha256(EVAL_SET_PATH),
            "n": len(eval_set),
        },
        "results": results,
    }
    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = results_dir / f"{run_id}_vector-only.json"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print_report(results, artifact_path)
    return artifact_path


if __name__ == "__main__":
    run()
