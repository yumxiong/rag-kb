"""
Streamlit前端应用
"""

import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime

import requests
import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)


def get_git_version_info_frontend():
    """在Streamlit前端获取git版本信息"""
    try:
        # 在应用的根目录执行git命令
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_root
            )
            .strip()
            .decode("utf-8")
        )
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project_root)
            .strip()
            .decode("utf-8")[:7]
        )
        return f"v: {branch} ({commit})"
    except Exception:
        return "v: unknown"


def detect_provider_from_api_key(api_key: str) -> str:
    """根据API Key格式自动检测提供商"""
    if not api_key:
        return "openai"

    api_key = api_key.strip()

    # Zhipu API keys have the format: xxxxxxxx.xxxxxxxxxxxxxx (32 char hex + . + 16 chars)
    # Check this first since it has a unique format
    if "." in api_key and len(api_key.split(".")) == 2:
        parts = api_key.split(".")
        if len(parts[0]) == 32 and len(parts[1]) == 16:
            return "zhipu"

    # OpenAI API keys start with "sk-" and are longer (51-55 chars typically)
    if api_key.startswith("sk-") and len(api_key) >= 48:
        return "openai"

    # DeepSeek API keys start with "sk-" and are shorter than OpenAI keys
    if api_key.startswith("sk-") and len(api_key) <= 47:
        return "deepseek"

    # Default to openai if pattern doesn't match
    return "openai"


# 尝试导入streamlit-js-eval，如果没有则使用备用方案
try:
    from streamlit_js_eval import get_geolocation, streamlit_js_eval

    JS_EVAL_AVAILABLE = True
except ImportError:
    JS_EVAL_AVAILABLE = False
    st.warning(
        "⚠️ 建议安装 streamlit-js-eval 以获得更好的设置持久化体验: pip install streamlit-js-eval"
    )

from components.chat_interface import ChatInterface
from components.file_upload import FileUploadComponent
from utils.settings_loader import SettingsStatus
from utils.settings_loader import load_user_settings as load_user_settings_shared
from utils.state_manager import StateManager

# 配置页面
st.set_page_config(
    page_title="RAG知识库",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)


