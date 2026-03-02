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
                "    'position_sizing_mode': 'risk_first',\n"
                "    'max_order_krw_by_cash_management': 0,\n"
                "    'min_buyable_krw': 0,\n"
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
                "    'trailing_requires_breakeven': True,\n"
                "    'trailing_activation_bars': 0,\n"
                "    'exit_mode': 'atr',\n"
                "    'atr_period': 14,\n"
                "    'atr_stop_mult': 1.4,\n"
                "    'atr_trailing_mult': 2.0,\n"
                "    'swing_lookback': 5,\n"
                "    'candle_interval': 3,\n"
                "    'macd_n_fast': 12,\n"
                "    'macd_n_slow': 26,\n"
                "    'macd_n_signal': 9,\n"
                "    'min_candle_extra': 3,\n"
                "    'buy_rsi_threshold': 35,\n"
                "    'sell_profit_threshold': 1.01,\n"
                "    'sell_requires_profit': False,\n"
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
                "    'min_candles_15m': 120,\n"
                "    'regime_filter_enabled': True,\n"
                "    'regime_ema_fast': 50,\n"
                "    'regime_ema_slow': 200,\n"
                "    'regime_adx_period': 14,\n"
                "    'regime_adx_min': 18.0,\n"
                "    'regime_slope_lookback': 3,\n"
                "    'zone_profile': 'aggressive',\n"
                "    'reentry_cooldown_bars': 10,\n"
                "    'cooldown_on_loss_exits_only': False,\n"
                "    'strategy_name': 'rsi_bb_reversal_long',\n"
                "    'rsi_period': 14,\n"
                "    'rsi_long_threshold': 30,\n"
                "    'rsi_neutral_filter_enabled': True,\n"
                "    'rsi_neutral_low': 45,\n"
                "    'rsi_neutral_high': 55,\n"
                "    'bb_period': 20,\n"
                "    'bb_std': 2.0,\n"
                "    'bb_touch_mode': 'touch_or_break',\n"
                "    'macd_fast': 12,\n"
                "    'macd_slow': 26,\n"
                "    'macd_signal': 9,\n"
                "    'macd_histogram_filter_enabled': False,\n"
                "    'engulfing_strict': True,\n"
                "    'engulfing_include_wick': False,\n"
                "    'consecutive_bearish_count': 3,\n"
                "    'pivot_left': 3,\n"
                "    'pivot_right': 3,\n"
                "    'double_bottom_lookback_bars': 40,\n"
                "    'double_bottom_tolerance_pct': 0.5,\n"
                "    'require_band_reentry_on_second_bottom': True,\n"
                "    'require_neckline_break': False,\n"
                "    'divergence_signal_enabled': True,\n"
                "    'entry_score_threshold': 2.5,\n"
                "    'rsi_oversold_weight': 1.0,\n"
                "    'bb_touch_weight': 1.0,\n"
                "    'divergence_weight': 0.8,\n"
                "    'macd_cross_weight': 0.8,\n"
                "    'engulfing_weight': 1.0,\n"
                "    'band_deviation_weight': 0.8,\n"
                "    'quality_score_low_threshold': 0.35,\n"
                "    'quality_score_high_threshold': 0.7,\n"
                "    'quality_multiplier_low': 0.7,\n"
                "    'quality_multiplier_mid': 1.0,\n"
                "    'quality_multiplier_high': 1.15,\n"
                "    'quality_multiplier_min_bound': 0.7,\n"
                "    'quality_multiplier_max_bound': 1.2,\n"
                "    'entry_mode': 'close',\n"
                "    'stop_mode_long': 'swing_low',\n"
                "    'take_profit_r': 2.0,\n"
                "    'partial_take_profit_enabled': False,\n"
                "    'partial_take_profit_r': 1.0,\n"
                "    'partial_take_profit_size': 0.5,\n"
                "    'move_stop_to_breakeven_after_partial': True,\n"
                "    'max_hold_bars': 0,\n"
                "    'strategy_cooldown_bars': 0\n"
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


    def test_min_buyable_env_override_is_treated_as_dynamic_buffer(self):
        os.environ["TRADING_MIN_ORDER_KRW"] = "5000"
        os.environ["TRADING_MIN_BUYABLE_KRW"] = "7000"
        try:
            config = load_trading_config()
        finally:
            del os.environ["TRADING_MIN_ORDER_KRW"]
            del os.environ["TRADING_MIN_BUYABLE_KRW"]

        self.assertEqual(config.min_buyable_krw, 7000)
        self.assertEqual(config.min_effective_buyable_krw, 7000)


    def test_entry_score_env_override(self):
        os.environ["TRADING_ENTRY_SCORE_THRESHOLD"] = "3.25"
        os.environ["TRADING_MACD_CROSS_WEIGHT"] = "1.7"
        os.environ["TRADING_QUALITY_MULTIPLIER_HIGH"] = "1.3"
        try:
            config = load_trading_config()
        finally:
            del os.environ["TRADING_ENTRY_SCORE_THRESHOLD"]
            del os.environ["TRADING_MACD_CROSS_WEIGHT"]
            del os.environ["TRADING_QUALITY_MULTIPLIER_HIGH"]

        self.assertEqual(config.entry_score_threshold, 3.25)
        self.assertEqual(config.macd_cross_weight, 1.7)
        self.assertEqual(config.quality_multiplier_high, 1.3)

    def test_regime_strategy_override_profile_is_available(self):
        config = load_trading_config()
        strong = config.regime_strategy_overrides("strong_trend")
        side = config.regime_strategy_overrides("sideways")

        self.assertGreater(strong.get("entry_score_threshold", 0.0), side.get("entry_score_threshold", 0.0))
        self.assertGreater(strong.get("take_profit_r", 0.0), side.get("take_profit_r", 0.0))


    def test_trailing_activation_env_overrides(self):
        os.environ["TRADING_TRAILING_REQUIRES_BREAKEVEN"] = "false"
        os.environ["TRADING_TRAILING_ACTIVATION_BARS"] = "3"
        try:
            config = load_trading_config()
        finally:
            del os.environ["TRADING_TRAILING_REQUIRES_BREAKEVEN"]
            del os.environ["TRADING_TRAILING_ACTIVATION_BARS"]

        self.assertFalse(config.trailing_requires_breakeven)
        self.assertEqual(config.trailing_activation_bars, 3)

    def test_invalid_range_raises(self):
        os.environ["TRADING_BUY_RSI_THRESHOLD"] = "120"
        try:
            with self.assertRaises(ConfigValidationError):
                load_trading_config()
        finally:
            del os.environ["TRADING_BUY_RSI_THRESHOLD"]


if __name__ == "__main__":
    unittest.main()
