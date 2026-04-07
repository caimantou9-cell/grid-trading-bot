"""
exchanges/lighter.py — Lighter DEX Adapter

credentials:
  api_key    = account_index      (integer string, e.g. "65")
  api_secret = api_private_key    (hex string, required for trading)
  extra      = JSON string with optional fields:
               {
                 "api_key_index": 0,
                 "base_url": "https://mainnet.zklighter.elliot.ai",
                 "market_map": {"BTC-USDC-PERP": 1, "ETH-USDC-PERP": 0}
               }

Default market IDs (Lighter mainnet, April 2026):
  ETH-USDC-PERP = 0,  BTC-USDC-PERP = 1,  SOL-USDC-PERP = 2
  BNB-USDC-PERP = 3,  DOGE-USDC-PERP = 4, XRP-USDC-PERP = 5
  AVAX-USDC-PERP = 6, LINK-USDC-PERP = 7, ARB-USDC-PERP = 8
  OP-USDC-PERP = 9,   SUI-USDC-PERP = 10

Requires: lighter-sdk  https://github.com/lighter-exchange/lighter-v2-api
  git clone https://github.com/lighter-exchange/lighter-v2-api /opt/lighter-sdk
  export PYTHONPATH=/opt/lighter-sdk:$PYTHONPATH
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from decimal import Decimal
from typing import Dict, Optional

import aiohttp

from exchanges.base import ExchangeAdapter, OrderResult, PositionInfo, Ticker

logger = logging.getLogger(__name__)

_MAINNET = "https://mainnet.zklighter.elliot.ai"

# Default market ID map — override via extra.market_map
_DEFAULT_MARKET_MAP: Dict[str, int] = {
    "ETH-USDC-PERP": 0,
    "BTC-USDC-PERP": 1,
    "SOL-USDC-PERP": 2,
    "BNB-USDC-PERP": 3,
    "DOGE-USDC-PERP": 4,
    "XRP-USDC-PERP": 5,
    "AVAX-USDC-PERP": 6,
    "LINK-USDC-PERP": 7,
    "ARB-USDC-PERP": 8,
    "OP-USDC-PERP": 9,
    "SUI-USDC-PERP": 10,
    # legacy aliases
    "ETH-USDC": 0, "BTC-USDC": 1,
}


def _ensure_lighter_sdk():
    try:
        import lighter  # noqa: F401
        return
    except ImportError:
        pass
    for candidate in ("/home/admin/lighter-sdk", "/opt/lighter-sdk"):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        try:
            import lighter  # noqa: F401
            return
        except ImportError:
            continue
    raise ImportError(
        "lighter-sdk not found. Clone it and add to PYTHONPATH, "
        "or set 'base_url' in extra config."
    )


def _extract_hash(obj) -> Optional[str]:
    for getter in (
        lambda o: getattr(o, "hex", None),
        lambda o: getattr(o, "value", None),
        lambda o: getattr(o, "tx_hash", None),
        lambda o: getattr(o, "hash", None),
    ):
        try:
            v = getter(obj)
            if v:
                m = re.findall(r"[0-9a-fA-F]{64,}", str(v))
                if m:
                    return max(m, key=len)
        except Exception:
            pass
    try:
        m = re.findall(r"[0-9a-fA-F]{64,}", str(obj))
        if m:
            return max(m, key=len)
    except Exception:
        pass
    return None


class LighterAdapter(ExchangeAdapter):
    """
    Lighter DEX perpetual futures adapter.

    extra JSON fields:
      api_key_index  (optional, default 0)
      base_url       (optional, default mainnet)
      market_map     (optional) — override or extend default symbol→market_id map
    """

    def __init__(self, api_key: str, api_secret: str, extra: Optional[str] = None):
        super().__init__(api_key, api_secret, extra)

        extra_cfg: dict = {}
        if extra:
            try:
                extra_cfg = json.loads(extra)
            except Exception:
                pass

        self._account_index: int = int(api_key)
        self._api_private_key: str = api_secret
        self._api_key_index: int = int(extra_cfg.get("api_key_index", 0))
        self._base_url: str = extra_cfg.get("base_url", _MAINNET).rstrip("/")
        user_map: dict = extra_cfg.get("market_map", {})
        self._market_map: Dict[str, int] = {
            **_DEFAULT_MARKET_MAP,
            **{k.upper(): v for k, v in user_map.items()},
        }

        self._api_client = None
        self._signer_client = None
        self._order_api = None
        self._account_api = None
        self._mul_cache: Dict[int, tuple] = {}
        self._oid2idx: Dict[str, int] = {}   # order_id → client_order_index for cancel

    # ── Internal ──────────────────────────────────────────────────────

    def _ensure_clients(self):
        if self._api_client is not None:
            return
        _ensure_lighter_sdk()
        import lighter
        self._api_client = lighter.ApiClient(
            configuration=lighter.Configuration(host=self._base_url)
        )
        self._order_api = lighter.OrderApi(self._api_client)
        self._account_api = lighter.AccountApi(self._api_client)
        if self._api_private_key:
            clean = self._api_private_key.lstrip("0x").replace(" ", "")
            is_valid_hex = len(clean) > 0 and all(c in "0123456789abcdefABCDEF" for c in clean)
            if is_valid_hex:
                self._signer_client = lighter.SignerClient(
                    url=self._base_url,
                    account_index=self._account_index,
                    api_private_keys={self._api_key_index: self._api_private_key},
                )
            else:
                logger.warning("[Lighter] api_secret is not valid hex — read-only mode (no trading)")

    def _market_id(self, symbol: str) -> int:
        mid = self._market_map.get(symbol.upper())
        if mid is None:
            raise ValueError(
                f"Unknown symbol={symbol}. Add it to extra.market_map."
            )
        return mid

    async def _get_multipliers(self, market_id: int) -> tuple:
        """Return (size_multiplier, price_multiplier) from exchange, cached."""
        if market_id in self._mul_cache:
            return self._mul_cache[market_id]
        url = f"{self._base_url}/api/v1/orderBooks"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as sess:
                async with sess.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        for ob in data.get("order_books", []):
                            if ob.get("market_id") == market_id:
                                sm = 10 ** int(ob.get("supported_size_decimals", 4))
                                pm = 10 ** int(ob.get("supported_price_decimals", 1))
                                self._mul_cache[market_id] = (sm, pm)
                                return sm, pm
        except Exception as e:
            logger.warning("[Lighter] failed to get precision: %s, using defaults", e)
        defaults = {0: (10000, 100), 1: (100000, 10)}
        result = defaults.get(market_id, (10000, 100))
        self._mul_cache[market_id] = result
        return result

    def _next_order_index(self) -> int:
        return int(time.time() * 1000) % (2 ** 48 - 1000)

    # ── Market Data ───────────────────────────────────────────────────

    async def get_ticker(self, symbol: str) -> Ticker:
        market_id = self._market_id(symbol)
        url = f"{self._base_url}/api/v1/orderBookOrders"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as sess:
            async with sess.get(url, params={"market_id": market_id, "limit": 1}) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        bid = Decimal(str(bids[0]["price"])) if bids else Decimal(0)
        ask = Decimal(str(asks[0]["price"])) if asks else Decimal(0)
        last = (bid + ask) / 2 if bid and ask else (bid or ask)
        return Ticker(symbol=symbol, bid=bid, ask=ask, last=last)

    # ── Account ───────────────────────────────────────────────────────

    async def get_balance(self, currency: str = "USDC") -> Decimal:
        self._ensure_clients()
        resp = await self._account_api.account(by="index", value=str(self._account_index))
        accounts = getattr(resp, "accounts", None) or []
        if not accounts:
            return Decimal(0)
        return Decimal(str(getattr(accounts[0], "available_balance", 0) or 0))

    async def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """
        Return PositionInfo for the symbol, including liq_price from exchange.
        Returns None when position size is 0 or symbol not found.

        Position data comes from account.positions list:
          - market_id: matches via _market_id(symbol)
          - sign: 1 = long, -1 = short
          - position: size (string)
          - avg_entry_price, liquidation_price, unrealized_pnl (all strings)
        """
        self._ensure_clients()
        try:
            market_id = self._market_id(symbol)
            resp = await self._account_api.account(by="index", value=str(self._account_index))
            accounts = getattr(resp, "accounts", None) or []
            if not accounts:
                return None
            for p in (getattr(accounts[0], "positions", None) or []):
                if int(getattr(p, "market_id", -1)) != market_id:
                    continue
                size = Decimal(str(getattr(p, "position", 0) or 0))
                if size == Decimal(0):
                    return None
                sign = int(getattr(p, "sign", 1) or 1)   # 1=long, -1=short
                size = size if sign >= 0 else -size
                entry = Decimal(str(getattr(p, "avg_entry_price", 0) or 0))
                liq   = Decimal(str(getattr(p, "liquidation_price", 0) or 0))
                upnl  = Decimal(str(getattr(p, "unrealized_pnl", 0) or 0))
                return PositionInfo(
                    symbol=symbol,
                    size=size,
                    entry_price=entry,
                    mark_price=Decimal(0),   # Lighter account API doesn't return mark_price
                    unrealized_pnl=upnl,
                    liq_price=liq,
                )
        except Exception as e:
            logger.debug("[Lighter] get_position failed: %s", e)
        return None

    # ── Orders ────────────────────────────────────────────────────────

    async def place_limit_order(self, symbol: str, side: str, price: Decimal, qty: Decimal) -> OrderResult:
        self._ensure_clients()
        if self._signer_client is None:
            raise RuntimeError("api_secret (api_private_key) not configured — cannot place orders")
        import lighter
        market_id = self._market_id(symbol)
        size_mul, price_mul = await self._get_multipliers(market_id)
        is_ask = side.lower() == "sell"
        base_amount = int(round(float(qty) * size_mul))
        price_int = int(round(float(price) * price_mul))
        client_order_index = self._next_order_index()

        tx, tx_hash, err = await self._signer_client.create_order(
            market_index=market_id,
            client_order_index=client_order_index,
            base_amount=base_amount,
            price=price_int,
            is_ask=is_ask,
            order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
            time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
            reduce_only=False,
            trigger_price=0,
            order_expiry=lighter.SignerClient.DEFAULT_28_DAY_ORDER_EXPIRY,
            api_key_index=self._api_key_index,
        )
        if err is not None:
            raise RuntimeError(f"Lighter place_limit_order failed: {err}")

        order_id = _extract_hash(tx_hash) or _extract_hash(tx) or str(tx_hash or client_order_index)
        self._oid2idx[order_id] = client_order_index
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            price=price, qty=qty, filled_qty=Decimal(0), status="open",
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        self._ensure_clients()
        if self._signer_client is None:
            raise RuntimeError("api_secret not configured — cannot cancel orders")
        market_id = self._market_id(symbol)
        order_index = self._oid2idx.get(order_id)
        if order_index is None:
            logger.warning("[Lighter] cancel_order: order_index not found for order_id=%s", order_id[:20])
            return False
        _, _, err = await self._signer_client.cancel_order(
            market_index=market_id,
            order_index=order_index,
            api_key_index=self._api_key_index,
        )
        if err:
            logger.error("[Lighter] cancel_order failed: %s", err)
            return False
        self._oid2idx.pop(order_id, None)
        return True

    async def get_order(self, symbol: str, order_id: str) -> OrderResult:
        self._ensure_clients()
        market_id = self._market_id(symbol)
        auth_token = None
        if self._signer_client:
            try:
                auth_token, _ = self._signer_client.create_auth_token_with_expiry(
                    api_key_index=self._api_key_index
                )
            except Exception:
                pass
        # Check active orders first
        resp = await self._order_api.account_active_orders(
            account_index=self._account_index,
            market_id=market_id,
            auth=auth_token,
        )
        for o in (getattr(resp, "orders", None) or []):
            if str(getattr(o, "order_id", "") or "") == order_id:
                return self._parse_order(o, symbol)
        # Then check inactive (filled/cancelled)
        resp2 = await self._order_api.account_inactive_orders(
            account_index=self._account_index,
            limit=20,
            market_id=market_id,
        )
        for o in (getattr(resp2, "orders", None) or []):
            if str(getattr(o, "order_id", "") or "") == order_id:
                return self._parse_order(o, symbol)
        raise LookupError(f"Lighter order not found: {order_id}")

    async def get_open_orders(self, symbol: str) -> list[OrderResult]:
        self._ensure_clients()
        market_id = self._market_id(symbol)
        auth_token = None
        if self._signer_client:
            try:
                auth_token, _ = self._signer_client.create_auth_token_with_expiry(
                    api_key_index=self._api_key_index
                )
            except Exception:
                pass
        resp = await self._order_api.account_active_orders(
            account_index=self._account_index,
            market_id=market_id,
            auth=auth_token,
        )
        return [self._parse_order(o, symbol) for o in (getattr(resp, "orders", None) or [])]

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

    async def close(self) -> None:
        if self._api_client:
            try:
                await self._api_client.close()
            except Exception:
                pass
        if self._signer_client:
            try:
                await self._signer_client.close()
            except Exception:
                pass

    # ── Parse ─────────────────────────────────────────────────────────

    def _parse_order(self, o, symbol: str) -> OrderResult:
        order_id = str(getattr(o, "order_id", "") or "")
        is_ask = bool(getattr(o, "is_ask", False))
        price = Decimal(str(getattr(o, "price", 0) or 0))
        initial   = Decimal(str(getattr(o, "initial_base_amount", 0) or 0))
        remaining = Decimal(str(getattr(o, "remaining_base_amount", 0) or 0))
        filled = initial - remaining
        status_map = {
            "open": "open", "partial": "open", "filled": "filled",
            "cancelled": "cancelled", "expired": "cancelled",
        }
        raw_status = str(getattr(o, "status", "open") or "open").lower()
        status = status_map.get(raw_status, "open")
        ci = getattr(o, "client_order_index", None)
        if order_id and ci is not None:
            self._oid2idx[order_id] = int(ci)
        return OrderResult(
            order_id=order_id, symbol=symbol,
            side="sell" if is_ask else "buy",
            price=price, qty=initial, filled_qty=filled, status=status,
        )
