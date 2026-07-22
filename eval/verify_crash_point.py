"""
Windows Chroma 崩溃点隔离验证脚本。

每个测试在独立子进程中运行，以便 segfault 时仍能记录退出码。
用法:
  python eval/verify_crash_point.py              # 运行全部测试
  python eval/verify_crash_point.py --test 2     # 只跑单个测试
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_COLLECTION = "win_crash_test"


def _run_test(name: str, test_id: int, python: str) -> int:
    """在子进程中运行单个测试，返回退出码。"""
    print(f"\n{'=' * 60}")
    print(f"TEST {test_id}: {name}")
    print("=" * 60)
    result = subprocess.run(
        [python, str(Path(__file__)), "--test", str(test_id)],
        cwd=str(ROOT),
        capture_output=False,
    )
    code = result.returncode
    if code == 0:
        print(f"[RESULT] TEST {test_id} PASSED (exit 0)")
    elif code == -1073741819 or code == 3221225477:  # 0xC0000005 unsigned/signed
        print(f"[RESULT] TEST {test_id} SEGFAULT / ACCESS_VIOLATION (exit {code} / 0xC0000005)")
    else:
        print(f"[RESULT] TEST {test_id} FAILED (exit {code})")
    return code


def test_1_process_document_only() -> None:
    """仅 DocumentProcessor，不涉及 Chroma。"""
    from app.core.document_processor import DocumentProcessor

    folder = ROOT / "data" / "eval_docs"
    processor = DocumentProcessor()
    md_files = sorted(f for f in folder.iterdir() if f.suffix.lower() == ".md")
    if not md_files:
        raise RuntimeError(f"no eval docs in {folder}")

    target = md_files[0]
    result = processor.process_document(str(target), target.name)
    assert result["status"] == "completed", result
    assert result["chunks"], "expected non-empty chunks"
    print(f"OK: process_document {target.name} -> {len(result['chunks'])} chunks")


def test_2_embed_only() -> None:
    """仅 embedding API + 缓存，不写 Chroma。"""
    from app.core.vector_store import get_vector_store

    vs = get_vector_store()
    vs._ensure_initialized()
    texts = ["RAG 检索评估基线测试文本"]
    vectors = vs.embeddings.embed_documents(texts)
    assert vectors and len(vectors[0]) > 0
    print(f"OK: embed_documents -> dim={len(vectors[0])}")


def test_3_chroma_raw_add_dummy_embeddings() -> None:
    """绕过 LangChain，直接用 PersistentClient + 假向量写入。"""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    from app.core.config import settings

    dim = 1024  # text-embedding-v3 默认维度
    client = chromadb.PersistentClient(
        path=settings.chroma_db_path,
        settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
    )
    try:
        client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass

    coll = client.get_or_create_collection(TEST_COLLECTION)
    coll.add(
        ids=["dummy-1"],
        documents=["dummy document for crash test"],
        embeddings=[[0.01] * dim],
    )
    count = coll.count()
    assert count >= 1, f"expected count>=1, got {count}"
    print(f"OK: raw chromadb add 1 item, count={count}")


def test_4_langchain_add_one_chunk() -> None:
    """LangChain Chroma.add_documents：embedding + 写入。"""
    from app.core.document_processor import DocumentProcessor
    from app.core.vector_store import get_vector_store

    folder = ROOT / "data" / "eval_docs"
    processor = DocumentProcessor()
    vs = get_vector_store()
    vs._ensure_initialized()

    try:
        vs.chroma_client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass

    coll = vs.get_chroma(TEST_COLLECTION)
    md_files = sorted(f for f in folder.iterdir() if f.suffix.lower() == ".md")
    result = processor.process_document(str(md_files[0]), md_files[0].name)
    chunks = result["chunks"][:1]

    print(f"before add_documents: 1 chunk from {md_files[0].name}")
    coll.add_documents(chunks, ids=[chunks[0].metadata["chunk_id"]])
    total = coll._collection.count()
    print(f"OK: langchain add_documents, count={total}")


def test_5_incremental_raw_adds() -> None:
    """逐步增加写入条数，观察在第几条触发崩溃（已知 Windows 上约第 100 条）。"""
    import tempfile

    import chromadb
    from chromadb.config import Settings as ChromaSettings

    dim = 1024
    tmp_dir = tempfile.mkdtemp(prefix="chroma_crash_")
    print(f"Using temp chroma path: {tmp_dir}", flush=True)

    client = chromadb.PersistentClient(
        path=tmp_dir,
        settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
    )
    coll = client.get_or_create_collection(TEST_COLLECTION + "_incr")

    for n in range(1, 101):
        coll.add(
            ids=[f"id-{n}"],
            documents=[f"doc content {n}"],
            embeddings=[[0.001 * (n % 97 + 1)] * dim],
        )
        if n <= 10 or n % 10 == 0 or n >= 95:
            print(f"OK: inserted {n}, count={coll.count()}", flush=True)

    print(f"OK: incremental add completed, final count={coll.count()}", flush=True)


TESTS = {
    1: ("DocumentProcessor only (no Chroma)", test_1_process_document_only),
    2: ("Embed only (no Chroma write)", test_2_embed_only),
    3: ("Raw Chroma add with dummy embeddings", test_3_chroma_raw_add_dummy_embeddings),
    4: ("LangChain add_documents (embed + write)", test_4_langchain_add_one_chunk),
    5: ("Incremental raw adds up to 100", test_5_incremental_raw_adds),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, choices=sorted(TESTS.keys()))
    args = parser.parse_args()

    if args.test:
        name, fn = TESTS[args.test]
        print(f"Running: {name}")
        fn()
        return 0

    python = sys.executable
    print(f"Python: {python}")
    print(f"ROOT: {ROOT}")
    print("Running crash-point isolation tests in subprocesses...")

    results: dict[int, int] = {}
    for test_id, (name, _) in sorted(TESTS.items()):
        results[test_id] = _run_test(name, test_id, python)

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    first_crash = None
    for test_id, code in results.items():
        label = TESTS[test_id][0]
        if code == 0:
            status = "PASS"
        elif code in (-1073741819, 3221225477):
            status = "SEGFAULT"
            if first_crash is None:
                first_crash = test_id
        else:
            status = f"FAIL({code})"
            if first_crash is None and code != 0:
                first_crash = test_id
        print(f"  TEST {test_id} [{status}] {label}")

    if first_crash:
        print(f"\nFirst failure/crash at TEST {first_crash}: {TESTS[first_crash][0]}")
    else:
        print("\nAll tests passed — no segfault reproduced in this run.")

    return 0 if all(c == 0 for c in results.values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
