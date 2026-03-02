from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from core.candle_buffer import CandleBuffer
from core.config import TradingConfig
from core.interfaces import Broker
from core.order_state import OrderRecord, OrderStatus
from core.price_rules import krw_tick_size, round_down_to_tick
from core.position_policy import PositionExitState, PositionOrderPolicy
from core.portfolio import normalize_accounts
from core.reconciliation import apply_my_asset_event, apply_my_order_event
from core.risk import RiskManager
from core.strategy import (
    StrategyParams,
    check_buy,
    check_sell,
    classify_market_regime,
    evaluate_long_entry,
    preprocess_candles,
    regime_filter_diagnostics,
)
from core.universe import UniverseBuilder
from infra.upbit_ws_client import UpbitWebSocketClient
from message.notifier import Notifier, format_entry_summary, format_exit_summary


class TradingEngine:
    def __init__(
        self,
        broker: Broker,
        notifier: Notifier,
        config: TradingConfig,
        ws_client: UpbitWebSocketClient | None = None,
    ):
        self.broker = broker
        self.notifier = notifier
        self.config = config
        self.ws_client = ws_client
        self._order_sequence = 0
        self.orders_by_identifier: dict[str, OrderRecord] = {}
        self.order_identifier_parent: dict[str, str] = {}
        self.order_last_timeout_action_at: dict[str, datetime] = {}
        self.portfolio_snapshot: dict[str, dict[str, float]] = {}
        self.order_timeout_seconds = 120
        self.max_order_retries = max(0, int(config.max_order_retries))
        self.timeout_retry_cooldown_seconds = max(0.0, float(config.timeout_retry_cooldown_seconds))
        self.partial_fill_timeout_scale = max(0.1, float(config.partial_fill_timeout_scale))
        self.partial_fill_reduce_ratio = min(1.0, max(0.1, float(config.partial_fill_reduce_ratio)))
        self.universe = UniverseBuilder(config)
        self.candle_buffer = CandleBuffer(maxlen_by_interval={1: 300, 5: 300, 15: 300, config.candle_interval: 300})
        self.last_universe_selection_result = None
        self.risk = RiskManager(
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_daily_loss_pct=config.max_daily_loss_pct,
            max_consecutive_losses=config.max_consecutive_losses,
            max_concurrent_positions=config.max_concurrent_positions,
            max_correlated_positions=config.max_correlated_positions,
            correlation_groups=config.correlation_groups,
            min_order_krw=config.min_order_krw,
            quality_multiplier_min_bound=config.quality_multiplier_min_bound,
            quality_multiplier_max_bound=config.quality_multiplier_max_bound,
        )
        self.order_policy = PositionOrderPolicy(
            stop_loss_threshold=config.stop_loss_threshold,
            trailing_stop_pct=config.trailing_stop_pct,
            partial_take_profit_threshold=config.partial_take_profit_threshold,
            partial_take_profit_ratio=config.partial_take_profit_ratio,
            partial_stop_loss_ratio=config.partial_stop_loss_ratio,
            exit_mode=config.exit_mode,
            atr_period=config.atr_period,
            atr_stop_mult=config.atr_stop_mult,
            atr_trailing_mult=config.atr_trailing_mult,
            swing_lookback=config.swing_lookback,
        )
        self._position_exit_states: dict[str, PositionExitState] = {}
        self._entry_tracking_by_market: dict[str, dict[str, float | str | datetime]] = {}
        self._entry_strategy_params_by_market: dict[str, StrategyParams] = {}
        self._last_processed_candle_at: dict[str, datetime] = {}
        self._last_exit_snapshot_by_market: dict[str, dict[str, datetime | str]] = {}
        self._last_strategy_exit_snapshot_by_market: dict[str, dict[str, datetime | str]] = {}
        self.debug_counters: dict[str, int] = {
            "fail_reentry_cooldown": 0,
            "fail_strategy_cooldown": 0,
        }
        self._recent_trade_reasons: list[str] = []
        self._trade_reason_log_path = Path("logs/recent_trade_reasons.txt")

        if self.ws_client:
            self.ws_client.on_message = self._route_ws_message

    def start(self) -> None:
        if not self.ws_client:
            return

        self.initialize_markets()
        self.bootstrap_open_orders()
        self.ws_client.connect()
        self.ws_client.subscribe("ticker", self.config.krw_markets, data_format=self.config.ws_data_format)

        if self._should_subscribe_private_channels():
            self.ws_client.subscribe("myOrder", data_format=self.config.ws_data_format, is_private=True)
            self.ws_client.subscribe("myAsset", data_format=self.config.ws_data_format, is_private=True)

    def shutdown(self) -> None:
        if self.ws_client:
            self.ws_client.close()

    def initialize_markets(self) -> None:
        if self.config.krw_markets:
            return

        markets = self.broker.get_markets()
        self.config.krw_markets = self.universe.collect_krw_markets(markets)

    def _print_runtime_status(self, *, stage: str, portfolio=None) -> None:
        if portfolio is None:
            print(f"[STATUS] stage={stage}")
            return

        print(
            "[STATUS]"
            f" stage={stage}"
            f" available_krw={int(portfolio.available_krw)}"
            f" total_equity_krw={int(portfolio.total_equity_krw)}"
            f" holdings={len(portfolio.held_markets)}/{self.config.max_holdings}"
            f" markets={portfolio.held_markets}"
        )

    def run_once(self) -> None:
        self._print_runtime_status(stage="initializing")
        self.initialize_markets()
        self._print_runtime_status(stage="reconciling_orders")
        self.reconcile_orders()
        strategy_params = self.config.to_strategy_params()

        accounts = self.broker.get_accounts()
        portfolio = normalize_accounts(accounts, self.config.do_not_trading)
        self.risk.set_baseline_equity(portfolio.total_equity_krw)
        self._print_runtime_status(stage="evaluating_positions", portfolio=portfolio)

        for account in portfolio.my_coins:
            market = "KRW-" + account["currency"]
            data = self._get_strategy_candles(market)
            if not self._should_run_strategy(market, data):
                continue
            avg_buy_price = float(account["avg_buy_price"])
            if avg_buy_price <= 0:
                continue
            current_price = float(data["1m"][0]["trade_price"])

            effective_strategy_params = self._entry_strategy_params_by_market.get(market, strategy_params)
            decision = self._should_exit_position(market, data, avg_buy_price, current_price, effective_strategy_params)
            if decision.should_exit:
                held_volume = float(account["balance"])
                requested_volume = held_volume * decision.qty_ratio
                if requested_volume <= 0:
                    continue
                preflight = self._preflight_order(
                    market=market,
                    side="ask",
                    requested_value=requested_volume,
                    reference_price=current_price,
                )
                if not preflight["ok"]:
                    self._notify_preflight_failure(preflight)
                    continue
                identifier = self._next_order_identifier(market, "ask")
                response = self.broker.sell_market(market, preflight["order_value"], identifier=identifier)
                self._record_accepted_order(response, identifier, market, "ask", preflight["order_value"])
                print("SELL_ACCEPTED", market, str(account["balance"]) + account["currency"], current_price)
                delta = ((current_price - avg_buy_price) / avg_buy_price) * 100
                self.risk.record_trade_result((current_price - avg_buy_price) * requested_volume)
                self._log_exit_diagnostics(
                    market=market,
                    decision=decision,
                    avg_buy_price=avg_buy_price,
                    current_price=current_price,
                    sold_volume=preflight["order_value"],
                )
                if decision.qty_ratio >= 1.0:
                    self._reset_position_exit_state(market)
                    latest_candle = data.get("1m", [{}])[0]
                    exit_time = self.candle_buffer.parse_candle_time(latest_candle) or datetime.now(timezone.utc)
                    exit_time = self._to_utc_aware(exit_time)
                    self._last_exit_snapshot_by_market[market] = {"time": exit_time, "reason": decision.reason}
                    if decision.reason == "strategy_signal":
                        self._last_strategy_exit_snapshot_by_market[market] = {
                            "time": exit_time,
                            "reason": decision.reason,
                        }
                self.notifier.send(
                    format_exit_summary(
                        market=market,
                        exit_price=current_price,
                        reason=decision.reason,
                        realized_r=self._compute_realized_r(market=market, current_price=current_price, avg_buy_price=avg_buy_price),
                        daily_pnl_krw=self._daily_realized_pnl_krw(),
                    )
                )
                self._append_trade_reason(
                    side="SELL",
                    market=market,
                    reason=str(decision.reason),
                    price=current_price,
                    qty=preflight["order_value"],
                    notional_krw=preflight.get("notional"),
                    qty_ratio=decision.qty_ratio,
                    diagnostics=decision.diagnostics,
                )

        self._print_runtime_status(stage="evaluating_entries", portfolio=portfolio)
        self._try_buy(portfolio.available_krw, portfolio.held_markets, strategy_params)
        self._print_runtime_status(stage="cycle_complete", portfolio=portfolio)

    def _try_buy(self, available_krw: float, held_markets: list[str], strategy_params) -> None:
        if available_krw < self.config.min_effective_buyable_krw:
            return

        tickers = self.broker.get_ticker(", ".join(self.config.krw_markets))
        ticker_by_market = {str(ticker.get("market")): ticker for ticker in tickers if ticker.get("market")}
        top_and_spread_result = self.universe.select_watch_markets_with_report(tickers)
        candles_by_market = {market: self._get_strategy_candles(market) for market in top_and_spread_result.watch_markets}
        universe_result = self.universe.select_watch_markets_with_report(
            tickers,
            candles_by_market={market: candles["1m"] for market, candles in candles_by_market.items()},
        )
        watch_markets = universe_result.watch_markets
        self.last_universe_selection_result = universe_result

        for market in watch_markets:
            if market in held_markets:
                continue

            data = candles_by_market[market]
            regime = classify_market_regime(data.get("15m", []), strategy_params)
            effective_strategy_params = self._resolve_strategy_params_for_regime(strategy_params, regime)
            regime_diag = regime_filter_diagnostics(data.get("15m", []), effective_strategy_params)
            if not self._should_run_strategy(market, data):
                continue
            latest_candle = data.get("1m", [{}])[0]
            latest_time = self.candle_buffer.parse_candle_time(latest_candle) or datetime.now(timezone.utc)
            latest_time = self._to_utc_aware(latest_time)
            if self._is_reentry_cooldown_active(market, latest_time):
                self.debug_counters["fail_reentry_cooldown"] = self.debug_counters.get("fail_reentry_cooldown", 0) + 1
                continue

            strategy_entry_result = None
            if str(effective_strategy_params.strategy_name).lower().strip() == "rsi_bb_reversal_long":
                strategy_entry_result = evaluate_long_entry(data, effective_strategy_params)
                if not strategy_entry_result.final_pass:
                    continue
            elif not check_buy(data, effective_strategy_params):
                continue

            if self._is_strategy_cooldown_active(market, latest_time, effective_strategy_params):
                self.debug_counters["fail_strategy_cooldown"] = self.debug_counters.get("fail_strategy_cooldown", 0) + 1
                continue

            reference_price = float(data["1m"][0]["trade_price"])
            stop_price = reference_price * self.config.stop_loss_threshold
            strategy_entry_price = reference_price
            strategy_risk_per_unit = max(reference_price - stop_price, 0.0)
            if strategy_entry_result is not None:
                diagnostics = strategy_entry_result.diagnostics if isinstance(strategy_entry_result.diagnostics, dict) else {}
                strategy_entry_price = float(diagnostics.get("entry_price", strategy_entry_price) or strategy_entry_price)
                stop_price = float(diagnostics.get("stop_price", stop_price) or stop_price)
                strategy_risk_per_unit = max(float(diagnostics.get("r_value", strategy_risk_per_unit) or strategy_risk_per_unit), 0.0)

            risk_sized_order_krw = self.risk.compute_risk_sized_order_krw(
                available_krw=available_krw,
                entry_price=strategy_entry_price,
                stop_price=stop_price,
            )
            if risk_sized_order_krw <= 0:
                continue

            cash_split_divisor = max(1, int(self.config.max_holdings))
            cash_split_order_krw = (available_krw / cash_split_divisor) * (1 - self.config.fee_rate)
            hard_cash_limit_krw = available_krw * (1 - self.config.fee_rate)
            configured_cash_management_cap_krw = float(self.config.max_order_krw_by_cash_management)
            if configured_cash_management_cap_krw <= 0:
                configured_cash_management_cap_krw = cash_split_order_krw

            if self.config.position_sizing_mode == "cash_split_first":
                cash_cap_order_krw = min(cash_split_order_krw, hard_cash_limit_krw)
                if self.config.max_order_krw_by_cash_management > 0:
                    cash_cap_order_krw = min(cash_cap_order_krw, float(self.config.max_order_krw_by_cash_management))
            else:
                cash_cap_order_krw = min(hard_cash_limit_krw, configured_cash_management_cap_krw)

            base_order_krw = min(risk_sized_order_krw, cash_cap_order_krw)
            diagnostics = strategy_entry_result.diagnostics if strategy_entry_result is not None and isinstance(strategy_entry_result.diagnostics, dict) else {}
            quality_score = float(diagnostics.get("quality_score", 0.0) or 0.0)
            if quality_score >= float(self.config.quality_score_high_threshold):
                quality_bucket = "high"
                raw_quality_multiplier = float(self.config.quality_multiplier_high)
            elif quality_score >= float(self.config.quality_score_low_threshold):
                quality_bucket = "mid"
                raw_quality_multiplier = float(self.config.quality_multiplier_mid)
            else:
                quality_bucket = "low"
                raw_quality_multiplier = float(self.config.quality_multiplier_low)
            quality_multiplier = self.risk.clamp_quality_multiplier(raw_quality_multiplier)
            final_order_krw = base_order_krw * quality_multiplier
            damping_log = None
            if self.config.market_damping_enabled:
                liquidity_factor, volatility_factor, damping_reasons = self._compute_market_damping_factors(
                    ticker=ticker_by_market.get(market, {}),
                    candles_1m=data.get("1m", []),
                )
                damping_factor = min(liquidity_factor, volatility_factor)
                final_order_krw = base_order_krw * quality_multiplier * damping_factor
                damping_log = {
                    "liquidity_factor": liquidity_factor,
                    "volatility_factor": volatility_factor,
                    "damping_factor": damping_factor,
                    "reasons": damping_reasons,
                }

            if len(held_markets) >= self.config.max_holdings:
                print(
                    "BUY_SIZING_SKIPPED",
                    market,
                    "reason=max_holdings",
                    f"risk_sized_order_krw={int(risk_sized_order_krw)}",
                    f"cash_cap_order_krw={int(cash_cap_order_krw)}",
                    f"final_order_krw={int(final_order_krw)}",
                    f"quality_score={quality_score:.3f}",
                    f"quality_bucket={quality_bucket}",
                    f"quality_multiplier={quality_multiplier:.2f}",
                )
                continue

            risk_decision = self.risk.allow_entry(
                available_krw=available_krw,
                held_markets=held_markets,
                candidate_market=market,
            )
            if not risk_decision.allowed:
                print(
                    "BUY_SIZING_SKIPPED",
                    market,
                    f"reason={risk_decision.reason}",
                    f"risk_sized_order_krw={int(risk_sized_order_krw)}",
                    f"cash_cap_order_krw={int(cash_cap_order_krw)}",
                    f"final_order_krw={int(final_order_krw)}",
                    f"quality_score={quality_score:.3f}",
                    f"quality_bucket={quality_bucket}",
                    f"quality_multiplier={quality_multiplier:.2f}",
                )
                continue

            if final_order_krw < self.config.min_order_krw:
                print(
                    "BUY_SIZING_SKIPPED",
                    market,
                    "reason=min_order_krw",
                    f"risk_sized_order_krw={int(risk_sized_order_krw)}",
                    f"cash_cap_order_krw={int(cash_cap_order_krw)}",
                    f"final_order_krw={int(final_order_krw)}",
                    f"quality_score={quality_score:.3f}",
                    f"quality_bucket={quality_bucket}",
                    f"quality_multiplier={quality_multiplier:.2f}",
                )
                continue
            residual_slots_after_buy = max(int(self.config.max_holdings) - (len(held_markets) + 1), 0)
            if residual_slots_after_buy > 0 and available_krw - final_order_krw < self.config.min_order_krw:
                print(
                    "BUY_SIZING_SKIPPED",
                    market,
                    "reason=insufficient_residual_cash",
                    f"risk_sized_order_krw={int(risk_sized_order_krw)}",
                    f"cash_cap_order_krw={int(cash_cap_order_krw)}",
                    f"final_order_krw={int(final_order_krw)}",
                    f"quality_score={quality_score:.3f}",
                    f"quality_bucket={quality_bucket}",
                    f"quality_multiplier={quality_multiplier:.2f}",
                )
                continue

            preflight = self._preflight_order(
                market=market,
                side="bid",
                requested_value=final_order_krw,
                reference_price=reference_price,
            )
            if not preflight["ok"]:
                self._notify_preflight_failure(preflight)
                continue

            if damping_log is not None and damping_log["damping_factor"] < 1.0:
                print(
                    "BUY_DAMPING_APPLIED",
                    market,
                    f"base_order_krw={int(base_order_krw)}",
                    f"liquidity_factor={damping_log['liquidity_factor']:.4f}",
                    f"volatility_factor={damping_log['volatility_factor']:.4f}",
                    f"damping_factor={damping_log['damping_factor']:.4f}",
                    f"final_order_krw={int(final_order_krw)}",
                    f"reasons={','.join(damping_log['reasons']) if damping_log['reasons'] else 'none'}",
                )

            identifier = self._next_order_identifier(market, "bid")
            response = self.broker.buy_market(market, preflight["order_value"], identifier=identifier)
            self._record_accepted_order(response, identifier, market, "bid", preflight["order_value"])
            entry_atr = self._latest_atr(data["1m"], self.config.atr_period)
            entry_swing_low = self._latest_swing_low(data["1m"], self.config.swing_lookback)
            self._position_exit_states[market] = PositionExitState(
                peak_price=reference_price,
                entry_atr=entry_atr,
                entry_swing_low=entry_swing_low,
                entry_price=strategy_entry_price,
                initial_stop_price=stop_price,
                risk_per_unit=strategy_risk_per_unit,
                entry_regime=regime,
            )
            self._entry_tracking_by_market[market] = {
                "entry_time": latest_time,
                "entry_price": strategy_entry_price,
                "risk_per_unit": strategy_risk_per_unit,
                "entry_score": float(diagnostics.get("entry_score", 0.0) or 0.0),
                "quality_score": quality_score,
                "quality_bucket": quality_bucket,
                "quality_multiplier": quality_multiplier,
                "regime": regime,
                "risk_sized_order_krw": risk_sized_order_krw,
                "cash_cap_order_krw": cash_cap_order_krw,
                "base_order_krw": base_order_krw,
                "final_order_krw": final_order_krw,
            }
            self._log_entry_diagnostics(
                market=market,
                latest_time=latest_time,
                regime=regime,
                effective_strategy_params=effective_strategy_params,
                diagnostics=diagnostics,
                risk_sized_order_krw=risk_sized_order_krw,
                cash_cap_order_krw=cash_cap_order_krw,
                base_order_krw=base_order_krw,
                final_order_krw=final_order_krw,
                strategy_entry_price=strategy_entry_price,
                stop_price=stop_price,
                strategy_risk_per_unit=strategy_risk_per_unit,
                quality_score=quality_score,
                quality_bucket=quality_bucket,
                quality_multiplier=quality_multiplier,
                damping_log=damping_log,
                regime_diag=regime_diag,
            )
            self._entry_strategy_params_by_market[market] = effective_strategy_params
            print(
                "BUY_ACCEPTED",
                market,
                str(int(preflight["order_value"])) + "원",
                data["1m"][0]["trade_price"],
                f"risk_sized_order_krw={int(risk_sized_order_krw)}",
                f"cash_cap_order_krw={int(cash_cap_order_krw)}",
                f"base_order_krw={int(base_order_krw)}",
                f"final_order_krw={int(final_order_krw)}",
                f"quality_score={quality_score:.3f}",
                f"quality_bucket={quality_bucket}",
                f"quality_multiplier={quality_multiplier:.2f}",
            )
            self.notifier.send(
                format_entry_summary(
                    market=market,
                    entry_price=float(data["1m"][0]["trade_price"]),
                    entry_score=float(diagnostics.get("entry_score", 0.0) or 0.0),
                    quality_bucket=quality_bucket,
                    final_order_krw=final_order_krw,
                )
            )
            entry_reason = str(getattr(strategy_entry_result, "reason", "entry_signal")) if strategy_entry_result is not None else "entry_signal"
            self._append_trade_reason(
                side="BUY",
                market=market,
                reason=entry_reason,
                price=float(data["1m"][0]["trade_price"]),
                qty=preflight["order_value"] / reference_price if reference_price > 0 else None,
                notional_krw=preflight.get("notional"),
            )
            break

    def _append_trade_reason(
        self,
        *,
        side: str,
        market: str,
        reason: str,
        price: float,
        qty: float | None = None,
        notional_krw: float | None = None,
        qty_ratio: float | None = None,
        diagnostics: dict[str, float | str] | None = None,
    ) -> None:
        stop_reasons = {"stop_loss", "partial_stop_loss", "trailing_stop"}

        def _fmt(value: float | int | None, precision: int = 8) -> str:
            if not isinstance(value, (int, float)):
                return "na"
            return f"{float(value):.{precision}f}"

        now = datetime.now(timezone.utc).isoformat()
        qty_text = _fmt(qty)
        notional_text = _fmt(notional_krw, precision=0)
        qty_ratio_text = _fmt(qty_ratio, precision=4)
        line = (
            f"{now} | {side} | {market} | price={price:.8f}"
            f" | qty={qty_text} | notional_krw={notional_text} | qty_ratio={qty_ratio_text} | reason={reason}"
        )

        if reason in stop_reasons:
            stop_diag = diagnostics if isinstance(diagnostics, dict) else {}
            stop_ref_price = stop_diag.get("hard_stop_price")
            if not isinstance(stop_ref_price, (int, float)):
                stop_ref_price = stop_diag.get("trailing_floor")
            stop_gap_pct = None
            if isinstance(price, (int, float)) and price > 0 and isinstance(stop_ref_price, (int, float)) and stop_ref_price > 0:
                stop_gap_pct = ((float(price) - float(stop_ref_price)) / float(stop_ref_price)) * 100.0
            line += f" | stop_ref_price={_fmt(stop_ref_price)} | stop_gap_pct={_fmt(stop_gap_pct, precision=4)}"

        self._recent_trade_reasons.append(line)
        self._recent_trade_reasons = self._recent_trade_reasons[-10:]
        try:
            self._trade_reason_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._trade_reason_log_path.write_text("\n".join(self._recent_trade_reasons) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"TRADE_REASON_LOG_WRITE_FAILED path={self._trade_reason_log_path} error={exc}")

    def _compute_market_damping_factors(self, ticker: dict, candles_1m: list[dict]) -> tuple[float, float, list[str]]:
        liquidity_factor = 1.0
        volatility_factor = 1.0
        reasons: list[str] = []

        ask = self._safe_float(ticker.get("ask_price"))
        bid = self._safe_float(ticker.get("bid_price"))
        last = self._safe_float(ticker.get("trade_price", ticker.get("last")))
        relative_spread = (ask - bid) / last if ask > 0 and bid > 0 and last > 0 else 0.0
        max_spread = max(1e-9, float(self.config.market_damping_max_spread))
        spread_factor = min(1.0, max_spread / relative_spread) if relative_spread > 0 else 1.0

        trade_value_24h = self._safe_float(
            ticker.get("acc_trade_price_24h", ticker.get("acc_trade_price", ticker.get("trade_volume")))
        )
        min_trade_value = max(1.0, float(self.config.market_damping_min_trade_value_24h))
        trade_value_factor = min(1.0, trade_value_24h / min_trade_value) if trade_value_24h > 0 else 0.0

        liquidity_factor = min(spread_factor, trade_value_factor)
        if spread_factor < 1.0:
            reasons.append(f"high_spread:{relative_spread:.6f}>{max_spread:.6f}")
        if trade_value_factor < 1.0:
            reasons.append(f"low_trade_value_24h:{trade_value_24h:.0f}<{min_trade_value:.0f}")

        atr_period = max(2, int(self.config.market_damping_atr_period))
        atr = self._latest_atr(candles_1m, atr_period)
        atr_ratio = atr / last if atr > 0 and last > 0 else 0.0
        max_atr_ratio = max(1e-9, float(self.config.market_damping_max_atr_ratio))
        volatility_factor = min(1.0, max_atr_ratio / atr_ratio) if atr_ratio > 0 else 1.0
        if volatility_factor < 1.0:
            reasons.append(f"high_atr_ratio:{atr_ratio:.6f}>{max_atr_ratio:.6f}")

        return liquidity_factor, volatility_factor, reasons

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


    def _is_reentry_cooldown_active(self, market: str, now_at: datetime) -> bool:
        cooldown_bars = max(0, int(self.config.reentry_cooldown_bars))
        if cooldown_bars <= 0:
            return False

        last_exit = self._last_exit_snapshot_by_market.get(market)
        if not last_exit:
            return False

        last_reason = str(last_exit.get("reason", ""))
        if self.config.cooldown_on_loss_exits_only and last_reason not in {"trailing_stop", "stop_loss"}:
            return False

        last_time = last_exit.get("time")
        if not isinstance(last_time, datetime):
            return False

        elapsed_bars = self._compute_elapsed_bars(last_time, now_at)
        return elapsed_bars < cooldown_bars

    def _is_strategy_cooldown_active(self, market: str, now_at: datetime, strategy_params) -> bool:
        cooldown_bars = max(0, int(getattr(strategy_params, "strategy_cooldown_bars", 0)))
        if cooldown_bars <= 0:
            return False

        last_exit = self._last_strategy_exit_snapshot_by_market.get(market)
        if not last_exit:
            return False

        last_time = last_exit.get("time")
        if not isinstance(last_time, datetime):
            return False

        elapsed_bars = self._compute_elapsed_bars(last_time, now_at)
        return elapsed_bars < cooldown_bars

    def _compute_elapsed_bars(self, before_at: datetime, now_at: datetime) -> int:
        normalized_before = self._to_utc_aware(before_at)
        normalized_now = self._to_utc_aware(now_at)
        elapsed_minutes = max(0.0, (normalized_now - normalized_before).total_seconds() / 60.0)
        bar_minutes = max(1, int(self.config.candle_interval))
        return int(elapsed_minutes // bar_minutes)

    def _to_utc_aware(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _get_strategy_candles(self, market: str) -> dict[str, list[dict]]:
        intervals = {1: "1m", 5: "5m", 15: "15m"}
        result: dict[str, list[dict]] = {}
        for interval, key in intervals.items():
            raw = self.candle_buffer.get_candles(
                market,
                interval,
                lambda selected_market, selected_interval: self.broker.get_candles(
                    selected_market,
                    interval=selected_interval,
                ),
            )
            result[key] = preprocess_candles(raw, source_order="newest")
        return result

    def _next_order_identifier(self, market: str, side: str) -> str:
        self._order_sequence += 1
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        return f"{market}:{side}:{timestamp}:{self._order_sequence}"

    def _should_run_strategy(self, market: str, data: dict[str, list[dict]]) -> bool:
        if not self._is_strategy_data_healthy(data):
            return False

        latest_candle = data.get("1m", [{}])[0]
        latest_time = self.candle_buffer.parse_candle_time(latest_candle)
        if latest_time is None:
            return True

        previous_time = self._last_processed_candle_at.get(market)
        if previous_time is not None and latest_time <= previous_time:
            return False

        self._last_processed_candle_at[market] = latest_time
        return True

    def _reset_position_exit_state(self, market: str) -> None:
        state = self._position_exit_states.get(market)
        if state is None:
            return
        state.reset_after_full_exit()
        self._position_exit_states.pop(market, None)
        self._entry_tracking_by_market.pop(market, None)
        self._entry_strategy_params_by_market.pop(market, None)

    def _emit_structured_log(self, event_type: str, **fields) -> None:
        event = {"type": event_type, **fields}
        print(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str))

    def _log_entry_diagnostics(
        self,
        *,
        market: str,
        latest_time: datetime,
        regime: str,
        effective_strategy_params: StrategyParams,
        diagnostics: dict,
        risk_sized_order_krw: float,
        cash_cap_order_krw: float,
        base_order_krw: float,
        final_order_krw: float,
        strategy_entry_price: float,
        stop_price: float,
        strategy_risk_per_unit: float,
        quality_score: float,
        quality_bucket: str,
        quality_multiplier: float,
        damping_log: dict | None,
        regime_diag: dict,
    ) -> None:
        self._emit_structured_log(
            "ENTRY_DIAGNOSTICS",
            market=market,
            candle_time=latest_time.isoformat(),
            regime=regime,
            strategy=str(getattr(effective_strategy_params, "strategy_name", "")),
            entry_score=float(diagnostics.get("entry_score", 0.0) or 0.0),
            quality_score=quality_score,
            quality_bucket=quality_bucket,
            quality_multiplier=quality_multiplier,
            sizing={
                "risk_sized_order_krw": int(risk_sized_order_krw),
                "cash_cap_order_krw": int(cash_cap_order_krw),
                "base_order_krw": int(base_order_krw),
                "final_order_krw": int(final_order_krw),
                "entry_price": strategy_entry_price,
                "stop_price": stop_price,
                "risk_per_unit": strategy_risk_per_unit,
            },
            regime_diagnostics=regime_diag,
            strategy_diagnostics=diagnostics,
            market_damping=damping_log or {},
        )

    def _compute_realized_r(self, *, market: str, current_price: float, avg_buy_price: float) -> float:
        state = self._position_exit_states.get(market)
        if state and state.risk_per_unit > 0 and state.entry_price > 0:
            return (current_price - state.entry_price) / state.risk_per_unit
        fallback_risk = max(avg_buy_price - (avg_buy_price * self.config.stop_loss_threshold), 0.0)
        if fallback_risk <= 0:
            return 0.0
        return (current_price - avg_buy_price) / fallback_risk

    def _estimate_exit_costs(self, *, market: str, sold_volume: float, current_price: float) -> tuple[float, float]:
        notional = max(0.0, sold_volume * current_price)
        fee_estimate = notional * float(self.config.fee_rate)
        tickers = self.broker.get_ticker(market)
        bid = ask = 0.0
        if isinstance(tickers, list) and tickers:
            bid = self._safe_float(tickers[0].get("bid_price"))
            ask = self._safe_float(tickers[0].get("ask_price"))
        rel_spread = ((ask - bid) / current_price) if bid > 0 and ask > 0 and current_price > 0 else 0.0
        slippage_estimate = notional * max(0.0, rel_spread / 2)
        return fee_estimate, slippage_estimate

    def _log_exit_diagnostics(
        self,
        *,
        market: str,
        decision,
        avg_buy_price: float,
        current_price: float,
        sold_volume: float,
    ) -> None:
        entry_tracking = self._entry_tracking_by_market.get(market, {})
        state = self._position_exit_states.get(market)
        now_at = datetime.now(timezone.utc)
        entry_time = entry_tracking.get("entry_time")
        holding_minutes = 0.0
        if isinstance(entry_time, datetime):
            entry_time = self._to_utc_aware(entry_time)
            holding_minutes = max(0.0, (now_at - entry_time).total_seconds() / 60.0)
        elif state is not None:
            holding_minutes = float(max(0, int(state.bars_held)) * max(1, int(self.config.candle_interval)))
        mfe_r = float(state.highest_r) if state is not None else 0.0
        lowest_r = float(state.lowest_r) if state is not None else 0.0
        mae_r = abs(min(0.0, lowest_r))
        realized_r = self._compute_realized_r(market=market, current_price=current_price, avg_buy_price=avg_buy_price)
        fee_estimate, slippage_estimate = self._estimate_exit_costs(
            market=market,
            sold_volume=sold_volume,
            current_price=current_price,
        )
        self._emit_structured_log(
            "EXIT_DIAGNOSTICS",
            market=market,
            exit_reason=decision.reason,
            qty_ratio=float(decision.qty_ratio),
            holding_minutes=holding_minutes,
            mfe_r=mfe_r,
            mae_r=mae_r,
            realized_r=realized_r,
            fee_estimate_krw=fee_estimate,
            slippage_estimate_krw=slippage_estimate,
            entry_score=float(entry_tracking.get("entry_score", 0.0) or 0.0),
            entry_regime=str(entry_tracking.get("regime", "unknown") or "unknown"),
            daily_realized_pnl_krw=self._daily_realized_pnl_krw(),
        )

    def _daily_realized_pnl_krw(self) -> float:
        return float(getattr(self.risk, "_realized_pnl_today", 0.0))

    def _resolve_strategy_params_for_regime(self, base_params: StrategyParams, regime: str) -> StrategyParams:
        overrides = self.config.regime_strategy_overrides(regime)
        if not overrides:
            return base_params
        merged = asdict(base_params)
        merged.update(overrides)
        return StrategyParams(**merged)

    def _is_strategy_data_healthy(self, data: dict[str, list[dict]]) -> bool:
        max_missing_rate = max(0.0, float(self.config.max_candle_missing_rate))
        for timeframe in ("1m", "5m", "15m"):
            candles = data.get(timeframe, [])
            if not candles:
                return False
            if bool(candles[0].get("missing")):
                return False

            missing_count = sum(1 for candle in candles if bool(candle.get("missing")))
            missing_rate = missing_count / len(candles)
            if missing_rate > max_missing_rate:
                return False
        return True


    def _should_subscribe_private_channels(self) -> bool:
        mode = str(self.config.mode or "").lower()
        return mode not in {"paper", "dry_run"} and hasattr(self.broker, "get_order")

    def _route_ws_message(self, message: dict) -> None:
        message_type = message.get("type") or message.get("ty")
        if message_type == "myOrder":
            apply_my_order_event(message, self.orders_by_identifier)
            return

        if message_type == "myAsset":
            apply_my_asset_event(message, self.portfolio_snapshot)

    def reconcile_orders(self) -> None:
        self._reconcile_orders_via_rest()
        now = datetime.now(timezone.utc)
        for order in list(self.orders_by_identifier.values()):
            if order.state in {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}:
                continue

            timeout_limit = self.order_timeout_seconds
            if order.state == OrderStatus.PARTIALLY_FILLED:
                timeout_limit *= self.partial_fill_timeout_scale

            age_seconds = (now - order.updated_at).total_seconds()
            if age_seconds >= timeout_limit:
                self._on_order_timeout(order)

            if 0 < order.filled_qty < order.requested_qty and order.state == OrderStatus.ACCEPTED:
                order.state = OrderStatus.PARTIALLY_FILLED

    def _reconcile_orders_via_rest(self) -> None:
        if not hasattr(self.broker, "get_order"):
            return

        for order in list(self.orders_by_identifier.values()):
            if order.state in {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}:
                continue

            if not order.uuid:
                continue

            try:
                remote_order = self.broker.get_order(order.uuid)
            except Exception:
                continue

            if not isinstance(remote_order, dict):
                continue

            remote_event = dict(remote_order)
            remote_event.setdefault("identifier", order.identifier)
            remote_event.setdefault("uuid", order.uuid)
            remote_event.setdefault("market", order.market)
            remote_event.setdefault("side", order.side)
            remote_event.setdefault("volume", order.requested_qty)

            remote_state = str(remote_event.get("state") or "").lower()
            remote_requested = float(remote_event.get("volume") or order.requested_qty or 0.0)
            remote_filled = remote_event.get("executed_volume")
            if remote_filled is None and remote_event.get("remaining_volume") is not None:
                remote_filled = max(0.0, remote_requested - float(remote_event.get("remaining_volume") or 0.0))
            remote_filled_qty = float(remote_filled or 0.0)

            if remote_state in {"wait", "watch"} and remote_filled_qty <= order.filled_qty:
                continue

            apply_my_order_event(remote_event, self.orders_by_identifier)

    def _on_order_timeout(self, order: OrderRecord) -> None:
        action = "NO_ACTION"
        result = "SKIPPED"
        retry_target_qty = 0.0
        timed_out_state = order.state

        if timed_out_state not in {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}:
            self._log_timeout_policy_event(order, action=action, result=result)
            return

        if self._is_in_timeout_cooldown(order):
            self._log_timeout_policy_event(order, action=action, result="COOLDOWN")
            return

        cancel_ok = self._cancel_open_order(order)
        if not cancel_ok:
            self._log_timeout_policy_event(order, action="CANCEL", result="FAILED")
            self._notify_timeout_warning(order, "CANCEL_FAILED")
            return

        action = "CANCEL"
        result = "SUCCESS"

        if timed_out_state == OrderStatus.PARTIALLY_FILLED:
            remaining_qty = max(0.0, order.requested_qty - order.filled_qty)
            retry_target_qty = remaining_qty * self.partial_fill_reduce_ratio
            action = "CANCEL_AND_AMEND"
        elif timed_out_state == OrderStatus.ACCEPTED:
            retry_target_qty = order.requested_qty
            action = "CANCEL_AND_REORDER"

        should_retry = retry_target_qty >= 1e-12 and order.retry_count < self.max_order_retries
        if not should_retry:
            if order.retry_count >= self.max_order_retries:
                result = "MAX_RETRIES_REACHED"
                self._notify_timeout_warning(order, result)
            self._log_timeout_policy_event(order, action=action, result=result)
            self._mark_timeout_action(order)
            return

        retried = self._retry_order(order, retry_target_qty)
        if retried:
            result = "RETRY_ACCEPTED"
        else:
            result = "RETRY_FAILED"
            self._notify_timeout_warning(order, result)
        self._log_timeout_policy_event(order, action=action, result=result)
        self._mark_timeout_action(order)

    def _cancel_open_order(self, order: OrderRecord) -> bool:
        if not order.uuid:
            return False

        remote_order = self.broker.get_order(order.uuid)
        remote_state = str(remote_order.get("state") or "").lower()
        if remote_state and remote_state not in {"wait", "watch"}:
            return False

        self.broker.cancel_order(order.uuid)
        order.state = OrderStatus.CANCELED
        order.updated_at = datetime.now(timezone.utc)
        return True

    def _retry_order(self, origin: OrderRecord, qty: float) -> OrderRecord | None:
        reference_price = self._get_market_trade_price(origin.market)
        if reference_price <= 0:
            self._notify_preflight_failure(
                {
                    "ok": False,
                    "code": "PREFLIGHT_PRICE_UNAVAILABLE",
                    "market": origin.market,
                    "side": origin.side,
                    "requested": qty,
                    "rounded_price": 0.0,
                    "order_value": qty,
                    "notional": 0.0,
                }
            )
            return None
        preflight = self._preflight_order(
            market=origin.market,
            side=origin.side,
            requested_value=qty,
            reference_price=reference_price,
        )
        if not preflight["ok"]:
            self._notify_preflight_failure(preflight)
            return None

        identifier = self._next_retry_identifier(origin)
        if origin.side == "bid":
            response = self.broker.buy_market(origin.market, preflight["order_value"], identifier=identifier)
        else:
            response = self.broker.sell_market(origin.market, preflight["order_value"], identifier=identifier)

        retried = self._record_accepted_order(
            response,
            identifier,
            origin.market,
            origin.side,
            preflight["order_value"],
            parent_identifier=origin.identifier,
        )
        retried.retry_count = origin.retry_count + 1
        return retried

    def _root_identifier(self, identifier: str) -> str:
        parent = self.order_identifier_parent.get(identifier)
        while parent and parent != identifier:
            identifier = parent
            parent = self.order_identifier_parent.get(identifier)
        return identifier

    def _next_retry_identifier(self, origin: OrderRecord) -> str:
        root = self._root_identifier(origin.identifier)
        return self._next_order_identifier(origin.market, origin.side) + f":r{origin.retry_count + 1}:root={root}"

    def _is_in_timeout_cooldown(self, order: OrderRecord) -> bool:
        root = self._root_identifier(order.identifier)
        last_action_at = self.order_last_timeout_action_at.get(root)
        if not last_action_at:
            return False
        elapsed = (datetime.now(timezone.utc) - last_action_at).total_seconds()
        return elapsed < self.timeout_retry_cooldown_seconds

    def _mark_timeout_action(self, order: OrderRecord) -> None:
        root = self._root_identifier(order.identifier)
        self.order_last_timeout_action_at[root] = datetime.now(timezone.utc)

    def _notify_timeout_warning(self, order: OrderRecord, reason: str) -> None:
        self.notifier.send(
            f"ORDER_TIMEOUT_WARNING reason={reason} root={self._root_identifier(order.identifier)} "
            f"identifier={order.identifier} retries={order.retry_count}/{self.max_order_retries}"
        )

    def _log_timeout_policy_event(self, order: OrderRecord, action: str, result: str) -> None:
        event = {
            "type": "ORDER_TIMEOUT_POLICY",
            "order_id": order.uuid,
            "identifier": order.identifier,
            "root_identifier": self._root_identifier(order.identifier),
            "action": action,
            "result": result,
            "retry_count": order.retry_count,
            "max_order_retries": self.max_order_retries,
            "state": order.state.value,
        }
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))

    def _get_market_trade_price(self, market: str) -> float:
        tickers = self.broker.get_ticker(market)
        if not isinstance(tickers, list) or not tickers:
            return 0.0
        return float(tickers[0].get("trade_price", 0.0) or 0.0)

    def _krw_tick_size(self, price: float) -> float:
        return krw_tick_size(price)

    def _round_to_tick(self, value: float, tick: float) -> float:
        return round_down_to_tick(value, tick)

    def _preflight_order(self, market: str, side: str, requested_value: float, reference_price: float) -> dict:
        if requested_value <= 0 or reference_price <= 0:
            return {
                "ok": False,
                "code": "PREFLIGHT_INVALID_INPUT",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": 0.0,
                "order_value": 0.0,
                "notional": 0.0,
            }

        tick = self._krw_tick_size(reference_price)
        rounded_price = self._round_to_tick(reference_price, tick)
        if rounded_price <= 0:
            return {
                "ok": False,
                "code": "PREFLIGHT_PRICE_ROUNDING_FAILED",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": rounded_price,
                "order_value": requested_value,
                "notional": 0.0,
            }

        if side == "bid":
            order_value = float(int(requested_value))
            notional = order_value
            rounded_qty = order_value / rounded_price
        else:
            rounded_qty = round(requested_value, 8)
            order_value = rounded_qty
            notional = rounded_qty * rounded_price

        if notional < self.config.min_order_krw:
            return {
                "ok": False,
                "code": "PREFLIGHT_MIN_NOTIONAL",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": rounded_price,
                "order_value": order_value,
                "notional": notional,
            }

        recomputed_notional = rounded_qty * rounded_price
        if order_value <= 0 or rounded_qty <= 0 or recomputed_notional < self.config.min_order_krw:
            return {
                "ok": False,
                "code": "PREFLIGHT_RECOMPUTE_INVALID",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": rounded_price,
                "order_value": order_value,
                "notional": recomputed_notional,
            }

        return {
            "ok": True,
            "code": "PREFLIGHT_OK",
            "market": market,
            "side": side,
            "requested": requested_value,
            "rounded_price": rounded_price,
            "order_value": order_value,
            "notional": recomputed_notional,
        }

    def _notify_preflight_failure(self, result: dict) -> None:
        code = result.get("code", "PREFLIGHT_UNKNOWN")
        market = result.get("market")
        side = result.get("side")
        requested = result.get("requested")
        rounded_price = result.get("rounded_price")
        notional = result.get("notional")
        print("ORDER_PREFLIGHT_BLOCKED", code, market, side, requested, rounded_price, notional)
        self.notifier.send(f"ORDER_PREFLIGHT_BLOCKED {code} {market} {side} req={requested} notional={notional}")

    def _should_exit_position(self, market: str, data: dict[str, list[dict]], avg_buy_price: float, current_price: float, strategy_params):
        current_atr = self._latest_atr(data["1m"], self.config.atr_period)
        swing_low = self._latest_swing_low(data["1m"], self.config.swing_lookback)
        state = self._position_exit_states.setdefault(
            market,
            PositionExitState(
                peak_price=current_price,
                entry_atr=current_atr,
                entry_swing_low=swing_low,
                entry_price=avg_buy_price,
                initial_stop_price=avg_buy_price * self.config.stop_loss_threshold,
                risk_per_unit=max(avg_buy_price - (avg_buy_price * self.config.stop_loss_threshold), 0.0),
                entry_regime=self._resolve_entry_regime(data, strategy_params),
            ),
        )
        state.bars_held = max(0, int(state.bars_held)) + 1
        signal_exit = check_sell(
            data,
            avg_buy_price,
            strategy_params,
            entry_price=state.entry_price,
            initial_stop_price=state.initial_stop_price,
            risk_per_unit=state.risk_per_unit,
        )
        return self.order_policy.evaluate(
            state=state,
            avg_buy_price=avg_buy_price,
            current_price=current_price,
            signal_exit=signal_exit,
            current_atr=current_atr,
            swing_low=swing_low,
            strategy_name=str(getattr(strategy_params, "strategy_name", "")),
            partial_take_profit_enabled=bool(getattr(strategy_params, "partial_take_profit_enabled", False)),
            partial_take_profit_r=float(getattr(strategy_params, "partial_take_profit_r", 1.0)),
            partial_take_profit_size=float(getattr(strategy_params, "partial_take_profit_size", 0.0)),
            move_stop_to_breakeven_after_partial=bool(
                getattr(strategy_params, "move_stop_to_breakeven_after_partial", False)
            ),
            max_hold_bars=int(getattr(strategy_params, "max_hold_bars", 0)),
        )

    @staticmethod
    def _resolve_entry_regime(data: dict[str, list[dict]], strategy_params) -> str:
        c15 = data.get("15m", []) if isinstance(data, dict) else []
        try:
            diag = regime_filter_diagnostics(c15, strategy_params)
        except Exception:
            return "unknown"

        if not isinstance(diag, dict):
            return "unknown"
        regime = str(diag.get("regime", "unknown") or "unknown").strip().lower()
        if regime in {"strong_trend", "weak_trend", "sideways"}:
            return regime
        return "unknown"

    def _latest_atr(self, candles_newest: list[dict], period: int) -> float:
        if period <= 0:
            return 0.0
        candles = list(reversed(candles_newest))
        if len(candles) < 2:
            return 0.0
        trs: list[float] = []
        for i in range(1, len(candles)):
            cur, prev = candles[i], candles[i - 1]
            high = float(cur.get("high_price", cur.get("trade_price", 0.0)))
            low = float(cur.get("low_price", cur.get("trade_price", 0.0)))
            prev_close = float(prev.get("trade_price", 0.0))
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        if not trs:
            return 0.0
        window = trs[-min(period, len(trs)) :]
        return sum(window) / len(window)

    def _latest_swing_low(self, candles_newest: list[dict], lookback: int) -> float:
        window = candles_newest[: max(1, lookback)]
        if not window:
            return 0.0
        return min(float(candle.get("low_price", candle.get("trade_price", 0.0))) for candle in window)

    def bootstrap_open_orders(self) -> None:
        if not hasattr(self.broker, "get_open_orders"):
            return

        open_orders = self.broker.get_open_orders()
        if not isinstance(open_orders, list):
            return

        for event in open_orders:
            if not isinstance(event, dict):
                continue
            apply_my_order_event(event, self.orders_by_identifier)

    def _record_accepted_order(
        self,
        response,
        identifier: str,
        market: str,
        side: str,
        requested_qty: float,
        parent_identifier: str | None = None,
    ) -> OrderRecord:
        response_data = response if isinstance(response, dict) else {}
        order_uuid = response_data.get("uuid")
        record = OrderRecord.accepted(
            uuid=order_uuid,
            identifier=identifier,
            market=market,
            side=side,
            requested_qty=requested_qty,
        )
        self.orders_by_identifier[identifier] = record
        self.order_identifier_parent[identifier] = parent_identifier or identifier
        return record
