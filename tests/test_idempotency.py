from kalshi_weather_hitbot.strategy.execution import build_client_order_id_deterministic


def test_deterministic_client_order_id_stable_for_same_inputs():
    one = build_client_order_id_deterministic("KXTEST", "YES", "BUY", 44, 1, "HOLD_TO_SETTLEMENT", "ENTRY-20240101")
    two = build_client_order_id_deterministic("KXTEST", "YES", "BUY", 44, 1, "HOLD_TO_SETTLEMENT", "ENTRY-20240101")
    assert one == two


def test_deterministic_client_order_id_changes_with_inputs():
    one = build_client_order_id_deterministic("KXTEST", "YES", "BUY", 44, 1, "HOLD_TO_SETTLEMENT", "ENTRY-20240101")
    two = build_client_order_id_deterministic("KXTEST", "YES", "BUY", 45, 1, "HOLD_TO_SETTLEMENT", "ENTRY-20240101")
    assert one != two
