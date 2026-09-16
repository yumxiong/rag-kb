"""
真正的实时更新方案
使用JavaScript直接更新DOM元素，无需页面刷新
"""

import json

import streamlit as st


def setup_realtime_update_system(backend_url: str):
    """
    设置实时更新系统
    创建JavaScript函数来直接更新页面元素
    """
    js_code = f"""
    <script>
    // 实时更新系统（使用相对路径，避免 HTTPS 环境下的混合内容问题）
    window.RagRealtimeUpdater = {{
        backendUrl: '',

        // 更新统计信息
        async updateStats() {{
            try {{
                const response = await fetch(this.backendUrl + '/api/documents/stats/overview');
                const stats = await response.json();

                // 查找并更新统计信息的元素
                const metrics = document.querySelectorAll('[data-testid="metric-value"]');

                metrics.forEach((metric, index) => {{
                    if (index === 0) {{ // 第一个metric是总文档数
                        metric.textContent = stats.total_documents || 0;
                    }} else if (index === 1) {{ // 第二个metric是总块数
                        metric.textContent = stats.total_chunks || 0;
                    }}
                }});

                console.log('Stats updated:', stats);
                return stats;
            }} catch (error) {{
                console.error('Failed to update stats:', error);
                return null;
            }}
        }},

        // 更新文档列表
        async updateDocumentList() {{
            try {{
                const response = await fetch(this.backendUrl + '/api/documents/');
                const documents = await response.json();

                // 找到文档列表容器
                const documentListContainer = this.findDocumentListContainer();
                if (documentListContainer) {{
                    this.refreshDocumentListHTML(documentListContainer, documents);
                }}

                console.log('Document list updated:', documents.length, 'documents');
                return documents;
            }} catch (error) {{
                console.error('Failed to update document list:', error);
                return null;
            }}
        }},

        // 查找文档列表容器
        findDocumentListContainer() {{
            // 查找包含"文档列表"标题的容器
            const headers = Array.from(document.querySelectorAll('h2, h3')).filter(h =>
                h.textContent.includes('文档列表')
            );

            if (headers.length > 0) {{
                // 找到文档列表标题后，查找其后的容器
                return headers[0].closest('.stColumn') || headers[0].parentElement;
            }}

            return null;
        }},

        // 刷新文档列表HTML
        refreshDocumentListHTML(container, documents) {{
            // 查找现有的文档数量显示
            const captionElements = container.querySelectorAll('.stCaption');
            captionElements.forEach(caption => {{
                if (caption.textContent.includes('共') && caption.textContent.includes('个文档')) {{
                    caption.textContent = `共 ${{documents.length}} 个文档`;
                }}
            }});

            // 更新文档数量（如果没有找到caption）
            if (captionElements.length === 0 && documents.length > 0) {{
                const refreshButton = container.querySelector('button[title="刷新文档列表"], button[title="刷新"]');
                if (refreshButton && refreshButton.parentElement) {{
                    // 在刷新按钮后添加文档数量显示
                    const countSpan = document.createElement('div');
                    countSpan.className = 'realtime-doc-count';
                    countSpan.style.cssText = 'font-size: 12px; color: #666; margin-top: 5px;';
                    countSpan.textContent = `共 ${{documents.length}} 个文档 (实时)`;

                    // 移除旧的计数
                    const oldCount = container.querySelector('.realtime-doc-count');
                    if (oldCount) oldCount.remove();

                    refreshButton.parentElement.appendChild(countSpan);
                }}
            }}

            // 在文档列表区域显示更新指示
            this.showUpdateIndicator(container, `文档列表已更新 (${{documents.length}}个文档)`);
        }},

        // 显示更新指示器
        showUpdateIndicator(container, message) {{
            // 移除旧的指示器
            const oldIndicator = container.querySelector('.realtime-update-indicator');
            if (oldIndicator) oldIndicator.remove();

            // 创建新的指示器
            const indicator = document.createElement('div');
            indicator.className = 'realtime-update-indicator';
            indicator.style.cssText = `
                background: linear-gradient(135deg, #4CAF50, #45a049);
                color: white;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                margin: 10px 0;
                animation: fadeInOut 3s ease-in-out;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            `;
            indicator.innerHTML = `✅ ${{message}}`;

            // 添加动画样式
            if (!document.querySelector('#realtime-update-styles')) {{
                const style = document.createElement('style');
                style.id = 'realtime-update-styles';
                style.textContent = `
                    @keyframes fadeInOut {{
                        0% {{ opacity: 0; transform: translateY(-10px); }}
                        20% {{ opacity: 1; transform: translateY(0); }}
                        80% {{ opacity: 1; transform: translateY(0); }}
                        100% {{ opacity: 0; transform: translateY(-10px); }}
                    }}
                `;
                document.head.appendChild(style);
            }}

            // 插入指示器
            const firstChild = container.firstElementChild;
            if (firstChild) {{
                container.insertBefore(indicator, firstChild.nextSibling);
            }} else {{
                container.appendChild(indicator);
            }}

            // 3秒后自动移除
            setTimeout(() => {{
                if (indicator.parentNode) {{
                    indicator.remove();
                }}
            }}, 3000);
        }},

        // 完整更新（统计信息 + 文档列表）
        async updateAll() {{
            const stats = await this.updateStats();
            const documents = await this.updateDocumentList();

            // 显示全局更新通知
            this.showGlobalUpdateNotification(stats, documents);

            return {{ stats, documents }};
        }},

        // 显示全局更新通知
        showGlobalUpdateNotification(stats, documents) {{
            // 移除旧通知
            const oldNotification = document.querySelector('.global-update-notification');
            if (oldNotification) oldNotification.remove();

            const notification = document.createElement('div');
            notification.className = 'global-update-notification';
            notification.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                background: linear-gradient(135deg, #2196F3, #1976D2);
                color: white;
                padding: 15px 20px;
                border-radius: 10px;
                z-index: 10000;
                font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                animation: slideInFromRight 0.3s ease-out;
                max-width: 320px;
            `;

            const docCount = documents ? documents.length : 0;
            const totalChunks = stats ? stats.total_chunks : 0;

            notification.innerHTML = `
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="font-size: 20px;">🎉</span>
                    <div>
                        <div style="font-weight: bold; margin-bottom: 4px;">内容已实时更新</div>
                        <div style="font-size: 13px; opacity: 0.9;">
                            📄 ${{docCount}} 个文档，${{totalChunks}} 个块
                        </div>
                    </div>
                </div>
            `;

            // 添加动画
            if (!document.querySelector('#global-notification-styles')) {{
                const style = document.createElement('style');
                style.id = 'global-notification-styles';
                style.textContent = `
                    @keyframes slideInFromRight {{
                        from {{ transform: translateX(100%); opacity: 0; }}
                        to {{ transform: translateX(0); opacity: 1; }}
                    }}
                    @keyframes slideOutToRight {{
                        from {{ transform: translateX(0); opacity: 1; }}
                        to {{ transform: translateX(100%); opacity: 0; }}
                    }}
                `;
                document.head.appendChild(style);
            }}

            document.body.appendChild(notification);

            // 4秒后淡出
            setTimeout(() => {{
                notification.style.animation = 'slideOutToRight 0.3s ease-out';
                setTimeout(() => notification.remove(), 300);
            }}, 4000);
        }}
    }};

    console.log('RAG Realtime Updater initialized');
    </script>
    """

    st.components.v1.html(js_code, height=0, width=0)


