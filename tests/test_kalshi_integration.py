from kalshi_weather_hitbot.cli import _available_dollars, _order_payload
from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.models import normalize_orderbook
from kalshi_weather_hitbot.strategy.execution import ExecutionDecision
from kalshi_weather_hitbot.strategy.risk import compute_positions_exposure, enforce_cap


def test_orderbook_normalization_bids_only():
    response = {
        "orderbook": {
            "yes": [[10, 1], [30, 4], [45, 7]],
            "no": [[20, 2], [35, 5], [60, 8]],
        }
    }

    out = normalize_orderbook(response)

    assert out.best_yes_bid_cents == 45
    assert out.best_no_bid_cents == 60
    assert out.best_yes_ask_cents == 40
    assert out.best_no_ask_cents == 55
    assert out.yes_bid_size == 7
    assert out.no_bid_size == 8


def test_create_order_payload_yes_buy_and_no_buy():
    cfg = AppConfig()
    yes_buy = ExecutionDecision(should_trade=True, side="YES", action="BUY", price_cents=42)
    no_buy = ExecutionDecision(should_trade=True, side="NO", action="BUY", price_cents=58)

    yes_payload = _order_payload(
        cfg=cfg,
        ticker="TEST-YES",
        decision=yes_buy,
        count=1,
        tif="good_till_canceled",
        post_only=True,
        strategy_mode="HOLD_TO_SETTLEMENT",
        cycle_key="ENTRY-20240101",
    )
    no_payload = _order_payload(
        cfg=cfg,
        ticker="TEST-NO",
        decision=no_buy,
        count=1,
        tif="good_till_canceled",
        post_only=True,
        strategy_mode="HOLD_TO_SETTLEMENT",
        cycle_key="ENTRY-20240101",
    )

    assert yes_payload["side"] == "yes"
    assert yes_payload["action"] == "buy"
    assert yes_payload["count_fp"] == "1.00"
    assert "yes_price_dollars" in yes_payload
    assert "no_price_dollars" not in yes_payload

    assert no_payload["side"] == "no"
    assert no_payload["action"] == "buy"
    assert no_payload["count_fp"] == "1.00"
    assert "no_price_dollars" in no_payload
    assert "yes_price_dollars" not in no_payload


def test_balance_parsing_cents():
    assert _available_dollars({"balance": 12345}) == 123.45


def test_cap_enforcement_with_positions():
    positions = [{"market_exposure": 950}]
    current_exposure = compute_positions_exposure(positions)
    new_order_notional = 1.0
    cap = 10.0

    assert enforce_cap(current_exposure, new_order_notional, cap) is False
