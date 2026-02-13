from __future__ import annotations

import logging
import os

from src.trading_flow import TradingFlow

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_mode = os.getenv("RUN_MODE", "mock").strip().lower() or "mock"
    print(f"[startup] RUN_MODE={run_mode}")
    print("[startup] Starting TradingFlow...")

    flow = TradingFlow()
    try:
        flow.kickoff()
    except KeyboardInterrupt:
        print("[startup] Keyboard interrupt received. Stopping flow cleanly...")
        flow.stop()
    finally:
        print("[startup] Agent trader stopped.")


if __name__ == "__main__":
    main()
