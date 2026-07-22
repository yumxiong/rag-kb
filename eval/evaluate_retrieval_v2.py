# eval/evaluate_retrieval_v2.py
"""检索质量评估 —— 支持 eval_set_v2.json 的 match 分组标注。"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.vector_store import get_vector_store

EVAL_COLLECTION = "rag_eval_documents"
ROOT = Path(__file__).resolve().parents[1]


def load_eval_set(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _norm(t):
    return "".join(str(t).split()).lower()


def _match_parts(match):
    match = match or {}
    return (
        match.get("required") or [],
        match.get("any_of") or [],
        match.get("any_of_min", 1),
    )


def hits_in_chunk(chunk, snippets):
    content = _norm(chunk.page_content)
    return {s for s in snippets if _norm(s) in content}


def is_hit(found, match):
    required, any_pool, min_any = _match_parts(match)
    req_ok = all(s in found for s in required)
    any_hit = sum(1 for s in any_pool if s in found)
    any_ok = (not any_pool) or (any_hit >= min_any)
    return req_ok and any_ok


def coverage_scores(found, match):
    required, any_pool, min_any = _match_parts(match)
    req_cov = (
        len([s for s in required if s in found]) / len(required)
        if required else 1.0
    )
    any_hit = sum(1 for s in any_pool if s in found)
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


def eval_question(retriever, item, k):
    match = item.get("match") or {}
    required, any_pool, _ = _match_parts(match)
    all_snippets = required + any_pool
    chunks = retriever(item["question"], k)[:k]

    cumulative = set()
    first_rank = None
    for rank, ch in enumerate(chunks, start=1):
        cumulative |= hits_in_chunk(ch, all_snippets)
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


def evaluate(retriever, eval_set, k):
    per_q = [eval_question(retriever, it, k) for it in eval_set]
    by_type = defaultdict(list)
    for r in per_q:
        by_type[r["type"]].append(r)

    agg = {}
    for typ, rows in by_type.items():
        n = len(rows)
        hit = sum(1 for r in rows if r["hit"])
        mrr = sum(1.0 / r["first_rank"] for r in rows if r["first_rank"])
        cov = sum(r["coverage"] for r in rows)
        fully = sum(1 for r in rows if r["fully_covered"])
        entry = {
            "n": n,
            "Hit": round(hit / n, 3),
            "Coverage": round(cov / n, 3),
            "FullyCovered": round(fully / n, 3),
        }
        if typ in ("exact", "semantic"):
            entry["MRR"] = round(mrr / n, 3)
        agg[typ] = entry

    return {"k": k, "by_type": dict(agg), "rows": per_q}


def vector_retriever(question, k):
    return get_vector_store().get_chroma(EVAL_COLLECTION).similarity_search(
        query=question, k=k
    )


def _fmt_sub_cov(value, applicable):
    """applicable=False 时显示 '-'（该题无此项 match 规则）。"""
    if not applicable:
        return "-"
    return str(value)


def print_report(name, r):
    k = r["k"]
    bt = r["by_type"]
    print(f"\n=== {name} | k={k} ===")
    if "exact" in bt:
        e = bt["exact"]
        print(
            f"[exact]    n={e['n']}  "
            f"Hit@{k}={e['Hit']}  MRR@{k}={e['MRR']}  Coverage@{k}={e['Coverage']}"
        )
    if "semantic" in bt:
        s = bt["semantic"]
        print(
            f"[semantic] n={s['n']}  "
            f"Hit@{k}={s['Hit']}  MRR@{k}={s['MRR']}  Coverage@{k}={s['Coverage']}"
        )
    if "multihop" in bt:
        m = bt["multihop"]
        print(
            f"[multihop] n={m['n']}  "
            f"Coverage@{k}={m['Coverage']}  FullyCovered@{k}={m['FullyCovered']}"
        )
    print("-" * 72)
    print("Per question:")
    print(f"{'id':<4} {'type':<9} {'hit':<5} {'rank':<5} {'cov':<6} {'req':<6} {'any':<6}")
    for row in r["rows"]:
        print(
            f"{row['id']:<4} {row['type']:<9} "
            f"{str(row['hit']):<5} "
            f"{row['first_rank'] or '-':<5} "
            f"{row['coverage']:<6} "
            f"{_fmt_sub_cov(row['cov_required'], row['has_required']):<6} "
            f"{_fmt_sub_cov(row['cov_any_of'], row['has_any_of']):<6}"
        )


if __name__ == "__main__":
    eval_set = load_eval_set(ROOT / "eval" / "eval_set_v2.json")
    print_report("baseline: vector-only", evaluate(vector_retriever, eval_set, k=5))