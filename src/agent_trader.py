from __future__ import annotations

import logging

from src.decision_types import Decision, TradeAction
from src.mock_broker import MockBroker
from src.portfolio import portfolio_value
from src.rate_limiter import RateLimiter
from src.strategy_buffett_lite import decide


def execute_decision(broker: MockBroker, decision: Decision) -> None:
    if decision.action == TradeAction.HOLD:
        return
    if not decision.symbol:
        raise ValueError("symbol is required for BUY/SELL")
    side = "buy" if decision.action == TradeAction.BUY else "sell"
    broker.place_order(decision.symbol, side, decision.qty)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    broker = MockBroker()
    limiter = RateLimiter(per_second=1, per_hour=100, per_day=1000)
    symbols = ["PLTR", "NFLX", "PLTK"]

    start_value = portfolio_value(broker)
    logging.info("Starting portfolio value: %.2f", start_value)

    decision = decide(symbols, broker)
    logging.info(
        "Decision: %s %s x%d (%s)",
        decision.action,
        decision.symbol,
        decision.qty,
        decision.reason,
    )

    if decision.action in {TradeAction.BUY, TradeAction.SELL}:
        if not limiter.allow("trade"):
            logging.info("Trade blocked by rate limiter")
        else:
            execute_decision(broker, decision)

    end_value = portfolio_value(broker)
    logging.info("Ending portfolio value: %.2f", end_value)
    logging.info("Positions: %s", broker.get_positions())


if __name__ == "__main__":
    main()
