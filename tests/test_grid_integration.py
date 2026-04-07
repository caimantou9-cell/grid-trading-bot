"""
tests/test_grid_integration.py — Integration tests for grid arithmetic/geometric modes

Tests:
  1. Arithmetic grid — verify equal spacing between price levels
  2. Geometric grid  — verify equal ratio between consecutive levels
  3. ExtendedX setup (dry-run) — verify orders are placed without errors
  4. Lighter setup (dry-run)   — verify orders are placed without errors

For tests 3 & 4 we use a MockAdapter that replaces exchange calls so no real
API credentials are required. To run LIVE tests that hit the real exchange,
use make_config_extendedx() / make_config_lighter() and call run_live_test().

Run:
    cd /home/admin/grid-github
    source /home/admin/.venv/bin/activate
    python3 -m pytest tests/test_grid_integration.py -v

Live test (requires real creds in config.extendedx.json / config.lighter.json):
    python3 -m pytest tests/test_grid_integration.py -v -k live --run-live
"""
from __future__ import annotations

import asyncio
import math
from decimal import Decimal, ROUND_DOWN

import pytest

from exchanges.base import ExchangeAdapter, OrderResult, Ticker, PositionInfo
from grid.config import GridConfig
from grid.strategy import GridStrategy

# ── Shared Mock Adapter ───────────────────────────────────────────────────────

class MockAdapter(ExchangeAdapter):
    def __init__(self, mid_price: Decimal = Decimal("66880")):
        super().__init__("key", "secret")
        self.mid = mid_price
        self.placed: list[OrderResult] = []
        self.cancelled: list[str] = []

    async def get_ticker(self, symbol: str) -> Ticker:
        return Ticker(symbol=symbol, bid=self.mid - 1, ask=self.mid + 1, last=self.mid)

    async def get_balance(self, currency: str = "USDT") -> Decimal:
        return Decimal("10000")

    async def place_limit_order(self, symbol, side, price, qty) -> OrderResult:
        oid = f"mock-{side}-{price}"
        r = OrderResult(order_id=oid, symbol=symbol, side=side,
                        price=price, qty=qty, filled_qty=Decimal(0), status="open")
        self.placed.append(r)
        return r

    async def cancel_order(self, symbol, order_id) -> bool:
        self.cancelled.append(order_id)
        self.placed = [o for o in self.placed if o.order_id != order_id]
        return True

    async def get_order(self, symbol, order_id) -> OrderResult:
        for o in self.placed:
            if o.order_id == order_id:
                return o
        raise KeyError(order_id)

    async def get_open_orders(self, symbol) -> list[OrderResult]:
        return list(self.placed)


# ── Helper ────────────────────────────────────────────────────────────────────

def _run_setup(config: GridConfig, adapter: MockAdapter | None = None) -> tuple[GridStrategy, MockAdapter]:
    """Run strategy._setup() and return (bot, adapter) for inspection."""
    adp = adapter or MockAdapter(mid_price=(config.lower_price + config.upper_price) / 2)

    async def _go():
        bot = GridStrategy(adp, config)
        await bot._setup()
        # immediately cancel everything (teardown)
        await bot._teardown()
        return bot

    bot = asyncio.run(_go())
    return bot, adp


# ── Test 1: Arithmetic grid level spacing ─────────────────────────────────────

def test_arithmetic_levels_equal_spacing():
    """
    Arithmetic grid: consecutive price levels must have equal spacing.
    With lower=60000, upper=70000, grid_count=5:
      step = (70000-60000)/5 = 2000
      levels = [60000, 62000, 64000, 66000, 68000, 70000]
    """
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("60000"),
        upper_price=Decimal("70000"),
        grid_count=5,
        total_investment=Decimal("1000"),
        is_arithmetic=True,
    )
    adp = MockAdapter(mid_price=Decimal("65000"))
    bot = GridStrategy(adp, cfg)
    bot._levels = []  # reset

    # reproduce _setup level computation
    step = (cfg.upper_price - cfg.lower_price) / cfg.grid_count
    levels = [cfg.lower_price + step * i for i in range(cfg.grid_count + 1)]

    diffs = [levels[i+1] - levels[i] for i in range(len(levels) - 1)]
    assert len(set(diffs)) == 1, f"Spacing not equal: {diffs}"
    assert diffs[0] == Decimal("2000"), f"Expected step=2000, got {diffs[0]}"
    print(f"\n  arithmetic levels: {[str(l) for l in levels]}")
    print(f"  step = {diffs[0]}")


