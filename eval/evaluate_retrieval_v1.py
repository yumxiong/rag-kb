# eval/evaluate_retrieval.py
"""检索质量评估 —— 跨 向量/混合/重排 复用的同一把尺子。"""
import json, sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))  # 让脚本能 import app.*

from app.core.vector_store import get_vector_store


EVAL_COLLECTION = "rag_eval_documents"
ROOT = Path(__file__).resolve().parents[1]

def load_eval_set(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _norm(t):  # 归一化：去空白、转小写，让子串匹配更稳
    return "".join(str(t).split()).lower()

def is_correct(chunk, item):
    """判断一个检索到的 chunk 是否命中标准答案。"""
    content = _norm(chunk.page_content)
    snippets = item.get("expected_snippets") or []
    if snippets:
        gold_count = sum(1 for s in snippets if _norm(s) in content)
        return gold_count >= (item.get("threshold_hit") or 1)
    expected_doc = item.get("expected_doc")           # 回退到文档级匹配
    if expected_doc:
        meta = chunk.metadata or {}
        return expected_doc in (meta.get("filename", ""), meta.get("document_id", ""))
    return False

def evaluate(retriever, eval_set, k):
    """retriever: 函数 (question, k) -> List[Document]（已按相关性排序）"""
    hit, rr, rows = 0, 0.0, []
    coverage = []
    for item in eval_set:
        chunks = retriever(item["question"], k)
        first_rank = None
        for rank, ch in enumerate(chunks[:k], start=1):
            if item["type"] == "multihop":
                coverage.extend(coverage_eval(ch, item))
            if is_correct(ch, item):
                first_rank = rank
                break
        if first_rank:
            hit += 1
            rr += 1.0 / first_rank
        rows.append((item["id"], item.get("type", "-"), first_rank))
    n = len(eval_set)
    recall = len(list(set(coverage))) / len(eval_set)
    return {"n": n, "k": k, "Hit": round(hit/n, 3), "MRR": round(rr/n, 3), "rows": rows, "recall": recall}

def coverage_eval(chunk, item):
    """判断一个检索到的 chunk 命中多少gold snippets"""
    content = _norm(chunk.page_content)
    coverage = []
    snippets = item.get("expected_snippets") or []
    if snippets:
        for rank, ch in enumerate(snippets, start=1):
            if _norm(ch) in content:
                coverage.append(ch)
                
    return coverage

# ↓↓↓ 第 0 步只需要这个；第 1/2/3 步你会再写 bm25_/hybrid_/rerank_retriever
def vector_retriever(question, k):
    return get_vector_store().get_chroma(EVAL_COLLECTION).similarity_search(query=question, k=k)  # 纯向量基线，全库无过滤

def print_report(name, r):
    print(f"\n=== {name} | N={r['n']} | k={r['k']} ===")
    print(f"Hit@{r['k']}={r['Hit']}  MRR@{r['k']}={r['MRR']}")
    print(f"Recall@{r['k']}={r['recall']}")
    print("id | type | first_rank")
    for rid, typ, rank in r["rows"]:
        print(f"{rid} | {typ} | {rank or '-'}")

if __name__ == "__main__":
    eval_set = load_eval_set(ROOT / "eval" / "eval_set_v1.json")
    print_report("baseline: vector-only", evaluate(vector_retriever, eval_set, k=5))