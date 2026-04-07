"""
tests/test_stop_logic.py — Unit tests for stop-loss / take-profit / liquidation-safe logic.

Run:
    cd /home/admin/grid-github
    python -m pytest tests/test_stop_logic.py -v

No real exchange connection needed — all exchange calls are mocked.
"""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from exchanges.base import ExchangeAdapter, OrderResult, PositionInfo, Ticker
from grid.config import GridConfig
from grid.strategy import GridStrategy


# ── Mock Adapter ──────────────────────────────────────────────────────────────

class MockAdapter(ExchangeAdapter):
    """Minimal mock adapter for unit tests. Override attributes per test."""

    def __init__(self):
        super().__init__("key", "secret")
        self.ticker_price = Decimal("65000")   # current mid-price
        self.position: PositionInfo | None = None
        self.open_orders: list[OrderResult] = []

    async def get_ticker(self, symbol: str) -> Ticker:
        p = self.ticker_price
        return Ticker(symbol=symbol, bid=p - 1, ask=p + 1, last=p)

    async def get_balance(self, currency: str = "USDT") -> Decimal:
        return Decimal("10000")

    async def get_position(self, symbol: str):
        return self.position

    async def place_limit_order(self, symbol, side, price, qty) -> OrderResult:
        oid = f"mock-{side}-{price}"
        r = OrderResult(order_id=oid, symbol=symbol, side=side,
                        price=price, qty=qty, filled_qty=Decimal(0), status="open")
        self.open_orders.append(r)
        return r

    async def cancel_order(self, symbol, order_id) -> bool:
        self.open_orders = [o for o in self.open_orders if o.order_id != order_id]
        return True

    async def get_order(self, symbol, order_id) -> OrderResult:
        for o in self.open_orders:
            if o.order_id == order_id:
                return o
        raise KeyError(f"order {order_id} not found")

    async def get_open_orders(self, symbol) -> list[OrderResult]:
        return list(self.open_orders)


def make_strategy(
    lower: str = "60000",
    upper: str = "70000",
    grid_count: int = 5,
    stop_loss: str | None = None,
    take_profit: str | None = None,
    adapter: MockAdapter | None = None,
) -> tuple[GridStrategy, MockAdapter]:
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal(lower),
        upper_price=Decimal(upper),
        grid_count=grid_count,
        total_investment=Decimal("5000"),
        stop_loss=Decimal(stop_loss) if stop_loss else None,
        take_profit=Decimal(take_profit) if take_profit else None,
    )
    adp = adapter or MockAdapter()
    bot = GridStrategy(adp, cfg)
    return bot, adp


# ── Test: Static Stop-Loss ────────────────────────────────────────────────────

def test_stop_loss_triggers_below_price():
    """
    Static stop_loss: when mid-price drops to or below stop_loss, bot stops.
    """
    bot, adp = make_strategy(stop_loss="62000")
    adp.ticker_price = Decimal("61999")   # below stop_loss

    async def run():
        # Manually call _tick logic: set up minimal internal state
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        # _tick checks stop conditions
        await bot._tick()

    asyncio.run(run())
    assert bot._stop_requested, "Bot should have requested stop when price < stop_loss"


def test_stop_loss_does_not_trigger_above_price():
    """
    Static stop_loss: no stop when mid-price is above stop_loss.
    """
    bot, adp = make_strategy(stop_loss="60000")
    adp.ticker_price = Decimal("65000")   # well above stop_loss

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._tick()

    asyncio.run(run())
    assert not bot._stop_requested, "Bot should NOT stop when price > stop_loss"


def test_take_profit_triggers_above_price():
    """
    Static take_profit: when mid-price rises to or above take_profit, bot stops.
    """
    bot, adp = make_strategy(take_profit="68000")
    adp.ticker_price = Decimal("68001")   # above take_profit

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._tick()

    asyncio.run(run())
    assert bot._stop_requested, "Bot should have requested stop when price > take_profit"


# ── Test: Dynamic Liquidation-Safe Stop ──────────────────────────────────────

