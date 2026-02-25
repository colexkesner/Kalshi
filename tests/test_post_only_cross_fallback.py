from kalshi_weather_hitbot.cli import _place_entry_order_with_post_only_cross_fallback
from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.client import APIError


class _Client:
    def __init__(self):
        self.calls = 0
        self.orders = []

    def place_order(self, payload):
        self.calls += 1
        self.orders.append(dict(payload))
        if self.calls == 1:
            raise APIError("post only cross")
        return {"ok": True, "order": {"status": "resting"}}

    def get_orderbook(self, ticker):
        _ = ticker
        return {"orderbook": {"yes": [[10, 1]], "no": [[20, 1], [40, 2]]}}


def test_post_only_cross_fallback_reprices_and_retries_once():
    client = _Client()
    cfg = AppConfig()
    cfg.risk.send_price_in_dollars = False
    cfg.risk.post_only_cross_retry_once = True
    order = {
        "ticker": "TEST",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "count_fp": "1.00",
        "post_only": True,
        "yes_price": 60,
    }

    out = _place_entry_order_with_post_only_cross_fallback(client, order, ticker="TEST", side="YES", cfg=cfg)

    assert out is not None
    assert client.calls == 2
    assert client.orders[0]["yes_price"] == 60
    # implied yes ask from no best bid 40 is 60, fallback reprices to 59 then retries
    assert client.orders[1]["yes_price"] == 59


def test_post_only_cross_fallback_disabled_re_raises():
    client = _Client()
    cfg = AppConfig()
    cfg.risk.post_only_cross_retry_once = False
    order = {"ticker": "TEST", "side": "yes", "action": "buy", "count": 1, "count_fp": "1.00", "post_only": True, "yes_price": 60}
    try:
        _place_entry_order_with_post_only_cross_fallback(client, order, ticker="TEST", side="YES", cfg=cfg)
        assert False, "expected APIError"
    except APIError:
        pass
