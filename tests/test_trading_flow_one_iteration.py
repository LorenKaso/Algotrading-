from __future__ import annotations

from src.trading_flow import TradingFlow


class _DummyBroker:
    def get_cash(self) -> float:
        return 10000.0

    def get_positions(self) -> dict[str, int]:
        return {"PLTR": 0, "NFLX": 0, "PLTK": 0}

    def get_price(self, symbol: str) -> float:
        prices = {"PLTR": 50.0, "NFLX": 250.0, "PLTK": 10.0}
        return prices[symbol]


def test_trading_flow_runs_one_iteration_and_calls_executor(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MODE", "mock")
    monkeypatch.setenv("EXECUTE", "0")
    monkeypatch.setenv("DIAG", "0")
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("LOOP_INTERVAL_SEC", "0")

    calls: list[tuple] = []
    monkeypatch.setattr("src.trading_flow.make_broker", lambda: _DummyBroker())
    monkeypatch.setattr(
        "src.trading_flow.execute_action",
        lambda api_client, snapshot, decision: calls.append((api_client, snapshot, decision)),
    )

    flow = TradingFlow(max_iterations=1, sleep_fn=lambda _seconds: None)
    flow.kickoff()

    assert len(calls) == 1
    _, snapshot, decision = calls[0]
    assert snapshot.prices["PLTR"] == 50.0
    assert decision.action.value in {"BUY", "SELL", "HOLD"}
    assert flow.iteration == 1
