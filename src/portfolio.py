from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.broker import Broker


@dataclass
class PortfolioState:
    last_sell_ts: dict[str, datetime] = field(default_factory=dict)


_portfolio_state = PortfolioState()


def portfolio_value(broker: Broker) -> float:
    total = broker.get_cash()
    for symbol, qty in broker.get_positions().items():
        total += broker.get_price(symbol) * qty
    return float(total)


def get_portfolio_state() -> PortfolioState:
    return _portfolio_state


def record_sell_fill(symbol: str, fill_ts: datetime) -> None:
    _portfolio_state.last_sell_ts[symbol.upper()] = _to_utc(fill_ts)


def get_last_sell_ts(symbol: str) -> datetime | None:
    return _portfolio_state.last_sell_ts.get(symbol.upper())


def reset_portfolio_state() -> None:
    _portfolio_state.last_sell_ts.clear()


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)
