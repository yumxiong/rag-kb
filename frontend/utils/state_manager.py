"""
状态管理工具
用于管理应用状态并支持实时更新，避免页面刷新
"""

import time
from datetime import datetime
from typing import Any, Dict, Optional

import streamlit as st


class StateManager:
    """状态管理器，用于处理实时更新和数据缓存"""

    @staticmethod
    def init_state():
        """初始化应用状态"""
        if "last_document_refresh" not in st.session_state:
            st.session_state.last_document_refresh = 0

        if "last_stats_refresh" not in st.session_state:
            st.session_state.last_stats_refresh = 0

        if "documents_cache" not in st.session_state:
            st.session_state.documents_cache = None

        if "stats_cache" not in st.session_state:
            st.session_state.stats_cache = None

        if "processing_jobs" not in st.session_state:
            existing_jobs = st.session_state.get("processing_documents", set())
            st.session_state.processing_jobs = set(existing_jobs)

        if "refresh_triggers" not in st.session_state:
            st.session_state.refresh_triggers = {}

    @staticmethod
    def trigger_refresh(component: str, delay: float = 0):
        """触发组件刷新"""
        if "refresh_triggers" not in st.session_state:
            st.session_state.refresh_triggers = {}

        st.session_state.refresh_triggers[component] = time.time() + delay

    @staticmethod
    def should_refresh(component: str, cache_duration: float = 30) -> bool:
        """检查组件是否需要刷新"""
        current_time = time.time()

        # 检查是否有手动触发的刷新
        if "refresh_triggers" in st.session_state:
            trigger_time = st.session_state.refresh_triggers.get(component, 0)
            if trigger_time > 0 and current_time >= trigger_time:
                # 清除触发器
                st.session_state.refresh_triggers[component] = 0
                return True

        # 检查缓存是否过期
        last_refresh_key = f"last_{component}_refresh"
        if last_refresh_key in st.session_state:
            last_refresh = st.session_state[last_refresh_key]
            if current_time - last_refresh > cache_duration:
                return True
        else:
            # 首次加载
            return True

        return False

    @staticmethod
    def mark_refreshed(component: str):
        """标记组件已刷新"""
        last_refresh_key = f"last_{component}_refresh"
        st.session_state[last_refresh_key] = time.time()

    @staticmethod
    def get_cache(cache_key: str) -> Optional[Any]:
        """获取缓存数据"""
        return st.session_state.get(f"{cache_key}_cache")

    @staticmethod
    def set_cache(cache_key: str, data: Any):
        """设置缓存数据"""
        st.session_state[f"{cache_key}_cache"] = data

    @staticmethod
    def add_processing_job(job_id: str):
        if "processing_jobs" not in st.session_state:
            st.session_state.processing_jobs = set()
        st.session_state.processing_jobs.add(job_id)

    @staticmethod
    def remove_processing_job(job_id: str):
        if "processing_jobs" in st.session_state:
            st.session_state.processing_jobs.discard(job_id)

        # 文档处理完成，触发相关组件刷新
        StateManager.trigger_refresh("documents", 1)  # 1秒后刷新文档列表
        StateManager.trigger_refresh("stats", 1)  # 1秒后刷新统计信息

    @staticmethod
    def get_processing_jobs() -> set:
        return st.session_state.get("processing_jobs", set())

    @staticmethod
    def is_job_processing(job_id: str) -> bool:
        return job_id in StateManager.get_processing_jobs()

    @staticmethod
    def clear_caches():
        """清除所有缓存"""
        cache_keys = ["documents", "stats"]
        for key in cache_keys:
            if f"{key}_cache" in st.session_state:
                del st.session_state[f"{key}_cache"]

        # 重置刷新时间
        for key in cache_keys:
            st.session_state[f"last_{key}_refresh"] = 0

    @staticmethod
    def get_refresh_status() -> Dict[str, Any]:
        """获取刷新状态信息（调试用）"""
        current_time = time.time()
        processing_jobs = StateManager.get_processing_jobs()

        return {
            "current_time": datetime.fromtimestamp(current_time).strftime("%H:%M:%S"),
            "processing_jobs": list(processing_jobs),
            "last_document_refresh": st.session_state.get("last_document_refresh", 0),
            "last_stats_refresh": st.session_state.get("last_stats_refresh", 0),
            "refresh_triggers": st.session_state.get("refresh_triggers", {}),
            "has_documents_cache": st.session_state.get("documents_cache") is not None,
            "has_stats_cache": st.session_state.get("stats_cache") is not None,
        }


class AutoRefreshMixin:
    """自动刷新混入类，为组件提供自动刷新功能"""

    def __init__(self, component_name: str, cache_duration: float = 30):
        self.component_name = component_name
        self.cache_duration = cache_duration
        StateManager.init_state()

    def should_refresh_data(self) -> bool:
        """检查是否应该刷新数据"""
        return StateManager.should_refresh(self.component_name, self.cache_duration)

    def mark_data_refreshed(self):
        """标记数据已刷新"""
        StateManager.mark_refreshed(self.component_name)

    def get_cached_data(self):
        """获取缓存数据"""
        return StateManager.get_cache(self.component_name)

    def set_cached_data(self, data: Any):
        """设置缓存数据"""
        StateManager.set_cache(self.component_name, data)
        self.mark_data_refreshed()

    def trigger_refresh(self, delay: float = 0):
        """触发组件刷新"""
        StateManager.trigger_refresh(self.component_name, delay)


class RealtimeUpdater:
    """实时更新器，使用JavaScript和Session State实现无刷新更新"""

    @staticmethod
    def create_document_completion_handler(
        job_id: str, component_name: str = "documents"
    ) -> str:
        """创建文档处理完成的JavaScript处理器"""
        js_code = f"""
        <script>
        (function() {{
            // 使用postMessage与Streamlit通信
            function notifyCompletion(documentId) {{
                // 通知Streamlit文档处理完成
                window.parent.postMessage({{
                    type: 'document_completed',
                    job_id: '{job_id}',
                    document_id: documentId || null,
                    component: '{component_name}',
                    timestamp: Date.now()
                }}, '*');
            }}

            // 监听文档处理状态
            const eventSource = new EventSource('/api/documents/status/stream/{job_id}');

            eventSource.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    const status = data.status;

                    if (status === 'completed') {{
                        eventSource.close();
                        notifyCompletion(data.document_id || null);
                    }} else if (status === 'failed') {{
                        eventSource.close();
                        // 失败也需要通知，以便清理状态
                        notifyCompletion(null);
                    }}
                }} catch (e) {{
                    console.error('Failed to parse SSE data:', e);
                }}
            }};

            eventSource.onerror = function() {{
                eventSource.close();
            }};

            // 超时保护
            setTimeout(() => {{
                if (eventSource.readyState !== EventSource.CLOSED) {{
                    eventSource.close();
                }}
            }}, 300000); // 5分钟
        }})();
        </script>
        """
        return js_code

    @staticmethod
    def setup_message_listener():
        """设置JavaScript消息监听器"""
        js_code = """
        <script>
        if (!window.__rag_message_listener_setup) {
            window.__rag_message_listener_setup = true;

            window.addEventListener('message', function(event) {
                if (event.data && event.data.type === 'document_completed') {
                    console.log('Document completion received:', event.data);

                    // 触发Streamlit重新运行特定组件
                    // 这里可以使用Streamlit的实验性功能或custom components
                    if (window.streamlitAPI) {
                        window.streamlitAPI.refresh();
                    }
                }
            });
        }
        </script>
        """
        return js_code
