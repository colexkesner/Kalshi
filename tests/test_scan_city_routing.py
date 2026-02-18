from pathlib import Path

from kalshi_weather_hitbot.cli import _scan_once
from kalshi_weather_hitbot.config import AppConfig


def test_scan_uses_city_series_tickers(monkeypatch, tmp_path: Path):
    calls = []

    class FakeClient:
        def __init__(self, cfg):
            _ = cfg

        def list_markets(self, series_ticker: str, status: str = "open", limit: int = 100):
            _ = status, limit
            calls.append(series_ticker)
            return []

    monkeypatch.setattr("kalshi_weather_hitbot.cli.KalshiClient", FakeClient)
    monkeypatch.setattr(
        "kalshi_weather_hitbot.cli.load_city_mapping",
        lambda _p: {
            "chicago": {
                "kalshi_series_tickers": ["KXHIGHTEMP-CHI", "KXSNOW-CHI"],
                "icao_station": "KMDW",
                "lat": 41.7868,
                "lon": -87.7522,
                "tz": "America/Chicago",
            }
        },
    )

    cfg = AppConfig(db_path=str(tmp_path / "x.db"))
    _scan_once(cfg)

    assert "KXHIGHTEMP-CHI" in calls
    assert "KXSNOW-CHI" not in calls