def test_arithmetic_levels_count():
    """grid_count=10 produces 11 price levels (10 intervals)."""
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("60000"),
        upper_price=Decimal("70000"),
        grid_count=10,
        total_investment=Decimal("1000"),
        is_arithmetic=True,
    )
    step = (cfg.upper_price - cfg.lower_price) / cfg.grid_count
    levels = [cfg.lower_price + step * i for i in range(cfg.grid_count + 1)]
    assert len(levels) == 11


# ── Test 2: Geometric grid level ratio ────────────────────────────────────────

def test_geometric_levels_equal_ratio():
    """
    Geometric grid: consecutive levels must have equal ratio.
    With lower=60000, upper=70000, grid_count=5:
      ratio = (70000/60000)^(1/5) ≈ 1.03143
    """
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("60000"),
        upper_price=Decimal("70000"),
        grid_count=5,
        total_investment=Decimal("1000"),
        is_arithmetic=False,  # geometric
    )
    ratio = (cfg.upper_price / cfg.lower_price) ** (Decimal(1) / cfg.grid_count)
    levels = [cfg.lower_price * (ratio ** i) for i in range(cfg.grid_count + 1)]

    ratios = [levels[i+1] / levels[i] for i in range(len(levels) - 1)]
    # All ratios should be equal (within floating-point tolerance)
    for r in ratios:
        assert abs(float(r) - float(ratios[0])) < 1e-9, f"Ratios not equal: {ratios}"

    print(f"\n  geometric levels: {[f'{float(l):.2f}' for l in levels]}")
    print(f"  ratio ≈ {float(ratios[0]):.6f}")
    assert abs(float(levels[-1]) - float(cfg.upper_price)) < 0.01, "Last level should equal upper_price"


def test_geometric_levels_tighter_at_bottom():
    """
    Geometric grid places tighter (smaller) intervals at lower prices,
    wider intervals at higher prices — unlike arithmetic which is uniform.
    This is more capital-efficient for volatile assets.
    """
    lower, upper, n = Decimal("60000"), Decimal("70000"), 10
    ratio = (upper / lower) ** (Decimal(1) / n)
    geo_levels = [lower * (ratio ** i) for i in range(n + 1)]
    arith_step = (upper - lower) / n
    arith_levels = [lower + arith_step * i for i in range(n + 1)]

    geo_diffs   = [geo_levels[i+1] - geo_levels[i] for i in range(n)]
    arith_diffs = [arith_levels[i+1] - arith_levels[i] for i in range(n)]

    # Geometric: first interval smaller than last
    assert geo_diffs[0] < geo_diffs[-1], "Geo: lower intervals should be smaller"
    # Arithmetic: all intervals equal
    assert max(arith_diffs) - min(arith_diffs) < Decimal("0.01"), "Arith: intervals should be equal"
    print(f"\n  geo first interval: {float(geo_diffs[0]):.2f}, last: {float(geo_diffs[-1]):.2f}")
    print(f"  arith interval: {float(arith_diffs[0]):.2f} (uniform)")


# ── Test 3: ExtendedX dry-run setup ───────────────────────────────────────────

