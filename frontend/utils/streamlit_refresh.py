"""
Streamlit原生刷新方案
使用Streamlit内置机制实现可靠的自动刷新
"""

import threading
import time

import streamlit as st


def setup_streamlit_auto_refresh(job_id: str, client_url: str, mode: str):
    """
    使用Streamlit原生方式设置自动刷新
    通过Session State + 定时检查实现
    """
    # 初始化状态
    if f"job_processing_{job_id}" not in st.session_state:
        st.session_state[f"job_processing_{job_id}"] = True
        st.session_state[f"job_check_count_{job_id}"] = 0

    # 显示处理状态
    status_placeholder = st.empty()

    # 检查文档状态
    doc_completed = check_document_status(job_id, client_url, status_placeholder)

    if doc_completed:
        # 文档处理完成
        st.session_state[f"job_processing_{job_id}"] = False

        if mode == "处理完成立即刷新页面":
            status_placeholder.success("✅ 处理完成！正在刷新页面...")
            time.sleep(1)
            st.rerun()
        elif mode == "10秒后自动刷新":
            handle_delayed_refresh(status_placeholder, 10)
        elif mode == "30秒后自动刷新":
            handle_delayed_refresh(status_placeholder, 30)
        else:
            status_placeholder.success("✅ 处理完成！请点击右侧的🔄刷新按钮查看新文档")

    elif st.session_state.get(f"job_processing_{job_id}", False):
        # 仍在处理中，设置自动重新检查
        st.session_state[f"job_check_count_{job_id}"] += 1

        # 每3秒检查一次，最多检查100次（5分钟）
        if st.session_state[f"job_check_count_{job_id}"] < 100:
            time.sleep(3)
            st.rerun()
        else:
            status_placeholder.warning("⏰ 检查超时，请手动刷新页面查看结果")
            st.session_state[f"job_processing_{job_id}"] = False


def check_document_status(job_id: str, client_url: str, status_placeholder):
    """检查文档处理状态"""
    import requests

    try:
        response = requests.get(
            f"{client_url}/api/documents/status/{job_id}", timeout=10
        )
        if response.status_code == 200:
            result = response.json()
            status = result.get("status", "unknown")

            if status == "completed":
                return True
            elif status == "failed":
                error = result.get("error", "未知错误")
                status_placeholder.error(f"❌ 处理失败: {error}")
                return True  # 虽然失败，但处理已结束
            elif status == "processing":
                progress = result.get("progress", 0)
                stage = result.get("stage", "")
                message = result.get("message", "")

                status_text = get_processing_status_text(stage, progress, message)
                status_placeholder.info(status_text)
                return False
            else:
                status_placeholder.info(f"🔄 文档状态: {status}")
                return False
        else:
            status_placeholder.warning("⚠️ 无法获取文档状态")
            return False

    except Exception as e:
        status_placeholder.error(f"❌ 状态检查出错: {str(e)}")
        return True  # 出错时停止检查


def get_processing_status_text(stage: str, progress: int, message: str) -> str:
    """获取处理状态文本"""
    if "ocr" in stage.lower():
        base_text = "🔍 OCR文字识别中"
    elif "split" in stage.lower() or "chunk" in stage.lower():
        base_text = "📄 文档分割中"
    elif "embed" in stage.lower():
        base_text = "🧠 生成向量嵌入中"
    elif "save" in stage.lower():
        base_text = "💾 保存到数据库中"
    else:
        base_text = "🔄 处理中"

    if progress > 0:
        base_text += f" ({progress}%)"

    if message:
        base_text += f" - {message}"

    return base_text


def handle_delayed_refresh(status_placeholder, delay_seconds: int):
    """处理延迟刷新"""
    # 使用Session State来管理倒计时
    countdown_key = f"refresh_countdown_{int(time.time())}"

    if countdown_key not in st.session_state:
        st.session_state[countdown_key] = delay_seconds

    countdown = st.session_state[countdown_key]

    if countdown > 0:
        status_placeholder.success(f"✅ 处理完成！页面将在 {countdown} 秒后自动刷新...")
        st.session_state[countdown_key] = countdown - 1
        time.sleep(1)
        st.rerun()
    else:
        status_placeholder.success("✅ 处理完成！正在刷新页面...")
        del st.session_state[countdown_key]  # 清理
        time.sleep(0.5)
        st.rerun()


def add_simple_refresh_buttons():
    """添加简单的刷新按钮组"""
    col1, col2, col3 = st.columns([2, 1, 1])

    with col2:
        if st.button("🔄 刷新统计", help="刷新文档统计信息"):
            # 清除缓存并刷新
            for key in list(st.session_state.keys()):
                if key.endswith("_cache"):
                    del st.session_state[key]
            st.rerun()

    with col3:
        if st.button("🔄 刷新列表", help="刷新文档列表"):
            # 清除缓存并刷新
            for key in list(st.session_state.keys()):
                if key.endswith("_cache"):
                    del st.session_state[key]
            st.rerun()


def setup_background_refresh_check():
    """设置后台刷新检查（使用JavaScript作为备用方案）"""
    js_code = """
    <script>
    // 简单的后台检查，作为备用方案
    if (!window.__rag_bg_check_setup) {
        window.__rag_bg_check_setup = true;

        let lastDocCount = 0;
        let lastChunkCount = 0;

        // 每30秒检查一次
        setInterval(() => {
            fetch('/api/documents/stats/overview')
                .then(response => response.json())
                .then(data => {
                    const currentDocCount = data.total_documents || 0;
                    const currentChunkCount = data.total_chunks || 0;

                    if (lastDocCount > 0 && (currentDocCount !== lastDocCount || currentChunkCount !== lastChunkCount)) {
                        // 检测到变化，显示通知
                        const notification = document.createElement('div');
                        notification.style.cssText = `
                            position: fixed;
                            top: 70px;
                            right: 20px;
                            background: #4CAF50;
                            color: white;
                            padding: 12px 20px;
                            border-radius: 8px;
                            z-index: 9999;
                            font-family: sans-serif;
                            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                            cursor: pointer;
                        `;
                        notification.innerHTML = '📄 检测到新文档！点击刷新页面';
                        notification.onclick = () => {
                            window.location.reload();
                        };
                        document.body.appendChild(notification);

                        // 5秒后自动移除
                        setTimeout(() => {
                            if (notification.parentNode) {
                                notification.parentNode.removeChild(notification);
                            }
                        }, 5000);
                    }

                    lastDocCount = currentDocCount;
                    lastChunkCount = currentChunkCount;
                })
                .catch(err => {
                    console.log('Background check failed:', err);
                });
        }, 30000);
    }
    </script>
    """

    st.components.v1.html(js_code, height=0, width=0)