def create_realtime_document_monitor(job_id: str, client_url: str, mode: str) -> str:
    """
    创建实时文档处理监控器
    处理完成后直接更新页面元素，无需刷新
    """

    if mode == "手动刷新（默认）":
        completion_action = """
            statusDiv.innerHTML = "✅ 处理完成！内容已自动更新";
            // 实时更新页面内容
            if (window.RagRealtimeUpdater) {
                window.RagRealtimeUpdater.updateAll();
            }
        """
    elif mode == "10秒后自动刷新":
        completion_action = create_realtime_countdown_action(10)
    elif mode == "30秒后自动刷新":
        completion_action = create_realtime_countdown_action(30)
    else:  # 实时更新模式
        completion_action = f"""
            console.log("开始实时更新处理...");
            statusDiv.innerHTML = "✅ 处理完成！正在实时更新内容...";
            statusDiv.style.color = "#1976d2";

            // 安全的实时更新操作，仅更新数字，不触发任何可能破坏页面的操作
            async function performSafeRealtimeUpdate() {{
                try {{
                    console.log("开始获取最新数据...");

                    // 1. 获取统计数据
                    const statsResponse = await fetch('{client_url}/api/documents/stats/overview');
                    const stats = await statsResponse.json();
                    console.log("获取到统计数据:", stats);

                    // 2. 确定正确的DOM环境
                    let targetDoc = document;
                    if (window.parent && window.parent !== window) {{
                        try {{
                            targetDoc = window.parent.document;
                            console.log("检测到iframe环境，使用父页面DOM");
                        }} catch (e) {{
                            console.log("无法访问父页面DOM，使用当前iframe DOM");
                        }}
                    }}

                    // 3. 仅安全更新数字，避免任何可能破坏页面的操作
                    let statsUpdated = false;

                    // 方法1: 查找metric-value元素
                    const metrics = targetDoc.querySelectorAll('[data-testid="metric-value"]');
                    console.log("找到metric元素:", metrics.length);
                    if (metrics.length >= 2) {{
                        const oldDoc = metrics[0].textContent;
                        const oldChunk = metrics[1].textContent;
                        metrics[0].textContent = stats.total_documents || 0;
                        metrics[1].textContent = stats.total_chunks || 0;
                        statsUpdated = true;
                        console.log(`方法1更新统计: 文档数 ${{oldDoc}} → ${{stats.total_documents}}, 块数 ${{oldChunk}} → ${{stats.total_chunks}}`);
                    }}

                    // 方法2: 通过metric容器查找
                    if (!statsUpdated) {{
                        const metricContainers = targetDoc.querySelectorAll('[data-testid="metric"]');
                        console.log("找到metric容器:", metricContainers.length);

                        metricContainers.forEach((container, index) => {{
                            const valueEl = container.querySelector('[data-testid="metric-value"]');
                            const labelEl = container.querySelector('[data-testid="metric-label"]');

                            if (valueEl && labelEl) {{
                                const label = labelEl.textContent || '';
                                const oldValue = valueEl.textContent;
                                if (label.includes('文档') || label.includes('Documents')) {{
                                    valueEl.textContent = stats.total_documents || 0;
                                    console.log(`更新文档数: ${{oldValue}} → ${{stats.total_documents}}`);
                                    statsUpdated = true;
                                }} else if (label.includes('块') || label.includes('Chunks')) {{
                                    valueEl.textContent = stats.total_chunks || 0;
                                    console.log(`更新块数: ${{oldValue}} → ${{stats.total_chunks}}`);
                                    statsUpdated = true;
                                }}
                            }}
                        }});
                    }}

                    // 4. 显示成功状态
                    if (statsUpdated) {{
                        statusDiv.innerHTML = "✅ 处理完成！统计信息已实时更新 🎉";
                        statusDiv.style.color = "#4CAF50";
                        console.log(`🎉 实时更新完成！文档数: ${{stats.total_documents}}, 块数: ${{stats.total_chunks}}`);
                    }} else {{
                        statusDiv.innerHTML = "✅ 处理完成！正在刷新页面...";
                        statusDiv.style.color = "#f57c00";
                        console.log("未找到可更新的统计元素，执行页面刷新回退");

                        // 轻量回退：优先尝试点击“刷新文档列表”按钮以触发 Streamlit rerun（避免整页刷新闪屏）
                        function __clickStreamlitRefreshButton() {{
                            try {{
                                const doc = (window.parent && window.parent !== window) ? window.parent.document : document;
                                const buttons = Array.from(doc.querySelectorAll('button'));
                                const target = buttons.find(b => (b.innerText || '').includes('刷新文档列表') || (b.innerText || '').includes('刷新'));
                                if (target) {{
                                    console.log('触发轻量 rerun：点击刷新按钮');
                                    target.click();
                                    return true;
                                }}
                            }} catch (e) {{ /* ignore */ }}
                            return false;
                        }}

                        setTimeout(async () => {{
                            try {{
                                if (window.RagRealtimeUpdater) {{ await window.RagRealtimeUpdater.updateAll(); }}
                            }} catch (e) {{ /* ignore */ }}

                            if (!__clickStreamlitRefreshButton()) {{
                                (window.top || window.parent || window).location.reload();
                            }}
                        }}, 800);
                    }}

                    // 5. 更新文档列表（如果可用）
                    try {{
                        if (window.RagRealtimeUpdater) {{
                            await window.RagRealtimeUpdater.updateDocumentList();
                        }}
                    }} catch (e) {{
                        console.log('更新文档列表失败', e);
                    }}

                }} catch (error) {{
                    console.error('实时更新失败:', error);
                    statusDiv.innerHTML = "✅ 处理完成！更新失败，正在自动刷新...";
                    statusDiv.style.color = "#f57c00";

                    function __clickStreamlitRefreshButton() {{
                        try {{
                            const doc = (window.parent && window.parent !== window) ? window.parent.document : document;
                            const buttons = Array.from(doc.querySelectorAll('button'));
                            const target = buttons.find(b => (b.innerText || '').includes('刷新文档列表') || (b.innerText || '').includes('刷新'));
                            if (target) {{ target.click(); return true; }}
                        }} catch (e) {{ /* ignore */ }}
                        return false;
                    }}
                    setTimeout(() => {{
                        if (!__clickStreamlitRefreshButton()) {{
                            (window.top || window.parent || window).location.reload();
                        }}
                    }}, 800);
                }}
            }}

            // 延迟1秒执行，确保页面稳定
            setTimeout(performSafeRealtimeUpdate, 1000);
        """

    return f"""
    <div id="realtime-monitor-{job_id}" style="margin: 10px 0; padding: 12px; border: 2px solid #e1f5fe; border-radius: 8px; background: linear-gradient(135deg, #f8f9fa, #e3f2fd);">
        <div id="realtime-status-{job_id}" style="font-weight: bold; color: #1976d2;">🔄 正在监听文档处理状态...</div>
    </div>

    <script>
    (function() {{
        const statusDiv = document.getElementById('realtime-status-{job_id}');
        const eventSource = new EventSource('{client_url}/api/documents/status/stream/{job_id}');
        let isCompleted = false;

        eventSource.onmessage = function(event) {{
            if (isCompleted) return;

            try {{
                const data = JSON.parse(event.data);
                const status = data.status;

                if (status === 'completed') {{
                    window.__rag_last_completed_document_id = data.document_id || null;
                    isCompleted = true;
                    eventSource.close();
                    {completion_action}

                }} else if (status === 'cancelled' || status === 'cancelling') {{
                    isCompleted = true;
                    eventSource.close();
                    statusDiv.innerHTML = '🛑 任务已取消';
                    statusDiv.style.color = '#f57c00';

                }} else if (status === 'failed') {{
                    isCompleted = true;
                    eventSource.close();
                    const error = data.error || data.message || '未知错误';
                    statusDiv.innerHTML = '❌ 处理失败: ' + error;
                    statusDiv.style.color = '#d32f2f';

                }} else if (status === 'processing') {{
                    const progress = data.progress || 0;
                    const stage = data.stage || '';

                    let statusText = '🔄 处理中';
                    let statusColor = '#1976d2';

                    if (stage.toLowerCase().includes('ocr')) {{
                        statusText = '🔍 OCR文字识别中';
                        statusColor = '#7b1fa2';
                    }} else if (stage.toLowerCase().includes('split') || stage.toLowerCase().includes('chunk')) {{
                        statusText = '📄 文档分割中';
                        statusColor = '#388e3c';
                    }} else if (stage.toLowerCase().includes('embed')) {{
                        statusText = '🧠 生成向量嵌入中';
                        statusColor = '#f57c00';
                    }} else if (stage.toLowerCase().includes('save')) {{
                        statusText = '💾 保存到数据库中';
                        statusColor = '#0288d1';
                    }}

                    if (progress > 0) {{
                        statusText += ` (${{progress}}%)`;
                    }}

                    statusDiv.innerHTML = statusText;
                    statusDiv.style.color = statusColor;
                }}

            }} catch (e) {{
                console.error('实时监控解析错误:', e);
                statusDiv.innerHTML = '⚠️ 状态解析出错';
                statusDiv.style.color = '#f57c00';
            }}
        }};

        eventSource.onerror = function() {{
            if (!isCompleted) {{
                eventSource.close();
                statusDiv.innerHTML = '⚠️ 连接中断，已切换到备用更新方式';
                statusDiv.style.color = '#f57c00';

                // 备用方案：定时检查
                setTimeout(() => {{
                    if (window.RagRealtimeUpdater) {{
                        window.RagRealtimeUpdater.updateAll();
                    }}
                }}, 3000);
            }}
        }};

        setTimeout(() => {{
            if (!isCompleted && eventSource.readyState !== EventSource.CLOSED) {{
                eventSource.close();
                statusDiv.innerHTML = '⏰ 监听超时，正在尝试更新内容...';
                statusDiv.style.color = '#f57c00';

                if (window.RagRealtimeUpdater) {{
                    window.RagRealtimeUpdater.updateAll();
                }}
            }}
        }}, 300000);

    }})();
    </script>
    """


