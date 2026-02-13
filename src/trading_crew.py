from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from src.crewai_models import DecisionModel, MarketSnapshotModel, RiskResult
from src.strategy_buffett_lite import FAIR_VALUES
from src.tools import FairValueTool

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
            raise RuntimeError("Fallback Crew cannot execute without deterministic mode")


@dataclass
class _TaskOutput:
    pydantic: BaseModel

    @property
    def json_dict(self) -> dict[str, Any]:
        return self.pydantic.model_dump()


def momentum_tool(snapshot: MarketSnapshotModel, state: dict[str, float]) -> DecisionModel:
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
        return DecisionModel(action="HOLD", symbol=None, reason="market: no momentum signal")
    if best_change >= 0.01:
        return DecisionModel(
            action="BUY",
            symbol=best_symbol,
            reason=f"market: momentum up {best_change * 100:.2f}%",
        )
    if best_change <= -0.01 and snapshot.positions.get(best_symbol, 0) > 0:
        return DecisionModel(
            action="SELL",
            symbol=best_symbol,
            reason=f"market: momentum down {abs(best_change) * 100:.2f}%",
        )
    return DecisionModel(action="HOLD", symbol=None, reason="market: momentum neutral")


def valuation_tool(snapshot: MarketSnapshotModel, symbols: list[str]) -> DecisionModel:
    fair_value_tool = FairValueTool()
    best_buy: tuple[str, float, float] | None = None
    best_sell: tuple[str, float, float] | None = None
    for symbol in symbols:
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
        return DecisionModel(
            action="BUY",
            symbol=best_buy[0],
            reason=f"valuation: score={best_buy[1]:.3f}, fair={fair:.2f}, price={best_buy[2]:.2f}",
        )
    if best_sell and best_sell[1] <= -0.03 and snapshot.positions.get(best_sell[0], 0) > 0:
        fair = FAIR_VALUES[best_sell[0]]
        return DecisionModel(
            action="SELL",
            symbol=best_sell[0],
            reason=f"valuation: score={best_sell[1]:.3f}, fair={fair:.2f}, price={best_sell[2]:.2f}",
        )
    return DecisionModel(action="HOLD", symbol=None, reason="valuation: no actionable signal")


def risk_tool(
    snapshot: MarketSnapshotModel,
    market: DecisionModel,
    valuation: DecisionModel,
    allowlist: set[str],
    market_is_open: bool | None,
    forced_veto: str | None = None,
) -> RiskResult:
    if forced_veto == "market_closed":
        return RiskResult(status="VETO", reason="market closed")
    if forced_veto == "symbol_not_allowed":
        return RiskResult(status="VETO", reason="symbol not allowed")
    if forced_veto == "insufficient_cash":
        return RiskResult(status="VETO", reason="insufficient cash")

    if market_is_open is False:
        return RiskResult(status="VETO", reason="market closed")

    proposed = valuation if valuation.action in {"BUY", "SELL"} else market
    symbol = (proposed.symbol or "").upper() if proposed.symbol else None
    action = proposed.action
    if symbol is not None and symbol not in allowlist:
        return RiskResult(status="VETO", reason="symbol not allowed")

    if action == "BUY" and symbol is not None:
        price = snapshot.prices.get(symbol)
        if price is None or price <= 0:
            return RiskResult(status="VETO", reason="insufficient cash")
        if snapshot.cash < price:
            return RiskResult(status="VETO", reason="insufficient cash")

    return RiskResult(status="APPROVE", reason="checks passed")


def coordinate_tool(
    market: DecisionModel,
    valuation: DecisionModel,
    risk: RiskResult,
) -> DecisionModel:
    if risk.status == "VETO":
        return DecisionModel(
            action="HOLD",
            symbol=None,
            reason=(
                f"risk veto: {risk.reason} | "
                f"market={market.action}:{market.reason} | "
                f"valuation={valuation.action}:{valuation.reason}"
            ),
        )
    if valuation.action in {"BUY", "SELL"}:
        return DecisionModel(
            action=valuation.action,
            symbol=valuation.symbol,
            reason=(
                f"risk approve: {risk.reason} | "
                f"market={market.action}:{market.reason} | "
                f"valuation={valuation.action}:{valuation.reason}"
            ),
        )
    if market.action in {"BUY", "SELL"}:
        return DecisionModel(
            action=market.action,
            symbol=market.symbol,
            reason=(
                f"risk approve: {risk.reason} | "
                f"market={market.action}:{market.reason} | "
                f"valuation={valuation.action}:{valuation.reason}"
            ),
        )
    return DecisionModel(
        action="HOLD",
        symbol=None,
        reason=(
            f"risk approve: {risk.reason} | "
            f"market={market.action}:{market.reason} | "
            f"valuation={valuation.action}:{valuation.reason}"
        ),
    )


