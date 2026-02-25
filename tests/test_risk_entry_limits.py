from kalshi_weather_hitbot.config import RiskConfig
from kalshi_weather_hitbot.strategy.risk import (
    check_entry_risk_limits,
    count_active_orders_for_ticker,
    count_open_positions,
    exposure_dollars_for_ticker,
)


def test_count_open_positions_counts_nonzero_contracts_or_position():
    positions = [
        {"ticker": "A", "contracts": 1},
        {"ticker": "B", "position": -2},
        {"ticker": "C", "contracts": 0},
        {"ticker": "D"},
    ]
    assert count_open_positions(positions) == 2


def test_count_active_orders_for_ticker_counts_buy_orders_only():
    orders = [
        {"ticker": "T1", "action": "buy"},
        {"ticker": "T1", "action": "sell"},
        {"market_ticker": "T1", "action": "buy"},
        {"ticker": "T2", "action": "buy"},
    ]
    assert count_active_orders_for_ticker(orders, "T1") == 2


def test_exposure_dollars_for_ticker_sums_positions_and_buy_orders():
    positions = [{"ticker": "T1", "market_exposure_dollars": "3.50"}]
    orders = [{"ticker": "T1", "action": "buy", "buy_max_cost_dollars": "1.25"}]
    assert exposure_dollars_for_ticker(positions, orders, "T1") == 4.75


def test_check_entry_risk_limits_blocks_max_open_positions():
    risk = RiskConfig(max_open_positions=1, max_orders_per_market=5, max_per_market_notional=100.0)
    positions = [{"ticker": "T1", "contracts": 1}]
    allowed, reason = check_entry_risk_limits("T2", 1.0, positions, [], risk)
    assert allowed is False
    assert reason == "Max open positions reached"


def test_check_entry_risk_limits_blocks_max_orders_per_market():
    risk = RiskConfig(max_open_positions=5, max_orders_per_market=1, max_per_market_notional=100.0)
    active_orders = [{"ticker": "T1", "action": "buy"}]
    allowed, reason = check_entry_risk_limits("T1", 1.0, [], active_orders, risk)
    assert allowed is False
    assert reason == "Max orders per market reached"


def test_check_entry_risk_limits_blocks_max_per_market_notional():
    risk = RiskConfig(max_open_positions=5, max_orders_per_market=5, max_per_market_notional=5.0)
    positions = [{"ticker": "T1", "market_exposure_dollars": "4.25"}]
    active_orders = [{"ticker": "T1", "action": "buy", "buy_max_cost_dollars": "0.50"}]
    allowed, reason = check_entry_risk_limits("T1", 0.50, positions, active_orders, risk)
    assert allowed is False
    assert reason == "Max per-market notional exceeded"
