from __future__ import annotations

import os
import time

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.rate_limiter import RateLimiter

_rate_limiter: RateLimiter | None = None


def configure_trade_executor(rate_limiter: RateLimiter | None) -> None:
    global _rate_limiter
    _rate_limiter = rate_limiter


def execute_action(api_client, snapshot: MarketSnapshot, action: Decision) -> None:
    if action.action == TradeAction.HOLD:
        print(f"[executor] HOLD at {snapshot.timestamp.isoformat()} ({action.reason})")
        return

    if not action.symbol or action.qty <= 0:
        print("[executor] Invalid action payload; skipping.")
        return

    if os.getenv("EXECUTE", "").strip() != "1":
        print(
            f"[executor] DRY-RUN: would {action.action.value} {action.qty} "
            f"of {action.symbol} ({action.reason})"
        )
        return

    if api_client is None:
        print("[executor] ERROR: EXECUTE=1 but Alpaca API client is unavailable.")
        return

    try:
        _wait_for_rate_limit("executor:submit_order")
        order = api_client.submit_order(
            symbol=action.symbol,
            qty=action.qty,
            side=action.action.value.lower(),
            type="market",
            time_in_force="day",
        )
        order_id = getattr(order, "id", "unknown")
        order_status = getattr(order, "status", "unknown")
        print(f"[executor] ORDER SENT: id={order_id}, status={order_status}")
    except Exception as exc:
        print(f"[executor] ERROR: order submission failed: {exc}")


def _wait_for_rate_limit(key: str) -> None:
    if _rate_limiter is None:
        return
    while not _rate_limiter.allow(key):
        print(f"[executor] Rate limit hit for {key}; sleeping 0.2s")
        time.sleep(0.2)
