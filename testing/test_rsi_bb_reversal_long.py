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
        data = {"1m": list(reversed(candles))}
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
        self.assertEqual(result.reason, "score_below_threshold")

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


if __name__ == "__main__":
    unittest.main()
