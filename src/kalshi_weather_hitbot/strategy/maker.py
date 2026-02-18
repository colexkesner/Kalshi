from __future__ import annotations

from dataclasses import dataclass

from kalshi_weather_hitbot.config import RiskConfig
from kalshi_weather_hitbot.kalshi.models import OrderBookTop


@dataclass
class MakerEntry:
    should_place: bool
    price_cents: int | None = None
    reason: str = ""


def maker_first_entry_price(target_side: str, book: OrderBookTop, max_price_allowed_cents: int, risk: RiskConfig) -> MakerEntry:
    implied_ask = book.best_yes_ask_cents if target_side == "YES" else book.best_no_ask_cents
    if implied_ask is None:
        return MakerEntry(False, reason="Missing implied ask")

    maker_price = min(implied_ask - 1, max_price_allowed_cents)
    if maker_price < 1:
        return MakerEntry(False, reason="Invalid maker price")

    best_bid = book.best_yes_bid_cents if target_side == "YES" else book.best_no_bid_cents
    if best_bid is not None and maker_price - best_bid > risk.max_spread_cents:
        return MakerEntry(False, reason="Maker price too far from bid")

    return MakerEntry(True, price_cents=maker_price, reason="Maker-first entry")
