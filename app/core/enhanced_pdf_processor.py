"""
增强的PDF处理器，支持OCR和多种处理策略
适用于扫描类PDF和复杂格式的PDF文档
"""

import io
import logging
from typing import Any, Callable, Dict, List, Optional

import fitz  # PyMuPDF
from langchain_core.documents import Document

from app.core.exceptions import CancellationError

logger = logging.getLogger(__name__)

# 单次 OCR 尝试的超时（秒），避免长时间卡住导致无法及时响应取消
OCR_ATTEMPT_TIMEOUT_SEC = 10


class EnhancedPDFProcessor:
    """增强的PDF处理器类"""

    def __init__(self):
        self.ocr_available = self._check_ocr_availability()
        self.image_extraction_available = self._check_image_extraction_availability()

    def _check_ocr_availability(self) -> bool:
        """检查OCR库是否可用"""
        try:
            import PIL.Image
            import pytesseract

            # 尝试检测Tesseract是否正确安装
            pytesseract.get_tesseract_version()
            logger.debug("PIL image module loaded: %s", PIL.Image.__name__)
            logger.info("OCR功能可用 (Tesseract + PIL)")
            return True
        except Exception as e:
            logger.warning(f"OCR功能不可用: {str(e)}")
            logger.info(
                "提示：安装 'pip install pytesseract pillow' 并安装Tesseract-OCR以启用OCR功能"
            )
            return False

    def _check_image_extraction_availability(self) -> bool:
        """检查图像提取库是否可用"""
        try:
            import PIL.Image

            logger.info("图像处理功能可用 (PIL)")
            return PIL.Image is not None
        except ImportError:
            logger.warning("图像处理功能不可用，请安装: pip install pillow")
            return False

    def load(
        self, file_path: str, cancel_checker: Optional[Callable[[], bool]] = None
    ) -> List[Document]:
        """
        加载PDF文档，自动选择最佳处理策略

        Args:
            file_path: PDF文件路径
            cancel_checker: 取消检查函数，返回True表示需要取消
        """
        try:
            # 分析PDF特性
            pdf_info = self._analyze_pdf(file_path)
            logger.info(f"PDF分析结果: {pdf_info}")

            # 根据PDF特性选择处理策略
            documents = []

            if pdf_info["is_scanned"] or pdf_info["low_text_ratio"]:
                logger.info("检测到扫描类PDF或低文本比例，尝试OCR处理")
                documents = self._process_with_ocr(file_path, pdf_info, cancel_checker)
            else:
                logger.info("检测到文本类PDF，使用标准文本提取")
                documents = self._process_with_text_extraction(
                    file_path, pdf_info, cancel_checker
                )

            # 如果主要方法失败，尝试备用方法
            if not documents or all(not doc.page_content.strip() for doc in documents):
                logger.warning("主要方法提取失败，尝试备用方法")
                if pdf_info["is_scanned"]:
                    documents = self._process_with_text_extraction(
                        file_path, pdf_info, cancel_checker
                    )
                else:
                    documents = self._process_with_ocr(
                        file_path, pdf_info, cancel_checker
                    )

            return documents

        except Exception as e:
            logger.error(f"处理PDF文件失败 {file_path}: {str(e)}")
            raise

    def _analyze_pdf(self, file_path: str) -> Dict[str, Any]:
        """
        分析PDF文档特性，判断是否为扫描类PDF
        """
        try:
            doc = fitz.open(file_path)

            total_chars = 0
            total_images = 0
            pages_with_images = 0
            pages_with_text = 0
            total_pages = len(doc)

            # 采样分析（最多检查前10页）
            sample_pages = min(10, total_pages)

            for page_num in range(sample_pages):
                page = doc[page_num]

                # 统计文本字符
                text = page.get_text()
                char_count = len(text.strip())
                total_chars += char_count

                if char_count > 10:  # 有意义的文本
                    pages_with_text += 1

                # 统计图像
                image_list = page.get_images()
                if image_list:
                    total_images += len(image_list)
                    pages_with_images += 1

            doc.close()

            # 计算比例
            text_ratio = pages_with_text / sample_pages if sample_pages > 0 else 0
            image_ratio = pages_with_images / sample_pages if sample_pages > 0 else 0
            avg_chars_per_page = total_chars / sample_pages if sample_pages > 0 else 0

            # 判断是否为扫描类PDF
            is_scanned = (
                text_ratio < 0.3  # 少于30%的页面有文本
                or avg_chars_per_page < 100  # 平均每页少于100个字符
                or (image_ratio > 0.8 and text_ratio < 0.5)  # 多数页面是图像且文本少
            )

            low_text_ratio = text_ratio < 0.5 and avg_chars_per_page < 200

            return {
                "total_pages": total_pages,
                "sample_pages": sample_pages,
                "pages_with_text": pages_with_text,
                "pages_with_images": pages_with_images,
                "text_ratio": text_ratio,
                "image_ratio": image_ratio,
                "avg_chars_per_page": avg_chars_per_page,
                "total_images": total_images,
                "is_scanned": is_scanned,
                "low_text_ratio": low_text_ratio,
            }

        except Exception as e:
            logger.error(f"分析PDF失败: {str(e)}")
            return {
                "total_pages": 0,
                "is_scanned": True,  # 出错时默认尝试OCR
                "low_text_ratio": True,
            }

    def _process_with_text_extraction(
        self,
        file_path: str,
        pdf_info: Dict,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> List[Document]:
        """
        使用文本提取方法处理PDF
        """
        try:
            doc = fitz.open(file_path)
            documents = []

            for page_num in range(len(doc)):
                # 支持快速取消
                if cancel_checker and cancel_checker():
                    doc.close()
                    raise CancellationError(
                        f"任务在文本提取第{page_num+1}页时被用户取消"
                    )

                page = doc[page_num]
                text = page.get_text()

                if text.strip():  # 只处理有文本的页面
                    # 清理和格式化文本
                    cleaned_text = self._clean_text(text)

                    if len(cleaned_text.strip()) > 10:  # 降低过滤阈值
                        document = Document(
                            page_content=cleaned_text,
                            metadata={
                                "source": file_path,
                                "page": page_num + 1,
                                "extraction_method": "text_extraction",
                                "total_pages": len(doc),
                            },
                        )
                        documents.append(document)

            doc.close()
            logger.info(f"文本提取完成: {len(documents)} 页")
            return documents

        except Exception as e:
            logger.error(f"文本提取失败: {str(e)}")
            raise

    def _process_with_ocr(
        self,
        file_path: str,
        pdf_info: Dict,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> List[Document]:
        """
        使用OCR方法处理PDF（适用于扫描类PDF）

        Args:
            file_path: PDF文件路径
            pdf_info: PDF分析信息
            cancel_checker: 取消检查函数，返回True表示需要取消
        """
        if not self.ocr_available:
            logger.warning("OCR功能不可用，回退到文本提取")
            return self._process_with_text_extraction(file_path, pdf_info)

        try:
            from PIL import Image

            doc = fitz.open(file_path)
            documents = []

            for page_num in range(len(doc)):
                # 检查取消标志
                if cancel_checker and cancel_checker():
                    logger.info(f"OCR处理在第{page_num+1}页被取消")
                    doc.close()
                    raise CancellationError(
                        f"任务在OCR处理第{page_num+1}页时被用户取消"
                    )

                page = doc[page_num]

                # 首先尝试提取现有文本
                existing_text = page.get_text().strip()

                # 渲染为灰度图像，优先使用约300DPI（3.0缩放），不足时再提升
                ocr_text = ""
                cleaned_text = ""
                for zoom in (3.0, 4.0):
                    # 取消检查：每个放大步开始前
                    if cancel_checker and cancel_checker():
                        doc.close()
                        raise CancellationError(
                            f"任务在OCR放大处理阶段被用户取消 (zoom={zoom})"
                        )

                    # 将页面转换为灰度图像（alpha关闭以减少噪声与体积）
                    mat = fitz.Matrix(zoom, zoom)

                    # 取消检查：渲染前
                    if cancel_checker and cancel_checker():
                        doc.close()
                        raise CancellationError(
                            f"任务在OCR图像渲染前被用户取消 (zoom={zoom})"
                        )

                    pix = page.get_pixmap(
                        matrix=mat, colorspace=fitz.csGRAY, alpha=False
                    )
                    img_data = pix.tobytes("png")

                    # 使用PIL打开图像
                    image = Image.open(io.BytesIO(img_data))

                    # 取消检查：打开图像后、预处理前
                    if cancel_checker and cancel_checker():
                        try:
                            image.close()
                        except Exception:
                            pass
                        doc.close()
                        raise CancellationError(
                            f"任务在OCR图像预处理前被用户取消 (zoom={zoom})"
                        )

                    # 图像预处理以提高OCR质量
                    image = self._preprocess_image_for_ocr(image)

                    # OCR处理（多种策略尝试），传入取消检查以支持快速停止
                    ocr_text = self._perform_ocr_with_fallback(image, cancel_checker)

                    # 合并现有文本和OCR文本
                    combined_text = self._combine_texts(existing_text, ocr_text)
                    cleaned_text = self._clean_text(combined_text)

                    # 资源清理
                    try:
                        image.close()
                    except Exception:
                        pass

                    # 如果获得了足够的文本，则不再提升分辨率
                    if len(cleaned_text.strip()) >= 80:
                        break

                if len(cleaned_text.strip()) > 10:  # 降低过滤阈值
                    document = Document(
                        page_content=cleaned_text,
                        metadata={
                            "source": file_path,
                            "page": page_num + 1,
                            "extraction_method": "ocr",
                            "total_pages": len(doc),
                            "has_existing_text": bool(existing_text),
                            "ocr_confidence": "medium",  # 可以后续添加置信度计算
                        },
                    )
                    documents.append(document)

            doc.close()
            logger.info(f"OCR处理完成: {len(documents)} 页")
            return documents

        except Exception as e:
            logger.error(f"OCR处理失败: {str(e)}")
            raise

    def _combine_texts(self, existing_text: str, ocr_text: str) -> str:
        """
        智能合并现有文本和OCR文本
        """
        existing_text = existing_text.strip()
        ocr_text = ocr_text.strip()

        if not existing_text and not ocr_text:
            return ""

        if not existing_text:
            return ocr_text

        if not ocr_text:
            return existing_text

        # 如果现有文本足够长，优先使用现有文本
        if len(existing_text) > len(ocr_text) * 0.8:
            return existing_text

        # 否则使用OCR文本
        return ocr_text

    def _clean_text(self, text: str) -> str:
        """
        清理和格式化提取的文本
        """
        if not text:
            return ""

        # 基本清理
        lines = text.split("\n")
        cleaned_lines = []

        for line in lines:
            line = line.strip()
            if line:  # 去除空行
                # 移除多余空格
                line = " ".join(line.split())
                if len(line) > 2:  # 过滤太短的行
                    cleaned_lines.append(line)

        # 重新组合
        cleaned_text = "\n".join(cleaned_lines)

        # 进一步清理
        import re

        # 移除重复的空行
        cleaned_text = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned_text)

        # 移除特殊字符（保留中文、英文、数字、标点）
        cleaned_text = re.sub(
            r'[^\w\s\u4e00-\u9fff.,;:!?()[\]{}""' "—-]", "", cleaned_text
        )

        return cleaned_text.strip()

    def get_processing_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取PDF处理信息，用于调试和优化
        """
        try:
            pdf_info = self._analyze_pdf(file_path)

            processing_info = {
                "pdf_analysis": pdf_info,
                "recommended_method": (
                    "ocr" if pdf_info["is_scanned"] else "text_extraction"
                ),
                "ocr_available": self.ocr_available,
                "image_processing_available": self.image_extraction_available,
                "processing_notes": [],
            }

            # 添加处理建议
            if pdf_info["is_scanned"] and not self.ocr_available:
                processing_info["processing_notes"].append(
                    "检测到扫描类PDF，但OCR功能不可用。建议安装Tesseract以获得更好的效果。"
                )

            if pdf_info["image_ratio"] > 0.8:
                processing_info["processing_notes"].append(
                    "文档包含大量图像，可能需要更长的处理时间。"
                )

            if pdf_info["text_ratio"] > 0.8:
                processing_info["processing_notes"].append(
                    "文档主要包含文本，将使用快速文本提取方法。"
                )

            return processing_info

        except Exception as e:
            logger.error(f"获取处理信息失败: {str(e)}")
            return {"error": str(e), "ocr_available": self.ocr_available}

    def _preprocess_image_for_ocr(self, image):
        """
        图像预处理以提高OCR质量
        """
        try:
            from PIL import ImageEnhance, ImageFilter, ImageOps

            # 转换为灰度
            if image.mode != "L":
                image = image.convert("L")

            # 自动对比度，增强文本与背景的区分
            try:
                image = ImageOps.autocontrast(image, cutoff=1)
            except Exception:
                pass

            # 增强对比度
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.6)

            # 增强锐度
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(2.0)

            # 应用轻微的降噪
            image = image.filter(ImageFilter.MedianFilter(size=1))

            return image

        except Exception as e:
            logger.warning(f"图像预处理失败，使用原图: {str(e)}")
            return image

    def _perform_ocr_with_fallback(
        self, image, cancel_checker: Optional[Callable[[], bool]] = None
    ):
        """
        使用多种OCR配置尝试识别
        """
        import pytesseract

        # 构造语言序列（根据已安装语言动态调整）
        langs = []
        try:
            available = set(pytesseract.get_languages() or [])
        except Exception:
            available = set()
        if "chi_sim" in available and "eng" in available:
            langs.append("chi_sim+eng")
        if "chi_sim" in available:
            langs.append("chi_sim")
        if "eng" in available or not langs:
            langs.append("eng")

        # PSM 尝试序列：优先适用于密集文本的 6，然后 3、4、11
        psms = [6, 3, 4, 11]

        best_text = ""
        best_length = 0

        for lang in langs:
            for psm in psms:
                # 支持在尝试之间快速取消
                if cancel_checker and cancel_checker():
                    raise CancellationError("任务在OCR内部尝试阶段被取消")
                config = f"--psm {psm} --oem 3"
                try:
                    # 为单次 OCR 尝试设置超时，避免阻塞导致无法及时取消
                    ocr_text = pytesseract.image_to_string(
                        image, lang=lang, config=config, timeout=OCR_ATTEMPT_TIMEOUT_SEC
                    )
                    current = len(ocr_text.strip())
                    if current > best_length:
                        best_text = ocr_text
                        best_length = current
                    # 早停：达到较长文本时直接返回
                    if best_length > 300:
                        logger.info(
                            f"最佳OCR结果长度: {best_length} (lang={lang}, psm={psm})"
                        )
                        return best_text
                except Exception as e:
                    logger.debug(f"OCR失败或超时 lang={lang}, psm={psm}: {str(e)}")
                    continue

        logger.info(f"最佳OCR结果长度: {best_length}")
        return best_text


def install_ocr_dependencies():
    """
    安装OCR依赖的辅助函数
    """
    install_commands = {
        "windows": [
            "pip install pytesseract pillow",
            "# 下载并安装 Tesseract-OCR:",
            "# https://github.com/UB-Mannheim/tesseract/wiki",
            "# 或使用 chocolatey: choco install tesseract",
        ],
        "linux": [
            "pip install pytesseract pillow",
            "sudo apt-get update",
            "sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim",
        ],
        "macos": [
            "pip install pytesseract pillow",
            "brew install tesseract tesseract-lang",
        ],
    }

    return install_commands
