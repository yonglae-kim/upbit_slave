import os
import warnings
import unittest
from unittest.mock import patch
from dataclasses import replace

from core.config import TradingConfig
from core.strategy import (
    check_buy,
    check_sell,
    debug_entry,
    cluster_sr_levels,
    detect_fvg_zones,
    detect_ob_zones,
    detect_sr_pivots,
    filter_active_zones,
    pick_best_zone,
    score_sr_levels,
    check_trigger_1m,
)


def make_candle(price: float, spread: float = 1.0, bull: bool = True):
    open_price = price - 0.3 if bull else price + 0.3
    close_price = price + 0.3 if bull else price - 0.3
    return {
        "opening_price": open_price,
        "trade_price": close_price,
        "high_price": price + spread,
        "low_price": price - spread,
    }


class MainSignalValidationTest(unittest.TestCase):
    def setUp(self):
        self.config = TradingConfig(do_not_trading=[])
        self.params = self.config.to_strategy_params()

    def _tf(self, c1, c5, c15):
        return {"1m": c1, "5m": c5, "15m": c15}

    def test_debug_entry_returns_required_fields(self):
        c15 = [make_candle(100 + (i % 6) - 3, spread=1.5) for i in range(160)]
        c5 = [make_candle(120 + i * 0.01) for i in range(160)]
        c1 = [make_candle(121 + i * 0.01) for i in range(120)]

        debug = debug_entry(self._tf(c1, c5, c15), self.params, side="buy")

        for key in ["len_c1", "len_c5", "len_c15", "zones_total", "zones_active", "selected_zone", "trigger_pass", "final_pass"]:
            self.assertIn(key, debug)
        self.assertEqual(debug["final_pass"], check_buy(self._tf(c1, c5, c15), self.params))


    def test_trigger_strict_requires_same_candle_zone_and_confirmations(self):
        params = replace(self.params, trigger_mode="strict", trigger_breakout_lookback=2, trigger_rejection_wick_ratio=0.3)
        zone = {"lower": 99.0, "upper": 101.0}
        candles = [
            {"opening_price": 101.0, "trade_price": 103.0, "high_price": 103.5, "low_price": 99.0},
            {"opening_price": 100.0, "trade_price": 100.2, "high_price": 101.0, "low_price": 99.5},
            {"opening_price": 100.1, "trade_price": 100.0, "high_price": 100.8, "low_price": 99.4},
            {"opening_price": 100.0, "trade_price": 99.9, "high_price": 100.5, "low_price": 99.3},
        ]

        self.assertTrue(check_trigger_1m(candles, zone, side="buy", params=params))

    def test_trigger_balanced_passes_with_prior_zone_touch_then_breakout(self):
        zone = {"lower": 99.0, "upper": 101.0}
        candles = [
            {"opening_price": 103.2, "trade_price": 104.0, "high_price": 104.2, "low_price": 103.0},
            {"opening_price": 101.5, "trade_price": 101.6, "high_price": 102.0, "low_price": 101.2},
            {"opening_price": 100.4, "trade_price": 100.0, "high_price": 101.0, "low_price": 99.4},
            {"opening_price": 100.0, "trade_price": 100.1, "high_price": 100.5, "low_price": 99.6},
            {"opening_price": 99.8, "trade_price": 99.9, "high_price": 100.4, "low_price": 99.2},
        ]
        strict_params = replace(self.params, trigger_mode="strict", trigger_breakout_lookback=2, trigger_zone_lookback=4, trigger_confirm_lookback=2)
        balanced_params = replace(self.params, trigger_mode="balanced", trigger_breakout_lookback=2, trigger_zone_lookback=4, trigger_confirm_lookback=2)

        self.assertFalse(check_trigger_1m(candles, zone, side="buy", params=strict_params))
        self.assertTrue(check_trigger_1m(candles, zone, side="buy", params=balanced_params))


    def test_trigger_adaptive_accepts_recent_zone_touch_with_rejection(self):
        zone = {"lower": 99.0, "upper": 101.0}
        candles = [
            {"opening_price": 101.2, "trade_price": 101.4, "high_price": 101.7, "low_price": 101.1},
            {"opening_price": 100.6, "trade_price": 100.9, "high_price": 101.1, "low_price": 99.4},
            {"opening_price": 100.8, "trade_price": 101.0, "high_price": 101.2, "low_price": 99.6},
            {"opening_price": 100.9, "trade_price": 101.1, "high_price": 101.3, "low_price": 99.8},
        ]
        strict_params = replace(self.params, trigger_mode="strict", trigger_breakout_lookback=2, trigger_zone_lookback=3, trigger_confirm_lookback=2)
        adaptive_params = replace(self.params, trigger_mode="adaptive", trigger_breakout_lookback=2, trigger_zone_lookback=3, trigger_confirm_lookback=2)

        self.assertFalse(check_trigger_1m(candles, zone, side="buy", params=strict_params))
        self.assertTrue(check_trigger_1m(candles, zone, side="buy", params=adaptive_params))

    def test_default_trigger_mode_is_adaptive(self):
        self.assertEqual(self.params.trigger_mode, "adaptive")
    def test_debug_entry_exposes_trigger_fail_code_details(self):
        c15 = [make_candle(100 + (i % 6) - 3, spread=1.5) for i in range(160)]
        c5 = [make_candle(120 + i * 0.01) for i in range(160)]
        c1 = [make_candle(121 + i * 0.01) for i in range(120)]
        params = replace(self.params, trigger_mode="strict")

        with patch("core.strategy.detect_fvg_zones", return_value=[]), patch(
            "core.strategy.detect_ob_zones",
            return_value=[{"type": "ob", "bias": "bullish", "lower": 110.0, "upper": 130.0, "created_index": 1}],
        ), patch("core.strategy.pick_best_zone", return_value={"type": "ob", "bias": "bullish", "lower": 110.0, "upper": 130.0, "created_index": 1}):
            debug = debug_entry(self._tf(c1, c5, c15), params, side="buy")

        self.assertEqual(debug["fail_code"], "trigger_strict_breakout_miss")

    def test_sr_only_does_not_trigger_entry(self):
        c15 = [make_candle(100 + (i % 6) - 3, spread=1.5) for i in range(140)]
        c5 = [make_candle(120 + i * 0.01) for i in range(140)]
        c1 = [make_candle(121 + i * 0.01) for i in range(120)]
        self.assertFalse(check_buy(self._tf(c1, c5, c15), self.params))

    def test_obfvg_only_does_not_trigger_without_sr_context(self):
        c15 = [make_candle(200 + i * 0.5, spread=0.2) for i in range(140)]
        c5 = [make_candle(100 + (i % 4), spread=2.0, bull=(i % 2 == 0)) for i in range(140)]
        c1 = [make_candle(102 + (i % 3), spread=1.2, bull=(i % 2 == 1)) for i in range(120)]
        self.assertFalse(check_buy(self._tf(c1, c5, c15), self.params))

    def test_intersection_priority_picks_overlap_zone(self):
        sr_levels = [{"bias": "support", "lower": 99.0, "upper": 101.0, "mid": 100.0, "touches": 3, "last_index": 10}]
        setup_zones = [
            {"type": "ob", "bias": "bullish", "lower": 95.0, "upper": 96.0, "created_index": 50},
            {"type": "fvg", "bias": "bullish", "lower": 99.5, "upper": 100.5, "created_index": 51},
        ]
        best = pick_best_zone(sr_levels, setup_zones, side="buy", params=self.params)
        self.assertIsNotNone(best)
        self.assertEqual(best["lower"], 99.5)


    def test_check_buy_uses_lookback_index_for_active_zone_filter(self):
        c15 = [make_candle(100 + (i % 6) - 3, spread=1.5) for i in range(160)]
        c5 = [make_candle(120 + i * 0.01) for i in range(160)]
        c1 = [make_candle(121 + i * 0.01) for i in range(120)]

        with patch("core.strategy.detect_fvg_zones", return_value=[]), patch(
            "core.strategy.detect_ob_zones",
            return_value=[{"type": "ob", "bias": "bullish", "lower": 110.0, "upper": 130.0, "created_index": 1}],
        ), patch("core.strategy.filter_active_zones", return_value=[]) as active_mock:
            check_buy(self._tf(c1, c5, c15), self.params)

        self.assertEqual(active_mock.call_args.kwargs["current_index"], self.params.ob_lookback_bars)

    def test_zone_invalidation_and_expiry(self):
        zones = [
            {"type": "ob", "bias": "bullish", "lower": 99.0, "upper": 101.0, "created_index": 1},
            {"type": "fvg", "bias": "bullish", "lower": 100.0, "upper": 102.0, "created_index": 100},
        ]
        active = filter_active_zones(zones, current_price=95.0, current_index=160, params=self.params)
        self.assertEqual(active, [])


    def test_sequence_input_is_disabled_by_default(self):
        c1 = [make_candle(100 + i * 0.1) for i in range(160)]
        os.environ.pop("STRATEGY_ALLOW_SEQUENCE_FALLBACK_FOR_TESTS", None)
        self.assertFalse(check_buy(c1, self.params))

    def test_sequence_input_fallback_is_test_only_with_warning(self):
        c1 = [make_candle(100 + i * 0.1) for i in range(160)]
        with patch.dict(os.environ, {"STRATEGY_ALLOW_SEQUENCE_FALLBACK_FOR_TESTS": "1"}, clear=False):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                _ = check_buy(c1, self.params)

        self.assertTrue(any("test-only" in str(w.message) for w in caught))

    def test_sell_requires_signal_and_profit_threshold(self):
        c15 = [make_candle(100 + (i % 5) - 2, spread=2.0) for i in range(160)]
        c5 = [make_candle(100 + (i % 5), spread=2.0, bull=(i % 2 == 0)) for i in range(160)]
        c1 = [make_candle(100 + (i % 3), spread=1.3, bull=(i % 2 == 0)) for i in range(140)]
        self.assertFalse(check_sell(self._tf(c1, c5, c15), avg_buy_price=300.0, params=self.params))

    @patch("core.strategy._check_entry", return_value=True)
    def test_sell_requires_profit_gate_when_enabled(self, _entry_mock):
        c1 = [make_candle(100.0)]
        c5 = [make_candle(100.0) for _ in range(160)]
        c15 = [make_candle(100.0) for _ in range(160)]
        params = replace(self.params, sell_requires_profit=True, sell_profit_threshold=1.01)

        self.assertFalse(check_sell(self._tf(c1, c5, c15), avg_buy_price=200.0, params=params))

    @patch("core.strategy._check_entry", return_value=True)
    def test_sell_skips_profit_gate_when_disabled(self, _entry_mock):
        c1 = [make_candle(100.0)]
        c5 = [make_candle(100.0) for _ in range(160)]
        c15 = [make_candle(100.0) for _ in range(160)]
        params = replace(self.params, sell_requires_profit=False, sell_profit_threshold=1.5)

        self.assertTrue(check_sell(self._tf(c1, c5, c15), avg_buy_price=200.0, params=params))


    def test_sr_scoring_reflects_touch_recency_volume(self):
        sr_levels = [
            {"bias": "support", "lower": 99.0, "upper": 100.0, "mid": 99.5, "touches": 2, "last_index": 40, "turnover": 1000.0},
            {"bias": "support", "lower": 98.0, "upper": 99.0, "mid": 98.5, "touches": 4, "last_index": 90, "turnover": 3000.0},
        ]

        scored = score_sr_levels(sr_levels, total_bars=120, params=self.params)

        self.assertGreater(scored[0]["score"], scored[1]["score"])
        self.assertEqual(scored[0]["mid"], 98.5)



    def _make_fvg_candles(self, base_price: float, gap: float) -> list[dict[str, float]]:
        oldest = [
            {
                "opening_price": base_price - 0.2,
                "trade_price": base_price,
                "high_price": base_price,
                "low_price": base_price - 1.0,
            },
            {
                "opening_price": base_price,
                "trade_price": base_price + 6.0,
                "high_price": base_price + 7.0,
                "low_price": base_price - 1.0,
            },
            {
                "opening_price": base_price + gap + 0.2,
                "trade_price": base_price + gap + 0.5,
                "high_price": base_price + gap + 1.0,
                "low_price": base_price + gap,
            },
        ]
        return list(reversed(oldest))

    def test_fvg_min_width_uses_krw_tick_boundaries(self):
        params = replace(self.params, fvg_min_width_atr_mult=0.0, displacement_min_atr_mult=0.0, fvg_min_width_ticks=2)

        boundary_cases = [
            (1000.0, 1.0),
            (10000.0, 10.0),
            (100000.0, 50.0),
        ]

        for base_price, tick in boundary_cases:
            almost = detect_fvg_zones(self._make_fvg_candles(base_price, (tick * 2) - (tick * 0.1)), params)
            enough = detect_fvg_zones(self._make_fvg_candles(base_price, tick * 2), params)

            self.assertEqual(almost, [])
            self.assertEqual(len(enough), 1)

    def test_sr_pivot_and_zone_detectors_execute(self):
        c15 = [make_candle(100 + (i % 7) - 3, spread=2.0) for i in range(150)]
        pivots = detect_sr_pivots(c15, self.params.sr_pivot_left, self.params.sr_pivot_right)
        _ = cluster_sr_levels(pivots, self.params.sr_cluster_band_pct, self.params.sr_min_touches)

        c5 = [make_candle(100 + (i % 7), spread=2.0, bull=(i % 2 == 0)) for i in range(150)]
        _ = detect_fvg_zones(c5, self.params)
        _ = detect_ob_zones(c5, self.params)


if __name__ == "__main__":
    unittest.main()
