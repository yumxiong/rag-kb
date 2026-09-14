#!/usr/bin/env python3
"""
调试PDF处理流程，分析扫描版PDF的处理情况
"""
import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 设置详细日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def analyze_pdf_processing(pdf_path: str):
    """详细分析PDF处理流程"""
    print(f"\n=== 分析PDF文件: {pdf_path} ===")

    # 检查文件是否存在
    if not os.path.exists(pdf_path):
        print(f"文件不存在: {pdf_path}")
        return

    print(f"文件存在，大小: {os.path.getsize(pdf_path)} 字节")

    from app.core.document_processor import DocumentProcessor
    from app.core.enhanced_pdf_processor import EnhancedPDFProcessor

    # 1. 使用增强PDF处理器分析
    print("\n--- 1. PDF文档分析 ---")
    enhanced_processor = EnhancedPDFProcessor()

    try:
        processing_info = enhanced_processor.get_processing_info(pdf_path)
        pdf_analysis = processing_info.get("pdf_analysis", {})

        print(f"总页数: {pdf_analysis.get('total_pages', 'N/A')}")
        print(f"采样页数: {pdf_analysis.get('sample_pages', 'N/A')}")
        print(f"有文本页数: {pdf_analysis.get('pages_with_text', 'N/A')}")
        print(f"有图像页数: {pdf_analysis.get('pages_with_images', 'N/A')}")
        print(f"文本比例: {pdf_analysis.get('text_ratio', 'N/A'):.2%}")
        print(f"图像比例: {pdf_analysis.get('image_ratio', 'N/A'):.2%}")
        print(f"平均每页字符数: {pdf_analysis.get('avg_chars_per_page', 'N/A')}")
        print(f"是否扫描类PDF: {pdf_analysis.get('is_scanned', 'N/A')}")
        print(f"低文本比例: {pdf_analysis.get('low_text_ratio', 'N/A')}")
        print(f"推荐处理方法: {processing_info.get('recommended_method', 'N/A')}")
        print(f"OCR可用: {processing_info.get('ocr_available', 'N/A')}")

        if processing_info.get("processing_notes"):
            print("处理建议:")
            for note in processing_info["processing_notes"]:
                print(f"  • {note}")

    except Exception as e:
        print(f"PDF分析失败: {str(e)}")
        return

    # 2. 测试增强处理器的实际处理
    print("\n--- 2. 增强PDF处理器测试 ---")
    try:
        documents = enhanced_processor.load(pdf_path)
        print(f"成功处理，生成文档数: {len(documents)}")

        total_chars = 0
        for i, doc in enumerate(documents):
            content_length = len(doc.page_content.strip())
            total_chars += content_length
            print(f"  页面 {doc.metadata.get('page', i+1)}: {content_length} 字符")
            print(f"  提取方法: {doc.metadata.get('extraction_method', 'N/A')}")
            if i < 2:  # 显示前2页的部分内容
                preview = doc.page_content.strip()[:200]
                print(f"  内容预览: {preview}...")

        print(f"总字符数: {total_chars}")

    except Exception as e:
        print(f"增强处理器处理失败: {str(e)}")

    # 3. 测试文档处理器的完整流程
    print("\n--- 3. 文档处理器完整流程测试 ---")
    try:
        doc_processor = DocumentProcessor()
        result = doc_processor.process_document(pdf_path, os.path.basename(pdf_path))

        print(f"处理状态: {result['status']}")
        print(f"分块数量: {result['chunk_count']}")

        if result["status"] == "completed":
            print("文档处理器成功处理")

            # 分析分块结果
            total_chunk_chars = 0
            for i, chunk in enumerate(result["chunks"][:5]):  # 显示前5个分块
                chunk_length = len(chunk.page_content.strip())
                total_chunk_chars += chunk_length
                print(f"  分块 {i+1}: {chunk_length} 字符")
                if i < 2:  # 显示前2个分块的部分内容
                    preview = chunk.page_content.strip()[:150]
                    print(f"    预览: {preview}...")

            print(f"前5个分块总字符数: {total_chunk_chars}")
        else:
            print(f"文档处理器处理失败: {result.get('error_message', 'Unknown error')}")

    except Exception as e:
        print(f"文档处理器测试失败: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pdf", nargs="?", type=Path, help="PDF 路径；省略则分析本工作树最新上传的 PDF"
    )
    args = parser.parse_args()
    if args.pdf is not None:
        analyze_pdf_processing(str(args.pdf.resolve()))
        return
    # 查找最新的PDF文件
    pdf_files = []
    for root, dirs, files in os.walk(PROJECT_ROOT / "data/uploads"):
        for file in files:
            if file.endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))

    pdf_files.sort(key=os.path.getmtime, reverse=True)  # 按修改时间排序，最新的在前

    if not pdf_files:
        print("未找到PDF文件")
        return

    print(f"找到 {len(pdf_files)} 个PDF文件")

    # 分析最新的PDF文件
    latest_pdf = pdf_files[0]
    analyze_pdf_processing(latest_pdf)


if __name__ == "__main__":
    main()
