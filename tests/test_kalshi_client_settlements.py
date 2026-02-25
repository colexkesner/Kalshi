import pytest

from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.client import APIError, KalshiClient


def test_get_settlements_returns_payload_with_list():
    client = KalshiClient(AppConfig())
    client._request = lambda *_args, **_kwargs: {"settlements": [{"ticker": "T1"}], "cursor": "abc"}  # type: ignore[method-assign]
    out = client.get_settlements(limit=10)
    assert out["settlements"][0]["ticker"] == "T1"
    assert out["cursor"] == "abc"


def test_get_settlements_raises_on_invalid_settlements_field():
    client = KalshiClient(AppConfig())
    client._request = lambda *_args, **_kwargs: {"settlements": "bad"}  # type: ignore[method-assign]
    with pytest.raises(APIError, match="Malformed /trade-api/v2/portfolio/settlements response"):
        client.get_settlements()
