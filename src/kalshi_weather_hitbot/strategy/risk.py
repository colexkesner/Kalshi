from __future__ import annotations


def compute_cap_dollars(balance_dollars: float, cap_mode: str, cap_value: float) -> float:
    if cap_mode == "percent":
        return balance_dollars * cap_value / 100.0
    return cap_value


def enforce_cap(current_open_notional: float, new_order_notional: float, cap_dollars: float) -> bool:
    return (current_open_notional + new_order_notional) <= cap_dollars
