from kalshi_weather_hitbot.cli import _set_order_price_field


def test_set_order_price_field_uses_dollar_fields_when_enabled():
    order = {"ticker": "TEST", "side": "yes", "yes_price": 12}

    _set_order_price_field(order, side="YES", price_cents=37, send_price_in_dollars=True)

    assert order.get("yes_price_dollars") == "0.3700"
    assert "yes_price" not in order


def test_set_order_price_field_uses_cent_fields_when_disabled():
    order = {"ticker": "TEST", "side": "no", "no_price_dollars": "0.1200"}

    _set_order_price_field(order, side="NO", price_cents=88, send_price_in_dollars=False)

    assert order.get("no_price") == 88
    assert "no_price_dollars" not in order

