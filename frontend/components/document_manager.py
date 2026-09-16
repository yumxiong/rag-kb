"""
文档管理组件 - 支持动态刷新
负责文档上传、统计信息显示和配额信息展示
"""

import logging
from typing import Any, Dict

import requests
import streamlit as st
from utils.settings_loader import SettingsStatus
from utils.state_manager import AutoRefreshMixin, StateManager

logger = logging.getLogger(__name__)


class DocumentManagerComponent(AutoRefreshMixin):
    """文档管理组件类 - 支持动态刷新"""

    def __init__(self, backend_url_internal: str, backend_url_client: str):
        super().__init__("stats", cache_duration=30)  # 30秒缓存
        self.backend_url_internal = backend_url_internal
        self.backend_url_client = backend_url_client

        # 初始化状态管理
        StateManager.init_state()

    def render(self):
        """渲染文档管理组件"""
        st.header("📄 文档管理")

        # 文档上传组件
        self._render_file_upload()

        st.markdown("---")

        # 统计信息
        self._render_statistics()

        # 配额信息
        self._render_quota_info()

    def _render_file_upload(self):
        """渲染文件上传组件"""
        # 使用现有的FileUploadComponent
        from components.file_upload import FileUploadComponent

        file_upload_component = FileUploadComponent(
            self.backend_url_internal, self.backend_url_client
        )
        file_upload_component.render()

    def _render_statistics(self):
        """渲染统计信息 - 支持缓存和动态刷新"""
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            st.subheader("📊 统计信息")

        with col3:
            # 手动刷新按钮
            if st.button("🔄", help="刷新统计信息", key="refresh_stats"):
                self.trigger_refresh()
                st.rerun()

        # 检查是否需要刷新数据
        stats = None
        if self.should_refresh_data():
            try:
                stats_response = requests.get(
                    f"{self.backend_url_internal}/api/documents/stats/overview"
                )
                if stats_response.status_code == 200:
                    stats = stats_response.json()
                    self.set_cached_data(stats)
                else:
                    st.error("获取统计信息失败")
                    return
            except Exception as e:
                st.error(f"统计信息获取错误: {str(e)}")
                return
        else:
            # 使用缓存数据
            stats = self.get_cached_data()

        if stats:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("总文档数", stats.get("total_documents", 0))
            with col2:
                st.metric("总块数", stats.get("total_chunks", 0))

            # 显示处理中的文档数量
            processing_count = len(StateManager.get_processing_jobs())
            if processing_count > 0:
                st.info(f"🔄 {processing_count} 个文档正在处理中...")
        else:
            st.warning("暂无统计数据")

    def _render_quota_info(self):
        """渲染配额信息"""
        st.subheader("📊 使用配额")
        try:
            if (
                st.session_state.get("settings_status")
                == SettingsStatus.RESTORING.value
            ):
                st.info("正在从浏览器恢复设置…")
            else:
                # 有自定义Key：直接提示无限制
                if st.session_state.get("byok_api_key"):
                    st.success("🔑 使用自定义 API Key - 不受试用配额限制")
                else:
                    # 无自定义Key：查询后端配额
                    headers = self._build_byok_headers()
                    quota_response = requests.get(
                        f"{self.backend_url_internal}/api/qa/quota", headers=headers
                    )
                    if quota_response.status_code == 200:
                        qi = quota_response.json()
                        if not qi.get("quota_enabled", True):
                            st.info("当前未启用配额限制")
                        else:
                            if qi.get("has_custom_key"):
                                st.success("🔑 使用自定义 API Key - 不受试用配额限制")
                            else:
                                used = qi.get("used_count", 0)
                                limit = qi.get("daily_limit", 0)
                                remaining = qi.get("remaining", 0)
                                msg = qi.get("message")

                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric("已使用", used)
                                with col2:
                                    st.metric("每日限额", limit)
                                with col3:
                                    st.metric("剩余次数", remaining)

                                if msg:
                                    st.caption(msg)
                    else:
                        st.info("无法获取配额信息")
        except Exception as e:
            st.warning(f"配额信息获取错误: {str(e)}")

    def _build_byok_headers(self) -> Dict[str, str]:
        """构建BYOK请求头"""
        headers = {}
        api_key = st.session_state.get("byok_api_key", "").strip()
        provider = st.session_state.get("byok_provider", "").strip()
        base_url = st.session_state.get("byok_base_url", "").strip()
        model = st.session_state.get("byok_model", "").strip()

        if api_key:
            headers["LLM-Api-Key"] = api_key
        if provider:
            headers["LLM-Provider"] = provider
        if base_url:
            headers["LLM-Base-URL"] = base_url
        if model:
            headers["LLM-Model"] = model

        return headers
