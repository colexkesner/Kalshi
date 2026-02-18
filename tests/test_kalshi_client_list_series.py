import pytest

from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.client import APIError, KalshiClient


def _client_with_payload(payload):
    client = KalshiClient(AppConfig())
    client._request = lambda *_args, **_kwargs: payload  # type: ignore[method-assign]
    return client


@pytest.mark.parametrize(
    "payload",
    [
        {"series": None},
        {},
        {"series": []},
    ],
)
def test_list_series_returns_empty_list_for_null_missing_or_empty_series(payload):
    client = _client_with_payload(payload)
    assert client.list_series(category="Climate") == []


def test_list_series_raises_for_non_list_series_field():
    client = _client_with_payload({"series": "bad"})
    with pytest.raises(APIError, match="Malformed /trade-api/v2/series response"):
        client.list_series(category="Climate")
