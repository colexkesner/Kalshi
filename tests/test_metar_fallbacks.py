from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import requests

from kalshi_weather_hitbot.cli import _scan_once
from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.data.metar import MetarClient


class _Resp:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        if self._payload is None:
            from requests.exceptions import JSONDecodeError

            raise JSONDecodeError("Expecting value", "", 0)
        return self._payload


class _SequenceSession:
    headers = {}

    def __init__(self, events):
        self.events = list(events)
        self.calls: list[str] = []

    def get(self, _url, *, params=None, timeout=None):
        _ = timeout
        station = str((params or {}).get("ids"))
        self.calls.append(station)
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def _valid_records():
    return [{"temp": 15, "obsTime": "2026-02-25T15:00:00Z"}]


def test_204_then_success_uses_fallback_station():
    client = MetarClient("https://aviationweather.gov", "test-agent", timeout_seconds=5, cooldown_seconds=600)
    client.session = _SequenceSession(
        [
            _Resp(status_code=204, payload=None, text="", headers={}),
            _Resp(status_code=200, payload=_valid_records(), headers={"Content-Type": "application/json"}),
        ]
    )  # type: ignore[assignment]

    records, station_used, status = client.fetch_metar_with_fallbacks(["KAAA", "KBBB"])

    assert status == "ok"
    assert station_used == "KBBB"
    assert records == _valid_records()


def test_timeout_then_success_uses_fallback_station():
    client = MetarClient("https://aviationweather.gov", "test-agent")
    client.session = _SequenceSession(
        [
            requests.Timeout("timeout"),
            _Resp(status_code=200, payload=_valid_records(), headers={"Content-Type": "application/json"}),
        ]
    )  # type: ignore[assignment]

    records, station_used, status = client.fetch_metar_with_fallbacks(["KAAA", "KBBB"])

    assert status == "ok"
    assert station_used == "KBBB"
    assert len(records) == 1


def test_cooldown_skip_avoids_known_bad_station_on_next_call():
    client = MetarClient("https://aviationweather.gov", "test-agent", timeout_seconds=5, cooldown_seconds=600)
    session = _SequenceSession(
        [
            _Resp(status_code=204, payload=None, text="", headers={}),
            _Resp(status_code=200, payload=_valid_records(), headers={"Content-Type": "application/json"}),
        ]
    )
    client.session = session  # type: ignore[assignment]

    first_records, first_used, first_status = client.fetch_metar_with_fallbacks(["KAAA"])
    assert first_records == []
    assert first_used is None
    assert first_status == "empty"

    second_records, second_used, second_status = client.fetch_metar_with_fallbacks(["KAAA", "KBBB"])
    assert second_status == "ok"
    assert second_used == "KBBB"
    assert second_records
    assert session.calls == ["KAAA", "KBBB"]


def test_scan_once_reuses_injected_metar_client_cache(monkeypatch, tmp_path: Path):
    class FakeClient:
        def __init__(self, _cfg=None):
            pass

        def list_markets(self, series_ticker: str, limit: int = 100, status: str = "open"):
            _ = series_ticker, limit, status
            return [{"ticker": "KXHIGHCHI-TEST"}]

    class FakeNWS:
        def hourly_forecast(self, lat: float, lon: float):
            _ = lat, lon
            return []

    monkeypatch.setattr(
        "kalshi_weather_hitbot.cli.load_city_mapping",
        lambda _p: {
            "chicago": {
                "kalshi_series_tickers": ["KXHIGHTEMP-CHI"],
                "icao_station": "KMDW",
                "icao_station_fallbacks": ["KORD"],
                "lat": 41.7868,
                "lon": -87.7522,
                "tz": "America/Chicago",
            }
        },
    )
    monkeypatch.setattr("kalshi_weather_hitbot.cli.parse_temperature_market", lambda _m: SimpleNamespace(
        bracket_low=70,
        bracket_high=75,
        close_ts=datetime.now(timezone.utc) + timedelta(hours=2),
    ))
    monkeypatch.setattr("kalshi_weather_hitbot.cli.max_forecast_temp_f", lambda periods, now_utc, close_ts: 80.0)
    monkeypatch.setattr("kalshi_weather_hitbot.cli.evaluate_lock", lambda *args, **kwargs: SimpleNamespace(
        min_possible=76.0,
        max_possible=85.0,
        lock_status="LOCKED_YES",
        p_yes=0.99,
    ))

    metar = MetarClient("https://aviationweather.gov", "test-agent", timeout_seconds=5, cooldown_seconds=600)
    session = _SequenceSession([_Resp(status_code=200, payload=_valid_records(), headers={"Content-Type": "application/json"})])
    metar.session = session  # type: ignore[assignment]

    cfg = AppConfig(db_path=str(tmp_path / "scan.db"))
    out1 = _scan_once(cfg, client=FakeClient(), metar=metar, nws=FakeNWS())
    out2 = _scan_once(cfg, client=FakeClient(), metar=metar, nws=FakeNWS())

    assert out1 and out2
    assert session.calls == ["KMDW"]  # second scan hits METAR cache on same client instance
    assert out1[0]["metar_station_used"] == "KMDW"
    assert out1[0]["metar_status"] == "ok"
