"""
文件上传组件 - 支持实时更新
"""

from typing import Dict, List, Optional

import requests
import streamlit as st
from utils.state_manager import AutoRefreshMixin, StateManager


class FileUploadComponent(AutoRefreshMixin):
    """文件上传组件类 - 支持实时更新"""

    def __init__(
        self,
        backend_url: str,
        client_url: str = None,
        admin_token: Optional[str] = None,
    ):
        super().__init__("file_upload", cache_duration=10)  # 10秒缓存
        self.backend_url = backend_url  # 服务器端调用用
        self.client_url = client_url or backend_url  # 浏览器端调用用
        self.admin_token = admin_token
        self.supported_formats = [".pdf", ".docx", ".doc", ".txt", ".md"]

        # 初始化状态管理
        StateManager.init_state()

        # 初始化上传状态
        if "uploading" not in st.session_state:
            st.session_state.uploading = False

        # 初始化当前处理的文档ID列表
        # if "processing_documents" not in st.session_state:
        if "upload_processing_docs" not in st.session_state:
            st.session_state.upload_processing_docs = {}

        # 单文件，批量上传控件的key， 用于上传成功后重建组件以清空选择
        if "single_file_upload_key" not in st.session_state:
            st.session_state.single_file_upload_key = 0
        if "multiple_files_upload_key" not in st.session_state:
            st.session_state.multiple_files_upload_key = 0

    def _auth_headers(self) -> Dict[str, str]:
        """构建管理员鉴权请求头。"""
        token = self.admin_token or st.session_state.get("admin_jwt")
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _get_max_file_size_mb(self) -> int:
        """从后端获取允许的最大文件大小，失败回退到50MB"""
        try:
            resp = requests.get(
                f"{self.backend_url}/api/documents/stats/overview",
                headers=self._auth_headers(),
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return int(data.get("storage_info", {}).get("max_file_size_mb", 50))
        except Exception:
            pass
        return 50

    def _calc_upload_timeout(self, size_bytes: int) -> int:
        """根据文件大小动态计算读超时（秒）。更保守：最少180秒，最多1800秒。"""
        try:
            size_mb = max(1, int(size_bytes / (1024 * 1024)))
            # 经验规则：30 秒基数 + 每 MB 5 秒（考虑慢速网络/磁盘写入）
            timeout = 30 + size_mb * 5
            return max(180, min(1800, timeout))
        except Exception:
            return 300

    def _cancel_processing(self, job_id: str, filename: str):
        """取消文档处理（服务端请求 + 浏览器兜底请求）"""
        # === 临时调试开始 ===
        # st.warning(f"[DEBUG] 点击取消: {document_id} - {filename}")
        # === 临时调试结束 ===
        # 先查询任务当前是否仍可取消
        try:
            status_resp = requests.get(
                f"{self.backend_url}/api/documents/cancel-status/{job_id}",
                headers=self._auth_headers(),
                timeout=5,
            )
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                cancellable = status_data.get("cancellable", False)
                current_status = status_data.get("status", "unknown")

                if not cancellable:
                    # 本地清理，避免列表中继续显示
                    try:
                        StateManager.remove_processing_job(job_id)
                    except Exception:
                        pass
                    if job_id in st.session_state.upload_processing_docs:
                        del st.session_state.upload_processing_docs[job_id]

                    if current_status in ("completed", "cancelled"):
                        st.info(f"ℹ️ {filename} 已处理完成或已取消，无需再次取消。")
                    else:
                        st.info(f"ℹ️ 当前任务状态为 {current_status}，暂不可取消。")
                    return
        except Exception:
            # 查询失败时，不阻止后续的取消请求，按原逻辑继续
            pass

        server_ok = False
        try:
            response = requests.post(
                f"{self.backend_url}/api/documents/cancel/{job_id}",
                headers=self._auth_headers(),
                timeout=5,
            )
            if response.status_code == 200 and (response.json() or {}).get("success"):
                server_ok = True
        except Exception:
            server_ok = False

        # 无论服务端是否成功，先本地清理，避免继续轮询造成闪烁
        try:
            StateManager.remove_processing_job(job_id)
        except Exception:
            pass
        if job_id in st.session_state.upload_processing_docs:
            del st.session_state.upload_processing_docs[job_id]

        if server_ok:
            st.success(f"✅ 已取消 {filename} 的处理")
        else:
            st.info(
                f"📝 已尝试发送取消请求：{filename} （如任务已完成，将自动从列表中消失）"
            )

    def _check_processing_status(self, job_id: str, filename: str):
        """检查文档处理状态"""
        try:
            response = requests.get(
                f"{self.backend_url}/api/documents/status/{job_id}",
                headers=self._auth_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                status = result.get("status", "unknown")

                if status == "completed":
                    real_document_id = result.get("document_id")
                    st.success(f"✅ {filename} 处理完成!")
                    chunk_count = result.get("chunk_count", 0)
                    if chunk_count > 0:
                        st.info(f"📄 文档已分割成 {chunk_count} 个块，可用于问答")
                    if real_document_id:
                        st.session_state["last_completed_document_id"] = (
                            real_document_id
                        )
                    # 从处理列表中移除
                    if job_id in st.session_state.upload_processing_docs:
                        del st.session_state.upload_processing_docs[job_id]
                    try:
                        StateManager.remove_processing_job(job_id)
                    except Exception:
                        pass
                elif status == "cancelled":
                    st.warning(f"⚠️ {filename} 已被取消")
                    # 从处理列表中移除
                    if job_id in st.session_state.upload_processing_docs:
                        del st.session_state.upload_processing_docs[job_id]
                    try:
                        StateManager.remove_processing_job(job_id)
                    except Exception:
                        pass
                elif status == "failed":
                    err = result.get("error") or result.get("message") or "未知错误"
                    st.error(f"❌ {filename} 处理失败: {err}")
                    # 可选：显示简单建议
                    st.info(
                        "💡 建议：确认文档未加密、扫描质量清晰；如为扫描版PDF请稍后重试或压缩体积后再传。"
                    )
                    # 从处理列表中移除
                    if job_id in st.session_state.upload_processing_docs:
                        del st.session_state.upload_processing_docs[job_id]
                    try:
                        StateManager.remove_processing_job(job_id)
                    except Exception:
                        pass
                elif status == "processing":
                    progress = result.get("progress")
                    message = result.get("message")
                    if isinstance(progress, int):
                        st.info(f"🔄 {filename} 正在处理中（进度 {progress}%）")
                    else:
                        st.info(f"🔄 {filename} 正在处理中...")
                    if message:
                        st.write(f"📝 {message}")
                    st.info("💡 扫描版PDF处理需要时间，请耐心等待")
                else:
                    st.warning(f"⚠️ {filename} 状态未知: {status}")
            else:
                st.error(f"❌ 无法查询状态: {response.text}")

        except Exception as e:
            st.error(f"❌ 查询状态时出错: {str(e)}")

    def _cleanup_finished_docs(self):
        """清理已经完成/失败/取消的任务，避免一直留在列表里"""
        upload_docs = st.session_state.get("upload_processing_docs", {})
        if not upload_docs:
            return

        to_remove = []

        for job_id, doc_info in list(upload_docs.items()):
            try:
                resp = requests.get(
                    f"{self.backend_url}/api/documents/status/{job_id}",
                    headers=self._auth_headers(),
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    status = (data.get("status") or "").lower()
                    # 后端可能返回: completed / failed / cancelled / not found 等
                    if status in (
                        "completed",
                        "failed",
                        "cancelled",
                        "not_found",
                        "timeout",
                        "error",
                    ):
                        to_remove.append(job_id)
                elif resp.status_code == 404:
                    to_remove.append(job_id)
            except Exception:
                # 查询失败时不做强制删除，等下次再清理
                continue

        for job_id in to_remove:
            if job_id in st.session_state.upload_processing_docs:
                del st.session_state.upload_processing_docs[job_id]
            try:
                StateManager.remove_processing_job(job_id)
            except Exception:
                pass

    def render(self):
        """渲染文件上传界面"""

        st.subheader("📤 上传文档")
        # 渲染前先清理掉已完成的任务
        self._cleanup_finished_docs()

        # 显示正在处理的文档
        upload_docs = st.session_state.get("upload_processing_docs", {})
        if upload_docs:
            with st.expander(f"🔄 正在处理的文档 ({len(upload_docs)})", expanded=True):
                for job_id, doc_info in list(upload_docs.items()):
                    col1, col2, col3 = st.columns([3, 1, 1])

                    with col1:
                        st.write(f"📄 {doc_info['filename']}")

                    with col2:
                        if st.button("📊 状态", key=f"check_{job_id}"):
                            self._check_processing_status(job_id, doc_info["filename"])

                    with col3:
                        if st.button("🛑 取消", key=f"cancel_list_{job_id}"):
                            self._cancel_processing(job_id, doc_info["filename"])

                st.markdown("---")

        # 显示支持的格式
        with st.expander("支持的文件格式", expanded=False):
            for fmt in self.supported_formats:
                st.write(f"• {fmt}")

        # 单文件上传
        st.write("**单文件上传:**")
        uploaded_file = st.file_uploader(
            "选择文件",
            type=["pdf", "docx", "doc", "txt", "md"],
            help="支持PDF、Word、文本和Markdown文件",
            key=f"single_file_upload_key_{st.session_state.single_file_upload_key}",
        )

        if uploaded_file is not None:
            # 显示文件信息
            st.write(f"**文件名:** {uploaded_file.name}")
            st.write(f"**文件大小:** {uploaded_file.size / 1024:.2f} KB")

            # 上传按钮
            upload_disabled = st.session_state.uploading
            if st.button("📤 上传文件", disabled=upload_disabled):
                self._upload_single_file(uploaded_file)

        st.markdown("---")

        # 批量上传
        st.write("**批量上传:**")
        uploaded_files = st.file_uploader(
            "选择多个文件",
            type=["pdf", "docx", "doc", "txt", "md"],
            accept_multiple_files=True,
            help="可以同时选择多个文件进行批量上传",
            key=f"multiple_files_upload_key_{st.session_state.multiple_files_upload_key}",
        )

        if uploaded_files:
            st.write(f"已选择 {len(uploaded_files)} 个文件:")
            for file in uploaded_files:
                st.write(f"• {file.name}")

            upload_disabled = st.session_state.uploading
            if st.button("📤 批量上传", disabled=upload_disabled):
                self._upload_multiple_files(uploaded_files)

    def _upload_single_file(self, uploaded_file):
        """上传单个文件"""
        try:
            # 设置上传状态
            reset_uploader = False
            st.session_state.uploading = True

            # 读取后端限制，超限则提前失败，避免长时间等待
            max_file_size_mb = self._get_max_file_size_mb()
            if uploaded_file.size > max_file_size_mb * 1024 * 1024:
                st.error(
                    f"❌ 文件超过后端限制：{max_file_size_mb} MB。请压缩后重试，或联系管理员提高限制。"
                )
                return

            # 动态计算超时：大文件/扫描PDF需要更长时间传输
            read_timeout = self._calc_upload_timeout(uploaded_file.size)

            with st.spinner(f"正在上传 {uploaded_file.name}..."):
                files = {
                    "file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        uploaded_file.type,
                    )
                }

                # 使用异步上传端点，立即返回
                response = requests.post(
                    f"{self.backend_url}/api/documents/upload-async",
                    files=files,
                    headers=self._auth_headers(),
                    timeout=(10, read_timeout),  # (连接超时, 读取超时)
                )

                if response.status_code == 200:
                    result = response.json()
                    st.success(f"✅ {uploaded_file.name} 上传成功!")

                    if result.get("processing_mode") == "async":
                        # 异步处理模式
                        job_id = result.get("job_id") or result.get("document_id")
                        st.info(f"🔄 文档正在后台异步处理中... 任务ID: `{job_id}`")

                        # 添加到处理队列和session state
                        StateManager.add_processing_job(job_id)
                        st.session_state.upload_processing_docs[job_id] = {
                            "job_id": job_id,
                            "document_id": None,
                            "filename": uploaded_file.name,
                            "upload_time": uploaded_file.size,
                        }

                        # 根据文件大小给出更准确的预估时间
                        file_size_mb = uploaded_file.size / (1024 * 1024)
                        if file_size_mb > 10:
                            st.warning("📋 大型文档处理提示：")
                            st.write("• 🔍 扫描版PDF需要OCR文字识别，可能需要3-10分钟")
                            st.write("• 📊 处理进度将实时显示在下方监听区域")
                            st.write("• ✅ 处理完成后会自动更新文档列表和统计信息")
                            st.write("• ⏰ 如果监听超时，请使用右侧刷新按钮查看结果")
                            st.write("• 🛑 如需取消处理，请点击下方取消按钮")
                        else:
                            st.info(
                                "💡 小型文档通常在1-2分钟内完成处理，完成后会自动更新列表"
                            )

                        # 创建两列：状态查询和取消按钮
                        col1, col2 = st.columns(2)

                        with col1:
                            if st.button(f"📊 查看处理状态", key=f"status_{job_id}"):
                                self._check_processing_status(
                                    job_id, uploaded_file.name
                                )

                        with col2:
                            if st.button(
                                f"🛑 取消处理", key=f"cancel_{job_id}", type="secondary"
                            ):
                                self._cancel_processing(job_id, uploaded_file.name)

                        # 友好提示
                        st.info("💡 **等待期间您可以：**")
                        st.write("• 继续上传其他文档")
                        st.write("• 查看右侧已有文档列表")
                        st.write("• 测试已有文档的问答功能")
                        st.write(
                            "• 如果文档过大或处理时间过长，可以点击取消按钮停止处理"
                        )
                    else:
                        st.info("文档正在后台处理中，请稍候...")

                    # 显示基本信息
                    if result.get("job_id"):
                        st.code(f"任务ID: {result['job_id']}")
                        st.caption("可在“正在处理的文档”中使用“📊 状态”查看最新进度。")
                    if result.get("filename"):
                        st.code(f"文件名: {result['filename']}")
                    # 上传/排队成功后，重置单文件上传控件
                    reset_uploader = True
                elif response.status_code == 409:
                    error_detail = response.json().get("detail", "文件已存在")
                    st.warning(f"⚠️ {error_detail}")
                    reset_uploader = True
                else:
                    error_detail = response.json().get("detail", "未知错误")
                    st.error(f"❌ 上传失败: {error_detail}")

        except requests.exceptions.Timeout:
            st.error(
                "❌ 上传超时：文件较大或网络较慢。建议压缩文件、改为批量上传（超时更长），或稍后重试。"
            )
        except Exception as e:
            st.error(f"❌ 上传出错: {str(e)}")
        finally:
            # 重置上传状态
            st.session_state.uploading = False
            # 根据需要重置上传控件
            if reset_uploader:
                st.session_state.single_file_upload_key += 1

    def _upload_multiple_files(self, uploaded_files: List):
        """批量上传文件"""
        try:
            # 设置上传状态
            st.session_state.uploading = True

            with st.spinner(f"正在批量上传 {len(uploaded_files)} 个文件..."):

                # 准备文件数据
                files = []
                for uploaded_file in uploaded_files:
                    files.append(
                        (
                            "files",
                            (
                                uploaded_file.name,
                                uploaded_file.getvalue(),
                                uploaded_file.type,
                            ),
                        )
                    )

                response = requests.post(
                    f"{self.backend_url}/api/documents/batch-upload",
                    files=files,
                    headers=self._auth_headers(),
                    timeout=900,  # 批量上传增加到15分钟
                )

                if response.status_code == 200:
                    result = response.json()
                    st.success(f"✅ 批量上传完成!")

                    # 显示每个文件的结果
                    results = result.get("results", [])
                    for file_result in results:
                        filename = file_result.get("filename", "未知文件")
                        if file_result.get("success"):
                            st.success(f"✅ {filename}: 上传成功")
                        else:
                            error = file_result.get("error", "未知错误")
                            if "already exists" in error.lower():
                                st.warning(f"⚠️ {filename}: 文件已存在")
                            else:
                                st.error(f"❌ {filename}: {error}")

                    st.info("所有文件正在后台处理中...")

                else:
                    error_detail = response.json().get("detail", "未知错误")
                    st.error(f"❌ 批量上传失败: {error_detail}")

        except requests.exceptions.Timeout:
            st.error("❌ 批量上传超时，请检查网络连接或稍后重试")
        except Exception as e:
            st.error(f"❌ 批量上传出错: {str(e)}")
        finally:
            # 重置上传状态
            st.session_state.uploading = False

    def get_upload_status(self):
        """获取上传状态（预留功能）"""
        # 这里可以实现上传状态检查
        pass
