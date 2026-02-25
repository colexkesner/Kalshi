from kalshi_weather_hitbot.cli import order_aligned_with_lock, resolve_trading_enabled


def test_order_aligned_with_lock():
    assert order_aligned_with_lock("yes", "LOCKED_YES") is True
    assert order_aligned_with_lock("no", "LOCKED_YES") is False
    assert order_aligned_with_lock("yes", "UNLOCKED") is False
    assert order_aligned_with_lock("yes", None) is False


def test_resolve_trading_enabled_uses_cli_or_config_flag():
    assert resolve_trading_enabled(False, False) is False
    assert resolve_trading_enabled(False, True) is True
    assert resolve_trading_enabled(True, False) is True
