"""Document loader, storage, and PDF fallback tests."""

import os
import zipfile
from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from app.core.document_processor import (
    DocumentProcessor,
    MarkdownLoader,
    SmartPDFLoader,
    WordDocumentLoader,
)


def test_markdown_loader_reads_content_and_reports_file_errors(tmp_path):
    markdown = tmp_path / "notes.md"
    markdown.write_text("# Heading\n\nUseful content", encoding="utf-8")

    documents = MarkdownLoader(str(markdown)).load()

    assert documents[0].page_content == "# Heading\n\nUseful content"
    assert documents[0].metadata["source"] == str(markdown)

    with pytest.raises(FileNotFoundError):
        MarkdownLoader(str(tmp_path / "missing.md")).load()


def test_word_loader_extracts_docx_xml(tmp_path):
    docx_path = tmp_path / "sample.docx"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r>'
        "<w:t>Hello </w:t><w:t>world</w:t>"
        "</w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    documents = WordDocumentLoader(str(docx_path)).load()

    assert documents[0].page_content == "Hello world"
    assert documents[0].metadata["source"] == str(docx_path)


def test_word_loader_extracts_readable_legacy_doc_content(tmp_path):
    doc_path = tmp_path / "legacy.doc"
    doc_path.write_bytes(b"This is readable legacy document content with details")

    documents = WordDocumentLoader(str(doc_path)).load()

    assert "readable legacy document" in documents[0].page_content


def test_word_loader_rejects_unknown_and_unreadable_formats(tmp_path):
    with pytest.raises(ValueError, match="不支持的文件格式"):
        WordDocumentLoader(str(tmp_path / "sample.rtf")).load()

    empty_doc = tmp_path / "empty.doc"
    empty_doc.write_bytes(b"\x00\x01")
    with pytest.raises(ValueError, match="无法处理.doc格式文件"):
        WordDocumentLoader(str(empty_doc)).load()

    corrupt_docx = tmp_path / "corrupt.docx"
    corrupt_docx.write_bytes(b"not a zip archive")
    with pytest.raises(ValueError, match="无法读取Word文档内容"):
        WordDocumentLoader(str(corrupt_docx)).load()


def test_smart_pdf_loader_initializes_enhanced_processor():
    enhanced = Mock()
    with patch(
        "app.core.enhanced_pdf_processor.EnhancedPDFProcessor",
        return_value=enhanced,
    ):
        loader = SmartPDFLoader("sample.pdf")

    assert loader.enhanced_processor is enhanced


def test_smart_pdf_loader_handles_enhanced_initialization_failure():
    with patch(
        "app.core.enhanced_pdf_processor.EnhancedPDFProcessor",
        side_effect=RuntimeError("optional dependency failed"),
    ):
        loader = SmartPDFLoader("sample.pdf")

    assert loader.enhanced_processor is None


def test_smart_pdf_loader_prefers_enhanced_result():
    expected = [Document(page_content="enhanced content")]
    enhanced = Mock()
    enhanced.get_processing_info.return_value = {"pdf_analysis": {}}
    enhanced.load.return_value = expected
    loader = SmartPDFLoader.__new__(SmartPDFLoader)
    loader.file_path = "sample.pdf"
    loader.enhanced_processor = enhanced

    result = loader.load(cancel_checker=lambda: False)

    assert result == expected
    enhanced.load.assert_called_once()


def test_smart_pdf_loader_falls_back_to_standard_loader():
    expected = [Document(page_content="standard content")]
    enhanced = Mock()
    enhanced.get_processing_info.return_value = {"pdf_analysis": {}}
    enhanced.load.side_effect = RuntimeError("OCR failed")
    standard = Mock()
    standard.load.return_value = expected
    loader = SmartPDFLoader.__new__(SmartPDFLoader)
    loader.file_path = "sample.pdf"
    loader.enhanced_processor = enhanced

    with patch(
        "app.core.document_processor.PyPDFLoader", return_value=standard
    ) as loader_class:
        result = loader.load()

    assert result == expected
    loader_class.assert_called_once_with("sample.pdf")


def test_smart_pdf_loader_reports_scanned_pdf_remediation():
    enhanced = Mock()
    enhanced.get_processing_info.return_value = {
        "pdf_analysis": {"is_scanned": True},
        "ocr_available": False,
    }
    enhanced.load.return_value = []
    standard = Mock()
    standard.load.return_value = [Document(page_content="  ")]
    loader = SmartPDFLoader.__new__(SmartPDFLoader)
    loader.file_path = "scan.pdf"
    loader.enhanced_processor = enhanced

    with patch("app.core.document_processor.PyPDFLoader", return_value=standard):
        with pytest.raises(ValueError, match="Tesseract-OCR"):
            loader.load()


