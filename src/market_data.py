from __future__ import annotations

import sys
import time

try:
    from alpaca_trade_api.rest import REST
    _ALPACA_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised in environments without alpaca package
    REST = object  # type: ignore[assignment]
    _ALPACA_IMPORT_ERROR = exc

from src.rate_limiter import RateLimiter

_api_client: REST | None = None
_rate_limiter: RateLimiter | None = None
_price_cache: dict[str, tuple[float, float]] = {}
_cache_ttl_seconds = 5.0


def configure_api_client(
    api: REST,
    rate_limiter: RateLimiter | None = None,
    cache_ttl_seconds: float = 5.0,
) -> None:
    if _ALPACA_IMPORT_ERROR is not None:
        raise RuntimeError(
            f"alpaca-trade-api import failed: {_ALPACA_IMPORT_ERROR}"
        ) from _ALPACA_IMPORT_ERROR
    global _rate_limiter
    global _cache_ttl_seconds
    global _api_client
    _api_client = api
    _rate_limiter = rate_limiter
    _cache_ttl_seconds = cache_ttl_seconds
    _price_cache.clear()
    print("[market_data] Alpaca market data client configured.")


def get_latest_price(symbol: str) -> float:
    if _api_client is None:
        message = "Market data client is not configured. Call configure_api_client(api) first."
        print(f"[market_data] ERROR: {message}", file=sys.stderr)
        raise RuntimeError(message)

    clean_symbol = symbol.strip().upper()
    if not clean_symbol:
        message = "Symbol cannot be empty."
        print(f"[market_data] ERROR: {message}", file=sys.stderr)
        raise ValueError(message)

    cached = _price_cache.get(clean_symbol)
    now = time.time()
    if cached is not None:
        expires_at, cached_price = cached
        if now < expires_at:
            print(f"[data] Cache hit for {clean_symbol}: {cached_price}")
            return cached_price

    print(f"[market_data] Fetching latest price for {clean_symbol}...")
    _wait_for_rate_limit(f"market_data:{clean_symbol}")
    try:
        trade = _api_client.get_latest_trade(clean_symbol)
        trade_price = float(trade.price)
        _price_cache[clean_symbol] = (now + _cache_ttl_seconds, trade_price)
        print(f"[market_data] Latest trade price for {clean_symbol}: {trade_price}")
        return trade_price
    except Exception as trade_exc:
        print(
            f"[market_data] WARN: get_latest_trade failed for {clean_symbol}: {trade_exc}. "
            "Trying latest bar..."
        )

    try:
        _wait_for_rate_limit(f"market_data:{clean_symbol}:bar")
        bar = _api_client.get_latest_bar(clean_symbol)
        bar_price = float(bar.c)
        _price_cache[clean_symbol] = (time.time() + _cache_ttl_seconds, bar_price)
        print(f"[market_data] Latest bar close for {clean_symbol}: {bar_price}")
        return bar_price
    except Exception as bar_exc:
        message = (
            f"Could not fetch latest price for {clean_symbol} via trade or bar API: {bar_exc}"
        )
        print(f"[market_data] ERROR: {message}", file=sys.stderr)
        raise RuntimeError(message) from bar_exc


def _wait_for_rate_limit(key: str) -> None:
    if _rate_limiter is None:
        return
    while not _rate_limiter.allow(key):
        print(f"[data] Rate limit hit for {key}; sleeping 0.2s")
        time.sleep(0.2)
