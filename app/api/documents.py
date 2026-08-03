"""
文档管理API
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.api.auth import require_admin
from app.core.async_processor import async_processor
from app.core.config import settings
from app.core.document_processor import DocumentProcessor
from app.core.job_status import job_status
from app.core.vector_store import VectorStore
from app.models.schemas import Document

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局实例（延迟初始化）
doc_processor = DocumentProcessor()
vector_store = None


def get_vector_store():
    """获取向量存储实例（延迟初始化）"""
    global vector_store
    if vector_store is None:
        vector_store = VectorStore()
    return vector_store


@router.post("/upload-async")
async def upload_document_async(
    file: UploadFile = File(...), _: dict = Depends(require_admin)
):
    """真正的异步上传（线程池版本）"""
    try:
        display_filename = doc_processor.validate_filename(file.filename)

        # 检查文件类型
        if not doc_processor.is_supported_file(display_filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported file type. Supported types: "
                    f"{list(doc_processor.supported_extensions)}"
                ),
            )

        # 检查文件大小
        file_content = await file.read()
        max_size_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(file_content) > max_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    "File size too large. Maximum size is "
                    f"{settings.max_file_size_mb}MB."
                ),
            )

        content_hash = doc_processor.compute_content_hash(file_content)

        # 高效重复检查（按内容哈希）
        if get_vector_store().document_exists_by_content_hash(content_hash):
            raise HTTPException(
                status_code=409,
                detail="Document with identical content already exists.",
            )

        # 保存到临时目录
        temp_path = doc_processor.save_to_temp_file(file_content, display_filename)

        # 生成任务ID
        job_id = str(uuid.uuid4())

        # 初始化作业状态
        job_status.init_job(
            job_id,
            display_filename,
            {
                "processing_mode": "async_thread",
                "stage": "queued",
                "content_hash": content_hash,
            },
        )
        # 提交到线程池（立即返回）
        async_processor.submit_task(job_id, temp_path, display_filename, content_hash)

        return {
            "success": True,
            "message": "文件上传成功，已加入处理队列",
            "job_id": job_id,
            "document_id": None,
            "status": "queued",
            "processing_mode": "async",
            "filename": display_filename,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Upload failed")


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    async_processing: bool = False,  # 保持原有同步处理作为选项
    _: dict = Depends(require_admin),
):
    """上传文档（兼容原有接口）"""
    try:
        display_filename = doc_processor.validate_filename(file.filename)

        # 检查文件类型
        if not doc_processor.is_supported_file(display_filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported file type. Supported types: "
                    f"{list(doc_processor.supported_extensions)}"
                ),
            )

        # 检查文件大小
        file_content = await file.read()
        max_size_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(file_content) > max_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    "File size too large. Maximum size is "
                    f"{settings.max_file_size_mb}MB."
                ),
            )

        content_hash = doc_processor.compute_content_hash(file_content)

        # 高效重复检查（按内容哈希）
        if get_vector_store().document_exists_by_content_hash(content_hash):
            raise HTTPException(
                status_code=409,
                detail="Document with identical content already exists.",
            )

        initial_document_id = str(uuid.uuid4())
        file_ext = os.path.splitext(display_filename)[1].lower()

        # 创建文档记录
        doc_record = Document(
            id=initial_document_id,
            filename=display_filename,
            file_type=file_ext,
            file_size=len(file_content),
            upload_time=datetime.now(),
            status="processing",
            chunk_count=None,
        )

        if async_processing:
            # 异步处理：立即返回，后台处理
            # 异步处理使用临时目录写入，后台搬迁
            temp_path = doc_processor.save_to_temp_file(file_content, display_filename)
            # 生成 job_id 并初始化作业
            job_id = str(uuid.uuid4())
            try:
                job_status.init_job(
                    job_id,
                    display_filename,
                    {
                        "processing_mode": "async",
                        "stage": "uploaded",
                        "content_hash": content_hash,
                    },
                )
            except Exception:
                pass
            doc_record.id = job_id
            background_tasks.add_task(
                process_document_background,
                temp_path,
                display_filename,
                job_id,
                content_hash,
            )

            return {
                "success": True,
                "message": (
                    "File uploaded successfully and processing started " "in background"
                ),
                "document": doc_record,
                "job_id": job_id,
                "document_id": None,
                "processing_mode": "async",
            }
        else:
            # 同步处理：先写入最终目录，再执行解析与向量化
            file_path = doc_processor.save_uploaded_file(file_content, display_filename)
            file_info = doc_processor.get_document_info(file_path)
            if not file_info:
                raise HTTPException(
                    status_code=500, detail="Failed to get file information"
                )

            doc_record.file_type = file_info["file_type"]
            doc_record.file_size = file_info["file_size"]

            # 同步处理：等待完成后返回
            logger.info(f"Processing document: {display_filename}")
            result = doc_processor.process_document(
                file_path, display_filename, content_hash=content_hash
            )

            if result["status"] == "completed":
                # 添加到向量存储
                get_vector_store().add_documents(result["chunks"])
                doc_record.status = "completed"
                doc_record.chunk_count = result["chunk_count"]
                doc_record.id = result["document_id"]
                logger.info(f"Document {display_filename} processed successfully")

                return {
                    "success": True,
                    "message": "File uploaded and processed successfully",
                    "document": doc_record,
                    "document_id": result["document_id"],
                    "chunk_count": result["chunk_count"],
                    "status": result["status"],
                    "processing_mode": "sync",
                }
            else:
                doc_record.status = "failed"
                logger.error(
                    f"Document processing failed: {result.get('error_message')}"
                )
                return {
                    "success": False,
                    "message": (
                        "Document processing failed: " f"{result.get('error_message')}"
                    ),
                    "document": doc_record,
                    "processing_mode": "sync",
                }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail="Upload failed")


async def process_document_background(
    file_path: str,
    filename: str,
    job_id: Optional[str] = None,
    content_hash: Optional[str] = None,
):
    """后台处理文档"""
    try:
        logger.info(f"Processing document: {filename} (job_id: {job_id})")
        try:
            if job_id:
                job_status.mark_processing(job_id, progress=1, message="Job started")
        except Exception:
            pass

        # 如果路径位于临时目录，先搬迁到最终上传目录
        try:
            if doc_processor.is_in_temp_dir(file_path):
                real_path = doc_processor.move_to_upload_dir(file_path, filename)
            else:
                real_path = file_path
            try:
                if job_id:
                    job_status.mark_processing(
                        job_id,
                        progress=10,
                        message="File moved to upload dir",
                        file_path=real_path,
                    )
            except Exception:
                pass
        except Exception as move_err:
            logger.error(f"Failed to move temp file before processing: {move_err}")
            real_path = file_path

        # 处理文档
        try:
            if job_id:
                job_status.mark_processing(
                    job_id, progress=15, message="Processing document"
                )
        except Exception:
            pass
        result = doc_processor.process_document(
            real_path, filename, content_hash=content_hash
        )

        if result["status"] == "completed":
            real_document_id = result.get("document_id")

            # 添加 job_id 到 chunks 元数据
            if job_id:
                for chunk in result["chunks"]:
                    chunk.metadata["job_id"] = job_id

            # 添加到向量存储
            get_vector_store().add_documents(result["chunks"])
            logger.info(
                f"Document {filename} processed successfully "
                f"(job_id: {job_id}, document_id: {real_document_id})"
            )
            try:
                if job_id:
                    job_status.mark_completed(
                        job_id,
                        chunk_count=result.get("chunk_count", 0),
                        filename=filename,
                        processed_at=datetime.now().isoformat(),
                        document_id=real_document_id,
                    )
            except Exception:
                pass
        else:
            logger.error(
                f"Document processing failed (job_id: {job_id}): "
                f"{result.get('error_message')}"
            )
            try:
                if job_id:
                    job_status.mark_failed(
                        job_id,
                        error=result.get("error_message", "Unknown error"),
                        filename=filename,
                    )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error in background processing (job_id: {job_id}): {str(e)}")
        try:
            if job_id:
                job_status.mark_failed(job_id, error=str(e), filename=filename)
        except Exception:
            pass


@router.get("/status/{job_id}")
async def get_processing_status(job_id: str, _: dict = Depends(require_admin)):
    """获取处理状态（线程池版本）"""
    try:
        # 先检查线程池状态
        thread_status = async_processor.get_task_status(job_id)
        if thread_status:
            return thread_status

        # 回退到job_status检查
        status_info = job_status.get_job_status(job_id)
        if not status_info:
            #  raise HTTPException(status_code=404, detail="Document not found")
            return {
                "status": "not_found",
                "message": "Job not found",
                "job_id": job_id,
                "document_id": None,
            }
        return status_info

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/stream/{job_id}")
async def stream_processing_status(job_id: str, _: dict = Depends(require_admin)):
    """SSE流式状态推送"""

    async def event_generator():
        try:
            retry_count = 0
            max_retries = 200  # 最多重试200次（5分钟），适应大型扫描版PDF的OCR处理

            while retry_count < max_retries:
                # 复用现有状态查询逻辑
                status = async_processor.get_task_status(job_id)
                if not status:
                    status = job_status.get_job_status(job_id)

                if status:
                    yield f"data: {json.dumps(status)}\n\n"

                    # 处理完成、失败或取消中时结束流（取消请求已发出即可结束SSE，避免前端长连接导致闪烁）
                    if status.get("status") in [
                        "completed",
                        "failed",
                        "cancelled",
                        "cancelling",
                    ]:
                        break
                else:
                    # 如果找不到状态，可能是刚提交还没开始处理，继续等待
                    waiting = {
                        "status": "waiting",
                        "message": "Waiting for processing to start...",
                        "job_id": job_id,
                        "document_id": None,
                    }
                    yield f"data: {json.dumps(waiting)}\n\n"

                await asyncio.sleep(1.5)  # 1.5秒轮询间隔
                retry_count += 1

            # 超时后发送超时状态
            if retry_count >= max_retries:
                timeout = {
                    "status": "timeout",
                    "message": "Status check timeout",
                    "job_id": job_id,
                    "document_id": None,
                }
                yield f"data: {json.dumps(timeout)}\n\n"

        except Exception as e:
            logger.error(f"SSE stream error for job {job_id}: {str(e)}")
            error = {
                "status": "error",
                "message": str(e),
                "job_id": job_id,
                "document_id": None,
            }
            yield f"data: {json.dumps(error)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/", response_model=List[Document])
async def list_documents(_: dict = Depends(require_admin)):
    """获取文档列表"""
    try:
        documents = get_vector_store().list_documents()

        # 转换为Document模型
        doc_list = []
        for doc_info in documents:
            doc = Document(
                id=doc_info["document_id"],
                filename=doc_info["filename"],
                file_type=os.path.splitext(doc_info["filename"])[1],
                file_size=0,  # 这里我们没有存储文件大小信息
                upload_time=(
                    datetime.fromisoformat(doc_info["processed_at"])
                    if doc_info.get("processed_at")
                    else datetime.now()
                ),
                status="completed",
                chunk_count=doc_info["chunk_count"],
            )
            doc_list.append(doc)

        return doc_list

    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list documents: {str(e)}"
        )


@router.get("/library")
async def list_library():
    """公开的只读知识库目录（用于首页展示，不返回ID等敏感字段）"""
    try:
        documents = get_vector_store().list_documents()
        library = []
        for doc_info in documents:
            filename = doc_info.get("filename", "")
            library.append(
                {
                    "filename": filename,
                    "file_type": os.path.splitext(filename)[1].lstrip(".") or "file",
                    "chunk_count": doc_info.get("chunk_count", 0),
                }
            )
        # 按文件名稳定排序，便于前端展示
        library.sort(key=lambda x: x["filename"].lower())
        return {
            "documents": library,
            "total": len(library),
        }
    except Exception as e:
        logger.error(f"Error listing library: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list library: {str(e)}")


@router.get("/{document_id}")
async def get_document(document_id: str, _: dict = Depends(require_admin)):
    """获取文档详情"""
    try:
        documents = get_vector_store().list_documents()

        # 查找指定文档
        doc_info = None
        for doc in documents:
            if doc["document_id"] == document_id:
                doc_info = doc
                break

        if not doc_info:
            raise HTTPException(status_code=404, detail="Document not found")

        return {"success": True, "document": doc_info}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document {document_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get document: {str(e)}")


@router.delete("/{document_id}")
async def delete_document(document_id: str, _: dict = Depends(require_admin)):
    """删除文档（包括向量数据和物理文件）"""
    try:
        # 先获取文档摘要信息（包含文件路径）
        doc_summary = get_vector_store().get_summary_by_document_id(document_id)
        if not doc_summary:
            raise HTTPException(status_code=404, detail="Document not found")

        file_path = doc_summary.get("file_path")
        filename = doc_summary.get("filename", "unknown")

        # 从向量存储中删除
        vectors_deleted = get_vector_store().delete_document_by_id(document_id)

        if not vectors_deleted:
            raise HTTPException(
                status_code=404, detail="Document not found in vector store"
            )

        # 删除物理文件
        file_deleted = False
        file_error = None
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True
                logger.info(f"Deleted physical file: {file_path}")
            except Exception as e:
                file_error = str(e)
                logger.error(f"Failed to delete file {file_path}: {file_error}")
        elif file_path:
            # 文件路径存在但文件不存在
            logger.warning(f"File not found at path: {file_path}")
            file_deleted = False
            file_error = "File not found"

        # 构造返回消息
        if file_deleted:
            message = (
                f"Document {filename} deleted successfully (vectors and file removed)"
            )
        elif file_error:
            message = (
                f"Document {filename} vectors deleted, but file removal failed: "
                f"{file_error}"
            )
        else:
            message = (
                f"Document {filename} deleted successfully (vectors only, no file path)"
            )

        return {
            "success": True,
            "message": message,
            "details": {
                "vectors_deleted": vectors_deleted,
                "file_deleted": file_deleted,
                "file_path": file_path,
                "error": file_error,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document {document_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete document: {str(e)}"
        )


@router.post("/batch-upload")
async def batch_upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    _: dict = Depends(require_admin),
):
    """批量上传文档"""
    try:
        if len(files) > 10:
            raise HTTPException(
                status_code=400, detail="Too many files. Maximum is 10 files per batch."
            )

        results = []
        seen_hashes = set()

        for file in files:
            try:
                display_filename = doc_processor.validate_filename(file.filename)

                # 检查文件类型
                if not doc_processor.is_supported_file(display_filename):
                    results.append(
                        {
                            "filename": display_filename,
                            "success": False,
                            "error": "Unsupported file type",
                        }
                    )
                    continue

                file_content = await file.read()
                max_size_bytes = settings.max_file_size_mb * 1024 * 1024
                if len(file_content) > max_size_bytes:
                    results.append(
                        {
                            "filename": display_filename,
                            "success": False,
                            "error": (
                                "File size too large. Maximum size is "
                                f"{settings.max_file_size_mb}MB."
                            ),
                        }
                    )
                    continue

                content_hash = doc_processor.compute_content_hash(file_content)

                if content_hash in seen_hashes:
                    results.append(
                        {
                            "filename": display_filename,
                            "success": False,
                            "error": "Document with identical content already exists",
                        }
                    )
                    continue

                # 高效重复检查（按内容哈希）
                if get_vector_store().document_exists_by_content_hash(content_hash):
                    results.append(
                        {
                            "filename": display_filename,
                            "success": False,
                            "error": "Document with identical content already exists",
                        }
                    )
                    continue

                # 保存到临时目录，后台搬迁再处理
                temp_path = doc_processor.save_to_temp_file(
                    file_content, display_filename
                )
                seen_hashes.add(content_hash)

                # 后台处理
                background_tasks.add_task(
                    process_document_background,
                    temp_path,
                    display_filename,
                    None,
                    content_hash,
                )

                results.append(
                    {
                        "filename": display_filename,
                        "success": True,
                        "message": "Upload successful, processing started",
                    }
                )
            except ValueError as e:
                results.append(
                    {"filename": file.filename, "success": False, "error": str(e)}
                )

            except Exception as e:
                results.append(
                    {"filename": file.filename, "success": False, "error": str(e)}
                )

        return {
            "success": True,
            "message": f"Processed {len(files)} files",
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch upload failed: {str(e)}")


@router.get("/stats/overview")
async def get_stats(_: dict = Depends(require_admin)):
    """获取文档统计信息"""
    try:
        collection_info = get_vector_store().get_collection_info()
        documents = get_vector_store().list_documents()

        # 检查OCR能力（若缺少依赖则降级）
        ocr_available = False
        image_processing_available = False
        enhanced_pdf_processing = False
        try:
            from app.core.enhanced_pdf_processor import EnhancedPDFProcessor

            pdf_processor = EnhancedPDFProcessor()
            ocr_available = getattr(pdf_processor, "ocr_available", False)
            image_processing_available = getattr(
                pdf_processor, "image_extraction_available", False
            )
            enhanced_pdf_processing = True
        except Exception as e:
            logger.warning(f"Enhanced PDF processor unavailable: {e}")

        stats = {
            "total_documents": len(documents),
            "total_chunks": collection_info.get("document_count", 0),
            "supported_formats": list(doc_processor.supported_extensions),
            "processing_capabilities": {
                "ocr_available": ocr_available,
                "image_processing_available": image_processing_available,
                "enhanced_pdf_processing": enhanced_pdf_processing,
            },
            "storage_info": {
                "upload_dir": settings.upload_dir,
                "chroma_db_path": settings.chroma_db_path,
                "max_file_size_mb": settings.max_file_size_mb,
            },
        }

        return stats

    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/pdf-info/{document_id}")
async def get_pdf_info(document_id: str, _: dict = Depends(require_admin)):
    """获取PDF文档的详细分析信息"""
    try:
        # 查找文档
        documents = get_vector_store().list_documents()
        doc_info = None
        for doc in documents:
            if doc["document_id"] == document_id:
                doc_info = doc
                break

        if not doc_info:
            raise HTTPException(status_code=404, detail="Document not found")

        # 如果是PDF文档，提供详细分析
        filename = doc_info.get("filename", "")
        if filename.lower().endswith(".pdf"):
            # 尝试找到文件路径（这里简化处理，实际可能需要更复杂的查找逻辑）
            file_path = doc_info.get("file_path")
            if not (file_path and os.path.exists(file_path)):
                return {"success": False, "message": "PDF文件路径未找到或文件已移动"}
            try:
                from app.core.enhanced_pdf_processor import EnhancedPDFProcessor

                pdf_processor = EnhancedPDFProcessor()
                processing_info = pdf_processor.get_processing_info(file_path)
                return {
                    "success": True,
                    "document_id": document_id,
                    "filename": filename,
                    "processing_info": processing_info,
                }
            except Exception as e:
                logger.warning(f"Enhanced PDF analysis unavailable: {e}")
                return {
                    "success": False,
                    "message": "增强型PDF分析不可用（缺少依赖或处理器不可用）",
                }
        else:
            return {"success": False, "message": "该文档不是PDF格式"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting PDF info for {document_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get PDF info: {str(e)}")


@router.post("/cancel/{job_id}")
async def cancel_document_processing(job_id: str, _: dict = Depends(require_admin)):
    """
    取消正在处理的文档任务

    Args:
        job_id: 异步任务ID

    Returns:
        取消结果，包含成功状态和消息
    """
    try:
        logger.info(f"Received cancel request for job: {job_id}")

        # 调用异步处理器的取消方法
        result = async_processor.cancel_task(job_id)

        if result["success"]:
            logger.info(f"Successfully cancelled task: {job_id}")
            return {
                "success": True,
                "message": result["message"],
                "job_id": job_id,
                "document_id": None,
                "status": result["status"],
            }
        else:
            logger.warning(f"Failed to cancel task {job_id}: {result['message']}")
            return {
                "success": False,
                "message": result["message"],
                "job_id": job_id,
                "document_id": None,
                "status": result["status"],
            }

    except Exception as e:
        logger.error(f"Error cancelling document processing for {job_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cancel document processing: {str(e)}"
        )


@router.get("/cancel-status/{job_id}")
async def get_cancel_status(job_id: str, _: dict = Depends(require_admin)):
    """
    查询任务是否可以取消

    Args:
        job_id: 异步任务ID

    Returns:
        任务状态信息，包括是否可以取消
    """
    try:
        # 从 job_status 获取任务状态
        job_info = job_status.get(job_id)

        if not job_info:
            return {
                "success": False,
                "message": "任务不存在",
                "job_id": job_id,
                "document_id": None,
                "cancellable": False,
            }

        status = job_info.get("status", "unknown")

        # 只有 processing 状态的任务可以取消
        cancellable = status == "processing"

        return {
            "success": True,
            "job_id": job_id,
            "document_id": job_info.get("document_id"),
            "status": status,
            "cancellable": cancellable,
            "progress": job_info.get("progress", 0),
            "message": job_info.get("message", ""),
        }

    except Exception as e:
        logger.error(f"Error getting cancel status for {job_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get cancel status: {str(e)}"
        )
