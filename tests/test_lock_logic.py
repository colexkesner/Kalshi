from kalshi_weather_hitbot.strategy.model import evaluate_lock


def test_locked_yes():
    out = evaluate_lock(70, 75, observed_max=71, forecast_max_remaining=71, safety_bias_f=2)
    assert out.lock_status == "LOCKED_YES"
    assert out.p_yes == 0.99


def test_locked_no_too_hot():
    out = evaluate_lock(70, 75, observed_max=76, forecast_max_remaining=76, safety_bias_f=0)
    assert out.lock_status == "LOCKED_NO"
    assert out.p_yes == 0.01


def test_unlocked():
    out = evaluate_lock(70, 75, observed_max=72, forecast_max_remaining=74, safety_bias_f=3)
    assert out.lock_status == "UNLOCKED"
