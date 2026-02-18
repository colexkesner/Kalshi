from __future__ import annotations

import gzip
import json
import logging
import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
import yaml


logger = logging.getLogger(__name__)

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


def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _token_set(text: str) -> set[str]:
    return {t for t in _norm_text(text).split() if t}


def extract_pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    parts = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(parts)


def _decode_terms_content(resp: requests.Response) -> str:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype or resp.url.lower().endswith(".pdf"):
        try:
            return extract_pdf_text(resp.content)
        except Exception:
            raw = resp.content.decode("latin-1", errors="ignore")
            return re.sub(r"\s+", " ", raw)
    return resp.text


def parse_contract_terms_text(text: str) -> ContractTermsInfo:
    compact = re.sub(r"\s+", " ", text)
    wfo_match = re.search(r"wrh/Climate\?wfo=([A-Z]{3})", compact, re.IGNORECASE)
    wfo = wfo_match.group(1).upper() if wfo_match else None

    patterns = [
        r"(?:Location|Station|Observed at|Observation site)\s*[:\-]\s*([^.;\n]+)",
        r"recorded\s+at\s+([^.;\n]+)",
    ]
    location = None
    for pattern in patterns:
        m = re.search(pattern, compact, re.IGNORECASE)
        if m:
            location = m.group(1).strip()
            break

    nws_label = None
    label_match = re.search(r"Location\s*:\s*([^<\n]+)", compact, re.IGNORECASE)
    if label_match:
        nws_label = label_match.group(1).strip()

    source_type = "nws_climate_daily" if wfo else "metar_nws_combo"
    return ContractTermsInfo(location, source_type, wfo, nws_label)


def _load_station_cache(
    session: requests.Session,
    station_cache_url: str,
    station_cache_path: str,
    cache_ttl_seconds: int,
) -> list[dict[str, Any]]:
    cache_file = Path(station_cache_path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    refresh_after = max(cache_ttl_seconds, 86400)
    should_refresh = (not cache_file.exists()) or (time.time() - cache_file.stat().st_mtime > refresh_after)

    if should_refresh:
        resp = session.get(station_cache_url, timeout=30)
        resp.raise_for_status()
        cache_file.write_bytes(resp.content)

    with gzip.open(cache_file, "rb") as fh:
        payload = json.loads(fh.read().decode("utf-8"))

    if isinstance(payload, dict) and "features" in payload:
        out: list[dict[str, Any]] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {}).get("coordinates") or [None, None]
            out.append(
                {
                    "icaoId": props.get("icaoId") or props.get("stationIdentifier"),
                    "name": props.get("name") or "",
                    "city": props.get("city") or "",
                    "state": props.get("state") or "",
                    "lat": geom[1],
                    "lon": geom[0],
                }
            )
        return out

    return payload if isinstance(payload, list) else []


def _resolve_timezone(session: requests.Session, nws_base_url: str, lat: float, lon: float) -> str | None:
    try:
        points_url = f"{nws_base_url.rstrip('/')}/points/{lat},{lon}"
        resp = session.get(points_url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data.get("properties", {}).get("timeZone")
    except Exception:
        return None


def _resolve_station_from_location(location_name: str, station_index: list[dict[str, Any]]) -> dict[str, Any] | None:
    loc_tokens = _token_set(location_name)
    best: tuple[int, dict[str, Any]] | None = None

    for station in station_index:
        name = station.get("name") or ""
        city = station.get("city") or ""
        state = station.get("state") or ""
        icao = station.get("icaoId")
        lat = station.get("lat")
        lon = station.get("lon")
        if not icao or lat is None or lon is None:
            continue

        bag = f"{name} {city} {state}"
        bag_norm = _norm_text(bag)
        score = 0
        if _norm_text(location_name) == bag_norm or _norm_text(location_name) in bag_norm:
            score += 100
        score += len(loc_tokens & _token_set(bag)) * 10

        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, station)

    return best[1] if best else None


def build_city_mapping(
    series_list: list[dict[str, Any]],
    downloader: requests.Session | None = None,
    station_cache_url: str = "https://aviationweather.gov/data/cache/stations.cache.json.gz",
    station_cache_path: str = ".cache/awc/stations.cache.json.gz",
    cache_ttl_seconds: int = 60,
    nws_base_url: str = "https://api.weather.gov",
) -> tuple[dict[str, Any], list[str]]:
    session = downloader or requests.Session()
    mapping: dict[str, Any] = {}
    needs_manual_override: list[str] = []
    station_index = _load_station_cache(session, station_cache_url, station_cache_path, cache_ttl_seconds)

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
            except Exception as exc:
                logger.warning("Failed parsing contract terms for %s: %s", ticker, exc)

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

        resolved = None
        if current.get("resolution_location_name"):
            resolved = _resolve_station_from_location(current["resolution_location_name"], station_index)
        if resolved:
            current["icao_station"] = resolved.get("icaoId")
            current["lat"] = resolved.get("lat")
            current["lon"] = resolved.get("lon")
            current["tz"] = _resolve_timezone(session, nws_base_url, float(current["lat"]), float(current["lon"]))
        else:
            if city_key not in needs_manual_override:
                needs_manual_override.append(city_key)

    return mapping, needs_manual_override


def dump_city_mapping_yaml(mapping: dict[str, Any]) -> str:
    return yaml.safe_dump(mapping, sort_keys=True)
