"""Quota manager persistence and boundary tests."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from app.core import quota_manager as quota_module
from app.core.quota_manager import QuotaInfo, QuotaManager


def _request(ip="127.0.0.1", agent="pytest"):
    return {"client_ip": ip, "user_agent": agent}


def test_quota_info_round_trip():
    quota = QuotaInfo(user_id="user", used_count=2, daily_limit=7)

    assert QuotaInfo.from_dict(quota.to_dict()) == quota


def test_loads_saved_quotas(tmp_path):
    quota_file = tmp_path / "user_quotas.json"
    quota_file.write_text(
        json.dumps({"abc": QuotaInfo(user_id="abc", used_count=2).to_dict()}),
        encoding="utf-8",
    )

    manager = QuotaManager(str(tmp_path), daily_limit=3)

    assert manager._quotas["abc"].used_count == 2


def test_invalid_quota_file_is_ignored(tmp_path):
    (tmp_path / "user_quotas.json").write_text("not-json", encoding="utf-8")

    manager = QuotaManager(str(tmp_path))

    assert manager._quotas == {}


def test_user_fingerprint_is_stable_and_distinct(tmp_path):
    manager = QuotaManager(str(tmp_path))

    first = manager._get_user_id(_request())

    assert first == manager._get_user_id(_request())
    assert first != manager._get_user_id(_request(ip="127.0.0.2"))
    assert len(first) == 16


def test_new_day_detection_handles_empty_invalid_and_dates(tmp_path):
    manager = QuotaManager(str(tmp_path))
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()

    assert manager._is_new_day("")
    assert manager._is_new_day("invalid")
    assert manager._is_new_day(yesterday)
    assert not manager._is_new_day(datetime.now().isoformat())


def test_custom_key_bypasses_quota_without_persisting(tmp_path):
    manager = QuotaManager(str(tmp_path), daily_limit=1)

    allowed, quota = manager.check_and_increment(_request(), has_custom_key=True)

    assert allowed
    assert quota.user_id == "custom_key_user"
    assert quota.daily_limit == 999999
    assert manager._quotas == {}


def test_enforces_limit_and_persists_usage(tmp_path):
    manager = QuotaManager(str(tmp_path), daily_limit=2)

    first_allowed, first = manager.check_and_increment(_request())
    second_allowed, second = manager.check_and_increment(_request())
    third_allowed, third = manager.check_and_increment(_request())

    assert first_allowed and second_allowed
    assert not third_allowed
    assert first.used_count == second.used_count == third.used_count == 2
    reloaded = QuotaManager(str(tmp_path), daily_limit=2)
    assert reloaded.get_quota_info(_request()).used_count == 2


def test_existing_quota_resets_on_new_day(tmp_path):
    manager = QuotaManager(str(tmp_path), daily_limit=2)
    user_id = manager._get_user_id(_request())
    manager._quotas[user_id] = QuotaInfo(
        user_id=user_id,
        used_count=2,
        daily_limit=2,
        last_reset_date=(datetime.now() - timedelta(days=1)).isoformat(),
    )

    allowed, quota = manager.check_and_increment(_request())

    assert allowed
    assert quota.used_count == 1


def test_get_quota_info_for_unknown_and_stale_users(tmp_path):
    manager = QuotaManager(str(tmp_path), daily_limit=4)

    unknown = manager.get_quota_info(_request())
    assert unknown.used_count == 0
    assert unknown.daily_limit == 4

    user_id = manager._get_user_id(_request())
    manager._quotas[user_id] = QuotaInfo(
        user_id=user_id,
        used_count=3,
        last_reset_date=(datetime.now() - timedelta(days=1)).isoformat(),
    )
    stale = manager.get_quota_info(_request())
    assert stale.used_count == 0
    assert stale.last_reset_date


def test_reset_and_admin_views(tmp_path):
    manager = QuotaManager(str(tmp_path), daily_limit=3)
    manager.check_and_increment(_request())
    user_id = manager._get_user_id(_request())

    assert manager.reset_user_quota(_request())
    assert not manager.reset_user_quota(_request(ip="missing"))
    assert manager._quotas[user_id].used_count == 0
    all_quotas = manager.get_all_quotas()
    assert list(all_quotas) == [user_id[:8] + "..."]


def test_set_daily_limit_updates_existing_users(tmp_path):
    manager = QuotaManager(str(tmp_path), daily_limit=2)
    manager.check_and_increment(_request())

    manager.set_daily_limit(9)

    assert manager.daily_limit == 9
    assert manager.get_quota_info(_request()).daily_limit == 9


def test_save_failure_does_not_break_quota_check(tmp_path):
    manager = QuotaManager(str(tmp_path))

    with patch("builtins.open", side_effect=OSError("disk full")):
        allowed, quota = manager.check_and_increment(_request())

    assert allowed
    assert quota.used_count == 1


def test_get_quota_manager_is_lazy_singleton(tmp_path):
    quota_module.quota_manager = None
    try:
        with patch("app.core.config.settings.default_daily_quota", 8), patch(
            "app.core.quota_manager.QuotaManager"
        ) as manager_class:
            instance = manager_class.return_value

            assert quota_module.get_quota_manager() is instance
            assert quota_module.get_quota_manager() is instance
            manager_class.assert_called_once_with(daily_limit=8)
    finally:
        quota_module.quota_manager = None
