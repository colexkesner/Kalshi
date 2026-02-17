from src.risk import RiskLimits, RiskManager
from venues.base import VenueOrderRequest


def test_risk_blocks_max_open_orders():
    risk = RiskManager(RiskLimits(max_open_orders=1))
    order = VenueOrderRequest(token_id="1", price=0.5, size=10, side="BUY")
    ok, reason = risk.validate_order(order, open_orders=[{"id": "a"}], positions=[])
    assert ok is False
    assert "MAX_OPEN_ORDERS" in reason


def test_risk_blocks_daily_notional():
    risk = RiskManager(RiskLimits(max_daily_notional=1))
    order = VenueOrderRequest(token_id="1", price=0.5, size=10, side="BUY")
    ok, reason = risk.validate_order(order, open_orders=[], positions=[])
    assert ok is False
    assert "MAX_DAILY_NOTIONAL" in reason
