from pathlib import Path

from kalshi_weather_hitbot.cli import bootstrap_cities


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
        lambda series: {
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
        },
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
