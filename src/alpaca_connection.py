from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from alpaca_trade_api.rest import REST


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def check_alpaca_connection() -> REST:
    print("[alpaca] Loading .env file...")
    load_dotenv()

    print("[alpaca] Validating required environment variables...")
    api_key = _require_env("APCA_API_KEY_ID")
    api_secret = _require_env("APCA_API_SECRET_KEY")
    base_url = _require_env("APCA_API_BASE_URL")
    print(f"[alpaca] Using base URL: {base_url}")

    print("[alpaca] Initializing Alpaca REST client...")
    client = REST(
        key_id=api_key,
        secret_key=api_secret,
        base_url=base_url,
    )

    print("[alpaca] Verifying credentials with get_account()...")
    account = client.get_account()
    print(
        f"[alpaca] SUCCESS: Connected. Account status={account.status}, equity={account.equity}"
    )
    return client


def verify_or_exit() -> REST:
    try:
        return check_alpaca_connection()
    except Exception as exc:
        print(f"[alpaca] ERROR: Connection check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def run_diagnostics_or_exit(api: REST) -> None:
    try:
        print("[diag] Running dry-run diagnostics (no orders will be placed)...")

        print("[diag] Fetching open positions with list_positions()...")
        positions = api.list_positions()
        if not positions:
            print("[diag] Positions: none")
        else:
            print(f"[diag] Positions count: {len(positions)}")
            for pos in positions:
                print(
                    f"[diag] - {pos.symbol}: qty={pos.qty}, side={pos.side}, market_value={pos.market_value}"
                )

        print("[diag] Fetching market clock with get_clock()...")
        clock = api.get_clock()
        print(f"[diag] Market open: {clock.is_open}")
    except Exception as exc:
        print(f"[diag] ERROR: Diagnostics failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
