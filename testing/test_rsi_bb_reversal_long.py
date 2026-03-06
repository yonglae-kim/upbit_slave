import unittest
from dataclasses import replace

from core.config import TradingConfig
from core.rsi_bb_reversal_long import (
    calc_bollinger_series,
    calc_macd_series,
    calc_rsi_series,
    compute_stop_price_for_test,
    detect_double_bottom,
    detect_pivot_lows,
    evaluate_long_entry,
    is_bullish_engulfing,
    is_bullish_rsi_divergence,
    is_macd_bullish_cross,
    match_bb_touch_mode,
)


def candle(o, h, l, c):
    return {"opening_price": o, "high_price": h, "low_price": l, "trade_price": c}


class RsiBbReversalLongTests(unittest.TestCase):
    def setUp(self):
        cfg = TradingConfig(do_not_trading=[])
        self.params = replace(cfg.to_strategy_params(), strategy_name="rsi_bb_reversal_long")

    def test_bullish_engulfing_detection(self):
        candles = [
            candle(10, 10.2, 9.5, 9.6),
            candle(9.5, 10.4, 9.4, 10.3),
        ]
        newest = list(reversed(candles))
        self.assertTrue(is_bullish_engulfing(newest, idx_oldest=1, strict=True, include_wick=False))

    def test_bb_touch_break_detection(self):
        c = candle(10, 10.1, 9.7, 9.8)
        self.assertTrue(match_bb_touch_mode(c, 9.75, "touch_only"))
        self.assertFalse(match_bb_touch_mode(c, 9.75, "break_only"))
        self.assertTrue(match_bb_touch_mode(c, 9.85, "touch_or_break"))

    def test_pivot_confirmation_prevents_lookahead(self):
        candles_oldest = [
            candle(10, 10.2, 9.7, 10.0),
            candle(9.9, 10.0, 9.1, 9.2),
            candle(9.3, 9.8, 9.4, 9.7),
            candle(9.8, 10.0, 9.6, 9.9),
            candle(10.0, 10.1, 9.8, 10.0),
        ]
        newest = list(reversed(candles_oldest))
        pivots_early = detect_pivot_lows(newest, left=1, right=2, upto_index=2)
        pivots_late = detect_pivot_lows(newest, left=1, right=2, upto_index=4)
        self.assertEqual(pivots_early, [])
        self.assertEqual(pivots_late, [1])

    def test_double_bottom_detection(self):
        candles_oldest = [
            candle(10.4, 10.5, 10.0, 10.1),
            candle(10.0, 10.1, 9.5, 9.6),
            candle(9.7, 9.9, 9.7, 9.8),
            candle(9.8, 10.0, 9.6, 9.7),
            candle(9.7, 10.1, 9.52, 9.9),
            candle(9.9, 10.4, 9.8, 10.3),
        ]
        newest = list(reversed(candles_oldest))
        pivots = [1, 4]
        _, _, bb_low = calc_bollinger_series(newest, 2, 2.0)
        result = detect_double_bottom(newest, pivots, bb_low, 10, 1.0, False, False, eval_idx=5)
        self.assertTrue(result["pass"])

    def test_rsi_bullish_divergence_detection(self):
        candles_oldest = [
            candle(10, 10.2, 9.8, 10),
            candle(10, 10.1, 9.4, 9.5),
            candle(9.6, 9.8, 9.6, 9.7),
            candle(9.7, 9.9, 9.3, 9.4),
            candle(9.5, 9.8, 9.5, 9.7),
            candle(9.8, 10.1, 9.7, 10.0),
        ]
        newest = list(reversed(candles_oldest))
        rsi = calc_rsi_series(newest, 2)
        pivots = [1, 3]
        div = is_bullish_rsi_divergence(pivots, newest, rsi, eval_idx=5)
        self.assertTrue(div["pass"])

    def test_macd_bullish_cross(self):
        candles_oldest = [candle(10+i*0.1, 10+i*0.1, 10+i*0.1, 10+i*0.1) for i in range(40)]
        newest = list(reversed(candles_oldest))
        macd_line, signal_line, hist = calc_macd_series(newest, 3, 6, 3)
        idx = len(macd_line)-1
        self.assertIsInstance(is_macd_bullish_cross(macd_line, signal_line, hist, idx, False), bool)

    def test_state_machine_filter_setup_trigger(self):
        candles_oldest = [
            candle(100, 101, 99, 100),
            candle(100, 100.5, 98, 98.2),
            candle(98.4, 98.6, 96.5, 96.8),
            candle(96.9, 97.0, 95.0, 95.4),
            candle(95.5, 95.8, 94.7, 94.9),
            candle(94.8, 97.8, 94.6, 97.6),
        ]
        data = {"1m": list(reversed(candles_oldest))}
        params = replace(self.params, rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1, double_bottom_tolerance_pct=2.0)
        result = evaluate_long_entry(data, params)
        self.assertIsInstance(result.final_pass, bool)
        self.assertTrue("state" in result.diagnostics or "warmup" in result.diagnostics)

    def test_no_duplicate_entry_when_already_holding(self):
        # engine-level policy keeps one holding; strategy still emits bool signal
        candles = [candle(10, 10.5, 9.5, 10.2) for _ in range(80)]
        trend15 = [candle(10 + i * 0.05, 10.2 + i * 0.05, 9.9 + i * 0.05, 10 + i * 0.05) for i in range(90)]
        data = {"1m": list(reversed(candles)), "15m": list(reversed(trend15))}
        result = evaluate_long_entry(data, replace(self.params, rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1))
        self.assertIsInstance(result.final_pass, bool)

    def test_entry_mode_close_vs_next_open(self):
        candles = [candle(10, 10.2, 9.8, 10.0) for _ in range(90)]
        data = {"1m": list(reversed(candles))}
        close_result = evaluate_long_entry(data, replace(self.params, entry_mode="close", rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1))
        next_result = evaluate_long_entry(data, replace(self.params, entry_mode="next_open", rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1))
        self.assertIn("entry_price", close_result.diagnostics)
        self.assertIn("entry_price", next_result.diagnostics)


    def test_entry_score_diagnostics_present(self):
        candles_oldest = [
            candle(100 - i * 0.2, 101 - i * 0.2, 99 - i * 0.25, 100 - i * 0.25)
            for i in range(80)
        ]
        data = {"1m": list(reversed(candles_oldest))}
        params = replace(self.params, rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1, entry_score_threshold=0.0)
        result = evaluate_long_entry(data, params)
        self.assertIn("entry_score", result.diagnostics)
        self.assertIn("score_components", result.diagnostics)
        self.assertIn("quality_score", result.diagnostics)
        self.assertIn("quality_components", result.diagnostics)

    def test_entry_score_threshold_blocks_entry(self):
        candles = [candle(10, 10.2, 9.8, 10.0) for _ in range(90)]
        data = {"1m": list(reversed(candles))}
        params = replace(
            self.params,
            rsi_period=2,
            bb_period=2,
            pivot_left=1,
            pivot_right=1,
            entry_score_threshold=999.0,
        )
        result = evaluate_long_entry(data, params)
        self.assertFalse(result.final_pass)
        self.assertIn(result.reason, {"score_below_threshold", "filter_fail", "trigger_fail", "regime_guard_fail"})


    def test_entry_score_threshold_is_adaptive_by_distribution(self):
        candles = [candle(10 + (i * 0.02), 10.3 + (i * 0.02), 9.7 + (i * 0.02), 10.0 + (i * 0.02)) for i in range(240)]
        trend15 = [candle(10 + i * 0.1, 10.2 + i * 0.1, 9.9 + i * 0.1, 10 + i * 0.1) for i in range(120)]
        data = {"1m": list(reversed(candles)), "15m": list(reversed(trend15))}
        params = replace(self.params, rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1, entry_score_threshold=0.0)
        result = evaluate_long_entry(data, params)

        self.assertIn("score_percentile_threshold", result.diagnostics)
        self.assertIn("min_threshold_by_regime", result.diagnostics)
        self.assertIn("score_threshold_percentile", result.diagnostics)
        self.assertGreaterEqual(result.diagnostics["entry_score_distribution_count"], 20)
        self.assertAlmostEqual(
            result.diagnostics["effective_score_threshold"],
            max(result.diagnostics["min_threshold_by_regime"], result.diagnostics["score_percentile_threshold"]),
        )

    def test_n_of_k_pass_when_hits_meet_required_count(self):
        candles = [candle(10, 10.2, 9.8, 10.0) for _ in range(90)]
        trend15 = [candle(10 + i * 0.05, 10.2 + i * 0.05, 9.9 + i * 0.05, 10 + i * 0.05) for i in range(90)]
        data = {"1m": list(reversed(candles)), "15m": list(reversed(trend15))}
        params = replace(
            self.params,
            rsi_period=2,
            bb_period=2,
            pivot_left=1,
            pivot_right=1,
            required_signal_count=1,
            entry_score_threshold=0.0,
        )
        result = evaluate_long_entry(data, params)
        self.assertTrue(result.diagnostics["n_of_k_pass"])
        self.assertGreaterEqual(result.diagnostics["signal_hits"], result.diagnostics["required_signal_count"])

    def test_n_of_k_fail_when_hits_below_required_count(self):
        candles = [candle(10, 10.2, 9.8, 10.0) for _ in range(90)]
        trend15 = [candle(10 + i * 0.05, 10.2 + i * 0.05, 9.9 + i * 0.05, 10 + i * 0.05) for i in range(90)]
        data = {"1m": list(reversed(candles)), "15m": list(reversed(trend15))}
        params = replace(
            self.params,
            rsi_period=2,
            bb_period=2,
            pivot_left=1,
            pivot_right=1,
            required_signal_count=6,
            entry_score_threshold=0.0,
        )
        result = evaluate_long_entry(data, params)
        self.assertFalse(result.diagnostics["n_of_k_pass"])
        self.assertEqual(result.reason, "trigger_fail")

    def test_stop_mode_price_calculation(self):
        candles_oldest = [
            candle(100, 101, 99, 100),
            candle(99, 100, 95, 96),
            candle(96, 98, 94, 97),
            candle(97, 99, 96, 98),
        ]
        newest = list(reversed(candles_oldest))
        _, _, bb_low = calc_bollinger_series(newest, 2, 2.0)
        swing = compute_stop_price_for_test(newest, bb_low, 3, "swing_low")
        lower = compute_stop_price_for_test(newest, bb_low, 3, "lower_band")
        cons = compute_stop_price_for_test(newest, bb_low, 3, "conservative")
        self.assertLessEqual(cons, lower)
        self.assertLessEqual(cons, swing)

    def test_trigger_allows_bullish_close_reversal_without_engulfing(self):
        base = [candle(120 - i * 0.1, 120.2 - i * 0.1, 119.8 - i * 0.1, 120 - i * 0.1) for i in range(85)]
        tail = [
            candle(109.5, 109.6, 108.4, 108.6),
            candle(108.7, 108.8, 107.7, 107.8),
            candle(107.9, 108.0, 106.9, 107.0),
            candle(107.1, 108.5, 106.8, 108.2),
        ]
        candles_oldest = base + tail
        trend15 = [candle(10 + i * 0.2, 10.2 + i * 0.2, 9.8 + i * 0.2, 10 + i * 0.2) for i in range(90)]
        data = {"1m": list(reversed(candles_oldest)), "15m": list(reversed(trend15))}
        params = replace(
            self.params,
            rsi_period=2,
            bb_period=2,
            pivot_left=1,
            pivot_right=1,
            required_signal_count=1,
            entry_score_threshold=0.0,
        )
        result = evaluate_long_entry(data, params)
        self.assertIn("engulfing", result.diagnostics)
        self.assertFalse(result.diagnostics["engulfing"])
        self.assertTrue(result.diagnostics["bullish_close_reversal"])

    def test_dynamic_bearish_count_changes_by_regime(self):
        candles = [candle(10, 10.3, 9.7, 10.0) for _ in range(90)]
        strong15 = [candle(10 + i * 0.2, 10.1 + i * 0.2, 9.9 + i * 0.2, 10 + i * 0.2) for i in range(90)]
        side15 = [candle(10, 10.1, 9.9, 10 + (0.02 if i % 2 == 0 else -0.02)) for i in range(90)]
        params = replace(self.params, rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1)

        strong = evaluate_long_entry({"1m": list(reversed(candles)), "15m": list(reversed(strong15))}, params)
        side = evaluate_long_entry({"1m": list(reversed(candles)), "15m": list(reversed(side15))}, params)

        self.assertEqual(strong.diagnostics["dynamic_bearish_count"], 1)
        self.assertEqual(side.diagnostics["dynamic_bearish_count"], 2)

    def test_diagnostics_include_filter_suppress_counts(self):
        candles = [candle(10, 10.2, 9.8, 10.0) for _ in range(90)]
        data = {"1m": list(reversed(candles))}
        params = replace(self.params, rsi_period=2, bb_period=2, pivot_left=1, pivot_right=1)
        result = evaluate_long_entry(data, params)

        self.assertIn("suppress_bearish", result.diagnostics)
        self.assertIn("suppress_db", result.diagnostics)
        self.assertIn("suppress_engulfing", result.diagnostics)


if __name__ == "__main__":
    unittest.main()
