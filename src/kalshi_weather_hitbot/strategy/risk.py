from __future__ import annotations

from typing import Any


def compute_cap_dollars(balance_dollars: float, cap_mode: str, cap_value: float) -> float:
    if cap_mode == "percent":
        return balance_dollars * cap_value / 100.0
    return cap_value


def _cents_to_dollars(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _fallback_notional_dollars(position: dict[str, Any]) -> float:
    contracts = position.get("contracts") or position.get("position") or position.get("count") or 0
    avg_price = position.get("avg_price") or position.get("average_price") or position.get("cost_basis") or 0
    try:
        contracts_f = abs(float(contracts))
        avg_price_f = float(avg_price)
    except (TypeError, ValueError):
        return 0.0
    # Conservative fallback + buffer for fees/slippage.
    return ((contracts_f * avg_price_f) / 100.0) * 1.1


def compute_positions_exposure(positions: list[dict[str, Any]]) -> float:
    exposure = 0.0
    for position in positions:
        market_exposure = position.get("market_exposure")
        if market_exposure is not None:
            exposure += _cents_to_dollars(market_exposure)
            continue
        exposure += _fallback_notional_dollars(position)
    return exposure


def compute_open_orders_exposure(orders: list[dict[str, Any]]) -> float:
    exposure = 0.0
    for order in orders:
        buy_max_cost = order.get("buy_max_cost")
        if buy_max_cost is not None:
            exposure += _cents_to_dollars(buy_max_cost)
            continue

        action = str(order.get("action") or "").lower()
        if action != "buy":
            continue
        count = order.get("remaining_count") or order.get("count") or 0
        price = order.get("yes_price")
        if price is None:
            price = order.get("no_price")
        if price is None:
            price = order.get("price")
        try:
            exposure += (float(count) * float(price)) / 100.0
        except (TypeError, ValueError):
            continue
    return exposure


def enforce_cap(current_open_notional: float, new_order_notional: float, cap_dollars: float) -> bool:
    return (current_open_notional + new_order_notional) <= cap_dollars
