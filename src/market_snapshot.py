from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: datetime
    prices: dict[str, float]
    cash: float
    positions: dict[str, int]