def test_dynamic_stop_set_when_fully_long():
    """
    When price drops below lower_price (fully long) and exchange returns
    liq_price=58000, dynamic_stop_loss should be set to 58000 * 1.01 = 58580.
    """
    bot, adp = make_strategy()
    adp.ticker_price = Decimal("59000")   # below lower_price=60000
    adp.position = PositionInfo(
        symbol="BTC-USD",
        size=Decimal("0.05"),
        entry_price=Decimal("63000"),
        mark_price=Decimal("59000"),
        unrealized_pnl=Decimal("-200"),
        liq_price=Decimal("58000"),   # 交易所返回的清算价
    )

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._update_liq_safety(Decimal("59000"))

    asyncio.run(run())
    expected = Decimal("58580.00")   # 58000 * 1.01
    assert bot._dynamic_stop_loss == expected, (
        f"Expected dynamic_stop_loss={expected}, got {bot._dynamic_stop_loss}"
    )


def test_dynamic_stop_triggers_before_liquidation():
    """
    End-to-end: price is below lower_price AND below dynamic_stop_loss
    → bot should stop (saved from liquidation at 58000).
    """
    bot, adp = make_strategy()
    adp.ticker_price = Decimal("58100")   # below both lower_price and liq_price+1%
    adp.position = PositionInfo(
        symbol="BTC-USD",
        size=Decimal("0.05"),
        entry_price=Decimal("63000"),
        mark_price=Decimal("58100"),
        unrealized_pnl=Decimal("-245"),
        liq_price=Decimal("58000"),
    )

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._tick()

    asyncio.run(run())
    # dynamic_stop_loss = 58000 * 1.01 = 58580, current price 58100 < 58580 → stop
    assert bot._stop_requested, "Bot should stop when price < dynamic_stop_loss (before liquidation)"


def test_dynamic_take_profit_set_when_fully_short():
    """
    When price rises above upper_price (fully short), dynamic_take_profit
    should be set to liq_price * 0.99.
    """
    bot, adp = make_strategy()
    adp.ticker_price = Decimal("71000")   # above upper_price=70000
    adp.position = PositionInfo(
        symbol="BTC-USD",
        size=Decimal("-0.05"),   # short
        entry_price=Decimal("67000"),
        mark_price=Decimal("71000"),
        unrealized_pnl=Decimal("-200"),
        liq_price=Decimal("72000"),   # short liq_price is above entry
    )

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._update_liq_safety(Decimal("71000"))

    asyncio.run(run())
    expected = Decimal("71280.00")   # 72000 * 0.99
    assert bot._dynamic_take_profit == expected, (
        f"Expected dynamic_take_profit={expected}, got {bot._dynamic_take_profit}"
    )


def test_dynamic_more_conservative_than_config():
    """
    Config stop_loss=59000, dynamic_stop_loss=58580 (liq=58000 * 1.01).
    Effective stop should be max(59000, 58580) = 59000 (config is more conservative here).
    Bot should stop at 58900 (below config 59000), not wait until 58580.
    """
    bot, adp = make_strategy(stop_loss="59000")
    adp.ticker_price = Decimal("58900")   # below config stop_loss=59000
    adp.position = PositionInfo(
        symbol="BTC-USD",
        size=Decimal("0.05"),
        entry_price=Decimal("62000"),
        mark_price=Decimal("58900"),
        unrealized_pnl=Decimal("-155"),
        liq_price=Decimal("58000"),
    )

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._tick()

    asyncio.run(run())
    # Config stop_loss=59000 > dynamic=58580 → effective=59000 → triggers at 58900
    assert bot._stop_requested


def test_no_position_no_dynamic_stop():
    """
    If get_position() returns None (spot or no open position),
    dynamic_stop_loss should remain None and bot should not stop.
    """
    bot, adp = make_strategy()
    adp.ticker_price = Decimal("59000")   # below lower_price
    adp.position = None  # no position

    async def run():
        bot._levels = [Decimal("60000") + Decimal("2000") * i for i in range(6)]
        bot._qty_per_grid = Decimal("0.001")
        await bot._update_liq_safety(Decimal("59000"))

    asyncio.run(run())
    assert bot._dynamic_stop_loss is None
    assert not bot._stop_requested


# ── How to run a quick LIVE stop_loss test ───────────────────────────────────
#
# Set stop_loss just above current market price in config.test.json:
#   "stop_loss": "<current_price + 100>"
# then start the bot:
#   PYTHONPATH=... python3 main.py --config config.test.json
# On the first tick, you should see:
#   stop_loss triggered: price=... <= sl=...
#   teardown: cancelling N tracked orders...
#
# To test the dynamic liq-safe stop:
#   Set lower_price well above current market price (e.g., current_price + 5000)
#   so the bot immediately detects "fully long beyond grid" on first tick.
#   If you have a real long position open, liq_price will be returned and
#   dynamic_stop_loss will be logged.
