"""Retrieval evaluation harness with multi-k sweeps and pinned artifacts.

The historical entry point remains available for compatibility. Shared
environment/corpus helpers now live in :mod:`eval.harness`, while pure scoring
rules live in :mod:`eval.scoring`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.vector_store import get_vector_store  # noqa: E402
from eval import harness as _harness  # noqa: E402
from eval import scoring as _scoring  # noqa: E402

EVAL_COLLECTION = _harness.EVAL_COLLECTION
K_VALUES = [1, 3, 5, 10]
ROOT = _harness.ROOT
EVAL_SET_PATH = ROOT / "eval" / "eval_set_v2.json"
CORPUS_DIR = _harness.CORPUS_DIR

# Compatibility exports retained while callers migrate to harness/scoring.
load_eval_set = _harness.load_eval_set
file_sha256 = _harness.file_sha256
capture_env = _harness.capture_env
git_info = _harness.git_info
validate_collection = _harness.validate_collection
_norm = _scoring._norm
_match_parts = _scoring._match_parts
hits_in_chunk = _scoring.hits_in_chunk
is_hit = _scoring.is_hit
coverage_scores = _scoring.coverage_scores
score_question = _scoring.score_question
aggregate = _scoring.aggregate


def corpus_info() -> dict[str, Any]:
    """Compatibility wrapper honoring the historical module-level patch point."""
    return _harness.corpus_info(CORPUS_DIR)


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
                fields.extend(
                    [
                        f"FullyCovered@{k}={entry['FullyCovered']}",
                        f"MeanHopSpread@{k}={entry['MeanHopSpread']}",
                        f"MeanWitnessChunks@{k}={entry['MeanWitnessChunks']}",
                        f"MultiDocRate@{k}={entry['MultiDocRate']}",
                    ]
                )
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
        if row["type"] == "multihop":
            witness_refs = [
                witness.get("chunk_ref") or witness.get("chunk_id") or "-"
                for witness in row["witness_chunks"]
            ]
            print(
                f"     snippets={row['snippet_ranks']} "
                f"witnesses={witness_refs} docs={row['witness_doc_count']} "
                f"spread={row['hop_spread']}"
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
