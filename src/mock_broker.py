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
        self._open_orders: list[dict[str, str]] = []

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

    def list_open_orders(
        self,
        symbol: str | None = None,
        side: str | None = None,
    ) -> list[dict[str, str]]:
        symbol_filter = symbol.upper() if symbol is not None else None
        side_filter = side.lower() if side is not None else None

        matches: list[dict[str, str]] = []
        for order in self._open_orders:
            if symbol_filter is not None and order["symbol"] != symbol_filter:
                continue
            if side_filter is not None and order["side"] != side_filter:
                continue
            matches.append(dict(order))
        return matches

    def has_open_order(self, symbol: str, side: str) -> bool:
        return any(self.list_open_orders(symbol=symbol, side=side))

    def seed_open_order(self, symbol: str, side: str) -> None:
        self._validate_symbol(symbol)
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        self._open_orders.append({"symbol": symbol.upper(), "side": side})

    def clear_open_orders(self) -> None:
        self._open_orders.clear()

    def _validate_symbol(self, symbol: str) -> None:
        if symbol not in self._PRICES:
            raise ValueError(f"unsupported symbol: {symbol}")
