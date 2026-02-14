from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from src.crewai_models import (
    DecisionModel,
    MarketSnapshotModel,
    PositionInsight,
    RiskResult,
)
from src.portfolio import get_last_sell_ts
from src.strategy_config import (
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    get_risk_max_shares,
    get_sell_cooldown_min,
)
from src.strategy_buffett_lite import FAIR_VALUES
from src.tools import FairValueTool
from src.tools.strategy_tool import compute_position_insight

try:
    from crewai import Agent, Crew, Task

    _CREWAI_AVAILABLE = True
except Exception:  # pragma: no cover - exercised in environments without crewai
    _CREWAI_AVAILABLE = False

    class Agent:  # type: ignore[no-redef]
        def __init__(
            self,
            role: str,
            goal: str,
            backstory: str = "",
            allow_delegation: bool = False,
            verbose: bool = False,
            llm=None,
            tools: list | None = None,
        ) -> None:
            self.role = role
            self.goal = goal
            self.backstory = backstory
            self.allow_delegation = allow_delegation
            self.verbose = verbose
            self.llm = llm
            self.tools = tools or []

    class Task:  # type: ignore[no-redef]
        def __init__(
            self,
            description: str,
            expected_output: str,
            agent: Agent,
            output_pydantic=None,
            output_json=None,
            context: list["Task"] | None = None,
            name: str | None = None,
        ) -> None:
            self.description = description
            self.expected_output = expected_output
            self.agent = agent
            self.output_pydantic = output_pydantic
            self.output_json = output_json
            self.context = context or []
            self.name = name or "task"
            self.output = None

    class Crew:  # type: ignore[no-redef]
        def __init__(
            self,
            agents: list[Agent],
            tasks: list[Task],
            verbose: bool = False,
        ) -> None:
            self.agents = agents
            self.tasks = tasks
            self.verbose = verbose

        def kickoff(self, inputs: dict[str, Any] | None = None):
            _ = inputs
            raise RuntimeError(
                "Fallback Crew cannot execute without deterministic mode"
            )


@dataclass
class _TaskOutput:
    pydantic: BaseModel

    @property
    def json_dict(self) -> dict[str, Any]:
        return self.pydantic.model_dump()


def momentum_tool(
    snapshot: MarketSnapshotModel, state: dict[str, float]
) -> DecisionModel:
    best_symbol: str | None = None
    best_change = float("-inf")
    for symbol, price in snapshot.prices.items():
        if price <= 0:
            continue
        previous = state.get(symbol)
        if previous is not None and previous > 0:
            change = (price - previous) / previous
            if change > best_change:
                best_change = change
                best_symbol = symbol
        state[symbol] = price

    if best_symbol is None:
        return DecisionModel(
            action="HOLD",
            symbol=None,
            reason="market: no momentum signal",
            confidence=0.45,
        )
    momentum_confidence = min(0.4 + abs(best_change) * 20.0, 0.85)
    if best_change >= 0.01:
        return DecisionModel(
            action="BUY",
            symbol=best_symbol,
            reason=f"market: momentum up {best_change * 100:.2f}%",
            confidence=momentum_confidence,
        )
    if best_change <= -0.01 and snapshot.positions.get(best_symbol, 0) > 0:
        return DecisionModel(
            action="SELL",
            symbol=best_symbol,
            reason=f"market: momentum down {abs(best_change) * 100:.2f}%",
            confidence=momentum_confidence,
        )
    neutral_confidence = max(0.4, min(0.55, momentum_confidence))
    return DecisionModel(
        action="HOLD",
        symbol=None,
        reason="market: momentum neutral",
        confidence=neutral_confidence,
    )


