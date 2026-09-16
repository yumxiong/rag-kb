import json
import logging
from enum import Enum
from typing import Any, Dict, Optional

import streamlit as st

logger = logging.getLogger(__name__)


class SettingsStatus(str, Enum):
    IDLE = "idle"
    RESTORING = "restoring"
    LOADED = "loaded"
    FAILED = "failed"


MAX_ATTEMPTS = 3


def _normalize_local_storage_value(value: Any, default: str = "") -> str:
    """Normalize localStorage string (possibly JSON-wrapped) to plain text."""
    if value is None:
        return default

    cleaned = value
    try:
        cleaned = json.loads(cleaned)
    except Exception:
        pass

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


def _read_browser_settings() -> Optional[Dict[str, Any]]:
    """Try reading BYOK settings from browser localStorage via JS eval."""
    try:
        from streamlit_js_eval import streamlit_js_eval  # type: ignore
    except Exception:
        return None

    try:
        payload = streamlit_js_eval(
            js_expressions="""
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
    except Exception as exc:
        logger.warning(f"Failed to read BYOK settings via JS eval: {exc}")
        return None

    if not payload or not isinstance(payload, str):
        return None

    try:
        return json.loads(payload)
    except Exception:
        return None


def _load_with_html_fallback() -> None:
    """Inject a hidden HTML snippet to attempt reading localStorage once."""
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
    st.components.v1.html(html_code, height=0, width=0)


def _restore_from_url_params() -> bool:
    """Try to restore settings from URL parameters; return True if restored."""
    try:
        try:
            query_params = dict(st.query_params)
            clear_params = lambda: st.query_params.clear()
        except AttributeError:
            query_params = st.experimental_get_query_params()
            clear_params = lambda: st.experimental_set_query_params()

        restored_flag = query_params.get("restored")
        if restored_flag == "1" or (
            isinstance(restored_flag, list)
            and restored_flag
            and restored_flag[0] == "1"
        ):
            import base64

            provider_param = query_params.get("provider", "openai")
            base_url_param = query_params.get("base_url", "")
            model_param = query_params.get("model", "gpt-3.5-turbo")

            def _decode_param(value: Any, fallback: str = "") -> str:
                if not value:
                    return fallback
                raw_value = value if isinstance(value, str) else value[0]
                if not raw_value:
                    return fallback
                try:
                    return base64.b64decode(raw_value).decode("utf-8") or fallback
                except Exception:
                    return raw_value or fallback

            provider = (
                provider_param if isinstance(provider_param, str) else provider_param[0]
            )
            base_url = _decode_param(base_url_param)
            model = model_param if isinstance(model_param, str) else model_param[0]

            st.session_state.byok_provider = (provider or "openai").strip()
            st.session_state.byok_base_url = base_url.strip()
            st.session_state.byok_model = (model or "gpt-3.5-turbo").strip()

            st.session_state.settings_status = SettingsStatus.LOADED.value
            st.session_state.settings_attempts = 0

            logger.info(
                "BYOK settings restored from query params: provider=%s",
                st.session_state.byok_provider,
            )

            clear_params()
            return True
    except Exception as exc:
        logger.warning(f"URL param restore failed: {exc}")

    return False


def _ensure_session_defaults() -> None:
    defaults = {
        "byok_api_key": "",
        "byok_provider": "openai",
        "byok_base_url": "",
        "byok_model": "gpt-3.5-turbo",
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

    if "settings_status" not in st.session_state:
        st.session_state.settings_status = SettingsStatus.IDLE.value
    if "settings_attempts" not in st.session_state:
        st.session_state.settings_attempts = 0


def load_user_settings() -> None:
    """Unified settings loader with status enum and bounded retries."""
    _ensure_session_defaults()

    skip_restore = st.session_state.pop("skip_restore_once", False)

    if st.session_state.settings_status == SettingsStatus.LOADED.value or skip_restore:
        return

    st.session_state.settings_status = SettingsStatus.RESTORING.value

    # 1) Try URL params (back-compat)
    if _restore_from_url_params():
        return

    # 2) Try JS read from localStorage
    raw_data = _read_browser_settings()

    # 3) Fallback via hidden HTML and bounded reruns
    if raw_data is None:
        _load_with_html_fallback()
        attempts = int(st.session_state.get("settings_attempts", 0))
        if attempts < MAX_ATTEMPTS:
            st.session_state.settings_attempts = attempts + 1
            st.rerun()
        # Exhausted retries -> mark as failed
        st.session_state.settings_status = SettingsStatus.FAILED.value
        return

    # Parse and normalize values
    api_key = _normalize_local_storage_value(raw_data.get("api_key_raw"))
    provider = (
        _normalize_local_storage_value(raw_data.get("provider_raw"), "openai")
        or "openai"
    )
    base_url = _normalize_local_storage_value(raw_data.get("base_url_raw"))
    model = (
        _normalize_local_storage_value(raw_data.get("model_raw"), "gpt-3.5-turbo")
        or "gpt-3.5-turbo"
    )

    st.session_state.byok_api_key = api_key
    st.session_state.byok_provider = provider
    st.session_state.byok_base_url = base_url
    st.session_state.byok_model = model

    st.session_state.settings_status = SettingsStatus.LOADED.value
    st.session_state.settings_attempts = 0

    logger.info(
        "BYOK settings loaded from browser: provider=%s, api_key_exists=%s",
        provider,
        bool(api_key),
    )
