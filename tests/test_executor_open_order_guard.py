from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.trade_executor import execute_action, reset_executor_state


class _ApiWithOpenOrders:
    def __init__(self, open_orders: list[SimpleNamespace]) -> None:
        self.open_orders = open_orders
        self.calls: list[dict] = []

    def list_orders(self, status: str = "open"):
        assert status == "open"
        return self.open_orders

    def submit_order(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="order-1", status="accepted")


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": 100.0},
        cash=10000.0,
        positions={"PLTR": 2},
    )


def test_open_order_guard_skips_duplicate_symbol_side(monkeypatch, capsys) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "1")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "1")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    api = _ApiWithOpenOrders(
        open_orders=[SimpleNamespace(symbol="PLTR", side="buy", status="open")]
    )

    execute_action(
        api,
        _snapshot(),
        Decision(action=TradeAction.BUY, symbol="PLTR", qty=1, reason="test"),
    )

    assert api.calls == []
    assert "SKIP: open order exists for PLTR BUY" in capsys.readouterr().out


def test_open_order_guard_allows_other_side(monkeypatch) -> None:
    reset_executor_state()
    monkeypatch.setenv("EXECUTE", "1")
    monkeypatch.setenv("ENABLE_OPEN_ORDER_GUARD", "1")
    monkeypatch.setenv("BUY_COOLDOWN_SECONDS", "0")
    api = _ApiWithOpenOrders(
        open_orders=[SimpleNamespace(symbol="PLTR", side="buy", status="open")]
    )

    execute_action(
        api,
        _snapshot(),
        Decision(action=TradeAction.SELL, symbol="PLTR", qty=1, reason="test"),
    )

    assert len(api.calls) == 1
    assert api.calls[0]["side"] == "sell"
