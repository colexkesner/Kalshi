from kalshi_weather_hitbot.config import RiskConfig
from kalshi_weather_hitbot.kalshi.models import OrderBookTop
from kalshi_weather_hitbot.strategy.execution import select_order


def _book() -> OrderBookTop:
    return OrderBookTop(
        best_yes_bid_cents=70,
        best_yes_ask_cents=75,
        best_no_bid_cents=20,
        best_no_ask_cents=25,
        yes_bid_size=20,
        yes_ask_size=20,
        no_bid_size=20,
        no_ask_size=20,
    )


def test_select_order_blocks_locked_yes_below_confidence_gate():
    risk = RiskConfig(p_confidence_gate=0.90, edge_buffer=0.01)
    out = select_order("LOCKED_YES", p_yes=0.80, book=_book(), risk=risk)
    assert out.should_trade is False
    assert "Confidence below gate" in out.reason


def test_select_order_blocks_locked_no_below_confidence_gate():
    risk = RiskConfig(p_confidence_gate=0.90, edge_buffer=0.01)
    out = select_order("LOCKED_NO", p_yes=0.30, book=_book(), risk=risk)
    assert out.should_trade is False
    assert "Confidence below gate" in out.reason
