"""
作业状态持久化（最小实现）
- 将每个异步处理任务（job_id 对应的作业）以 JSON 文件存储在 settings.job_status_dir
- 提供 init / update / mark_completed / mark_failed / get 等基础方法
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class JobStatusManager:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or settings.job_status_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, job_id: str) -> str:
        safe_id = "".join(c for c in job_id if c.isalnum() or c in ("-", "_"))
        return os.path.join(self.base_dir, f"{safe_id}.json")

    def _now(self) -> str:
        return datetime.now().isoformat()

    def init_job(
        self, job_id: str, filename: str, extra: Optional[Dict[str, Any]] = None
    ):
        data = {
            "job_id": job_id,
            "document_id": None,
            "filename": filename,
            "status": "processing",
            "progress": 0,
            "message": "Job created",
            "created_at": self._now(),
            "last_updated": self._now(),
        }
        if extra:
            data.update(extra)
        self._write(job_id, data)

    def update(self, job_id: str, **kwargs):
        data = self.get(job_id) or {"job_id": job_id, "document_id": None}
        data.update(kwargs)
        data["last_updated"] = self._now()
        self._write(job_id, data)

    def mark_processing(
        self,
        job_id: str,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        **kwargs,
    ):
        payload = {"status": "processing"}
        if progress is not None:
            payload["progress"] = int(max(0, min(99, progress)))
        if message:
            payload["message"] = message
        payload.update(kwargs)
        self.update(job_id, **payload)

    def mark_completed(self, job_id: str, chunk_count: int = 0, **kwargs):
        payload = {
            "status": "completed",
            "progress": 100,
            "message": "Processing completed",
            "completed_at": self._now(),
            "chunk_count": int(chunk_count),
        }
        payload.update(kwargs)
        self.update(job_id, **payload)

    def mark_failed(self, job_id: str, error: str, **kwargs):
        payload = {
            "status": "failed",
            "progress": 100,
            "message": "Processing failed",
            "error": error,
            "failed_at": self._now(),
        }
        payload.update(kwargs)
        self.update(job_id, **payload)

    def mark_cancelled(self, job_id: str, **kwargs):
        """标记任务已取消"""
        payload = {
            "status": "cancelled",
            "progress": 100,
            "message": "Task cancelled by user",
            "cancelled_at": self._now(),
        }
        payload.update(kwargs)
        self.update(job_id, **payload)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(job_id)
        try:
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read job status {job_id}: {e}")
            return None

    # 兼容旧调用别名
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.get(job_id)

    def _write(self, job_id: str, data: Dict[str, Any]):
        path = self._path(job_id)
        try:
            with self._lock:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to write job status {job_id}: {e}")


# 全局实例
job_status = JobStatusManager()
