from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def report_portfolio_tick(
    timestamp: datetime,
    cash: float,
    positions: dict[str, int],
    avg_entry_prices: dict[str, float],
    prices: dict[str, float],
    csv_path: str = "runs/portfolio_timeseries.csv",
) -> None:
    ts_utc = _to_utc(timestamp)
    equity = cash + sum(
        positions.get(symbol, 0) * prices.get(symbol, 0.0) for symbol in positions
    )
    unrealized = 0.0
    position_rows: list[str] = []
    for symbol, qty in positions.items():
        if qty <= 0:
            continue
        avg_entry = float(avg_entry_prices.get(symbol, 0.0))
        price = float(prices.get(symbol, 0.0))
        upnl = (price - avg_entry) * qty if avg_entry > 0 else 0.0
        unrealized += upnl
        position_rows.append(
            f"{symbol}:qty={qty},avg={avg_entry:.2f},px={price:.2f},upnl={upnl:.2f}"
        )

    positions_text = "; ".join(position_rows) if position_rows else "none"
    print(
        "[portfolio] ts=%s cash=%.2f equity=%.2f unrealized=%.2f positions=%s"
        % (ts_utc.isoformat(), cash, equity, unrealized, positions_text)
    )
    _append_csv(
        path=Path(csv_path),
        row={
            "timestamp": ts_utc.isoformat(),
            "cash": f"{cash:.2f}",
            "equity": f"{equity:.2f}",
            "unrealized_pnl": f"{unrealized:.2f}",
            "positions_json": json.dumps(positions, sort_keys=True),
            "avg_entry_prices_json": json.dumps(avg_entry_prices, sort_keys=True),
            "prices_json": json.dumps(prices, sort_keys=True),
        },
    )


def _append_csv(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)
