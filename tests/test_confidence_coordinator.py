from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.crewai_models import DecisionModel, MarketSnapshotModel, RiskResult
from src.portfolio import record_sell_fill, reset_portfolio_state
from src.trading_crew import coordinate_tool


def test_confidence_weighted_buy_allowed() -> None:
    reset_portfolio_state()
    snapshot = MarketSnapshotModel(
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
        prices={"PLTK": 20.0},
        cash=1000.0,
        positions={"PLTK": 0},
        avg_entry_prices={"PLTK": 0.0},
    )
    market = DecisionModel(
        action="HOLD", symbol=None, reason="neutral", confidence=0.61
    )
    valuation = DecisionModel(
        action="BUY", symbol="PLTK", reason="undervalued", confidence=0.82
    )
    risk = RiskResult(status="APPROVE", reason="checks passed", confidence=0.70)

    final = coordinate_tool(snapshot, market, valuation, risk)

    assert final.action == "BUY"
    assert final.symbol == "PLTK"
    assert final.confidence >= 0.65


def test_confidence_clamped_by_sell_cooldown() -> None:
    reset_portfolio_state()
    now = datetime.now(tz=timezone.utc)
    record_sell_fill("PLTK", now - timedelta(minutes=30))
    snapshot = MarketSnapshotModel(
        timestamp=now.isoformat(),
        prices={"PLTK": 20.0},
        cash=1000.0,
        positions={"PLTK": 0},
        avg_entry_prices={"PLTK": 0.0},
    )
    market = DecisionModel(
        action="HOLD", symbol=None, reason="neutral", confidence=0.60
    )
    valuation = DecisionModel(
        action="BUY", symbol="PLTK", reason="undervalued", confidence=0.90
    )
    risk = RiskResult(status="APPROVE", reason="checks passed", confidence=0.70)

    final = coordinate_tool(snapshot, market, valuation, risk)

    assert final.action == "HOLD"
    assert "buy confidence too low" in final.reason
