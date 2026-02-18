from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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


def _parse_cents(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    # Fixed-point dollar inputs (e.g. "0.47") should map to cents.
    if dec <= 1 and dec >= 0 and "." in str(value):
        return int((dec * 100).quantize(Decimal("1")))
    return int(dec.quantize(Decimal("1")))


def _parse_qty(value: Any) -> int:
    if value is None:
        return 0
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 0
    return int(dec)


def _extract_level(level: Any, side_label: str) -> tuple[int | None, int]:
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return _parse_cents(level[0]), _parse_qty(level[1])
    if isinstance(level, dict):
        price = (
            level.get("price")
            or level.get("price_cents")
            or level.get("price_fp")
            or level.get(f"{side_label}_dollars")
            or level.get(f"{side_label}_dollars_fp")
        )
        qty = level.get("qty") or level.get("quantity") or level.get("quantity_fp") or level.get("count") or level.get("count_fp")
        return _parse_cents(price), _parse_qty(qty)
    return None, 0


def _best_bid(levels: Any, side_label: str) -> tuple[int | None, int]:
    if not isinstance(levels, list) or not levels:
        return None, 0
    return _extract_level(levels[-1], side_label)


def normalize_orderbook(response: dict[str, Any]) -> OrderBookTop:
    if isinstance(response.get("orderbook_fp"), dict):
        book = response["orderbook_fp"]
        yes_levels = book.get("yes_dollars") or book.get("yes") or []
        no_levels = book.get("no_dollars") or book.get("no") or []
    else:
        book = response.get("orderbook") if isinstance(response.get("orderbook"), dict) else response
        yes_levels = book.get("yes", []) if isinstance(book, dict) else []
        no_levels = book.get("no", []) if isinstance(book, dict) else []

    best_yes_bid, yes_bid_size = _best_bid(yes_levels, "yes")
    best_no_bid, no_bid_size = _best_bid(no_levels, "no")

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