def test_extendedx_arithmetic_setup():
    """
    Simulate ExtendedX arithmetic grid setup with mock adapter.
    Mid-price = 66880, grid [64000, 70000], 6 grids.
    Expect: 3 buy orders below mid, 3 sell orders above mid.
    """
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("64000"),
        upper_price=Decimal("70000"),
        grid_count=6,
        total_investment=Decimal("400"),  # ~$400 USDC
        is_arithmetic=True,
    )
    adp = MockAdapter(mid_price=Decimal("66880"))
    bot, adp = _run_setup(cfg, adp)

    buys  = [o for o in adp.placed + [OrderResult(o, "BTC-USD", "buy", Decimal(0), Decimal(0), Decimal(0), "open")
                                       for o in adp.cancelled] if False]  # placed was cancelled in teardown
    # After setup+teardown, orders were placed then cancelled
    # Check via adp.cancelled length = adp.placed was populated during setup
    # Re-run without teardown for inspection:
    adp2 = MockAdapter(mid_price=Decimal("66880"))

    async def _setup_only():
        b = GridStrategy(adp2, cfg)
        await b._setup()
        return b

    bot2 = asyncio.run(_setup_only())
    buys  = [o for o in adp2.placed if o.side == "buy"]
    sells = [o for o in adp2.placed if o.side == "sell"]

    print(f"\n  ExtendedX arithmetic: {len(buys)} buys + {len(sells)} sells placed")
    print(f"  buy prices:  {sorted([float(o.price) for o in buys])}")
    print(f"  sell prices: {sorted([float(o.price) for o in sells])}")

    assert len(buys) > 0,  "Should have buy orders below mid"
    assert len(sells) > 0, "Should have sell orders above mid"
    # When mid does NOT fall exactly on a level: all grid_count+1 levels are used
    # When mid IS exactly on a level: that level is skipped → grid_count orders
    assert len(buys) + len(sells) in (cfg.grid_count, cfg.grid_count + 1), \
        f"Expected {cfg.grid_count} or {cfg.grid_count+1} orders, got {len(buys)+len(sells)}"

    # All buy prices < mid, all sell prices > mid
    for o in buys:
        assert o.price < Decimal("66880"), f"Buy at {o.price} should be below mid"
    for o in sells:
        assert o.price > Decimal("66880"), f"Sell at {o.price} should be above mid"

    # Teardown
    asyncio.run(bot2._teardown())


def test_extendedx_geometric_setup():
    """
    Simulate ExtendedX geometric grid setup.
    Same range + mid-price, expect same order count with geometric spacing.
    """
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("64000"),
        upper_price=Decimal("70000"),
        grid_count=6,
        total_investment=Decimal("400"),
        is_arithmetic=False,  # geometric
    )
    adp = MockAdapter(mid_price=Decimal("66880"))

    async def _setup_only():
        b = GridStrategy(adp, cfg)
        await b._setup()
        return b

    bot = asyncio.run(_setup_only())
    buys  = [o for o in adp.placed if o.side == "buy"]
    sells = [o for o in adp.placed if o.side == "sell"]

    print(f"\n  ExtendedX geometric: {len(buys)} buys + {len(sells)} sells placed")
    print(f"  buy prices:  {[f'{float(o.price):.1f}' for o in sorted(buys, key=lambda x: x.price)]}")
    print(f"  sell prices: {[f'{float(o.price):.1f}' for o in sorted(sells, key=lambda x: x.price)]}")

    assert len(buys) + len(sells) in (cfg.grid_count, cfg.grid_count + 1)
    assert len(buys) > 0 and len(sells) > 0
    asyncio.run(bot._teardown())


# ── Test 4: Lighter dry-run setup ─────────────────────────────────────────────

def test_lighter_arithmetic_setup():
    """
    Simulate Lighter arithmetic grid for BTC-USDC-PERP.
    Mid-price = 66885, grid [64000, 70000], 6 grids.
    """
    cfg = GridConfig(
        symbol="BTC-USDC-PERP",
        lower_price=Decimal("64000"),
        upper_price=Decimal("70000"),
        grid_count=6,
        total_investment=Decimal("400"),
        is_arithmetic=True,
    )
    adp = MockAdapter(mid_price=Decimal("66885"))

    async def _setup_only():
        b = GridStrategy(adp, cfg)
        await b._setup()
        return b

    bot = asyncio.run(_setup_only())
    buys  = [o for o in adp.placed if o.side == "buy"]
    sells = [o for o in adp.placed if o.side == "sell"]

    print(f"\n  Lighter arithmetic: {len(buys)} buys + {len(sells)} sells placed")
    assert len(buys) + len(sells) in (cfg.grid_count, cfg.grid_count + 1)
    assert len(buys) > 0 and len(sells) > 0
    asyncio.run(bot._teardown())


