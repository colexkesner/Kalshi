from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from kalshi_weather_hitbot.data.cache import TTLCache


logger = logging.getLogger(__name__)


class MetarClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        ttl_seconds: int = 60,
        timeout_seconds: int = 15,
        cooldown_seconds: int = 600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = TTLCache(ttl_seconds)
        self.station_cooldown = TTLCache(cooldown_seconds)
        self._negative_ttl_seconds = min(30, max(5, int(ttl_seconds // 2) if ttl_seconds > 1 else 5))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._last_station_status: dict[str, str] = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_metar(self, station: str, hours: int = 24) -> list[dict[str, Any]]:
        key = f"metar:{station}:{hours}"
        cached = self.cache.get(key)
        if cached is not None:
            self._last_station_status.setdefault(station, "ok" if cached else "empty")
            return cached
        try:
            resp = self.session.get(
                f"{self.base_url}/api/data/metar",
                params={"ids": station, "format": "json", "hours": hours},
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 204:
                data: list[dict[str, Any]] = []
                self.cache.set(key, data, ttl_seconds=self._negative_ttl_seconds)
                self._last_station_status[station] = "empty"
                logger.debug("AviationWeather METAR returned 204 (no content) for station=%s", station)
                return data
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("AviationWeather METAR request failed for station=%s error=%s", station, exc)
            data: list[dict[str, Any]] = []
            self.cache.set(key, data, ttl_seconds=self._negative_ttl_seconds)
            self._last_station_status[station] = "error"
            return data
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
        if data:
            self.cache.set(key, data)
            self._last_station_status[station] = "ok"
        else:
            self.cache.set(key, data, ttl_seconds=self._negative_ttl_seconds)
            self._last_station_status[station] = "empty"
        return data

    def fetch_metar_with_fallbacks(self, stations: list[str], hours: int = 24) -> tuple[list[dict[str, Any]], str | None, str]:
        unique_stations: list[str] = []
        for station in stations:
            s = str(station or "").strip()
            if s and s not in unique_stations:
                unique_stations.append(s)
        if not unique_stations:
            return [], None, "empty"

        if len(unique_stations) == 1:
            stations_to_try = unique_stations
        else:
            stations_to_try = [s for s in unique_stations if self.station_cooldown.get(s) is None]

        saw_error = False
        for station in stations_to_try:
            records = self.fetch_metar(station, hours=hours)
            if records:
                return records, station, "ok"
            self.station_cooldown.set(station, True)
            if self._last_station_status.get(station) == "error":
                saw_error = True
        return [], None, "error_all" if saw_error else "empty"


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
