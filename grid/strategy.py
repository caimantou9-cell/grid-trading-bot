"""
grid/strategy.py — Neutral Grid Strategy

Supports arithmetic and geometric grids for spot and perpetual markets.

Core logic:
  setup()     — compute price levels, cancel stale orders, place initial grid
  run()       — poll every POLL_INTERVAL seconds, detect fills, place counter-orders
  teardown()  — cancel all tracked orders on stop

Usage:
    adapter = MyExchangeAdapter(api_key, api_secret)
    config  = GridConfig(**params)
    bot     = GridStrategy(adapter, config)
    await   bot.start()   # blocks until stopped
"""
from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from exchanges.base import ExchangeAdapter, OrderResult
from grid.config import GridConfig

logger = logging.getLogger("grid")

POLL_INTERVAL_S  = 10   # seconds between each tick
MAX_CONSEC_ERRORS = 5   # consecutive tick errors before auto-stop


@dataclass
class _GridOrder:
    """In-memory record of a tracked grid order."""
    order_id: str
    level_idx: int    # index into self._levels (0 = lower_price)
    side: str         # "buy" | "sell"
    price: Decimal
    qty: Decimal


class GridStrategy:
    """Neutral grid bot: places buy orders below mid-price, sell orders above."""

    def __init__(self, adapter: ExchangeAdapter, config: GridConfig) -> None:
        self._adapter = adapter
        self.config   = config
        self._orders: dict[str, _GridOrder] = {}   # order_id → _GridOrder
        self._levels: list[Decimal] = []
        self._qty_per_grid: Decimal = Decimal(0)
        self._running = False
        self._stop_requested = False
        self._stop_event = asyncio.Event()
        # Dynamically computed from exchange liquidation price when grid is fully loaded
        self._dynamic_stop_loss: Optional[Decimal] = None
        self._dynamic_take_profit: Optional[Decimal] = None

    # ── Public API ────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the grid bot. Runs until:
          - stop() is called
          - stop_loss or take_profit is triggered
          - MAX_CONSEC_ERRORS consecutive tick failures
        Registers SIGINT/SIGTERM to call stop() gracefully.
        """
        self._stop_requested = False
        self._stop_event.clear()
        self._running = True
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._signal_handler)
            except NotImplementedError:
                pass   # Windows doesn't support add_signal_handler

        try:
            await self._setup()
            await self._run_loop()
        finally:
            await self._teardown()
            self._running = False

    def stop(self) -> None:
        """Request a graceful stop (wakes up the poll sleep immediately)."""
        logger.info("stop requested")
        self._stop_requested = True
        try:
            self._stop_event.set()
        except RuntimeError:
            pass  # event loop already closed

    def _signal_handler(self) -> None:
        logger.info("signal received, stopping...")
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(self.stop)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def _setup(self) -> None:
        cfg = self.config
        logger.info("=== Grid Bot Starting ===")
        logger.info("symbol=%s  grid_count=%d  [%s ~ %s]  mode=%s",
                    cfg.symbol, cfg.grid_count, cfg.lower_price, cfg.upper_price,
                    "arithmetic" if cfg.is_arithmetic else "geometric")

        # 1. Compute price levels
        if cfg.is_arithmetic:
            step = (cfg.upper_price - cfg.lower_price) / cfg.grid_count
            self._levels = [cfg.lower_price + step * i for i in range(cfg.grid_count + 1)]
        else:
            ratio = (cfg.upper_price / cfg.lower_price) ** (Decimal(1) / cfg.grid_count)
            self._levels = [cfg.lower_price * (ratio ** i) for i in range(cfg.grid_count + 1)]

        # 2. Fetch current mid-price
        ticker = await self._adapter.get_ticker(cfg.symbol)
        mid = (ticker.bid + ticker.ask) / 2
        if mid <= Decimal(0):
            mid = ticker.last
        if mid <= Decimal(0):
            raise RuntimeError(f"Cannot determine price for {cfg.symbol}: bid={ticker.bid} ask={ticker.ask} last={ticker.last}")
        logger.info("current mid-price: %s", mid)

        # 3. Calculate qty_per_grid (precision: floor to 8 decimal places by default)
        if cfg.qty_per_grid is not None:
            raw_qty = cfg.qty_per_grid
        else:
            raw_qty = cfg.total_investment / (cfg.grid_count * mid)

        # Floor to 8 decimal places; exchange adapters may apply tighter rounding inside place_limit_order
        step_dec = Decimal("0.00000001")
        self._qty_per_grid = (raw_qty // step_dec) * step_dec
        if self._qty_per_grid <= Decimal(0):
            raise ValueError(
                f"Calculated qty_per_grid={raw_qty:.10f} rounds to 0. "
                f"Increase total_investment or set qty_per_grid explicitly."
            )
        logger.info("qty_per_grid: %s", self._qty_per_grid)

        # 4. Cancel any existing open orders (restart safety)
        try:
            cancelled = await self._adapter.cancel_all_orders(cfg.symbol)
            if cancelled:
                logger.info("cancelled %d stale orders", cancelled)
        except Exception as e:
            logger.warning("cancel_all_orders failed (proceeding anyway): %s", e)

        # 5. Place initial grid
        tasks = []
        for i, price in enumerate(self._levels):
            if price < mid:
                tasks.append(self._place_and_track(i, "buy", price))
            elif price > mid:
                tasks.append(self._place_and_track(i, "sell", price))
            # levels at mid are skipped to avoid immediate fill

        results = await asyncio.gather(*tasks, return_exceptions=True)
        placed = sum(1 for r in results if not isinstance(r, Exception))
        errors  = [r for r in results if isinstance(r, Exception)]
        logger.info("initial grid placed=%d errors=%d", placed, len(errors))
        for err in errors:
            logger.warning("  place error: %s", err)

        logger.info("=== Grid Bot Running ===")

    async def _run_loop(self) -> None:
        consec_errors = 0
        while not self._stop_requested:
            try:
                await self._tick()
                consec_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consec_errors += 1
                logger.error("tick error (%d/%d): %s", consec_errors, MAX_CONSEC_ERRORS, e)
                if consec_errors >= MAX_CONSEC_ERRORS:
                    logger.critical("too many consecutive errors, stopping")
                    break
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass

    async def _teardown(self) -> None:
        # Ignore further SIGTERM/SIGINT during teardown so API calls aren't interrupted
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: None)
            except NotImplementedError:
                pass

        logger.info("teardown: cancelling %d tracked orders...", len(self._orders))
        cfg = self.config
        tasks = [self._adapter.cancel_order(cfg.symbol, oid) for oid in list(self._orders.keys())]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            cancelled = sum(1 for r in results if r is True)
            logger.info("teardown: cancelled %d/%d orders", cancelled, len(tasks))
        self._orders.clear()
        try:
            await self._adapter.close()
        except Exception:
            pass
        logger.info("=== Grid Bot Stopped ===")

    # ── Tick ──────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        """
        Single tick:
          1. Fetch current open orders from exchange
          2. Find locally-tracked orders that disappeared (= filled)
          3. Filled buy → place sell one level up; filled sell → place buy one level down
          4. Check stop_loss / take_profit
        """
        cfg = self.config
        exchange_orders = await self._adapter.get_open_orders(cfg.symbol)
        exchange_ids    = {o.order_id for o in exchange_orders}

        open_count = len(exchange_orders)
        logger.debug("tick: %d open orders on exchange, %d tracked locally", open_count, len(self._orders))

        # Detect fills
        filled: list[_GridOrder] = []
        for oid, gorder in list(self._orders.items()):
            if oid not in exchange_ids:
                try:
                    res = await self._adapter.get_order(cfg.symbol, oid)
                    if res.status == "filled":
                        filled.append(gorder)
                except Exception:
                    # If we can't look it up, assume filled conservatively
                    filled.append(gorder)
                del self._orders[oid]

        # Place counter-orders
        counter_tasks = []
        for gorder in filled:
            logger.info("fill detected: %s @ %s  level=%d", gorder.side, gorder.price, gorder.level_idx)
            if gorder.side == "buy":
                sell_idx = gorder.level_idx + 1
                if sell_idx < len(self._levels):
                    counter_tasks.append(self._place_and_track(sell_idx, "sell", self._levels[sell_idx]))
            else:
                buy_idx = gorder.level_idx - 1
                if buy_idx >= 0:
                    counter_tasks.append(self._place_and_track(buy_idx, "buy", self._levels[buy_idx]))

        if counter_tasks:
            results = await asyncio.gather(*counter_tasks, return_exceptions=True)
            for err in (r for r in results if isinstance(r, Exception)):
                logger.warning("counter order error: %s", err)

        # Check stop / take-profit (with liquidation-safe dynamic values)
        ticker = await self._adapter.get_ticker(cfg.symbol)
        mid = (ticker.bid + ticker.ask) / 2 or ticker.last

        await self._update_liq_safety(mid)

        # Use the more conservative of config vs dynamic (whichever triggers sooner)
        sl_vals = [v for v in (cfg.stop_loss, self._dynamic_stop_loss) if v]
        tp_vals = [v for v in (cfg.take_profit, self._dynamic_take_profit) if v]
        effective_sl = max(sl_vals) if sl_vals else None   # higher = triggers sooner for longs
        effective_tp = min(tp_vals) if tp_vals else None   # lower  = triggers sooner for shorts

        if effective_sl and mid <= effective_sl:
            tag = " [liq-safe]" if effective_sl == self._dynamic_stop_loss else ""
            logger.warning("stop_loss triggered%s: price=%.4f <= sl=%s", tag, mid, effective_sl)
            self.stop()
        if effective_tp and mid >= effective_tp:
            tag = " [liq-safe]" if effective_tp == self._dynamic_take_profit else ""
            logger.info("take_profit triggered%s: price=%.4f >= tp=%s", tag, mid, effective_tp)
            self.stop()

    # ── Liquidation Safety ────────────────────────────────────────────

    async def _update_liq_safety(self, mid: Decimal) -> None:
        """
        When price goes beyond grid boundaries (fully loaded), query the exchange
        liquidation price and set a dynamic stop_loss / take_profit that fires
        BEFORE liquidation, with a 1% safety buffer.

        - Price < lower_price  → fully long  → dynamic_stop_loss  = liq_price * 1.01
        - Price > upper_price  → fully short → dynamic_take_profit = liq_price * 0.99

        Only overrides config values when the dynamic value is more conservative
        (i.e., triggers sooner). Silently skips if get_position() returns None
        (spot markets or exchanges without perpetual positions).
        """
        cfg = self.config
        LIQ_BUFFER = Decimal("0.01")

        if mid < cfg.lower_price:
            # Fully long: further drop risks long liquidation
            try:
                pos = await self._adapter.get_position(cfg.symbol)
            except Exception as e:
                logger.debug("get_position failed: %s", e)
                return
            if pos is None or pos.liq_price <= 0:
                return
            safe_sl = (pos.liq_price * (1 + LIQ_BUFFER)).quantize(Decimal("0.01"))
            if self._dynamic_stop_loss != safe_sl:
                logger.warning(
                    "fully long beyond grid: liq_price=%s → dynamic stop_loss=%s (1%% above liq, config sl=%s)",
                    pos.liq_price, safe_sl, cfg.stop_loss,
                )
                self._dynamic_stop_loss = safe_sl

        elif mid > cfg.upper_price:
            # Fully short: further rise risks short liquidation
            try:
                pos = await self._adapter.get_position(cfg.symbol)
            except Exception as e:
                logger.debug("get_position failed: %s", e)
                return
            if pos is None or pos.liq_price <= 0:
                return
            safe_tp = (pos.liq_price * (1 - LIQ_BUFFER)).quantize(Decimal("0.01"))
            if self._dynamic_take_profit != safe_tp:
                logger.warning(
                    "fully short beyond grid: liq_price=%s → dynamic take_profit=%s (1%% below liq, config tp=%s)",
                    pos.liq_price, safe_tp, cfg.take_profit,
                )
                self._dynamic_take_profit = safe_tp

    # ── Helpers ───────────────────────────────────────────────────────

    async def _place_and_track(self, level_idx: int, side: str, price: Decimal) -> None:
        logger.info("placing %s limit: %s @ %s qty=%s", side, self.config.symbol, price, self._qty_per_grid)
        result = await self._adapter.place_limit_order(
            symbol=self.config.symbol,
            side=side,
            price=price,
            qty=self._qty_per_grid,
        )
        logger.info("order placed: %s @ %s  order_id=%s  status=%s",
                    side, price, result.order_id, result.status)
        self._orders[result.order_id] = _GridOrder(
            order_id=result.order_id,
            level_idx=level_idx,
            side=side,
            price=price,
            qty=self._qty_per_grid,
        )
