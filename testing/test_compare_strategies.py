import sys
import types
import unittest

import pandas as pd

from core.config import TradingConfig

if "slave_constants" not in sys.modules:
    sys.modules["slave_constants"] = types.SimpleNamespace(ACCESS_KEY="x", SECRET_KEY="y", SERVER_URL="https://api.upbit.com")
from testing.backtest_runner import apply_strategy_profile
from testing.compare_strategies import _aggregate_segment_metrics, _split_is_oos


class CompareStrategiesTest(unittest.TestCase):
    def test_apply_strategy_profile_a_relaxes_filters(self):
        cfg = TradingConfig(do_not_trading=[])
        apply_strategy_profile(cfg, "a")

        self.assertEqual(cfg.required_signal_count, 2)
        self.assertFalse(cfg.rsi_neutral_filter_enabled)
        self.assertFalse(cfg.macd_histogram_filter_enabled)

    def test_aggregate_segment_metrics_includes_requested_fields(self):
        df = pd.DataFrame(
            [
                {
                    "period_return": 10.0,
                    "cagr": 12.0,
                    "win_rate": 55.0,
                    "avg_profit": 1.2,
                    "avg_loss": -0.8,
                    "expectancy": 0.3,
                    "mdd": 5.0,
                    "profit_loss_ratio": 1.5,
                    "trades": 10,
                    "observed_days": 30,
                    "avg_holding_minutes": 45,
                    "longest_no_trade_bars": 7,
                    "oos_start": "2026-01-01T00:00:00",
                },
                {
                    "period_return": -2.0,
                    "cagr": 8.0,
                    "win_rate": 45.0,
                    "avg_profit": 1.0,
                    "avg_loss": -1.0,
                    "expectancy": -0.1,
                    "mdd": 6.0,
                    "profit_loss_ratio": 0.9,
                    "trades": 8,
                    "observed_days": 30,
                    "avg_holding_minutes": 30,
                    "longest_no_trade_bars": 5,
                    "oos_start": "2026-02-01T00:00:00",
                },
            ]
        )

        metrics = _aggregate_segment_metrics(df)

        self.assertIn("total_return", metrics)
        self.assertIn("monthly_trades", metrics)
        self.assertIn("recent_12m", metrics)
        self.assertEqual(metrics["trades"], 18)
        self.assertGreaterEqual(metrics["longest_no_trade_bars"], 7)

    def test_split_is_oos_uses_second_half(self):
        df = pd.DataFrame([{"x": 1}, {"x": 2}, {"x": 3}, {"x": 4}])
        is_df, oos_df = _split_is_oos(df)

        self.assertEqual(len(is_df), 2)
        self.assertEqual(len(oos_df), 2)
        self.assertEqual(oos_df.iloc[0]["x"], 3)


if __name__ == "__main__":
    unittest.main()
