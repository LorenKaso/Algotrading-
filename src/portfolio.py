from __future__ import annotations

from src.broker import Broker


def portfolio_value(broker: Broker) -> float:
    total = broker.get_cash()
    for symbol, qty in broker.get_positions().items():
        total += broker.get_price(symbol) * qty
    return float(total)
