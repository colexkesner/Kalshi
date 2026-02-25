from datetime import datetime, timezone

from kalshi_weather_hitbot.data.metar import MetarClient, max_observed_temp_f


class _Resp:
    status_code = 200
    text = ""
    headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        return None

    def json(self):
        from requests.exceptions import JSONDecodeError

        raise JSONDecodeError("Expecting value", "", 0)


class _Session:
    headers = {}

    def get(self, *args, **kwargs):
        _ = args, kwargs
        return _Resp()


def test_fetch_metar_returns_empty_list_on_non_json_response():
    client = MetarClient("https://aviationweather.gov", "test-agent")
    client.session = _Session()  # type: ignore[assignment]
    out = client.fetch_metar("KMDW")
    assert out == []


def test_max_observed_temp_f_handles_integer_obs_time():
    records = [
        {"obsTime": 1719892800000, "temp": 30},  # ms epoch
        {"obsTime": 1719896400, "temp": 31},  # s epoch
    ]
    start = datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 7, 3, 0, 0, tzinfo=timezone.utc)
    out = max_observed_temp_f(records, start, end)
    assert out is not None
    assert out > 86
