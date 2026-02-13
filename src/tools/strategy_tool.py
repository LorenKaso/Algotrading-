from __future__ import annotations

from src.crewai_models import PositionInsight


def compute_position_insight(position, current_price: float) -> PositionInsight:
    symbol = str(_get_field(position, "symbol", default="")).upper()
    avg_entry_price = float(_get_field(position, "avg_entry_price", default=0.0) or 0.0)
    qty = int(_get_field(position, "qty", default=0) or 0)
    price = float(current_price)

    if qty <= 0 or avg_entry_price <= 0:
        pnl_pct = 0.0
    else:
        pnl_pct = (price - avg_entry_price) / avg_entry_price

    return PositionInsight(
        symbol=symbol,
        avg_entry_price=max(avg_entry_price, 0.0),
        current_price=price,
        pnl_pct=float(pnl_pct),
    )


def _get_field(position, name: str, default):
    if isinstance(position, dict):
        return position.get(name, default)
    return getattr(position, name, default)
