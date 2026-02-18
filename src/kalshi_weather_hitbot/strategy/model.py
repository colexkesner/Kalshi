from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LockEval:
    lock_status: str
    p_yes: float
    min_possible: float
    max_possible: float


def evaluate_lock(bracket_low: float, bracket_high: float, observed_max: float, forecast_max_remaining: float, safety_bias_f: float = 3.0, p_yes_locked: float = 0.99, p_no_locked: float = 0.01) -> LockEval:
    min_possible = observed_max
    max_possible = max(observed_max, forecast_max_remaining + safety_bias_f)

    if min_possible >= bracket_low and max_possible <= bracket_high:
        return LockEval("LOCKED_YES", p_yes_locked, min_possible, max_possible)
    if min_possible > bracket_high or max_possible < bracket_low:
        return LockEval("LOCKED_NO", p_no_locked, min_possible, max_possible)
    return LockEval("UNLOCKED", 0.5, min_possible, max_possible)
