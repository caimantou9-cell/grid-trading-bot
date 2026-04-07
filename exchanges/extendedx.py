"""
exchanges/extendedx.py — ExtendedX (extended.exchange) Adapter

credentials:
  api_key    = X10 REST API Key (Bearer token)
  api_secret = Stark private key (hex)
  extra      = JSON string with required fields:
               {
                 "stark_public": "0x...",
                 "stark_vault":  12345,
                 "network":      "mainnet"   (or "testnet")
               }

Requires: x10-python-trading-starknet  (pip install x10-python-trading-starknet)
"""
from __future__ import annotations

import json
import logging
import sys
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from typing import Optional

from exchanges.base import ExchangeAdapter, OrderResult, Ticker

logger = logging.getLogger(__name__)


def _ensure_x10_sdk():
    try:
        import x10  # noqa: F401
        return
    except ImportError:
        pass
    for candidate in ("/home/admin/extended-pythonsdk", "/opt/extended-pythonsdk"):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        try:
            import x10  # noqa: F401
            return
        except ImportError:
            continue
    raise ImportError(
        "extended-pythonsdk not found. "
        "Clone it and add its path to PYTHONPATH, or set sdk_path in extra config."
    )


class ExtendedXAdapter(ExchangeAdapter):
    """
    ExtendedX perpetual futures adapter.

    extra JSON fields:
      stark_public  (required) — Stark public key hex
      stark_vault   (required) — Vault ID (integer)
      network       (optional) — "mainnet" (default) or "testnet"
    """

    def __init__(self, api_key: str, api_secret: str, extra: Optional[str] = None):
        super().__init__(api_key, api_secret, extra)
        extra_cfg: dict = {}
        if extra:
            try:
                extra_cfg = json.loads(extra) if isinstance(extra, str) else extra
            except Exception:
                pass

        self._rest_api_key: str = api_key
        self._stark_private: str = api_secret
        self._stark_public: str = extra_cfg.get("stark_public", "")
        self._stark_vault = extra_cfg.get("stark_vault")
        self._network: str = extra_cfg.get("network", "mainnet")
        self._client = None

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.close()
        except Exception as e:
            logger.debug("[ExtendedX] close: %s", e)

    # ── Internal ──────────────────────────────────────────────────────

    def _ensure_client(self):
        if self._client is not None:
            return
        _ensure_x10_sdk()
        from x10.perpetual import configuration as cfg_mod
        from x10.perpetual.trading_client.trading_client import PerpetualTradingClient

        cfg = cfg_mod.MAINNET_CONFIG if self._network == "mainnet" else cfg_mod.TESTNET_CONFIG
        stark_account = None
        if self._rest_api_key and self._stark_private and self._stark_public and self._stark_vault is not None:
            from x10.perpetual.accounts import StarkPerpetualAccount
            stark_account = StarkPerpetualAccount(
                vault=self._stark_vault,
                private_key=self._stark_private,
                public_key=self._stark_public,
                api_key=self._rest_api_key,
            )
        self._client = PerpetualTradingClient(endpoint_config=cfg, stark_account=stark_account)

    async def _round_for_market(self, market_name: str, price: Decimal, qty: Decimal, is_ask: bool):
        try:
            mdict = await self._client.markets_info.get_markets_dict()
            m = mdict.get(market_name)
            if m and getattr(m, "trading_config", None):
                price_rounding = ROUND_FLOOR if is_ask else ROUND_CEILING
                price = m.trading_config.round_price(price, rounding_direction=price_rounding)
                qty = m.trading_config.round_order_size(qty, rounding_direction=ROUND_FLOOR)
        except Exception as e:
            logger.debug("[ExtendedX] rounding failed, using raw values: %s", e)
        return price, qty

    # ── Market Data ───────────────────────────────────────────────────

    async def get_ticker(self, symbol: str) -> Ticker:
        self._ensure_client()
        bid = ask = last = Decimal(0)
        try:
            ob = await self._client.markets_info.get_orderbook_snapshot(market_name=symbol)
            data = ob.data
            if data is not None:
                bid  = Decimal(str(data.bid[0].price)) if data.bid else Decimal(0)
                ask  = Decimal(str(data.ask[0].price)) if data.ask else Decimal(0)
                last = (bid + ask) / 2 if bid and ask else (bid or ask)
        except Exception as e:
            logger.debug("[ExtendedX] orderbook snapshot failed: %s", e)

        if last <= Decimal(0):
            try:
                mdict = await self._client.markets_info.get_markets_dict()
                m = mdict.get(symbol)
                if m and getattr(m, "market_stats", None):
                    s = m.market_stats
                    bid  = Decimal(str(s.bid_price or 0))
                    ask  = Decimal(str(s.ask_price or 0))
                    last = Decimal(str(s.last_price or 0)) or Decimal(str(s.mark_price or 0))
                    if not bid: bid = last
                    if not ask: ask = last
                    logger.info("[ExtendedX] orderbook empty, fallback to market_stats: %s last=%s", symbol, last)
            except Exception as e:
                logger.warning("[ExtendedX] market_stats fallback failed: %s", e)

        if last <= Decimal(0):
            try:
                mdict = await self._client.markets_info.get_markets_dict()
                similar = [k for k in sorted(mdict.keys()) if k.startswith(symbol.split("-")[0])]
                hint = f", available {symbol.split('-')[0]} markets: {similar}" if similar else ""
            except Exception:
                hint = ""
            raise RuntimeError(f"ExtendedX get_ticker: no price data for {symbol}{hint}")

        return Ticker(symbol=symbol, bid=bid, ask=ask, last=last)

    # ── Account ───────────────────────────────────────────────────────

    async def get_balance(self, currency: str = "USDT") -> Decimal:
        self._ensure_client()
        resp = await self._client.account.get_balance()
        bal = resp.data
        if bal is None:
            return Decimal(0)
        available = getattr(bal, "available_balance", None) or getattr(bal, "balance", None) or 0
        return Decimal(str(available))

    async def get_position(self, symbol: str):
        """Return PositionInfo with liq_price from Extended, or None if no position."""
        from exchanges.base import PositionInfo
        self._ensure_client()
        try:
            resp = await self._client.account.get_positions(market_names=[symbol])
            for pos in (resp.data or []):
                if str(getattr(pos, "market", "") or "") != symbol:
                    continue
                status_val = str(getattr(pos, "status", "OPENED") or "OPENED").upper()
                if status_val == "CLOSED":
                    return None
                size_raw = Decimal(str(getattr(pos, "size", 0) or 0))
                side_raw = str(getattr(pos, "side", "LONG") or "LONG").upper()
                size = size_raw if side_raw != "SHORT" else -size_raw
                if size == Decimal(0):
                    return None
                # SDK real field names: open_price (not avg_entry_price), unrealised_pnl (UK spelling)
                entry = Decimal(str(getattr(pos, "open_price", 0) or 0))
                mark  = Decimal(str(getattr(pos, "mark_price", 0) or 0))
                upnl  = Decimal(str(getattr(pos, "unrealised_pnl", 0) or 0))
                liq   = Decimal(str(getattr(pos, "liquidation_price", None) or 0))
                lev   = int(float(getattr(pos, "leverage", 1) or 1))
                return PositionInfo(
                    symbol=symbol, size=size, entry_price=entry,
                    mark_price=mark, unrealized_pnl=upnl,
                    leverage=lev, liq_price=liq,
                )
        except Exception as e:
            logger.debug("[ExtendedX] get_position failed: %s", e)
        return None

    # ── Orders ────────────────────────────────────────────────────────

    async def place_limit_order(self, symbol: str, side: str, price: Decimal, qty: Decimal) -> OrderResult:
        self._ensure_client()
        from x10.perpetual.orders import OrderSide, TimeInForce

        is_ask = side.lower() == "sell"
        price, qty = await self._round_for_market(symbol, price, qty, is_ask)
        if qty <= Decimal(0):
            raise ValueError(f"ExtendedX: qty rounds to 0 for symbol={symbol}")

        placed = await self._client.place_order(
            market_name=symbol,
            amount_of_synthetic=qty,
            price=price,
            side=OrderSide.SELL if is_ask else OrderSide.BUY,
            post_only=True,
            time_in_force=TimeInForce.GTT,
            reduce_only=False,
        )
        logger.debug("[ExtendedX] place_order response: error=%s data=%s", placed.error, placed.data)
        if placed.error is not None:
            raise RuntimeError(f"ExtendedX place_limit_order failed: {placed.error}")

        po  = placed.data
        oid = str(getattr(po, "external_id", None) or getattr(po, "id", None) or "")
        return OrderResult(order_id=oid, symbol=symbol, side=side,
                           price=price, qty=qty, filled_qty=Decimal(0), status="open")

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        self._ensure_client()
        resp = await self._client.orders.cancel_order_by_external_id(order_id)
        if getattr(resp, "error", None):
            logger.error("[ExtendedX] cancel_order failed: %s", resp.error)
            return False
        return True

    async def get_order(self, symbol: str, order_id: str) -> OrderResult:
        self._ensure_client()
        for fetch in (
            lambda: self._client.account.get_open_orders(market_names=[symbol]),
            lambda: self._client.account.get_orders_history(market_names=[symbol], limit=50),
        ):
            resp = await fetch()
            for o in (resp.data or []):
                if str(getattr(o, "external_id", "") or "") == order_id:
                    return self._parse_order(o, symbol)
        raise LookupError(f"ExtendedX order not found: {order_id}")

    async def get_open_orders(self, symbol: str) -> list[OrderResult]:
        self._ensure_client()
        resp = await self._client.account.get_open_orders(market_names=[symbol])
        return [self._parse_order(o, symbol) for o in (resp.data or [])]

    async def cancel_all_orders(self, symbol: str) -> int:
        orders = await self.get_open_orders(symbol)
        if not orders:
            return 0
        import asyncio
        results = await asyncio.gather(
            *[self.cancel_order(symbol, o.order_id) for o in orders],
            return_exceptions=True,
        )
        return sum(1 for r in results if r is True)

    def _parse_order(self, o, symbol: str) -> OrderResult:
        oid      = str(getattr(o, "external_id", "") or getattr(o, "id", "") or "")
        side_raw = str(getattr(o, "side", "BUY") or "BUY").upper()
        side     = "sell" if side_raw == "SELL" else "buy"
        price    = Decimal(str(getattr(o, "price", 0) or 0))
        qty      = Decimal(str(getattr(o, "size", 0) or getattr(o, "amount", 0) or 0))
        filled   = Decimal(str(getattr(o, "filled_size", 0) or getattr(o, "filled_amount", 0) or 0))
        raw_status = str(getattr(o, "status", "OPEN") or "OPEN").upper()
        status = {"OPEN": "open", "PARTIALLY_FILLED": "open",
                  "FILLED": "filled", "CANCELED": "cancelled",
                  "CANCELLED": "cancelled", "EXPIRED": "cancelled"}.get(raw_status, "open")
        return OrderResult(order_id=oid, symbol=symbol, side=side,
                           price=price, qty=qty, filled_qty=filled, status=status)