def add_floating_admin_button():
    """添加右上角浮动的管理员入口（低调样式）"""
    is_logged_in = st.session_state.get("admin_jwt") is not None

    # 登录状态：醒目主题色；未登录：低对比度灰色描边按钮
    if is_logged_in:
        bg_color = "#10b981"
        button_text = "✓"
        tooltip_text = "进入管理面板"
        border = "2px solid rgba(16,185,129,0.25)"
        color = "#ffffff"
    else:
        bg_color = "#ffffff"
        button_text = "⚙"
        tooltip_text = "管理员入口"
        border = "1px solid rgba(15,23,42,0.12)"
        color = "#475569"

    button_html = f"""
    <style>
    /* 隐藏侧边栏中的页面导航 */
    [data-testid="stSidebarNav"] {{
        display: none !important;
    }}
    
    /* 浮动按钮主体 */
    .floating-admin-btn {{
        position: fixed;
        top: 18px;
        right: 18px;
        z-index: 999999;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: {bg_color};
        color: {color};
        box-shadow: 0 1px 2px rgba(15,23,42,0.06);
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.2s ease;
        text-decoration: none;
        font-size: 18px;
        font-weight: 600;
        border: {border};
    }}
    
    /* 悬停效果 */
    .floating-admin-btn:hover {{
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(15,23,42,0.12);
        border-color: rgba(99,102,241,0.4);
        color: #6366f1;
    }}
    
    /* 点击效果 */
    .floating-admin-btn:active {{
        transform: translateY(-1px) scale(0.98);
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }}
    
    /* 提示文本 */
    .admin-tooltip {{
        position: fixed;
        top: 26px;
        right: 68px;
        background: rgba(38, 39, 48, 0.95);
        color: white;
        padding: 8px 14px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        white-space: nowrap;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.25s ease, transform 0.25s ease;
        z-index: 999998;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        transform: translateX(10px);
    }}
    
    /* 提示文本箭头 */
    .admin-tooltip::after {{
        content: '';
        position: absolute;
        right: -6px;
        top: 50%;
        transform: translateY(-50%);
        border-left: 6px solid rgba(38, 39, 48, 0.95);
        border-top: 6px solid transparent;
        border-bottom: 6px solid transparent;
    }}
    
    /* 悬停时显示提示 */
    .floating-admin-btn:hover + .admin-tooltip {{
        opacity: 1;
        transform: translateX(0);
    }}
    
    /* 登录状态指示器（小绿点） */
    .status-indicator {{
        position: absolute;
        top: -2px;
        right: -2px;
        width: 10px;
        height: 10px;
        background: #10b981;
        border-radius: 50%;
        border: 2px solid white;
        display: {'block' if is_logged_in else 'none'};
    }}
    
    @keyframes pulse {{
        0%, 100% {{
            transform: scale(1);
            opacity: 1;
        }}
        50% {{
            transform: scale(1.1);
            opacity: 0.8;
        }}
    }}
    
    /* 响应式设计 */
    @media (max-width: 768px) {{
        .floating-admin-btn {{
            width: 36px;
            height: 36px;
            top: 14px;
            right: 14px;
            font-size: 16px;
        }}
        .admin-tooltip {{
            font-size: 12px;
            padding: 6px 10px;
        }}
    }}
    </style>
    
    <a href="/Admin" target="_self" class="floating-admin-btn" title="{tooltip_text}">
        {button_text}
        <span class="status-indicator"></span>
    </a>
    <div class="admin-tooltip">{tooltip_text}</div>
    """

    st.markdown(button_html, unsafe_allow_html=True)


# 配置API端点
# Docker环境中，前端容器使用backend服务名，但浏览器需要使用localhost
BACKEND_URL_INTERNAL = os.getenv("BACKEND_URL", "http://localhost:8000")  # 服务器端调用
BACKEND_URL_CLIENT = os.getenv(
    "BACKEND_URL_CLIENT", "http://localhost:8000"
)  # 浏览器端调用

# 文档管理接口已改为管理员鉴权，禁用浏览器侧匿名轮询。
# 如需恢复前端实时更新，请在后续改造中为浏览器请求加入安全鉴权机制。


def init_websocket_connection(client_id: str):
    """使用JS注入WebSocket连接"""
    ws_url = f"{BACKEND_URL_CLIENT.replace('http', 'ws')}/ws/{client_id}"

    js_code = f"""
    <script>
    (function() {{
        if (!window.ragWs) {{
            console.log('Attempting to connect WebSocket to {ws_url}');
            const ws = new WebSocket('{ws_url}');
            ws.onopen = () => console.log('WebSocket connection established.');
            ws.onclose = () => console.log('WebSocket connection closed.');
            ws.onerror = (error) => console.error('WebSocket error:', error);
            window.ragWs = ws;
        }}
    }})();
    </script>
    """
    components.html(js_code, height=0, width=0)


def build_byok_headers() -> dict:
    """根据当前会话中的 BYOK 设置构造请求头"""
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


