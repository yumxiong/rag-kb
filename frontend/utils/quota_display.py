"""Shared quota rendering using server counts and mode-specific budget state."""


def render_quota_info(quota: dict, ui) -> None:
    """Keep personal quota and global availability visibly independent."""
    budget = quota.get("global_budget") or {}
    status = budget.get("status")
    if status == "exhausted":
        ui.warning("今日演示服务额度已用完，当前模式暂不可提问，请在重置后再试。")
    elif status == "available":
        ui.caption("全站预算：当前模式可用（此读数为快照，不是额度预约）。")
    else:
        ui.warning("暂时无法确认全站预算，请刷新额度后再试。")
    if budget.get("reset_at"):
        ui.caption(f"全站预算重置时间（UTC）：{budget['reset_at']}")

    if quota.get("has_custom_key"):
        ui.info("已接入自定义 API Key：不扣个人免费次数，仍受全站预算限制。")
        ui.caption(f"今日默认 Key 已使用：{quota.get('used_count', 0)} 次")
    elif not quota.get("quota_enabled", True):
        ui.info("当前未启用个人额度限制，仍受全站预算限制。")
    else:
        ui.caption(
            f"今日个人免费额度：已用 {quota.get('used_count')} / "
            f"{quota.get('daily_limit')}，剩余 {quota.get('remaining')} 次。"
        )
        if quota.get("remaining") == 0:
            ui.warning("今日个人免费次数已用完；BYOK 是否可用取决于该模式的全站预算。")
    if quota.get("reset_at"):
        ui.caption(f"个人额度重置时间（UTC）：{quota['reset_at']}")
