from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from kalshi_weather_hitbot.db import DB


def beta_posterior_mean(alpha: float, beta: float, wins: int, losses: int) -> float:
    total_alpha = float(alpha) + max(0, int(wins))
    total_beta = float(beta) + max(0, int(losses))
    if total_alpha + total_beta <= 0:
        return 0.5
    return total_alpha / (total_alpha + total_beta)


def _bucket_label(hours_to_close: float, buckets_hours_to_close: list[float]) -> float:
    for b in sorted(buckets_hours_to_close):
        if hours_to_close <= b:
            return float(b)
    if not buckets_hours_to_close:
        return float("inf")
    return float(max(buckets_hours_to_close))


def build_lock_calibration(
    db_path: str,
    by_city: bool,
    buckets_hours_to_close: list[float],
    *,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    min_samples_per_bucket: int = 5,
) -> Callable[[str | None, float, str, float], float]:
    db = DB(db_path)
    rows: list[tuple[str, str | None, str | None, str | None]] = []
    with db.connect() as con:
        query = """
            SELECT s.ticker, s.market_result, o.request_json, e.raw_payload
            FROM settlements s
            LEFT JOIN orders o ON o.market_ticker = s.ticker
            LEFT JOIN run_evaluations e ON e.market_ticker = s.ticker
            ORDER BY s.id DESC, o.id DESC, e.id DESC
        """
        rows = list(con.execute(query).fetchall())

    # Collapse to most recent order/eval per ticker with a buy side and lock context.
    per_ticker: dict[str, tuple[str, str | None, float]] = {}
    for ticker, market_result, request_json, eval_raw in rows:
        if not ticker or ticker in per_ticker:
            continue
        if not request_json or not eval_raw or not market_result:
            continue
        try:
            req = json.loads(request_json)
            ev = json.loads(eval_raw)
        except json.JSONDecodeError:
            continue
        if str(req.get("action") or "").lower() != "buy":
            continue
        side = str(req.get("side") or "").upper()
        if side not in {"YES", "NO"}:
            continue
        lock_status = str(ev.get("lock_status") or "")
        if lock_status not in {"LOCKED_YES", "LOCKED_NO"}:
            continue
        try:
            hours_to_close = float(ev.get("hours_to_close"))
        except (TypeError, ValueError):
            continue
        # Win = held side matched settlement market result.
        result = str(market_result).upper()
        if result in {"YES", "NO"}:
            won = result == side
        elif result in {"1", "TRUE"}:
            won = side == "YES"
        elif result in {"0", "FALSE"}:
            won = side == "NO"
        else:
            continue
        city_key = str(ev.get("city_key") or "") or None
        key_city = city_key if by_city else None
        bucket = _bucket_label(hours_to_close, buckets_hours_to_close)
        per_ticker[ticker] = ("1" if won else "0", key_city, bucket)

    counts: dict[tuple[str | None, float], tuple[int, int]] = {}
    for won_str, city_key, bucket in per_ticker.values():
        key = (city_key, float(bucket))
        wins, losses = counts.get(key, (0, 0))
        if won_str == "1":
            wins += 1
        else:
            losses += 1
        counts[key] = (wins, losses)

    prior_mean = beta_posterior_mean(prior_alpha, prior_beta, 0, 0)

    def lookup(city_key: str | None, hours_to_close: float, lock_status: str, base_p_yes: float) -> float:
        if lock_status not in {"LOCKED_YES", "LOCKED_NO"}:
            return base_p_yes
        bucket = _bucket_label(hours_to_close, buckets_hours_to_close)
        key_city = city_key if by_city else None
        wins, losses = counts.get((key_city, bucket), (0, 0))
        total = wins + losses
        if total < min_samples_per_bucket:
            calibrated_lock_correct_prob = prior_mean
        else:
            calibrated_lock_correct_prob = beta_posterior_mean(prior_alpha, prior_beta, wins, losses)
        return calibrated_lock_correct_prob if lock_status == "LOCKED_YES" else (1.0 - calibrated_lock_correct_prob)

    return lookup
