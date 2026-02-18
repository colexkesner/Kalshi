from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from kalshi_weather_hitbot.data.cache import TTLCache


class MetarClient:
    def __init__(self, base_url: str, user_agent: str, ttl_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = TTLCache(ttl_seconds)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_metar(self, station: str, hours: int = 24) -> list[dict[str, Any]]:
        key = f"metar:{station}:{hours}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        resp = self.session.get(f"{self.base_url}/api/data/metar", params={"ids": station, "format": "json", "hours": hours}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self.cache.set(key, data)
        return data


def parse_temp_f(record: dict[str, Any]) -> float | None:
    c = record.get("temp")
    if c is None:
        return None
    return (float(c) * 9 / 5) + 32


def max_observed_temp_f(records: list[dict[str, Any]], start_ts: datetime, end_ts: datetime) -> float | None:
    max_temp = None
    for r in records:
        obs_time = r.get("obsTime") or r.get("observationTime")
        if not obs_time:
            continue
        dt = datetime.fromisoformat(obs_time.replace("Z", "+00:00")).astimezone(timezone.utc)
        if dt < start_ts or dt > end_ts:
            continue
        tf = parse_temp_f(r)
        if tf is None:
            continue
        max_temp = tf if max_temp is None else max(max_temp, tf)
    return max_temp
