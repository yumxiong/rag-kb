import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from app.core.exceptions import CancellationError
from app.core.global_budget import require_document_maintenance

logger = logging.getLogger(__name__)


class AsyncDocumentProcessor:
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="doc_processor"
        )
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # 取消标志字典：job_id -> threading.Event
        self._cancel_flags: Dict[str, threading.Event] = {}

        # 启动清理线程
        self._start_cleanup_thread()

    def submit_task(
        self,
        job_id: str,
        file_path: str,
        filename: str,
        content_hash: Optional[str] = None,
    ) -> str:
        """提交处理任务"""
        require_document_maintenance()
        # 创建取消标志
        cancel_event = threading.Event()

        with self._lock:
            self._cancel_flags[job_id] = cancel_event

        future = self.executor.submit(
            self._process_document_safe, job_id, file_path, filename, content_hash
        )

        with self._lock:
            self.tasks[job_id] = {
                "future": future,
                "filename": filename,
                "content_hash": content_hash,
                "submitted_at": time.time(),
                "status": "queued",
                "file_path": file_path,  # 保存文件路径用于清理
            }

        logger.info(f"Task submitted for file {filename} (job_id: {job_id})")
        return job_id

    def cancel_task(self, job_id: str) -> Dict[str, Any]:
        """
        取消正在处理的任务

        Returns:
            Dict with keys: success, message, status
        """
        with self._lock:
            task_info = self.tasks.get(job_id)
            cancel_event = self._cancel_flags.get(job_id)

        if not task_info:
            return {
                "success": False,
                "message": "任务不存在或已完成",
                "status": "not_found",
            }

        future = task_info["future"]

        # 如果任务已经完成，无法取消
        if future.done():
            return {
                "success": False,
                "message": "任务已完成，无法取消",
                "status": "already_done",
            }

        # 设置取消标志
        if cancel_event:
            cancel_event.set()
            logger.info(f"Cancel flag set for document {job_id}")

        # 立即更新状态为 cancelling，让 SSE 监控器知道任务正在取消
        from app.core.job_status import job_status

        job_status.update(job_id, status="cancelling", message="正在取消任务...")

        # 尝试取消 Future（如果还在队列中未开始执行）
        cancelled = future.cancel()

        if cancelled:
            # 成功取消（任务还未开始执行）
            logger.info(f"Task cancelled before execution: {job_id}")
            self._cleanup_task_files(job_id, task_info)

            # 更新任务状态
            from app.core.job_status import job_status

            job_status.mark_cancelled(job_id, filename=task_info.get("filename"))

            return {
                "success": True,
                "message": "任务已取消（未开始执行）",
                "status": "cancelled",
            }
        else:
            # 任务已经在执行中，等待其检查取消标志
            logger.info(f"Task is running, waiting for cancellation check: {job_id}")
            return {
                "success": True,
                "message": "取消请求已发送，任务将在下一个检查点停止",
                "status": "cancelling",
            }

    def _check_cancelled(self, job_id: str) -> bool:
        """检查任务是否被取消（多通道检查：事件标志 + job_status）"""
        with self._lock:
            cancel_event = self._cancel_flags.get(job_id)

        if cancel_event and cancel_event.is_set():
            logger.info(f"Task {job_id} detected cancellation flag")
            return True

        # 兜底：读取持久化 job_status，若为 cancelling/cancelled 也视为已取消
        try:
            from app.core.job_status import job_status

            js = job_status.get(job_id) or {}
            st = (js.get("status") or "").lower()
            if st in ("cancelling", "cancelled"):
                logger.info(f"Task {job_id} detected job_status={st}")
                return True
        except Exception:
            pass
        return False

    def _cleanup_task_files(self, job_id: str, task_info: Dict[str, Any]):
        """清理任务相关的文件"""
        try:
            file_path = task_info.get("file_path")
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")

            # 如果文件已经移动到上传目录，也需要清理
            from app.core.job_status import job_status

            # 从 job_status 获取实际文件路径
            job_info = job_status.get(job_id)
            if job_info:
                real_path = job_info.get("file_path")
                if real_path and os.path.exists(real_path) and real_path != file_path:
                    os.remove(real_path)
                    logger.info(f"Cleaned up moved file: {real_path}")

        except Exception as e:
            logger.error(f"Error cleaning up files for {job_id}: {str(e)}")

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
                status = "completed"
                if not result.get("success"):
                    status = "cancelled" if result.get("cancelled") else "failed"
                return {
                    "status": status,
                    "job_id": job_id,
                    "filename": task_info["filename"],
                    "chunk_count": result.get("chunk_count", 0),
                    "document_id": (
                        result.get("document_id") if result.get("success") else None
                    ),
                    "error": result.get("error"),
                    "submitted_at": task_info["submitted_at"],
                }
        else:
            # 若取消标志已设置，显式返回取消中，避免前端将其视为进行中而反复刷新
            if self._check_cancelled(job_id):
                return {
                    "status": "cancelling",
                    "job_id": job_id,
                    "document_id": None,
                    "filename": task_info["filename"],
                    "submitted_at": task_info["submitted_at"],
                }
            return {
                "status": "processing",
                "job_id": job_id,
                "chunk_count": 0,
                "filename": task_info["filename"],
                "document_id": None,
                "error": None,
                "submitted_at": task_info["submitted_at"],
            }

    def _process_document_safe(
        self,
        job_id: str,
        file_path: str,
        filename: str,
        content_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """安全的文档处理包装器（支持取消）"""
        try:
            from app.core.document_processor import doc_processor
            from app.core.job_status import job_status
            from app.core.vector_store import get_vector_store

            require_document_maintenance()
            logger.info(f"Starting processing for {filename}")

            # 检查点 1: 开始前检查
            if self._check_cancelled(job_id):
                logger.info(f"Task cancelled before start: {job_id}")
                with self._lock:
                    task_info = self.tasks.get(job_id, {})
                self._cleanup_task_files(job_id, task_info)
                job_status.mark_cancelled(job_id, filename=filename)
                return {
                    "success": False,
                    "error": "Task cancelled by user",
                    "cancelled": True,
                }

            # 更新状态
            job_status.mark_processing(job_id, progress=10, message="开始处理文档")

            # 检查点 2: 文件移动前检查
            if self._check_cancelled(job_id):
                logger.info(f"Task cancelled before file move: {job_id}")
                with self._lock:
                    task_info = self.tasks.get(job_id, {})
                self._cleanup_task_files(job_id, task_info)
                job_status.mark_cancelled(job_id, filename=filename)
                return {
                    "success": False,
                    "error": "Task cancelled by user",
                    "cancelled": True,
                }

            # 移动文件到最终目录
            if doc_processor.is_in_temp_dir(file_path):
                real_path = doc_processor.move_to_upload_dir(file_path, filename)
            else:
                real_path = file_path

            # 更新任务信息中的文件路径
            with self._lock:
                if job_id in self.tasks:
                    self.tasks[job_id]["file_path"] = real_path

            job_status.mark_processing(
                job_id, progress=20, message="文件准备完成", file_path=real_path
            )

            # 检查点 3: 文档处理前检查
            if self._check_cancelled(job_id):
                logger.info(f"Task cancelled before document processing: {job_id}")
                with self._lock:
                    task_info = self.tasks.get(job_id, {})
                self._cleanup_task_files(job_id, task_info)
                job_status.mark_cancelled(job_id, filename=filename)
                return {
                    "success": False,
                    "error": "Task cancelled by user",
                    "cancelled": True,
                }

            # 处理文档，传递取消检查函数
            job_status.mark_processing(
                job_id, progress=30, message="正在解析文档内容..."
            )
            result = doc_processor.process_document(
                real_path,
                filename,
                cancel_checker=lambda: self._check_cancelled(job_id),
                content_hash=content_hash,
            )

            # 检查点 4: 文档处理后检查
            if self._check_cancelled(job_id):
                logger.info(f"Task cancelled after document processing: {job_id}")
                with self._lock:
                    task_info = self.tasks.get(job_id, {})
                self._cleanup_task_files(job_id, task_info)
                job_status.mark_cancelled(job_id, filename=filename)
                return {
                    "success": False,
                    "error": "Task cancelled by user",
                    "cancelled": True,
                }

            if result["status"] == "completed":
                # 检查点 5: 向量化前检查
                if self._check_cancelled(job_id):
                    logger.info(f"Task cancelled before vectorization: {job_id}")
                    with self._lock:
                        task_info = self.tasks.get(job_id, {})
                    self._cleanup_task_files(job_id, task_info)
                    job_status.mark_cancelled(job_id, filename=filename)
                    return {
                        "success": False,
                        "error": "Task cancelled by user",
                        "cancelled": True,
                    }

                # 添加到向量存储
                chunks = result.get("chunks", [])
                for chunk in chunks:
                    chunk.metadata["job_id"] = job_id

                job_status.mark_processing(job_id, progress=80, message="生成向量嵌入")
                require_document_maintenance()
                get_vector_store().add_documents(chunks)

                # 最后检查点: 完成前检查
                if self._check_cancelled(job_id):
                    logger.info(f"Task cancelled after vectorization: {job_id}")
                    # 此时向量已存储，需要从向量库删除
                    try:
                        get_vector_store().delete_by_metadata("job_id", job_id)
                    except Exception as ve:
                        logger.error(
                            f"Failed to delete vectors for cancelled task: {ve}"
                        )

                    with self._lock:
                        task_info = self.tasks.get(job_id, {})
                    self._cleanup_task_files(job_id, task_info)
                    job_status.mark_cancelled(job_id, filename=filename)
                    return {
                        "success": False,
                        "error": "Task cancelled by user",
                        "cancelled": True,
                    }

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

        except CancellationError as e:
            # 处理取消异常
            logger.info(f"Document processing cancelled for {filename}: {str(e)}")
            from app.core.job_status import job_status

            with self._lock:
                task_info = self.tasks.get(job_id, {})
            self._cleanup_task_files(job_id, task_info)
            job_status.mark_cancelled(job_id, filename=filename)
            return {
                "success": False,
                "job_id": job_id,
                "document_id": None,
                "error": str(e),
                "cancelled": True,
            }
        except Exception as e:
            logger.error(f"Document processing failed for {filename}: {str(e)}")
            from app.core.job_status import job_status

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
