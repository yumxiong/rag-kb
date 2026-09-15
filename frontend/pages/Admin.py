import os, requests, streamlit as st
from datetime import datetime, timedelta
import jwt
import time


#BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
BACKEND = os.getenv("BACKEND_URL")
st.set_page_config(
    page_title="管理员控制台",
    page_icon="🔐",
    layout="wide"
)


def check_token_validity():
    """检查JWT令牌是否有效"""
    token = st.session_state.get("admin_jwt")
    if not token:
        return False
    
    try:
        # 不验证签名，只检查过期时间
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get('exp')
        if exp:
            exp_time = datetime.fromtimestamp(exp)
            if datetime.now() > exp_time:
                return False
        return True
    except:
        return False

def admin_login_form():
    """管理员登录表单"""
    st.title("🔐 管理员登录")
    st.markdown("---")
    
    with st.form("admin_login"):
        u = st.text_input("用户名", value="admin", placeholder="请输入管理员用户名")
        p = st.text_input("密码", type="password", placeholder="请输入密码")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            submit = st.form_submit_button("🔓 登录", use_container_width=True, type="primary")
        with col2:
            if st.form_submit_button("← 返回主页", use_container_width=True):
                st.switch_page("streamlit_app.py")
        
        if submit:
            if not u or not p:
                st.error("❌ 请填写用户名和密码")
                return
                
            try:
                r = requests.post(
                    f"{BACKEND}/api/auth/login", 
                    data={"username": u, "password": p},
                    timeout=10
                )
                if r.ok:
                    token_data = r.json()
                    st.session_state["admin_jwt"] = token_data["access_token"]
                    st.success("✅ 登录成功！正在跳转...")
                    st.rerun()
                else:
                    error_detail = r.json().get("detail", "未知错误")
                    st.error(f"❌ 登录失败: {error_detail}")
            except requests.exceptions.Timeout:
                st.error("❌ 请求超时，请检查后端服务")
            except requests.exceptions.ConnectionError:
                st.error("❌ 无法连接到后端服务")
            except Exception as e:
                st.error(f"❌ 登录失败: {str(e)}")

def reset_quota():
    """重置用户配额"""
    tok = st.session_state.get("admin_jwt")
    if not tok:
        st.warning("⚠️ 请先登录管理员")
        return
    
    try:
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.post(f"{BACKEND}/api/qa/quota/reset", headers=h, timeout=10)
        
        if r.status_code == 200:
            result = r.json()
            if result.get("success"):
                st.success(f"✅ {result.get('message', '配额重置成功')}")
            else:
                st.warning(f"⚠️ {result.get('message', '配额重置失败')}")
        elif r.status_code == 403:
            st.error("❌ 权限不足，令牌可能已过期，请重新登录")
            del st.session_state["admin_jwt"]
            st.rerun()
        else:
            st.error(f"❌ 操作失败 (HTTP {r.status_code}): {r.text}")
    except Exception as e:
        st.error(f"❌ 请求失败: {str(e)}")

def get_quota_stats():
    """获取配额统计"""
    tok = st.session_state.get("admin_jwt")
    if not tok:
        st.warning("⚠️ 请先登录管理员")
        return
    
    try:
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{BACKEND}/api/qa/quota/stats", headers=h, timeout=10)
        
        if r.status_code == 200:
            stats = r.json()
            st.json(stats)
        elif r.status_code == 403:
            st.error("❌ 权限不足，令牌可能已过期，请重新登录")
            del st.session_state["admin_jwt"]
            st.rerun()
        else:
            st.error(f"❌ 获取失败 (HTTP {r.status_code})")
    except Exception as e:
        st.error(f"❌ 请求失败: {str(e)}")


