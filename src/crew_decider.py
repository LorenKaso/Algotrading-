from __future__ import annotations

from dataclasses import dataclass

from src.decision_types import Decision, TradeAction
from src.market_snapshot import MarketSnapshot
from src.strategy_buffett_lite import FAIR_VALUES
from src.tools import FairValueTool

_MARKET_PRICE_CACHE: dict[str, float] = {}


def _normalize_symbols(
    symbols: list[str] | None,
    snapshot: MarketSnapshot,
) -> list[str]:
    if symbols is None:
        symbols = list(snapshot.prices.keys())
    return [symbol.upper() for symbol in symbols]


@dataclass(frozen=True)
class CoordinationResult:
    market_decision: Decision
    valuation_decision: Decision
    risk_decision: Decision
    final_decision: Decision


class MarketAgent:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols
        self._last_prices = _MARKET_PRICE_CACHE

    def decide(self, snapshot: MarketSnapshot) -> Decision:
        best_symbol: str | None = None
        best_change = float("-inf")

        for symbol in self._symbols:
            price = snapshot.prices.get(symbol)
            if price is None or price <= 0:
                continue
            previous = self._last_prices.get(symbol)
            if previous is not None and previous > 0:
                pct_change = (price - previous) / previous
                if pct_change > best_change:
                    best_change = pct_change
                    best_symbol = symbol
            self._last_prices[symbol] = price

        if best_symbol is None:
            return Decision(
                action=TradeAction.HOLD,
                symbol=None,
                qty=0,
                reason="no momentum signal",
            )

        if best_change >= 0.01:
            return Decision(
                action=TradeAction.BUY,
                symbol=best_symbol,
                qty=1,
                reason=f"momentum up {best_change * 100:.2f}%",
            )

        if best_change <= -0.01 and snapshot.positions.get(best_symbol, 0) > 0:
            return Decision(
                action=TradeAction.SELL,
                symbol=best_symbol,
                qty=1,
                reason=f"momentum down {abs(best_change) * 100:.2f}%",
            )

        return Decision(
            action=TradeAction.HOLD,
            symbol=None,
            qty=0,
            reason=f"momentum neutral {best_change * 100:.2f}%",
        )


class ValuationAgent:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols
        self._tool = FairValueTool()

    def decide(self, snapshot: MarketSnapshot) -> Decision:
        best_buy: tuple[str, float, float] | None = None
        best_sell: tuple[str, float, float] | None = None

        for symbol in self._symbols:
            price = snapshot.prices.get(symbol)
            fair = FAIR_VALUES.get(symbol)
            if fair is None or price is None or price <= 0:
                continue
            score = self._tool.run(price=price, fair=fair)
            if best_buy is None or score > best_buy[1]:
                best_buy = (symbol, score, price)
            if best_sell is None or score < best_sell[1]:
                best_sell = (symbol, score, price)

        if best_buy is not None and best_buy[1] >= 0.03:
            fair = FAIR_VALUES[best_buy[0]]
            return Decision(
                action=TradeAction.BUY,
                symbol=best_buy[0],
                qty=1,
                reason=(
                    f"score={best_buy[1]:.3f}, "
                    f"fair={fair:.2f}, "
                    f"price={best_buy[2]:.2f}"
                ),
            )
        if (
            best_sell is not None
            and best_sell[1] <= -0.03
            and snapshot.positions.get(best_sell[0], 0) > 0
        ):
            fair = FAIR_VALUES[best_sell[0]]
            return Decision(
                action=TradeAction.SELL,
                symbol=best_sell[0],
                qty=1,
                reason=(
                    f"score={best_sell[1]:.3f}, "
                    f"fair={fair:.2f}, "
                    f"price={best_sell[2]:.2f}"
                ),
            )

        return Decision(
            action=TradeAction.HOLD,
            symbol=None,
            qty=0,
            reason="not undervalued enough",
        )


