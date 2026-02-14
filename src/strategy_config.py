from __future__ import annotations

import os

TAKE_PROFIT_PCT = 0.05
STOP_LOSS_PCT = -0.03
SELL_COOLDOWN_MIN = 120
RISK_MAX_SHARES = 5


def get_risk_max_shares() -> int:
    raw = os.getenv("RISK_MAX_SHARES", str(RISK_MAX_SHARES)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = RISK_MAX_SHARES
    return max(1, value)


def get_sell_cooldown_min() -> int:
    raw = os.getenv("SELL_COOLDOWN_MIN", str(SELL_COOLDOWN_MIN)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = SELL_COOLDOWN_MIN
    return max(0, value)
