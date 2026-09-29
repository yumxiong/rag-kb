"""
数据模型定义
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class DocumentBase(BaseModel):
    """文档基础模型"""

    filename: str
    file_type: str
    file_size: int


class DocumentCreate(DocumentBase):
    """文档创建模型"""

    pass


class Document(DocumentBase):
    """文档响应模型"""

    id: str
    upload_time: datetime
    status: str  # "processing", "completed", "failed"
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None


class DocumentChunk(BaseModel):
    """文档块模型"""

    id: str
    document_id: str
    chunk_index: int
    content: str
    metadata: dict


class QuestionRequest(BaseModel):
    """问答请求模型"""

    model_config = {"extra": "forbid"}

    question: str = Field(
        ..., min_length=1, max_length=2000, description="用户提问内容"
    )
    max_sources: Optional[int] = Field(
        default=settings.max_sources,
        strict=True,
        ge=settings.min_source_limit,
        le=settings.max_source_limit,
        description="返回的来源文档数量",
    )
    document_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128, description="文档ID"
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, v):
        if not v or not v.strip():
            raise ValueError("question can not be empty")
        if len(v) > 2000:
            raise ValueError("question length can not exceed 2000 characters")
        return v.strip()

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("document_id can not be empty")
        # 检查控制字符
        if any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise ValueError("document_id can not contain control characters")
        # 验证 UUID V4
        try:
            parsed_id = uuid.UUID(v)
        except ValueError:
            raise ValueError("document_id must be a valid UUID format")
        if parsed_id.version != 4:
            raise ValueError("document_id must be a valid version 4 UUID")
        return str(parsed_id)


class SourceDocument(BaseModel):
    """来源文档模型"""

    document_name: str
    content: str
    similarity_score: float
    page_number: Optional[int] = None


class QuestionResponse(BaseModel):
    """问答响应模型"""

    answer: str
    sources: List[SourceDocument]
    processing_time: float
    from_cache: Optional[bool] = False
    request_id: Optional[str] = None


class ApiResponse(BaseModel):
    """通用API响应模型"""

    success: bool
    message: str
    data: Optional[dict] = None


class HealthCheck(BaseModel):
    """健康检查模型"""

    status: str = "healthy"
    timestamp: datetime = datetime.now()
    version: str
