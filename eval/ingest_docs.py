import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.document_processor import DocumentProcessor
from app.core.vector_store import get_vector_store


ROOT = Path(__file__).resolve().parents[1]
# 指定需要遍历的文件夹路径
folder_path = ROOT / "data" / "eval_docs"
processor = DocumentProcessor()
vector_store = get_vector_store()

EVAL_COLLECTION = "rag_eval_documents"
vector_store._ensure_initialized()

# 防止chunks重复入库，如果集合存在则删除
try:
    vector_store.chroma_client.delete_collection(EVAL_COLLECTION)
except Exception as e:
    pass

eval_coll = vector_store.get_chroma(EVAL_COLLECTION)

# 遍历文件夹下的所有文件
for file_path in folder_path.iterdir():
    if file_path.is_file() and processor.is_supported_file(file_path.name):
        try:
            # 读取文件内容
            result = processor.process_document(str(file_path), file_path.name)
            if result['status'] != 'completed' or not result['chunks']:
                print(f"处理失败 {file_path.name}: {result.get('error_message', 'Unknown error')}")
                continue
            eval_coll.add_documents(
                result['chunks'],
                ids=[doc.metadata['chunk_id'] for doc in result['chunks']],
            )
            print(f"成功读取 {file_path.name}")
        except Exception as e:
            print(f"入库失败 {file_path.name}: {type(e).__name__}: {e}")

print("所有文档处理完成")
total = eval_coll._collection.count()
print(f"入库完成， rag_eval_documents 集合中共有 {total} 条数据")
if total == 0:
    print("入库失败，rag_eval_documents 集合中没有数据")
    sys.exit(1)