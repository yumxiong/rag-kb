"""
文档处理器测试
"""

import os
import tempfile
from unittest.mock import patch

import pytest

from app.core.document_processor import DocumentProcessor


class TestDocumentProcessor:
    """文档处理器测试类"""

    def setup_method(self):
        """测试前准备"""
        self.processor = DocumentProcessor()

    def test_supported_file_extensions(self):
        """测试支持的文件格式"""
        assert self.processor.is_supported_file("test.pdf")
        assert self.processor.is_supported_file("test.docx")
        assert self.processor.is_supported_file("test.txt")
        assert self.processor.is_supported_file("test.md")
        assert not self.processor.is_supported_file("test.xlsx")
        assert not self.processor.is_supported_file("test.jpg")

    def test_save_uploaded_file(self):
        """测试文件保存功能"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 模拟设置
            with patch("app.core.document_processor.settings") as mock_settings:
                mock_settings.upload_dir = temp_dir

                # 测试保存文件
                content = b"test content"
                filename = "test.txt"

                file_path = self.processor.save_uploaded_file(content, filename)

                # 验证文件是否保存成功
                assert os.path.exists(file_path)
                assert os.path.basename(file_path) != filename
                assert os.path.splitext(os.path.basename(file_path))[1] == ".txt"

                # 验证文件内容
                with open(file_path, "rb") as f:
                    saved_content = f.read()
                assert saved_content == content

    def test_save_uploaded_file_rejects_dangerous_filename(self):
        """测试危险文件名会被拒绝"""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.core.document_processor.settings") as mock_settings:
                mock_settings.upload_dir = temp_dir

                with pytest.raises(ValueError):
                    self.processor.save_uploaded_file(b"x", "../../evil.txt")

    def test_get_document_info(self):
        """测试获取文档信息"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file_path = temp_file.name

        try:
            info = self.processor.get_document_info(temp_file_path)

            assert info is not None
            assert info["filename"] == os.path.basename(temp_file_path)
            assert info["file_type"] == ".txt"
            assert info["file_size"] > 0
            assert info["is_supported"] is True

        finally:
            os.unlink(temp_file_path)

    def test_load_document(self):
        """测试文档加载"""
        # 创建一个临时文件进行真实测试
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as temp_file:
            temp_file.write("test content for loading")
            temp_file_path = temp_file.name

        try:
            # 测试加载
            result = self.processor.load_document(temp_file_path)

            assert len(result) == 1
            assert "test content for loading" in result[0].page_content
            assert "source" in result[0].metadata

        finally:
            os.unlink(temp_file_path)

    def test_load_document_unsupported_format(self):
        """测试不支持的文件格式"""
        with pytest.raises(ValueError, match="Unsupported file type"):
            self.processor.load_document("test.xyz")

    def test_split_documents(self):
        """测试文档分割"""
        from langchain_core.documents import Document

        # 模拟输入文档 - 使用实际的文本分割器
        input_docs = [
            Document(
                page_content=(
                    "This is a long content that should be split into multiple "
                    "chunks. "
                )
                * 20,
                metadata={"source": "test.txt"},
            )
        ]

        # 测试分割
        result = self.processor.split_documents(input_docs)

        # 验证分割结果
        assert len(result) >= 1  # 至少有一个块
        assert all("chunk_index" in chunk.metadata for chunk in result)
        assert all("chunk_id" in chunk.metadata for chunk in result)

        # 验证chunk_index的连续性
        for i, chunk in enumerate(result):
            assert chunk.metadata["chunk_index"] == i
            assert isinstance(chunk.metadata["chunk_id"], str)

    @patch("app.core.document_processor.DocumentProcessor.load_document")
    @patch("app.core.document_processor.DocumentProcessor.split_documents")
    def test_process_document_success(self, mock_split, mock_load):
        """测试成功处理文档"""
        from langchain_core.documents import Document

        # 模拟加载结果
        loaded_docs = [Document(page_content="content", metadata={"page": 1})]
        mock_load.return_value = loaded_docs

        # 模拟分割结果 - 这些chunks应该已经有完整的metadata了
        chunks = [
            Document(
                page_content="chunk 1",
                metadata={
                    "chunk_index": 0,
                    "chunk_id": "test-chunk-1",
                    "document_id": "test-doc-id",
                    "filename": "test.txt",
                },
            ),
            Document(
                page_content="chunk 2",
                metadata={
                    "chunk_index": 1,
                    "chunk_id": "test-chunk-2",
                    "document_id": "test-doc-id",
                    "filename": "test.txt",
                },
            ),
        ]
        mock_split.return_value = chunks

        # 测试处理
        result = self.processor.process_document("test.txt", "test.txt")

        assert result["status"] == "completed"
        assert result["filename"] == "test.txt"
        assert result["chunk_count"] == 2
        assert len(result["chunks"]) == 2
        assert "document_id" in result

        # 验证chunks中添加了文档元数据
        for chunk in result["chunks"]:
            assert "document_id" in chunk.metadata
            assert "filename" in chunk.metadata
            assert chunk.metadata["filename"] == "test.txt"

    @patch("app.core.document_processor.DocumentProcessor.load_document")
    def test_process_document_failure(self, mock_load):
        """测试处理文档失败"""
        # 模拟加载失败
        mock_load.side_effect = Exception("Loading failed")

        # 测试处理
        result = self.processor.process_document("test.txt", "test.txt")

        assert result["status"] == "failed"
        assert result["filename"] == "test.txt"
        assert result["chunk_count"] == 0
        assert len(result["chunks"]) == 0
        assert "Loading failed" in result["error_message"]
