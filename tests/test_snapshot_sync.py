from __future__ import annotations

from datetime import datetime, timezone

from src.crew_decider import (
    CoordinatorAgent,
    MarketAgent,
    RiskAgent,
    ValuationAgent,
    decide,
)
from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot


def test_same_snapshot_used_across_all_agent_calls(monkeypatch) -> None:
    seen_ids: list[int] = []

    def market_decide(self, snapshot: MarketSnapshot) -> Decision:
        _ = self
        seen_ids.append(id(snapshot))
        return Decision(TradeAction.HOLD, None, 0, "market")

    def valuation_decide(self, snapshot: MarketSnapshot) -> Decision:
        _ = self
        seen_ids.append(id(snapshot))
        return Decision(TradeAction.BUY, "PLTR", 1, "valuation")

    def risk_decide(self, snapshot: MarketSnapshot) -> Decision:
        _ = self
        seen_ids.append(id(snapshot))
        return Decision(TradeAction.HOLD, None, 0, "APPROVE: test")

    def coord_decide(self, snapshot: MarketSnapshot) -> Decision:
        _ = self
        seen_ids.append(id(snapshot))
        return Decision(TradeAction.BUY, "PLTR", 1, "coord")

    monkeypatch.setattr(MarketAgent, "decide", market_decide)
    monkeypatch.setattr(ValuationAgent, "decide", valuation_decide)
    monkeypatch.setattr(RiskAgent, "decide", risk_decide)
    monkeypatch.setattr(CoordinatorAgent, "decide", coord_decide)

    snapshot = MarketSnapshot(
        timestamp=datetime.now(tz=timezone.utc),
        prices={"PLTR": 100.0},
        cash=1000.0,
        positions={"PLTR": 0},
    )
    decide(snapshot=snapshot, symbols=["PLTR"], allowed_symbols={"PLTR"})

    assert len(seen_ids) == 4
    assert set(seen_ids) == {id(snapshot)}
