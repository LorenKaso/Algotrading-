from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MarketSnapshotModel(BaseModel):
    timestamp: str
    prices: dict[str, float]
    cash: float
    positions: dict[str, int]


class DecisionModel(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = Field(default=None)
    reason: str


class RiskResult(BaseModel):
    status: Literal["APPROVE", "VETO"]
    reason: str
