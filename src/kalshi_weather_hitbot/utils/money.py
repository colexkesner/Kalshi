from __future__ import annotations


def dollars_to_cents(value: float) -> int:
    return int(round(value * 100))


def cents_to_dollars(cents: int) -> str:
    return f"{cents / 100:.2f}"
