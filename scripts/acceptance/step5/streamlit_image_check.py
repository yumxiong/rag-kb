"""Run from /probe in the image, without injecting the repository into sys.path."""

import sys
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

# The streamlit CLI supplies the entrypoint directory; AppTest does not.
# Do not add /app: that package root must come from the image configuration.
sys.path.insert(0, "/app/frontend")


def response(body):
    return Mock(status_code=200, json=Mock(return_value=body))


def get(url, **kwargs):
    if url.endswith("/health"):
        return response({"status": "healthy"})
    if url.endswith("/library"):
        return response({"total": 9, "documents": []})
    if url.endswith("/quota"):
        return response({"quota_enabled": True, "used_count": 0, "daily_limit": 5})
    if url.endswith("/suggestions"):
        return response({"document_count": 9, "suggestions": ["Public question"] * 4})
    raise AssertionError("Unexpected backend request")


with patch("requests.get", side_effect=get), patch(
    "requests.post",
    return_value=response({"token": "anon_v1_" + "a" * 43}),
):
    app = AppTest.from_file("/app/frontend/streamlit_app.py").run(timeout=20)
    if "--expect-import-failure" in sys.argv:
        assert any("No module named 'frontend'" in e.message for e in app.exception)
        print("ORIGINAL_IMAGE_IMPORT_FAILURE_REPRODUCED")
    else:
        assert not app.exception, [e.message for e in app.exception]
        with patch("utils.settings_loader._read_browser_settings", return_value={}):
            app.run(timeout=20)
        assert not app.exception, [e.message for e in app.exception]
        assert (
            len([b for b in app.button if (b.key or "").startswith("suggestion_")]) == 4
        )
        assert not app.get("file_uploader")
        assert "admin_jwt" not in app.session_state
        print("FULL_STREAMLIT_HOMEPAGE_EXECUTED_WITHOUT_EXCEPTION")
