# PDF / OCR 辅助脚本

从仓库根目录执行，使用已安装后端依赖的 Python 环境。

```bash
python scripts/debug_pdf_processing.py path/to/sample.pdf
python scripts/install_ocr.py --check
```

PDF 调试脚本输出分析、提取预览及分块结果。省略 PDF 参数时，只查找本工作树 `data/uploads/` 下最新的 PDF；指定的相对路径按调用目录解析。脚本不会上传文件或写入向量库。

`--check` 只检测 Tesseract 版本和语言包。需要安装时运行 `python scripts/install_ocr.py`，该命令会安装 Python 包并尝试调用系统包管理器，可能需要管理员权限。自动安装支持 Windows、Linux 和 macOS；语言包是否满足输入语言仍需核对。Docker 后端已在镜像构建阶段安装 Tesseract。

其他脚本按 [部署指南](../docker/README.md)、[安全指南](../SECURITY.md) 和 [任务取消指南](../docs/CANCEL_TASK_GUIDE.md) 中的对应说明使用。返回 [文档导航](../docs/README.md)。
