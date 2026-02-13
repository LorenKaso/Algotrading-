from __future__ import annotations

from datetime import datetime, timezone

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.trade_executor import execute_action, reset_executor_state


def _snapshot(cash: float, qty: int, price: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": price},
        cash=cash,
        positions={"PLTR": qty},
    )


def test_position_cap_reduces_buy_qty(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "0")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("MAX_POSITION_PERCENT", "20")
    monkeypatch.setenv("MAX_SHARES_PER_TRADE", "10")

    execute_action(
        None,
        _snapshot(cash=1000.0, qty=0, price=100.0),
        Decision(action=TradeAction.BUY, symbol="PLTR", qty=5, reason="test"),
    )

    output = capsys.readouterr().out
    assert "ADJUST: qty reduced from 5 to 2 for PLTR due to position cap" in output
    assert "DRY-RUN: would BUY 2 of PLTR" in output


def test_position_cap_skip_when_no_room(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "0")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("MAX_POSITION_PERCENT", "50")
    monkeypatch.setenv("MAX_SHARES_PER_TRADE", "10")

    execute_action(
        None,
        _snapshot(cash=100.0, qty=1, price=100.0),
        Decision(action=TradeAction.BUY, symbol="PLTR", qty=1, reason="test"),
    )

    assert "SKIP: position cap reached" in capsys.readouterr().out