def valuation_tool(
    snapshot: MarketSnapshotModel,
    symbols: list[str],
    max_shares_per_symbol: int,
) -> DecisionModel:
    for symbol in symbols:
        qty = int(snapshot.positions.get(symbol, 0))
        price = snapshot.prices.get(symbol)
        if qty <= 0 or price is None or price <= 0:
            continue
        avg_entry = float(snapshot.avg_entry_prices.get(symbol, 0.0))
        insight: PositionInsight = compute_position_insight(
            {"symbol": symbol, "qty": qty, "avg_entry_price": avg_entry},
            current_price=price,
        )
        pnl_pct_display = f"{insight.pnl_pct * 100:+.1f}%"
        if insight.pnl_pct >= TAKE_PROFIT_PCT:
            print(f"[strategy] {symbol} pnl={pnl_pct_display} take-profit triggered")
            return DecisionModel(
                action="SELL", symbol=symbol, reason="take profit hit", confidence=0.9
            )
        if insight.pnl_pct <= STOP_LOSS_PCT:
            print(f"[strategy] {symbol} pnl={pnl_pct_display} stop-loss triggered")
            return DecisionModel(
                action="SELL", symbol=symbol, reason="stop loss hit", confidence=0.85
            )

    fair_value_tool = FairValueTool()
    best_buy: tuple[str, float, float] | None = None
    best_sell: tuple[str, float, float] | None = None
    for symbol in symbols:
        if int(snapshot.positions.get(symbol, 0)) >= max_shares_per_symbol:
            continue
        price = snapshot.prices.get(symbol)
        fair = FAIR_VALUES.get(symbol)
        if fair is None or price is None or price <= 0:
            continue
        score = fair_value_tool.run(price=price, fair=fair)
        if best_buy is None or score > best_buy[1]:
            best_buy = (symbol, score, price)
        if best_sell is None or score < best_sell[1]:
            best_sell = (symbol, score, price)

    if best_buy and best_buy[1] >= 0.03:
        fair = FAIR_VALUES[best_buy[0]]
        confidence = min(0.5 + max(best_buy[1] - 0.03, 0.0) * 5.0, 0.9)
        return DecisionModel(
            action="BUY",
            symbol=best_buy[0],
            reason=f"valuation: score={best_buy[1]:.3f}, fair={fair:.2f}, price={best_buy[2]:.2f}",
            confidence=confidence,
        )
    if (
        best_sell
        and best_sell[1] <= -0.03
        and snapshot.positions.get(best_sell[0], 0) > 0
    ):
        fair = FAIR_VALUES[best_sell[0]]
        confidence = min(0.6 + max(abs(best_sell[1]) - 0.03, 0.0) * 3.0, 0.85)
        return DecisionModel(
            action="SELL",
            symbol=best_sell[0],
            reason=f"valuation: score={best_sell[1]:.3f}, fair={fair:.2f}, price={best_sell[2]:.2f}",
            confidence=confidence,
        )
    return DecisionModel(
        action="HOLD",
        symbol=None,
        reason="valuation: no actionable signal",
        confidence=0.5,
    )


def risk_tool(
    snapshot: MarketSnapshotModel,
    market: DecisionModel,
    valuation: DecisionModel,
    allowlist: set[str],
    market_is_open: bool | None,
    max_shares_per_symbol: int,
    forced_veto: str | None = None,
) -> RiskResult:
    if forced_veto == "market_closed":
        return RiskResult(status="VETO", reason="market closed", confidence=1.0)
    if forced_veto == "symbol_not_allowed":
        return RiskResult(status="VETO", reason="symbol not allowed", confidence=1.0)
    if forced_veto == "insufficient_cash":
        return RiskResult(status="VETO", reason="insufficient cash", confidence=1.0)

    if market_is_open is not None:
        if not market_is_open:
            return RiskResult(status="VETO", reason="market closed", confidence=1.0)
    else:
        snapshot_ts = _parse_snapshot_timestamp(snapshot.timestamp)
        if not _is_market_open_at(snapshot_ts):
            return RiskResult(status="VETO", reason="market closed", confidence=1.0)

    proposed = valuation if valuation.action in {"BUY", "SELL"} else market
    symbol = (proposed.symbol or "").upper() if proposed.symbol else None
    action = proposed.action
    if symbol is not None and symbol not in allowlist:
        return RiskResult(status="VETO", reason="symbol not allowed", confidence=1.0)

    if action == "BUY" and symbol is not None:
        current_qty = int(snapshot.positions.get(symbol, 0))
        if current_qty >= max_shares_per_symbol:
            return RiskResult(
                status="VETO", reason="position limit reached", confidence=1.0
            )
        price = snapshot.prices.get(symbol)
        if price is None or price <= 0:
            return RiskResult(status="VETO", reason="insufficient cash", confidence=1.0)
        if snapshot.cash < price:
            return RiskResult(status="VETO", reason="insufficient cash", confidence=1.0)

    return RiskResult(status="APPROVE", reason="checks passed", confidence=0.7)


