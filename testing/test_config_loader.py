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
                "    'candle_interval': 3,\n"
                "    'macd_n_fast': 12,\n"
                "    'macd_n_slow': 26,\n"
                "    'macd_n_signal': 9,\n"
                "    'min_candle_extra': 3,\n"
                "    'buy_rsi_threshold': 35,\n"
                "    'sell_profit_threshold': 1.01,\n"
                "    'stop_loss_threshold': 0.975,\n"
                "    'krw_markets': [],\n    'universe_top_n1': 30,\n    'universe_watch_n2': 10,\n    'max_relative_spread': 0.003,\n    'max_candle_missing_rate': 0.1\n"
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
