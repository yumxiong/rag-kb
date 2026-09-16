"""
模型设置组件
负责BYOK (Bring Your Own Key) 配置界面
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict

import streamlit as st
import streamlit.components.v1 as components
from utils.settings_loader import SettingsStatus
from utils.settings_loader import load_user_settings as load_user_settings_shared

logger = logging.getLogger(__name__)

# 尝试导入streamlit-js-eval，如果没有则使用备用方案
try:
    from streamlit_js_eval import streamlit_js_eval

    JS_EVAL_AVAILABLE = True
except ImportError:
    JS_EVAL_AVAILABLE = False


class ModelSettingsComponent:
    """模型设置组件类"""

    def __init__(self):
        self.provider_options = ["openai", "deepseek", "zhipu", "custom"]
        self.default_models = {
            "openai": "gpt-3.5-turbo",
            "deepseek": "deepseek-chat",
            "zhipu": "glm-4",
            "custom": "gpt-3.5-turbo",
        }
        self.default_base_urls = {
            "openai": "",
            "deepseek": "https://api.deepseek.com",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
            "custom": "",
        }

    def detect_provider_from_api_key(self, api_key: str) -> str:
        """根据API Key格式自动检测提供商"""
        if not api_key:
            return "openai"

        api_key = api_key.strip()

        # Zhipu API keys: xxxxxxxx.xxxxxxxxxxxxxx (32 char hex + . + 16 chars)
        if "." in api_key and len(api_key.split(".")) == 2:
            parts = api_key.split(".")
            if len(parts[0]) == 32 and len(parts[1]) == 16:
                return "zhipu"

        # OpenAI API keys: start with "sk-" and are longer (51-55 chars typically)
        if api_key.startswith("sk-") and len(api_key) >= 48:
            return "openai"

        # DeepSeek API keys: start with "sk-" and are shorter than OpenAI keys
        if api_key.startswith("sk-") and len(api_key) <= 47:
            return "deepseek"

        return "openai"

    def _normalize_local_storage_value(self, value: str, default: str = "") -> str:
        """尽可能把localStorage中的值解析为纯文本"""
        if value is None:
            return default

        cleaned = value
        try:
            cleaned = json.loads(cleaned)
        except Exception:
            pass

        # 早期版本可能出现双重 JSON 编码，这里再尝试一次
        if isinstance(cleaned, str):
            stripped = cleaned.strip()
            if stripped and stripped[0] in ('"', "'") and stripped[-1] == stripped[0]:
                try:
                    cleaned = json.loads(cleaned)
                except Exception:
                    cleaned = stripped.strip('"')

        if isinstance(cleaned, str):
            return cleaned.strip()

        return default

    def _read_browser_settings(self) -> dict | None:
        """尝试通过JS一次性读取localStorage中的BYOK设置"""
        if not JS_EVAL_AVAILABLE:
            return None

        try:
            payload = streamlit_js_eval(
                """
                (function(){
                  try {
                    const getLS = () => {
                      try { return (window.top && window.top.localStorage) ? window.top.localStorage : localStorage; }
                      catch(e) { return localStorage; }
                    };
                    const ls = getLS();
                    const result = {
                      api_key_raw: ls.getItem('rag_byok_api_key'),
                      provider_raw: ls.getItem('rag_byok_provider'),
                      base_url_raw: ls.getItem('rag_byok_base_url'),
                      model_raw: ls.getItem('rag_byok_model'),
                      last_saved_raw: ls.getItem('rag_byok_last_saved')
                    };
                    return JSON.stringify(result);
                  } catch(e) {
                    return '';
                  }
                })()
                """,
                key="ls_bulk_read",
                want_output=True,
            )

            if not payload or not isinstance(payload, str):
                return None

            return json.loads(payload)
        except Exception as exc:
            logger.warning(f"Failed to read BYOK settings via JS eval: {exc}")
            return None

    def load_with_html_fallback(self):
        """使用HTML方式读取localStorage的备用方案"""
        html_code = """
        <script>
        (function(){
          function read(k){
            const v = localStorage.getItem(k);
            try { return JSON.parse(v); } catch(e) { return v || ''; }
          }
          function buildSettings(){
            return {
              api_key: read('rag_byok_api_key') || '',
              provider: read('rag_byok_provider') || 'openai',
              base_url: read('rag_byok_base_url') || '',
              model: read('rag_byok_model') || 'gpt-3.5-turbo'
            };
          }
          function sendOnce(){
            try {
              const settings = buildSettings();
              var el = document.getElementById('settings-data');
              if (el) { el.textContent = JSON.stringify(settings); }
              if (window.parent && window.parent.__rag_listener_installed) {
                window.parent.postMessage({ type:'localStorage_data', data: settings }, '*');
              } else {
                setTimeout(sendOnce, 200);
              }
            } catch(e) {
              setTimeout(sendOnce, 200);
            }
          }
          if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function(){ setTimeout(sendOnce, 50); });
          } else {
            setTimeout(sendOnce, 50);
          }
        })();
        </script>
        <div id="settings-data" style="display:none;"></div>
        """
        components.html(html_code, height=0, width=0)

    def load_user_settings(self):
        """统一入口：使用共享加载器实现设置恢复与重试。"""
        load_user_settings_shared()

    def _restore_from_url_params(self):
        """Deprecated: handled by the shared loader in utils.settings_loader."""
        return None

    def save_user_settings(self):
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

    def clear_user_settings(self):
        """清除用户设置"""
        if JS_EVAL_AVAILABLE:
            try:
                import time

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

    def render(self):
        """渲染模型设置组件"""
        st.header("🔑 模型设置 (BYOK)")

        api_key_configured = bool(st.session_state.get("byok_api_key"))
        st.caption(f"API Key：{'已配置' if api_key_configured else '未配置'}")

        # 设置表单
        with st.form("byok_form"):
            api_key = st.text_input(
                "API Key",
                type="password",
                value=st.session_state.byok_api_key,
                help="设置将保存在浏览器本地，刷新页面不会丢失",
            )

            # Auto-detect provider based on API key format
            detected_provider = (
                self.detect_provider_from_api_key(api_key)
                if api_key
                else st.session_state.byok_provider
            )
            current_provider = st.session_state.byok_provider

            # Show detected provider hint
            if api_key and detected_provider != current_provider:
                st.info(
                    f"💡 检测到 API Key 格式，建议选择提供商: **{detected_provider}**"
                )

            provider = st.selectbox(
                "提供商",
                options=self.provider_options,
                index=self.provider_options.index(current_provider),
            )

            base_url = st.text_input(
                "Base URL (可选)",
                value=st.session_state.byok_base_url,
                placeholder="如自定义兼容 OpenAI 的网关地址",
            )

            model = st.text_input(
                "模型 (可选)",
                value=st.session_state.byok_model,
                placeholder="如 gpt-4o-mini / deepseek-chat / glm-4",
            )

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                saved = st.form_submit_button(
                    "💾 保存设置",
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
                    "🗑️ 清除设置",
                    on_click=lambda: st.session_state.__setitem__(
                        "skip_restore_once", True
                    ),
                )

            # 处理按钮点击事件
            if auto_detect and api_key:
                self._handle_auto_detect(api_key)

            if saved:
                self._handle_save_settings(api_key, provider, base_url, model)

            if cleared:
                self._handle_clear_settings()

    def _handle_auto_detect(self, api_key: str):
        """处理自动检测按钮点击"""
        detected = self.detect_provider_from_api_key(api_key)
        st.session_state.byok_api_key = api_key.strip()
        st.session_state.byok_provider = detected

        # Set appropriate defaults based on provider
        st.session_state.byok_base_url = self.default_base_urls.get(detected, "")
        st.session_state.byok_model = self.default_models.get(detected, "gpt-3.5-turbo")

        self.save_user_settings()
        st.session_state.settings_just_saved = True
        st.success(f"✅ 已自动检测并配置为 {detected} 提供商")
        st.rerun()

    def _handle_save_settings(
        self, api_key: str, provider: str, base_url: str, model: str
    ):
        """处理保存设置按钮点击"""
        st.session_state.byok_api_key = api_key.strip()
        st.session_state.byok_provider = provider.strip()
        st.session_state.byok_base_url = base_url.strip()
        st.session_state.byok_model = model.strip()

        self.save_user_settings()
        st.session_state.settings_just_saved = True
        st.success("✅ 设置已保存到浏览器本地，刷新页面不会丢失")

    def _handle_clear_settings(self):
        """处理清除设置按钮点击"""
        st.session_state.byok_api_key = ""
        st.session_state.byok_provider = "openai"
        st.session_state.byok_base_url = ""
        st.session_state.byok_model = "gpt-3.5-turbo"

        self.clear_user_settings()
        st.session_state.settings_just_saved = True
        st.session_state.just_cleared = True
        st.success("🗑️ 设置已清除")

    def build_byok_headers(self) -> Dict[str, str]:
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