def check_backend_connection():
    """检查后端连接"""
    try:
        response = requests.get(f"{BACKEND_URL_INTERNAL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def load_with_html_fallback():
    """Deprecated: use utils.settings_loader._load_with_html_fallback via shared loader."""
    pass


def _normalize_local_storage_value(value: str, default: str = "") -> str:
    """Deprecated: normalization is handled in utils.settings_loader."""
    return value if isinstance(value, str) else default


def _read_browser_settings() -> dict | None:
    """Deprecated: reading handled in utils.settings_loader."""
    return None


def load_user_settings():
    """统一入口：使用共享加载器实现设置恢复与重试。"""
    load_user_settings_shared()


def save_user_settings():
    """保存用户设置到浏览器localStorage"""
    api_key = st.session_state.get("byok_api_key", "")
    provider = st.session_state.get("byok_provider", "openai")
    base_url = st.session_state.get("byok_base_url", "")
    model = st.session_state.get("byok_model", "gpt-3.5-turbo")

    timestamp = datetime.utcnow().isoformat()

    js_template = """
    localStorage.setItem('rag_byok_api_key', {api_key});
    localStorage.setItem('rag_byok_provider', {provider});
    localStorage.setItem('rag_byok_base_url', {base_url});
    localStorage.setItem('rag_byok_model', {model});
    localStorage.setItem('rag_byok_last_saved', {timestamp});
    """

    js_expr = js_template.format(
        api_key=json.dumps(api_key),
        provider=json.dumps(provider),
        base_url=json.dumps(base_url),
        model=json.dumps(model),
        timestamp=json.dumps(timestamp),
    )

    if JS_EVAL_AVAILABLE:
        try:
            streamlit_js_eval(
                js_expressions=js_expr, key="save_ls_byok", want_output=False
            )
            logger.info(
                "BYOK settings saved via JS eval: provider=%s, api_key_exists=%s",
                provider,
                bool(api_key),
            )
            return
        except Exception as exc:
            logger.warning(f"JS-eval save failed, fallback to HTML: {exc}")

    components.html(
        f"""
        <script>
        (function() {{
            try {{
                {js_expr}
            }} catch (e) {{
                console.error('Failed to save BYOK settings:', e);
            }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )
    logger.info(
        "BYOK settings saved via HTML fallback: provider=%s, api_key_exists=%s",
        provider,
        bool(api_key),
    )


def clear_user_settings():
    """清除用户设置（覆盖 top 与当前上下文的 localStorage）"""
    if JS_EVAL_AVAILABLE:
        try:
            import time

            from streamlit_js_eval import streamlit_js_eval

            js_code = """
            (function(){
              try{
                const getLS = () => { try { return (window.top && window.top.localStorage) ? window.top.localStorage : localStorage; } catch(e) { return localStorage; } };
                const ls = getLS();
                ['rag_byok_api_key','rag_byok_provider','rag_byok_base_url','rag_byok_model','rag_byok_last_saved'].forEach(k=>{ try{ ls.removeItem(k); }catch(_){} });
                ['rag_byok_api_key','rag_byok_provider','rag_byok_base_url','rag_byok_model','rag_byok_last_saved'].forEach(k=>{ try{ localStorage.removeItem(k); }catch(_){} });
                console.log('All BYOK settings cleared');
              }catch(e){ console.error('clear error', e); }
            })();
            """
            streamlit_js_eval(
                js_expressions=js_code,
                key=f"clear_all_settings_{int(time.time()*1000)}",
                want_output=False,
            )
        except Exception as e:
            logger.warning(f"清除设置时出错: {e}")
    else:
        clear_js = """
        <script>
        (function(){
          try{
            ['rag_byok_api_key','rag_byok_provider','rag_byok_base_url','rag_byok_model','rag_byok_last_saved'].forEach(k=>{ try{ localStorage.removeItem(k); }catch(_){} });
            if (window.top && window.top!==window && window.top.localStorage){
              ['rag_byok_api_key','rag_byok_provider','rag_byok_base_url','rag_byok_model','rag_byok_last_saved'].forEach(k=>{ try{ window.top.localStorage.removeItem(k); }catch(_){} });
            }
            console.log('BYOK settings cleared (fallback)');
          }catch(e){ console.error('fallback clear error', e); }
        })();
        </script>
        """
        components.html(clear_js, height=0, width=0)


def display_quota_info():
    """以进度条形式展示当日体验额度。"""
    try:
        if st.session_state.get("settings_status") == SettingsStatus.RESTORING.value:
            st.caption("正在从浏览器恢复设置…")
            return

        if st.session_state.get("byok_api_key"):
            st.markdown(
                """
                <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:10px 12px;">
                  <div style="font-size:13px;color:#065f46;font-weight:600;">🔑 已接入自定义 API Key</div>
                  <div style="font-size:12px;color:#047857;margin-top:2px;">不受试用配额限制</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        response = requests.get(
            f"{BACKEND_URL_INTERNAL}/api/qa/quota",
            headers=build_byok_headers(),
            timeout=5,
        )

        if response.status_code != 200:
            st.caption("无法获取配额信息")
            return

        quota_info = response.json()

        if not quota_info.get("quota_enabled", True):
            st.caption("当前未启用配额限制")
            return

        used = int(quota_info.get("used_count", 0) or 0)
        limit_raw = quota_info.get("daily_limit", 0)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 0
        remaining = max(limit - used, 0)
        ratio = (used / limit) if limit > 0 else 0.0

        st.markdown(
            f"""
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;">
              <div style="display:flex;justify-content:space-between;align-items:baseline;">
                <span style="font-size:13px;color:#475569;font-weight:600;">🎁 今日免费体验额度</span>
                <span style="font-size:12px;color:#64748b;">{used} / {limit}</span>
              </div>
              <div style="margin-top:8px;height:6px;background:#e2e8f0;border-radius:999px;overflow:hidden;">
                <div style="width:{min(ratio*100, 100):.1f}%;height:100%;background:linear-gradient(90deg,#6366f1,#8b5cf6);"></div>
              </div>
              <div style="margin-top:8px;font-size:12px;color:#64748b;">剩余 <b style="color:#6366f1;">{remaining}</b> 次 · 超额可在「⚙️ 高级」中接入自己的 Key</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    except Exception as e:
        st.caption(f"配额信息获取错误: {str(e)}")


def fetch_public_library() -> dict:
    """获取只读知识库目录（无需登录）。失败时返回空结构。"""
    try:
        resp = requests.get(f"{BACKEND_URL_INTERNAL}/api/documents/library", timeout=5)
        if resp.status_code == 200:
            return resp.json() or {"documents": [], "total": 0}
    except Exception:
        pass
    return {"documents": [], "total": 0}


def inject_global_styles():
    """注入全局样式：字体、强调色、卡片、聊天输入框美化等。"""
    st.markdown(
        """
        <style>
        /* 全局：去掉 Streamlit 顶部留白 */
        .block-container { padding-top: 2rem; padding-bottom: 4rem; }
        /* 标题：减小字重 */
        h1, h2, h3 { letter-spacing: -0.01em; }
        /* 主按钮色 */
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
            border: none !important;
        }
        /* 通用按钮：圆角胶囊 */
        .stButton > button {
            border-radius: 999px;
            border: 1px solid #e2e8f0;
            background: #ffffff;
            color: #334155;
            transition: all 0.2s ease;
            font-weight: 500;
        }
        .stButton > button:hover {
            border-color: #6366f1;
            color: #6366f1;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(99,102,241,0.08);
        }
        /* 聊天输入框 */
        [data-testid="stChatInput"] > div {
            border-radius: 16px !important;
            border: 1.5px solid #e2e8f0 !important;
            box-shadow: 0 1px 3px rgba(15,23,42,0.04) !important;
        }
        [data-testid="stChatInput"] > div:focus-within {
            border-color: #6366f1 !important;
            box-shadow: 0 0 0 4px rgba(99,102,241,0.08) !important;
        }
        /* 侧边栏整体 */
        section[data-testid="stSidebar"] {
            background: #fafbff;
            border-right: 1px solid #eef0f7;
        }
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            font-size: 0.95rem !important;
            color: #475569 !important;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-top: 0.5rem !important;
        }
        /* expander 默认更柔和 */
        [data-testid="stExpander"] {
            border-radius: 10px !important;
            border: 1px solid #eef0f7 !important;
            background: #ffffff !important;
        }
        /* hr 更轻 */
        hr { border-color: #eef0f7 !important; margin: 1rem 0 !important; }
        /* 隐藏 Streamlit 自带的右上汉堡菜单和"Deploy"按钮，保留更干净的首页 */
        [data-testid="stHeader"] { background: transparent; }
        /* 隐藏页脚 */
        footer { visibility: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero():
    """首页 hero：产品名 + 一句话价值主张 + 关于折叠卡片。"""
    st.markdown(
        """
        <div style="margin-bottom: 4px;">
          <h1 style="font-size: 1.9rem; margin-bottom: 4px; font-weight: 700;
                     background: linear-gradient(90deg,#6366f1,#8b5cf6);
                     -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
            📚 知问 · 智能文档问答
          </h1>
          <div style="color:#64748b; font-size: 0.95rem; margin-bottom: 0.75rem;">
            上传文档 · 精准检索 · AI 答疑 —— 一个轻量的 RAG 知识库 Demo
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_about_expander():
    """关于项目的折叠介绍卡。"""
    with st.expander("ℹ️ 关于这个项目（点击展开）", expanded=False):
        st.markdown(
            """
            **知问** 是一个面向个人知识库场景的 RAG 应用 Demo，支持上传 PDF / Word / Markdown 等文档，
            通过向量检索 + 大模型生成提供带出处的智能问答。

            **技术栈**：FastAPI · Streamlit · ChromaDB · OpenAI-compatible LLM · Docker

            **当前体验模式**：管理员（即作者）预置文档，访客无需登录即可直接提问。
            如果你想突破免费配额，可在侧边栏「⚙️ 高级」中填写自己的 API Key。

            > 这是一个持续迭代中的求职作品，欢迎交流反馈。
            """
        )


def render_kb_preview(library: dict):
    """侧边栏：当前知识库（只读预览）。"""
    docs = library.get("documents", [])
    total = library.get("total", 0)
    st.markdown(
        f"""
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
          <span style="font-size:13px;font-weight:600;color:#475569;">📂 当前知识库</span>
          <span style="font-size:12px;color:#94a3b8;">{total} 个文档</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not docs:
        st.caption("知识库暂时为空，等待管理员上传…")
        return
    # 最多展示前 8 条；超出收进 expander
    preview = docs[:8]
    remaining = docs[8:]
    icon_map = {"pdf": "📕", "md": "📝", "txt": "📄", "docx": "📘", "doc": "📘"}
    lines_html = []
    for d in preview:
        ext = (d.get("file_type") or "").lower()
        icon = icon_map.get(ext, "📄")
        name = d.get("filename", "(unnamed)")
        chunks = d.get("chunk_count", 0)
        lines_html.append(
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:6px 8px;border-radius:8px;font-size:13px;color:#334155;'>"
            f"<span style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:170px;' title='{name}'>{icon} {name}</span>"
            f"<span style='color:#94a3b8;font-size:11px;'>{chunks} 块</span>"
            f"</div>"
        )
    st.markdown(
        "<div style='background:#ffffff;border:1px solid #eef0f7;border-radius:10px;padding:4px;'>"
        + "".join(lines_html)
        + "</div>",
        unsafe_allow_html=True,
    )
    if remaining:
        with st.expander(f"展开剩余 {len(remaining)} 个文档"):
            for d in remaining:
                ext = (d.get("file_type") or "").lower()
                icon = icon_map.get(ext, "📄")
                st.caption(
                    f"{icon} {d.get('filename','(unnamed)')} · {d.get('chunk_count',0)} 块"
                )


def render_byok_advanced():
    """高级设置：自定义 API Key（默认折叠）。"""
    with st.expander("⚙️ 高级 · 使用自己的 API Key", expanded=False):
        st.caption("配置将仅保存在你的浏览器本地，不会上传到服务器。")
        with st.form("byok_form"):
            api_key = st.text_input(
                "API Key",
                type="password",
                value=st.session_state.byok_api_key,
                placeholder="sk-...",
            )

            detected_provider = (
                detect_provider_from_api_key(api_key)
                if api_key
                else st.session_state.byok_provider
            )
            provider_options = ["openai", "deepseek", "zhipu", "custom"]
            current_provider = st.session_state.byok_provider

            if api_key and detected_provider != current_provider:
                st.info(f"💡 检测到可能是 **{detected_provider}** 的 Key")

            provider = st.selectbox(
                "提供商",
                options=provider_options,
                index=provider_options.index(current_provider),
            )
            base_url = st.text_input(
                "Base URL（可选）",
                value=st.session_state.byok_base_url,
                placeholder="兼容 OpenAI 的网关地址",
            )
            model = st.text_input(
                "模型（可选）",
                value=st.session_state.byok_model,
                placeholder="gpt-4o-mini / deepseek-chat / glm-4",
            )

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                saved = st.form_submit_button(
                    "💾 保存",
                    on_click=lambda: st.session_state.__setitem__(
                        "skip_restore_once", True
                    ),
                )
            with col2:
                auto_detect = st.form_submit_button(
                    "🎯 自动检测",
                    on_click=lambda: st.session_state.__setitem__(
                        "skip_restore_once", True
                    ),
                )
            with col3:
                cleared = st.form_submit_button(
                    "🗑️ 清除",
                    on_click=lambda: st.session_state.__setitem__(
                        "skip_restore_once", True
                    ),
                )

            if auto_detect and api_key:
                detected = detect_provider_from_api_key(api_key)
                st.session_state.byok_api_key = api_key.strip()
                st.session_state.byok_provider = detected
                if detected == "deepseek":
                    st.session_state.byok_base_url = "https://api.deepseek.com"
                    st.session_state.byok_model = "deepseek-chat"
                elif detected == "zhipu":
                    st.session_state.byok_base_url = (
                        "https://open.bigmodel.cn/api/paas/v4"
                    )
                    st.session_state.byok_model = "glm-4"
                elif detected == "openai":
                    st.session_state.byok_base_url = ""
                    st.session_state.byok_model = "gpt-3.5-turbo"
                save_user_settings()
                st.session_state.settings_just_saved = True
                st.success(f"✅ 已识别为 {detected}")
                st.rerun()

            if saved:
                st.session_state.byok_api_key = api_key.strip()
                st.session_state.byok_provider = provider.strip()
                st.session_state.byok_base_url = base_url.strip()
                st.session_state.byok_model = model.strip()
                save_user_settings()
                st.session_state.settings_just_saved = True
                st.success("✅ 已保存到浏览器")

            if cleared:
                st.session_state.byok_api_key = ""
                st.session_state.byok_provider = "openai"
                st.session_state.byok_base_url = ""
                st.session_state.byok_model = "gpt-3.5-turbo"
                clear_user_settings()
                st.session_state.settings_just_saved = True
                st.session_state.just_cleared = True
                st.success("🗑️ 已清除")


def get_admin_auth_headers() -> dict:
    """获取管理员鉴权请求头。"""
    token = st.session_state.get("admin_jwt")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def render_footer():
    """页脚：版本 / 项目链接。"""
    version = get_git_version_info_frontend()
    st.markdown(
        f"""
        <div style="margin-top:36px;padding-top:16px;border-top:1px solid #eef0f7;
                    display:flex;justify-content:space-between;color:#94a3b8;font-size:12px;">
          <span>📚 知问 · RAG Demo</span>
          <span>{version}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    """主应用函数"""

    # 注入全局样式（必须在所有 UI 之前）
    inject_global_styles()

    # 添加右上角浮动管理员按钮
    # add_floating_admin_button()

    # --- WebSocket & Client ID Management ---
    if "client_id" not in st.session_state:
        st.session_state.client_id = str(uuid.uuid4())
        with st.container():
            init_websocket_connection(st.session_state.client_id)

    # 加载用户设置
    load_user_settings()

    # 检查后端连接
    if not check_backend_connection():
        st.error("⚠️ 后端服务连接失败，请确保 API 服务正在运行")
        st.caption(f"服务器端后端地址: {BACKEND_URL_INTERNAL}")
        st.caption(f"浏览器端后端地址: {BACKEND_URL_CLIENT}")
        st.stop()

    admin_headers = get_admin_auth_headers()
    admin_logged_in = bool(admin_headers)

    # 提前获取一次公开知识库目录（供 hero 与 chat 共用）
    library = fetch_public_library()
    doc_count = library.get("total", 0)
    st.session_state["_public_library"] = library  # ChatInterface 可读取

    # ===== 侧边栏 =====
    with st.sidebar:
        st.markdown(
            "<div style='padding:6px 0 14px 0;'>"
            "<div style='font-size:1.05rem;font-weight:700;color:#0f172a;'>📚 知问</div>"
            "<div style='font-size:11px;color:#94a3b8;letter-spacing:0.05em;'>RAG KNOWLEDGE BASE</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        if admin_logged_in:
            st.markdown(
                "<div style='background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;"
                "padding:6px 10px;font-size:12px;color:#065f46;margin-bottom:10px;'>"
                "✓ 管理员模式</div>",
                unsafe_allow_html=True,
            )

        # 1. 知识库预览
        render_kb_preview(library)

        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

        # 2. 管理员上传
        if admin_logged_in:
            file_upload_component = FileUploadComponent(
                BACKEND_URL_INTERNAL,
                BACKEND_URL_CLIENT,
                st.session_state.get("admin_jwt"),
            )
            file_upload_component.render()

            # 文档统计
            with st.expander("📊 文档统计", expanded=False):
                try:
                    stats_response = requests.get(
                        f"{BACKEND_URL_INTERNAL}/api/documents/stats/overview",
                        headers=admin_headers,
                        timeout=5,
                    )
                    if stats_response.status_code == 200:
                        stats = stats_response.json()
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            st.metric("文档数", stats.get("total_documents", 0))
                        with cc2:
                            st.metric("块数", stats.get("total_chunks", 0))
                    elif stats_response.status_code in (401, 403):
                        st.caption("登录已失效")
                    else:
                        st.caption("获取统计失败")
                except Exception as e:
                    st.caption(f"统计错误: {e}")

        # 3. 使用配额
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        display_quota_info()

        # 4. 高级（BYOK 折叠）
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        render_byok_advanced()

    # ===== 主区域 =====

    # Hero 区
    render_hero()

    # 关于折叠卡
    render_about_expander()

    if st.session_state.get("settings_status") == SettingsStatus.RESTORING.value:
        st.info("正在从浏览器恢复设置…")
        st.stop()

    # 检索范围状态条（如果已锁定到某文档，在主区显著提示）
    if st.session_state.get("selected_doc_id"):
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                "<div style='background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;"
                "padding:8px 12px;font-size:13px;color:#1e40af;'>"
                "🎯 当前已限定检索范围到指定文档</div>",
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("清除限定", key="clear_scope_main", use_container_width=True):
                st.session_state.selected_doc_id = None
                st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # 聊天界面（welcome 卡片 + 建议问题在内部渲染）
    chat_interface = ChatInterface(
        BACKEND_URL_INTERNAL, st.session_state.get("admin_jwt")
    )
    chat_interface.render()

    # 管理员专属：文档管理面板（折叠在底部）
    # if admin_logged_in:
    #     st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
    #     render_admin_doc_management(admin_headers)

    # 页脚
    render_footer()


if __name__ == "__main__":
    main()
