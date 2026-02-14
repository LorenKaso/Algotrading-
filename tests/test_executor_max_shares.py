from __future__ import annotations

from datetime import datetime, timezone

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.trade_executor import execute_action, reset_executor_state


def _snapshot(price: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": price},
        cash=10000.0,
        positions={"PLTR": 0},
    )


def test_max_shares_per_trade_reduces_qty(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "0")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("MAX_POSITION_PERCENT", "100")
    monkeypatch.setenv("MAX_SHARES_PER_TRADE", "3")

    execute_action(
        None,
        _snapshot(),
        Decision(action=TradeAction.BUY, symbol="PLTR", qty=9, reason="test"),
    )

    output = capsys.readouterr().out
    assert (
        "ADJUST: qty reduced from 9 to 3 for PLTR due to max shares per trade" in output
    )
    assert "DRY-RUN: would BUY 3 of PLTR" in output


def test_qty_below_one_is_skipped(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "0")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")

    execute_action(
        None,
        _snapshot(),
        Decision(action=TradeAction.BUY, symbol="PLTR", qty=0, reason="test"),
    )

    assert "Invalid action payload; skipping." in capsys.readouterr().out
