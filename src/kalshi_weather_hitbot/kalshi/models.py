from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OrderBookTop:
    best_yes_bid_cents: int | None
    best_yes_ask_cents: int | None
    best_no_bid_cents: int | None
    best_no_ask_cents: int | None
    yes_bid_size: int = 0
    yes_ask_size: int = 0
    no_bid_size: int = 0
    no_ask_size: int = 0


def _price_to_cents(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value * 100))
    if isinstance(value, str):
        if value.replace(".", "", 1).isdigit():
            if "." in value:
                return int(round(float(value) * 100))
            return int(value)
    return None


def normalize_orderbook(book: dict[str, Any]) -> OrderBookTop:
    yes = book.get("yes", {})
    no = book.get("no", {})
    return OrderBookTop(
        best_yes_bid_cents=_price_to_cents(yes.get("bid_dollars") or yes.get("bid")),
        best_yes_ask_cents=_price_to_cents(yes.get("ask_dollars") or yes.get("ask")),
        best_no_bid_cents=_price_to_cents(no.get("bid_dollars") or no.get("bid")),
        best_no_ask_cents=_price_to_cents(no.get("ask_dollars") or no.get("ask")),
        yes_bid_size=int(yes.get("bid_size") or 0),
        yes_ask_size=int(yes.get("ask_size") or 0),
        no_bid_size=int(no.get("bid_size") or 0),
        no_ask_size=int(no.get("ask_size") or 0),
    )