def _parse_snapshot_timestamp(raw_timestamp: str) -> datetime:
    text = raw_timestamp.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_market_open_at(ts: datetime) -> bool:
    ny_ts = ts.astimezone(ZoneInfo("America/New_York"))
    if ny_ts.weekday() >= 5:
        return False
    market_open = time(hour=9, minute=30)
    market_close = time(hour=16, minute=0)
    current = ny_ts.time()
    return market_open <= current <= market_close


def _clamp_confidence(value: float | None) -> float:
    if value is None:
        return 0.5
    return max(0.0, min(1.0, float(value)))


def _weighted_confidence(
    market_conf: float, valuation_conf: float, risk_conf: float
) -> float:
    return 0.30 * market_conf + 0.45 * valuation_conf + 0.25 * risk_conf


def _apply_buy_cooldown_confidence(
    symbol: str | None,
    snapshot_ts: str,
    valuation_confidence: float,
) -> float:
    if symbol is None:
        return valuation_confidence
    last_sell_ts = get_last_sell_ts(symbol)
    if last_sell_ts is None:
        return valuation_confidence
    snapshot_dt = _parse_snapshot_timestamp(snapshot_ts)
    elapsed_min = (snapshot_dt - last_sell_ts).total_seconds() / 60.0
    cooldown_min = get_sell_cooldown_min()
    if elapsed_min < cooldown_min:
        return min(valuation_confidence, 0.4)
    return valuation_confidence


def coordinate_tool(
    snapshot: MarketSnapshotModel,
    market: DecisionModel,
    valuation: DecisionModel,
    risk: RiskResult,
) -> DecisionModel:
    market_conf = _clamp_confidence(market.confidence)
    valuation_conf = _clamp_confidence(valuation.confidence)
    risk_conf = _clamp_confidence(risk.confidence)

    if risk.status == "VETO":
        final_conf = _weighted_confidence(market_conf, valuation_conf, 1.0)
        print(
            f"[confidence] valuation={valuation_conf:.2f} market={market_conf:.2f} "
            f"risk={1.00:.2f} final={final_conf:.2f}"
        )
        return DecisionModel(
            action="HOLD",
            symbol=None,
            reason=(
                f"risk veto: {risk.reason} | "
                f"market={market.action}:{market.reason} | "
                f"valuation={valuation.action}:{valuation.reason}"
            ),
            confidence=final_conf,
        )

    effective_valuation_conf = valuation_conf
    if valuation.action == "BUY":
        effective_valuation_conf = _apply_buy_cooldown_confidence(
            symbol=valuation.symbol,
            snapshot_ts=snapshot.timestamp,
            valuation_confidence=valuation_conf,
        )
    final_confidence = _weighted_confidence(
        market_conf, effective_valuation_conf, risk_conf
    )
    print(
        f"[confidence] valuation={effective_valuation_conf:.2f} market={market_conf:.2f} "
        f"risk={risk_conf:.2f} final={final_confidence:.2f}"
    )

    if valuation.action == "SELL":
        return DecisionModel(
            action="SELL",
            symbol=valuation.symbol,
            reason=valuation.reason,
            confidence=final_confidence,
        )
    if valuation.action == "BUY":
        if effective_valuation_conf < 0.6 or final_confidence < 0.65:
            return DecisionModel(
                action="HOLD",
                symbol=None,
                reason=(
                    f"buy confidence too low | valuation_conf={effective_valuation_conf:.2f} "
                    f"final_conf={final_confidence:.2f} | "
                    f"market={market.action}:{market.reason} | "
                    f"valuation={valuation.action}:{valuation.reason}"
                ),
                confidence=final_confidence,
            )
        if market.action == "SELL":
            return DecisionModel(
                action="HOLD",
                symbol=None,
                reason=(
                    f"buy blocked by market sell | "
                    f"market={market.action}:{market.reason} | "
                    f"valuation={valuation.action}:{valuation.reason}"
                ),
                confidence=final_confidence,
            )
        return DecisionModel(
            action="BUY",
            symbol=valuation.symbol,
            reason=valuation.reason,
            confidence=final_confidence,
        )
    return DecisionModel(
        action="HOLD",
        symbol=None,
        reason=(
            f"no actionable signal | "
            f"market={market.action}:{market.reason} | "
            f"valuation={valuation.action}:{valuation.reason}"
        ),
        confidence=final_confidence,
    )


