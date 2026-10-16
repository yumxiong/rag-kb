"""Conservative CNY reservations in the existing single-owner durable ledger."""

import copy
import uuid
from datetime import date

DAILY_CAP_MICROS = 50_000_000


def initial_money_state() -> dict:
    return {"schema": 1, "days": {}, "pending": {}, "last_day": ""}


def validate_money_state(money: dict) -> None:
    if not isinstance(money, dict) or money.get("schema") != 1:
        raise ValueError("Missing monetary ledger; explicit provisioning required")
    if not isinstance(money["days"], dict) or not isinstance(money["pending"], dict):
        raise ValueError("Invalid monetary ledger")
    last = money["last_day"]
    if last:
        date.fromisoformat(last)
    pending_totals = {}
    for day, amount in money["days"].items():
        if date.fromisoformat(day).isoformat() != day or day > last:
            raise ValueError("Invalid monetary day")
        if type(amount) is not int or not 0 <= amount <= DAILY_CAP_MICROS:
            raise ValueError("Invalid monetary total")
    for identifier, record in money["pending"].items():
        uuid.UUID(identifier)
        day, amount = record["day"], record["amount"]
        if day not in money["days"] or type(amount) is not int or amount <= 0:
            raise ValueError("Invalid monetary reservation")
        if not isinstance(record["policy"], str) or not record["policy"]:
            raise ValueError("Missing price policy")
        pending_totals[day] = pending_totals.get(day, 0) + amount
    if any(amount > money["days"][day] for day, amount in pending_totals.items()):
        raise ValueError("Reservations exceed recorded spending")


class MoneyLedger:
    """Never refund; unresolved attempts consume headroom on every future day."""

    def __init__(self, store):
        self.store = store

    def _checked(self, state):
        from app.core.anonymous_session import SessionError

        self.store._ensure_healthy()
        try:
            money = state["money"]
            validate_money_state(money)
            day = self.store._day()
            if day < money["last_day"]:
                raise ValueError("Clock moved backwards")
        except (KeyError, TypeError, ValueError):
            raise SessionError("quota_storage_unavailable", 503) from None
        return money, day

    @staticmethod
    def _carried(money, day):
        return sum(
            row["amount"] for row in money["pending"].values() if row["day"] != day
        )

    def reserve(self, amount: int, *, policy: str) -> str:
        """Commit the full upper bound before any provider request is dispatched."""
        from app.core.anonymous_session import SessionError

        if type(amount) is not int or not 0 < amount <= DAILY_CAP_MICROS or not policy:
            raise SessionError("service_unavailable", 503)
        with self.store._lock:
            state = copy.deepcopy(self.store.state)
            money, day = self._checked(state)
            used = money["days"].get(day, 0)
            if used + self._carried(money, day) + amount > DAILY_CAP_MICROS:
                raise SessionError(
                    "global_budget_exceeded", 503, self.store.seconds_until_reset()
                )
            identifier = str(uuid.uuid4())
            money["last_day"] = day
            money["days"][day] = used + amount
            money["pending"][identifier] = {
                "day": day,
                "amount": amount,
                "policy": policy,
            }
            self.store._commit(state)
            return identifier

    def complete(self, identifier: str) -> None:
        """A complete successful response ends uncertainty, but never refunds."""
        with self.store._lock:
            state = copy.deepcopy(self.store.state)
            money, day = self._checked(state)
            row = money["pending"].pop(identifier)
            if row["day"] != day:
                # Charge BOTH dispatch day and completion day. The carried amount
                # already blocked this capacity while the request was outstanding.
                money["days"][day] = money["days"].get(day, 0) + row["amount"]
            money["last_day"] = day
            validate_money_state(money)
            self.store._commit(state)

    def snapshot(self) -> dict:
        with self.store._lock:
            money, day = self._checked(self.store.state)
            used = money["days"].get(day, 0)
            carried = self._carried(money, day)
            return {
                "currency": "CNY",
                "unit": "microyuan",
                "date": day,
                "daily_cap": DAILY_CAP_MICROS,
                "reserved_today": used,
                "unresolved_previous_days": carried,
                "remaining": max(0, DAILY_CAP_MICROS - used - carried),
                "pending_attempts": len(money["pending"]),
                "actual_billed": None,
            }
