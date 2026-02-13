from __future__ import annotations

import os

from src.alpaca_broker import AlpacaBroker
from src.broker import Broker
from src.mock_broker import MockBroker


def make_broker() -> Broker:
    run_mode = os.getenv("RUN_MODE", "mock").strip().lower()
    if run_mode != "alpaca":
        return MockBroker()

    try:
        return AlpacaBroker()
    except Exception:
        return MockBroker()
