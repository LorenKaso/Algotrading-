from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import Callable

from src.alpaca_connection import run_diagnostics_or_exit, verify_or_exit
from src.backtest_runner import run_backtest
from src.broker_factory import make_broker
from src.crewai_models import DecisionModel, MarketSnapshotModel, RiskResult
from src.decision_types import Decision, TradeAction
import src.market_data as market_data
from src.market_snapshot import MarketSnapshot
from src.portfolio_reporter import report_portfolio_tick
from src.portfolio import reset_portfolio_state
from src.rate_limiter import RateLimiter
from src.trade_executor import configure_trade_executor, execute_action
from src.trading_crew import build_trading_crew

try:
    from crewai.flow.flow import Flow, listen, start
except Exception:  # pragma: no cover - exercised in environments without crewai

    class Flow:  # type: ignore[no-redef]
        pass

    def start():
        def decorator(func):
            return func

        return decorator

    def listen(_source):
        def decorator(func):
            return func

        return decorator


class TradingFlow(Flow):
    SYMBOLS = ["PLTR", "NFLX", "PLTK"]

    def __init__(
        self,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        try:
            super().__init__()
        except Exception:
            pass
        self.max_iterations = max_iterations
        self._sleep = sleep_fn or time.sleep
        self._stop_requested = False

        self.run_mode = "mock"
        self.diag_mode = False
        self.execute_mode = False
        self.loop_interval_seconds = 5.0
        self.backtest_mode = False
        self.market_is_open: bool | None = None
        self.backtest_start: date | None = None
        self.backtest_days = 5
        self.backtest_step_min = 60
        self.backtest_initial_cash = 100000.0
        self.backtest_report: dict | None = None

        self.broker = None
        self.api_client = None
        self.rate_limiter: RateLimiter | None = None
        self.crew = None
        self.iteration = 0
        self.last_decision: Decision | None = None
        self.last_snapshot: MarketSnapshot | None = None

    def stop(self) -> None:
        self._stop_requested = True

    def kickoff(self) -> None:
        signal = self.initialize()
        _ = self.run_iteration(signal)

    @start()
    def initialize(self) -> str:
        self.run_mode = os.getenv("RUN_MODE", "mock").strip().lower() or "mock"
        self.diag_mode = os.getenv("DIAG", "").strip() == "1"
        self.execute_mode = os.getenv("EXECUTE", "").strip() == "1"
        self.backtest_mode = os.getenv("BACKTEST", "").strip() == "1"
        loop_raw = os.getenv(
            "LOOP_INTERVAL_SEC", os.getenv("LOOP_INTERVAL_SECONDS", "5")
        )
        try:
            self.loop_interval_seconds = float(loop_raw)
        except ValueError:
            self.loop_interval_seconds = 5.0
        if self.loop_interval_seconds < 0:
            self.loop_interval_seconds = 0.0
        if self.backtest_mode:
            self.backtest_start = self._parse_backtest_start()
            self.backtest_days = self._read_int_env(
                "BACKTEST_DAYS", default=5, minimum=1
            )
            self.backtest_step_min = self._read_int_env(
                "BACKTEST_STEP_MIN", default=60, minimum=1
            )
            self.backtest_initial_cash = self._read_float_env(
                "BACKTEST_INITIAL_CASH", default=100000.0, minimum=0.0
            )

        print(f"[startup] RUN_MODE={self.run_mode}")
        print(
            f"[startup] EXECUTE={'1' if self.execute_mode else '0'} "
            "(1 means real paper orders enabled)"
        )
        if self.backtest_mode:
            print(
                "[backtest] ENABLED start=%s days=%d step_min=%d initial_cash=%.2f"
                % (
                    self.backtest_start.isoformat() if self.backtest_start else "unset",
                    self.backtest_days,
                    self.backtest_step_min,
                    self.backtest_initial_cash,
                )
            )
            if self.execute_mode:
                print(
                    "[backtest] EXECUTE is ignored in backtest mode; no broker orders will be sent."
                )

        self.broker = make_broker()
        self.rate_limiter = RateLimiter(per_second=3, per_hour=1000, per_day=5000)
        reset_portfolio_state()
        configure_trade_executor(self.rate_limiter)

        self.api_client = None
        if self.run_mode == "alpaca":
            base_url = os.getenv("APCA_API_BASE_URL", "").strip()
            if "paper-api.alpaca.markets" not in base_url:
                raise ValueError(
                    "RUN_MODE=alpaca requires APCA_API_BASE_URL to point to Alpaca paper "
                    "(https://paper-api.alpaca.markets)."
                )
            print("[startup] Running Alpaca connection check...")
            self.api_client = verify_or_exit()
            market_data.configure_api_client(
                self.api_client, rate_limiter=self.rate_limiter, cache_ttl_seconds=5.0
            )
            if not self.execute_mode:
                print(
                    "[startup] WARNING: EXECUTE=0 in RUN_MODE=alpaca; "
                    "no paper orders will be sent. Alpaca paper portfolio "
                    "will not change."
                )
            if self.diag_mode:
                run_diagnostics_or_exit(self.api_client)
                print("[startup] DIAG=1 complete. Exiting before trading loop.")
                self.stop()
                return "diag-complete"
        elif self.diag_mode:
            print(
                "[startup] DIAG=1 is only applicable in RUN_MODE=alpaca. Exiting cleanly."
            )
            self.stop()
            return "diag-complete"

        self.market_is_open = self._read_market_open_state()
        if self.market_is_open is False:
            print("[startup] US market closed, no live ticks/fills expected now")
        elif self.market_is_open is True:
            print("[startup] US market open")
        else:
            print(
                "[startup] Market status unknown; RiskAgent will use snapshot timestamp fallback"
            )
        self.crew = build_trading_crew(
            llm=None,
            symbols=self.SYMBOLS,
            allowlist=set(self.SYMBOLS),
            market_is_open=self.market_is_open,
            run_mode=self.run_mode,
        )
        self.iteration = 0
        self.last_decision = None
        self.last_snapshot = None
        print("[startup] Trading flow initialized.")
        return "ready"

    @listen(initialize)
    def run_iteration(self, _signal: str) -> str:
        if self.backtest_mode:
            assert self.backtest_start is not None
            assert self.broker is not None
            assert self.crew is not None
            self.backtest_report = run_backtest(
                broker=self.broker,
                market_data=market_data,
                crew=self.crew,
                symbols=self.SYMBOLS,
                start_date=self.backtest_start,
                days=self.backtest_days,
                step_min=self.backtest_step_min,
                initial_cash=self.backtest_initial_cash,
            )
            self.stop()
            return "backtest-complete"

        while not self._stop_requested:
            try:
                self.iteration += 1
                print(f"[startup] Iteration {self.iteration} started")
                snapshot = self._build_snapshot()
                self.last_snapshot = snapshot
                for symbol, price in snapshot.prices.items():
                    print(f"[data] {symbol} latest={price}")

                snapshot_payload = MarketSnapshotModel(
                    timestamp=snapshot.timestamp.isoformat(),
                    prices=snapshot.prices,
                    cash=snapshot.cash,
                    positions=snapshot.positions,
                    avg_entry_prices=snapshot.avg_entry_prices,
                ).model_dump()

                assert self.crew is not None
                print(
                    "[crew] kickoff inputs=snapshot(ts=%s, prices=%s, cash=%.2f, positions=%s)"
                    % (
                        snapshot.timestamp.isoformat(),
                        snapshot.prices,
                        snapshot.cash,
                        snapshot.positions,
                    )
                )
                self.crew.kickoff(
                    inputs={
                        "snapshot": snapshot_payload,
                        "symbols": self.SYMBOLS,
                        "market_is_open": self.market_is_open,
                    }
                )
                market_model = self._decision_from_task(
                    0, fallback_reason="market output missing"
                )
                market_model = self._sanitize_decision_symbol(market_model)
                valuation_model = self._decision_from_task(
                    1, fallback_reason="valuation output missing"
                )
                valuation_model = self._sanitize_decision_symbol(valuation_model)
                risk_model = self._risk_from_task(
                    2, fallback_reason="risk output missing"
                )
                final_model = self._final_decision_from_tasks()
                final_model = self._sanitize_decision_symbol(final_model)
                decision = self._to_decision(final_model)
                self.last_decision = decision
                print(
                    f"[agent][market] {market_model.action} "
                    f"{market_model.symbol} ({market_model.reason})"
                )
                print(
                    f"[agent][valuation] {valuation_model.action} "
                    f"{valuation_model.symbol} ({valuation_model.reason})"
                )
                print(f"[agent][risk] {risk_model.status}: {risk_model.reason}")
                print(
                    f"[agent][coord] final={decision.action.value} {decision.symbol} "
                    f"confidence={decision.confidence:.2f} "
                    f"({decision.reason}) "
                    f"(risk={risk_model.status}:{risk_model.reason})"
                )
                if (
                    risk_model.status == "VETO"
                    and "market closed" in risk_model.reason.lower()
                ):
                    print(
                        "[startup] US market closed,"
                        " no live ticks/fills expected now"
                    )
                print(
                    f"[crew] completed final_decision={decision.action.value} "
                    f"{decision.symbol} ({decision.reason})"
                )
                execute_action(self.api_client, snapshot, decision)
                portfolio_value, portfolio_cash, portfolio_positions = (
                    self._emit_portfolio_dashboard(
                        timestamp=snapshot.timestamp,
                        fallback_prices=snapshot.prices,
                    )
                )
                print(
                    "[startup] Portfolio value=%.2f, cash=%.2f, positions=%s"
                    % (portfolio_value, portfolio_cash, portfolio_positions)
                )
            except Exception as exc:
                print(f"[error] Loop iteration failed: {exc}")

            if (
                self.max_iterations is not None
                and self.iteration >= self.max_iterations
            ):
                self.stop()
                break
            if not self._stop_requested:
                self._sleep(self.loop_interval_seconds)
        return "stopped"

    def _build_snapshot(self) -> MarketSnapshot:
        assert self.broker is not None
        self._wait_for_rate_limit("broker:get_cash")
        cash = float(self.broker.get_cash())
        self._wait_for_rate_limit("broker:get_positions")
        positions = self.broker.get_positions()
        avg_entry_prices = self._get_avg_entry_prices()
        price_fetcher = (
            market_data.get_latest_price
            if self.api_client is not None
            else self.broker.get_price
        )
        prices: dict[str, float] = {}
        for symbol in self.SYMBOLS:
            self._wait_for_rate_limit(f"price:{symbol}")
            prices[symbol] = float(price_fetcher(symbol))
        return MarketSnapshot(
            timestamp=datetime.now(tz=timezone.utc),
            prices=prices,
            cash=cash,
            positions=positions,
            avg_entry_prices=avg_entry_prices,
        )

    def _final_decision_from_tasks(self) -> DecisionModel:
        return self._decision_from_task(
            task_index=-1, fallback_reason="coord output missing"
        )

    def _risk_from_task(self, task_index: int, fallback_reason: str) -> RiskResult:
        assert self.crew is not None
        tasks = list(getattr(self.crew, "tasks", []))
        if not tasks:
            return RiskResult(status="VETO", reason=fallback_reason)
        selected_task = tasks[task_index]
        output = getattr(selected_task, "output", None)
        if output is None:
            return RiskResult(status="VETO", reason=fallback_reason)
        pydantic_out = getattr(output, "pydantic", None)
        if pydantic_out is not None:
            return RiskResult.model_validate(pydantic_out.model_dump())
        json_out = getattr(output, "json_dict", None)
        if json_out is not None:
            return RiskResult.model_validate(json_out)
        return RiskResult(status="VETO", reason=fallback_reason)

    def _decision_from_task(
        self, task_index: int, fallback_reason: str
    ) -> DecisionModel:
        assert self.crew is not None
        tasks = list(getattr(self.crew, "tasks", []))
        if not tasks:
            return DecisionModel(action="HOLD", symbol=None, reason=fallback_reason)
        selected_task = tasks[task_index]
        output = getattr(selected_task, "output", None)
        if output is None:
            return DecisionModel(action="HOLD", symbol=None, reason=fallback_reason)
        pydantic_out = getattr(output, "pydantic", None)
        if pydantic_out is not None:
            return DecisionModel.model_validate(pydantic_out.model_dump())
        json_out = getattr(output, "json_dict", None)
        if json_out is not None:
            return DecisionModel.model_validate(json_out)
        return DecisionModel(action="HOLD", symbol=None, reason=fallback_reason)

    @staticmethod
    def _to_decision(model: DecisionModel) -> Decision:
        action = TradeAction(model.action)
        qty = 1 if action in {TradeAction.BUY, TradeAction.SELL} else 0
        return Decision(
            action=action,
            symbol=model.symbol,
            qty=qty,
            reason=model.reason,
            confidence=model.confidence,
        )

    def _sanitize_decision_symbol(self, model: DecisionModel) -> DecisionModel:
        symbol = model.symbol
        if symbol is None:
            return model
        symbol_upper = symbol.upper()
        if symbol_upper in self.SYMBOLS:
            if symbol == symbol_upper:
                return model
            return DecisionModel(
                action=model.action,
                symbol=symbol_upper,
                reason=model.reason,
                confidence=model.confidence,
            )
        allowed = ",".join(self.SYMBOLS)
        return DecisionModel(
            action="HOLD",
            symbol=None,
            reason=(
                f"invalid symbol returned by agent: {symbol}; " f"allowed={allowed}"
            ),
            confidence=model.confidence,
        )

    def _read_market_open_state(self) -> bool | None:
        assert self.broker is not None
        checker = getattr(self.broker, "is_market_open", None)
        if checker is None:
            return None
        try:
            return bool(checker())
        except Exception:
            return None

    def _emit_portfolio_dashboard(
        self,
        timestamp: datetime,
        fallback_prices: dict[str, float],
    ) -> tuple[float, float, dict[str, int]]:
        assert self.broker is not None
        self._wait_for_rate_limit("broker:get_cash:dashboard")
        cash = float(self.broker.get_cash())
        self._wait_for_rate_limit("broker:get_positions:dashboard")
        positions = self.broker.get_positions()
        avg_entry_prices = self._get_avg_entry_prices()
        prices = dict(fallback_prices)
        for symbol, qty in positions.items():
            if qty <= 0:
                continue
            if symbol in prices and prices[symbol] > 0:
                continue
            try:
                self._wait_for_rate_limit(f"price:dashboard:{symbol}")
                if self.api_client is not None:
                    prices[symbol] = float(market_data.get_latest_price(symbol))
                else:
                    prices[symbol] = float(self.broker.get_price(symbol))
            except Exception:
                prices[symbol] = 0.0
        report_portfolio_tick(
            timestamp=timestamp,
            cash=cash,
            positions=positions,
            avg_entry_prices=avg_entry_prices,
            prices=prices,
        )
        equity = cash + sum(
            positions.get(symbol, 0) * prices.get(symbol, 0.0) for symbol in positions
        )
        return equity, cash, positions

    def _wait_for_rate_limit(self, key: str) -> None:
        if self.rate_limiter is None:
            return
        while not self.rate_limiter.allow(key):
            print(f"[data] Rate limit reached for {key}; sleeping 0.2s")
            time.sleep(0.2)

    def _get_avg_entry_prices(self) -> dict[str, float]:
        assert self.broker is not None
        getter = getattr(self.broker, "get_avg_entry_prices", None)
        if getter is None:
            return {}
        self._wait_for_rate_limit("broker:get_avg_entry_prices")
        try:
            values = getter()
            return {
                str(symbol).upper(): float(price) for symbol, price in values.items()
            }
        except Exception:
            return {}

    def _parse_backtest_start(self) -> date:
        raw = os.getenv("BACKTEST_START", "").strip()
        if not raw:
            raise ValueError(
                "BACKTEST_START is required when BACKTEST=1 " "(format YYYY-MM-DD)"
            )
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid BACKTEST_START '{raw}', expected YYYY-MM-DD"
            ) from exc

    @staticmethod
    def _read_int_env(name: str, default: int, minimum: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            value = default
        return max(minimum, value)

    @staticmethod
    def _read_float_env(name: str, default: float, minimum: float) -> float:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = float(raw)
        except ValueError:
            value = default
        return max(minimum, value)
