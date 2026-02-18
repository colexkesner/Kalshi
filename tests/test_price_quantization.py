from kalshi_weather_hitbot.kalshi.pricing import quantize_price


def test_quantize_buy_rounds_down():
    assert quantize_price(57, tick_size=5, side="buy") == 55


def test_quantize_sell_rounds_up():
    assert quantize_price(57, tick_size=5, side="sell") == 60