@pytest.mark.parametrize(
    ("processing_info", "expected"),
    [
        (
            {"pdf_analysis": {"is_scanned": True}, "ocr_available": True},
            "OCR功能可用但处理失败",
        ),
        (
            {"pdf_analysis": {"is_scanned": False}, "ocr_available": False},
            "检查PDF是否受密码保护",
        ),
    ],
)
def test_pdf_processing_suggestions_cover_ocr_and_text_failures(
    processing_info, expected
):
    loader = SmartPDFLoader.__new__(SmartPDFLoader)

    assert expected in loader._get_processing_suggestions(processing_info)


@pytest.fixture
def processor():
    return DocumentProcessor()


@pytest.mark.parametrize(
    "filename",
    [
        None,
        "",
        "../secret.txt",
        "folder/file.txt",
        "trailing.txt.",
        "bad\x01.txt",
        "bad?.txt",
        "CON.txt",
    ],
)
def test_validate_filename_rejects_unsafe_names(processor, filename):
    with pytest.raises(ValueError):
        processor.validate_filename(filename)


def test_content_hash_and_storage_filename_are_deterministic_and_safe(processor):
    assert (
        processor.compute_content_hash(b"content")
        == "ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec"
        "9432297b9ec9f73"
    )
    first = processor._generate_storage_filename("Report.PDF")
    second = processor._generate_storage_filename("Report.PDF")
    assert first.endswith(".pdf")
    assert first != second


def test_build_storage_path_rejects_escape(processor, tmp_path):
    with pytest.raises(ValueError, match="Invalid storage path"):
        processor._build_storage_path(str(tmp_path), "../escape.txt")


def test_temp_file_move_and_location_checks(processor, tmp_path):
    temp_dir = tmp_path / "temp"
    upload_dir = tmp_path / "uploads"
    with patch("app.core.document_processor.settings") as settings:
        settings.temp_upload_dir = str(temp_dir)
        settings.upload_dir = str(upload_dir)

        temp_file = processor.save_to_temp_file(b"payload", "report.txt")
        assert processor.is_in_temp_dir(temp_file)

        moved_file = processor.move_to_upload_dir(temp_file, "report.txt")
        assert os.path.exists(moved_file)
        assert not os.path.exists(temp_file)
        assert not processor.is_in_temp_dir(moved_file)


def test_move_renames_when_destination_exists(processor, tmp_path):
    temp_dir = tmp_path / "temp"
    upload_dir = tmp_path / "uploads"
    with patch("app.core.document_processor.settings") as settings:
        settings.temp_upload_dir = str(temp_dir)
        settings.upload_dir = str(upload_dir)
        temp_file = processor.save_to_temp_file(b"new", "report.txt")
        date_dir = upload_dir / os.path.basename(os.path.dirname(temp_file))
        date_dir.mkdir(parents=True, exist_ok=True)
        existing = date_dir / os.path.basename(temp_file)
        existing.write_bytes(b"old")

        moved_file = processor.move_to_upload_dir(temp_file, "report.txt")

    assert moved_file.endswith("_moved.txt")
    assert existing.read_bytes() == b"old"


def test_move_missing_temp_file_and_path_check_error(processor, tmp_path):
    with pytest.raises(FileNotFoundError):
        processor.move_to_upload_dir(str(tmp_path / "missing.txt"), "missing.txt")

    with patch("app.core.document_processor.os.path.commonpath", side_effect=OSError):
        assert processor.is_in_temp_dir("anything") is False


def test_load_pdf_passes_cancel_checker(processor):
    def checker():
        return False

    with patch.object(SmartPDFLoader, "__init__", return_value=None), patch.object(
        SmartPDFLoader, "load", return_value=[Document(page_content="pdf")]
    ) as load:
        result = processor.load_document("sample.pdf", checker)

    assert result[0].page_content == "pdf"
    load.assert_called_once_with(checker)


def test_split_documents_propagates_splitter_error(processor):
    processor.text_splitter = Mock()
    processor.text_splitter.split_documents.side_effect = RuntimeError("split failed")

    with pytest.raises(RuntimeError, match="split failed"):
        processor.split_documents([Document(page_content="content")])


def test_get_document_info_returns_none_for_missing_file(processor, tmp_path):
    assert processor.get_document_info(str(tmp_path / "missing.txt")) is None
