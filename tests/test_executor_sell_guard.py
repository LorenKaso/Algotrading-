from __future__ import annotations

from datetime import datetime, timezone

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.trade_executor import execute_action, reset_executor_state


class _ApiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "accepted"}


def test_sell_skips_when_no_position(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "1")
    api = _ApiClient()
    snapshot = MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTK": 20.0},
        cash=1000.0,
        positions={"PLTK": 0},
    )
    action = Decision(action=TradeAction.SELL, symbol="PLTK", qty=1, reason="take profit hit")

    execute_action(api, snapshot, action)

    assert api.calls == []
    assert "SKIP: no position available to SELL for PLTK" in capsys.readouterr().out
