from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from kalshi_weather_hitbot.config import RiskConfig


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


def count_open_positions(positions: list[dict[str, Any]]) -> int:
    count = 0
    for position in positions:
        contracts = _to_float(position.get("contracts"))
        if contracts is None:
            contracts = _to_float(position.get("position"))
        if contracts is not None and abs(contracts) > 0:
            count += 1
    return count


def count_active_orders_for_ticker(active_orders: list[dict[str, Any]], ticker: str) -> int:
    target = str(ticker)
    return sum(
        1
        for order in active_orders
        if str(order.get("action") or "").lower() == "buy"
        and str(order.get("ticker") or order.get("market_ticker") or "") == target
    )


def _order_buy_exposure_dollars(order: dict[str, Any]) -> float:
    buy_max_cost_dollars = order.get("buy_max_cost_dollars") or order.get("buy_max_cost_fp")
    if buy_max_cost_dollars is not None:
        parsed = _to_float(buy_max_cost_dollars)
        return parsed if parsed is not None else 0.0

    buy_max_cost = order.get("buy_max_cost")
    if buy_max_cost is not None:
        return _cents_to_dollars(buy_max_cost)

    action = str(order.get("action") or "").lower()
    if action != "buy":
        return 0.0
    count = _to_float(order.get("remaining_count") or order.get("count") or order.get("count_fp")) or 0
    side = str(order.get("side") or "").lower()
    if side == "yes":
        price = order.get("yes_price")
    elif side == "no":
        price = order.get("no_price")
    else:
        price = order.get("yes_price")
        if price is None:
            price = order.get("no_price")
    if price is None:
        price = order.get("price")
    price_val = _to_float(price) or 0
    return (count * price_val) / 100.0


def exposure_dollars_for_ticker(
    positions: list[dict[str, Any]],
    active_orders: list[dict[str, Any]],
    ticker: str,
) -> float:
    target = str(ticker)
    exposure = 0.0
    for position in positions:
        if str(position.get("ticker") or position.get("market_ticker") or "") != target:
            continue
        market_exposure = _parse_exposure_dollars(position)
        if market_exposure > 0:
            exposure += market_exposure
            continue
        exposure += _fallback_notional_dollars(position)
    for order in active_orders:
        if str(order.get("ticker") or order.get("market_ticker") or "") != target:
            continue
        exposure += _order_buy_exposure_dollars(order)
    return exposure


def compute_open_orders_exposure(orders: list[dict[str, Any]]) -> float:
    exposure = 0.0
    for order in orders:
        exposure += _order_buy_exposure_dollars(order)
    return exposure


def enforce_cap(current_open_notional: float, new_order_notional: float, cap_dollars: float) -> bool:
    return (current_open_notional + new_order_notional) <= cap_dollars


def check_entry_risk_limits(
    ticker: str,
    new_order_notional: float,
    positions: list[dict[str, Any]],
    active_orders: list[dict[str, Any]],
    risk: RiskConfig,
) -> tuple[bool, str]:
    if count_open_positions(positions) >= risk.max_open_positions:
        return False, "Max open positions reached"
    if count_active_orders_for_ticker(active_orders, ticker) >= risk.max_orders_per_market:
        return False, "Max orders per market reached"
    if exposure_dollars_for_ticker(positions, active_orders, ticker) + new_order_notional > risk.max_per_market_notional:
        return False, "Max per-market notional exceeded"
    return True, ""
