import os
import tempfile
import unittest
from pathlib import Path

from core.config_loader import ConfigValidationError, load_trading_config


class ConfigLoaderTest(unittest.TestCase):
    def test_load_trading_config_from_module_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "custom_config.py"
            config_path.write_text(
                "TRADING_CONFIG = {\n"
                "    'do_not_trading': ['BTC'],\n"
                "    'mode': 'paper',\n"
                "    'paper_initial_krw': 2000000,\n"
                "    'fee_rate': 0.001,\n"
                "    'min_order_krw': 5000,\n"
                "    'max_holdings': 4,\n"
                "    'buy_divisor': 5,\n"
                "    'min_buyable_krw': 20000,\n"
                "    'risk_per_trade_pct': 0.1,\n"
                "    'max_daily_loss_pct': 0.05,\n"
                "    'max_consecutive_losses': 3,\n"
                "    'max_concurrent_positions': 4,\n"
                "    'max_correlated_positions': 2,\n"
                "    'correlation_groups': {},\n"
                "    'trailing_stop_pct': 0.01,\n"
                "    'partial_take_profit_threshold': 1.02,\n"
                "    'partial_take_profit_ratio': 0.5,\n"
                "    'partial_stop_loss_ratio': 1.0,\n"
                "    'candle_interval': 3,\n"
                "    'macd_n_fast': 12,\n"
                "    'macd_n_slow': 26,\n"
                "    'macd_n_signal': 9,\n"
                "    'min_candle_extra': 3,\n"
                "    'buy_rsi_threshold': 35,\n"
                "    'sell_profit_threshold': 1.01,\n"
                "    'sell_requires_profit': True,\n"
                "    'stop_loss_threshold': 0.975,\n"
                "    'krw_markets': [],\n"
                "    'universe_top_n1': 30,\n"
                "    'universe_watch_n2': 10,\n"
                "    'low_spec_watch_cap_n2': 10,\n"
                "    'max_relative_spread': 0.003,\n"
                "    'max_candle_missing_rate': 0.1,\n"
                "    'sr_pivot_left': 2,\n"
                "    'sr_pivot_right': 2,\n"
                "    'sr_cluster_band_pct': 0.0025,\n"
                "    'sr_min_touches': 2,\n"
                "    'sr_lookback_bars': 120,\n"
                "    'zone_priority_mode': 'intersection',\n"
                "    'fvg_atr_period': 14,\n"
                "    'fvg_min_width_atr_mult': 0.2,\n"
                "    'fvg_min_width_ticks': 2,\n"
                "    'displacement_min_body_ratio': 0.6,\n"
                "    'displacement_min_atr_mult': 1.2,\n"
                "    'ob_lookback_bars': 80,\n"
                "    'ob_max_base_bars': 6,\n"
                "    'zone_expiry_bars_5m': 36,\n"
                "    'zone_reentry_buffer_pct': 0.0005,\n"
                "    'trigger_rejection_wick_ratio': 0.35,\n"
                "    'trigger_breakout_lookback': 3,\n"
                "    'trigger_zone_lookback': 5,\n"
                "    'trigger_confirm_lookback': 3,\n"
                "    'trigger_mode': 'strict',\n"
                "    'min_candles_1m': 80,\n"
                "    'min_candles_5m': 120,\n"
                "    'min_candles_15m': 120\n"
                "}\n",
                encoding="utf-8",
            )
            os.environ["TRADING_CONFIG_FILE"] = str(config_path)
            try:
                config = load_trading_config()
            finally:
                del os.environ["TRADING_CONFIG_FILE"]

        self.assertEqual(config.mode, "paper")
        self.assertEqual(config.paper_initial_krw, 2_000_000)


    def test_default_portfolio_limits_are_single_position(self):
        config = load_trading_config()
        self.assertEqual(config.max_holdings, 1)
        self.assertEqual(config.max_concurrent_positions, 1)

    def test_env_override_and_validation(self):
        os.environ["TRADING_MODE"] = "dry_run"
        os.environ["TRADING_BUY_RSI_THRESHOLD"] = "45"
        try:
            config = load_trading_config()
        finally:
            del os.environ["TRADING_MODE"]
            del os.environ["TRADING_BUY_RSI_THRESHOLD"]

        self.assertEqual(config.mode, "dry_run")
        self.assertEqual(config.buy_rsi_threshold, 45)

    def test_invalid_range_raises(self):
        os.environ["TRADING_BUY_RSI_THRESHOLD"] = "120"
        try:
            with self.assertRaises(ConfigValidationError):
                load_trading_config()
        finally:
            del os.environ["TRADING_BUY_RSI_THRESHOLD"]


if __name__ == "__main__":
    unittest.main()
