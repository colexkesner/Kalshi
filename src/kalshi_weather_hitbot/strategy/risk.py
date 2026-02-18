from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def compute_cap_dollars(balance_dollars: float, cap_mode: str, cap_value: float) -> float:
    if cap_mode == "percent":
        return balance_dollars * cap_value / 100.0
    return cap_value


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _cents_to_dollars(value: Any) -> float:
    parsed = _to_float(value)
    if parsed is None:
        return 0.0
    return parsed / 100.0


def _parse_exposure_dollars(position: dict[str, Any]) -> float:
    market_exposure_fp = position.get("market_exposure_dollars") or position.get("market_exposure_fp")
    if market_exposure_fp is not None:
        parsed = _to_float(market_exposure_fp)
        return parsed if parsed is not None else 0.0
    market_exposure_cents = position.get("market_exposure")
    if market_exposure_cents is not None:
        return _cents_to_dollars(market_exposure_cents)
    return 0.0


def _fallback_notional_dollars(position: dict[str, Any]) -> float:
    contracts = _to_float(position.get("contracts") or position.get("position") or position.get("count")) or 0
    avg_price = _to_float(position.get("avg_price") or position.get("average_price") or position.get("cost_basis")) or 0
    # Conservative fallback + buffer for fees/slippage.
    return ((abs(contracts) * avg_price) / 100.0) * 1.1


def compute_positions_exposure(positions: list[dict[str, Any]]) -> float:
    exposure = 0.0
    for position in positions:
        market_exposure = _parse_exposure_dollars(position)
        if market_exposure > 0:
            exposure += market_exposure
            continue
        exposure += _fallback_notional_dollars(position)
    return exposure


def compute_open_orders_exposure(orders: list[dict[str, Any]]) -> float:
    exposure = 0.0
    for order in orders:
        buy_max_cost_dollars = order.get("buy_max_cost_dollars") or order.get("buy_max_cost_fp")
        if buy_max_cost_dollars is not None:
            parsed = _to_float(buy_max_cost_dollars)
            exposure += parsed if parsed is not None else 0.0
            continue

        buy_max_cost = order.get("buy_max_cost")
        if buy_max_cost is not None:
            exposure += _cents_to_dollars(buy_max_cost)
            continue

        action = str(order.get("action") or "").lower()
        if action != "buy":
            continue
        count = _to_float(order.get("remaining_count") or order.get("count") or order.get("count_fp")) or 0
        price = order.get("yes_price")
        if price is None:
            price = order.get("no_price")
        if price is None:
            price = order.get("price")
        price_val = _to_float(price) or 0
        exposure += (count * price_val) / 100.0
    return exposure


def enforce_cap(current_open_notional: float, new_order_notional: float, cap_dollars: float) -> bool:
    return (current_open_notional + new_order_notional) <= cap_dollars
