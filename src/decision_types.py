from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Decision:
    action: TradeAction
    symbol: str | None
    qty: int
    reason: str
