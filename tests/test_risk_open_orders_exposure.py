from kalshi_weather_hitbot.strategy.risk import compute_open_orders_exposure


def test_compute_open_orders_exposure_uses_side_specific_price_for_no_buy():
    orders = [
        {
            "action": "buy",
            "side": "no",
            "remaining_count": 1,
            "yes_price": 22,
            "no_price": 78,
        }
    ]
    assert compute_open_orders_exposure(orders) == 0.78


def test_compute_open_orders_exposure_uses_side_specific_price_for_yes_buy():
    orders = [
        {
            "action": "buy",
            "side": "yes",
            "remaining_count": 2,
            "yes_price": 15,
            "no_price": 85,
        }
    ]
    assert compute_open_orders_exposure(orders) == 0.30
