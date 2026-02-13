from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: datetime
    prices: dict[str, float]
    cash: float
    positions: dict[str, int]
    avg_entry_prices: dict[str, float] = field(default_factory=dict)
