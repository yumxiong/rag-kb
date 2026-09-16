"""
OCR依赖安装脚本
用于安装Tesseract OCR和相关Python包，以支持扫描类PDF处理
"""

import argparse
import platform
import subprocess
import sys


def run_command(command, check=True):
    """运行系统命令"""
    print(f"执行命令: {command}")
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, check=check
        )
        if result.stdout:
            print(result.stdout)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e}")
        if e.stderr:
            print(f"错误输出: {e.stderr}")
        return False


def install_python_packages():
    """安装Python OCR包"""
    print("\n=== 安装Python OCR依赖 ===")
    packages = ["pytesseract", "pillow"]

    for package in packages:
        print(f"安装 {package}...")
        success = run_command(f"{sys.executable} -m pip install {package}")
        if success:
            print(f"✅ {package} 安装成功")
        else:
            print(f"❌ {package} 安装失败")
            return False

    return True


def install_tesseract_windows():
    """在Windows上安装Tesseract"""
    print("\n=== Windows Tesseract 安装 ===")

    # 检查是否已安装
    if run_command("tesseract --version", check=False):
        print("✅ Tesseract 已经安装")
        return True

    print("Tesseract未安装，提供安装选项:")
    print("\n选项1: 使用Chocolatey（推荐）")
    print("  如果已安装Chocolatey，执行: choco install tesseract")

    print("\n选项2: 手动下载安装")
    print("  1. 访问: https://github.com/UB-Mannheim/tesseract/wiki")
    print("  2. 下载最新版本的Windows安装包")
    print("  3. 运行安装程序，确保添加到PATH")
    print("  4. 重启命令行/IDE")

    # 尝试使用Chocolatey
    print("\n尝试检测Chocolatey...")
    if run_command("choco --version", check=False):
        print("检测到Chocolatey，尝试自动安装...")
        if run_command("choco install tesseract -y"):
            print("✅ 通过Chocolatey安装成功")
            return True
        else:
            print("❌ Chocolatey安装失败")

    print("\n请手动安装Tesseract，然后重新运行此脚本")
    return False


def install_tesseract_linux():
    """在Linux上安装Tesseract"""
    print("\n=== Linux Tesseract 安装 ===")

    # 检查是否已安装
    if run_command("tesseract --version", check=False):
        print("✅ Tesseract 已经安装")
        return True

    print("尝试使用包管理器安装...")

    # 尝试apt-get (Ubuntu/Debian)
    if run_command("which apt-get", check=False):
        print("检测到apt-get，安装Tesseract...")
        success = run_command("sudo apt-get update") and run_command(
            "sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim"
        )
        if success:
            print("✅ 通过apt-get安装成功")
            return True

    # 尝试yum (CentOS/RHEL)
    if run_command("which yum", check=False):
        print("检测到yum，安装Tesseract...")
        success = run_command(
            "sudo yum install -y tesseract tesseract-langpack-chi-sim"
        )
        if success:
            print("✅ 通过yum安装成功")
            return True

    print("❌ 自动安装失败，请手动安装:")
    print("Ubuntu/Debian: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim")
    print("CentOS/RHEL: sudo yum install tesseract tesseract-langpack-chi-sim")
    return False


def install_tesseract_macos():
    """在macOS上安装Tesseract"""
    print("\n=== macOS Tesseract 安装 ===")

    # 检查是否已安装
    if run_command("tesseract --version", check=False):
        print("✅ Tesseract 已经安装")
        return True

    # 尝试使用Homebrew
    if run_command("which brew", check=False):
        print("检测到Homebrew，安装Tesseract...")
        success = run_command("brew install tesseract tesseract-lang")
        if success:
            print("✅ 通过Homebrew安装成功")
            return True
        else:
            print("❌ Homebrew安装失败")
    else:
        print("未检测到Homebrew")
        print(
            '请先安装Homebrew: /bin/bash -c "$(curl -fsSL '
            'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        )
        print("然后执行: brew install tesseract tesseract-lang")

    return False


def test_ocr_functionality():
    """测试OCR功能"""
    print("\n=== 测试OCR功能 ===")

    try:
        import pytesseract

        # 检查Tesseract版本
        version = pytesseract.get_tesseract_version()
        print(f"✅ Tesseract版本: {version}")

        # 检查支持的语言
        languages = pytesseract.get_languages()
        print(f"✅ 支持的语言: {', '.join(languages)}")

        if "chi_sim" in languages or "eng" in languages:
            print("✅ OCR功能安装成功，支持文本识别")
            return True
        else:
            print("⚠️ OCR安装成功，但可能缺少语言包")
            return True

    except Exception as e:
        print(f"❌ OCR功能测试失败: {str(e)}")
        return False


def main():
    """主安装流程"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅检查 OCR，不安装软件")
    args = parser.parse_args()
    if args.check:
        sys.exit(0 if test_ocr_functionality() else 1)
    print("RAG知识库 - OCR依赖安装脚本")
    print("=" * 40)

    # 1. 安装Python包
    if not install_python_packages():
        print("❌ Python包安装失败，退出")
        sys.exit(1)

    # 2. 根据系统安装Tesseract
    system = platform.system().lower()
    tesseract_success = False

    if system == "windows":
        tesseract_success = install_tesseract_windows()
    elif system == "linux":
        tesseract_success = install_tesseract_linux()
    elif system == "darwin":  # macOS
        tesseract_success = install_tesseract_macos()
    else:
        print(f"❌ 不支持的操作系统: {system}")
        sys.exit(1)

    # 3. 测试OCR功能
    if tesseract_success:
        if test_ocr_functionality():
            print("\n🎉 OCR依赖安装完成!")
            print("现在可以处理扫描类PDF文档了")

            # 提供使用提示
            print("\n📋 使用说明:")
            print("1. 重启RAG知识库服务")
            print("2. 上传扫描类PDF文档")
            print("3. 系统会自动检测并使用OCR处理")
        else:
            print("\n⚠️ 安装完成但OCR测试失败")
            print("请检查安装或重启终端/IDE后重试")
    else:
        print("\n❌ Tesseract安装失败")
        print("请参考上方说明手动安装后重试")


if __name__ == "__main__":
    main()
