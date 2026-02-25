from __future__ import annotations

import math
from typing import Literal


def kalshi_fee_cents(price_cents: int, contracts: int, fee_kind: Literal["taker", "maker"]) -> int:
    if contracts <= 0:
        return 0
    p = max(0.0, min(1.0, price_cents / 100.0))
    coeff = 0.0175 if fee_kind == "maker" else 0.07
    fee_dollars = math.ceil(coeff * contracts * p * (1 - p) * 100) / 100.0
    return int(round(fee_dollars * 100))


def fee_per_contract_cents(total_fee_cents: int, contracts: int) -> int:
    if contracts <= 0 or total_fee_cents <= 0:
        return 0
    return (total_fee_cents + contracts - 1) // contracts
