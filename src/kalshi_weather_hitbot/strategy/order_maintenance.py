from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def _parse_cents_from_dollar_like(value: Any) -> int | None:
    if value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return int((dec * 100).quantize(Decimal("1")))


def parse_order_price_cents(order: dict[str, Any]) -> int | None:
    side = str(order.get("side") or "").lower()
    if side == "yes":
        for key in ("yes_price", "price"):
            if order.get(key) is not None:
                return int(order[key])
        for key in ("yes_price_dollars", "price_dollars"):
            cents = _parse_cents_from_dollar_like(order.get(key))
            if cents is not None:
                return cents
        return None
    if side == "no":
        for key in ("no_price", "price"):
            if order.get(key) is not None:
                return int(order[key])
        for key in ("no_price_dollars", "price_dollars"):
            cents = _parse_cents_from_dollar_like(order.get(key))
            if cents is not None:
                return cents
        return None
    for key in ("yes_price", "no_price", "price"):
        if order.get(key) is not None:
            return int(order[key])
    for key in ("yes_price_dollars", "no_price_dollars", "price_dollars"):
        cents = _parse_cents_from_dollar_like(order.get(key))
        if cents is not None:
            return cents
    return None


def order_age_seconds(order: dict[str, Any], now_utc: datetime) -> float:
    ts_raw = order.get("created_time") or order.get("last_update_time")
    if not ts_raw:
        return 0.0
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now_utc - ts.astimezone(timezone.utc)).total_seconds())


def should_amend(existing_price: int, desired_price: int, age_seconds: float, cfg: Any) -> bool:
    if not bool(getattr(cfg, "order_maintenance_enabled", False)):
        return False
    if age_seconds < float(getattr(cfg, "amend_min_age_seconds", 0)):
        return False
    min_tick = int(getattr(cfg, "amend_min_tick", 1))
    return abs(int(desired_price) - int(existing_price)) >= max(1, min_tick)


def build_amend_payload(
    order_id: str,
    ticker: str,
    side: str,
    action: str,
    desired_price_cents: int,
    count: int,
    cfg_price_in_dollars_flag: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "order_id": order_id,
        "ticker": ticker,
        "side": str(side).lower(),
        "action": str(action).lower(),
        "count": int(count),
        "count_fp": f"{int(count):.2f}",
    }
    side_upper = str(side).upper()
    if cfg_price_in_dollars_flag:
        if side_upper == "YES":
            payload["yes_price_dollars"] = f"{(desired_price_cents / 100.0):.4f}"
        else:
            payload["no_price_dollars"] = f"{(desired_price_cents / 100.0):.4f}"
    else:
        if side_upper == "YES":
            payload["yes_price"] = int(desired_price_cents)
        else:
            payload["no_price"] = int(desired_price_cents)
    return payload
