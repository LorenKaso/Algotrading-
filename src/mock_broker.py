from __future__ import annotations

from src.broker import Broker


class MockBroker(Broker):
    _PRICES: dict[str, float] = {
        "PLTR": 100.0,
        "NFLX": 200.0,
        "PLTK": 20.0,
    }

    def __init__(self, starting_cash: float = 100000.0) -> None:
        self._cash = float(starting_cash)
        self._positions: dict[str, int] = {s: 0 for s in self._PRICES}

    def get_cash(self) -> float:
        return self._cash

    def get_positions(self) -> dict[str, int]:
        return dict(self._positions)

    def get_price(self, symbol: str) -> float:
        self._validate_symbol(symbol)
        return self._PRICES[symbol]

    def place_order(self, symbol: str, side: str, qty: int) -> None:
        self._validate_symbol(symbol)
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        price = self._PRICES[symbol]
        cost = price * qty
        if side == "buy":
            if cost > self._cash:
                raise ValueError("insufficient cash")
            self._cash -= cost
            self._positions[symbol] += qty
            return

        if qty > self._positions[symbol]:
            raise ValueError("insufficient position")
        self._cash += cost
        self._positions[symbol] -= qty

    def _validate_symbol(self, symbol: str) -> None:
        if symbol not in self._PRICES:
            raise ValueError(f"unsupported symbol: {symbol}")
