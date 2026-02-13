from __future__ import annotations

import os
import time
from dataclasses import dataclass

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.rate_limiter import RateLimiter

_rate_limiter: RateLimiter | None = None
_last_order_by_symbol_side: dict[tuple[str, TradeAction], tuple[float, float]] = {}


@dataclass(frozen=True)
class ExecutorLimits:
    max_position_percent: float
    max_shares_per_trade: int
    buy_cooldown_seconds: float
    price_move_bypass_pct: float
    enable_open_order_guard: bool


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

    symbol = action.symbol.upper()
    limits = _read_limits()
    qty = action.qty
    side = action.action.value.lower()
    latest_price = float(snapshot.prices.get(symbol, 0.0))

    if limits.enable_open_order_guard and _has_open_order(api_client, symbol=symbol, side=side):
        print(f"[executor] SKIP: open order exists for {symbol} {action.action.value}")
        return

    now = time.time()
    if action.action == TradeAction.BUY:
        if latest_price <= 0:
            print(f"[executor] SKIP: invalid or missing price for {symbol}")
            return
        if _is_buy_in_cooldown(
            symbol=symbol,
            now=now,
            latest_price=latest_price,
            cooldown_seconds=limits.buy_cooldown_seconds,
            bypass_pct=limits.price_move_bypass_pct,
        ):
            return
        qty = _apply_position_cap(snapshot, symbol, latest_price, qty, limits.max_position_percent)
        if qty < 1:
            print("[executor] SKIP: position cap reached")
            return

    if qty > limits.max_shares_per_trade:
        print(
            f"[executor] ADJUST: qty reduced from {qty} to {limits.max_shares_per_trade} "
            f"for {symbol} due to max shares per trade"
        )
        qty = limits.max_shares_per_trade
    if qty < 1:
        print(f"[executor] SKIP: qty below 1 for {symbol}")
        return

    _last_order_by_symbol_side[(symbol, action.action)] = (now, latest_price)

    if os.getenv("EXECUTE", "").strip() != "1":
        print(
            f"[executor] DRY-RUN: would {action.action.value} {qty} "
            f"of {symbol} ({action.reason})"
        )
        return

    if api_client is None:
        print("[executor] ERROR: EXECUTE=1 but Alpaca API client is unavailable.")
        return

    try:
        _wait_for_rate_limit("executor:submit_order")
        order = api_client.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
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


def _read_limits() -> ExecutorLimits:
    max_position_raw = os.getenv("MAX_POSITION_PERCENT", "20").strip()
    max_shares_raw = os.getenv("MAX_SHARES_PER_TRADE", "10").strip()
    cooldown_raw = os.getenv("BUY_COOLDOWN_SECONDS", "60").strip()
    bypass_raw = os.getenv("PRICE_MOVE_BYPASS_PCT", "1.0").strip()
    open_guard_raw = os.getenv("ENABLE_OPEN_ORDER_GUARD", "1").strip()

    try:
        max_position_percent = float(max_position_raw)
    except ValueError:
        max_position_percent = 20.0
    if max_position_percent <= 0:
        max_position_percent = 20.0

    try:
        max_shares_per_trade = int(max_shares_raw)
    except ValueError:
        max_shares_per_trade = 10
    if max_shares_per_trade <= 0:
        max_shares_per_trade = 1

    try:
        buy_cooldown_seconds = float(cooldown_raw)
    except ValueError:
        buy_cooldown_seconds = 60.0
    if buy_cooldown_seconds < 0:
        buy_cooldown_seconds = 0.0

    try:
        price_move_bypass_pct = float(bypass_raw)
    except ValueError:
        price_move_bypass_pct = 1.0
    if price_move_bypass_pct < 0:
        price_move_bypass_pct = 0.0

    return ExecutorLimits(
        max_position_percent=max_position_percent,
        max_shares_per_trade=max_shares_per_trade,
        buy_cooldown_seconds=buy_cooldown_seconds,
        price_move_bypass_pct=price_move_bypass_pct,
        enable_open_order_guard=open_guard_raw == "1",
    )


def _apply_position_cap(
    snapshot: MarketSnapshot,
    symbol: str,
    latest_price: float,
    buy_qty: int,
    max_position_percent: float,
) -> int:
    if latest_price <= 0 or max_position_percent <= 0:
        return 0

    portfolio_value = snapshot.cash + sum(
        qty * snapshot.prices.get(pos_symbol, 0.0)
        for pos_symbol, qty in snapshot.positions.items()
    )
    if portfolio_value <= 0:
        return 0

    current_qty = snapshot.positions.get(symbol, 0)
    current_position_value = current_qty * latest_price
    allowed_value = (max_position_percent / 100.0) * portfolio_value
    remaining_value = allowed_value - current_position_value
    if remaining_value <= 0:
        return 0
    max_qty_by_cap = int(remaining_value // latest_price)
    if max_qty_by_cap <= 0:
        return 0
    if buy_qty > max_qty_by_cap:
        print(
            f"[executor] ADJUST: qty reduced from {buy_qty} to {max_qty_by_cap} "
            f"for {symbol} due to position cap"
        )
    return min(buy_qty, max_qty_by_cap)


def _is_buy_in_cooldown(
    symbol: str,
    now: float,
    latest_price: float,
    cooldown_seconds: float,
    bypass_pct: float,
) -> bool:
    previous = _last_order_by_symbol_side.get((symbol, TradeAction.BUY))
    if previous is None:
        return False
    last_trade_time, last_trade_price = previous
    if (now - last_trade_time) >= cooldown_seconds:
        return False
    if last_trade_price <= 0:
        print(f"[executor] SKIP: BUY cooldown active for {symbol} (no significant price move)")
        return True
    move_pct = abs(latest_price - last_trade_price) / last_trade_price * 100.0
    if move_pct < bypass_pct:
        print(f"[executor] SKIP: BUY cooldown active for {symbol} (no significant price move)")
        return True
    print(f"[executor] BYPASS: cooldown bypassed due to price move for {symbol}")
    return False


def _has_open_order(api_client, symbol: str, side: str) -> bool:
    if api_client is None:
        return False

    if hasattr(api_client, "has_open_order"):
        try:
            return bool(api_client.has_open_order(symbol=symbol, side=side))
        except TypeError:
            return bool(api_client.has_open_order(symbol, side))
        except Exception:
            return False

    if hasattr(api_client, "list_open_orders"):
        try:
            orders = api_client.list_open_orders(symbol=symbol, side=side)
        except TypeError:
            try:
                orders = api_client.list_open_orders(symbol, side)
            except Exception:
                return False
        except Exception:
            return False
        return len(orders) > 0

    if not hasattr(api_client, "list_orders"):
        return False

    try:
        open_orders = api_client.list_orders(status="open")
    except TypeError:
        try:
            open_orders = api_client.list_orders()
        except Exception:
            return False
    except Exception:
        return False

    for order in open_orders:
        order_symbol = str(getattr(order, "symbol", "")).upper()
        order_side = str(getattr(order, "side", "")).lower()
        order_status = str(getattr(order, "status", "")).lower()
        if order_symbol != symbol or order_side != side:
            continue
        if order_status in {"", "open", "new", "accepted", "partially_filled", "pending_new"}:
            return True
    return False


def reset_executor_state() -> None:
    _last_order_by_symbol_side.clear()
