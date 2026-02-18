from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LockEval:
    lock_status: str
    p_yes: float
    min_possible: float
    max_possible: float


def evaluate_lock(
    bracket_low: float | None,
    bracket_high: float | None,
    observed_max: float,
    forecast_max_remaining: float,
    safety_bias_f: float = 3.0,
    p_yes_locked: float = 0.99,
    p_no_locked: float = 0.01,
    station_uncertainty_f: float = 0.5,
) -> LockEval:
    min_possible = observed_max - station_uncertainty_f
    max_possible = max(observed_max, forecast_max_remaining + safety_bias_f) + station_uncertainty_f

    if bracket_low is None and bracket_high is None:
        return LockEval("UNLOCKED", 0.5, min_possible, max_possible)

    # "X or below" style: can only prove YES lock.
    if bracket_low is None and bracket_high is not None:
        if max_possible < bracket_high:
            return LockEval("LOCKED_YES", p_yes_locked, min_possible, max_possible)
        return LockEval("UNLOCKED", 0.5, min_possible, max_possible)

    # "X or above" style: can only prove NO lock.
    if bracket_high is None and bracket_low is not None:
        if min_possible > bracket_low:
            return LockEval("LOCKED_NO", p_no_locked, min_possible, max_possible)
        return LockEval("UNLOCKED", 0.5, min_possible, max_possible)

    assert bracket_low is not None and bracket_high is not None

    if min_possible >= bracket_low and max_possible <= bracket_high:
        return LockEval("LOCKED_YES", p_yes_locked, min_possible, max_possible)
    if min_possible > bracket_high or max_possible < bracket_low:
        return LockEval("LOCKED_NO", p_no_locked, min_possible, max_possible)
    return LockEval("UNLOCKED", 0.5, min_possible, max_possible)
