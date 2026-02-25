from __future__ import annotations

import math

from kalshi_weather_hitbot.config import RiskConfig, SizingConfig


def kelly_fraction_for_binary(p: float, price: float) -> float:
    if price >= 1.0:
        return 0.0
    if price <= 0.0:
        return 1.0 if p > 0 else 0.0
    raw = (p - price) / (1 - price)
    return max(0.0, min(1.0, raw))


def compute_contracts(
    bankroll_dollars: float,
    price_cents: int,
    p: float,
    cfg_sizing: SizingConfig,
    risk: RiskConfig,
) -> int:
    if bankroll_dollars <= 0 or price_cents <= 0:
        return 0
    price_dollars = price_cents / 100.0
    if price_dollars <= 0:
        return 0

    if cfg_sizing.mode == "fractional_kelly":
        f_star = kelly_fraction_for_binary(p=p, price=price_dollars)
        f = max(0.0, cfg_sizing.kelly_fraction) * f_star
        target_dollars = bankroll_dollars * f
        budget_dollars = min(target_dollars, max(0.0, cfg_sizing.max_order_cost_dollars))
        budget_cents = max(0, int(round(budget_dollars * 100)))
        contracts = budget_cents // int(price_cents)
    else:
        contracts = int(cfg_sizing.fixed_contracts)

    contracts = min(contracts, max(0, int(cfg_sizing.max_contracts_per_order)))
    max_by_market_notional = math.floor(max(0.0, risk.max_per_market_notional) / price_dollars)
    contracts = min(contracts, max(0, max_by_market_notional))
    if contracts <= 0:
        return 0
    return max(1, contracts)
