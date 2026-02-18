from __future__ import annotations

from math import ceil, floor


def quantize_price(price_cents: int, tick_size: int = 1, side: str = "buy") -> int:
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")
    if side.lower() == "buy":
        return int(floor(price_cents / tick_size) * tick_size)
    return int(ceil(price_cents / tick_size) * tick_size)
