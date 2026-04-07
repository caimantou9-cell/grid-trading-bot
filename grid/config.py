"""
grid/config.py — Grid Bot Parameter Model

Supports both arithmetic and geometric grid modes.
Either qty_per_grid or total_investment must be provided.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class GridConfig(BaseModel):
    # ── Required ──────────────────────────────────────────────────────
    symbol: str          # Exchange-specific market name, e.g. "BTC-USD", "BTCUSDT"
    lower_price: Decimal # Grid lower bound
    upper_price: Decimal # Grid upper bound
    grid_count: int      # Number of grid intervals (2 ~ 300)

    # ── Sizing: at least one required ─────────────────────────────────
    qty_per_grid: Optional[Decimal] = None      # Order size per grid (in base asset)
    total_investment: Optional[Decimal] = None  # Total capital (in quote asset)
    # When both are given, qty_per_grid takes priority.
    # When only total_investment is given, qty is calculated from current price at startup.

    # ── Optional ──────────────────────────────────────────────────────
    is_arithmetic: bool = True          # True = arithmetic, False = geometric
    stop_loss: Optional[Decimal] = None   # Stop the bot if price drops below this
    take_profit: Optional[Decimal] = None # Stop the bot if price rises above this

    @field_validator("grid_count")
    @classmethod
    def _validate_grid_count(cls, v: int) -> int:
        if not 2 <= v <= 300:
            raise ValueError("grid_count must be between 2 and 300")
        return v

    @field_validator("upper_price")
    @classmethod
    def _validate_prices(cls, v: Decimal, info) -> Decimal:
        lower = info.data.get("lower_price")
        if lower is not None and v <= lower:
            raise ValueError("upper_price must be greater than lower_price")
        return v

    @model_validator(mode="after")
    def _validate_qty_or_investment(self) -> "GridConfig":
        if self.qty_per_grid is None and self.total_investment is None:
            raise ValueError("Provide at least one of: qty_per_grid, total_investment")
        if self.qty_per_grid is not None and self.qty_per_grid <= Decimal(0):
            raise ValueError("qty_per_grid must be > 0")
        if self.total_investment is not None and self.total_investment <= Decimal(0):
            raise ValueError("total_investment must be > 0")
        return self
