"""
文档列表组件 - 支持动态刷新
负责显示已上传的文档列表，提供文档操作功能
"""

import logging
import time
from typing import Any, Dict, List

import requests
import streamlit as st
from utils.state_manager import AutoRefreshMixin, StateManager

logger = logging.getLogger(__name__)


class DocumentListComponent(AutoRefreshMixin):
    """文档列表组件类 - 支持动态刷新"""

    def __init__(self, backend_url_internal: str):
        super().__init__("documents", cache_duration=60)  # 60秒缓存
        self.backend_url_internal = backend_url_internal

        # 初始化状态管理
        StateManager.init_state()

    def render(self):
        """渲染文档列表组件 - 支持动态刷新"""
        col1, col2 = st.columns([2, 1])

        with col1:
            st.header("📋 文档列表")

        with col2:
            # 刷新按钮
            if st.button("🔄 刷新", help="刷新文档列表", key="refresh_docs"):
                self.trigger_refresh()
                st.rerun()

        # 获取并显示文档列表
        self._render_document_list()

    def _render_document_list(self):
        """渲染文档列表 - 支持缓存和动态刷新"""
        documents = None

        # 检查是否需要刷新数据
        if self.should_refresh_data():
            try:
                docs_response = requests.get(
                    f"{self.backend_url_internal}/api/documents/"
                )
                if docs_response.status_code == 200:
                    documents = docs_response.json()
                    self.set_cached_data(documents)
                else:
                    st.error("获取文档列表失败")
                    return
            except Exception as e:
                st.error(f"文档列表获取错误: {str(e)}")
                return
        else:
            # 使用缓存数据
            documents = self.get_cached_data()

        if documents:
            if len(documents) > 0:
                # 显示文档总数
                st.caption(f"共 {len(documents)} 个文档")

                for doc in documents:
                    self._render_document_item(doc)
            else:
                st.info("暂无上传的文档")
        else:
            st.warning("无法获取文档列表")

    def _render_document_item(self, doc: Dict[str, Any]):
        """渲染单个文档项"""
        with st.expander(f"📄 {doc['filename']}", expanded=False):
            # 文档信息
            col1, col2 = st.columns([2, 1])

            with col1:
                st.write(f"**文件类型:** {doc['file_type']}")
                st.write(f"**状态:** {doc['status']}")
                st.write(f"**块数量:** {doc.get('chunk_count', 'N/A')}")
                st.write(f"**上传时间:** {doc['upload_time'][:19]}")

            with col2:
                # 操作按钮
                self._render_document_actions(doc)

    def _render_document_actions(self, doc: Dict[str, Any]):
        """渲染文档操作按钮"""
        # 基于此文档提问按钮
        if st.button("🎯 基于此文档提问", key=f"focus_{doc['id']}"):
            st.session_state.selected_doc_id = doc["id"]
            st.success("已限定检索范围到该文档。回到上方聊天区继续提问。")
            time.sleep(1)
            st.rerun()

        # 删除按钮
        if st.button(f"🗑️ 删除", key=f"delete_{doc['id']}"):
            if self._delete_document(doc["id"]):
                st.success("文档删除成功!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("文档删除失败")

    def _delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        try:
            delete_response = requests.delete(
                f"{self.backend_url_internal}/api/documents/{doc_id}"
            )
            return delete_response.status_code == 200
        except Exception as e:
            logger.error(f"删除文档失败: {str(e)}")
            return False

    def get_document_count(self) -> int:
        """获取文档总数"""
        try:
            docs_response = requests.get(f"{self.backend_url_internal}/api/documents/")
            if docs_response.status_code == 200:
                documents = docs_response.json()
                return len(documents)
            return 0
        except Exception:
            return 0
