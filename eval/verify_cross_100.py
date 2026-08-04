"""模拟 eval 入库后累计写入越过第 100 条时是否崩溃。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import settings

DIM = 1024
COLL = "rag_eval_documents"


def main() -> None:
    client = chromadb.PersistentClient(
        path=settings.chroma_db_path,
        settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
    )
    coll = client.get_collection(COLL)
    start = coll.count()
    print(f"Starting count={start}", flush=True)

    for i in range(start + 1, start + 51):
        coll.add(
            ids=[f"extra-{i}"],
            documents=[f"extra doc {i}"],
            embeddings=[[0.002 * (i % 50 + 1)] * DIM],
        )
        if i <= start + 5 or i % 5 == 0 or i >= start + 45:
            print(f"OK after insert #{i}, count={coll.count()}", flush=True)

    print(f"DONE final count={coll.count()}", flush=True)


if __name__ == "__main__":
    main()
