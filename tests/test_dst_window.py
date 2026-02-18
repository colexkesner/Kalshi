from datetime import datetime, timezone

from kalshi_weather_hitbot.strategy.screener import climate_window_start, parse_temperature_market


def test_climate_window_start_dst_uses_1am_local():
    # July in New York (DST). Close at 00:59 local next day.
    close_ts = datetime(2024, 7, 2, 4, 59, tzinfo=timezone.utc)
    start = climate_window_start(close_ts, "America/New_York")
    assert start == datetime(2024, 7, 1, 5, 0, tzinfo=timezone.utc)


def test_climate_window_start_standard_uses_midnight_local():
    # January in Chicago (standard time).
    close_ts = datetime(2024, 1, 1, 23, 59, tzinfo=timezone.utc)
    start = climate_window_start(close_ts, "America/Chicago")
    assert start == datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)


def test_parse_temperature_market_prefers_floor_cap_strike():
    market = {
        "title": "NYC High temp market",
        "subtitle": "random",
        "floor_strike": 70,
        "cap_strike": 75,
        "close_time": "2024-07-02T04:59:00Z",
    }

    parsed = parse_temperature_market(market)
    assert parsed is not None
    assert parsed.bracket_low == 70
    assert parsed.bracket_high == 75