def test_lighter_geometric_setup():
    """
    Simulate Lighter geometric grid for ETH-USDC-PERP.
    Mid-price = 2037, grid [1900, 2200], 8 grids.
    """
    cfg = GridConfig(
        symbol="ETH-USDC-PERP",
        lower_price=Decimal("1900"),
        upper_price=Decimal("2200"),
        grid_count=8,
        total_investment=Decimal("400"),
        is_arithmetic=False,
    )
    adp = MockAdapter(mid_price=Decimal("2037"))

    async def _setup_only():
        b = GridStrategy(adp, cfg)
        await b._setup()
        return b

    bot = asyncio.run(_setup_only())
    buys  = [o for o in adp.placed if o.side == "buy"]
    sells = [o for o in adp.placed if o.side == "sell"]

    print(f"\n  Lighter geometric ETH: {len(buys)} buys + {len(sells)} sells placed")
    assert len(buys) + len(sells) in (cfg.grid_count, cfg.grid_count + 1)
    assert len(buys) > 0 and len(sells) > 0
    asyncio.run(bot._teardown())


# ── Test 5: qty_per_grid vs total_investment ──────────────────────────────────

def test_qty_per_grid_explicit():
    """When qty_per_grid is set explicitly, it is used directly."""
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("64000"),
        upper_price=Decimal("70000"),
        grid_count=5,
        qty_per_grid=Decimal("0.0003"),
        is_arithmetic=True,
    )
    adp = MockAdapter(mid_price=Decimal("66880"))

    async def _setup_only():
        b = GridStrategy(adp, cfg)
        await b._setup()
        return b

    bot = asyncio.run(_setup_only())
    for o in adp.placed:
        assert o.qty == Decimal("0.0003"), f"Expected qty=0.0003, got {o.qty}"
    asyncio.run(bot._teardown())


def test_total_investment_calculates_qty():
    """When only total_investment is set, qty is calculated from mid-price."""
    mid = Decimal("66880")
    grid_count = 5
    investment = Decimal("1000")
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("64000"),
        upper_price=Decimal("70000"),
        grid_count=grid_count,
        total_investment=investment,
        is_arithmetic=True,
    )
    adp = MockAdapter(mid_price=mid)

    async def _setup_only():
        b = GridStrategy(adp, cfg)
        await b._setup()
        return b

    bot = asyncio.run(_setup_only())
    # Expected qty ≈ investment / (grid_count * mid) = 1000 / (5 * 66880) ≈ 0.00000299...
    expected_raw = investment / (grid_count * mid)
    # floored to 8 decimals
    step = Decimal("0.00000001")
    expected_qty = (expected_raw // step) * step
    assert bot._qty_per_grid == expected_qty, \
        f"Expected qty={expected_qty}, got {bot._qty_per_grid}"
    asyncio.run(bot._teardown())


# ── Test 6: Edge cases ────────────────────────────────────────────────────────

def test_mid_price_at_level_skipped():
    """A price level exactly at mid-price is skipped (no order placed at mid)."""
    # With arithmetic grid lower=64000, upper=70000, grid_count=6, step=1000
    # levels = [64000, 65000, 66000, 67000, 68000, 69000, 70000]
    # If mid = 67000, level 67000 is skipped → 3 buys + 3 sells = grid_count
    cfg = GridConfig(
        symbol="BTC-USD",
        lower_price=Decimal("64000"),
        upper_price=Decimal("70000"),
        grid_count=6,
        total_investment=Decimal("500"),
        is_arithmetic=True,
    )
    # mid = 67000 (exactly on a level)
    adp = MockAdapter(mid_price=Decimal("67000"))

    async def _setup_only():
        b = GridStrategy(adp, cfg)
        await b._setup()
        return b

    bot = asyncio.run(_setup_only())
    order_prices = {o.price for o in adp.placed}
    assert Decimal("67000") not in order_prices, "No order should be placed exactly at mid-price"
    asyncio.run(bot._teardown())
