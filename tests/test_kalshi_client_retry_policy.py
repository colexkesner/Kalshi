from __future__ import annotations

from types import SimpleNamespace

import pytest
from tenacity import wait_none

from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.client import KalshiClient, PermanentAPIError, RateLimitError, TransientAPIError


def _response(status_code: int, text: str = "err", headers: dict[str, str] | None = None):
    return SimpleNamespace(status_code=status_code, text=text, headers=headers or {}, json=lambda: {})


def test_request_does_not_retry_permanent_400(monkeypatch):
    client = KalshiClient(AppConfig())
    calls = {"count": 0}

    def fake_request(*_args, **_kwargs):
        calls["count"] += 1
        return _response(400, "bad request")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(PermanentAPIError):
        client._request("GET", "/trade-api/v2/test")

    assert calls["count"] == 1


def test_request_retries_transient_500(monkeypatch):
    client = KalshiClient(AppConfig())
    calls = {"count": 0}

    def fake_request(*_args, **_kwargs):
        calls["count"] += 1
        return _response(500, "server error")

    monkeypatch.setattr(client.session, "request", fake_request)
    monkeypatch.setattr(client._request.retry, "wait", wait_none())

    with pytest.raises(TransientAPIError):
        client._request("GET", "/trade-api/v2/test")

    assert calls["count"] == 4


def test_request_raises_rate_limit_error_and_honors_retry_after(monkeypatch):
    client = KalshiClient(AppConfig())
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *_args, **_kwargs: _response(429, "too many requests", headers={"Retry-After": "2"}),
    )
    slept: list[float] = []
    monkeypatch.setattr("kalshi_weather_hitbot.kalshi.client.time.sleep", lambda seconds: slept.append(seconds))

    with pytest.raises(RateLimitError) as excinfo:
        KalshiClient._request.__wrapped__(client, "GET", "/trade-api/v2/test")

    assert excinfo.value.retry_after_seconds == 2.0
    assert slept == [2.0]