class RiskAgent:
    def __init__(
        self,
        symbols: list[str],
        allowed_symbols: set[str] | None = None,
        market_is_open: bool | None = None,
    ) -> None:
        self._symbols = symbols
        self._allowed_symbols = {
            symbol.upper() for symbol in (allowed_symbols or set(symbols))
        }
        self._market_is_open = market_is_open

    def decide(self, snapshot: MarketSnapshot) -> Decision:
        if self._market_is_open is False:
            return Decision(TradeAction.HOLD, None, 0, "VETO: market closed")
        if not self._symbols:
            return Decision(TradeAction.HOLD, None, 0, "APPROVE: risk checks passed")

        for symbol in self._symbols:
            if symbol not in self._allowed_symbols:
                return Decision(
                    TradeAction.HOLD,
                    None,
                    0,
                    f"VETO: symbol not allowed ({symbol})",
                )
            price = snapshot.prices.get(symbol)
            if price is None or price <= 0:
                return Decision(
                    TradeAction.HOLD,
                    None,
                    0,
                    f"VETO: price missing for {symbol}",
                )

        minimum_price = min(snapshot.prices[symbol] for symbol in self._symbols)
        if snapshot.cash < minimum_price:
            return Decision(TradeAction.HOLD, None, 0, "VETO: cash too low")

        return Decision(TradeAction.HOLD, None, 0, "APPROVE: risk checks passed")


class CoordinatorAgent:
    def __init__(
        self,
        market_decision: Decision,
        valuation_decision: Decision,
        risk_decision: Decision,
    ) -> None:
        self._market_decision = market_decision
        self._valuation_decision = valuation_decision
        self._risk_decision = risk_decision

    def decide(self, snapshot: MarketSnapshot) -> Decision:
        _ = snapshot
        market_text = (
            f"{self._market_decision.action.value}:" f"{self._market_decision.reason}"
        )
        valuation_text = (
            f"{self._valuation_decision.action.value}:"
            f"{self._valuation_decision.reason}"
        )
        merged = (
            f"market={market_text} | "
            f"valuation={valuation_text} | "
            f"risk={self._risk_decision.reason}"
        )
        if self._risk_decision.reason.upper().startswith("VETO"):
            return Decision(TradeAction.HOLD, None, 0, merged)

        if self._valuation_decision.action in {TradeAction.BUY, TradeAction.SELL}:
            return Decision(
                action=self._valuation_decision.action,
                symbol=self._valuation_decision.symbol,
                qty=self._valuation_decision.qty,
                reason=merged,
            )

        if self._market_decision.action in {TradeAction.BUY, TradeAction.SELL}:
            return Decision(
                action=self._market_decision.action,
                symbol=self._market_decision.symbol,
                qty=self._market_decision.qty,
                reason=merged,
            )

        return Decision(TradeAction.HOLD, None, 0, merged)


def decide(
    snapshot: MarketSnapshot,
    symbols: list[str] | None = None,
    allowed_symbols: set[str] | None = None,
    market_is_open: bool | None = None,
) -> CoordinationResult:
    normalized_symbols = _normalize_symbols(symbols, snapshot)
    market_agent = MarketAgent(normalized_symbols)
    valuation_agent = ValuationAgent(normalized_symbols)
    risk_agent = RiskAgent(
        symbols=normalized_symbols,
        allowed_symbols=allowed_symbols,
        market_is_open=market_is_open,
    )

    market_decision = market_agent.decide(snapshot)
    valuation_decision = valuation_agent.decide(snapshot)
    risk_decision = risk_agent.decide(snapshot)
    coordinator = CoordinatorAgent(
        market_decision=market_decision,
        valuation_decision=valuation_decision,
        risk_decision=risk_decision,
    )
    final_decision = coordinator.decide(snapshot)
    return CoordinationResult(
        market_decision=market_decision,
        valuation_decision=valuation_decision,
        risk_decision=risk_decision,
        final_decision=final_decision,
    )


def decide_with_crew(
    snapshot: MarketSnapshot,
    symbols: list[str],
    max_position_pct: float = 0.4,
) -> Decision:
    _ = max_position_pct
    return decide(snapshot=snapshot, symbols=symbols).final_decision
