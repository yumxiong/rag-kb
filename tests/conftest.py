"""
pytest配置文件
"""

import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

logger = logging.getLogger(__name__)


class AsyncDocumentProcessor:
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="doc_processor"
        )
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # 启动清理线程
        self._start_cleanup_thread()

    def submit_task(self, job_id: str, file_path: str, filename: str) -> str:
        """提交处理任务"""
        future = self.executor.submit(
            self._process_document_safe, job_id, file_path, filename
        )

        with self._lock:
            self.tasks[job_id] = {
                "future": future,
                "filename": filename,
                "submitted_at": time.time(),
                "status": "queued",
            }

        logger.info(f"Task submitted for file {filename} (job_id: {job_id})")
        return job_id

    def get_task_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self._lock:
            task_info = self.tasks.get(job_id)

        if not task_info:
            return None

        future = task_info["future"]

        if future.done():
            if future.exception():
                return {
                    "status": "failed",
                    "job_id": job_id,
                    "document_id": None,
                    "error": str(future.exception()),
                    "filename": task_info["filename"],
                }
            else:
                result = future.result()
                return {
                    "status": "completed" if result.get("success") else "failed",
                    "job_id": job_id,
                    "filename": task_info["filename"],
                    "chunk_count": result.get("chunk_count", 0),
                    "document_id": (
                        result.get("document_id") if result.get("success") else None
                    ),
                    "error": result.get("error"),
                }
        else:
            return {
                "status": "processing",
                "job_id": job_id,
                "document_id": None,
                "filename": task_info["filename"],
                "submitted_at": task_info["submitted_at"],
            }

    def _process_document_safe(
        self, job_id: str, file_path: str, filename: str
    ) -> Dict[str, Any]:
        """安全的文档处理包装器"""
        try:
            from app.core.document_processor import doc_processor
            from app.core.job_status import job_status
            from app.core.vector_store import get_vector_store

            logger.info(f"Starting processing for {filename}")

            # 更新状态
            job_status.mark_processing(job_id, progress=10, message="开始处理文档")

            # 移动文件到最终目录
            if doc_processor.is_in_temp_dir(file_path):
                real_path = doc_processor.move_to_upload_dir(file_path, filename)
            else:
                real_path = file_path

            job_status.mark_processing(job_id, progress=20, message="文件准备完成")

            # 处理文档
            result = doc_processor.process_document(real_path)

            if result["status"] == "completed":
                # 添加到向量存储
                chunks = result.get("chunks", [])
                for chunk in chunks:
                    chunk.metadata["job_id"] = job_id

                job_status.mark_processing(job_id, progress=80, message="生成向量嵌入")
                get_vector_store().add_documents(chunks)

                real_document_id = result.get("document_id")
                # 标记完成
                job_status.mark_completed(
                    job_id,
                    chunk_count=len(chunks),
                    filename=filename,
                    document_id=real_document_id,
                )

                logger.info(f"Document {filename} processed successfully")
                return {
                    "success": True,
                    "job_id": job_id,
                    "chunk_count": len(chunks),
                    "document_id": real_document_id,
                }
            else:
                error_msg = result.get("error_message", "Unknown processing error")
                job_status.mark_failed(job_id, error=error_msg, filename=filename)
                return {
                    "success": False,
                    "job_id": job_id,
                    "document_id": None,
                    "error": error_msg,
                }

        except Exception as e:
            logger.error(f"Document processing failed for {filename}: {str(e)}")
            job_status.mark_failed(job_id, error=str(e), filename=filename)
            return {
                "success": False,
                "job_id": job_id,
                "document_id": None,
                "error": str(e),
            }

    def _start_cleanup_thread(self):
        """启动清理线程，定期清理完成的任务"""

        def cleanup_worker():
            while True:
                try:
                    current_time = time.time()
                    with self._lock:
                        # 清理1小时前完成的任务
                        to_remove = []
                        for doc_id, task_info in self.tasks.items():
                            if (
                                task_info["future"].done()
                                and current_time - task_info["submitted_at"] > 3600
                            ):
                                to_remove.append(doc_id)

                        for doc_id in to_remove:
                            del self.tasks[doc_id]

                    if to_remove:
                        logger.info(f"Cleaned up {len(to_remove)} completed tasks")

                except Exception as e:
                    logger.error(f"Cleanup thread error: {e}")

                time.sleep(300)  # 5分钟清理一次

        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()


# 全局单例
async_processor = AsyncDocumentProcessor(max_workers=2)


@pytest.fixture
def temp_dir():
    """临时目录fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_settings():
    """模拟设置fixture"""
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.openai_api_key = "test-api-key"
        mock_settings.upload_dir = "/tmp/test_uploads"
        mock_settings.chroma_db_path = "/tmp/test_chroma"
        mock_settings.chunk_size = 1000
        mock_settings.chunk_overlap = 200
        mock_settings.max_sources = 3
        mock_settings.similarity_threshold = 0.7
        mock_settings.app_name = "RAG Knowledge Base"
        mock_settings.app_version = "1.0.0"
        mock_settings.debug = False
        yield mock_settings


@pytest.fixture
def sample_document():
    """示例文档fixture"""
    return {
        "content": "This is a test document content for RAG testing.",
        "metadata": {"filename": "test.txt", "document_id": "test-doc-123", "page": 1},
    }


@pytest.fixture(autouse=True)
def mock_openai_key():
    """自动模拟OpenAI API Key"""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        yield


@pytest.fixture
def mock_vector_store():
    """模拟向量存储fixture"""
    with patch("app.core.vector_store.VectorStore") as mock_vs:
        mock_instance = mock_vs.return_value
        mock_instance.get_collection_info.return_value = {"document_count": 0}
        mock_instance.list_documents.return_value = []
        mock_instance.add_documents.return_value = True
        mock_instance.delete_document_by_id.return_value = True
        yield mock_instance


@pytest.fixture
def test_document_content():
    """测试文档内容fixture"""
    return "This is a test document with some content for testing purposes. " * 10


@pytest.fixture
def mock_job_status():
    """模拟作业状态fixture"""
    with patch("app.core.job_status.JobStatus") as mock_job:
        mock_instance = mock_job.return_value
        mock_instance.init_job.return_value = True
        mock_instance.mark_processing.return_value = True
        mock_instance.mark_completed.return_value = True
        mock_instance.mark_failed.return_value = True
        yield mock_instance
