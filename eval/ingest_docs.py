import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.document_processor import DocumentProcessor  # noqa: E402
from app.core.vector_store import get_vector_store  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
EVAL_COLLECTION = "rag_eval_documents"


def ingest() -> int:
    folder_path = ROOT / "data" / "eval_docs"
    processor = DocumentProcessor()
    vector_store = get_vector_store()
    vector_store._ensure_initialized()

    client = vector_store.chroma_client
    if EVAL_COLLECTION in {collection.name for collection in client.list_collections()}:
        client.delete_collection(EVAL_COLLECTION)
        if EVAL_COLLECTION in {
            collection.name for collection in client.list_collections()
        }:
            raise RuntimeError(
                f"Could not delete existing collection {EVAL_COLLECTION}"
            )

    eval_coll = vector_store.get_chroma(EVAL_COLLECTION)
    expected_files = set()
    expected_chunks = 0

    for file_path in sorted(folder_path.iterdir()):
        if not file_path.is_file() or not processor.is_supported_file(file_path.name):
            continue
        expected_files.add(file_path.name)
        result = processor.process_document(str(file_path), file_path.name)
        if result["status"] != "completed" or not result["chunks"]:
            raise RuntimeError(
                f"Failed to process {file_path.name}: "
                f"{result.get('error_message', 'unknown error')}"
            )
        chunks = result["chunks"]
        eval_coll.add_documents(
            chunks,
            ids=[doc.metadata["chunk_id"] for doc in chunks],
        )
        expected_chunks += len(chunks)
        print(f"成功读取 {file_path.name}")

    total = eval_coll._collection.count()
    if total == 0 or total != expected_chunks:
        raise RuntimeError(
            f"Collection count mismatch: expected {expected_chunks}, got {total}"
        )

    raw = eval_coll._collection.get(include=["metadatas"], limit=total)
    metadatas = raw.get("metadatas") or []
    required = {"filename", "document_id", "chunk_id"}
    if len(metadatas) != total or any(
        not metadata or not required.issubset(metadata) for metadata in metadatas
    ):
        raise RuntimeError("One or more ingested chunks have incomplete metadata")
    actual_files = {metadata["filename"] for metadata in metadatas}
    if actual_files != expected_files:
        raise RuntimeError(
            f"Collection file mismatch: expected {sorted(expected_files)}, "
            f"got {sorted(actual_files)}"
        )

    print("所有文档处理完成")
    print(f"入库完成， rag_eval_documents 集合中共有 {total} 条数据")
    return total


if __name__ == "__main__":
    try:
        ingest()
    except Exception as exc:
        print(f"评测语料入库失败: {type(exc).__name__}: {exc}")
        sys.exit(1)
