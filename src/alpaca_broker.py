from __future__ import annotations

import os

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from dotenv import load_dotenv

from src.broker import Broker


class AlpacaBroker(Broker):
    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY")

        self._trading = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,
        )
        self._data = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

    def get_cash(self) -> float:
        account = self._trading.get_account()
        return float(account.cash)  # type: ignore[attr-defined]

    def get_positions(self) -> dict[str, int]:
        positions_list = self._trading.get_all_positions()
        positions: dict[str, int] = {}

        for pos in positions_list:
            symbol = pos.symbol  # type: ignore[attr-defined]
            qty = pos.qty        # type: ignore[attr-defined]
            positions[symbol] = int(float(qty))

        return positions

    def get_price(self, symbol: str) -> float:
        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        latest = self._data.get_stock_latest_trade(req)
        return float(latest[symbol].price)

    def place_order(self, symbol: str, side: str, qty: int) -> None:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        self._trading.submit_order(order_data=order)


if __name__ == "__main__":
    try:
        broker = AlpacaBroker()
        print("cash:", broker.get_cash())
        print("positions:", broker.get_positions())
    except Exception as exc:
        print("smoke check failed:", exc)
