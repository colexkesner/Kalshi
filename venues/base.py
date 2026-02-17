"""Venue adapter abstraction for execution and account access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VenueOrderRequest:
    """Normalized order request payload."""

    token_id: str
    price: float
    size: float
    side: str
    order_type: str = "GTC"
    fee_rate_bps: int = 0


@dataclass
class VenueOrderResult:
    """Normalized order result payload."""

    success: bool
    order_id: Optional[str] = None
    status: Optional[str] = None
    message: str = ""
    data: Dict[str, Any] | None = None


class VenueAdapter(ABC):
    """Interface implemented by execution venues."""

    @abstractmethod
    def list_markets(self, coin: str) -> List[Dict[str, Any]]:
        """List markets for a coin."""

    @abstractmethod
    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Get orderbook snapshot for a token."""

    @abstractmethod
    def place_order(self, order: VenueOrderRequest) -> VenueOrderResult:
        """Place order on venue."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel one order."""

    @abstractmethod
    def positions(self) -> List[Dict[str, Any]]:
        """Fetch positions."""

    @abstractmethod
    def balances(self) -> Dict[str, Any]:
        """Fetch balances."""

    @abstractmethod
    def fills(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch fills/trades."""
