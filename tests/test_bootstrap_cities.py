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

    def json(self):
        return {"properties": {"timeZone": "America/New_York"}}


class _Session:
    def get(self, _url, timeout=20):
        _ = timeout
        if "stations.cache.json.gz" in _url:
            import gzip, json

            payload = [{"icaoId": "KMIA", "name": "Miami International Airport", "city": "Miami", "state": "FL", "lat": 25.7959, "lon": -80.2871}]
            body = gzip.compress(json.dumps(payload).encode())
            r = _Resp("")
            r.content = body
            return r
        if "/points/" in _url:
            return _Resp("{}")
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
    mapping, needs_manual = build_city_mapping(
        series,
        downloader=_Session(),
        station_cache_path=str(tmp_path / "stations.cache.json.gz"),
    )
    assert "miami" in mapping
    city = mapping["miami"]
    assert "KXHIGHTEMP-MIA" in city["kalshi_series_tickers"]
    assert city["resolution_location_name"]
    assert city["nws_wfo"] == "MFL"
    assert city["icao_station"] == "KMIA"
    assert not needs_manual

    out = tmp_path / "cities.yaml"
    out.write_text(dump_city_mapping_yaml(mapping))
    assert out.read_text().strip()
