# Trading Agent Quick Run Guide

## Required environment variables

- `RUN_MODE`: `mock` or `alpaca`
- `EXECUTE`: `1` to send paper orders, `0` for dry-run decisions only
- `BACKTEST`: `1` for historical simulation mode, otherwise realtime loop
- `APCA_API_BASE_URL` (for `RUN_MODE=alpaca`): must be `https://paper-api.alpaca.markets`

### Common optional variables

- `RISK_MAX_SHARES` (default `5`)
- `SELL_COOLDOWN_MIN` (default `120`)
- `MAX_POSITION_PERCENT` (default `20`)
- `MAX_SHARES_PER_TRADE` (default `10`)
- `BUY_COOLDOWN_SECONDS` (default `60`)

## Backtest mode

Run a finite historical simulation:

```bash
RUN_MODE=alpaca BACKTEST=1 BACKTEST_START=2025-11-03 BACKTEST_DAYS=5 BACKTEST_STEP_MIN=60 python -m src.agent_trader
```

Backtest notes:

- No Alpaca orders are submitted.
- Logs use `[backtest]` and `[backtest][executor]`.
- Summary prints with `[backtest][summary]`.

## Paper trading mode (Alpaca)

Dry-run (decision-only, no paper orders):

```bash
RUN_MODE=alpaca EXECUTE=0 BACKTEST=0 python -m src.agent_trader
```

Active paper orders:

```bash
RUN_MODE=alpaca EXECUTE=1 BACKTEST=0 python -m src.agent_trader
```

Paper mode notes:

- Uses Alpaca paper endpoint (`https://paper-api.alpaca.markets` via your env config).
- With `EXECUTE=0`, the app logs a warning that Alpaca portfolio will not change.
- Per tick, portfolio dashboard is printed and appended to:
  - `runs/portfolio_timeseries.csv`
