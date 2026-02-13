from __future__ import annotations

import threading

import src.agent_trader as agent_trader
from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot


class _DummyBroker:
    def get_cash(self) -> float:
        return 5000.0

    def get_positions(self) -> dict[str, int]:
        return {"PLTR": 1}

    def get_price(self, symbol: str) -> float:
        return {"PLTR": 100.0}[symbol]


def test_agent_loop_builds_snapshot(monkeypatch) -> None:
    captured: list[MarketSnapshot] = []

    def fake_run_agents(snapshot: MarketSnapshot, symbols: list[str], broker):
        _ = symbols
        _ = broker
        captured.append(snapshot)
        return Decision(action=TradeAction.HOLD, symbol=None, qty=0, reason="test")

    monkeypatch.setattr(agent_trader, "_run_agents", fake_run_agents)
    monkeypatch.setattr(agent_trader, "execute_action", lambda *args, **kwargs: None)

    agent_trader.run_trading_loop(
        broker=_DummyBroker(),
        api_client=None,
        symbols=["PLTR"],
        rate_limiter=None,
        stop_event=threading.Event(),
        loop_interval_seconds=0.0,
        max_iterations=1,
    )

    assert len(captured) == 1
    assert captured[0].prices["PLTR"] == 100.0
    assert captured[0].cash == 5000.0
    assert captured[0].positions["PLTR"] == 1


def test_agent_loop_stops_on_keyboard_interrupt(monkeypatch) -> None:
    def raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_trader, "_build_snapshot", raise_interrupt)

    stop_event = threading.Event()
    agent_trader.run_trading_loop(
        broker=_DummyBroker(),
        api_client=None,
        symbols=["PLTR"],
        rate_limiter=None,
        stop_event=stop_event,
        loop_interval_seconds=0.0,
        max_iterations=None,
    )

    assert stop_event.is_set()
