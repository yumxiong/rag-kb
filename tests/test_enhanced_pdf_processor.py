"""Enhanced PDF processing strategy and failure-path tests."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.documents import Document
from PIL import Image

from app.core.enhanced_pdf_processor import (
    EnhancedPDFProcessor,
    install_ocr_dependencies,
)
from app.core.exceptions import CancellationError


@pytest.fixture
def processor():
    with patch.object(
        EnhancedPDFProcessor, "_check_ocr_availability", return_value=True
    ), patch.object(
        EnhancedPDFProcessor,
        "_check_image_extraction_availability",
        return_value=True,
    ):
        return EnhancedPDFProcessor()


def _pdf_info(scanned=False, low_text=False):
    return {
        "total_pages": 1,
        "sample_pages": 1,
        "pages_with_text": 0 if scanned else 1,
        "pages_with_images": 1 if scanned else 0,
        "text_ratio": 0.0 if scanned else 1.0,
        "image_ratio": 1.0 if scanned else 0.0,
        "avg_chars_per_page": 0 if scanned else 300,
        "total_images": 1 if scanned else 0,
        "is_scanned": scanned,
        "low_text_ratio": low_text,
    }


def test_initialization_checks_optional_capabilities():
    with patch.object(
        EnhancedPDFProcessor, "_check_ocr_availability", return_value=False
    ) as check_ocr, patch.object(
        EnhancedPDFProcessor,
        "_check_image_extraction_availability",
        return_value=True,
    ) as check_images:
        instance = EnhancedPDFProcessor()

    assert instance.ocr_available is False
    assert instance.image_extraction_available is True
    check_ocr.assert_called_once_with()
    check_images.assert_called_once_with()


def test_ocr_and_image_availability_success(processor):
    with patch("pytesseract.get_tesseract_version", return_value="5.0"):
        assert processor._check_ocr_availability() is True

    assert processor._check_image_extraction_availability() is True


def test_ocr_availability_handles_engine_failure(processor):
    with patch(
        "pytesseract.get_tesseract_version", side_effect=RuntimeError("missing")
    ):
        assert processor._check_ocr_availability() is False


def test_load_selects_text_or_ocr_strategy(processor):
    text_doc = Document(page_content="text content")
    ocr_doc = Document(page_content="ocr content")

    with patch.object(
        processor, "_analyze_pdf", return_value=_pdf_info()
    ), patch.object(
        processor, "_process_with_text_extraction", return_value=[text_doc]
    ) as text_extract, patch.object(
        processor, "_process_with_ocr", return_value=[ocr_doc]
    ) as ocr:
        assert processor.load("text.pdf") == [text_doc]
        text_extract.assert_called_once()
        ocr.assert_not_called()

    with patch.object(
        processor, "_analyze_pdf", return_value=_pdf_info(scanned=True)
    ), patch.object(
        processor, "_process_with_text_extraction", return_value=[text_doc]
    ) as text_extract, patch.object(
        processor, "_process_with_ocr", return_value=[ocr_doc]
    ) as ocr:
        assert processor.load("scan.pdf") == [ocr_doc]
        ocr.assert_called_once()
        text_extract.assert_not_called()


def test_load_uses_alternate_strategy_when_primary_is_empty(processor):
    recovered = Document(page_content="recovered content")
    empty = Document(page_content="   ")

    with patch.object(
        processor, "_analyze_pdf", return_value=_pdf_info(scanned=True)
    ), patch.object(processor, "_process_with_ocr", return_value=[empty]), patch.object(
        processor, "_process_with_text_extraction", return_value=[recovered]
    ) as fallback:
        assert processor.load("scan.pdf") == [recovered]
        fallback.assert_called_once()

    with patch.object(
        processor, "_analyze_pdf", return_value=_pdf_info()
    ), patch.object(
        processor, "_process_with_text_extraction", return_value=[]
    ), patch.object(
        processor, "_process_with_ocr", return_value=[recovered]
    ) as fallback:
        assert processor.load("text.pdf") == [recovered]
        fallback.assert_called_once()


def test_load_propagates_processing_failure(processor):
    with patch.object(processor, "_analyze_pdf", side_effect=OSError("broken")):
        with pytest.raises(OSError, match="broken"):
            processor.load("bad.pdf")


def test_analyze_pdf_classifies_text_and_scanned_documents(processor):
    text_page = Mock()
    text_page.get_text.return_value = "x" * 300
    text_page.get_images.return_value = []
    text_doc = MagicMock()
    text_doc.__len__.return_value = 1
    text_doc.__getitem__.return_value = text_page

    with patch("app.core.enhanced_pdf_processor.fitz.open", return_value=text_doc):
        text_info = processor._analyze_pdf("text.pdf")

    assert text_info["is_scanned"] is False
    assert text_info["text_ratio"] == 1.0
    text_doc.close.assert_called_once_with()

    image_page = Mock()
    image_page.get_text.return_value = ""
    image_page.get_images.return_value = [(1,)]
    image_doc = MagicMock()
    image_doc.__len__.return_value = 1
    image_doc.__getitem__.return_value = image_page

    with patch("app.core.enhanced_pdf_processor.fitz.open", return_value=image_doc):
        image_info = processor._analyze_pdf("scan.pdf")

    assert image_info["is_scanned"] is True
    assert image_info["total_images"] == 1


def test_analyze_pdf_returns_safe_defaults_on_error(processor):
    with patch(
        "app.core.enhanced_pdf_processor.fitz.open",
        side_effect=RuntimeError("invalid pdf"),
    ):
        result = processor._analyze_pdf("bad.pdf")

    assert result == {
        "total_pages": 0,
        "is_scanned": True,
        "low_text_ratio": True,
    }


def test_text_extraction_cleans_pages_and_skips_empty_content(processor):
    useful_page = Mock()
    useful_page.get_text.return_value = "  Useful   extracted text with detail.  "
    empty_page = Mock()
    empty_page.get_text.return_value = "  "
    document = MagicMock()
    document.__len__.return_value = 2
    document.__getitem__.side_effect = [useful_page, empty_page]

    with patch("app.core.enhanced_pdf_processor.fitz.open", return_value=document):
        result = processor._process_with_text_extraction("text.pdf", _pdf_info())

    assert len(result) == 1
    assert result[0].page_content == "Useful extracted text with detail."
    assert result[0].metadata["extraction_method"] == "text_extraction"
    document.close.assert_called_once_with()


def test_text_extraction_honors_cancellation(processor):
    document = MagicMock()
    document.__len__.return_value = 1

    with patch("app.core.enhanced_pdf_processor.fitz.open", return_value=document):
        with pytest.raises(CancellationError):
            processor._process_with_text_extraction(
                "text.pdf", _pdf_info(), cancel_checker=lambda: True
            )

    document.close.assert_called_once_with()


def test_ocr_unavailable_falls_back_to_text_extraction(processor):
    processor.ocr_available = False
    expected = [Document(page_content="fallback")]
    with patch.object(
        processor, "_process_with_text_extraction", return_value=expected
    ) as fallback:
        result = processor._process_with_ocr("scan.pdf", _pdf_info(scanned=True))

    assert result == expected
    fallback.assert_called_once_with("scan.pdf", _pdf_info(scanned=True))


def test_ocr_processing_builds_document_and_closes_resources(processor):
    page = Mock()
    page.get_text.return_value = "existing"
    pixmap = Mock()
    pixmap.tobytes.return_value = b"png bytes"
    page.get_pixmap.return_value = pixmap
    document = MagicMock()
    document.__len__.return_value = 1
    document.__getitem__.return_value = page
    image = Mock(mode="L")

    with patch(
        "app.core.enhanced_pdf_processor.fitz.open", return_value=document
    ), patch("PIL.Image.open", return_value=image), patch.object(
        processor, "_preprocess_image_for_ocr", return_value=image
    ), patch.object(
        processor,
        "_perform_ocr_with_fallback",
        return_value="recognized text " * 10,
    ):
        result = processor._process_with_ocr("scan.pdf", _pdf_info(scanned=True))

    assert len(result) == 1
    assert result[0].metadata["extraction_method"] == "ocr"
    assert result[0].metadata["has_existing_text"] is True
    image.close.assert_called_once_with()
    document.close.assert_called_once_with()


def test_ocr_processing_honors_early_cancellation(processor):
    document = MagicMock()
    document.__len__.return_value = 1

    with patch("app.core.enhanced_pdf_processor.fitz.open", return_value=document):
        with pytest.raises(CancellationError):
            processor._process_with_ocr(
                "scan.pdf", _pdf_info(scanned=True), cancel_checker=lambda: True
            )

    document.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("existing", "ocr", "expected"),
    [
        ("", "", ""),
        ("", "ocr", "ocr"),
        ("existing", "", "existing"),
        ("existing content", "short", "existing content"),
        ("tiny", "much longer OCR content", "much longer OCR content"),
    ],
)
def test_combine_texts_prefers_best_content(processor, existing, ocr, expected):
    assert processor._combine_texts(existing, ocr) == expected


def test_clean_text_normalizes_whitespace_and_symbols(processor):
    assert processor._clean_text("") == ""
    cleaned = processor._clean_text("  Valid   text!!! \n x \n More@ content  ")
    assert cleaned == "Valid text!!!\nMore content"


def test_processing_info_reports_recommendations(processor):
    processor.ocr_available = False
    info = _pdf_info(scanned=True)
    with patch.object(processor, "_analyze_pdf", return_value=info):
        result = processor.get_processing_info("scan.pdf")

    assert result["recommended_method"] == "ocr"
    assert len(result["processing_notes"]) == 2

    text_info = _pdf_info()
    with patch.object(processor, "_analyze_pdf", return_value=text_info):
        result = processor.get_processing_info("text.pdf")
    assert result["recommended_method"] == "text_extraction"
    assert result["processing_notes"]


def test_processing_info_handles_unexpected_analysis_error(processor):
    with patch.object(processor, "_analyze_pdf", side_effect=RuntimeError("failed")):
        result = processor.get_processing_info("bad.pdf")

    assert result == {"error": "failed", "ocr_available": True}


def test_preprocess_image_returns_grayscale_image(processor):
    image = Image.new("RGB", (8, 8), color="white")

    result = processor._preprocess_image_for_ocr(image)

    assert result.mode == "L"
    assert result.size == (8, 8)


def test_preprocess_image_returns_original_on_dependency_error(processor):
    image = Mock(mode="RGB")
    image.convert.side_effect = RuntimeError("conversion failed")

    assert processor._preprocess_image_for_ocr(image) is image


def test_ocr_fallback_selects_longest_result_and_early_stops(processor):
    long_text = "x" * 301
    with patch("pytesseract.get_languages", return_value=["chi_sim", "eng"]), patch(
        "pytesseract.image_to_string", return_value=long_text
    ) as recognize:
        result = processor._perform_ocr_with_fallback(Mock())

    assert result == long_text
    recognize.assert_called_once()


def test_ocr_fallback_handles_engine_errors_and_cancellation(processor):
    with patch(
        "pytesseract.get_languages", side_effect=RuntimeError("no langs")
    ), patch(
        "pytesseract.image_to_string", side_effect=RuntimeError("timeout")
    ) as recognize:
        assert processor._perform_ocr_with_fallback(Mock()) == ""
    assert recognize.call_count == 4

    with pytest.raises(CancellationError):
        processor._perform_ocr_with_fallback(Mock(), cancel_checker=lambda: True)


def test_install_ocr_dependencies_lists_supported_platforms():
    commands = install_ocr_dependencies()

    assert set(commands) == {"windows", "linux", "macos"}
    assert all(commands[platform] for platform in commands)
