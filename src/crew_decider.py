from __future__ import annotations

from src.decision_types import Decision, TradeAction
from src.portfolio import portfolio_value
from src.strategy_buffett_lite import FAIR_VALUES
from src.tools import FairValueTool

try:
    from crewai import Agent, Crew, Task
except Exception:  # pragma: no cover
    class Agent:
        def __init__(
            self,
            role: str,
            goal: str,
            backstory: str = "",
            allow_delegation: bool = False,
            verbose: bool = False,
        ) -> None:
            self.role = role
            self.goal = goal
            self.backstory = backstory
            self.allow_delegation = allow_delegation
            self.verbose = verbose

    class Task:
        def __init__(self, description: str, expected_output: str, agent: Agent) -> None:
            self.description = description
            self.expected_output = expected_output
            self.agent = agent

    class Crew:
        def __init__(self, agents: list[Agent], tasks: list[Task]) -> None:
            self.agents = agents
            self.tasks = tasks

        def kickoff(self, inputs: dict) -> dict:
            return inputs


def _collect_market_data(ctx: dict) -> None:
    broker = ctx["broker"]
    symbols = ctx["symbols"]
    ctx["cash"] = broker.get_cash()
    ctx["positions"] = broker.get_positions()
    ctx["prices"] = {s: broker.get_price(s) for s in symbols}


def _compute_scores(ctx: dict) -> None:
    tool = ctx["tool"]
    scores = {}
    for symbol, price in ctx["prices"].items():
        scores[symbol] = tool.run(price, FAIR_VALUES[symbol])
    ctx["scores"] = scores


def _check_risk(ctx: dict) -> None:
    broker = ctx["broker"]
    max_position_pct = ctx["max_position_pct"]
    total = portfolio_value(broker)
    positions = ctx["positions"]
    prices = ctx["prices"]
    risk_ok = {}
    for symbol, price in prices.items():
        current_qty = positions.get(symbol, 0)
        proposed_value = current_qty * price + price
        risk_ok[symbol] = total <= 0 or proposed_value <= max_position_pct * total
    ctx["risk_ok"] = risk_ok


def _final_decision(ctx: dict) -> None:
    scores = ctx["scores"]
    risk_ok = ctx["risk_ok"]
    best_symbol = max(scores, key=scores.get) if scores else None
    best_score = scores[best_symbol] if best_symbol else float("-inf")
    if not best_symbol or best_score <= 0.03:
        ctx["result"] = {"action": "HOLD", "symbol": None, "qty": 0, "reason": "not undervalued enough"}
        return
    price = ctx["prices"][best_symbol]
    if not risk_ok.get(best_symbol, False):
        ctx["result"] = {"action": "HOLD", "symbol": None, "qty": 0, "reason": "risk cap"}
        return
    fair = FAIR_VALUES[best_symbol]
    reason = f"score={best_score:.3f}, fair={fair:.2f}, price={price:.2f}"
    ctx["result"] = {"action": "BUY", "symbol": best_symbol, "qty": 1, "reason": reason}


def decide_with_crew(symbols: list[str], broker, max_position_pct: float = 0.4) -> Decision:
    market_agent = Agent(
        role="MarketDataAgent",
        goal="Collect prices, positions, and cash",
        backstory="A data specialist that gathers deterministic broker snapshots.",
        allow_delegation=False,
        verbose=False,
    )
    val_agent = Agent(
        role="ValuationAgent",
        goal="Compute fair value score per symbol",
        backstory="A valuation analyst that applies the fair value scoring tool.",
        allow_delegation=False,
        verbose=False,
    )
    risk_agent = Agent(
        role="RiskAgent",
        goal="Check max position exposure limit",
        backstory="A risk controller enforcing position-size constraints.",
        allow_delegation=False,
        verbose=False,
    )
    dec_agent = Agent(
        role="DecisionAgent",
        goal="Choose BUY or HOLD with reason",
        backstory="A deterministic trader that emits final trade decisions.",
        allow_delegation=False,
        verbose=False,
    )
    crew = Crew(
        agents=[market_agent, val_agent, risk_agent, dec_agent],
        tasks=[
            Task(
                description="Collect prices, positions, and cash for candidate symbols.",
                expected_output="Context contains cash, positions, and current prices for each symbol.",
                agent=market_agent,
            ),
            Task(
                description="Compute fair-value-based scores for each symbol.",
                expected_output="Context contains a score per symbol in ctx['scores'].",
                agent=val_agent,
            ),
            Task(
                description="Evaluate max position exposure for a 1-share buy per symbol.",
                expected_output="Context contains risk gates in ctx['risk_ok'] keyed by symbol.",
                agent=risk_agent,
            ),
            Task(
                description="Choose final BUY/HOLD action with reason from prior context.",
                expected_output="Context contains final payload in ctx['result'].",
                agent=dec_agent,
            ),
        ],
    )
    ctx = {"symbols": symbols, "broker": broker, "max_position_pct": max_position_pct, "tool": FairValueTool()}
    _ = crew
    _collect_market_data(ctx)
    _compute_scores(ctx)
    _check_risk(ctx)
    _final_decision(ctx)
    if "result" not in ctx:
        return Decision(action=TradeAction.HOLD, symbol=None, qty=0, reason="crew decision missing")
    result = ctx["result"]
    return Decision(action=TradeAction[result["action"]], symbol=result["symbol"], qty=result["qty"], reason=result["reason"])
