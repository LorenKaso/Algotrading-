
from __future__ import annotations

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.portfolio import portfolio_value

import logging
logger = logging.getLogger(__name__)

FAIR_VALUES: dict[str, float] = {
    "PLTR": 95.0,
    "NFLX": 190.0,
    "PLTK": 18.0,
}


def decide(
    symbols: list[str],
    broker,
    max_position_pct: float = 0.4,
) -> Decision:
    best_symbol = None
    best_score = float("-inf")
    best_price = 0.0

    for symbol in symbols:
        price = broker.get_price(symbol)
        if price <= 0:
            logger.warning(
                "Skipping %s due to non-positive price: %s",
                symbol,
                price,
                )
            continue
        fair = FAIR_VALUES[symbol]
        score = (fair - price) / price
        if score > best_score:
            best_symbol = symbol
            best_score = score
            best_price = price

    if best_symbol is None or best_score <= 0.03:
        return Decision(TradeAction.HOLD, None, 0, "not undervalued enough")

    total = portfolio_value(broker)
    current_qty = broker.get_positions().get(best_symbol, 0)
    current_value = current_qty * best_price
    proposed_value = current_value + best_price
    if total > 0 and proposed_value > max_position_pct * total:
        return Decision(TradeAction.HOLD, None, 0, "risk cap")

    fair = FAIR_VALUES[best_symbol]
    reason = f"score={best_score:.3f}, fair={fair:.2f}, price={best_price:.2f}"
    return Decision(TradeAction.BUY, best_symbol, 1, reason)


def decide_from_snapshot(
    snapshot: MarketSnapshot,
    symbols: list[str],
    max_position_pct: float = 0.4,
) -> Decision:
    best_symbol = None
    best_score = float("-inf")
    best_price = 0.0

    for symbol in symbols:
        if symbol not in snapshot.prices:
            continue
        price = snapshot.prices[symbol]
        if price <= 0:
            logger.warning("Skipping %s due to non-positive price: %s", symbol, price)
            continue
        fair = FAIR_VALUES[symbol]
        score = (fair - price) / price
        if score > best_score:
            best_symbol = symbol
            best_score = score
            best_price = price

    if best_symbol is None or best_score <= 0.03:
        return Decision(TradeAction.HOLD, None, 0, "not undervalued enough")

    total = snapshot.cash + sum(
        snapshot.positions.get(symbol, 0) * snapshot.prices.get(symbol, 0.0)
        for symbol in symbols
    )
    current_qty = snapshot.positions.get(best_symbol, 0)
    current_value = current_qty * best_price
    proposed_value = current_value + best_price
    if total > 0 and proposed_value > max_position_pct * total:
        return Decision(TradeAction.HOLD, None, 0, "risk cap")

    fair = FAIR_VALUES[best_symbol]
    reason = f"score={best_score:.3f}, fair={fair:.2f}, price={best_price:.2f}"
    return Decision(TradeAction.BUY, best_symbol, 1, reason)
