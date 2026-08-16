import unittest
from dataclasses import replace

from core.config import TradingConfig
from core.decision_core import _normalize_exit_strategy_params
from core.strategy_registry import get_strategy
from core.strategies.nfi_v1 import evaluate_long_entry, should_exit_long


def candle(open_price: float, close_price: float, low_price: float, volume: float = 10.0):
    return {
        "opening_price": open_price,
        "trade_price": close_price,
        "high_price": max(open_price, close_price) + 1.0,
        "low_price": low_price,
        "candle_acc_trade_volume": volume,
    }


class NFIStrategyV1Test(unittest.TestCase):
    def setUp(self):
        base = TradingConfig(do_not_trading=[], strategy_name="nfi_v1").to_strategy_params()
        self.params = replace(
            base,
            min_candles_1m=3,
            min_candles_5m=6,
            min_candles_15m=8,
            regime_ema_fast=3,
            regime_ema_slow=5,
            rsi_period=3,
        )

    def _data(self, latest_volume: float = 20.0):
        closes_15m = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 108.0]
        candles_15m = [candle(close - 0.5, close, close - 1.0) for close in closes_15m]
        closes_5m = [95.0, 96.0, 97.0, 98.0, 99.0, 101.0, 90.0, 105.0]
        candles_5m = [
            candle(close - 0.5, close, close - 1.0, latest_volume if index == 0 else 10.0)
            for index, close in enumerate(reversed(closes_5m))
        ]
        candles_1m = [candle(104.0, 105.0, 104.0), candle(103.0, 104.0, 102.0), candle(102.0, 103.0, 101.0)]
        return {"1m": candles_1m, "5m": candles_5m, "15m": list(reversed(candles_15m))}

    def test_accepts_trend_pullback_with_volume_confirmation(self):
        signal = evaluate_long_entry(self._data(), self.params)

        self.assertTrue(signal.accepted)
        self.assertEqual(signal.reason, "ok")
        self.assertEqual(signal.diagnostics["entry_tag"], "trend_pullback_volume_confirmed")
        self.assertGreater(signal.diagnostics["r_value"], 0.0)
        self.assertTrue(signal.diagnostics["trend_pass"])
        self.assertTrue(signal.diagnostics["volume_pass"])
        self.assertAlmostEqual(signal.diagnostics["rsi"], 60.7142857143)

    def test_rejects_entry_when_volume_confirmation_is_missing(self):
        signal = evaluate_long_entry(self._data(latest_volume=10.5), self.params)

        self.assertFalse(signal.accepted)
        self.assertEqual(signal.reason, "pullback_confirmation_fail")
        self.assertFalse(signal.diagnostics["volume_pass"])

    def test_rejects_insufficient_candles_before_indicators(self):
        signal = evaluate_long_entry({"1m": [], "5m": [], "15m": []}, self.params)

        self.assertFalse(signal.accepted)
        self.assertEqual(signal.reason, "insufficient_candles")
        self.assertEqual(signal.diagnostics["r_value"], 0.0)

    def test_rejects_malformed_candle_without_crashing(self):
        signal = evaluate_long_entry(
            {"1m": [{}] * 3, "5m": [{}] * 6 + ["bad"], "15m": [{}] * 8},
            self.params,
        )

        self.assertFalse(signal.accepted)
        self.assertEqual(signal.reason, "malformed_candles")

        outer_signal = evaluate_long_entry(
            {"1m": None, "5m": [], "15m": []}, self.params
        )
        self.assertEqual(outer_signal.reason, "malformed_candles")

    def test_rejects_overbought_confirmation(self):
        data = self._data()
        for index, item in enumerate(data["5m"]):
            item["trade_price"] = 120.0 - index

        signal = evaluate_long_entry(data, self.params)

        self.assertFalse(signal.accepted)
        self.assertTrue(signal.diagnostics["rsi_overbought"])
        self.assertFalse(signal.diagnostics["rsi_pass"])

    def test_shared_exit_seam_normalizes_nfi_parameters(self):
        unnormalized = replace(
            self.params,
            strategy_name="ict_v1",
            take_profit_r=1.0,
        )
        normalized = _normalize_exit_strategy_params(
            get_strategy("nfi_v1"), unnormalized
        )

        self.assertEqual(normalized.strategy_name, "nfi_v1")
        self.assertGreaterEqual(normalized.take_profit_r, 1.5)

    def test_exits_at_stop_or_target(self):
        self.assertTrue(
            should_exit_long(
                {"1m": [candle(97.0, 97.0, 96.0)], "15m": []},
                self.params,
                entry_price=100.0,
                initial_stop_price=98.0,
                risk_per_unit=2.0,
            )
        )
        self.assertTrue(
            should_exit_long(
                {"1m": [candle(105.0, 105.0, 104.0)], "15m": []},
                self.params,
                entry_price=100.0,
                initial_stop_price=98.0,
                risk_per_unit=2.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
