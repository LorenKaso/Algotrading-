from __future__ import annotations

from datetime import datetime, timezone

from src.crew_decider import decide
from src.decision_types import TradeAction
from src.market_snapshot import MarketSnapshot


def test_valuation_overrides_market_when_no_veto() -> None:
    snapshot = MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": 50.0},
        cash=1000.0,
        positions={"PLTR": 0},
    )

    result = decide(snapshot=snapshot, symbols=["PLTR"], allowed_symbols={"PLTR"})

    assert result.risk_decision.reason.startswith("APPROVE:")
    assert result.market_decision.action == TradeAction.HOLD
    assert result.valuation_decision.action == TradeAction.BUY
    assert result.final_decision.action == TradeAction.BUY
    assert result.final_decision.symbol == "PLTR"
