from __future__ import annotations

import src.agent_trader as agent_trader


def test_agent_trader_main_starts_flow(monkeypatch) -> None:
    calls: dict[str, int] = {"kickoff": 0, "stop": 0}

    class _DummyFlow:
        def kickoff(self) -> None:
            calls["kickoff"] += 1

        def stop(self) -> None:
            calls["stop"] += 1

    monkeypatch.setattr(agent_trader, "TradingFlow", _DummyFlow)
    agent_trader.main()

    assert calls["kickoff"] == 1
    assert calls["stop"] == 0


def test_agent_trader_main_stops_flow_on_keyboard_interrupt(monkeypatch) -> None:
    calls: dict[str, int] = {"kickoff": 0, "stop": 0}

    class _DummyFlow:
        def kickoff(self) -> None:
            calls["kickoff"] += 1
            raise KeyboardInterrupt

        def stop(self) -> None:
            calls["stop"] += 1

    monkeypatch.setattr(agent_trader, "TradingFlow", _DummyFlow)
    agent_trader.main()

    assert calls["kickoff"] == 1
    assert calls["stop"] == 1