class DeterministicTradingCrew:
    def __init__(
        self,
        agents: list[Agent],
        tasks: list[Task],
        symbols: list[str],
        allowlist: set[str],
        market_is_open: bool | None,
        max_shares_per_symbol: int,
        forced_veto: str | None,
    ) -> None:
        self.agents = agents
        self.tasks = tasks
        self._symbols = symbols
        self._allowlist = allowlist
        self._market_is_open = market_is_open
        self._max_shares_per_symbol = max_shares_per_symbol
        self._forced_veto = forced_veto
        self._market_state: dict[str, float] = {}

    def kickoff(self, inputs: dict[str, Any] | None = None):
        context = dict(inputs or {})
        snapshot_raw = context.get("snapshot")
        snapshot = MarketSnapshotModel.model_validate(snapshot_raw)
        kickoff_market_is_open = context.get("market_is_open", self._market_is_open)
        if not isinstance(kickoff_market_is_open, bool):
            kickoff_market_is_open = None

        market_out = momentum_tool(snapshot, state=self._market_state)
        self.tasks[0].output = _TaskOutput(pydantic=market_out)
        context["market"] = self.tasks[0].output.json_dict

        valuation_out = valuation_tool(
            snapshot,
            symbols=self._symbols,
            max_shares_per_symbol=self._max_shares_per_symbol,
        )
        self.tasks[1].output = _TaskOutput(pydantic=valuation_out)
        context["valuation"] = self.tasks[1].output.json_dict

        risk_out = risk_tool(
            snapshot,
            market=market_out,
            valuation=valuation_out,
            allowlist=self._allowlist,
            market_is_open=kickoff_market_is_open,
            max_shares_per_symbol=self._max_shares_per_symbol,
            forced_veto=self._forced_veto,
        )
        self.tasks[2].output = _TaskOutput(pydantic=risk_out)
        context["risk"] = self.tasks[2].output.json_dict

        coord_out = coordinate_tool(snapshot, market_out, valuation_out, risk_out)
        self.tasks[3].output = _TaskOutput(pydantic=coord_out)
        context["coord"] = self.tasks[3].output.json_dict
        return SimpleNamespace(tasks=self.tasks, final=self.tasks[3].output)


