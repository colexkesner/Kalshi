from pathlib import Path

from kalshi_weather_hitbot.data.city_bootstrap import build_city_mapping, dump_city_mapping_yaml


class _Resp:
    def __init__(self, text: str):
        self.text = text
        self.content = text.encode()
        self.url = "https://example.com/terms.html"
        self.headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        return None


class _Session:
    def get(self, _url, timeout=20):
        _ = timeout
        return _Resp("Settlement from weather.gov/wrh/Climate?wfo=MFL Location: Miami International Airport, FL")


def test_bootstrap_writes_expected_city_structure(tmp_path: Path):
    series = [
        {
            "ticker": "KXHIGHTEMP-MIA",
            "title": "Highest temperature Miami",
            "category": "Climate",
            "contract_terms_url": "https://example.com/terms.html",
        }
    ]
    mapping = build_city_mapping(series, downloader=_Session())
    assert "miami" in mapping
    city = mapping["miami"]
    assert "KXHIGHTEMP-MIA" in city["kalshi_series_tickers"]
    assert city["resolution_location_name"]
    assert city["nws_wfo"] == "MFL"
    assert city["icao_station"] == "KMIA"

    out = tmp_path / "cities.yaml"
    out.write_text(dump_city_mapping_yaml(mapping))
    assert out.read_text().strip()
