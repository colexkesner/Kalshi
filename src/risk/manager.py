"""Central risk checks before order placement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Tuple

from venues.base import VenueOrderRequest


@dataclass
class RiskLimits:
    dry_run: bool = True
    max_daily_notional: float = 1000.0
    max_position_per_market: float = 500.0
    max_open_orders: int = 10
    max_loss_daily: float = 200.0
    halt_on_error_count: int = 5


class RiskManager:
    """Tracks intraday state and blocks unsafe order placement."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self._day = date.today()
        self.daily_notional = 0.0
        self.daily_realized_pnl = 0.0
        self.error_count = 0

    def _rollover_if_needed(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self.daily_notional = 0.0
            self.daily_realized_pnl = 0.0
            self.error_count = 0

    def validate_order(
        self,
        order: VenueOrderRequest,
        open_orders: List[Dict],
        positions: List[Dict],
    ) -> Tuple[bool, str]:
        self._rollover_if_needed()

        if self.error_count >= self.limits.halt_on_error_count:
            return False, "Risk halt: error threshold exceeded"

        notional = order.price * order.size
        if self.daily_notional + notional > self.limits.max_daily_notional:
            return False, "Risk halt: MAX_DAILY_NOTIONAL exceeded"

        if len(open_orders) >= self.limits.max_open_orders:
            return False, "Risk halt: MAX_OPEN_ORDERS exceeded"

        market_exposure = 0.0
        for p in positions:
            if str(p.get("asset_id", p.get("token_id", ""))) == order.token_id:
                market_exposure += float(p.get("size", p.get("amount", 0.0)))

        if market_exposure + order.size > self.limits.max_position_per_market:
            return False, "Risk halt: MAX_POSITION_PER_MARKET exceeded"

        if self.daily_realized_pnl <= -abs(self.limits.max_loss_daily):
            return False, "Risk halt: MAX_LOSS_DAILY exceeded"

        return True, "ok"

    def on_order_attempt(self, order: VenueOrderRequest) -> None:
        self.daily_notional += order.price * order.size

    def on_error(self) -> None:
        self.error_count += 1

    def on_realized_pnl(self, pnl: float) -> None:
        self.daily_realized_pnl += pnl
