from __future__ import annotations

from datetime import datetime, timezone

from src.market_snapshot import MarketSnapshot


def test_market_snapshot_dataclass_fields() -> None:
    now = datetime.now(tz=timezone.utc)
    snapshot = MarketSnapshot(
        timestamp=now,
        prices={"PLTR": 100.5},
        cash=1000.0,
        positions={"PLTR": 2},
    )

    assert snapshot.timestamp == now
    assert snapshot.prices["PLTR"] == 100.5
    assert snapshot.cash == 1000.0
    assert snapshot.positions["PLTR"] == 2
