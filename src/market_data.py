from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
_historical_cache: dict[str, list[tuple[datetime, float]]] = {}
_cache_ttl_seconds = 5.0
_historical_cache_dir = Path(".cache") / "market_data"


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
    _historical_cache.clear()
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


def get_price_at(symbol: str, ts: datetime) -> float:
    clean_symbol = symbol.strip().upper()
    if not clean_symbol:
        raise ValueError("Symbol cannot be empty.")

    target_ts = _to_utc(ts)
    run_mode = os.getenv("RUN_MODE", "mock").strip().lower() or "mock"
    if run_mode != "alpaca" or _api_client is None:
        synthetic = _synthetic_price(clean_symbol, target_ts)
        return synthetic

    step_min = _read_step_minutes()
    timeframe = _select_timeframe(step_min)
    start_ts = (target_ts - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_ts = target_ts.replace(hour=23, minute=59, second=59, microsecond=0)
    bars = _get_historical_bars(clean_symbol, timeframe, start_ts, end_ts)
    closes = [close for bar_ts, close in bars if bar_ts <= target_ts]
    if not closes:
        message = (
            f"No historical close available for {clean_symbol} up to {target_ts.isoformat()} "
            f"with timeframe {timeframe}"
        )
        print(f"[market_data] ERROR: {message}", file=sys.stderr)
        raise RuntimeError(message)
    price = closes[-1]
    print(f"[market_data] Historical close for {clean_symbol} at {target_ts.isoformat()}: {price}")
    return price


def _wait_for_rate_limit(key: str) -> None:
    if _rate_limiter is None:
        return
    while not _rate_limiter.allow(key):
        print(f"[data] Rate limit hit for {key}; sleeping 0.2s")
        time.sleep(0.2)


def _read_step_minutes() -> int:
    raw = os.getenv("BACKTEST_STEP_MIN", "60").strip()
    try:
        step = int(raw)
    except ValueError:
        step = 60
    return max(1, step)


def _select_timeframe(step_min: int) -> str:
    if step_min <= 1:
        return "1Min"
    if step_min <= 5:
        return "5Min"
    if step_min <= 15:
        return "15Min"
    if step_min <= 30:
        return "30Min"
    if step_min <= 60:
        return "1Hour"
    return "1Day"


def _get_historical_bars(
    symbol: str,
    timeframe: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[tuple[datetime, float]]:
    key = f"{symbol}|{timeframe}|{start_ts.isoformat()}|{end_ts.isoformat()}"
    if key in _historical_cache:
        return _historical_cache[key]

    disk_cached = _read_historical_cache(key)
    if disk_cached is not None:
        _historical_cache[key] = disk_cached
        return disk_cached

    bars = _fetch_historical_bars(symbol, timeframe, start_ts, end_ts)
    _historical_cache[key] = bars
    _write_historical_cache(key, bars)
    return bars


def _fetch_historical_bars(
    symbol: str,
    timeframe: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[tuple[datetime, float]]:
    if _api_client is None:
        raise RuntimeError("Market data client is not configured.")

    _wait_for_rate_limit(f"market_data:historical:{symbol}:{timeframe}")
    start_iso = start_ts.isoformat()
    end_iso = end_ts.isoformat()
    try:
        raw = _api_client.get_bars(
            symbol,
            timeframe,
            start=start_iso,
            end=end_iso,
            limit=10000,
            adjustment="raw",
        )
    except TypeError:
        raw = _api_client.get_bars(
            symbol,
            timeframe,
            start=start_iso,
            end=end_iso,
            limit=10000,
        )
    except Exception as exc:
        message = f"Failed historical bars for {symbol} ({timeframe}): {exc}"
        print(f"[market_data] ERROR: {message}", file=sys.stderr)
        raise RuntimeError(message) from exc

    bars = _extract_bars(raw)
    if not bars:
        print(
            f"[market_data] WARN: empty historical bars for {symbol} "
            f"({timeframe}) {start_iso} -> {end_iso}"
        )
    return bars


def _extract_bars(raw) -> list[tuple[datetime, float]]:
    bars: list[tuple[datetime, float]] = []
    df = getattr(raw, "df", None)
    if df is not None:
        try:
            iterator = df.iterrows()
            for index, row in iterator:
                ts = index[-1] if isinstance(index, tuple) else index
                parsed_ts = _coerce_datetime(ts)
                if parsed_ts is None:
                    continue
                close = None
                if hasattr(row, "get"):
                    close = row.get("close")
                    if close is None:
                        close = row.get("c")
                if close is None:
                    continue
                bars.append((parsed_ts, float(close)))
        except Exception:
            pass
        if bars:
            bars.sort(key=lambda item: item[0])
            return bars

    try:
        for bar in raw:
            ts = getattr(bar, "t", None) or getattr(bar, "timestamp", None)
            parsed_ts = _coerce_datetime(ts)
            if parsed_ts is None:
                continue
            close = getattr(bar, "c", None)
            if close is None:
                close = getattr(bar, "close", None)
            if close is None:
                continue
            bars.append((parsed_ts, float(close)))
    except TypeError:
        pass
    bars.sort(key=lambda item: item[0])
    return bars


def _coerce_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_utc(value)
    if hasattr(value, "to_pydatetime"):
        try:
            return _to_utc(value.to_pydatetime())
        except Exception:
            return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return _to_utc(dt)
    except Exception:
        return None


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _synthetic_price(symbol: str, ts: datetime) -> float:
    base_prices = {
        "PLTR": 95.0,
        "NFLX": 190.0,
        "PLTK": 18.0,
    }
    base = base_prices.get(symbol, 50.0)
    minute_bucket = int(ts.timestamp() // 60)
    intraday_wave = ((minute_bucket % 1440) / 1440.0) - 0.5
    weekly_wave = ((minute_bucket % (1440 * 5)) / (1440.0 * 5.0)) - 0.5
    price = base * (1.0 + 0.03 * intraday_wave + 0.02 * weekly_wave)
    return round(max(price, 1.0), 2)


def _cache_path_for_key(key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return _historical_cache_dir / f"{digest}.json"


def _read_historical_cache(key: str) -> list[tuple[datetime, float]] | None:
    path = _cache_path_for_key(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars: list[tuple[datetime, float]] = []
        for item in payload.get("bars", []):
            bar_ts = _coerce_datetime(item.get("t"))
            close = item.get("c")
            if bar_ts is None or close is None:
                continue
            bars.append((bar_ts, float(close)))
        bars.sort(key=lambda item: item[0])
        return bars
    except Exception:
        return None


def _write_historical_cache(key: str, bars: list[tuple[datetime, float]]) -> None:
    path = _cache_path_for_key(key)
    payload = {
        "bars": [{"t": ts.isoformat(), "c": close} for ts, close in bars],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
