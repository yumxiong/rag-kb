"""
最终简化的自动刷新方案
使用最简单可靠的方法实现自动刷新
"""

import streamlit as st


def create_simple_auto_refresh_html(job_id: str, client_url: str, mode: str) -> str:
    """
    创建简单的自动刷新HTML
    使用纯JavaScript实现，避免Streamlit复杂性
    """

    if mode == "手动刷新（默认）":
        refresh_action = (
            'statusDiv.innerHTML = "✅ 处理完成！请点击右侧的🔄刷新按钮查看新文档";'
        )
    elif mode == "10秒后自动刷新":
        refresh_action = create_countdown_refresh(10)
    elif mode == "30秒后自动刷新":
        refresh_action = create_countdown_refresh(30)
    else:  # 立即刷新
        refresh_action = """
            statusDiv.innerHTML = "✅ 处理完成！1秒后自动刷新页面...";
            setTimeout(() => {
                // 尝试多种刷新方式
                try {
                    window.top.location.reload();
                } catch(e1) {
                    try {
                        window.parent.location.reload();
                    } catch(e2) {
                        try {
                            window.location.reload();
                        } catch(e3) {
                            // 如果都失败，显示提示
                            statusDiv.innerHTML = "✅ 处理完成！请手动刷新页面查看新文档";
                        }
                    }
                }
            }, 1000);
        """

    return f"""
    <div id="refresh-monitor-{job_id}" style="margin: 10px 0; padding: 10px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9;">
        <div id="status-{job_id}" style="font-weight: bold;">🔄 正在监听文档处理状态...</div>
    </div>

    <script>
    (function() {{
        const statusDiv = document.getElementById('status-{job_id}');
        const eventSource = new EventSource('{client_url}/api/documents/status/stream/{job_id}');

        let isCompleted = false;

        eventSource.onmessage = function(event) {{
            if (isCompleted) return; // 防止重复处理

            try {{
                const data = JSON.parse(event.data);
                const status = data.status;

                console.log('Document status:', status, data);

                if (status === 'completed') {{
                    window.__rag_last_completed_document_id = data.document_id || null;
                    isCompleted = true;
                    eventSource.close();
                    {refresh_action}

                }} else if (status === 'failed') {{
                    isCompleted = true;
                    eventSource.close();
                    const error = data.error || data.message || '未知错误';
                    statusDiv.innerHTML = '❌ 处理失败: ' + error;

                }} else if (status === 'processing') {{
                    const progress = data.progress || 0;
                    const stage = data.stage || '';
                    const message = data.message || '';

                    let statusText = '🔄 处理中';

                    // 显示具体阶段
                    if (stage.toLowerCase().includes('ocr')) {{
                        statusText = '🔍 OCR文字识别中';
                    }} else if (stage.toLowerCase().includes('split') || stage.toLowerCase().includes('chunk')) {{
                        statusText = '📄 文档分割中';
                    }} else if (stage.toLowerCase().includes('embed')) {{
                        statusText = '🧠 生成向量嵌入中';
                    }} else if (stage.toLowerCase().includes('save')) {{
                        statusText = '💾 保存到数据库中';
                    }}

                    // 添加进度
                    if (progress > 0) {{
                        statusText += ` (${{progress}}%)`;
                    }}

                    // 添加消息
                    if (message) {{
                        statusText += ` - ${{message}}`;
                    }}

                    statusDiv.innerHTML = statusText;

                }} else if (status === 'waiting') {{
                    statusDiv.innerHTML = '⏳ 等待处理队列中...';
                }} else {{
                    statusDiv.innerHTML = '🔄 文档状态: ' + status;
                }}

            }} catch (e) {{
                console.error('解析SSE数据出错:', e);
                statusDiv.innerHTML = '⚠️ 状态解析出错';
            }}
        }};

        eventSource.onerror = function(error) {{
            console.error('SSE连接出错:', error);
            if (!isCompleted) {{
                eventSource.close();
                statusDiv.innerHTML = '⚠️ 连接中断，请手动刷新页面查看结果';
            }}
        }};

        // 5分钟超时
        setTimeout(() => {{
            if (!isCompleted && eventSource.readyState !== EventSource.CLOSED) {{
                eventSource.close();
                statusDiv.innerHTML = '⏰ 监听超时，请手动刷新页面查看结果';
            }}
        }}, 300000);

    }})();
    </script>
    """


