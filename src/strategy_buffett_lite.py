from __future__ import annotations

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.portfolio import portfolio_value
from src.strategy_config import get_risk_max_shares

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
    positions = broker.get_positions()
    total = portfolio_value(broker)
    max_shares_per_symbol = get_risk_max_shares()

    for symbol in symbols:
        price = broker.get_price(symbol)
        if not _can_add_share(
            current_qty=positions.get(symbol, 0),
            price=price,
            total_portfolio_value=total,
            max_position_pct=max_position_pct,
            max_shares_per_symbol=max_shares_per_symbol,
        ):
            continue
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

    current_qty = positions.get(best_symbol, 0)
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
    max_shares_per_symbol = get_risk_max_shares()
    total = snapshot.cash + sum(
        snapshot.positions.get(symbol, 0) * snapshot.prices.get(symbol, 0.0)
        for symbol in symbols
    )

    for symbol in symbols:
        if symbol not in snapshot.prices:
            continue
        price = snapshot.prices[symbol]
        if not _can_add_share(
            current_qty=snapshot.positions.get(symbol, 0),
            price=price,
            total_portfolio_value=total,
            max_position_pct=max_position_pct,
            max_shares_per_symbol=max_shares_per_symbol,
        ):
            continue
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

    current_qty = snapshot.positions.get(best_symbol, 0)
    current_value = current_qty * best_price
    proposed_value = current_value + best_price
    if total > 0 and proposed_value > max_position_pct * total:
        return Decision(TradeAction.HOLD, None, 0, "risk cap")

    fair = FAIR_VALUES[best_symbol]
    reason = f"score={best_score:.3f}, fair={fair:.2f}, price={best_price:.2f}"
    return Decision(TradeAction.BUY, best_symbol, 1, reason)


def _can_add_share(
    current_qty: int,
    price: float,
    total_portfolio_value: float,
    max_position_pct: float,
    max_shares_per_symbol: int,
) -> bool:
    if current_qty >= max_shares_per_symbol:
        return False
    if price <= 0:
        return False
    if total_portfolio_value <= 0:
        return True
    current_value = current_qty * price
    proposed_value = current_value + price
    return proposed_value <= max_position_pct * total_portfolio_value