def create_realtime_countdown_action(seconds: int) -> str:
    """创建实时更新倒计时"""
    return f"""
        let countdown = {seconds};
        statusDiv.innerHTML = `✅ 处理完成！${{countdown}}秒后实时更新内容...`;
        statusDiv.style.color = '#388e3c';

        const countdownInterval = setInterval(() => {{
            countdown--;
            statusDiv.innerHTML = `✅ 处理完成！${{countdown}}秒后实时更新内容...`;

            if (countdown <= 0) {{
                clearInterval(countdownInterval);
                statusDiv.innerHTML = "✅ 正在实时更新内容...";

                if (window.RagRealtimeUpdater) {{
                    window.RagRealtimeUpdater.updateAll().then(() => {{
                        statusDiv.innerHTML = "✅ 处理完成！内容已实时更新 🎉";
                    }}).catch(error => {{
                        console.error('实时更新失败:', error);
                        statusDiv.innerHTML = "✅ 处理完成！请手动刷新查看更新";
                    }});
                }} else {{
                    // 如果更新器不存在，尝试刷新页面（优先轻量 rerun）
                    statusDiv.innerHTML = "✅ 处理完成！正在刷新页面...";
                    setTimeout(() => {{
                        try {{
                            const doc = (window.parent && window.parent !== window) ? window.parent.document : document;
                            const buttons = Array.from(doc.querySelectorAll('button'));
                            const target = buttons.find(b => (b.innerText || '').includes('刷新文档列表') || (b.innerText || '').includes('刷新'));
                            if (target) {{ target.click(); return; }}
                        }} catch (e) {{ /* ignore */ }}
                        (window.top || window.parent || window).location.reload();
                    }}, 500);
                }}
            }}
        }}, 1000);
    """


