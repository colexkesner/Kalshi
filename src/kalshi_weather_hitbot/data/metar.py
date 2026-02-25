from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from kalshi_weather_hitbot.data.cache import TTLCache


logger = logging.getLogger(__name__)


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
        try:
            data = resp.json()
        except requests.exceptions.JSONDecodeError:
            snippet = (resp.text or "")[:200].strip()
            logger.warning(
                "AviationWeather METAR returned non-JSON for station=%s status=%s content-type=%s snippet=%r",
                station,
                resp.status_code,
                resp.headers.get("Content-Type"),
                snippet,
            )
            data = []
        if not isinstance(data, list):
            logger.warning("AviationWeather METAR returned unexpected payload type for station=%s: %s", station, type(data).__name__)
            data = []
        self.cache.set(key, data)
        return data


def parse_temp_f(record: dict[str, Any]) -> float | None:
    c = record.get("temp")
    if c is None:
        return None
    return (float(c) * 9 / 5) + 32


def _parse_obs_time_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        # Handle ms epoch values if present.
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return None


def max_observed_temp_f(records: list[dict[str, Any]], start_ts: datetime, end_ts: datetime) -> float | None:
    max_temp = None
    for r in records:
        obs_time = r.get("obsTime") or r.get("observationTime")
        if not obs_time:
            continue
        dt = _parse_obs_time_utc(obs_time)
        if dt is None:
            continue
        if dt < start_ts or dt > end_ts:
            continue
        tf = parse_temp_f(r)
        if tf is None:
            continue
        max_temp = tf if max_temp is None else max(max_temp, tf)
    return max_temp
