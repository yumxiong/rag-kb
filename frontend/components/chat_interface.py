"""
聊天界面组件
"""

from html import escape
from typing import Optional

import requests
import streamlit as st

from frontend.utils.anonymous_session import (
    AnonymousConnectionError,
    ensure_identity,
    identity_headers,
    recover_identity,
)

MAX_QUESTION_LENGTH = 2000
DEFAULT_MAX_SOURCES = 3
MAX_SOURCES_LIMIT = 5


class ChatInterface:
    """聊天界面组件类"""

    def __init__(self, backend_url: str, admin_token: Optional[str] = None):
        self.backend_url = backend_url
        self.admin_token = admin_token

        # 初始化会话状态
        if "messages" not in st.session_state:
            st.session_state.messages = []
        if "is_processing" not in st.session_state:
            st.session_state.is_processing = False
        # 检索范围：None 表示全库
        if "selected_doc_id" not in st.session_state:
            st.session_state.selected_doc_id = None
        # 清空对话时是否重置检索范围（可配置）
        if "reset_scope_on_clear" not in st.session_state:
            st.session_state.reset_scope_on_clear = True

    def render(self):
        """渲染聊天界面"""

        try:
            ensure_identity(st.session_state, self.backend_url)
        except AnonymousConnectionError:
            st.caption(st.session_state.get("anonymous_error", "暂时无法连接会话。"))

        has_messages = bool(st.session_state.messages)

        if not has_messages:
            # 欢迎卡片 + 建议问题（仅在尚未提问时显示）
            self._render_welcome_and_suggestions()
        else:
            # 已有对话：渲染历史 + 顶部操作条
            self._render_chat_history()
            top_c1, top_c2 = st.columns([5, 1])
            with top_c2:
                if st.button("🗑️ 清空对话", key="clear_chat", use_container_width=True):
                    st.session_state.messages = []
                    if st.session_state.get("reset_scope_on_clear", True):
                        st.session_state.selected_doc_id = None
                    st.rerun()

        # 输入区域 + 高级设置
        self._render_input_area()

    def _render_chat_history(self):
        """渲染聊天历史"""

        # 聊天容器
        chat_container = st.container()

        with chat_container:
            # 显示历史消息
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])

                    # 如果是助手回答，显示来源文档
                    if message["role"] == "assistant" and "sources" in message:
                        self._render_sources(message["sources"])

    def _render_sources(self, sources):
        """渲染来源文档 - 优化为卡片式设计"""
        if sources:
            with st.expander("📚 参考来源", expanded=True):
                for i, source in enumerate(sources, 1):
                    # 使用容器创建卡片效果
                    with st.container():
                        st.markdown(
                            f"""
                        <div style="
                            background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
                            border-left: 4px solid #667eea;
                            padding: 12px 16px;
                            border-radius: 8px;
                            margin-bottom: 12px;
                        ">
                            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                <span style="
                                    background: #667eea;
                                    color: white;
                                    width: 24px;
                                    height: 24px;
                                    border-radius: 50%;
                                    display: inline-flex;
                                    align-items: center;
                                    justify-content: center;
                                    font-weight: bold;
                                    font-size: 12px;
                                    margin-right: 10px;
                                ">{i}</span>
                                <strong style="color: #667eea;">{escape(source['document_name'])}</strong>
                            </div>
                        </div>
                        """,
                            unsafe_allow_html=True,
                        )

                        # 内容预览
                        content_preview = (
                            source["content"][:200] + "..."
                            if len(source["content"]) > 200
                            else source["content"]
                        )
                        st.markdown(
                            f"<div style='padding-left: 34px; color: #666; font-size: 0.9em;'>{escape(content_preview)}</div>",
                            unsafe_allow_html=True,
                        )

                        # 元数据
                        if source.get("page_number"):
                            st.caption(f"📄 页码: {source['page_number']}")

                        # 查看完整内容
                        if len(source["content"]) > 200:
                            with st.expander("查看完整内容", expanded=False):
                                st.text(source["content"])

                        st.markdown("<br>", unsafe_allow_html=True)

    def _fetch_suggestions(self):
        """获取问题建议 + 文档数量。"""
        try:
            response = requests.get(f"{self.backend_url}/api/qa/suggestions", timeout=5)
            if response.status_code == 200:
                data = response.json() or {}
                return data.get("suggestions", []), data.get("document_count", 0)
        except Exception:
            pass
        return [], None

    def _render_welcome_and_suggestions(self):
        """空对话状态：欢迎卡片 + 胶囊式示例问题。"""
        suggestions, doc_count = self._fetch_suggestions()

        if doc_count is None:
            st.warning("暂时无法获取示例问题，请稍后刷新。你也可以直接输入问题。")
            return

        if doc_count == 0:
            # 空知识库：友好引导
            st.markdown(
                """
                <div style="background:linear-gradient(135deg,#fef3c7 0%,#fde68a 100%);
                            border:1px solid #fcd34d;border-radius:14px;padding:20px 22px;margin:8px 0 18px 0;">
                  <div style="font-size:1.05rem;font-weight:600;color:#92400e;margin-bottom:6px;">
                    📭 知识库目前是空的
                  </div>
                  <div style="font-size:13px;color:#78350f;line-height:1.6;">
                    管理员还没有上传任何文档。如果你是访客，请稍后再来；如果你是管理员，请从侧边栏上传文档后开始体验。
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        # 欢迎卡片
        st.markdown(
            f"""
            <div style="background:linear-gradient(135deg,#eef2ff 0%,#f5f3ff 100%);
                        border:1px solid #e0e7ff;border-radius:14px;padding:20px 22px;
                        margin:8px 0 16px 0;">
              <div style="font-size:1.1rem;font-weight:600;color:#312e81;margin-bottom:6px;">
                👋 从 {doc_count} 份文档中检索信息，为你解答
              </div>
              <div style="font-size:13px;color:#4338ca;line-height:1.6;">
                左侧栏列出了当前可问答的文档范围。在下方输入框直接提问，或点击下面的建议快速开始。
                回答下方可查看检索来源；请展开原文核对，资料不足时不应据此推断。
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 胶囊式建议问题
        if suggestions:
            st.markdown(
                "<div style='font-size:13px;color:#64748b;margin:4px 0 8px 2px;font-weight:500;'>💡 试试这些问题</div>",
                unsafe_allow_html=True,
            )
            top = suggestions[:4]
            cols = st.columns(2)
            for i, suggestion in enumerate(top):
                with cols[i % 2]:
                    if st.button(
                        suggestion,
                        key=f"suggestion_{i}",
                        use_container_width=True,
                        disabled=(
                            st.session_state.is_processing
                            or not st.session_state.get("anonymous_token")
                        ),
                    ):
                        # Demo questions span the corpus, including two-source evidence.
                        st.session_state.selected_doc_id = None
                        self._process_question(suggestion)

    def _fetch_scope_docs(self) -> list:
        """获取检索范围下拉数据：管理员使用完整列表（含 id），访客使用公开列表。"""
        # 管理员：使用受限端点取得带 ID 的列表
        if self.admin_token:
            try:
                headers = {"Authorization": f"Bearer {self.admin_token}"}
                resp = requests.get(
                    f"{self.backend_url}/api/documents/", headers=headers, timeout=5
                )
                if resp.status_code == 200:
                    docs = resp.json() or []
                    return [
                        {"id": d.get("id"), "filename": d.get("filename", "")}
                        for d in docs
                    ]
            except Exception:
                pass
        # 访客：只能看到 filename（无法切换检索范围），返回空列表 -> 仅显示"全库"
        try:
            lib = st.session_state.get("_public_library") or {}
            return [
                {"id": None, "filename": d.get("filename", "")}
                for d in (lib.get("documents") or [])
            ]
        except Exception:
            return []

    def _render_input_area(self):
        """渲染输入区域。"""

        # 问题输入（主输入框，最显眼）
        user_question = st.chat_input(
            "向 AtlasDesk 文档提问…",
            disabled=(
                st.session_state.is_processing
                or not st.session_state.get("anonymous_token")
            ),
            max_chars=MAX_QUESTION_LENGTH,
        )

        if user_question:
            self._process_question(user_question)

        # 工具栏：检索范围 + 高级设置（默认折叠，单行排布）
        toolbar_c1, toolbar_c2 = st.columns([1, 1])
        with toolbar_c1:
            with st.expander("🔎 检索范围", expanded=False):
                docs = self._fetch_scope_docs()
                has_ids = any(d.get("id") for d in docs)
                if not has_ids:
                    # 访客模式：只能浏览，不能切换
                    st.caption("以下文档当前都参与检索：")
                    for d in docs[:6]:
                        st.caption(f"• {d['filename']}")
                    if len(docs) > 6:
                        st.caption(f"… 共 {len(docs)} 个文档")
                    st.caption("（如需限定到单个文档，请联系管理员）")
                else:
                    options = ["全库（默认）"] + [
                        f"{d['filename']} ({(d.get('id') or '')[:8]})" for d in docs
                    ]
                    idx = 0
                    sel_id = st.session_state.selected_doc_id
                    if sel_id:
                        for i, d in enumerate(docs, start=1):
                            if d.get("id") == sel_id:
                                idx = i
                                break
                    choice = st.selectbox(
                        "限定到指定文档",
                        options=options,
                        index=idx,
                        label_visibility="collapsed",
                        help="选择文档后，检索仅基于该文档；选择全库则跨文档检索。",
                    )
                    if choice == "全库（默认）":
                        st.session_state.selected_doc_id = None
                    else:
                        sel_index = options.index(choice) - 1
                        if 0 <= sel_index < len(docs):
                            st.session_state.selected_doc_id = docs[sel_index].get("id")

        with toolbar_c2:
            with st.expander("⚙️ 高级设置", expanded=False):
                max_sources = st.slider(
                    "最大来源文档数量",
                    min_value=1,
                    max_value=MAX_SOURCES_LIMIT,
                    value=DEFAULT_MAX_SOURCES,
                    help="控制回答时参考的文档数量",
                )
                st.session_state.max_sources = max_sources
                reset_scope = st.checkbox(
                    "清空对话时重置检索范围",
                    value=getattr(st.session_state, "reset_scope_on_clear", True),
                )
                st.session_state.reset_scope_on_clear = reset_scope

        st.caption(f"问题长度上限：{MAX_QUESTION_LENGTH} 字符")

    def _validate_question(self, question: str) -> Optional[str]:
        """验证问题长度"""
        normalized_question = question.strip()
        if not normalized_question:
            st.warning("⚠️ 请输入有效的问题")
            return None
        if len(normalized_question) > MAX_QUESTION_LENGTH:
            st.warning(f"⚠️ 问题长度不能超过{MAX_QUESTION_LENGTH}字符，请精简后重试")
            return None
        return normalized_question

    def _process_question(self, question: str):
        """处理用户问题"""

        validated_question = self._validate_question(question)
        if validated_question is None:
            return

        st.session_state.messages.append({"role": "user", "content": question})

        # 显示用户消息
        with st.chat_message("user"):
            st.write(validated_question)

        # 设置处理状态
        st.session_state.is_processing = True

        # 显示助手思考中
        with st.chat_message("assistant"):
            with st.spinner("正在思考中..."):
                try:
                    # 调用问答API
                    max_sources = getattr(
                        st.session_state, "max_sources", DEFAULT_MAX_SOURCES
                    )

                    response = requests.post(
                        f"{self.backend_url}/api/qa/ask",
                        json=(
                            (
                                lambda payload: (
                                    (
                                        payload.update(
                                            {
                                                "document_id": st.session_state.selected_doc_id
                                            }
                                        )
                                        if st.session_state.get("selected_doc_id")
                                        else None
                                    ),
                                    payload,
                                )
                            )(
                                {
                                    "question": validated_question,
                                    "max_sources": max_sources,
                                }
                            )[
                                1
                            ]
                        ),
                        headers=self._build_byok_headers(),
                        timeout=75,
                    )

                    if response.status_code == 200:
                        result = response.json()
                        answer = result.get("answer", "抱歉，我无法回答这个问题。")
                        sources = result.get("sources", [])
                        processing_time = result.get("processing_time", 0)

                        # 显示答案
                        st.write(answer)

                        # 显示处理时间
                        st.caption(f"⏱️ 处理时间: {processing_time:.2f}秒")

                        # 显示来源
                        self._render_sources(sources)

                        # 添加助手消息到历史
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": answer,
                                "sources": sources,
                                "processing_time": processing_time,
                            }
                        )

                        # 反馈按钮
                        self._render_feedback(question, answer)

                    else:
                        recovered = recover_identity(
                            st.session_state, self.backend_url, response
                        )
                        try:
                            error_detail = response.json().get("detail", "请求失败")
                            if isinstance(error_detail, dict):
                                error_detail = error_detail.get(
                                    "message", "服务暂不可用"
                                )
                        except ValueError:
                            error_detail = f"服务暂时不可用（HTTP {response.status_code}），请稍后重试"
                        error_msg = f"❌ 处理问题时出错: {error_detail}"
                        if recovered:
                            error_msg = "会话已重新连接，请再次主动提交问题。"
                        st.error(error_msg)

                        st.session_state.messages.append(
                            {"role": "assistant", "content": error_msg}
                        )

                except requests.exceptions.Timeout:
                    timeout_msg = "❌ 请求超时，请稍后重试"
                    st.error(timeout_msg)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": timeout_msg}
                    )

                except Exception as e:
                    error_msg = f"❌ 发生错误: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_msg}
                    )

                finally:
                    # 重置处理状态
                    st.session_state.is_processing = False

        # 刷新页面以显示新消息
        st.rerun()

    def _render_feedback(self, question: str, answer: str):
        """渲染反馈区域"""

        st.write("**这个回答有帮助吗？**")

        col1, col2, col3, col4, col5 = st.columns(5)

        feedback_given = False

        with col1:
            if st.button("⭐", key=f"feedback_1_{len(st.session_state.messages)}"):
                self._submit_feedback(question, answer, 1)
                feedback_given = True

        with col2:
            if st.button("⭐⭐", key=f"feedback_2_{len(st.session_state.messages)}"):
                self._submit_feedback(question, answer, 2)
                feedback_given = True

        with col3:
            if st.button("⭐⭐⭐", key=f"feedback_3_{len(st.session_state.messages)}"):
                self._submit_feedback(question, answer, 3)
                feedback_given = True

        with col4:
            if st.button(
                "⭐⭐⭐⭐", key=f"feedback_4_{len(st.session_state.messages)}"
            ):
                self._submit_feedback(question, answer, 4)
                feedback_given = True

        with col5:
            if st.button(
                "⭐⭐⭐⭐⭐", key=f"feedback_5_{len(st.session_state.messages)}"
            ):
                self._submit_feedback(question, answer, 5)
                feedback_given = True

        if feedback_given:
            st.success("感谢您的反馈！")

    def _submit_feedback(self, question: str, answer: str, rating: int):
        """提交用户反馈"""
        try:
            requests.post(
                f"{self.backend_url}/api/qa/feedback",
                json={"question": question, "answer": answer, "rating": rating},
                timeout=10,
            )
        except Exception as e:
            st.error(f"反馈提交失败: {str(e)}")

    def _build_byok_headers(self) -> dict:
        """根据侧边栏保存的 BYOK 设置构建请求头（仅保存在本地会话）"""
        headers = identity_headers(st.session_state, self.backend_url)
        try:
            api_key = getattr(st.session_state, "byok_api_key", "").strip()
            provider = getattr(st.session_state, "byok_provider", "").strip()
            base_url = getattr(st.session_state, "byok_base_url", "").strip()
            model = getattr(st.session_state, "byok_model", "").strip()
            if api_key:
                headers["LLM-Api-Key"] = api_key
            if provider:
                headers["LLM-Provider"] = provider
            if base_url:
                headers["LLM-Base-URL"] = base_url
            if model:
                headers["LLM-Model"] = model
        except Exception:
            pass
        return headers

    def get_chat_history(self):
        """获取聊天历史"""
        return st.session_state.messages

    def clear_chat_history(self):
        """清空聊天历史"""
        st.session_state.messages = []
