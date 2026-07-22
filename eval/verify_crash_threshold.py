"""精确定位 HNSW 写入崩溃阈值。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb
from chromadb.config import Settings as ChromaSettings

DIM = 1024
COLL = "win_crash_threshold"


def main() -> None:
    # 使用独立临时目录，避免被先前崩溃污染的主库影响
    tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_crash_"))
    print(f"Using temp chroma path: {tmp_dir}", flush=True)

    client = chromadb.PersistentClient(
        path=str(tmp_dir),
        settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
    )
    coll = client.get_or_create_collection(COLL)

    inserted = 0
    for n in range(1, 151):
        coll.add(
            ids=[f"id-{n}"],
            documents=[f"doc {n}"],
            embeddings=[[0.001 * (n % 97 + 1)] * DIM],
        )
        inserted = n
        if n <= 10 or n % 5 == 0 or n >= 90:
            print(f"OK after insert #{n}, count={coll.count()}", flush=True)

    print(f"DONE: inserted {inserted}, final count={coll.count()}", flush=True)


if __name__ == "__main__":
    main()
