"""
测试任务取消功能
"""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest

from app.core.async_processor import AsyncDocumentProcessor
from app.core.config import settings
from app.core.job_status import JobStatusManager


def _admin_headers() -> dict:
    settings.jwt_secret = "test-jwt-secret"
    exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    token = jwt.encode(
        {
            "sub": settings.admin_username,
            "role": "admin",
            "iat": datetime.now(timezone.utc),
            "exp": exp,
        },
        settings.get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


class TestCancelFunctionality:
    """测试任务取消功能"""

    def test_cancel_task_before_execution(self):
        """测试在任务执行前取消"""
        processor = AsyncDocumentProcessor(max_workers=1)

        # 提交一个任务
        job_id = "test-job-1"
        file_path = "/tmp/test.pdf"
        filename = "test.pdf"

        # 模拟提交任务
        with patch.object(processor.executor, "submit") as mock_submit:
            mock_future = MagicMock()
            mock_future.cancel.return_value = True  # 模拟成功取消
            mock_future.done.return_value = False
            mock_submit.return_value = mock_future

            processor.submit_task(job_id, file_path, filename)

            # 立即取消
            result = processor.cancel_task(job_id)

            assert result["success"] is True
            assert result["status"] == "cancelled"
            assert "未开始执行" in result["message"]

    def test_cancel_task_during_execution(self):
        """测试在任务执行中取消"""
        processor = AsyncDocumentProcessor(max_workers=1)

        job_id = "test-job-2"
        file_path = "/tmp/test.pdf"
        filename = "test.pdf"

        with patch.object(processor.executor, "submit") as mock_submit:
            mock_future = MagicMock()
            mock_future.cancel.return_value = False  # 任务已在执行，无法直接取消
            mock_future.done.return_value = False
            mock_submit.return_value = mock_future

            processor.submit_task(job_id, file_path, filename)

            # 尝试取消
            result = processor.cancel_task(job_id)

            assert result["success"] is True
            assert result["status"] == "cancelling"
            assert "下一个检查点" in result["message"]

    def test_cancel_nonexistent_task(self):
        """测试取消不存在的任务"""
        processor = AsyncDocumentProcessor(max_workers=1)

        result = processor.cancel_task("nonexistent-id")

        assert result["success"] is False
        assert result["status"] == "not_found"
        assert "不存在" in result["message"]

    def test_cancel_completed_task(self):
        """测试取消已完成的任务"""
        processor = AsyncDocumentProcessor(max_workers=1)

        job_id = "test-job-3"
        file_path = "/tmp/test.pdf"
        filename = "test.pdf"

        with patch.object(processor.executor, "submit") as mock_submit:
            mock_future = MagicMock()
            mock_future.done.return_value = True  # 任务已完成
            mock_submit.return_value = mock_future

            processor.submit_task(job_id, file_path, filename)

            # 尝试取消
            result = processor.cancel_task(job_id)

            assert result["success"] is False
            assert result["status"] == "already_done"
            assert "已完成" in result["message"]

    def test_check_cancelled_flag(self):
        """测试取消标志检查"""
        processor = AsyncDocumentProcessor(max_workers=1)

        job_id = "test-job-4"

        # 创建取消标志
        cancel_event = threading.Event()
        processor._cancel_flags[job_id] = cancel_event

        # 初始状态：未取消
        assert processor._check_cancelled(job_id) is False

        # 设置取消标志
        cancel_event.set()

        # 检查：已取消
        assert processor._check_cancelled(job_id) is True

    def test_job_status_mark_cancelled(self):
        """测试作业状态标记为已取消"""
        import tempfile

        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            job_manager = JobStatusManager(base_dir=tmpdir)

            job_id = "test-job-1"
            filename = "test.pdf"

            # 初始化作业
            job_manager.init_job(job_id, filename)

            # 标记为已取消
            job_manager.mark_cancelled(job_id, filename=filename)

            # 验证状态
            status = job_manager.get(job_id)
            assert status is not None
            assert status["status"] == "cancelled"
            assert status["progress"] == 100
            assert "cancelled_at" in status
            assert status["message"] == "Task cancelled by user"


class TestCancelIntegration:
    """集成测试：测试取消功能的完整流程"""

    @pytest.mark.asyncio
    async def test_cancel_api_endpoint(self):
        """测试取消API端点"""
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        # 测试取消不存在的任务
        response = client.post(
            "/api/documents/cancel/nonexistent-id",
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is False
        assert result["job_id"] == "nonexistent-id"
        assert result["document_id"] is None

    @pytest.mark.asyncio
    async def test_cancel_status_endpoint(self):
        """测试取消状态查询端点"""
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        # 测试查询不存在的任务
        response = client.get(
            "/api/documents/cancel-status/nonexistent-id",
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is False
        assert result["cancellable"] is False
        assert result["job_id"] == "nonexistent-id"
        assert result["document_id"] is None