def create_countdown_refresh(seconds: int) -> str:
    """创建倒计时刷新逻辑"""
    return f"""
        let countdown = {seconds};
        statusDiv.innerHTML = `✅ 处理完成！页面将在${{countdown}}秒后自动刷新...`;

        const countdownInterval = setInterval(() => {{
            countdown--;
            statusDiv.innerHTML = `✅ 处理完成！页面将在${{countdown}}秒后自动刷新...`;

            if (countdown <= 0) {{
                clearInterval(countdownInterval);
                statusDiv.innerHTML = "✅ 正在刷新页面...";

                // 尝试多种刷新方式
                setTimeout(() => {{
                    try {{
                        window.top.location.reload();
                    }} catch(e1) {{
                        try {{
                            window.parent.location.reload();
                        }} catch(e2) {{
                            try {{
                                window.location.reload();
                            }} catch(e3) {{
                                statusDiv.innerHTML = "✅ 处理完成！请手动刷新页面查看新文档";
                            }}
                        }}
                    }}
                }}, 500);
            }}
        }}, 1000);
    """


def add_refresh_status_indicator():
    """添加刷新状态指示器"""
    st.markdown(
        """
    <div style="position: fixed; top: 10px; right: 10px; z-index: 9999; background: rgba(255,255,255,0.9); padding: 5px 10px; border-radius: 5px; font-size: 12px; border: 1px solid #ddd;">
        📊 支持自动刷新
    </div>
    """,
        unsafe_allow_html=True,
    )


def add_enhanced_refresh_buttons():
    """添加增强的刷新按钮"""
    st.markdown("---")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        if st.button("🔄 刷新统计", help="刷新文档统计信息", key="refresh_stats_btn"):
            # 清除相关缓存
            cache_keys_to_clear = [
                k for k in st.session_state.keys() if "cache" in k or "refresh" in k
            ]
            for key in cache_keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    with col2:
        if st.button("🔄 刷新列表", help="刷新文档列表", key="refresh_docs_btn"):
            # 清除相关缓存
            cache_keys_to_clear = [
                k for k in st.session_state.keys() if "cache" in k or "refresh" in k
            ]
            for key in cache_keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    with col3:
        if st.button("🔄 刷新全部", help="完整刷新页面", key="refresh_all_btn"):
            # 清除所有缓存
            keys_to_keep = [
                "byok_api_key",
                "byok_provider",
                "byok_base_url",
                "byok_model",
                "refresh_mode",
            ]
            for key in list(st.session_state.keys()):
                if key not in keys_to_keep:
                    del st.session_state[key]
            st.rerun()

    with col4:
        # 显示最后刷新时间
        if "last_refresh_time" not in st.session_state:
            st.session_state.last_refresh_time = "未刷新"

        st.caption(f"最后刷新: {st.session_state.last_refresh_time}")


def setup_background_notification():
    """设置后台通知系统"""
    js_code = """
    <script>
    if (!window.__rag_bg_notification_setup) {
        window.__rag_bg_notification_setup = true;

        let lastDocCount = localStorage.getItem('rag_last_doc_count') || '0';
        let lastChunkCount = localStorage.getItem('rag_last_chunk_count') || '0';

        // 每15秒检查一次
        setInterval(() => {
            fetch('/api/documents/stats/overview')
                .then(response => response.json())
                .then(data => {
                    const currentDocCount = String(data.total_documents || 0);
                    const currentChunkCount = String(data.total_chunks || 0);

                    if (lastDocCount !== '0' && (currentDocCount !== lastDocCount || currentChunkCount !== lastChunkCount)) {
                        // 检测到变化
                        showUpdateNotification();
                    }

                    lastDocCount = currentDocCount;
                    lastChunkCount = currentChunkCount;
                    localStorage.setItem('rag_last_doc_count', currentDocCount);
                    localStorage.setItem('rag_last_chunk_count', currentChunkCount);
                })
                .catch(err => console.log('Background check error:', err));
        }, 15000);

        function showUpdateNotification() {
            // 移除已存在的通知
            const existing = document.getElementById('rag-update-notification');
            if (existing) existing.remove();

            const notification = document.createElement('div');
            notification.id = 'rag-update-notification';
            notification.style.cssText = `
                position: fixed;
                top: 70px;
                right: 20px;
                background: linear-gradient(135deg, #4CAF50, #45a049);
                color: white;
                padding: 15px 20px;
                border-radius: 10px;
                z-index: 10000;
                font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                font-size: 14px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                cursor: pointer;
                animation: slideIn 0.3s ease-out;
                max-width: 300px;
            `;

            notification.innerHTML = `
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 18px;">📄</span>
                    <div>
                        <div style="font-weight: bold;">文档更新完成</div>
                        <div style="font-size: 12px; opacity: 0.9;">点击刷新页面查看</div>
                    </div>
                </div>
            `;

            notification.onclick = () => {
                window.location.reload();
            };

            document.body.appendChild(notification);

            // 10秒后自动移除
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.style.animation = 'slideOut 0.3s ease-out';
                    setTimeout(() => notification.remove(), 300);
                }
            }, 10000);
        }

        // 添加动画样式
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
        document.head.appendChild(style);
    }
    </script>
    """

    st.components.v1.html(js_code, height=0, width=0)
