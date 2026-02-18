from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from kalshi_weather_hitbot.data.cache import TTLCache


class NWSClient:
    def __init__(self, base_url: str, user_agent: str, ttl_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = TTLCache(ttl_seconds)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/geo+json"})

    def _get_json(self, url: str) -> dict[str, Any]:
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self.cache.set(url, data)
        return data

    def hourly_forecast(self, lat: float, lon: float) -> list[dict[str, Any]]:
        points_url = f"{self.base_url}/points/{lat},{lon}"
        points = self._get_json(points_url)
        forecast_url = points["properties"]["forecastHourly"]
        payload = self._get_json(forecast_url)
        return payload.get("properties", {}).get("periods", [])


def max_forecast_temp_f(periods: list[dict[str, Any]], now_utc: datetime, close_ts: datetime) -> float | None:
    max_temp = None
    for p in periods:
        start = datetime.fromisoformat(p["startTime"]).astimezone(timezone.utc)
        if start < now_utc or start > close_ts:
            continue
        temp = p.get("temperature")
        unit = p.get("temperatureUnit", "F")
        if temp is None:
            continue
        tf = float(temp) if unit == "F" else (float(temp) * 9 / 5) + 32
        max_temp = tf if max_temp is None else max(max_temp, tf)
    return max_temp
