import unittest


try:
    from core.strategies.ict_models import (
        detect_bullish_turtle_soup,
        detect_bullish_unicorn,
        is_price_in_ote_long_pocket,
    )
except ModuleNotFoundError:

    def detect_bullish_turtle_soup(*args, **kwargs) -> dict[str, object]:
        raise AssertionError("core.strategies.ict_models is unavailable")

    def detect_bullish_unicorn(*args, **kwargs) -> dict[str, object]:
        raise AssertionError("core.strategies.ict_models is unavailable")

    def is_price_in_ote_long_pocket(*args, **kwargs) -> dict[str, object]:
        raise AssertionError("core.strategies.ict_models is unavailable")


try:
    from core.strategies.ict_sessions import is_in_silver_bullet_window
except ModuleNotFoundError:

    def is_in_silver_bullet_window(*args, **kwargs) -> bool:
        raise AssertionError("core.strategies.ict_sessions is unavailable")


from core.config import TradingConfig


def as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise AssertionError(f"expected float-compatible value, got: {value!r}")


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


class ICTModelHelpersTest(unittest.TestCase):
    params = TradingConfig(do_not_trading=[]).to_strategy_params()

    def setUp(self):
        self.params = TradingConfig(do_not_trading=[]).to_strategy_params()

    def test_bullish_turtle_soup_passes_on_sweep_and_reclaim(self):
        self.assertTrue(callable(detect_bullish_turtle_soup))
        candles = [
            make_candle(100.4, 101.3, 101.5, 99.8),
            make_candle(99.4, 100.2, 100.4, 97.8),
            make_candle(100.8, 100.1, 101.0, 99.6),
            make_candle(101.4, 100.8, 101.8, 99.7),
            make_candle(101.8, 101.4, 102.0, 100.3),
        ]

        result = detect_bullish_turtle_soup(candles)

        self.assertTrue(result["pass"])
        self.assertEqual(result["reference_low"], 99.6)
        self.assertEqual(result["sweep_low"], 97.8)

    def test_bullish_turtle_soup_rejects_when_reclaim_fails(self):
        self.assertTrue(callable(detect_bullish_turtle_soup))
        candles = [
            make_candle(99.3, 99.4, 99.8, 98.9),
            make_candle(99.4, 99.2, 100.0, 97.8),
            make_candle(100.8, 100.1, 101.0, 99.6),
            make_candle(101.4, 100.8, 101.8, 99.7),
            make_candle(101.8, 101.4, 102.0, 100.3),
        ]

        result = detect_bullish_turtle_soup(candles)

        self.assertFalse(result["pass"])
        self.assertEqual(result["reason"], "no_reclaim")

    def test_bullish_unicorn_passes_on_valid_overlap(self):
        self.assertTrue(callable(detect_bullish_unicorn))
        candles = [
            make_candle(101.7, 101.8, 102.2, 101.4),
            make_candle(103.2, 104.8, 105.0, 103.0),
            make_candle(101.2, 103.0, 103.2, 101.0),
            make_candle(100.6, 101.0, 101.4, 100.2),
            make_candle(101.8, 100.8, 102.0, 100.0),
            make_candle(101.2, 101.8, 102.2, 100.8),
        ]

        result = detect_bullish_unicorn(candles, self.params)

        self.assertTrue(result["pass"])
        self.assertAlmostEqual(as_float(result["overlap_lower"]), 101.4)
        self.assertAlmostEqual(as_float(result["overlap_upper"]), 102.0)

    def test_bullish_unicorn_rejects_without_overlap(self):
        self.assertTrue(callable(detect_bullish_unicorn))
        candles = [
            make_candle(104.2, 104.4, 104.8, 103.9),
            make_candle(103.2, 104.8, 105.0, 103.0),
            make_candle(101.2, 103.0, 103.2, 101.0),
            make_candle(100.6, 101.0, 101.4, 100.2),
            make_candle(104.4, 103.5, 104.8, 103.2),
            make_candle(104.0, 104.4, 104.6, 103.8),
        ]

        result = detect_bullish_unicorn(candles, self.params)

        self.assertFalse(result["pass"])
        self.assertEqual(result["reason"], "no_overlap")

    def test_bullish_unicorn_rejects_entries_too_close_to_overlap_upper_bound(self):
        self.assertTrue(callable(detect_bullish_unicorn))
        candles = [
            make_candle(101.6, 101.9, 102.1, 101.5),
            make_candle(103.2, 104.8, 105.0, 103.0),
            make_candle(101.2, 103.0, 103.2, 101.0),
            make_candle(100.6, 101.0, 101.4, 100.2),
            make_candle(101.8, 100.8, 102.0, 100.0),
            make_candle(101.2, 101.8, 102.2, 100.8),
        ]

        result = detect_bullish_unicorn(candles, self.params)

        self.assertFalse(result["pass"])
        self.assertEqual(result["reason"], "entry_too_high_in_overlap")

    def test_ote_pocket_detection_passes_inside_discount_pocket(self):
        self.assertTrue(callable(is_price_in_ote_long_pocket))

        result = is_price_in_ote_long_pocket(
            price=106.5, dealing_range_low=100.0, dealing_range_high=120.0
        )

        self.assertTrue(result["pass"])
        self.assertAlmostEqual(as_float(result["pocket_lower"]), 104.2)
        self.assertAlmostEqual(as_float(result["pocket_upper"]), 107.6)

    def test_ote_pocket_detection_rejects_outside_discount_pocket(self):
        self.assertTrue(callable(is_price_in_ote_long_pocket))

        result = is_price_in_ote_long_pocket(
            price=109.2, dealing_range_low=100.0, dealing_range_high=120.0
        )

        self.assertFalse(result["pass"])
        self.assertEqual(result["reason"], "outside_ote_pocket")

    def test_silver_bullet_window_passes_inside_london_open_window(self):
        self.assertTrue(callable(is_in_silver_bullet_window))
        candle = make_candle(
            100.0,
            101.0,
            101.2,
            99.8,
            candle_time="2024-01-02T08:30:00",
        )

        self.assertTrue(is_in_silver_bullet_window(candle))

    def test_silver_bullet_window_passes_inside_new_york_am_window(self):
        self.assertTrue(callable(is_in_silver_bullet_window))
        candle = make_candle(
            100.0,
            101.0,
            101.2,
            99.8,
            candle_time="2024-01-02T15:30:00",
        )

        self.assertTrue(is_in_silver_bullet_window(candle))

    def test_silver_bullet_window_passes_inside_new_york_pm_window(self):
        self.assertTrue(callable(is_in_silver_bullet_window))
        candle = make_candle(
            100.0,
            101.0,
            101.2,
            99.8,
            candle_time="2024-01-02T19:30:00",
        )

        self.assertTrue(is_in_silver_bullet_window(candle))

    def test_silver_bullet_window_rejects_old_buggy_fifteen_hundred_slot(self):
        self.assertTrue(callable(is_in_silver_bullet_window))
        candle = make_candle(
            100.0,
            101.0,
            101.2,
            99.8,
            candle_time="2024-01-02T20:30:00",
        )

        self.assertFalse(is_in_silver_bullet_window(candle))


if __name__ == "__main__":
    unittest.main()
