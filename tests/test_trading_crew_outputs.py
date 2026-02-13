from __future__ import annotations

from datetime import datetime, timezone

from src.crewai_models import DecisionModel, MarketSnapshotModel, RiskResult
from src.trading_crew import build_trading_crew


def test_trading_crew_task_outputs_are_pydantic(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "stub")
    crew = build_trading_crew(symbols=["PLTR"], allowlist={"PLTR"}, market_is_open=True)
    snapshot = MarketSnapshotModel(
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
        prices={"PLTR": 50.0},
        cash=1000.0,
        positions={"PLTR": 0},
    ).model_dump()

    crew.kickoff(inputs={"snapshot": snapshot})

    assert len(crew.tasks) == 4
    for index, task in enumerate(crew.tasks):
        assert task.output is not None
        if index == 2:
            assert isinstance(task.output.pydantic, RiskResult)
        else:
            assert isinstance(task.output.pydantic, DecisionModel)
        assert isinstance(task.output.json_dict, dict)

    final = crew.tasks[-1].output.pydantic
    assert final.action in {"BUY", "SELL", "HOLD"}
