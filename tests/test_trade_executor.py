from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.trade_executor import configure_trade_executor, execute_action


class _MockApiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_order(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="order-1", status="accepted")


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": 100.0},
        cash=10000.0,
        positions={"PLTR": 0},
    )


def test_execute_action_dry_run_does_not_submit(monkeypatch) -> None:
    monkeypatch.delenv("EXECUTE", raising=False)
    api = _MockApiClient()
    configure_trade_executor(None)
    action = Decision(action=TradeAction.BUY, symbol="PLTR", qty=1, reason="test")

    execute_action(api, _snapshot(), action)

    assert api.calls == []


def test_execute_action_executes_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTE", "1")
    api = _MockApiClient()
    configure_trade_executor(None)
    action = Decision(action=TradeAction.SELL, symbol="PLTR", qty=2, reason="test")

    execute_action(api, _snapshot(), action)

    assert len(api.calls) == 1
    call = api.calls[0]
    assert call["symbol"] == "PLTR"
    assert call["qty"] == 2
    assert call["side"] == "sell"
