from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from src.crewai_models import DecisionModel, MarketSnapshotModel, RiskResult
from src.market_snapshot import MarketSnapshot


def run_backtest(
    broker,
    market_data,
    crew,
    symbols: list[str],
    start_date: date,
    days: int,
    step_min: int,
    initial_cash: float,
) -> dict[str, Any]:
    _ = broker
    clean_symbols = [symbol.upper() for symbol in symbols]
    cash = float(initial_cash)
    positions = {symbol: 0 for symbol in clean_symbols}
    avg_entry_prices = {symbol: 0.0 for symbol in clean_symbols}
    buys = 0
    sells = 0
    last_prices = {symbol: 0.0 for symbol in clean_symbols}

    timestamps = _generate_timestamps(start_date, days=max(1, days), step_min=max(1, step_min))
    print(
        "[backtest] Starting simulation start=%s days=%d step_min=%d symbols=%s initial_cash=%.2f"
        % (start_date.isoformat(), days, step_min, clean_symbols, cash)
    )
    for ts in timestamps:
        prices: dict[str, float] = {}
        for symbol in clean_symbols:
            prices[symbol] = float(market_data.get_price_at(symbol, ts))
        last_prices = dict(prices)

        snapshot = MarketSnapshot(
            timestamp=ts,
            prices=prices,
            cash=cash,
            positions=dict(positions),
            avg_entry_prices=dict(avg_entry_prices),
        )
        print(f"[backtest] ts={ts.isoformat()} prices={prices}")

        snapshot_payload = MarketSnapshotModel(
            timestamp=snapshot.timestamp.isoformat(),
            prices=snapshot.prices,
            cash=snapshot.cash,
            positions=snapshot.positions,
            avg_entry_prices=snapshot.avg_entry_prices,
        ).model_dump()
        print(
            "[crew] kickoff inputs=snapshot(ts=%s, prices=%s, cash=%.2f, positions=%s)"
            % (
                snapshot.timestamp.isoformat(),
                snapshot.prices,
                snapshot.cash,
                snapshot.positions,
            )
        )
        crew.kickoff(inputs={"snapshot": snapshot_payload, "symbols": clean_symbols})

        market_out = _decision_from_task(crew, 0, "market output missing")
        valuation_out = _decision_from_task(crew, 1, "valuation output missing")
        risk_out = _risk_from_task(crew, 2, "risk output missing")
        final_out = _decision_from_task(crew, 3, "coord output missing")

        print(f"[agent][market] {market_out.action} {market_out.symbol} ({market_out.reason})")
        print(f"[agent][valuation] {valuation_out.action} {valuation_out.symbol} ({valuation_out.reason})")
        print(f"[agent][risk] {risk_out.status}: {risk_out.reason}")
        print(
            f"[agent][coord] final={final_out.action} {final_out.symbol} "
            f"({final_out.reason}) (risk={risk_out.status}:{risk_out.reason})"
        )
        print(
            f"[crew] completed final_decision={final_out.action} "
            f"{final_out.symbol} ({final_out.reason})"
        )

        action = final_out.action
        symbol = (final_out.symbol or "").upper() if final_out.symbol else None
        if action == "BUY":
            if symbol is None or symbol not in prices:
                print(f"[backtest][executor] SKIP BUY: invalid symbol {symbol}")
            else:
                price = prices[symbol]
                if cash >= price:
                    current_qty = positions[symbol]
                    current_avg = avg_entry_prices.get(symbol, 0.0)
                    cash -= price
                    positions[symbol] = current_qty + 1
                    new_qty = positions[symbol]
                    total_cost = current_avg * current_qty + price
                    avg_entry_prices[symbol] = total_cost / new_qty if new_qty > 0 else 0.0
                    buys += 1
                    print(
                        f"[backtest][executor] FILL BUY {symbol} qty=1 at {price:.2f}; "
                        f"cash={cash:.2f}"
                    )
                else:
                    print(
                        f"[backtest][executor] SKIP BUY {symbol}: insufficient cash "
                        f"(cash={cash:.2f}, price={price:.2f})"
                    )
        elif action == "SELL":
            if symbol is None or symbol not in prices:
                print(f"[backtest][executor] SKIP SELL: invalid symbol {symbol}")
            else:
                price = prices[symbol]
                if positions.get(symbol, 0) >= 1:
                    positions[symbol] -= 1
                    cash += price
                    if positions[symbol] == 0:
                        avg_entry_prices[symbol] = 0.0
                    sells += 1
                    print(
                        f"[backtest][executor] FILL SELL {symbol} qty=1 at {price:.2f}; "
                        f"cash={cash:.2f}"
                    )
                else:
                    print(
                        f"[backtest][executor] SKIP SELL {symbol}: insufficient position "
                        f"(qty={positions.get(symbol, 0)})"
                    )
        else:
            print("[backtest][executor] HOLD")

        portfolio_value = cash + sum(positions[symbol] * prices[symbol] for symbol in clean_symbols)
        print(
            "[backtest] portfolio_value=%.2f cash=%.2f positions=%s"
            % (portfolio_value, cash, positions)
        )

    end_value = cash + sum(positions[symbol] * last_prices.get(symbol, 0.0) for symbol in clean_symbols)
    report = {
        "start_cash": float(initial_cash),
        "end_value": float(end_value),
        "pnl": float(end_value - initial_cash),
        "num_buys": buys,
        "num_sells": sells,
        "final_positions": dict(positions),
        "steps": len(timestamps),
    }
    print("[backtest][summary] start_cash=%.2f" % report["start_cash"])
    print("[backtest][summary] end_value=%.2f" % report["end_value"])
    print("[backtest][summary] pnl=%.2f" % report["pnl"])
    print("[backtest][summary] buys=%d sells=%d" % (report["num_buys"], report["num_sells"]))
    print("[backtest][summary] final_positions=%s" % report["final_positions"])
    print("[backtest][summary] steps=%d" % report["steps"])
    return report


