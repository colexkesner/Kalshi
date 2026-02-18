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


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _best_bid(levels: Any) -> tuple[int | None, int]:
    if not isinstance(levels, list) or not levels:
        return None, 0
    raw = levels[-1]
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None, 0
    price = _to_int(raw[0])
    size = _to_int(raw[1]) or 0
    return price, size


def normalize_orderbook(response: dict[str, Any]) -> OrderBookTop:
    book = response.get("orderbook") if isinstance(response.get("orderbook"), dict) else response
    yes_levels = book.get("yes", []) if isinstance(book, dict) else []
    no_levels = book.get("no", []) if isinstance(book, dict) else []

    best_yes_bid, yes_bid_size = _best_bid(yes_levels)
    best_no_bid, no_bid_size = _best_bid(no_levels)

    best_yes_ask = (100 - best_no_bid) if best_no_bid is not None else None
    best_no_ask = (100 - best_yes_bid) if best_yes_bid is not None else None

    return OrderBookTop(
        best_yes_bid_cents=best_yes_bid,
        best_yes_ask_cents=best_yes_ask,
        best_no_bid_cents=best_no_bid,
        best_no_ask_cents=best_no_ask,
        yes_bid_size=yes_bid_size,
        yes_ask_size=no_bid_size,
        no_bid_size=no_bid_size,
        no_ask_size=yes_bid_size,
    )
