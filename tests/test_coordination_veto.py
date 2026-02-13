from __future__ import annotations

from datetime import datetime, timezone

from src.crew_decider import decide
from src.decision_types import TradeAction
from src.market_snapshot import MarketSnapshot


def test_risk_veto_overrides_valuation_buy() -> None:
    snapshot = MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": 50.0},
        cash=10.0,
        positions={"PLTR": 0},
    )

    result = decide(snapshot=snapshot, symbols=["PLTR"], allowed_symbols={"PLTR"})

    assert result.valuation_decision.action == TradeAction.BUY
    assert result.risk_decision.reason.startswith("VETO:")
    assert result.final_decision.action == TradeAction.HOLD
    assert "risk=VETO:" in result.final_decision.reason
