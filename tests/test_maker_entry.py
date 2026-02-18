from kalshi_weather_hitbot.config import RiskConfig
from kalshi_weather_hitbot.kalshi.models import OrderBookTop
from kalshi_weather_hitbot.strategy.maker import maker_first_entry_price


def test_maker_entry_prices_one_tick_below_implied_ask():
    book = OrderBookTop(best_yes_bid_cents=43, best_yes_ask_cents=48, best_no_bid_cents=52, best_no_ask_cents=57, yes_bid_size=10, yes_ask_size=8, no_bid_size=8, no_ask_size=10)
    out = maker_first_entry_price("YES", book, max_price_allowed_cents=60, risk=RiskConfig())
    assert out.should_place is True
    assert out.price_cents == 47


def test_maker_entry_respects_max_price_allowed():
    book = OrderBookTop(best_yes_bid_cents=43, best_yes_ask_cents=48, best_no_bid_cents=52, best_no_ask_cents=57, yes_bid_size=10, yes_ask_size=8, no_bid_size=8, no_ask_size=10)
    out = maker_first_entry_price("YES", book, max_price_allowed_cents=45, risk=RiskConfig())
    assert out.should_place is True
    assert out.price_cents == 45
