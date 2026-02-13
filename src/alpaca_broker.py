from __future__ import annotations

import os
import time

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from dotenv import load_dotenv

from src.broker import Broker
from src.rate_limiter import RateLimiter


class AlpacaBroker(Broker):
    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        cache: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        load_dotenv()
        api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError(
                "Missing Alpaca API credentials. Set either "
                "APCA_API_KEY_ID/APCA_API_SECRET_KEY (preferred) or "
                "ALPACA_API_KEY/ALPACA_SECRET_KEY (backward compatible)."
            )

        self._trading = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,
        )
        self._data = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )
        self._rate_limiter = rate_limiter
        self._price_cache = cache if cache is not None else {}
        self._price_cache_ttl_seconds = 10.0

    def get_cash(self) -> float:
        self._check_rate_limit("alpaca:get_cash")
        account = self._trading.get_account()
        return float(account.cash)  # type: ignore[attr-defined]

    def get_positions(self) -> dict[str, int]:
        self._check_rate_limit("alpaca:get_positions")
        positions_list = self._trading.get_all_positions()
        positions: dict[str, int] = {}

        for pos in positions_list:
            symbol = pos.symbol  # type: ignore[attr-defined]
            qty = pos.qty        # type: ignore[attr-defined]
            positions[symbol] = int(float(qty))

        return positions

    def get_price(self, symbol: str) -> float:
        self._check_rate_limit(f"alpaca:get_price:{symbol}")
        cached = self._price_cache.get(symbol)
        now = time.time()
        if cached is not None:
            expires_at, cached_price = cached
            if now < expires_at:
                return cached_price

        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        latest = self._data.get_stock_latest_trade(req)
        price = float(latest[symbol].price)
        self._price_cache[symbol] = (now + self._price_cache_ttl_seconds, price)
        return price

    def place_order(self, symbol: str, side: str, qty: int) -> None:
        self._check_rate_limit("alpaca:place_order")
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

    def _check_rate_limit(self, key: str) -> None:
        if self._rate_limiter is None:
            return
        if not self._rate_limiter.allow(key):
            raise RuntimeError("Rate limit exceeded")


if __name__ == "__main__":
    try:
        broker = AlpacaBroker()
        print("cash:", broker.get_cash())
        print("positions:", broker.get_positions())
        print("price(PLTR):", broker.get_price("PLTR"))
    except Exception as exc:
        print("smoke check failed:", exc)