def _decision_from_task(crew, task_index: int, fallback_reason: str) -> DecisionModel:
    tasks = list(getattr(crew, "tasks", []))
    if not tasks:
        return DecisionModel(action="HOLD", symbol=None, reason=fallback_reason)
    output = getattr(tasks[task_index], "output", None)
    if output is None:
        return DecisionModel(action="HOLD", symbol=None, reason=fallback_reason)
    pydantic_out = getattr(output, "pydantic", None)
    if pydantic_out is not None:
        return DecisionModel.model_validate(pydantic_out.model_dump())
    json_out = getattr(output, "json_dict", None)
    if json_out is not None:
        return DecisionModel.model_validate(json_out)
    return DecisionModel(action="HOLD", symbol=None, reason=fallback_reason)


def _risk_from_task(crew, task_index: int, fallback_reason: str) -> RiskResult:
    tasks = list(getattr(crew, "tasks", []))
    if not tasks:
        return RiskResult(status="VETO", reason=fallback_reason)
    output = getattr(tasks[task_index], "output", None)
    if output is None:
        return RiskResult(status="VETO", reason=fallback_reason)
    pydantic_out = getattr(output, "pydantic", None)
    if pydantic_out is not None:
        return RiskResult.model_validate(pydantic_out.model_dump())
    json_out = getattr(output, "json_dict", None)
    if json_out is not None:
        return RiskResult.model_validate(json_out)
    return RiskResult(status="VETO", reason=fallback_reason)


def _generate_timestamps(start_date: date, days: int, step_min: int) -> list[datetime]:
    timestamps: list[datetime] = []
    trading_days = _trading_days(start_date, days)
    for trading_day in trading_days:
        session_start = datetime.combine(trading_day, time(hour=14, minute=30), tzinfo=timezone.utc)
        session_end = datetime.combine(trading_day, time(hour=21, minute=0), tzinfo=timezone.utc)
        current = session_start
        while current <= session_end:
            timestamps.append(current)
            current += timedelta(minutes=step_min)
    return timestamps


def _trading_days(start_date: date, days: int) -> list[date]:
    current = start_date
    output: list[date] = []
    while len(output) < days:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return output
