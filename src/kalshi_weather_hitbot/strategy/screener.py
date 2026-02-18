from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass
class ParsedMarket:
    bracket_low: float | None
    bracket_high: float | None
    close_ts: datetime


BRACKET_PATTERNS = [
    re.compile(r"(?P<low>-?\d+)\s*(to|-)\s*(?P<high>-?\d+)\s*°?F", re.IGNORECASE),
    re.compile(r"between\s*(?P<low>-?\d+)\s*and\s*(?P<high>-?\d+)", re.IGNORECASE),
]
LOW_ONLY_PATTERNS = [
    re.compile(r"(?P<threshold>-?\d+)\s*°?\s*or\s*above", re.IGNORECASE),
    re.compile(r"greater\s+than\s+(?P<threshold>-?\d+)", re.IGNORECASE),
]
HIGH_ONLY_PATTERNS = [
    re.compile(r"(?P<threshold>-?\d+)\s*°?\s*or\s*below", re.IGNORECASE),
    re.compile(r"less\s+than\s+(?P<threshold>-?\d+)", re.IGNORECASE),
]


def _parse_strike(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_temperature_market(market: dict) -> ParsedMarket | None:
    text = " ".join(
        str(market.get(k, ""))
        for k in ["title", "subtitle", "yes_sub_title", "no_sub_title", "rules_primary", "rules"]
    )

    low = _parse_strike(market.get("floor_strike"))
    high = _parse_strike(market.get("cap_strike"))

    if low is None or high is None:
        for pat in BRACKET_PATTERNS:
            m = pat.search(text)
            if m:
                low, high = float(m.group("low")), float(m.group("high"))
                break

    if low is None and high is None:
        for pat in HIGH_ONLY_PATTERNS:
            m = pat.search(text)
            if m:
                high = float(m.group("threshold"))
                break

    if low is None and high is None:
        for pat in LOW_ONLY_PATTERNS:
            m = pat.search(text)
            if m:
                low = float(m.group("threshold"))
                break

    close_time = market.get("close_time") or market.get("close_ts")
    if not close_time:
        return None
    close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    if low is None and high is None:
        return None
    return ParsedMarket(bracket_low=low, bracket_high=high, close_ts=close_dt)


def _is_dst(ts_local: datetime) -> bool:
    return bool(ts_local.dst() and ts_local.dst() != timedelta(0))


def climate_window_start(close_ts: datetime, city_tz: str) -> datetime:
    tz = ZoneInfo(city_tz)
    close_local = close_ts.astimezone(tz)

    if _is_dst(close_local):
        observation_day = (close_local - timedelta(hours=1)).date()
        start_local = datetime.combine(observation_day, time(hour=1, minute=0), tzinfo=tz)
    else:
        observation_day = close_local.date()
        start_local = datetime.combine(observation_day, time(hour=0, minute=0), tzinfo=tz)

    return start_local.astimezone(timezone.utc)
