from __future__ import annotations

from typing import Protocol


class Broker(Protocol):
    def get_cash(self) -> float:
        ...

    def get_positions(self) -> dict[str, int]:
        ...

    def get_price(self, symbol: str) -> float:
        ...

    def place_order(self, symbol: str, side: str, qty: int) -> None:
        ...
