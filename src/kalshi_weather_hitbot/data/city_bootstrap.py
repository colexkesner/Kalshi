from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests
import yaml


AIRPORT_LOCATION_TO_ICAO = {
    "chicago midway": "KMDW",
    "los angeles airport": "KLAX",
    "miami international airport": "KMIA",
    "austin-bergstrom": "KAUS",
    "austin bergstrom": "KAUS",
}

ICAO_COORDS = {
    "KMDW": {"lat": 41.7868, "lon": -87.7522, "tz": "America/Chicago"},
    "KLAX": {"lat": 33.9425, "lon": -118.4081, "tz": "America/Los_Angeles"},
    "KMIA": {"lat": 25.7959, "lon": -80.2871, "tz": "America/New_York"},
    "KAUS": {"lat": 30.1945, "lon": -97.6699, "tz": "America/Chicago"},
}

INCLUDE_PATTERNS = ["highest temperature", "lowest temperature", "snow", "rain"]
EXCLUDE_PATTERNS = ["volcano", "earthquake", "hurricane", "tornado", "wildfire"]


@dataclass
class ContractTermsInfo:
    resolution_location_name: str | None
    resolution_source_type: str
    nws_wfo: str | None
    nws_location_label: str | None


def is_city_climate_series(series: dict[str, Any]) -> bool:
    text = " ".join(
        str(series.get(k, "")) for k in ["title", "subtitle", "description", "name", "ticker", "tags", "category"]
    ).lower()
    if any(p in text for p in EXCLUDE_PATTERNS):
        return False
    return any(p in text for p in INCLUDE_PATTERNS)


def derive_city_key(series_ticker: str, location_name: str | None) -> str:
    suffix = (series_ticker.split("-")[-1] if "-" in series_ticker else series_ticker).lower()
    ticker_map = {
        "chi": "chicago",
        "nyc": "nyc",
        "mia": "miami",
        "aus": "austin",
        "lax": "la",
        "la": "la",
        "sf": "sf",
        "bos": "boston",
        "phx": "phoenix",
    }
    if suffix in ticker_map:
        return ticker_map[suffix]
    if location_name:
        cleaned = re.sub(r"[^a-z0-9]+", "_", location_name.lower()).strip("_")
        return cleaned[:48]
    return suffix


def _decode_terms_content(resp: requests.Response) -> str:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype or resp.url.lower().endswith(".pdf"):
        # Lightweight fallback parser for text-like PDFs; robust parsing can be layered later.
        raw = resp.content.decode("latin-1", errors="ignore")
        return re.sub(r"\s+", " ", raw)
    return resp.text


def parse_contract_terms_text(text: str) -> ContractTermsInfo:
    compact = re.sub(r"\s+", " ", text)
    wfo_match = re.search(r"wrh/Climate\?wfo=([A-Z]{3})", compact, re.IGNORECASE)
    wfo = wfo_match.group(1).upper() if wfo_match else None

    location = None
    loc_match = re.search(r"(?:Location|Station|Observed at|Observation site)\s*[:\-]\s*([^.;\n]+)", compact, re.IGNORECASE)
    if loc_match:
        location = loc_match.group(1).strip()
    if not location:
        # Common phrasing fallback.
        fallback = re.search(r"(Central Park, New York|Chicago Midway, IL|Los Angeles Airport, CA|Miami International Airport, FL)", compact, re.IGNORECASE)
        if fallback:
            location = fallback.group(1)

    nws_label = None
    label_match = re.search(r"Location\s*:\s*([^<\n]+)", compact, re.IGNORECASE)
    if label_match:
        nws_label = label_match.group(1).strip()

    source_type = "nws_climate_daily" if wfo else "metar_nws_combo"
    return ContractTermsInfo(
        resolution_location_name=location,
        resolution_source_type=source_type,
        nws_wfo=wfo,
        nws_location_label=nws_label,
    )


def resolve_icao(location_name: str | None) -> str | None:
    if not location_name:
        return None
    lower = location_name.lower()
    for key, icao in AIRPORT_LOCATION_TO_ICAO.items():
        if key in lower:
            return icao
    return None


def build_city_mapping(series_list: list[dict[str, Any]], downloader: requests.Session | None = None) -> dict[str, Any]:
    session = downloader or requests.Session()
    mapping: dict[str, Any] = {}

    for series in series_list:
        if not is_city_climate_series(series):
            continue
        ticker = str(series.get("ticker") or "")
        if not ticker:
            continue

        terms_url = series.get("contract_terms_url")
        terms_info = ContractTermsInfo(None, "metar_nws_combo", None, None)
        if terms_url:
            try:
                resp = session.get(terms_url, timeout=20)
                resp.raise_for_status()
                terms_info = parse_contract_terms_text(_decode_terms_content(resp))
            except Exception:
                pass

        city_key = derive_city_key(ticker, terms_info.resolution_location_name)
        current = mapping.setdefault(
            city_key,
            {
                "kalshi_series_tickers": [],
                "resolution_location_name": terms_info.resolution_location_name,
                "resolution_source_type": terms_info.resolution_source_type,
                "nws_wfo": terms_info.nws_wfo,
                "nws_location_label": terms_info.nws_location_label,
                "icao_station": None,
                "lat": None,
                "lon": None,
                "tz": None,
            },
        )

        if ticker not in current["kalshi_series_tickers"]:
            current["kalshi_series_tickers"].append(ticker)

        if not current.get("resolution_location_name") and terms_info.resolution_location_name:
            current["resolution_location_name"] = terms_info.resolution_location_name
        if terms_info.nws_wfo:
            current["nws_wfo"] = terms_info.nws_wfo
            current["resolution_source_type"] = "nws_climate_daily"
        if terms_info.nws_location_label:
            current["nws_location_label"] = terms_info.nws_location_label

        icao = resolve_icao(current.get("resolution_location_name"))
        if icao:
            current["icao_station"] = icao
            coords = ICAO_COORDS.get(icao, {})
            current["lat"] = coords.get("lat")
            current["lon"] = coords.get("lon")
            current["tz"] = coords.get("tz")

    return mapping


def dump_city_mapping_yaml(mapping: dict[str, Any]) -> str:
    return yaml.safe_dump(mapping, sort_keys=True)
