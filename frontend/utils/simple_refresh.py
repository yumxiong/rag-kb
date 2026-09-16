"""
简单自动刷新方案
提供多种刷新方式供用户选择
"""

import time

import streamlit as st


def add_auto_refresh_option():
    """添加自动刷新选项给用户"""
    with st.expander("⚙️ 自动刷新设置", expanded=False):
        st.write("**文档处理完成后的更新方式：**")

        refresh_mode = st.radio(
            "选择刷新方式",
            options=[
                "手动刷新（默认）",
                "10秒后自动刷新",
                "30秒后自动刷新",
                "处理完成立即刷新页面",
            ],
            index=0,
            key="refresh_mode",
        )

        if refresh_mode != "手动刷新（默认）":
            st.info(f"已选择：{refresh_mode}")

        return refresh_mode


def setup_page_auto_refresh(seconds: int):
    """设置页面定时自动刷新"""
    js_code = f"""
    <script>
    setTimeout(function(){{
        window.location.reload();
    }}, {seconds * 1000});
    </script>
    """
    st.components.v1.html(js_code, height=0, width=0)


def add_refresh_notification(job_id: str, refresh_mode: str, client_url: str):
    """根据用户选择的刷新模式添加相应的处理"""
    if refresh_mode == "手动刷新（默认）":
        return create_manual_refresh_sse(job_id, client_url)
    elif refresh_mode == "10秒后自动刷新":
        return create_delayed_refresh_sse(job_id, client_url, 10)
    elif refresh_mode == "30秒后自动刷新":
        return create_delayed_refresh_sse(job_id, client_url, 30)
    elif refresh_mode == "处理完成立即刷新页面":
        return create_immediate_refresh_sse(job_id, client_url)
    else:
        return create_manual_refresh_sse(job_id, client_url)


def create_manual_refresh_sse(job_id: str, client_url: str) -> str:
    """创建手动刷新模式的SSE监听"""
    return f"""
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

                if (status === 'completed') {{
                    window.__rag_last_completed_document_id = data.document_id || null;
                    statusDiv.innerHTML = '✅ 处理完成！请手动点击右侧的刷新按钮查看新文档';
                    eventSource.close();
                }} else if (status === 'failed') {{
                    statusDiv.innerHTML = '❌ 处理失败: ' + (data.error || data.message || '未知错误');
                    eventSource.close();
                }} else if (status === 'processing') {{
                    const progress = data.progress || 0;
                    const stage = data.stage || '';
                    let statusText = '🔄 处理中...';

                    if (stage.includes('ocr')) statusText = '🔍 OCR文字识别中...';
                    else if (stage.includes('split')) statusText = '📄 文档分割中...';
                    else if (stage.includes('embed')) statusText = '🧠 生成向量嵌入中...';
                    else if (stage.includes('save')) statusText = '💾 保存到数据库中...';

                    if (progress > 0) statusText += ` ${{progress}}%`;
                    statusDiv.innerHTML = statusText;
                }}
            }} catch (e) {{
                console.error('SSE解析错误:', e);
            }}
        }};

        eventSource.onerror = function() {{
            eventSource.close();
            statusDiv.innerHTML = '⚠️ 连接中断，请手动刷新页面查看结果';
        }};

        setTimeout(() => {{
            if (eventSource.readyState !== EventSource.CLOSED) {{
                eventSource.close();
                statusDiv.innerHTML = '⏰ 监听超时，请手动刷新页面查看结果';
            }}
        }}, 300000);
    }})();
    </script>
    """


def create_delayed_refresh_sse(job_id: str, client_url: str, delay_seconds: int) -> str:
    """创建延迟自动刷新模式的SSE监听"""
    return f"""
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

                if (status === 'completed') {{
                    window.__rag_last_completed_document_id = data.document_id || null;
                    eventSource.close();
                    let countdown = {delay_seconds};
                    statusDiv.innerHTML = `✅ 处理完成！页面将在${{countdown}}秒后自动刷新...`;

                    const countdownInterval = setInterval(() => {{
                        countdown--;
                        statusDiv.innerHTML = `✅ 处理完成！页面将在${{countdown}}秒后自动刷新...`;
                        if (countdown <= 0) {{
                            clearInterval(countdownInterval);
                            window.location.reload();
                        }}
                    }}, 1000);

                }} else if (status === 'failed') {{
                    statusDiv.innerHTML = '❌ 处理失败: ' + (data.error || data.message || '未知错误');
                    eventSource.close();
                }} else if (status === 'processing') {{
                    const progress = data.progress || 0;
                    const stage = data.stage || '';
                    let statusText = '🔄 处理中...';

                    if (stage.includes('ocr')) statusText = '🔍 OCR文字识别中...';
                    else if (stage.includes('split')) statusText = '📄 文档分割中...';
                    else if (stage.includes('embed')) statusText = '🧠 生成向量嵌入中...';
                    else if (stage.includes('save')) statusText = '💾 保存到数据库中...';

                    if (progress > 0) statusText += ` ${{progress}}%`;
                    statusDiv.innerHTML = statusText;
                }}
            }} catch (e) {{
                console.error('SSE解析错误:', e);
            }}
        }};

        eventSource.onerror = function() {{
            eventSource.close();
            statusDiv.innerHTML = '⚠️ 连接中断，请手动刷新页面查看结果';
        }};

        setTimeout(() => {{
            if (eventSource.readyState !== EventSource.CLOSED) {{
                eventSource.close();
                statusDiv.innerHTML = '⏰ 监听超时，请手动刷新页面查看结果';
            }}
        }}, 300000);
    }})();
    </script>
    """


def create_immediate_refresh_sse(job_id: str, client_url: str) -> str:
    """创建立即刷新模式的SSE监听"""
    return f"""
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

                if (status === 'completed') {{
                    window.__rag_last_completed_document_id = data.document_id || null;
                    statusDiv.innerHTML = '✅ 处理完成！正在刷新页面...';
                    eventSource.close();
                    setTimeout(() => {{
                        window.location.reload();
                    }}, 1000);

                }} else if (status === 'failed') {{
                    statusDiv.innerHTML = '❌ 处理失败: ' + (data.error || data.message || '未知错误');
                    eventSource.close();
                }} else if (status === 'processing') {{
                    const progress = data.progress || 0;
                    const stage = data.stage || '';
                    let statusText = '🔄 处理中...';

                    if (stage.includes('ocr')) statusText = '🔍 OCR文字识别中...';
                    else if (stage.includes('split')) statusText = '📄 文档分割中...';
                    else if (stage.includes('embed')) statusText = '🧠 生成向量嵌入中...';
                    else if (stage.includes('save')) statusText = '💾 保存到数据库中...';

                    if (progress > 0) statusText += ` ${{progress}}%`;
                    statusDiv.innerHTML = statusText;
                }}
            }} catch (e) {{
                console.error('SSE解析错误:', e);
            }}
        }};

        eventSource.onerror = function() {{
            eventSource.close();
            statusDiv.innerHTML = '⚠️ 连接中断，请手动刷新页面查看结果';
        }};

        setTimeout(() => {{
            if (eventSource.readyState !== EventSource.CLOSED) {{
                eventSource.close();
                statusDiv.innerHTML = '⏰ 监听超时，请手动刷新页面查看结果';
            }}
        }}, 300000);
    }})();
    </script>
    """