def render_admin_doc_management(admin_headers: dict):
    """管理员专属：文档列表 + 删除/聚焦操作（折叠在主区底部）。"""
    with st.expander("🗂️ 管理：文档库 / 删除 / 限定检索", expanded=True):
        col_a, col_b, col_c = st.columns([5, 1, 1])
        with col_b:
            if st.button("🔄 刷新", key="admin_refresh_docs", use_container_width=True):
                st.rerun()
        with col_c:
            if st.button("🚪 退出登录", key="admin_logout", use_container_width=True):
                if st.session_state.get("admin_jwt"):
                    del st.session_state["admin_jwt"]
                st.success("已退出登录")
                time.sleep(0.5)
                st.rerun()
        try:
            docs_response = requests.get(
                f"{BACKEND}/api/documents/",
                headers=admin_headers,
                timeout=10,
            )
            if docs_response.status_code == 200:
                documents = docs_response.json() or []
                if not documents:
                    st.caption("暂无文档")
                    return
                for doc in documents:
                    with st.container(border=True):
                        st.markdown(
                            f"**📄 {doc['filename']}**  \n"
                            f"<span style='color:#94a3b8;font-size:12px;'>"
                            f"{doc.get('file_type','')} · {doc.get('chunk_count','N/A')} 块 · "
                            f"上传于 {str(doc.get('upload_time',''))[:19]}</span>",
                            unsafe_allow_html=True,
                        )
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.button("🎯 限定问答到此文档", key=f"focus_{doc['id']}", use_container_width=True):
                                st.session_state.selected_doc_id = doc['id']
                                st.success("已限定到该文档")
                                time.sleep(0.6)
                                st.rerun()
                        with c2:
                            # 检查是否正在确认删除此文档
                            if st.session_state.get(f"pending_delete_{doc['id']}", False):
                                col_confirm, col_cancel = st.columns([1, 1])
                                with col_confirm:
                                    if st.button("✅ 确认删除", key=f"confirm_{doc['id']}", use_container_width=True, type="primary"):
                                        delete_response = requests.delete(
                                            f"{BACKEND}/api/documents/{doc['id']}",
                                            headers=admin_headers,
                                        )
                                        if delete_response.status_code == 200:
                                            result = delete_response.json()
                                            if result.get("details", {}).get("file_deleted"):
                                                st.success("已删除（向量数据和物理文件）")
                                            elif result.get("details", {}).get("error"):
                                                st.warning(f"已删除向量数据，但文件删除失败: {result['details']['error']}")
                                            else:
                                                st.success("已删除（仅向量数据）")
                                            # 清除确认状态
                                            st.session_state[f"pending_delete_{doc['id']}"] = False
                                            time.sleep(0.6)
                                            st.rerun()
                                        elif delete_response.status_code in (401, 403):
                                            st.error("登录已失效，请重新登录")
                                        else:
                                            st.error("删除失败")
                                with col_cancel:
                                    if st.button("❌ 取消", key=f"cancel_{doc['id']}", use_container_width=True):
                                        st.session_state[f"pending_delete_{doc['id']}"] = False
                                        st.rerun()
                            else:
                                if st.button("🗑️ 删除", key=f"delete_{doc['id']}", use_container_width=True):
                                    # 设置确认状态
                                    st.session_state[f"pending_delete_{doc['id']}"] = True
                                    st.warning(f"⚠️ 确认要删除文档「{doc['filename']}」吗？此操作将同时删除向量数据和物理文件。")
                                    st.rerun()
            elif docs_response.status_code in (401, 403):
                st.warning("管理员登录已失效")
            else:
                st.error("获取文档列表失败")
        except Exception as e:
            st.error(f"文档列表获取错误: {str(e)}")


def admin_panel():
    """管理员控制面板"""
    st.title("📊 管理员控制台")
    
    # 顶部状态栏
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.success("✅ 管理员已登录")
    with col2:
        if st.button("🏠 返回主页", use_container_width=True):
            st.switch_page("streamlit_app.py")
    with col3:
        if st.button("🚪 退出登录", use_container_width=True):
            del st.session_state["admin_jwt"]
            st.success("已退出登录")
            st.rerun()
    
    st.markdown("---")
    
    # 功能选项卡
    tab1, tab2, tab3, tab4 = st.tabs(["📊 配额管理", "📈 系统统计", "⚙️ 系统设置", "📚 文档管理"])
    
    with tab1:
        st.subheader("配额管理")
        
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.markdown("#### 重置用户配额")
            st.info("重置当前用户的查询配额（基于IP和User-Agent）")
            if st.button("🔄 重置配额", type="primary", use_container_width=True):
                reset_quota()
        
        with col_b:
            st.markdown("#### 配额统计")
            st.info("查看所有用户的配额使用情况")
            if st.button("📊 查看统计", use_container_width=True):
                get_quota_stats()
    
    with tab2:
        st.subheader("系统统计")
        
        try:
            tok = st.session_state.get("admin_jwt")
            h = {"Authorization": f"Bearer {tok}"} if tok else {}
            response = requests.get(f"{BACKEND}/api/documents/stats/overview", headers=h, timeout=10)
            if response.status_code == 200:
                stats = response.json()
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("📄 总文档数", stats.get("total_documents", 0))
                with col2:
                    st.metric("🔢 总块数", stats.get("total_chunks", 0))
                with col3:
                    storage = stats.get("storage_info", {}) or {}
                    st.metric("� 上传目录", storage.get("upload_dir", "N/A"))
                with col4:
                    st.metric("⚙️ 文件上限", f"{storage.get('max_file_size_mb', 'N/A')} MB")
                
                st.markdown("---")
                st.json(stats)
            elif response.status_code == 401:
                st.error("❌ 未登录或登录已过期，请重新登录")
                if "admin_jwt" in st.session_state:
                    del st.session_state["admin_jwt"]
                st.rerun()
            elif response.status_code == 403:
                st.error("❌ 权限不足，当前账户不是管理员")
            else:
                st.error(f"无法获取系统统计 (HTTP {response.status_code})")
        except Exception as e:
            st.error(f"获取统计失败: {str(e)}")
    
    with tab3:
        st.subheader("系统设置")
        st.info("🚧 系统设置功能开发中...")
        st.markdown("""
        **计划功能：**
        - ⚙️ 修改配额限制
        - 👥 用户管理
        - 🔑 API密钥管理
        - 📝 系统日志查看
        - 🔄 缓存清理
        """)

    with tab4:
        st.subheader("文档管理")
        st.info("🚧 文档管理功能开发中...")
        st.markdown("""
        **计划功能：**
        - 📄 查看所有文档
        - 🗑️ 删除文档
        - 🔍 聚焦检索
        """)
        token = st.session_state.get('admin_jwt')
        if token:
            render_admin_doc_management({"Authorization": f"Bearer {token}"})


# 主逻辑
if not st.session_state.get("admin_jwt") or not check_token_validity():
    if st.session_state.get("admin_jwt"):
        # 令牌已过期
        st.warning("⚠️ 登录已过期，请重新登录")
        del st.session_state["admin_jwt"]
    admin_login_form()
else:
    admin_panel()
