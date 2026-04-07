"""
exchanges/base.py — Exchange Adapter Abstract Interface

All exchange implementations inherit from ExchangeAdapter.
The grid strategy only depends on this interface, not on any specific SDK.

To integrate a new exchange:
  1. Create a file, e.g. exchanges/my_exchange.py
  2. Subclass ExchangeAdapter and implement all @abstractmethod methods
  3. Pass an instance to GridStrategy via --adapter in main.py or config
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str           # "buy" | "sell"
    price: Decimal
    qty: Decimal
    filled_qty: Decimal
    status: str         # "open" | "filled" | "cancelled"
    fee: Decimal = Decimal(0)


@dataclass
class Ticker:
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal


@dataclass
class PositionInfo:
    """Perpetual futures position. size > 0 = long, size < 0 = short."""
    symbol: str
    size: Decimal           # positive = long, negative = short
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: int = 1
    liq_price: Decimal = field(default_factory=lambda: Decimal(0))


class ExchangeAdapter(ABC):
    """
    Unified exchange adapter interface.
    All methods are async. Implement each method using your exchange's SDK.
    """

    def __init__(self, api_key: str, api_secret: str, extra: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.extra = extra  # e.g. passphrase, account_index, etc.

    # ── Market Data ───────────────────────────────────────────────────

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Return current best bid/ask/last price."""

    # ── Account ───────────────────────────────────────────────────────

    @abstractmethod
    async def get_balance(self, currency: str = "USDT") -> Decimal:
        """Return available balance for the given currency."""

    async def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """
        Return current perpetual position, or None if no position / spot market.
        Override this in your adapter if your exchange supports perpetual futures.
        The liq_price field is used by GridStrategy for liquidation-safe stop-loss.
        """
        return None

    # ── Orders ────────────────────────────────────────────────────────

    @abstractmethod
    async def place_limit_order(
        self, symbol: str, side: str, price: Decimal, qty: Decimal
    ) -> OrderResult:
        """Place a limit order. side = 'buy' | 'sell'."""

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order. Returns True if successful."""

    @abstractmethod
    async def get_order(self, symbol: str, order_id: str) -> OrderResult:
        """Query order status by order_id."""

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> list[OrderResult]:
        """Return all currently open orders for the symbol."""

    async def cancel_all_orders(self, symbol: str) -> int:
        """
        Cancel all open orders for the symbol.
        Default: calls cancel_order() one by one.
        Override with a bulk cancel API if your exchange supports it.
        Returns the number of orders cancelled.
        """
        orders = await self.get_open_orders(symbol)
        count = 0
        for o in orders:
            try:
                await self.cancel_order(symbol, o.order_id)
                count += 1
            except Exception:
                pass
        return count

    async def close(self) -> None:
        """Release underlying HTTP session resources. Override if needed."""
