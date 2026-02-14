📈 CrewAI Multi-Agent Trading (Alpaca Paper Only)
paper Trading Only
This project uses Alpaca Paper Trading (no live trading).
Required:

APCA_API_BASE_URL=https://paper-api.alpaca.markets


On startup, connection is verified using get_account().

Successful connection prints:

[alpaca] SUCCESS: Connected. Account status=ACTIVE, equity=100000

🛡 Safety Mechanism
Variable	Behavior
EXECUTE=0	Decisions only (NO paper orders sent)
EXECUTE=1	Orders sent to Alpaca paper account

Recommended default:

EXECUTE=0

🔧 Required Environment Variables
RUN_MODE=alpaca
EXECUTE=0 | 1
BACKTEST=0 | 1
LLM_MODE=real
APCA_API_BASE_URL=https://paper-api.alpaca.markets

▶️ Run – Safe Mode (No Orders)
LLM_MODE=real RUN_MODE=alpaca EXECUTE=0 BACKTEST=0 python -m src.agent_trader

Agents decide, but no trades are sent.

▶️ Run – Paper Orders Enabled
LLM_MODE=real RUN_MODE=alpaca EXECUTE=1 BACKTEST=0 python -m src.agent_trader

Orders are sent to Alpaca paper account only.

🧪 Backtest Mode
RUN_MODE=alpaca BACKTEST=1 BACKTEST_START=2025-11-03 BACKTEST_DAYS=5 BACKTEST_STEP_MIN=60 python -m src.agent_trader

No orders are submitted during backtest.

🧠 CrewAI (Open Source)

The system runs 4 coordinated agents:
Market
Valuation
Risk
Coordinator

Snapshot + symbols + market status are passed to CrewAI.
Risk agent may veto.
Coordinator produces final decision.

🧪 Run Tests
pytest -q