class DeterministicTradingCrew:
    def __init__(
        self,
        agents: list[Agent],
        tasks: list[Task],
        symbols: list[str],
        allowlist: set[str],
        market_is_open: bool | None,
        forced_veto: str | None,
    ) -> None:
        self.agents = agents
        self.tasks = tasks
        self._symbols = symbols
        self._allowlist = allowlist
        self._market_is_open = market_is_open
        self._forced_veto = forced_veto
        self._market_state: dict[str, float] = {}

    def kickoff(self, inputs: dict[str, Any] | None = None):
        context = dict(inputs or {})
        snapshot_raw = context.get("snapshot")
        snapshot = MarketSnapshotModel.model_validate(snapshot_raw)

        market_out = momentum_tool(snapshot, state=self._market_state)
        self.tasks[0].output = _TaskOutput(pydantic=market_out)
        context["market"] = self.tasks[0].output.json_dict

        valuation_out = valuation_tool(snapshot, symbols=self._symbols)
        self.tasks[1].output = _TaskOutput(pydantic=valuation_out)
        context["valuation"] = self.tasks[1].output.json_dict

        risk_out = risk_tool(
            snapshot,
            market=market_out,
            valuation=valuation_out,
            allowlist=self._allowlist,
            market_is_open=self._market_is_open,
            forced_veto=self._forced_veto,
        )
        self.tasks[2].output = _TaskOutput(pydantic=risk_out)
        context["risk"] = self.tasks[2].output.json_dict

        coord_out = coordinate_tool(market_out, valuation_out, risk_out)
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
            "Use snapshot input and produce ONLY a DecisionModel JSON/pydantic output. "
            "No prose. Action must be BUY, SELL, or HOLD."
        ),
        expected_output="DecisionModel",
        agent=market_agent,
        output_pydantic=DecisionModel,
    )
    task_valuation = Task(
        name="task_valuation",
        description=(
            "Use valuation scoring and produce ONLY a DecisionModel JSON/pydantic output. "
            "No prose."
        ),
        expected_output="DecisionModel",
        agent=valuation_agent,
        output_pydantic=DecisionModel,
        context=[task_market],
    )
    task_risk = Task(
        name="task_risk",
        description=(
            "Apply gatekeeper checks and produce ONLY a RiskResult JSON/pydantic output. "
            "Rules: market closed => VETO('market closed'); chosen symbol not allowed => "
            "VETO('symbol not allowed'); proposed BUY without enough cash for 1 share => "
            "VETO('insufficient cash'); otherwise APPROVE('checks passed')."
        ),
        expected_output="RiskResult",
        agent=risk_agent,
        output_pydantic=RiskResult,
        context=[task_market, task_valuation],
    )
    task_coord = Task(
        name="task_coord",
        description=(
            "Combine prior decisions deterministically and produce ONLY DecisionModel. "
            "Inputs: Market DecisionModel, Valuation DecisionModel, RiskResult. "
            "Rules: if risk.status == VETO => HOLD with "
            "\"risk veto: <risk.reason> | market=<...> | valuation=<...>\". "
            "Else valuation BUY/SELL has priority over market; otherwise HOLD."
        ),
        expected_output="DecisionModel",
        agent=coordinator_agent,
        output_pydantic=DecisionModel,
        context=[task_market, task_valuation, task_risk],
    )
    tasks = [task_market, task_valuation, task_risk, task_coord]

    llm_mode = os.getenv("LLM_MODE", "stub").strip().lower() or "stub"
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
            forced_veto=risk_force_veto,
        )

    return Crew(
        agents=[market_agent, valuation_agent, risk_agent, coordinator_agent],
        tasks=tasks,
        verbose=False,
    )