def add_realtime_refresh_buttons():
    """添加实时刷新按钮"""
    st.markdown("---")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        if st.button(
            "📊 实时更新统计", help="实时更新文档统计信息", key="realtime_stats"
        ):
            st.components.v1.html(
                """
            <script>
            if (window.RagRealtimeUpdater) {
                window.RagRealtimeUpdater.updateStats();
            }
            </script>
            """,
                height=0,
                width=0,
            )
            st.success("✅ 统计信息已实时更新")

    with col2:
        if st.button("📄 实时更新列表", help="实时更新文档列表", key="realtime_docs"):
            st.components.v1.html(
                """
            <script>
            if (window.RagRealtimeUpdater) {
                window.RagRealtimeUpdater.updateDocumentList();
            }
            </script>
            """,
                height=0,
                width=0,
            )
            st.success("✅ 文档列表已实时更新")

    with col3:
        if st.button("🎉 实时更新全部", help="实时更新所有内容", key="realtime_all"):
            st.components.v1.html(
                """
            <script>
            if (window.RagRealtimeUpdater) {
                window.RagRealtimeUpdater.updateAll();
            }
            </script>
            """,
                height=0,
                width=0,
            )
            st.success("✅ 所有内容已实时更新")

    with col4:
        if st.button("🔄 传统刷新", help="传统页面刷新", key="traditional_refresh"):
            st.rerun()


def setup_realtime_refresh_mode():
    """设置实时刷新模式选项"""
    with st.expander("⚙️ 实时更新设置", expanded=False):
        st.write("**文档处理完成后的更新方式：**")

        refresh_mode = st.radio(
            "选择更新方式",
            options=[
                "实时更新（推荐）",
                "手动更新",
                "10秒后实时更新",
                "30秒后实时更新",
            ],
            index=0,
            key="realtime_refresh_mode",
            help="实时更新无需刷新页面，直接更新内容",
        )

        if refresh_mode == "实时更新（推荐）":
            st.success("✅ 已启用实时更新模式，处理完成后内容会自动更新，无需刷新页面")
        else:
            st.info(f"已选择：{refresh_mode}")

        return refresh_mode
