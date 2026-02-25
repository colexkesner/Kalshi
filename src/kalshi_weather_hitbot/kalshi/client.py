from __future__ import annotations

import logging
import time
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.kalshi.auth import KalshiSigner
from kalshi_weather_hitbot.utils.timeutil import now_ms


logger = logging.getLogger(__name__)


class APIError(RuntimeError):
    pass


class TransientAPIError(APIError):
    pass


class PermanentAPIError(APIError):
    pass


class UnauthorizedError(PermanentAPIError):
    pass


class RateLimitError(TransientAPIError):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after_seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


class KalshiClient:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.base_url = cfg.base_url
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": cfg.user_agent})
        self.signer = KalshiSigner(cfg.private_key_path) if cfg.api_key_id and cfg.private_key_path else None

    def _headers(self, method: str, path: str, authenticated: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self.signer or not self.cfg.api_key_id:
                raise APIError("Missing API credentials for authenticated call.")
            ts = now_ms()
            headers.update(
                {
                    "KALSHI-ACCESS-KEY": self.cfg.api_key_id,
                    "KALSHI-ACCESS-TIMESTAMP": ts,
                    "KALSHI-ACCESS-SIGNATURE": self.signer.sign(ts, method, path),
                }
            )
        return headers

    @retry(
        reraise=True,
        retry=retry_if_exception_type((requests.RequestException, TransientAPIError)),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        stop=stop_after_attempt(4),
    )
    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, authenticated: bool = False) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._headers(method, path, authenticated),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise TransientAPIError(f"Network error while calling {path}: {exc}") from exc
        if response.status_code == 401:
            raise UnauthorizedError("Unauthorized (401). Check API key id, private key path, and environment base URL.")
        if response.status_code == 429:
            retry_after_seconds = _parse_retry_after_seconds(getattr(response, "headers", {}).get("Retry-After"))
            if retry_after_seconds is not None:
                time.sleep(min(retry_after_seconds, 30.0))
            raise RateLimitError(
                f"Rate limited (429): {getattr(response, 'text', '')}",
                retry_after_seconds=retry_after_seconds,
            )
        if response.status_code >= 500:
            raise TransientAPIError(f"Transient API error: {response.status_code} {response.text}")
        if response.status_code >= 400:
            raise PermanentAPIError(f"API error {response.status_code}: {response.text}")
        return response.json() if response.text else {}

    def list_series(self, tags: str | None = "Weather", category: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if tags:
            params["tags"] = tags
        if category:
            params["category"] = category
        payload = self._request("GET", "/trade-api/v2/series", params=params or None)
        if not isinstance(payload, dict):
            raise APIError(
                "Malformed /trade-api/v2/series response: expected JSON object, "
                f"got {type(payload).__name__}"
            )
        series = payload.get("series")
        if series is None:
            return []
        if not isinstance(series, list):
            raise APIError(
                "Malformed /trade-api/v2/series response: expected 'series' to be a list or null, "
                f"got {type(series).__name__}"
            )
        return series

    def list_markets(self, series_ticker: str, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request("GET", "/trade-api/v2/markets", params={"series_ticker": series_ticker, "status": status, "limit": limit})
        return payload.get("markets", [])

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._request("GET", f"/trade-api/v2/markets/{ticker}")

    def get_orderbook(self, ticker: str) -> dict[str, Any]:
        return self._request("GET", f"/trade-api/v2/markets/{ticker}/orderbook")

    def get_balance(self) -> dict[str, Any]:
        return self._request("GET", "/trade-api/v2/portfolio/balance", authenticated=True)

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/trade-api/v2/portfolio/orders", json_body=payload, authenticated=True)

    def get_positions(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/trade-api/v2/portfolio/positions", authenticated=True)
        return payload.get("positions", [])

    def list_orders(self, status: str = "open") -> list[dict[str, Any]]:
        payload = self._request("GET", "/trade-api/v2/portfolio/orders", params={"status": status}, authenticated=True)
        return payload.get("orders", [])

    def amend_order(self, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/trade-api/v2/portfolio/orders/{order_id}/amend", json_body=payload, authenticated=True)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/trade-api/v2/portfolio/orders/{order_id}", authenticated=True)
