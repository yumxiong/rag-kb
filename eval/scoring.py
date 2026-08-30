"""Pure retrieval scoring functions.

The matching and aggregation semantics intentionally mirror the existing v2
evaluation implementation. This module does not import Chroma or make any
network calls, so the rules can be characterized with deterministic fixtures.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

MATCHER_VERSION = 1
SCORER_VERSION = 2


def _norm(t: Any) -> str:
    """Normalize text exactly as the historical scorer did."""
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
    all_snippets = list(dict.fromkeys(required + any_pool))

    cumulative: set[str] = set()
    snippet_ranks = {snippet: None for snippet in all_snippets}
    completion_rank = None
    earliest_evidence_rank = None
    witness_chunks = []
    for rank, chunk in enumerate(chunks[:k], start=1):
        chunk_hits = hits_in_chunk(chunk, all_snippets)
        if chunk_hits and earliest_evidence_rank is None:
            earliest_evidence_rank = rank
        new_hits = chunk_hits - cumulative
        for snippet in all_snippets:
            if snippet in new_hits:
                snippet_ranks[snippet] = rank
        if new_hits and completion_rank is None:
            metadata = getattr(chunk, "metadata", None) or {}
            witness = {
                "rank": rank,
                "chunk_ref": metadata.get("chunk_ref"),
                "filename": metadata.get("filename"),
                "chunk_index": metadata.get("chunk_index"),
                "snippets": [
                    snippet for snippet in all_snippets if snippet in new_hits
                ],
            }
            if witness["chunk_ref"] is None and metadata.get("chunk_id"):
                witness["chunk_id"] = metadata["chunk_id"]
            witness_chunks.append(witness)
        cumulative |= chunk_hits
        if completion_rank is None and is_hit(cumulative, match):
            completion_rank = rank

    hit = is_hit(cumulative, match)
    cov = coverage_scores(cumulative, match)
    witness_documents = {
        witness["filename"]
        for witness in witness_chunks
        if witness["filename"] is not None
    }
    return {
        "id": item["id"],
        "type": item.get("type", "-"),
        "hit": hit,
        "snippet_ranks": snippet_ranks,
        "completion_rank": completion_rank,
        "first_rank": completion_rank,
        "earliest_evidence_rank": earliest_evidence_rank,
        "hop_spread": (
            completion_rank - earliest_evidence_rank
            if completion_rank is not None and earliest_evidence_rank is not None
            else None
        ),
        "witness_chunks": witness_chunks,
        "witness_doc_count": len(witness_documents),
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
        mrr = sum(
            1.0 / row["completion_rank"] for row in rows if row["completion_rank"]
        )
        coverage = sum(row["coverage"] for row in rows)
        fully_covered = sum(1 for row in rows if row["fully_covered"])
        entry: dict[str, Any] = {
            "n": n,
            "Hit": round(hit / n, 3),
            "Coverage": round(coverage / n, 3),
            "FullyCovered": round(fully_covered / n, 3),
            "MRR": round(mrr / n, 3),
        }
        if question_type == "multihop":
            hit_rows = [row for row in rows if row["hit"]]
            mean_hop_spread = (
                sum((row["hop_spread"] or 0) for row in hit_rows) / len(hit_rows)
                if hit_rows
                else 0.0
            )
            mean_witness_chunks = sum(len(row["witness_chunks"]) for row in rows) / n
            multi_doc = sum(
                1 for row in rows if row["hit"] and row["witness_doc_count"] >= 2
            )
            entry.update(
                {
                    "MeanHopSpread": round(mean_hop_spread, 3),
                    "MeanWitnessChunks": round(mean_witness_chunks, 3),
                    "MultiDocRate": round(multi_doc / n, 3),
                }
            )
        result[question_type] = entry
    return result
