"""
自动刷新工具 - 使用简单有效的方法实现组件自动更新
"""

import time

import streamlit as st


def setup_auto_refresh(job_id: str, client_url: str) -> str:
    """
    设置自动刷新机制 - 使用简单的JavaScript定时器
    当文档处理完成时自动刷新页面指定区域
    """
    js_code = f"""
    <div id="sse-status-{job_id}" style="margin: 10px 0;">
        <div id="status-text-{job_id}">🔄 正在监听处理状态...</div>
    </div>
    <script>
    (function() {{
        const statusDiv = document.getElementById('status-text-{job_id}');
        const eventSource = new EventSource('{client_url}/api/documents/status/stream/{job_id}');

        eventSource.onmessage = function(event) {{
            try {{
                const data = JSON.parse(event.data);
                const status = data.status;
                console.log('SSE received:', data);

                if (status === 'completed') {{
                    window.__rag_last_completed_document_id = data.document_id || null;
                    statusDiv.innerHTML = '✅ 处理完成！文档列表将在3秒后自动更新...';
                    eventSource.close();

                    // 简单的自动刷新：3秒后刷新页面
                    let countdown = 3;
                    const countdownInterval = setInterval(() => {{
                        statusDiv.innerHTML = `✅ 处理完成！文档列表将在${{countdown}}秒后自动更新...`;
                        countdown--;
                        if (countdown <= 0) {{
                            clearInterval(countdownInterval);
                            statusDiv.innerHTML = '✅ 处理完成！正在刷新页面...';

                            // 使用location.reload()确保页面刷新
                            setTimeout(() => {{
                                window.location.reload();
                            }}, 500);
                        }}
                    }}, 1000);

                }} else if (status === 'failed') {{
                    statusDiv.innerHTML = '❌ 处理失败: ' + (data.error || data.message || '未知错误');
                    eventSource.close();

                }} else if (status === 'processing') {{
                    const progress = data.progress || 0;
                    const message = data.message || '';
                    const stage = data.stage || '';
                    let statusText = '🔄 处理中...';

                    if (stage.includes('ocr') || stage.includes('OCR')) {{
                        statusText = '🔍 OCR文字识别中...';
                    }} else if (stage.includes('split') || stage.includes('chunk')) {{
                        statusText = '📄 文档分割中...';
                    }} else if (stage.includes('embed')) {{
                        statusText = '🧠 生成向量嵌入中...';
                    }} else if (stage.includes('save')) {{
                        statusText = '💾 保存到数据库中...';
                    }}

                    if (progress > 0) {{
                        statusText += ` ${{progress}}%`;
                    }}
                    if (message) {{
                        statusText += ` - ${{message}}`;
                    }}
                    statusDiv.innerHTML = statusText;

                }} else if (status === 'waiting') {{
                    statusDiv.innerHTML = '⏳ 等待处理队列中...';
                }} else if (status === 'timeout') {{
                    statusDiv.innerHTML = '⏰ 监听超时，大型文档可能仍在处理中，请手动刷新页面查看结果';
                    eventSource.close();
                }} else if (status === 'error') {{
                    statusDiv.innerHTML = '❌ 状态查询错误: ' + (data.message || '未知错误');
                    eventSource.close();
                }}
            }} catch (e) {{
                console.error('SSE解析错误:', e);
                statusDiv.innerHTML = '❌ 数据解析错误';
            }}
        }};

        eventSource.onerror = function(error) {{
            console.error('SSE连接错误:', error);
            statusDiv.innerHTML = '⚠️ 连接中断，请手动刷新页面查看结果';
            eventSource.close();
        }};

        // 5分钟超时保护
        setTimeout(() => {{
            if (eventSource.readyState !== EventSource.CLOSED) {{
                eventSource.close();
                statusDiv.innerHTML = '⏰ 监听超时，文档可能仍在处理中，请手动刷新页面查看结果';
            }}
        }}, 300000);
    }})();
    </script>
    """

    return js_code


def show_refresh_notification():
    """显示刷新通知"""
    st.info("📄 有新文档处理完成，页面将在几秒内自动刷新以显示最新内容...")


def add_manual_refresh_button(key_suffix: str = ""):
    """添加手动刷新按钮"""
    col1, col2, col3 = st.columns([2, 1, 1])

    with col3:
        if st.button("🔄 刷新页面", key=f"manual_refresh_{key_suffix}"):
            st.rerun()


def setup_periodic_refresh(interval_seconds: int = 30):
    """设置定期自动刷新（可选功能）"""
    js_code = f"""
    <script>
    // 定期检查是否有更新
    if (!window.__rag_periodic_refresh_setup) {{
        window.__rag_periodic_refresh_setup = true;

        setInterval(() => {{
            // 检查是否有新文档或处理完成的文档
            fetch('/api/documents/stats/overview')
                .then(response => response.json())
                .then(data => {{
                    const currentDocCount = data.total_documents || 0;
                    const currentChunkCount = data.total_chunks || 0;

                    // 存储在localStorage中进行比较
                    const lastDocCount = localStorage.getItem('rag_last_doc_count') || '0';
                    const lastChunkCount = localStorage.getItem('rag_last_chunk_count') || '0';

                    if (currentDocCount != lastDocCount || currentChunkCount != lastChunkCount) {{
                        localStorage.setItem('rag_last_doc_count', currentDocCount.toString());
                        localStorage.setItem('rag_last_chunk_count', currentChunkCount.toString());

                        // 如果检测到变化，显示刷新提示
                        const notification = document.createElement('div');
                        notification.style.cssText = `
                            position: fixed;
                            top: 20px;
                            right: 20px;
                            background: #00ff00;
                            color: white;
                            padding: 10px 20px;
                            border-radius: 5px;
                            z-index: 9999;
                            font-family: sans-serif;
                        `;
                        notification.innerHTML = '📄 检测到新文档，点击刷新页面查看';
                        notification.onclick = () => window.location.reload();
                        document.body.appendChild(notification);

                        // 3秒后自动移除通知
                        setTimeout(() => {{
                            if (notification.parentNode) {{
                                notification.parentNode.removeChild(notification);
                            }}
                        }}, 3000);
                    }}
                }})
                .catch(err => console.log('定期检查失败:', err));
        }}, {interval_seconds * 1000});
    }}
    </script>
    """

    st.components.v1.html(js_code, height=0, width=0)
