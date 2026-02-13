from __future__ import annotations

from src.tools.strategy_tool import compute_position_insight


def test_compute_position_insight_math() -> None:
    insight = compute_position_insight(
        {"symbol": "PLTK", "qty": 2, "avg_entry_price": 10.0},
        current_price=10.5,
    )
    assert insight.symbol == "PLTK"
    assert insight.avg_entry_price == 10.0
    assert insight.current_price == 10.5
    assert insight.pnl_pct == 0.05


def test_compute_position_insight_zero_position_safe() -> None:
    insight = compute_position_insight(
        {"symbol": "PLTK", "qty": 0, "avg_entry_price": 10.0},
        current_price=9.0,
    )
    assert insight.pnl_pct == 0.0
