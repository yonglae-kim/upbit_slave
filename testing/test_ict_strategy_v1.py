import unittest
from dataclasses import replace

from core.decision_models import StrategySignal


try:
    from core.strategies.ict_v1 import evaluate_long_entry, should_exit_long
except ModuleNotFoundError:

    def evaluate_long_entry(*args, **kwargs) -> StrategySignal:
        raise AssertionError("core.strategies.ict_v1 is unavailable")

    def should_exit_long(*args, **kwargs) -> bool:
        raise AssertionError("core.strategies.ict_v1 is unavailable")


from core.config import TradingConfig


def make_candle(
    open_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
    candle_time: str | None = None,
):
    candle: dict[str, object] = {
        "opening_price": open_price,
        "trade_price": close_price,
        "high_price": high_price,
        "low_price": low_price,
    }
    if candle_time is not None:
        candle["candle_date_time_utc"] = candle_time
    return candle


class ICTStrategyV1Test(unittest.TestCase):
    params = replace(
        TradingConfig(do_not_trading=[], strategy_name="ict_v1").to_strategy_params(),
        min_candles_1m=3,
        min_candles_5m=4,
        min_candles_15m=12,
        min_candles_1h=3,
        trigger_breakout_lookback=2,
        trigger_zone_lookback=2,
        trigger_confirm_lookback=2,
        regime_ema_fast=2,
        regime_ema_slow=3,
        regime_adx_period=1,
        regime_slope_lookback=1,
        regime_adx_min=1.0,
        regime_1h_ema_fast=1,
        regime_1h_ema_slow=2,
        regime_1h_adx_period=1,
        regime_1h_adx_min=1.0,
    )

    def setUp(self):
        base = TradingConfig(
            do_not_trading=[], strategy_name="ict_v1"
        ).to_strategy_params()
        self.params = replace(
            base,
            min_candles_1m=3,
            min_candles_5m=4,
            min_candles_15m=12,
            min_candles_1h=3,
            trigger_breakout_lookback=2,
            trigger_zone_lookback=2,
            trigger_confirm_lookback=2,
            regime_ema_fast=2,
            regime_ema_slow=3,
            regime_adx_period=1,
            regime_slope_lookback=1,
            regime_adx_min=1.0,
            regime_1h_ema_fast=1,
            regime_1h_ema_slow=2,
            regime_1h_adx_period=1,
            regime_1h_adx_min=1.0,
        )

    def _candles_from_closes_15m(self, closes_oldest: list[float]):
        candles_oldest = [
            make_candle(
                close_price - 0.8,
                close_price,
                close_price + 0.5,
                close_price - 1.0,
            )
            for close_price in closes_oldest
        ]
        return list(reversed(candles_oldest))

    def _bullish_trigger_1m(
        self, *, latest_close: float = 101.8, candle_time: str | None = None
    ):
        latest_open = latest_close - 0.8
        return [
            make_candle(
                latest_open,
                latest_close,
                latest_close + 0.1,
                latest_open - 0.1,
                candle_time=candle_time,
            ),
            make_candle(
                latest_close - 1.4,
                latest_close - 0.9,
                latest_close - 0.8,
                latest_close - 1.5,
            ),
            make_candle(
                latest_close - 1.8,
                latest_close - 1.4,
                latest_close - 1.3,
                latest_close - 1.9,
            ),
            make_candle(
                latest_close - 2.1,
                latest_close - 1.8,
                latest_close - 1.7,
                latest_close - 2.2,
            ),
        ]

    def _non_breakout_1m(self):
        return [
            make_candle(101.0, 101.05, 101.1, 100.9),
            make_candle(100.7, 101.1, 101.2, 100.6),
            make_candle(100.3, 100.7, 100.8, 100.2),
            make_candle(100.1, 100.3, 100.4, 100.0),
        ]

    def _bullish_regime_15m(self):
        return self._candles_from_closes_15m(
            [
                100.0,
                100.8,
                101.6,
                102.4,
                103.2,
                104.0,
                105.0,
                106.0,
                107.2,
                109.0,
                114.0,
                116.0,
            ]
        )

    def _sideways_regime_15m(self):
        return self._candles_from_closes_15m(
            [
                110.0,
                109.9,
                109.8,
                109.7,
                109.6,
                109.5,
                109.4,
                109.3,
                109.2,
                109.1,
                109.0,
                108.9,
            ]
        )

    def _bullish_15m_but_bearish_1h(self):
        return self._candles_from_closes_15m(
            [
                100.0,
                101.0,
                102.0,
                103.0,
                104.0,
                105.0,
                106.0,
                107.0,
                104.0,
                105.0,
                106.0,
                106.5,
            ]
        )

    def _insufficient_1h_regime_15m(self):
        return [
            make_candle(113.0, 116.0, 116.5, 112.8),
            make_candle(109.0, 113.0, 113.5, 108.8),
            make_candle(104.0, 109.0, 109.5, 103.8),
            make_candle(100.0, 104.0, 104.5, 99.8),
        ]

    def _assert_accepted(self, signal: StrategySignal, expected_setup_model: str):
        self.assertIsInstance(signal, StrategySignal)
        self.assertTrue(signal.accepted)
        self.assertEqual(signal.reason, "ok")
        self.assertEqual(signal.diagnostics["setup_model"], expected_setup_model)
        self.assertGreater(signal.diagnostics["entry_price"], 0.0)
        self.assertGreater(signal.diagnostics["stop_price"], 0.0)
        self.assertGreater(signal.diagnostics["r_value"], 0.0)
        self.assertAlmostEqual(
            signal.diagnostics["entry_price"] - signal.diagnostics["stop_price"],
            signal.diagnostics["r_value"],
        )

    def _assert_rejected(self, signal: StrategySignal):
        self.assertIsInstance(signal, StrategySignal)
        self.assertFalse(signal.accepted)
        self.assertNotEqual(signal.reason, "ok")
        self.assertIn("setup_model", signal.diagnostics)
        self.assertEqual(signal.diagnostics["r_value"], 0.0)

    def test_accepts_turtle_soup_long_entry(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(100.4, 101.3, 101.5, 99.8),
                    make_candle(99.4, 100.2, 100.4, 97.8),
                    make_candle(100.8, 100.1, 101.0, 99.6),
                    make_candle(101.4, 100.8, 101.8, 99.7),
                    make_candle(101.8, 101.4, 102.0, 100.3),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_accepted(signal, "turtle_soup")
        self.assertTrue(signal.diagnostics["trigger_zone"])

    def test_rejects_turtle_soup_without_reclaim(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._non_breakout_1m(),
                "5m": [
                    make_candle(99.3, 99.4, 99.8, 98.9),
                    make_candle(99.4, 99.2, 100.0, 97.8),
                    make_candle(100.8, 100.1, 101.0, 99.6),
                    make_candle(101.4, 100.8, 101.8, 99.7),
                    make_candle(101.8, 101.4, 102.0, 100.3),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_accepts_unicorn_long_entry(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_accepted(signal, "unicorn")

    def test_rejects_valid_unicorn_setup_when_required_trigger_count_is_not_met(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(self.params, required_trigger_count=3),
        )

        self._assert_rejected(signal)
        self.assertEqual(signal.reason, "trigger_fail")
        self.assertEqual(signal.diagnostics["setup_model"], "unicorn")
        self.assertFalse(signal.diagnostics["trigger_result"]["pass"])
        self.assertGreater(signal.diagnostics.get("entry_score", 0.0), 0.0)

    def test_accepts_unicorn_zone_limit_entry_at_overlap_midpoint(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(self.params, entry_mode="zone_limit"),
        )

        self._assert_accepted(signal, "unicorn")
        self.assertAlmostEqual(signal.diagnostics["entry_price"], 101.7)

    def test_rejects_unicorn_zone_limit_when_midpoint_was_not_touched(self):
        signal = evaluate_long_entry(
            {
                "1m": [
                    make_candle(101.75, 101.8, 101.85, 101.75),
                    make_candle(100.4, 101.0, 101.1, 100.3),
                    make_candle(100.0, 100.4, 100.5, 99.9),
                ],
                "5m": [
                    make_candle(101.8, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(self.params, entry_mode="zone_limit"),
        )

        self._assert_rejected(signal)
        self.assertEqual(signal.reason, "limit_entry_unfilled")
        self.assertAlmostEqual(signal.diagnostics["preferred_entry_price"], 101.7)

    def test_rejects_unicorn_without_overlap(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._non_breakout_1m(),
                "5m": [
                    make_candle(104.2, 104.4, 104.8, 103.9),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(104.4, 103.5, 104.8, 103.2),
                    make_candle(104.0, 104.4, 104.6, 103.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_rejects_unicorn_entry_when_price_is_too_high_in_overlap(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(latest_close=101.9),
                "5m": [
                    make_candle(101.6, 101.9, 102.1, 101.5),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_accepts_silver_bullet_long_entry(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(
                    latest_close=101.8,
                    candle_time="2024-01-02T15:30:00",
                ),
                "5m": [
                    make_candle(101.6, 101.8, 102.0, 101.4),
                    make_candle(102.8, 104.3, 104.5, 102.6),
                    make_candle(100.8, 102.6, 102.8, 100.6),
                    make_candle(100.0, 100.6, 101.0, 99.8),
                    make_candle(100.2, 100.0, 100.4, 99.6),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_accepted(signal, "silver_bullet")
        self.assertGreater(signal.diagnostics.get("entry_score", 0.0), 0.0)
        self.assertGreater(signal.diagnostics.get("quality_score", 0.0), 0.0)

    def test_accepts_silver_bullet_zone_limit_entry_at_fvg_midpoint(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(
                    latest_close=102.0,
                    candle_time="2024-01-02T15:30:00",
                ),
                "5m": [
                    make_candle(101.6, 101.8, 102.0, 101.4),
                    make_candle(102.8, 104.3, 104.5, 102.6),
                    make_candle(100.8, 102.6, 102.8, 100.6),
                    make_candle(100.0, 100.6, 101.0, 99.8),
                    make_candle(100.2, 100.0, 100.4, 99.6),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(self.params, entry_mode="zone_limit"),
        )

        self._assert_accepted(signal, "silver_bullet")
        self.assertAlmostEqual(signal.diagnostics["entry_price"], 101.8)

    def test_rejects_silver_bullet_outside_window(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(
                    latest_close=101.8,
                    candle_time="2024-01-02T17:30:00",
                ),
                "5m": [
                    make_candle(101.6, 101.8, 102.0, 101.4),
                    make_candle(102.8, 104.3, 104.5, 102.6),
                    make_candle(100.8, 102.6, 102.8, 100.6),
                    make_candle(100.0, 100.6, 101.0, 99.8),
                    make_candle(100.2, 100.0, 100.4, 99.6),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_rejects_ote_long_entry_below_default_score_threshold(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(latest_close=104.8),
                "5m": [
                    make_candle(109.5, 109.2, 109.8, 108.8),
                    make_candle(109.8, 109.7, 110.0, 109.1),
                    make_candle(110.2, 109.9, 110.4, 109.5),
                    make_candle(110.6, 110.1, 110.8, 109.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)
        self.assertEqual(signal.reason, "score_below_threshold")

    def test_accepts_ote_long_entry_when_threshold_allows_model_score(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(latest_close=104.8),
                "5m": [
                    make_candle(109.5, 109.2, 109.8, 108.8),
                    make_candle(109.8, 109.7, 110.0, 109.1),
                    make_candle(110.2, 109.9, 110.4, 109.5),
                    make_candle(110.6, 110.1, 110.8, 109.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(self.params, entry_score_threshold=2.0),
        )

        self._assert_accepted(signal, "ote")
        self.assertGreater(signal.diagnostics.get("entry_score", 0.0), 0.0)
        self.assertGreater(signal.diagnostics.get("quality_score", 0.0), 0.0)

    def test_rejects_low_quality_ote_setup_before_shared_sizing(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(latest_close=104.8),
                "5m": [
                    make_candle(109.5, 109.2, 109.8, 108.8),
                    make_candle(109.8, 109.7, 110.0, 109.1),
                    make_candle(110.2, 109.9, 110.4, 109.5),
                    make_candle(110.6, 110.1, 110.8, 109.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(
                self.params,
                entry_score_threshold=2.0,
                quality_score_low_threshold=0.6,
            ),
        )

        self._assert_rejected(signal)
        self.assertEqual(signal.reason, "quality_gate_fail")
        self.assertEqual(signal.diagnostics["setup_model"], "ote")
        self.assertEqual(signal.diagnostics["quality_bucket"], "low")
        self.assertLess(signal.diagnostics.get("quality_score", 0.0), 0.6)

    def test_accepts_ote_zone_limit_entry_at_pocket_midpoint(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(latest_close=104.3),
                "5m": [
                    make_candle(109.5, 109.2, 109.8, 108.8),
                    make_candle(109.8, 109.7, 110.0, 109.1),
                    make_candle(110.2, 109.9, 110.4, 109.5),
                    make_candle(110.6, 110.1, 110.8, 109.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            replace(self.params, entry_mode="zone_limit", entry_score_threshold=2.0),
        )

        self._assert_accepted(signal, "ote")
        self.assertAlmostEqual(signal.diagnostics["entry_price"], 103.5725)

    def test_rejects_ote_outside_pocket(self):
        self.assertTrue(callable(evaluate_long_entry))
        signal = evaluate_long_entry(
            {
                "1m": self._non_breakout_1m(),
                "5m": [
                    make_candle(109.5, 109.2, 109.8, 108.8),
                    make_candle(109.8, 109.7, 110.0, 109.1),
                    make_candle(110.2, 109.9, 110.4, 109.5),
                    make_candle(110.6, 110.1, 110.8, 109.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_rejects_valid_setup_without_bullish_micro_trigger(self):
        signal = evaluate_long_entry(
            {
                "1m": self._non_breakout_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_rejects_entry_when_regime_filter_is_sideways(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._sideways_regime_15m(),
            },
            self.params,
        )

        self._assert_rejected(signal)

    def test_rejects_entry_when_derived_1h_bias_disagrees(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._bullish_15m_but_bearish_1h(),
            },
            self.params,
        )

        self._assert_rejected(signal)
        self.assertEqual(signal.reason, "regime_filter_fail")
        self.assertFalse(signal.diagnostics["regime_1h_diagnostics"]["pass"])

    def test_rejects_entry_when_15m_history_cannot_build_required_1h_window(self):
        signal = evaluate_long_entry(
            {
                "1m": self._bullish_trigger_1m(),
                "5m": [
                    make_candle(101.7, 101.8, 102.2, 101.4),
                    make_candle(103.2, 104.8, 105.0, 103.0),
                    make_candle(101.2, 103.0, 103.2, 101.0),
                    make_candle(100.6, 101.0, 101.4, 100.2),
                    make_candle(101.8, 100.8, 102.0, 100.0),
                    make_candle(101.2, 101.8, 102.2, 100.8),
                ],
                "15m": self._insufficient_1h_regime_15m(),
            },
            replace(self.params, min_candles_15m=4, min_candles_1h=3),
        )

        self._assert_rejected(signal)
        self.assertEqual(signal.reason, "regime_filter_fail")
        self.assertEqual(
            signal.diagnostics["regime_1h_diagnostics"]["reason"],
            "insufficient_1h_candles",
        )

    def test_should_exit_long_triggers_at_tp2_multiple(self):
        self.assertTrue(callable(should_exit_long))

        should_exit = should_exit_long(
            {"1m": [make_candle(109.8, 110.0, 110.2, 109.7)]},
            self.params,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
        )

        self.assertTrue(should_exit)

    def test_should_exit_long_holds_below_tp2_multiple(self):
        self.assertTrue(callable(should_exit_long))

        should_exit = should_exit_long(
            {"1m": [make_candle(107.3, 107.5, 107.6, 107.2)]},
            self.params,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
        )

        self.assertFalse(should_exit)


if __name__ == "__main__":
    unittest.main()
