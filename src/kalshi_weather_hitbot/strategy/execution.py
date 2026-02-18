from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from kalshi_weather_hitbot.config import RiskConfig
from kalshi_weather_hitbot.kalshi.models import OrderBookTop
from kalshi_weather_hitbot.kalshi.pricing import quantize_price


@dataclass
class ExecutionDecision:
    should_trade: bool
    side: str | None = None
    action: str | None = None
    price_cents: int | None = None
    reason: str = ""


def select_order(lock_status: str, p_yes: float, book: OrderBookTop, risk: RiskConfig) -> ExecutionDecision:
    if lock_status == "UNLOCKED":
        return ExecutionDecision(False, reason="Not locked")

    target_side = "YES" if lock_status == "LOCKED_YES" else "NO"
    ask = book.best_yes_ask_cents if target_side == "YES" else book.best_no_ask_cents
    bid = book.best_yes_bid_cents if target_side == "YES" else book.best_no_bid_cents
    size = book.yes_ask_size if target_side == "YES" else book.no_ask_size

    if ask is None or bid is None:
        return ExecutionDecision(False, reason="Missing orderbook prices")
    if (ask - bid) > risk.max_spread_cents:
        return ExecutionDecision(False, reason="Spread too wide")
    if size < risk.min_liquidity_contracts:
        return ExecutionDecision(False, reason="Insufficient liquidity")

    max_price_prob = p_yes - risk.edge_buffer if target_side == "YES" else (1 - p_yes) - risk.edge_buffer
    max_price_cents = int(max_price_prob * 100)
    if ask > max_price_cents:
        return ExecutionDecision(False, reason="Price above edge-adjusted threshold")
    return ExecutionDecision(True, side=target_side, action="BUY", price_cents=quantize_price(ask, tick_size=1, side="buy"), reason="Locked and edge positive")


def select_exit_order(position: dict[str, Any], book: OrderBookTop, risk: RiskConfig) -> ExecutionDecision:
    if not risk.enable_exit_sells:
        return ExecutionDecision(False, reason="Exit sells disabled")

    side = str(position.get("side") or position.get("position_side") or "").upper()
    contracts = int(position.get("contracts") or position.get("position") or 0)
    if contracts <= 0 or side not in {"YES", "NO"}:
        return ExecutionDecision(False, reason="No long position to exit")

    exit_bid = book.best_yes_bid_cents if side == "YES" else book.best_no_bid_cents
    exit_size = book.yes_bid_size if side == "YES" else book.no_bid_size
    best_ask = book.best_yes_ask_cents if side == "YES" else book.best_no_ask_cents

    if exit_bid is None or best_ask is None:
        return ExecutionDecision(False, reason="Missing exit prices")
    if exit_size < min(risk.min_liquidity_contracts, contracts):
        return ExecutionDecision(False, reason="Insufficient bid depth for exit")
    if (best_ask - exit_bid) > risk.max_spread_cents:
        return ExecutionDecision(False, reason="Spread too wide for safe exit")

    entry_price = int(position.get("avg_price") or position.get("average_price") or 0)
    if exit_bid < risk.take_profit_cents:
        return ExecutionDecision(False, reason="Take-profit not reached")
    if entry_price and (exit_bid - entry_price) < risk.min_profit_cents:
        return ExecutionDecision(False, reason="Minimum profit threshold not reached")

    return ExecutionDecision(
        True,
        side=side,
        action="SELL",
        price_cents=quantize_price(exit_bid, tick_size=1, side="sell"),
        reason="Take-profit exit",
    )


def build_client_order_id(market_ticker: str) -> str:
    return f"hitbot-{market_ticker}-{uuid.uuid4().hex[:12]}"
