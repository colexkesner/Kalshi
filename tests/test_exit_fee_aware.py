from kalshi_weather_hitbot.config import FeesConfig, RiskConfig
from kalshi_weather_hitbot.kalshi.models import OrderBookTop
from kalshi_weather_hitbot.strategy.execution import select_exit_order


def _exit_book(bid_cents: int, ask_cents: int = 99, size: int = 10) -> OrderBookTop:
    return OrderBookTop(
        best_yes_bid_cents=bid_cents,
        best_yes_ask_cents=ask_cents,
        best_no_bid_cents=1,
        best_no_ask_cents=2,
        yes_bid_size=size,
        yes_ask_size=size,
        no_bid_size=size,
        no_ask_size=size,
    )


def test_exit_fee_aware_blocks_fake_one_cent_profit():
    risk = RiskConfig(min_profit_cents=1, take_profit_cents=98, min_liquidity_contracts=1, max_spread_cents=5)
    fees = FeesConfig(enabled=True, assume_taker_fee_on_exit=True)
    pos = {"side": "YES", "contracts": 1, "avg_price": 97}

    out = select_exit_order(pos, _exit_book(98), risk, fees)

    assert out.should_trade is False
    assert "net of exit fee" in out.reason


def test_exit_fee_aware_allows_real_profit_after_fee():
    risk = RiskConfig(min_profit_cents=1, take_profit_cents=98, min_liquidity_contracts=1, max_spread_cents=5)
    fees = FeesConfig(enabled=True, assume_taker_fee_on_exit=True)
    pos = {"side": "YES", "contracts": 1, "avg_price": 95}

    out = select_exit_order(pos, _exit_book(98), risk, fees)

    assert out.should_trade is True
    assert out.action == "SELL"


def test_exit_fee_aware_multi_contract_uses_conservative_per_contract_rounding():
    risk = RiskConfig(min_profit_cents=2, take_profit_cents=50, min_liquidity_contracts=1, max_spread_cents=50)
    fees = FeesConfig(enabled=True, assume_taker_fee_on_exit=True)
    pos = {"side": "YES", "contracts": 3, "avg_price": 48}

    out = select_exit_order(pos, _exit_book(50, ask_cents=51, size=10), risk, fees)

    # At 50c taker fees round to 6c total for 3 contracts => 2c per contract, so 2c gross is not enough.
    assert out.should_trade is False
    assert "net of exit fee" in out.reason

