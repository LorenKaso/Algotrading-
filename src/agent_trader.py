from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from src.alpaca_connection import run_diagnostics_or_exit, verify_or_exit
from src.broker_factory import make_broker
from src.crew_decider import decide
from src.decision_types import Decision
from src.market_data import configure_api_client, get_latest_price
from src.market_snapshot import MarketSnapshot
from src.rate_limiter import RateLimiter
from src.trade_executor import configure_trade_executor, execute_action

logger = logging.getLogger(__name__)

PORTFOLIO_SYMBOLS = ["PLTR", "NFLX", "PLTK"]
MAX_POSITION_PCT = 0.4


def _compute_portfolio_value(snapshot: MarketSnapshot) -> float:
    return snapshot.cash + sum(
        snapshot.positions.get(symbol, 0) * snapshot.prices.get(symbol, 0.0)
        for symbol in snapshot.prices
    )


def _wait_for_rate_limit(rate_limiter: RateLimiter | None, key: str) -> None:
    if rate_limiter is None:
        return
    while not rate_limiter.allow(key):
        print(f"[data] Rate limit reached for {key}; sleeping 0.2s")
        time.sleep(0.2)


def _build_snapshot(
    broker,
    symbols: list[str],
    price_fetcher: Callable[[str], float],
    rate_limiter: RateLimiter | None,
) -> MarketSnapshot:
    _wait_for_rate_limit(rate_limiter, "broker:get_cash")
    cash = float(broker.get_cash())
    _wait_for_rate_limit(rate_limiter, "broker:get_positions")
    positions = broker.get_positions()
    prices: dict[str, float] = {}
    for symbol in symbols:
        prices[symbol] = float(price_fetcher(symbol))

    return MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices=prices,
        cash=cash,
        positions=positions,
    )


def _get_market_open_state(broker) -> bool | None:
    checker = getattr(broker, "is_market_open", None)
    if checker is None:
        return None
    try:
        return bool(checker())
    except Exception:
        return None


def _run_agents(snapshot: MarketSnapshot, symbols: list[str], broker) -> Decision:
    coordination = decide(
        snapshot=snapshot,
        symbols=symbols,
        allowed_symbols=set(symbols),
        market_is_open=_get_market_open_state(broker),
    )
    market = coordination.market_decision
    valuation = coordination.valuation_decision
    risk = coordination.risk_decision
    final = coordination.final_decision
    print(f"[agent][market] {market.action.value} {market.symbol} ({market.reason})")
    print(f"[agent][valuation] {valuation.action.value} {valuation.symbol} ({valuation.reason})")
    print(f"[agent][risk] {risk.reason}")
    print(f"[agent][coord] final={final.action.value} {final.symbol} ({final.reason})")
    return final


def run_trading_loop(
    broker,
    api_client,
    symbols: list[str],
    rate_limiter: RateLimiter | None,
    stop_event: threading.Event,
    loop_interval_seconds: float,
    max_iterations: int | None = None,
) -> None:
    iteration = 0
    price_fetcher = get_latest_price if api_client is not None else broker.get_price
    while not stop_event.is_set():
        try:
            iteration += 1
            print(f"[startup] Iteration {iteration} started")
            snapshot = _build_snapshot(
                broker=broker,
                symbols=symbols,
                price_fetcher=price_fetcher,
                rate_limiter=rate_limiter,
            )
            for symbol, price in snapshot.prices.items():
                print(f"[data] {symbol} latest={price}")

            chosen_action = _run_agents(snapshot, symbols, broker)
            execute_action(api_client, snapshot, chosen_action)

            portfolio_value = _compute_portfolio_value(snapshot)
            print(
                "[startup] Portfolio value=%.2f, cash=%.2f, positions=%s"
                % (portfolio_value, snapshot.cash, snapshot.positions)
            )
            if max_iterations is not None and iteration >= max_iterations:
                print("[startup] Max iterations reached; exiting loop.")
                return
            stop_event.wait(loop_interval_seconds)
        except KeyboardInterrupt:
            print("[startup] Keyboard interrupt received inside loop; stopping.")
            stop_event.set()
        except Exception as exc:
            print(f"[error] Loop iteration failed: {exc}")
            stop_event.wait(loop_interval_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_mode = os.getenv("RUN_MODE", "mock").strip().lower() or "mock"
    loop_interval_seconds = float(os.getenv("LOOP_INTERVAL_SECONDS", "5"))
    print(f"[startup] RUN_MODE={run_mode}")
    print("[startup] Creating broker from broker_factory...")
    broker = make_broker()

    rate_limiter = RateLimiter(per_second=3, per_hour=1000, per_day=5000)
    configure_trade_executor(rate_limiter)

    api_client = None
    if run_mode == "alpaca":
        print("[startup] Running Alpaca connection check...")
        api_client = verify_or_exit()
        configure_api_client(api_client, rate_limiter=rate_limiter, cache_ttl_seconds=5.0)
        if os.getenv("DIAG", "").strip() == "1":
            run_diagnostics_or_exit(api_client)
            print("[startup] DIAG=1 complete. Exiting before trading loop.")
            return

    print("[startup] Agent trader started")
    print(f"[startup] EXECUTE={os.getenv('EXECUTE', '') or '0'} (1 means real paper orders enabled)")

    stop_event = threading.Event()

    def _signal_handler(signum: int, _frame) -> None:
        print(f"[startup] Signal {signum} received. Shutting down cleanly...")
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    run_trading_loop(
        broker=broker,
        api_client=api_client,
        symbols=PORTFOLIO_SYMBOLS,
        rate_limiter=rate_limiter,
        stop_event=stop_event,
        loop_interval_seconds=loop_interval_seconds,
    )
    print("[startup] Agent trader stopped.")


if __name__ == "__main__":
    main()
