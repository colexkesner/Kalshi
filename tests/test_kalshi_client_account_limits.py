import pytest

from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.client import APIError, KalshiClient


def test_get_account_limits_returns_payload_dict():
    client = KalshiClient(AppConfig())
    client._request = lambda *_args, **_kwargs: {"max_open_orders": 100}  # type: ignore[method-assign]
    out = client.get_account_limits()
    assert out["max_open_orders"] == 100


def test_get_account_limits_raises_on_non_dict_payload():
    client = KalshiClient(AppConfig())
    client._request = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
    with pytest.raises(APIError, match="Malformed /trade-api/v2/account/limits response"):
        client.get_account_limits()
