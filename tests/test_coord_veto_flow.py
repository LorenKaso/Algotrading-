from __future__ import annotations

from datetime import datetime, timezone

from src.crewai_models import DecisionModel, MarketSnapshotModel
from src.trading_crew import build_trading_crew


def test_coordinator_holds_when_risk_veto_even_if_valuation_buy(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("RISK_FORCE_VETO", "market_closed")
    crew = build_trading_crew(
        symbols=["PLTR"],
        allowlist={"PLTR"},
        market_is_open=True,
        run_mode="mock",
    )
    snapshot = MarketSnapshotModel(
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
        prices={"PLTR": 50.0},
        cash=1000.0,
        positions={"PLTR": 0},
    ).model_dump()

    crew.kickoff(inputs={"snapshot": snapshot})
    valuation = crew.tasks[1].output.pydantic
    final = crew.tasks[3].output.pydantic

    assert isinstance(valuation, DecisionModel)
    assert valuation.action == "BUY"
    assert final.action == "HOLD"
    assert "risk veto:" in final.reason


def test_risk_force_veto_only_honored_in_mock(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("RISK_FORCE_VETO", "market_closed")
    snapshot = MarketSnapshotModel(
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
        prices={"PLTR": 50.0},
        cash=1000.0,
        positions={"PLTR": 0},
    ).model_dump()

    mock_crew = build_trading_crew(
        symbols=["PLTR"],
        allowlist={"PLTR"},
        market_is_open=True,
        run_mode="mock",
    )
    mock_crew.kickoff(inputs={"snapshot": snapshot})
    mock_risk = mock_crew.tasks[2].output.pydantic
    assert mock_risk.status == "VETO"
    assert mock_risk.reason == "market closed"

    alpaca_crew = build_trading_crew(
        symbols=["PLTR"],
        allowlist={"PLTR"},
        market_is_open=True,
        run_mode="alpaca",
    )
    alpaca_crew.kickoff(inputs={"snapshot": snapshot})
    alpaca_risk = alpaca_crew.tasks[2].output.pydantic
    assert alpaca_risk.status == "APPROVE"
    assert alpaca_risk.reason == "checks passed"
