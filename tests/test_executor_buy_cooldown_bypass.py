from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.trade_executor import execute_action, reset_executor_state


class _ApiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_order(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="order-1", status="accepted")


def _snapshot(price: float) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": price},
        cash=10000.0,
        positions={"PLTR": 0},
    )


def test_buy_cooldown_skips_then_bypasses_on_price_move(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "0")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("PRICE_MOVE_BYPASS_PCT", "1.0")

    now = {"value": 1000.0}
    monkeypatch.setattr("src.trade_executor.time.time", lambda: now["value"])
    action = Decision(action=TradeAction.BUY, symbol="PLTR", qty=1, reason="test")

    execute_action(None, _snapshot(100.0), action)
    now["value"] = 1020.0
    execute_action(None, _snapshot(100.5), action)
    now["value"] = 1030.0
    execute_action(None, _snapshot(102.0), action)

    output = capsys.readouterr().out
    assert output.count("DRY-RUN: would BUY 1 of PLTR") == 2
    assert "SKIP: BUY cooldown active for PLTR (no significant price move)" in output
    assert "BYPASS: cooldown bypassed due to price move for PLTR" in output


def test_sell_is_not_blocked_by_cooldown(monkeypatch) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "1")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("PRICE_MOVE_BYPASS_PCT", "99.0")
    api = _ApiClient()
    action = Decision(action=TradeAction.SELL, symbol="PLTR", qty=1, reason="urgent")

    now = {"value": 2000.0}
    monkeypatch.setattr("src.trade_executor.time.time", lambda: now["value"])
    execute_action(api, _snapshot(100.0), action)
    now["value"] = 2005.0
    execute_action(api, _snapshot(99.0), action)

    assert len(api.calls) == 2
