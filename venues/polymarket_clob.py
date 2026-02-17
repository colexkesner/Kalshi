"""Polymarket CLOB venue adapter."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.client import ClobClient
from src.config import Config
from src.discovery.crypto_markets import list_crypto_15m_markets
from src.signer import Order, OrderSigner
from venues.base import VenueAdapter, VenueOrderRequest, VenueOrderResult

try:  # optional official client
    from py_clob_client.client import ClobClient as OfficialClobClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    OfficialClobClient = None


class PolymarketClobVenue(VenueAdapter):
    """Execution adapter backed by the Polymarket CLOB."""

    def __init__(self, config: Config, signer: Optional[OrderSigner] = None):
        self.config = config
        self.signer = signer
        self.client = ClobClient(
            host=config.clob.host,
            chain_id=config.clob.chain_id,
            signature_type=config.clob.signature_type,
            funder=config.safe_address,
            builder_creds=config.builder if config.use_gasless else None,
        )
        self._official_client = None
        if OfficialClobClient and signer:
            try:
                self._official_client = OfficialClobClient(
                    host=config.clob.host,
                    key=signer.private_key,
                    chain_id=config.clob.chain_id,
                    signature_type=config.clob.signature_type,
                    funder=config.safe_address,
                )
            except Exception:
                self._official_client = None

    def list_markets(self, coin: str) -> List[Dict[str, Any]]:
        return list_crypto_15m_markets(coin)

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        return self.client.get_order_book(token_id)

    def place_order(self, order: VenueOrderRequest) -> VenueOrderResult:
        if not self.signer:
            return VenueOrderResult(success=False, message="Signer not configured", data={})

        # Prefer official order builder when available.
        if self._official_client is not None:
            try:
                built = self._official_client.create_order({
                    "token_id": order.token_id,
                    "price": order.price,
                    "size": order.size,
                    "side": order.side,
                })
                response = self._official_client.post_order(built, order.order_type)
                return VenueOrderResult(
                    success=response.get("success", False),
                    order_id=response.get("orderId"),
                    status=response.get("status"),
                    message=response.get("errorMsg", ""),
                    data=response,
                )
            except Exception:
                pass

        unsigned = Order(
            token_id=order.token_id,
            price=order.price,
            size=order.size,
            side=order.side,
            maker=self.config.safe_address,
            fee_rate_bps=order.fee_rate_bps,
        )
        signed = self.signer.sign_order(unsigned)
        response = self.client.post_order(signed, order.order_type)
        return VenueOrderResult(
            success=response.get("success", False),
            order_id=response.get("orderId"),
            status=response.get("status"),
            message=response.get("errorMsg", ""),
            data=response,
        )

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.client.cancel_order(order_id)

    def positions(self) -> List[Dict[str, Any]]:
        return self.client.get_positions()

    def balances(self) -> Dict[str, Any]:
        return self.client.get_balance_allowance()

    def fills(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.client.get_trades(limit=limit)
