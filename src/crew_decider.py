from __future__ import annotations

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
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


def _market_agent(snapshot: MarketSnapshot, symbols: list[str]) -> dict:
    prices = {symbol: snapshot.prices[symbol] for symbol in symbols if symbol in snapshot.prices}
    return {
        "prices": prices,
        "cash": snapshot.cash,
        "positions": dict(snapshot.positions),
    }


def _valuation_agent(prices: dict[str, float], tool: FairValueTool) -> dict[str, float]:
    scores = {}
    for symbol, price in prices.items():
        scores[symbol] = tool.run(price, FAIR_VALUES[symbol])
    return scores


def _risk_agent(
    prices: dict[str, float],
    positions: dict[str, int],
    cash: float,
    max_position_pct: float,
) -> dict[str, bool]:
    total = cash + sum(positions.get(symbol, 0) * price for symbol, price in prices.items())
    risk_ok = {}
    for symbol, price in prices.items():
        current_qty = positions.get(symbol, 0)
        proposed_value = current_qty * price + price
        risk_ok[symbol] = total <= 0 or proposed_value <= max_position_pct * total
    return risk_ok


def _coordination_agent(
    scores: dict[str, float],
    risk_ok: dict[str, bool],
    prices: dict[str, float],
) -> Decision:
    best_symbol = max(scores, key=scores.get) if scores else None
    best_score = scores[best_symbol] if best_symbol else float("-inf")
    if not best_symbol or best_score <= 0.03:
        return Decision(action=TradeAction.HOLD, symbol=None, qty=0, reason="not undervalued enough")
    price = prices[best_symbol]
    if not risk_ok.get(best_symbol, False):
        return Decision(action=TradeAction.HOLD, symbol=None, qty=0, reason="risk cap")
    fair = FAIR_VALUES[best_symbol]
    reason = f"score={best_score:.3f}, fair={fair:.2f}, price={price:.2f}"
    return Decision(action=TradeAction.BUY, symbol=best_symbol, qty=1, reason=reason)


def decide_with_crew(
    snapshot: MarketSnapshot,
    symbols: list[str],
    max_position_pct: float = 0.4,
) -> Decision:
    market_agent = Agent(
        role="MarketAgent",
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
        role="CoordinationAgent",
        goal="Merge sub-agent outputs and choose final BUY/HOLD action",
        backstory="A deterministic coordinator that resolves all agent outputs.",
        allow_delegation=False,
        verbose=False,
    )
    crew = Crew(
        agents=[market_agent, val_agent, risk_agent, dec_agent],
        tasks=[
            Task(
                description="Collect market snapshot fields for candidate symbols.",
                expected_output="Context contains cash, positions, and snapshot prices per symbol.",
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
    _ = crew
    market_ctx = _market_agent(snapshot, symbols)
    scores = _valuation_agent(market_ctx["prices"], FairValueTool())
    risk_ok = _risk_agent(
        market_ctx["prices"],
        market_ctx["positions"],
        market_ctx["cash"],
        max_position_pct,
    )
    return _coordination_agent(scores, risk_ok, market_ctx["prices"])
