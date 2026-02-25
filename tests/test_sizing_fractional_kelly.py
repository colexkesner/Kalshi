from kalshi_weather_hitbot.config import RiskConfig, SizingConfig
from kalshi_weather_hitbot.strategy.sizing import compute_contracts, kelly_fraction_for_binary


def test_kelly_fraction_for_binary_clamps_to_range():
    assert kelly_fraction_for_binary(p=0.20, price=0.80) == 0.0
    assert kelly_fraction_for_binary(p=1.20, price=0.20) == 1.0


def test_kelly_fraction_for_binary_basic_value():
    out = kelly_fraction_for_binary(p=0.60, price=0.40)
    assert round(out, 4) == 0.3333


def test_compute_contracts_fixed_mode_preserves_default_one_contract():
    cfg = SizingConfig(mode="fixed", fixed_contracts=1)
    risk = RiskConfig()
    assert compute_contracts(100.0, 50, 0.60, cfg, risk) == 1


def test_compute_contracts_fractional_kelly_applies_caps():
    cfg = SizingConfig(
        mode="fractional_kelly",
        kelly_fraction=0.10,
        max_contracts_per_order=10,
        max_order_cost_dollars=3.00,
    )
    risk = RiskConfig(max_per_market_notional=10.0)
    # p=0.6, price=$0.50 -> f*=0.2, fractional f=0.02, target=$2 on $100 bankroll => 4 contracts
    assert compute_contracts(100.0, 50, 0.60, cfg, risk) == 4


def test_compute_contracts_fractional_kelly_can_return_zero_when_too_small():
    cfg = SizingConfig(mode="fractional_kelly", kelly_fraction=0.10, max_contracts_per_order=10, max_order_cost_dollars=25.0)
    risk = RiskConfig(max_per_market_notional=50.0)
    assert compute_contracts(10.0, 95, 0.951, cfg, risk) == 0


def test_compute_contracts_clamps_fixed_size_by_risk_and_order_caps():
    cfg = SizingConfig(mode="fixed", fixed_contracts=20, max_contracts_per_order=10, max_order_cost_dollars=25.0)
    risk = RiskConfig(max_per_market_notional=1.5)
    # Price $1.00, risk notional cap allows only 1 contract.
    assert compute_contracts(100.0, 100, 0.99, cfg, risk) == 1
