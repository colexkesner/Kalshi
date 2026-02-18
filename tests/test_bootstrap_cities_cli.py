from pathlib import Path

import pytest
from click.exceptions import Exit

from kalshi_weather_hitbot.cli import bootstrap_cities
from kalshi_weather_hitbot.kalshi.client import APIError


class FakeClient:
    def __init__(self, cfg):
        _ = cfg

    def list_series(self, tags=None, category=None):
        _ = tags, category
        return [{"ticker": "KXHIGHTEMP-CHI", "title": "Highest temperature Chicago", "contract_terms_url": "x"}]


def test_bootstrap_cities_command_writes_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("kalshi_weather_hitbot.cli.KalshiClient", FakeClient)
    monkeypatch.setattr(
        "kalshi_weather_hitbot.cli.build_city_mapping",
        lambda series, **kwargs: ( {
            "chicago": {
                "kalshi_series_tickers": [series[0]["ticker"]],
                "resolution_location_name": "Chicago Midway, IL",
                "resolution_source_type": "nws_climate_daily",
                "nws_wfo": "LOT",
                "nws_location_label": "CHICAGO MIDWAY AP",
                "icao_station": "KMDW",
                "lat": 41.7868,
                "lon": -87.7522,
                "tz": "America/Chicago",
            }
        }, [] ),
    )

    class FakeDB:
        def __init__(self, _):
            pass

        def save_city_mapping_snapshot(self, yaml_text, source="bootstrap-cities"):
            assert "chicago" in yaml_text
            assert source == "bootstrap-cities"

    monkeypatch.setattr("kalshi_weather_hitbot.cli.DB", FakeDB)

    out = tmp_path / "cities.yaml"
    bootstrap_cities(overwrite=True, out=str(out), category="Climate")
    assert out.exists()
    assert "kalshi_series_tickers" in out.read_text()


def test_bootstrap_cities_command_empty_series_writes_valid_yaml(monkeypatch, tmp_path: Path):
    class EmptyClient:
        def __init__(self, cfg):
            _ = cfg

        def list_series(self, tags=None, category=None):
            _ = tags, category
            return []

    monkeypatch.setattr("kalshi_weather_hitbot.cli.KalshiClient", EmptyClient)
    monkeypatch.setattr(
        "kalshi_weather_hitbot.cli.build_city_mapping",
        lambda series, **kwargs: ({}, []),
    )

    class FakeDB:
        def __init__(self, _):
            pass

        def save_city_mapping_snapshot(self, yaml_text, source="bootstrap-cities"):
            assert source == "bootstrap-cities"
            assert yaml_text.strip() == "{}"

    monkeypatch.setattr("kalshi_weather_hitbot.cli.DB", FakeDB)

    out = tmp_path / "cities-empty.yaml"
    bootstrap_cities(overwrite=True, out=str(out), category="Climate")
    assert out.exists()
    assert out.read_text().strip() == "{}"


def test_bootstrap_cities_command_reports_api_failure(monkeypatch, capsys):
    class BrokenClient:
        def __init__(self, cfg):
            _ = cfg

        def list_series(self, tags=None, category=None):
            _ = tags, category
            raise APIError("Malformed /trade-api/v2/series response: expected 'series' to be a list or null, got str")

    monkeypatch.setattr("kalshi_weather_hitbot.cli.KalshiClient", BrokenClient)

    with pytest.raises(Exit) as exc:
        bootstrap_cities(overwrite=True, out="configs/cities.yaml", category="Climate")
    assert exc.value.exit_code == 1
    captured = capsys.readouterr()
    assert "bootstrap-cities failed:" in captured.err
