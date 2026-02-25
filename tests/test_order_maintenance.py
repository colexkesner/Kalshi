from datetime import datetime, timezone

from kalshi_weather_hitbot.config import RiskConfig
from kalshi_weather_hitbot.strategy.order_maintenance import (
    build_amend_payload,
    order_age_seconds,
    parse_order_price_cents,
    should_amend,
)


def test_parse_order_price_cents_handles_side_specific_cents_and_dollars():
    assert parse_order_price_cents({"side": "yes", "yes_price": 42}) == 42
    assert parse_order_price_cents({"side": "no", "no_price_dollars": "0.8800"}) == 88
    assert parse_order_price_cents({"side": "no", "price": 55}) == 55


def test_order_age_seconds_parses_iso_timestamp():
    now_utc = datetime(2026, 2, 25, 13, 0, tzinfo=timezone.utc)
    order = {"created_time": "2026-02-25T12:58:30Z"}
    assert order_age_seconds(order, now_utc) == 90.0


def test_should_amend_respects_flags_age_and_tick():
    cfg = RiskConfig(order_maintenance_enabled=True, amend_min_age_seconds=60, amend_min_tick=2)
    assert should_amend(existing_price=40, desired_price=43, age_seconds=61, cfg=cfg) is True
    assert should_amend(existing_price=40, desired_price=41, age_seconds=61, cfg=cfg) is False
    assert should_amend(existing_price=40, desired_price=43, age_seconds=30, cfg=cfg) is False
    assert should_amend(existing_price=40, desired_price=43, age_seconds=61, cfg=RiskConfig(order_maintenance_enabled=False)) is False


def test_build_amend_payload_supports_cents_and_dollars():
    cents_payload = build_amend_payload("oid", "TICK", "YES", "buy", 47, 2, False)
    assert cents_payload["yes_price"] == 47
    assert cents_payload["count_fp"] == "2.00"

    dollars_payload = build_amend_payload("oid", "TICK", "NO", "buy", 88, 1, True)
    assert dollars_payload["no_price_dollars"] == "0.8800"
    assert "no_price" not in dollars_payload
