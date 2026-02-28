import datetime
import io
import sys
from dataclasses import replace
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

from core.config import TradingConfig

if 'slave_constants' not in sys.modules:
    sys.modules['slave_constants'] = types.SimpleNamespace(ACCESS_KEY='x', SECRET_KEY='y', SERVER_URL='https://api.upbit.com')

from testing.backtest_runner import BacktestRunner


class BacktestRunnerTest(unittest.TestCase):
    def _candle(self, ts: datetime.datetime, price: float):
        return {
            "market": "KRW-BTC",
            "candle_date_time_kst": ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "opening_price": price,
            "high_price": price,
            "low_price": price,
            "trade_price": price,
            "candle_acc_trade_volume": 1,
        }

    def test_shortage_policy_pads_missing_candles(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i) for i in range(5)]

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
        candles = [self._candle(latest - datetime.timedelta(days=i), 10000 + i) for i in range(10)]

        filtered = runner._filter_recent_days(candles)

        self.assertEqual(filtered[0]["candle_date_time_kst"], candles[0]["candle_date_time_kst"])
        self.assertLessEqual(len(filtered), len(candles))
        self.assertGreaterEqual(len(filtered), 7)

    def test_oos_windows_is_clamped_to_two_or_more(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, oos_windows=1)
        self.assertEqual(runner.oos_windows, 2)

    def test_required_base_bars_for_regime_uses_strategy_regime_diagnostics_formula(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)

        required_15m = max(
            runner.strategy_params.regime_ema_slow,
            runner.strategy_params.regime_adx_period + 1,
            runner.strategy_params.regime_slope_lookback + 1,
        )
        expected_base_bars = required_15m * 5  # default 3m base candles -> 15m requires 5 base bars.

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
        self.assertEqual(latest_5m["high_price"], max(c["high_price"] for c in latest_bucket))
        self.assertEqual(latest_5m["low_price"], min(c["low_price"] for c in latest_bucket))


    @patch("testing.backtest_runner.check_buy", return_value=False)
    @patch("testing.backtest_runner.debug_entry", return_value={"final_pass": False, "fail_code": "trigger_fail"})
    def test_run_segment_when_len_equals_buffer_runs_once(self, _debug_entry, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i) for i in range(3)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        args, _ = _check_buy.call_args
        self.assertIsInstance(args[0], dict)
        self.assertEqual(set(args[0].keys()), {"1m", "5m", "15m"})
        self.assertEqual(result.attempted_entries, 0)
        self.assertEqual(result.candidate_entries, 0)
        self.assertEqual(result.trades, 0)
        self.assertEqual(result.entry_fail_counts.get("trigger_fail"), 1)

    @patch("testing.backtest_runner.check_buy", return_value=False)
    @patch("testing.backtest_runner.debug_entry", return_value={"final_pass": False, "fail_code": "trigger_fail", "selected_zone": {"x": 1}})
    def test_run_segment_counts_candidate_entries_only_with_selected_zone(self, _debug_entry, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i) for i in range(3)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertEqual(result.attempted_entries, 1)
        self.assertEqual(result.candidate_entries, 1)
        self.assertEqual(result.triggered_entries, 0)

    @patch("testing.backtest_runner.check_buy", return_value=False)
    @patch("testing.backtest_runner.debug_entry")
    def test_run_segment_expands_warmup_for_regime_filter_lookback(self, debug_entry_mock, _check_buy):
        runner = BacktestRunner(buffer_cnt=3000, multiple_cnt=2)
        runner.config.candle_interval = 1
        runner.mtf_timeframes = runner._resolve_mtf_timeframes()
        runner.strategy_params = replace(runner.strategy_params, regime_ema_slow=200)
        runner.required_base_bars_for_regime = runner._required_base_bars_for_regime()
        runner.required_base_bars_for_mtf_minimums = runner._required_base_bars_for_mtf_minimums()

        base = datetime.datetime(2024, 1, 1, 6, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=i), 10000 + i) for i in range(3200)]

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

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreater(result.entry_fail_counts.get("regime_filter_fail:ema_trend_fail", 0), 0)
        self.assertEqual(result.entry_fail_counts.get("regime_filter_fail:insufficient_15m_candles", 0), 0)

    @patch("testing.backtest_runner.check_buy", return_value=True)
    @patch("testing.backtest_runner.check_sell", return_value=True)
    def test_run_segment_applies_costs_and_metrics(self, _check_sell, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2, spread_rate=0.001, slippage_rate=0.001)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + (10 * i)) for i in range(10)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreaterEqual(result.trades, 1)
        self.assertGreaterEqual(result.entries, result.closed_trades)
        self.assertGreaterEqual(result.fill_rate, 0)
        self.assertLessEqual(result.fill_rate, 1)
        self.assertIsInstance(result.sharpe, float)

    @patch("testing.backtest_runner.check_buy", return_value=True)
    @patch("testing.backtest_runner.check_sell", return_value=False)
    def test_run_segment_tracks_partial_take_profit_reason(self, _check_sell, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        prices = [100.0, 103.0, 103.5, 100.0, 99.0, 98.0]
        candles = [self._candle(base - datetime.timedelta(minutes=i), p) for i, p in enumerate(prices)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreaterEqual(result.exit_reason_counts.get("partial_take_profit", 0), 1)

    @patch("testing.backtest_runner.check_buy", return_value=True)
    @patch("testing.backtest_runner.check_sell", return_value=True)
    def test_sell_decision_rule_and_requires_both_signal_and_policy(self, _check_sell, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2, sell_decision_rule="and")
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        prices = [100.0, 100.5, 100.3, 100.2, 100.1, 100.0]
        candles = [self._candle(base - datetime.timedelta(minutes=i), p) for i, p in enumerate(prices)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertEqual(result.exit_reason_counts.get("signal_exit", 0), 0)

    @patch("testing.backtest_runner.debug_entry")
    def test_debug_mode_exports_dominant_entry_fail_code_when_signal_zero(self, debug_entry_mock):
        runner = BacktestRunner(
            buffer_cnt=3,
            multiple_cnt=2,
            path="/tmp/not_used_debug.xlsx",
            segment_report_path="/tmp/segments_debug.csv",
            debug_mode=True,
            debug_report_path="/tmp/entry_debug.csv",
        )
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=i), 100 + i) for i in range(12)]

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

        with patch.object(runner, "_load_or_create_data", return_value=(candles, 0)):
            runner.run()

        debug_df = pd.read_csv("/tmp/entry_debug.csv")
        self.assertTrue((debug_df["signal_zero"] == True).all())
        self.assertTrue((debug_df["dominant_fail_code"] == "no_selected_zone").all())
        self.assertGreater(debug_df["fail_no_selected_zone"].sum(), 0)

    @patch("testing.backtest_runner.check_buy", return_value=True)
    @patch("testing.backtest_runner.check_sell", return_value=False)
    def test_run_segment_reentry_cooldown_zero_vs_positive(self, _check_sell, _check_buy):
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        prices = [100.0, 90.0, 100.0, 90.0, 100.0, 90.0, 100.0, 90.0, 100.0]
        candles = [self._candle(base - datetime.timedelta(minutes=i), p) for i, p in enumerate(prices)]

        runner_no_cooldown = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        runner_no_cooldown.config.reentry_cooldown_bars = 0
        result_no_cooldown = runner_no_cooldown._run_segment(candles, init_amount=1_000_000, segment_id=1)

        runner_with_cooldown = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        runner_with_cooldown.config.reentry_cooldown_bars = 2
        runner_with_cooldown.config.cooldown_on_loss_exits_only = True
        result_with_cooldown = runner_with_cooldown._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreater(result_no_cooldown.trades, result_with_cooldown.trades)
        self.assertGreater(result_with_cooldown.entry_fail_counts.get("fail_reentry_cooldown", 0), 0)



    def test_fill_rate_uses_candidate_entries(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)

        total_return, return_per_trade, cagr, mdd, sharpe, fill_rate, cagr_valid, observed_days = runner._calc_metrics(
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

        total_return, return_per_trade, cagr, mdd, sharpe, fill_rate, cagr_valid, observed_days = runner._calc_metrics(
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
        candles = [self._candle(base - datetime.timedelta(minutes=i), 100 + i) for i in range(12)]

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
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2, path="/tmp/not_used.xlsx", segment_report_path="/tmp/segments.csv")
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=i), 100 + i) for i in range(12)]

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
                    exit_reason_counts={"signal_exit": 2, "trailing_stop": 1},
                )
                runner.run()

        df = pd.read_csv("/tmp/segments.csv")
        self.assertIn("exit_reason_signal_exit", df.columns)
        self.assertIn("exit_reason_trailing_stop", df.columns)
        self.assertIn("exit_reason_stop_loss_early_bar_share_pct", df.columns)

    def test_segment_csv_includes_fail_columns_when_trades_are_zero(self):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2, path="/tmp/not_used_fail.xlsx", segment_report_path="/tmp/segments_fail.csv")
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=i), 100 + i) for i in range(12)]

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
                    entry_fail_counts={"no_selected_zone": 2, "trigger_fail": 1, "regime_filter_fail:ema_trend_fail": 1},
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
        self.assertGreaterEqual(available["15m"], runner.strategy_params.min_candles_15m)

    def test_validate_mtf_capacity_warns_with_separated_min_and_regime_requirements(self):
        config = TradingConfig(do_not_trading=[], candle_interval=1, regime_filter_enabled=True, regime_ema_slow=200)
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


if __name__ == "__main__":
    unittest.main()
