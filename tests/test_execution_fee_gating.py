from kalshi_weather_hitbot.config import FeesConfig, RiskConfig
from kalshi_weather_hitbot.kalshi.models import OrderBookTop
from kalshi_weather_hitbot.strategy.execution import select_order


def _book_yes_ask_90() -> OrderBookTop:
    return OrderBookTop(
        best_yes_bid_cents=89,
        best_yes_ask_cents=90,
        best_no_bid_cents=10,
        best_no_ask_cents=11,
        yes_bid_size=20,
        yes_ask_size=20,
        no_bid_size=20,
        no_ask_size=20,
    )


def test_select_order_blocks_when_fee_adjusted_net_edge_below_minimum():
    risk = RiskConfig(p_confidence_gate=0.50, edge_buffer=0.01, min_net_edge_cents=2)
    fees = FeesConfig(enabled=True, assume_maker_fee=True)
    out = select_order("LOCKED_YES", p_yes=0.92, book=_book_yes_ask_90(), risk=risk, fees_cfg=fees)
    assert out.should_trade is False
    assert out.reason == "Net edge below threshold"
    assert out.expected_fee_cents == 1
    assert out.expected_net_ev_cents == 1


def test_select_order_returns_expected_ev_fields_for_ranking():
    risk = RiskConfig(p_confidence_gate=0.50, edge_buffer=0.01, min_net_edge_cents=2)
    fees = FeesConfig(enabled=True, assume_maker_fee=False)
    out = select_order("LOCKED_YES", p_yes=0.95, book=_book_yes_ask_90(), risk=risk, fees_cfg=fees)
    assert out.should_trade is True
    assert out.expected_fee_cents == 0
    assert out.expected_net_ev_cents == 5
    assert "net_ev_cents=5" in out.reason


def test_select_order_uses_model_prob_for_confidence_gate():
    risk = RiskConfig(p_confidence_gate=0.90, edge_buffer=0.01, min_net_edge_cents=1)
    fees = FeesConfig(enabled=False, assume_maker_fee=False)
    out = select_order("LOCKED_YES", p_yes=0.60, model_prob=0.95, book=_book_yes_ask_90(), risk=risk, fees_cfg=fees)
    assert out.should_trade is True
