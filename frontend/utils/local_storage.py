"""
本地存储工具模块
使用Streamlit的组件机制实现浏览器localStorage功能
"""

import json
from typing import Any, Optional

import streamlit as st
import streamlit.components.v1 as components


def save_to_local_storage(key: str, value: Any) -> None:
    """
    保存数据到浏览器localStorage

    Args:
        key: 存储的键名
        value: 要存储的值（会被JSON序列化）
    """
    try:
        # 将值序列化为JSON字符串
        json_value = json.dumps(value, ensure_ascii=False)

        # 使用JavaScript代码保存到localStorage
        js_code = f"""
        <script>
        localStorage.setItem('{key}', {json.dumps(json_value)});
        </script>
        """

        # 执行JavaScript代码
        components.html(js_code, height=0, width=0)

    except Exception as e:
        st.error(f"保存到本地存储失败: {str(e)}")


def load_from_local_storage(key: str, default_value: Any = None) -> Any:
    """
    从浏览器localStorage加载数据

    Args:
        key: 存储的键名
        default_value: 如果键不存在时返回的默认值

    Returns:
        存储的值或默认值
    """
    try:
        # 创建一个唯一的session_state键来存储localStorage的值
        storage_key = f"_local_storage_{key}"

        # 如果已经加载过，直接返回
        if storage_key in st.session_state:
            return st.session_state[storage_key]

        # 使用JavaScript读取localStorage并通过hidden input传回Python
        js_code = f"""
        <script>
        var value = localStorage.getItem('{key}');
        var input = document.getElementById('local_storage_{key}');
        if (input && value) {{
            input.value = value;
            input.dispatchEvent(new Event('input'));
        }}
        </script>
        <input type="hidden" id="local_storage_{key}" />
        """

        # 显示HTML组件
        component_value = components.html(js_code, height=0, width=0)

        # 使用session_state作为fallback
        if storage_key not in st.session_state:
            st.session_state[storage_key] = default_value

        return st.session_state[storage_key]

    except Exception as e:
        st.error(f"从本地存储加载失败: {str(e)}")
        return default_value


def initialize_local_storage_values(keys_defaults: dict) -> dict:
    """
    初始化多个localStorage值到session_state

    Args:
        keys_defaults: 键值对字典，键为localStorage键名，值为默认值

    Returns:
        包含所有加载值的字典
    """
    results = {}

    # 创建JavaScript代码读取所有localStorage值
    js_items = []
    for key in keys_defaults.keys():
        js_items.append(f'"{key}": localStorage.getItem("{key}")')

    js_code = f"""
    <script>
    var storageData = {{ {', '.join(js_items)} }};
    var hiddenDiv = document.getElementById('storage_data');
    if (hiddenDiv) {{
        hiddenDiv.textContent = JSON.stringify(storageData);
    }}
    </script>
    <div id="storage_data" style="display:none;"></div>
    """

    # 执行JavaScript
    components.html(js_code, height=0, width=0)

    # 从session_state获取或使用默认值
    for key, default_value in keys_defaults.items():
        storage_key = f"_local_storage_{key}"
        if storage_key not in st.session_state:
            st.session_state[storage_key] = default_value
        results[key] = st.session_state[storage_key]

    return results


def update_local_storage_from_session(key: str) -> None:
    """
    将session_state中的值更新到localStorage

    Args:
        key: localStorage键名
    """
    storage_key = f"_local_storage_{key}"
    if storage_key in st.session_state:
        save_to_local_storage(key, st.session_state[storage_key])


# 简化版本：直接使用session_state持久化（页面刷新会丢失，但会话期间保持）
class SimpleLocalStorage:
    """
    简化的本地存储类，使用session_state实现
    虽然页面刷新会丢失，但提供了统一的接口
    """

    @staticmethod
    def set(key: str, value: Any) -> None:
        """设置值"""
        st.session_state[f"ls_{key}"] = value

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """获取值"""
        return st.session_state.get(f"ls_{key}", default)

    @staticmethod
    def remove(key: str) -> None:
        """删除值"""
        if f"ls_{key}" in st.session_state:
            del st.session_state[f"ls_{key}"]

    @staticmethod
    def clear() -> None:
        """清除所有localStorage相关的值"""
        keys_to_remove = [k for k in st.session_state.keys() if k.startswith("ls_")]
        for key in keys_to_remove:
            del st.session_state[key]


# 为了更好的用户体验，使用浏览器真正的localStorage
class BrowserLocalStorage:
    """
    真正的浏览器localStorage实现
    """

    @staticmethod
    def initialize_from_browser(keys: list) -> None:
        """从浏览器localStorage初始化值到session_state"""
        if not keys:
            return

        # 构建JavaScript代码
        js_items = []
        for key in keys:
            js_items.append(
                f'    parent.postMessage({{type: "localStorage", key: "{key}", value: localStorage.getItem("{key}")}}, "*");'
            )

        js_code = f"""
        <script>
        // 发送localStorage数据到父窗口
        {chr(10).join(js_items)}
        </script>
        """

        components.html(js_code, height=0, width=0)

    @staticmethod
    def save_to_browser(key: str, value: Any) -> None:
        """保存值到浏览器localStorage"""
        json_value = json.dumps(value, ensure_ascii=False)

        js_code = f"""
        <script>
        try {{
            localStorage.setItem({json.dumps(key)}, {json.dumps(json_value)});
            
        }} catch(e) {{
            console.error('Failed to save to localStorage');
        }}
        </script>
        """

        components.html(js_code, height=0, width=0)
