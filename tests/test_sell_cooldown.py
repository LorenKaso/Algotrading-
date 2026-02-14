from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.portfolio import record_sell_fill
from src.trade_executor import execute_action, reset_executor_state


class _ApiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "accepted"}


def test_buy_blocked_during_sell_cooldown(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "1")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("SELL_COOLDOWN_MIN", "120")

    now = datetime.now(tz=timezone.utc)
    record_sell_fill("PLTK", now - timedelta(minutes=30))

    snapshot = MarketSnapshot(
        timestamp=now,
        prices={"PLTK": 20.0},
        cash=1000.0,
        positions={"PLTK": 0},
    )
    api = _ApiClient()
    action = Decision(action=TradeAction.BUY, symbol="PLTK", qty=1, reason="re-entry")

    execute_action(api, snapshot, action)

    assert api.calls == []
    assert "COOLDOWN BUY blocked symbol=PLTK" in capsys.readouterr().out


def test_buy_allowed_after_sell_cooldown(monkeypatch) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "1")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "0")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("SELL_COOLDOWN_MIN", "120")

    now = datetime.now(tz=timezone.utc)
    record_sell_fill("PLTK", now - timedelta(minutes=130))

    snapshot = MarketSnapshot(
        timestamp=now,
        prices={"PLTK": 20.0},
        cash=1000.0,
        positions={"PLTK": 0},
    )
    api = _ApiClient()
    action = Decision(action=TradeAction.BUY, symbol="PLTK", qty=1, reason="re-entry")

    execute_action(api, snapshot, action)

    assert len(api.calls) == 1
