from kalshi_weather_hitbot.strategy.fees import fee_per_contract_cents, kalshi_fee_cents


def test_kalshi_fee_cents_taker_and_maker_single_contract():
    assert kalshi_fee_cents(price_cents=50, contracts=1, fee_kind="maker") == 1
    assert kalshi_fee_cents(price_cents=50, contracts=1, fee_kind="taker") == 2


def test_kalshi_fee_cents_rounds_up_total_fee():
    # 0.0175 * 10 * 0.9 * 0.1 * 100 = 1.575 -> ceil -> 2 cents total
    assert kalshi_fee_cents(price_cents=90, contracts=10, fee_kind="maker") == 2


def test_fee_per_contract_cents_uses_conservative_ceil_division():
    assert fee_per_contract_cents(total_fee_cents=2, contracts=10) == 1
    assert fee_per_contract_cents(total_fee_cents=5, contracts=2) == 3
    assert fee_per_contract_cents(total_fee_cents=0, contracts=3) == 0
