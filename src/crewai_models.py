from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MarketSnapshotModel(BaseModel):
    timestamp: str
    prices: dict[str, float]
    cash: float
    positions: dict[str, int]
    avg_entry_prices: dict[str, float] = Field(default_factory=dict)


class DecisionModel(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = Field(default=None)
    reason: str


class RiskResult(BaseModel):
    status: Literal["APPROVE", "VETO"]
    reason: str


class PositionInsight(BaseModel):
    symbol: str
    avg_entry_price: float
    current_price: float
    pnl_pct: float
