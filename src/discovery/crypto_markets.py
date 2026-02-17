"""Market discovery utilities for 15m crypto markets."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.gamma_client import GammaClient


def get_current_15m_market_info(coin: str, gamma: Optional[GammaClient] = None) -> Optional[Dict[str, Any]]:
    """Return normalized active 15m market metadata for coin."""
    client = gamma or GammaClient()
    return client.get_market_info(coin)


def list_crypto_15m_markets(coin: str, gamma: Optional[GammaClient] = None) -> List[Dict[str, Any]]:
    """List containing the currently tradable 15m market (if any)."""
    market = get_current_15m_market_info(coin=coin, gamma=gamma)
    return [market] if market else []