def build_trading_crew(
    llm=None,
    symbols: list[str] | None = None,
    allowlist: set[str] | None = None,
    market_is_open: bool | None = None,
    run_mode: str = "mock",
) -> Crew | DeterministicTradingCrew:
    symbols = [s.upper() for s in (symbols or ["PLTR", "NFLX", "PLTK"])]
    allowlist = {s.upper() for s in (allowlist or set(symbols))}

    market_agent = Agent(
        role="MarketAgent",
        goal="Generate a market momentum decision from snapshot data.",
        backstory="A deterministic momentum specialist for short horizon signals.",
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )
    valuation_agent = Agent(
        role="ValuationAgent",
        goal="Generate BUY/SELL/HOLD from fair-value scoring.",
        backstory="A valuation analyst using deterministic fair-value tools.",
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )
    risk_agent = Agent(
        role="RiskAgent",
        goal="Apply hard veto checks over market state, symbols, prices, and cash sanity.",
        backstory="A strict risk controller with deterministic veto rules.",
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )
    coordinator_agent = Agent(
        role="CoordinatorAgent",
        goal="Merge market, valuation, and risk outputs deterministically.",
        backstory="A rule-based coordinator that outputs final trade action.",
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )

    task_market = Task(
        name="task_market",
        description=(
            "Inputs:\n"
            "- snapshot: {snapshot}\n"
            "- symbols: {symbols}\n"
            "- market_is_open: {market_is_open}\n"
            "Use snapshot input and produce ONLY a DecisionModel JSON/pydantic output. "
            "No prose. Action must be BUY, SELL, or HOLD. "
            "You MUST choose symbol only from {symbols} (case-insensitive). "
            "If no actionable signal, return HOLD with symbol=null."
        ),
        expected_output="DecisionModel",
        agent=market_agent,
        output_pydantic=DecisionModel,
    )
    task_valuation = Task(
        name="task_valuation",
        description=(
            "Inputs:\n"
            "- snapshot: {snapshot}\n"
            "- symbols: {symbols}\n"
            "- market_is_open: {market_is_open}\n"
            "Use valuation + strategy exits and produce ONLY a DecisionModel JSON/pydantic output. "
            "Rules include SELL exits on take-profit and stop-loss, else BUY/HOLD from valuation. "
            "You MUST choose symbol only from {symbols} (case-insensitive). "
            "If no actionable signal, return HOLD with symbol=null."
        ),
        expected_output="DecisionModel",
        agent=valuation_agent,
        output_pydantic=DecisionModel,
        context=[task_market],
    )
    task_risk = Task(
        name="task_risk",
        description=(
            "Inputs:\n"
            "- snapshot: {snapshot}\n"
            "- symbols: {symbols}\n"
            "- market_is_open: {market_is_open}\n"
            "Apply gatekeeper checks and produce ONLY a RiskResult JSON/pydantic output. "
            "Rules: if {market_is_open} is False => VETO('market closed'); "
            "if {market_is_open} is True => do NOT return market-closed veto; "
            "if {market_is_open} is None => use snapshot timestamp market-hours fallback. "
            "If proposed decision symbol is not in {symbols} => "
            "VETO('symbol not allowed'). Proposed BUY when positions[symbol] >= "
            "RISK_MAX_SHARES => VETO('position limit reached'); proposed BUY without enough "
            "cash for 1 share => VETO('insufficient cash'); otherwise APPROVE('checks passed')."
        ),
        expected_output="RiskResult",
        agent=risk_agent,
        output_pydantic=RiskResult,
        context=[task_market, task_valuation],
    )
    task_coord = Task(
        name="task_coord",
        description=(
            "Inputs:\n"
            "- snapshot: {snapshot}\n"
            "- symbols: {symbols}\n"
            "- market_is_open: {market_is_open}\n"
            "Combine prior decisions deterministically and produce ONLY DecisionModel. "
            "Inputs: Market DecisionModel, Valuation DecisionModel, RiskResult. "
            "Rules: if risk.status == VETO => HOLD with "
            '"risk veto: <risk.reason> | market=<...> | valuation=<...>". '
            "Else valuation SELL has priority. BUY only if valuation BUY and market is not SELL. "
            "Use confidence-weighted aggregation and include confidence in output. "
            "You MUST choose symbol only from {symbols} (case-insensitive). "
            "If no actionable signal, return HOLD with symbol=null."
        ),
        expected_output="DecisionModel",
        agent=coordinator_agent,
        output_pydantic=DecisionModel,
        context=[task_market, task_valuation, task_risk],
    )
    tasks = [task_market, task_valuation, task_risk, task_coord]

    llm_mode = os.getenv("LLM_MODE", "stub").strip().lower() or "stub"
    max_shares_per_symbol = get_risk_max_shares()

    risk_force_veto = None
    if run_mode == "mock":
        raw_force = os.getenv("RISK_FORCE_VETO", "").strip().lower()
        if raw_force in {"market_closed", "symbol_not_allowed", "insufficient_cash"}:
            risk_force_veto = raw_force
    if llm_mode == "stub" or not _CREWAI_AVAILABLE:
        return DeterministicTradingCrew(
            agents=[market_agent, valuation_agent, risk_agent, coordinator_agent],
            tasks=tasks,
            symbols=symbols,
            allowlist=allowlist,
            market_is_open=market_is_open,
            max_shares_per_symbol=max_shares_per_symbol,
            forced_veto=risk_force_veto,
        )

    return Crew(
        agents=[market_agent, valuation_agent, risk_agent, coordinator_agent],
        tasks=tasks,
        verbose=False,
    )
