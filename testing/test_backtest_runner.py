import datetime
import importlib
import io
import sys
from dataclasses import replace
from typing import cast
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

pd = importlib.import_module("pandas")

from core.config import TradingConfig
from core.decision_core import evaluate_market as evaluate_shared_market
from core.decision_models import Candle, DecisionIntent, StrategySignal
from core.strategy_registry import RegisteredStrategy

if "slave_constants" not in sys.modules:
    slave_constants = types.ModuleType("slave_constants")
    setattr(slave_constants, "ACCESS_KEY", "x")
    setattr(slave_constants, "SECRET_KEY", "y")
    setattr(slave_constants, "SERVER_URL", "https://api.upbit.com")
    sys.modules["slave_constants"] = slave_constants

from testing.backtest_runner import BacktestRunner


class BacktestRunnerTest(unittest.TestCase):
    def _candle(self, ts: datetime.datetime, price: float) -> Candle:
        return {
            "market": "KRW-BTC",
            "candle_date_time_kst": ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "opening_price": price,
            "high_price": price,
            "low_price": price,
            "trade_price": price,
            "candle_acc_trade_volume": 1,
        }

    def _candle_value(self, candle: Candle, key: str) -> float:
        value = candle.get(key, 0.0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    def _enter_intent(
        self,
        *,
        final_order_krw: float = 80_000.0,
        base_order_krw: float | None = None,
        entry_price: float = 100.0,
        stop_price: float = 95.0,
        risk_per_unit: float = 5.0,
        entry_score: float = 1.2,
        quality_score: float = 0.4,
        quality_bucket: str = "mid",
        quality_multiplier: float = 1.0,
        entry_regime: str = "weak_trend",
        next_position_state: dict[str, object] | None = None,
    ) -> DecisionIntent:
        resolved_base_order = float(
            final_order_krw if base_order_krw is None else base_order_krw
        )
        resolved_next_state = dict(
            next_position_state
            or {
                "peak_price": entry_price,
                "entry_atr": 1.5,
                "entry_swing_low": 94.0,
                "entry_price": entry_price,
                "initial_stop_price": stop_price,
                "stop_basis": "unknown",
                "risk_per_unit": risk_per_unit,
                "bars_held": 0,
                "entry_regime": entry_regime,
                "partial_take_profit_done": False,
                "strategy_partial_done": False,
                "breakeven_armed": False,
                "highest_r": 0.0,
                "lowest_r": 0.0,
                "drawdown_from_peak_r": 0.0,
                "proof_window_active": False,
                "proof_window_promoted": False,
                "proof_window_status": "inactive",
                "proof_window_start_bar": 0,
                "proof_window_elapsed_bars": 0,
                "proof_window_max_bars": 0,
                "proof_window_max_favorable_excursion_r": 0.0,
                "proof_window_promotion_threshold_r": 0.0,
                "proof_window_cooldown_hint_bars": 0,
                "proof_window_symbol_profile": "default",
            }
        )
        return DecisionIntent(
            action="enter",
            reason="ok",
            diagnostics={
                "strategy_name": "baseline",
                "entry_score": entry_score,
                "quality_score": quality_score,
                "quality_bucket": quality_bucket,
                "quality_multiplier": quality_multiplier,
                "entry_regime": entry_regime,
                "stop_mode_long": "swing_low",
                "stop_price": stop_price,
                "entry_swing_low": 94.0,
                "sizing": {
                    "base_order_krw": resolved_base_order,
                    "final_order_krw": float(final_order_krw),
                    "entry_price": entry_price,
                    "risk_per_unit": risk_per_unit,
                },
            },
            next_position_state=resolved_next_state,
        )

    def _hold_intent(
        self,
        *,
        reason: str = "hold",
        diagnostics: dict[str, object] | None = None,
        next_position_state: dict[str, object] | None = None,
    ) -> DecisionIntent:
        return DecisionIntent(
            action="hold",
            reason=reason,
            diagnostics={"strategy_name": "baseline", **dict(diagnostics or {})},
            next_position_state=dict(next_position_state or {}),
        )

    def _exit_intent(
        self,
        *,
        action: str,
        reason: str,
        qty_ratio: float,
        next_position_state: dict[str, object] | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> DecisionIntent:
        return DecisionIntent(
            action=action,
            reason=reason,
            diagnostics={
                "strategy_name": "baseline",
                "qty_ratio": qty_ratio,
                "exit_stage": "mid_management",
                "entry_price": 100.0,
                "risk_per_unit": 5.0,
                "bars_held": 1.0,
                "highest_r": 1.0,
                **dict(diagnostics or {}),
            },
            next_position_state=dict(next_position_state or {}),
        )

    def test_shortage_policy_pads_missing_candles(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i)
            for i in range(5)
        ]

        padded, shortage = runner._apply_shortage_policy(candles)

        self.assertEqual(len(padded), 8)
        self.assertEqual(shortage, 3)
        self.assertTrue(padded[-1].get("missing", False))

    def test_target_count_expands_for_lookback_days(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, lookback_days=7)
        self.assertGreaterEqual(runner._target_count(), 7 * 24 * 20)

    def test_filter_recent_days_uses_latest_window(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, lookback_days=7)
        latest = datetime.datetime(2024, 1, 15, 0, 0, 0)
        candles = [
            self._candle(latest - datetime.timedelta(days=i), 10000 + i)
            for i in range(10)
        ]

        filtered = runner._filter_recent_days(candles)

        self.assertEqual(
            filtered[0]["candle_date_time_kst"], candles[0]["candle_date_time_kst"]
        )
        self.assertLessEqual(len(filtered), len(candles))
        self.assertGreaterEqual(len(filtered), 7)

    def test_oos_windows_is_clamped_to_two_or_more(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, oos_windows=1)
        self.assertEqual(runner.oos_windows, 2)

    def test_required_base_bars_for_regime_uses_strategy_regime_diagnostics_formula(
        self,
    ):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)

        required_15m = max(
            runner.strategy_params.regime_ema_slow,
            runner.strategy_params.regime_adx_period + 1,
            runner.strategy_params.regime_slope_lookback + 1,
        )
        expected_base_bars = (
            required_15m * 5
        )  # default 3m base candles -> 15m requires 5 base bars.

        self.assertEqual(runner._required_regime_15m_candles(), required_15m)
        self.assertEqual(runner.required_base_bars_for_regime, expected_base_bars)

    def test_build_mtf_candles_resamples_ohlcv(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 5, 0)
        candles = [
            {
                **self._candle(base - datetime.timedelta(minutes=3 * i), 100 + i),
                "opening_price": 100 + i,
                "high_price": 101 + (i * 2),
                "low_price": 99 - i,
                "trade_price": 100.5 + i,
                "candle_acc_trade_volume": 1 + i,
            }
            for i in range(6)
        ]

        mtf = runner._build_mtf_candles(candles)

        self.assertEqual(set(mtf.keys()), {"1m", "5m", "15m"})
        self.assertEqual(len(mtf["1m"]), 6)
        self.assertEqual(len(mtf["5m"]), 3)
        latest_5m = mtf["5m"][0]
        latest_bucket = candles[:2]
        self.assertEqual(latest_5m["opening_price"], latest_bucket[-1]["opening_price"])
        self.assertEqual(latest_5m["trade_price"], latest_bucket[0]["trade_price"])
        self.assertEqual(
            self._candle_value(latest_5m, "high_price"),
            max(self._candle_value(c, "high_price") for c in latest_bucket),
        )
        self.assertEqual(
            self._candle_value(latest_5m, "low_price"),
            min(self._candle_value(c, "low_price") for c in latest_bucket),
        )

    @patch(
        "testing.backtest_runner.debug_entry",
        return_value={"final_pass": False, "fail_code": "trigger_fail"},
    )
    def test_run_segment_when_len_equals_buffer_runs_once(self, _debug_entry):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i)
            for i in range(3)
        ]

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            return_value=self._hold_intent(reason="score_below_threshold"),
        ) as evaluate_market_mock:
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        context = evaluate_market_mock.call_args.args[0]
        self.assertEqual(
            set(context.market.candles_by_timeframe.keys()), {"1m", "5m", "15m"}
        )
        self.assertEqual(result.attempted_entries, 0)
        self.assertEqual(result.candidate_entries, 0)
        self.assertEqual(result.trades, 0)
        self.assertEqual(result.entry_fail_counts.get("trigger_fail"), 1)

    @patch(
        "testing.backtest_runner.debug_entry",
        return_value={
            "final_pass": False,
            "fail_code": "trigger_fail",
            "selected_zone": {"x": 1},
        },
    )
    def test_run_segment_counts_candidate_entries_only_with_selected_zone(
        self, _debug_entry
    ):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i)
            for i in range(3)
        ]

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            return_value=self._hold_intent(reason="score_below_threshold"),
        ):
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertEqual(result.attempted_entries, 1)
        self.assertEqual(result.candidate_entries, 1)
        self.assertEqual(result.triggered_entries, 0)

    @patch("testing.backtest_runner.debug_entry")
    def test_run_segment_expands_warmup_for_regime_filter_lookback(
        self, debug_entry_mock
    ):
        runner = BacktestRunner(buffer_cnt=3000, multiple_cnt=2)
        runner.config.candle_interval = 1
        runner.mtf_timeframes = runner._resolve_mtf_timeframes()
        runner.strategy_params = replace(runner.strategy_params, regime_ema_slow=200)
        runner.required_base_bars_for_regime = runner._required_base_bars_for_regime()
        runner.required_base_bars_for_mtf_minimums = (
            runner._required_base_bars_for_mtf_minimums()
        )

        base = datetime.datetime(2024, 1, 1, 6, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), 10000 + i)
            for i in range(3200)
        ]

        def debug_side_effect(mtf_data, _params, side="buy"):
            if len(mtf_data["15m"]) < 200:
                return {
                    "final_pass": False,
                    "fail_code": "regime_filter_fail",
                    "regime_filter_reason": "insufficient_15m_candles",
                }
            return {
                "final_pass": False,
                "fail_code": "regime_filter_fail",
                "regime_filter_reason": "ema_trend_fail",
            }

        debug_entry_mock.side_effect = debug_side_effect

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            return_value=self._hold_intent(reason="score_below_threshold"),
        ):
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreater(
            result.entry_fail_counts.get("regime_filter_fail:ema_trend_fail", 0), 0
        )
        self.assertEqual(
            result.entry_fail_counts.get(
                "regime_filter_fail:insufficient_15m_candles", 0
            ),
            0,
        )

    def test_run_segment_uses_decision_core_for_entry_sizing_exit_and_state_persistence(
        self,
    ):
        runner = BacktestRunner(
            buffer_cnt=3, multiple_cnt=2, spread_rate=0.0, slippage_rate=0.0
        )
        runner.config.fee_rate = 0.0
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), price)
            for i, price in enumerate([110.0, 100.0, 90.0, 80.0])
        ]
        enter_intent = self._enter_intent(final_order_krw=123_456.0, entry_price=100.0)
        exit_intent = self._exit_intent(
            action="exit_full", reason="strategy_signal", qty_ratio=1.0
        )

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=[enter_intent, exit_intent],
        ) as evaluate_market_mock:
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertEqual(evaluate_market_mock.call_count, 2)
        first_context = evaluate_market_mock.call_args_list[0].args[0]
        second_context = evaluate_market_mock.call_args_list[1].args[0]
        self.assertEqual(first_context.position.quantity, 0.0)
        self.assertEqual(
            first_context.diagnostics["entry_sizing_policy"]["baseline_equity"],
            1_000_000.0,
        )
        self.assertEqual(
            first_context.diagnostics["entry_sizing_policy"]["realized_pnl_today"],
            0.0,
        )
        self.assertEqual(
            first_context.diagnostics["market_damping_policy"]["enabled"],
            runner.config.market_damping_enabled,
        )
        self.assertEqual(
            first_context.diagnostics["market_damping_policy"]["max_spread"],
            runner.config.market_damping_max_spread,
        )
        self.assertEqual(second_context.position.state["stop_basis"], "unknown")
        self.assertEqual(
            second_context.position.state, enter_intent.next_position_state
        )
        self.assertEqual(second_context.position.entry_price, 100.0)
        self.assertEqual(second_context.diagnostics["sell_decision_rule"], "or")
        self.assertEqual(result.entries, 1)
        self.assertEqual(result.closed_trades, 1)
        self.assertEqual(result.exit_reason_counts.get("strategy_signal"), 1)
        self.assertAlmostEqual(result.return_pct, 1.23456, places=5)

    def test_build_entry_decision_context_includes_ticker_for_market_damping(self):
        runner = BacktestRunner(
            buffer_cnt=20,
            multiple_cnt=2,
            spread_rate=0.0002,
            slippage_rate=0.0,
        )
        runner.config.market_damping_enabled = True
        base = datetime.datetime(2024, 1, 1, 0, 57, 0)
        candles = [
            {
                **self._candle(base - datetime.timedelta(minutes=3 * i), 10000.0 + i),
                "trade_price": 10000.0 + i,
                "candle_acc_trade_volume": 2_000_000.0,
            }
            for i in range(20)
        ]
        mtf_data = runner._build_mtf_candles(candles)
        current_price = self._candle_value(candles[0], "trade_price")

        context = runner._build_entry_decision_context(
            data=mtf_data,
            price=current_price,
            current_atr=runner._latest_atr(candles, runner.config.atr_period),
            swing_low=runner._latest_swing_low(candles, runner.config.swing_lookback),
            available_krw=1_000_000.0,
            baseline_equity=1_000_000.0,
            realized_pnl_today=0.0,
        )

        ticker = cast(dict[str, object], context.market.diagnostics["ticker"])
        expected_half_spread = current_price * runner.spread_rate / 2
        self.assertAlmostEqual(float(cast(float, ticker["trade_price"])), current_price)
        self.assertAlmostEqual(
            float(cast(float, ticker["ask_price"])),
            current_price + expected_half_spread,
        )
        self.assertAlmostEqual(
            float(cast(float, ticker["bid_price"])),
            current_price - expected_half_spread,
        )
        self.assertGreater(float(cast(float, ticker["acc_trade_price_24h"])), 0.0)

    def test_entry_context_keeps_market_damping_sizing_positive_when_strategy_accepts(
        self,
    ):
        runner = BacktestRunner(
            buffer_cnt=20,
            multiple_cnt=2,
            spread_rate=0.0002,
            slippage_rate=0.0,
        )
        runner.config.market_damping_enabled = True
        runner.config.market_damping_max_spread = 0.01
        runner.config.market_damping_min_trade_value_24h = 1_000.0
        runner.config.market_damping_max_atr_ratio = 0.5
        base = datetime.datetime(2024, 1, 1, 0, 57, 0)
        candles = [
            {
                **self._candle(base - datetime.timedelta(minutes=3 * i), 10000.0 + i),
                "trade_price": 10000.0 + i,
                "high_price": 10001.0 + i,
                "low_price": 9999.0 + i,
                "candle_acc_trade_volume": 2_000_000.0,
            }
            for i in range(20)
        ]
        mtf_data = runner._build_mtf_candles(candles)
        context = runner._build_entry_decision_context(
            data=mtf_data,
            price=self._candle_value(candles[0], "trade_price"),
            current_atr=runner._latest_atr(candles, runner.config.atr_period),
            swing_low=runner._latest_swing_low(candles, runner.config.swing_lookback),
            available_krw=1_000_000.0,
            baseline_equity=1_000_000.0,
            realized_pnl_today=0.0,
        )
        strategy = RegisteredStrategy(
            canonical_name="baseline",
            entry_evaluator=lambda *_args, **_kwargs: StrategySignal(
                accepted=True,
                reason="ok",
                diagnostics={
                    "entry_price": 10000.0,
                    "stop_price": 9990.0,
                    "r_value": 10.0,
                    "quality_score": 0.4,
                },
            ),
            exit_evaluator=lambda *_args, **_kwargs: False,
            aliases=("rsi_bb_reversal_long",),
            metadata={"legacy_strategy_name": "rsi_bb_reversal_long"},
        )

        with patch("core.decision_core.get_strategy", return_value=strategy):
            intent = evaluate_shared_market(
                context,
                strategy_params=runner.strategy_params,
                order_policy=runner.order_policy,
            )

        sizing = cast(dict[str, object], intent.diagnostics["sizing"])
        self.assertEqual(intent.action, "enter")
        self.assertGreater(float(cast(float, sizing["base_order_krw"])), 0.0)
        self.assertGreater(float(cast(float, sizing["final_order_krw"])), 0.0)
        self.assertAlmostEqual(
            float(cast(float, sizing["final_order_krw"])),
            float(cast(float, sizing["base_order_krw"])),
        )

    def test_run_segment_persists_hold_state_updates_between_seam_calls(self):
        runner = BacktestRunner(
            buffer_cnt=3, multiple_cnt=2, spread_rate=0.0, slippage_rate=0.0
        )
        runner.config.fee_rate = 0.0
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), price)
            for i, price in enumerate([106.0, 104.0, 102.0, 100.0, 98.0])
        ]
        enter_intent = self._enter_intent(final_order_krw=100.0, entry_price=100.0)
        hold_state = dict(enter_intent.next_position_state) | {
            "bars_held": 7,
            "highest_r": 1.5,
            "drawdown_from_peak_r": -0.2,
        }
        hold_intent = self._hold_intent(next_position_state=hold_state)
        exit_intent = self._exit_intent(
            action="exit_full",
            reason="strategy_signal",
            qty_ratio=1.0,
            next_position_state=hold_state,
        )

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=[enter_intent, hold_intent, exit_intent],
        ) as evaluate_market_mock:
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertEqual(evaluate_market_mock.call_count, 3)
        exit_context = evaluate_market_mock.call_args_list[2].args[0]
        self.assertEqual(exit_context.position.state["stop_basis"], "unknown")
        self.assertEqual(exit_context.position.state, hold_state)
        self.assertEqual(result.closed_trades, 1)

    def test_run_segment_uses_position_risk_for_realized_r_accounting(self):
        runner = BacktestRunner(
            buffer_cnt=3, multiple_cnt=2, spread_rate=0.0, slippage_rate=0.0
        )
        runner.config.fee_rate = 0.0
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), price)
            for i, price in enumerate([104.0, 102.0, 100.0, 98.0])
        ]
        enter_intent = self._enter_intent(
            final_order_krw=100.0,
            entry_price=100.0,
            risk_per_unit=2.0,
            stop_price=98.0,
        )
        exit_intent = self._exit_intent(
            action="exit_full",
            reason="stop_loss",
            qty_ratio=1.0,
            diagnostics={
                "entry_price": 100.0,
                "risk_per_unit": 2.0,
                "hard_stop_price": 98.0,
            },
        )

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=[enter_intent, exit_intent],
        ):
            runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertTrue(runner.stop_recovery_rows)
        self.assertAlmostEqual(
            float(runner.stop_recovery_rows[-1]["realized_r"]), 1.0, places=6
        )

    def test_run_segment_applies_costs_and_metrics(self):
        runner = BacktestRunner(
            buffer_cnt=3, multiple_cnt=2, spread_rate=0.001, slippage_rate=0.001
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + (10 * i))
            for i in range(10)
        ]

        intents = [
            self._enter_intent(final_order_krw=80_000.0, entry_price=10020.0),
            self._exit_intent(
                action="exit_full",
                reason="strategy_signal",
                qty_ratio=1.0,
                diagnostics={"entry_price": 10020.0},
            ),
        ]

        decision_state = {"entry_given": False}

        def decision_side_effect(context, **_kwargs):
            if context.position.quantity > 0:
                return intents[1]
            if decision_state["entry_given"]:
                return self._hold_intent()
            decision_state["entry_given"] = True
            return intents[0]

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ):
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreaterEqual(result.trades, 1)
        self.assertGreaterEqual(result.entries, result.closed_trades)
        self.assertGreaterEqual(result.fill_rate, 0)
        self.assertLessEqual(result.fill_rate, 1)
        self.assertIsInstance(result.sharpe, float)

    def test_run_segment_force_closes_open_position_at_segment_end(self):
        runner = BacktestRunner(
            buffer_cnt=3, multiple_cnt=2, spread_rate=0.0, slippage_rate=0.0
        )
        runner.config.fee_rate = 0.0
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), price)
            for i, price in enumerate([106.0, 104.0, 102.0, 100.0, 98.0])
        ]

        decision_state = {"entered": False}

        def decision_side_effect(context, **_kwargs):
            if context.position.quantity > 0:
                return self._hold_intent(next_position_state=context.position.state)
            if decision_state["entered"]:
                return self._hold_intent()
            decision_state["entered"] = True
            return self._enter_intent(final_order_krw=100.0, entry_price=100.0)

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ):
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertEqual(result.entries, 1)
        self.assertEqual(result.closed_trades, 1)
        self.assertEqual(result.exit_reason_counts.get("segment_end"), 1)

    def test_run_segment_segment_end_close_contributes_to_win_rate(self):
        runner = BacktestRunner(
            buffer_cnt=3, multiple_cnt=2, spread_rate=0.0, slippage_rate=0.0
        )
        runner.config.fee_rate = 0.0
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=3 * i), price)
            for i, price in enumerate([106.0, 104.0, 102.0, 100.0, 98.0])
        ]

        decision_state = {"entered": False}

        def decision_side_effect(context, **_kwargs):
            if context.position.quantity > 0:
                return self._hold_intent(next_position_state=context.position.state)
            if decision_state["entered"]:
                return self._hold_intent()
            decision_state["entered"] = True
            return self._enter_intent(final_order_krw=100.0, entry_price=100.0)

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ):
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreater(result.return_pct, 0.0)
        self.assertEqual(result.win_rate, 100.0)
        self.assertGreater(result.avg_profit, 0.0)

    def test_run_segment_tracks_partial_take_profit_reason(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        prices = [100.0, 103.0, 103.5, 100.0, 99.0, 98.0]
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), p)
            for i, p in enumerate(prices)
        ]

        partial_state = self._enter_intent().next_position_state | {
            "partial_take_profit_done": True,
            "bars_held": 1,
            "highest_r": 1.2,
        }

        decision_state = {"enter_given": False, "partial_given": False}

        def decision_side_effect(context, **_kwargs):
            if context.position.quantity <= 0 and not decision_state["enter_given"]:
                decision_state["enter_given"] = True
                return self._enter_intent()
            if context.position.quantity > 0 and not decision_state["partial_given"]:
                decision_state["partial_given"] = True
                return self._exit_intent(
                    action="exit_partial",
                    reason="partial_take_profit",
                    qty_ratio=runner.config.partial_take_profit_ratio,
                    next_position_state=partial_state,
                )
            return self._hold_intent(next_position_state=partial_state)

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ):
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreaterEqual(
            result.exit_reason_counts.get("partial_take_profit", 0), 1
        )

    def test_sell_decision_rule_and_requires_both_signal_and_policy(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2, sell_decision_rule="and")
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        prices = [100.0, 100.5, 100.3, 100.2, 100.1, 100.0]
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), p)
            for i, p in enumerate(prices)
        ]

        enter_intent = self._enter_intent()

        def decision_side_effect(context, **_kwargs):
            if context.position.quantity <= 0:
                return enter_intent
            return self._hold_intent(
                next_position_state=enter_intent.next_position_state
            )

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ) as evaluate_market_mock:
            result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        exit_context = evaluate_market_mock.call_args_list[1].args[0]
        self.assertEqual(exit_context.diagnostics["sell_decision_rule"], "and")
        self.assertEqual(result.exit_reason_counts.get("signal_exit", 0), 0)

    @patch("testing.backtest_runner.debug_entry")
    def test_debug_mode_exports_dominant_entry_fail_code_when_signal_zero(
        self, debug_entry_mock
    ):
        runner = BacktestRunner(
            buffer_cnt=3,
            multiple_cnt=2,
            path="/tmp/not_used_debug.xlsx",
            segment_report_path="/tmp/segments_debug.csv",
            debug_mode=True,
            debug_report_path="/tmp/entry_debug.csv",
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), 100 + i)
            for i in range(12)
        ]

        debug_entry_mock.return_value = {
            "len_c1": 120,
            "len_c5": 120,
            "len_c15": 120,
            "zones_total": 1,
            "zones_active": 1,
            "selected_zone": None,
            "trigger_pass": False,
            "final_pass": False,
            "fail_code": "no_selected_zone",
        }

        with (
            patch.object(runner, "_load_or_create_data", return_value=(candles, 0)),
            patch(
                "testing.backtest_runner.evaluate_market",
                create=True,
                return_value=self._hold_intent(reason="score_below_threshold"),
            ),
        ):
            runner.run()

        debug_df = pd.read_csv("/tmp/entry_debug.csv")
        self.assertTrue((debug_df["signal_zero"] == True).all())
        self.assertTrue((debug_df["dominant_fail_code"] == "no_selected_zone").all())
        self.assertGreater(debug_df["fail_no_selected_zone"].sum(), 0)

    def test_run_segment_reentry_cooldown_zero_vs_positive(self):
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        prices = [100.0, 90.0, 100.0, 90.0, 100.0, 90.0, 100.0, 90.0, 100.0]
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), p)
            for i, p in enumerate(prices)
        ]

        runner_no_cooldown = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        runner_no_cooldown.config.reentry_cooldown_bars = 0

        runner_with_cooldown = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        runner_with_cooldown.config.reentry_cooldown_bars = 2
        runner_with_cooldown.config.cooldown_on_loss_exits_only = True

        def decision_side_effect(context, **_kwargs):
            if (
                context.position.quantity > 0
                and float(context.market.price or 0.0) <= 90.0
            ):
                return self._exit_intent(
                    action="exit_full", reason="stop_loss", qty_ratio=1.0
                )
            if context.position.quantity > 0:
                return self._hold_intent(next_position_state=context.position.state)
            return self._enter_intent()

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ):
            result_no_cooldown = runner_no_cooldown._run_segment(
                candles, init_amount=1_000_000, segment_id=1
            )

        with patch(
            "testing.backtest_runner.evaluate_market",
            create=True,
            side_effect=decision_side_effect,
        ):
            result_with_cooldown = runner_with_cooldown._run_segment(
                candles, init_amount=1_000_000, segment_id=1
            )

        self.assertGreater(result_no_cooldown.trades, result_with_cooldown.trades)
        self.assertGreater(
            result_with_cooldown.entry_fail_counts.get("fail_reentry_cooldown", 0), 0
        )

    def test_fill_rate_uses_candidate_entries(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)

        (
            total_return,
            return_per_trade,
            cagr,
            mdd,
            sharpe,
            fill_rate,
            cagr_valid,
            observed_days,
        ) = runner._calc_metrics(
            [1_000_000, 1_000_000],
            trades=2,
            attempted_entries=10,
            candidate_entries=4,
            triggered_entries=3,
        )

        self.assertIsInstance(total_return, float)
        self.assertIsInstance(cagr, float)
        self.assertIsInstance(mdd, float)
        self.assertIsInstance(sharpe, float)
        self.assertEqual(fill_rate, 0.5)
        self.assertFalse(cagr_valid)
        self.assertGreater(observed_days, 0)
        self.assertAlmostEqual(return_per_trade, total_return / 2)

    def test_calc_metrics_marks_short_period_cagr_as_nan(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)

        (
            total_return,
            return_per_trade,
            cagr,
            mdd,
            sharpe,
            fill_rate,
            cagr_valid,
            observed_days,
        ) = runner._calc_metrics(
            [1_000_000, 1_010_000, 1_020_000],
            trades=1,
            attempted_entries=1,
            candidate_entries=1,
            triggered_entries=1,
        )

        self.assertFalse(cagr_valid)
        self.assertTrue(pd.isna(cagr))
        self.assertLess(observed_days, runner.MIN_CAGR_OBSERVATION_DAYS)
        self.assertGreater(total_return, 0)
        self.assertEqual(return_per_trade, total_return)
        self.assertGreaterEqual(fill_rate, 0)

    def test_segment_csv_keeps_entry_counter_columns_for_fill_rate_context(self):
        runner = BacktestRunner(
            buffer_cnt=3,
            multiple_cnt=2,
            path="/tmp/not_used_entry_metrics.xlsx",
            segment_report_path="/tmp/segments_entry_metrics.csv",
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), 100 + i)
            for i in range(12)
        ]

        with patch.object(runner, "_load_or_create_data", return_value=(candles, 0)):
            with patch.object(runner, "_run_segment") as run_segment:
                from testing.backtest_runner import SegmentResult

                run_segment.return_value = SegmentResult(
                    segment_id=1,
                    insample_start="a",
                    insample_end="b",
                    oos_start="c",
                    oos_end="d",
                    trades=2,
                    attempted_entries=5,
                    candidate_entries=4,
                    triggered_entries=3,
                    fill_rate=0.5,
                    return_pct=1.0,
                    cagr=1.0,
                    mdd=1.0,
                    sharpe=1.0,
                    exit_reason_counts={},
                    entry_fail_counts={},
                )
                runner.run()

        df = pd.read_csv("/tmp/segments_entry_metrics.csv")
        self.assertIn("attempted_entries", df.columns)
        self.assertIn("candidate_entries", df.columns)
        self.assertIn("triggered_entries", df.columns)
        self.assertIn("entries", df.columns)
        self.assertIn("closed_trades", df.columns)
        self.assertIn("win_rate", df.columns)
        self.assertIn("expectancy", df.columns)
        self.assertIn("compounded_return_pct", df.columns)
        self.assertIn("segment_return_std", df.columns)
        self.assertIn("segment_return_median", df.columns)
        self.assertIn("quality_bucket_low_trades", df.columns)
        self.assertIn("quality_bucket_mid_expectancy", df.columns)
        self.assertIn("quality_bucket_high_win_rate", df.columns)
        self.assertEqual(df.loc[0, "fill_rate"], 0.5)

    def test_segment_csv_includes_exit_reason_columns(self):
        runner = BacktestRunner(
            buffer_cnt=3,
            multiple_cnt=2,
            path="/tmp/not_used.xlsx",
            segment_report_path="/tmp/segments.csv",
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), 100 + i)
            for i in range(12)
        ]

        with patch.object(runner, "_load_or_create_data", return_value=(candles, 0)):
            with patch.object(runner, "_run_segment") as run_segment:
                from testing.backtest_runner import SegmentResult

                run_segment.return_value = SegmentResult(
                    segment_id=1,
                    insample_start="a",
                    insample_end="b",
                    oos_start="c",
                    oos_end="d",
                    trades=1,
                    attempted_entries=1,
                    candidate_entries=1,
                    triggered_entries=1,
                    fill_rate=1.0,
                    return_pct=1.0,
                    cagr=1.0,
                    mdd=1.0,
                    sharpe=1.0,
                    exit_reason_counts={
                        "signal_exit": 2,
                        "trailing_stop": 1,
                        "segment_end": 1,
                    },
                )
                runner.run()

        df = pd.read_csv("/tmp/segments.csv")
        self.assertIn("exit_reason_signal_exit", df.columns)
        self.assertIn("exit_reason_segment_end", df.columns)
        self.assertIn("exit_reason_trailing_stop", df.columns)
        self.assertIn("exit_reason_stop_loss_early_bar_share_pct", df.columns)
        self.assertIn("stop_recovery_stop_loss_mfe_r_3_mean", df.columns)
        self.assertIn(
            "stop_recovery_trailing_stop_recovered_1r_10_share_pct", df.columns
        )

    def test_calc_post_exit_recovery_uses_forward_recent_bars(self):
        data_newest: list[Candle] = [
            {"high_price": 140.0, "trade_price": 140.0},
            {"high_price": 130.0, "trade_price": 130.0},
            {"high_price": 125.0, "trade_price": 125.0},
            {"high_price": 110.0, "trade_price": 110.0},
            {"high_price": 100.0, "trade_price": 100.0},
        ]

        stats = BacktestRunner._calc_post_exit_recovery(
            data_newest=data_newest,
            exit_index=4,
            exit_price=100.0,
            risk_per_unit=10.0,
        )

        self.assertEqual(stats["bars_available_3"], 3)
        self.assertAlmostEqual(stats["mfe_r_3"], 3.0)
        self.assertEqual(stats["recovered_1r_3"], 1)

    def test_run_writes_stop_recovery_csv_when_rows_exist(self):
        runner = BacktestRunner(
            buffer_cnt=3,
            multiple_cnt=2,
            path="/tmp/not_used_stop_recovery.xlsx",
            segment_report_path="/tmp/segments_stop_recovery.csv",
            stop_recovery_path="/tmp/stop_recovery.csv",
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), 100 + i)
            for i in range(12)
        ]

        with patch.object(runner, "_load_or_create_data", return_value=(candles, 0)):
            with patch.object(runner, "_run_segment") as run_segment:
                from testing.backtest_runner import SegmentResult

                def _segment_side_effect(*_args, **_kwargs):
                    runner.stop_recovery_rows.append(
                        {
                            "segment_id": 1,
                            "reason": "stop_loss",
                            "entry_score": 1.2,
                            "entry_regime": "sideways",
                            "bars_held": 2,
                            "realized_r": -0.8,
                            "mfe_r_3": 1.1,
                            "recovered_1r_3": 1,
                        }
                    )
                    return SegmentResult(
                        segment_id=1,
                        insample_start="a",
                        insample_end="b",
                        oos_start="c",
                        oos_end="d",
                        trades=1,
                        attempted_entries=1,
                        candidate_entries=1,
                        triggered_entries=1,
                        fill_rate=1.0,
                        return_pct=1.0,
                        cagr=1.0,
                        mdd=1.0,
                        sharpe=1.0,
                        exit_reason_counts={"stop_loss": 1},
                        stop_recovery_stats={
                            "stop_loss": {
                                "count": 1.0,
                                "mfe_r_3_mean": 1.1,
                                "recovered_1r_3_share_pct": 100.0,
                            }
                        },
                    )

                run_segment.side_effect = _segment_side_effect
                runner.run()

        df = pd.read_csv("/tmp/stop_recovery.csv")
        self.assertIn("entry_regime", df.columns)
        self.assertIn("entry_score", df.columns)
        self.assertIn("bars_held", df.columns)

    def test_segment_csv_includes_fail_columns_when_trades_are_zero(self):
        runner = BacktestRunner(
            buffer_cnt=3,
            multiple_cnt=2,
            path="/tmp/not_used_fail.xlsx",
            segment_report_path="/tmp/segments_fail.csv",
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [
            self._candle(base - datetime.timedelta(minutes=i), 100 + i)
            for i in range(12)
        ]

        with patch.object(runner, "_load_or_create_data", return_value=(candles, 0)):
            with patch.object(runner, "_run_segment") as run_segment:
                from testing.backtest_runner import SegmentResult

                run_segment.return_value = SegmentResult(
                    segment_id=1,
                    insample_start="a",
                    insample_end="b",
                    oos_start="c",
                    oos_end="d",
                    trades=0,
                    attempted_entries=3,
                    candidate_entries=3,
                    triggered_entries=0,
                    fill_rate=0.0,
                    return_pct=0.0,
                    cagr=0.0,
                    mdd=0.0,
                    sharpe=0.0,
                    exit_reason_counts={},
                    entry_fail_counts={
                        "no_selected_zone": 2,
                        "trigger_fail": 1,
                        "regime_filter_fail:ema_trend_fail": 1,
                    },
                )
                runner.run()

        df = pd.read_csv("/tmp/segments_fail.csv")
        self.assertIn("dominant_fail_code", df.columns)
        self.assertIn("fail_no_selected_zone", df.columns)
        self.assertIn("fail_regime_filter_fail", df.columns)
        self.assertEqual(df.loc[0, "dominant_fail_code"], "no_selected_zone")
        self.assertGreater(df.loc[0, "fail_no_selected_zone"], 0)

    def test_mtf_timeframes_and_minimums_follow_base_interval(self):
        runner = BacktestRunner(buffer_cnt=200, multiple_cnt=2)

        self.assertEqual(runner.mtf_timeframes, {"1m": 3, "5m": 6, "15m": 15})
        self.assertEqual(runner.strategy_params.min_candles_1m, 27)
        self.assertEqual(runner.strategy_params.min_candles_5m, 25)
        self.assertEqual(runner.strategy_params.min_candles_15m, 40)

    def test_validate_mtf_capacity_reports_clear_error_for_impossible_combination(self):
        runner = BacktestRunner(buffer_cnt=10, multiple_cnt=2)

        with self.assertRaises(ValueError) as exc:
            runner._validate_mtf_capacity(raise_on_failure=True)

        self.assertIn("insufficient MTF candle capacity", str(exc.exception))
        self.assertIn("available=", str(exc.exception))

    def test_default_buffer_capacity_is_not_insufficient(self):
        config = TradingConfig(do_not_trading=[], regime_filter_enabled=False)
        with patch("testing.backtest_runner.load_trading_config", return_value=config):
            runner = BacktestRunner(buffer_cnt=200, multiple_cnt=2)

        available = runner._validate_mtf_capacity(raise_on_failure=True)

        self.assertGreaterEqual(available["1m"], runner.strategy_params.min_candles_1m)
        self.assertGreaterEqual(available["5m"], runner.strategy_params.min_candles_5m)
        self.assertGreaterEqual(
            available["15m"], runner.strategy_params.min_candles_15m
        )

    def test_validate_mtf_capacity_warns_with_separated_min_and_regime_requirements(
        self,
    ):
        config = TradingConfig(
            do_not_trading=[],
            strategy_name="baseline",
            candle_interval=1,
            regime_filter_enabled=True,
            regime_ema_slow=200,
        )
        with patch("testing.backtest_runner.load_trading_config", return_value=config):
            runner = BacktestRunner(buffer_cnt=200, multiple_cnt=2)

        captured = io.StringIO()
        with redirect_stdout(captured):
            available = runner._validate_mtf_capacity(raise_on_failure=False)

        self.assertEqual(available["15m"], 14)
        warning = captured.getvalue()
        self.assertIn("insufficient MTF candle capacity", warning)
        self.assertIn("15m: available=14 < required=200", warning)
        self.assertIn("min_candles 기준=40", warning)
        self.assertIn("regime 기준=200", warning)

    def test_strategy_params_default_sell_requires_profit_false(self):
        runner = BacktestRunner(buffer_cnt=200, multiple_cnt=2)

        self.assertFalse(runner.strategy_params.sell_requires_profit)

    def test_strategy_params_sell_requires_profit_can_be_disabled(self):
        config = TradingConfig(do_not_trading=[], sell_requires_profit=False)
        with patch("testing.backtest_runner.load_trading_config", return_value=config):
            runner = BacktestRunner(buffer_cnt=200, multiple_cnt=2)

        self.assertFalse(runner.strategy_params.sell_requires_profit)

    def test_classify_structure_ignore_case_returns_expected_labels(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)

        self.assertEqual(
            runner._classify_structure_ignore_case(
                stop_mode_long="lower_band",
                entry_stop_price=95.0,
                entry_swing_low=94.0,
                hard_stop_price=96.0,
                entry_price=100.0,
                risk_per_unit=5.0,
            ),
            "entry_lower_band_mode",
        )
        self.assertEqual(
            runner._classify_structure_ignore_case(
                stop_mode_long="swing_low",
                entry_stop_price=95.0,
                entry_swing_low=95.0,
                hard_stop_price=101.0,
                entry_price=100.0,
                risk_per_unit=5.0,
            ),
            "breakeven_or_higher",
        )

    def test_build_stop_gap_deterioration_stats_splits_large_gap_group(self):
        rows: list[dict[str, float | int | str]] = [
            {"pnl": -10000.0, "stop_gap_from_entry_r": 1.2},
            {"pnl": -5000.0, "stop_gap_from_entry_r": 0.8},
            {"pnl": 3000.0, "stop_gap_from_entry_r": 0.2},
            {"pnl": 2000.0, "stop_gap_from_entry_r": 0.1},
        ]

        stats = BacktestRunner._build_stop_gap_deterioration_stats(rows)

        self.assertGreater(stats.get("large_gap_threshold_r", 0.0), 0.0)
        self.assertGreaterEqual(stats.get("large_gap_trades", 0.0), 1.0)
        self.assertIn("large_gap_win_rate", stats)
        self.assertIn("large_gap_expectancy", stats)
        self.assertIn("large_gap_avg_loss", stats)

    def test_score_win_rates_by_quantile_handles_sparse_distinct_scores(self):
        score_pnl_rows = [
            (1.0, -10.0),
            (1.0, -5.0),
            (1.0, 10.0),
            (1.0, 5.0),
            (2.0, -10.0),
            (2.0, 10.0),
            (2.0, 15.0),
            (2.0, 20.0),
        ]

        quantile_win_rates = BacktestRunner._score_win_rates_by_quantile(score_pnl_rows)

        self.assertEqual(
            quantile_win_rates,
            {"q1": 50.0, "q2": 75.0, "q3": 0.0, "q4": 0.0},
        )


if __name__ == "__main__":
    unittest.main()
