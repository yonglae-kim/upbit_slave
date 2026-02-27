from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
from typing import Any

from core.config import TradingConfig


_ENV_KEY_MAP = {
    "do_not_trading": "TRADING_DO_NOT_TRADING",
    "mode": "TRADING_MODE",
    "paper_initial_krw": "TRADING_PAPER_INITIAL_KRW",
    "fee_rate": "TRADING_FEE_RATE",
    "min_order_krw": "TRADING_MIN_ORDER_KRW",
    "max_holdings": "TRADING_MAX_HOLDINGS",
    "buy_divisor": "TRADING_BUY_DIVISOR",
    "position_sizing_mode": "TRADING_POSITION_SIZING_MODE",
    "max_order_krw_by_cash_management": "TRADING_MAX_ORDER_KRW_BY_CASH_MANAGEMENT",
    "min_buyable_krw": "TRADING_MIN_BUYABLE_KRW",
    "risk_per_trade_pct": "TRADING_RISK_PER_TRADE_PCT",
    "max_daily_loss_pct": "TRADING_MAX_DAILY_LOSS_PCT",
    "max_consecutive_losses": "TRADING_MAX_CONSECUTIVE_LOSSES",
    "max_concurrent_positions": "TRADING_MAX_CONCURRENT_POSITIONS",
    "max_correlated_positions": "TRADING_MAX_CORRELATED_POSITIONS",
    "trailing_stop_pct": "TRADING_TRAILING_STOP_PCT",
    "partial_take_profit_threshold": "TRADING_PARTIAL_TAKE_PROFIT_THRESHOLD",
    "partial_take_profit_ratio": "TRADING_PARTIAL_TAKE_PROFIT_RATIO",
    "partial_stop_loss_ratio": "TRADING_PARTIAL_STOP_LOSS_RATIO",
    "exit_mode": "TRADING_EXIT_MODE",
    "atr_period": "TRADING_ATR_PERIOD",
    "atr_stop_mult": "TRADING_ATR_STOP_MULT",
    "atr_trailing_mult": "TRADING_ATR_TRAILING_MULT",
    "swing_lookback": "TRADING_SWING_LOOKBACK",
    "candle_interval": "TRADING_CANDLE_INTERVAL",
    "macd_n_fast": "TRADING_MACD_N_FAST",
    "macd_n_slow": "TRADING_MACD_N_SLOW",
    "macd_n_signal": "TRADING_MACD_N_SIGNAL",
    "min_candle_extra": "TRADING_MIN_CANDLE_EXTRA",
    "buy_rsi_threshold": "TRADING_BUY_RSI_THRESHOLD",
    "sell_profit_threshold": "TRADING_SELL_PROFIT_THRESHOLD",
    "sell_requires_profit": "TRADING_SELL_REQUIRES_PROFIT",
    "stop_loss_threshold": "TRADING_STOP_LOSS_THRESHOLD",
    "krw_markets": "TRADING_KRW_MARKETS",
    "universe_top_n1": "TRADING_UNIVERSE_TOP_N1",
    "universe_watch_n2": "TRADING_UNIVERSE_WATCH_N2",
    "low_spec_watch_cap_n2": "TRADING_LOW_SPEC_WATCH_CAP_N2",
    "max_relative_spread": "TRADING_MAX_RELATIVE_SPREAD",
    "max_candle_missing_rate": "TRADING_MAX_CANDLE_MISSING_RATE",
    "sr_pivot_left": "TRADING_SR_PIVOT_LEFT",
    "sr_pivot_right": "TRADING_SR_PIVOT_RIGHT",
    "sr_cluster_band_pct": "TRADING_SR_CLUSTER_BAND_PCT",
    "sr_min_touches": "TRADING_SR_MIN_TOUCHES",
    "sr_lookback_bars": "TRADING_SR_LOOKBACK_BARS",
    "zone_priority_mode": "TRADING_ZONE_PRIORITY_MODE",
    "fvg_atr_period": "TRADING_FVG_ATR_PERIOD",
    "fvg_min_width_atr_mult": "TRADING_FVG_MIN_WIDTH_ATR_MULT",
    "fvg_min_width_ticks": "TRADING_FVG_MIN_WIDTH_TICKS",
    "displacement_min_body_ratio": "TRADING_DISPLACEMENT_MIN_BODY_RATIO",
    "displacement_min_atr_mult": "TRADING_DISPLACEMENT_MIN_ATR_MULT",
    "ob_lookback_bars": "TRADING_OB_LOOKBACK_BARS",
    "ob_max_base_bars": "TRADING_OB_MAX_BASE_BARS",
    "zone_expiry_bars_5m": "TRADING_ZONE_EXPIRY_BARS_5M",
    "zone_reentry_buffer_pct": "TRADING_ZONE_REENTRY_BUFFER_PCT",
    "trigger_rejection_wick_ratio": "TRADING_TRIGGER_REJECTION_WICK_RATIO",
    "trigger_breakout_lookback": "TRADING_TRIGGER_BREAKOUT_LOOKBACK",
    "trigger_zone_lookback": "TRADING_TRIGGER_ZONE_LOOKBACK",
    "trigger_confirm_lookback": "TRADING_TRIGGER_CONFIRM_LOOKBACK",
    "trigger_mode": "TRADING_TRIGGER_MODE",
    "min_candles_1m": "TRADING_MIN_CANDLES_1M",
    "min_candles_5m": "TRADING_MIN_CANDLES_5M",
    "min_candles_15m": "TRADING_MIN_CANDLES_15M",
    "regime_filter_enabled": "TRADING_REGIME_FILTER_ENABLED",
    "regime_ema_fast": "TRADING_REGIME_EMA_FAST",
    "regime_ema_slow": "TRADING_REGIME_EMA_SLOW",
    "regime_adx_period": "TRADING_REGIME_ADX_PERIOD",
    "regime_adx_min": "TRADING_REGIME_ADX_MIN",
    "regime_slope_lookback": "TRADING_REGIME_SLOPE_LOOKBACK",
    "zone_profile": "TRADING_ZONE_PROFILE",
    "reentry_cooldown_bars": "TRADING_REENTRY_COOLDOWN_BARS",
    "cooldown_on_loss_exits_only": "TRADING_COOLDOWN_ON_LOSS_EXITS_ONLY",
    "strategy_name": "TRADING_STRATEGY_NAME",
    "rsi_period": "TRADING_RSI_PERIOD",
    "rsi_long_threshold": "TRADING_RSI_LONG_THRESHOLD",
    "rsi_neutral_filter_enabled": "TRADING_RSI_NEUTRAL_FILTER_ENABLED",
    "rsi_neutral_low": "TRADING_RSI_NEUTRAL_LOW",
    "rsi_neutral_high": "TRADING_RSI_NEUTRAL_HIGH",
    "bb_period": "TRADING_BB_PERIOD",
    "bb_std": "TRADING_BB_STD",
    "bb_touch_mode": "TRADING_BB_TOUCH_MODE",
    "macd_fast": "TRADING_MACD_FAST",
    "macd_slow": "TRADING_MACD_SLOW",
    "macd_signal": "TRADING_MACD_SIGNAL",
    "macd_histogram_filter_enabled": "TRADING_MACD_HISTOGRAM_FILTER_ENABLED",
    "engulfing_strict": "TRADING_ENGULFING_STRICT",
    "engulfing_include_wick": "TRADING_ENGULFING_INCLUDE_WICK",
    "consecutive_bearish_count": "TRADING_CONSECUTIVE_BEARISH_COUNT",
    "pivot_left": "TRADING_PIVOT_LEFT",
    "pivot_right": "TRADING_PIVOT_RIGHT",
    "double_bottom_lookback_bars": "TRADING_DOUBLE_BOTTOM_LOOKBACK_BARS",
    "double_bottom_tolerance_pct": "TRADING_DOUBLE_BOTTOM_TOLERANCE_PCT",
    "require_band_reentry_on_second_bottom": "TRADING_REQUIRE_BAND_REENTRY_ON_SECOND_BOTTOM",
    "require_neckline_break": "TRADING_REQUIRE_NECKLINE_BREAK",
    "divergence_signal_enabled": "TRADING_DIVERGENCE_SIGNAL_ENABLED",
    "entry_score_threshold": "TRADING_ENTRY_SCORE_THRESHOLD",
    "rsi_oversold_weight": "TRADING_RSI_OVERSOLD_WEIGHT",
    "bb_touch_weight": "TRADING_BB_TOUCH_WEIGHT",
    "divergence_weight": "TRADING_DIVERGENCE_WEIGHT",
    "macd_cross_weight": "TRADING_MACD_CROSS_WEIGHT",
    "engulfing_weight": "TRADING_ENGULFING_WEIGHT",
    "band_deviation_weight": "TRADING_BAND_DEVIATION_WEIGHT",
    "entry_mode": "TRADING_ENTRY_MODE",
    "stop_mode_long": "TRADING_STOP_MODE_LONG",
    "take_profit_r": "TRADING_TAKE_PROFIT_R",
    "partial_take_profit_enabled": "TRADING_PARTIAL_TAKE_PROFIT_ENABLED",
    "partial_take_profit_r": "TRADING_PARTIAL_TAKE_PROFIT_R",
    "partial_take_profit_size": "TRADING_PARTIAL_TAKE_PROFIT_SIZE",
    "move_stop_to_breakeven_after_partial": "TRADING_MOVE_STOP_TO_BREAKEVEN_AFTER_PARTIAL",
    "max_hold_bars": "TRADING_MAX_HOLD_BARS",
    "strategy_cooldown_bars": "TRADING_STRATEGY_COOLDOWN_BARS",
}


class ConfigValidationError(ValueError):
    pass


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.py"


def _load_module_config(path: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("runtime_trading_config", path)
    if spec is None or spec.loader is None:
        raise ConfigValidationError(f"Failed to load config module from path: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = getattr(module, "TRADING_CONFIG", None)
    if not isinstance(config, dict):
        raise ConfigValidationError("TRADING_CONFIG must be a dict")
    return copy.deepcopy(config)


def _parse_env_value(key: str, value: str):
    if key in {"do_not_trading", "krw_markets"}:
        return [item.strip() for item in value.split(",") if item.strip()]
    if key in {
        "paper_initial_krw",
        "min_order_krw",
        "max_holdings",
        "buy_divisor",
        "max_order_krw_by_cash_management",
        "min_buyable_krw",
        "max_concurrent_positions",
        "max_correlated_positions",
        "atr_period",
        "swing_lookback",
        "candle_interval",
        "macd_n_fast",
        "macd_n_slow",
        "macd_n_signal",
        "min_candle_extra",
        "buy_rsi_threshold",
        "universe_top_n1",
        "universe_watch_n2",
        "low_spec_watch_cap_n2",
        "sr_pivot_left",
        "sr_pivot_right",
        "sr_min_touches",
        "sr_lookback_bars",
        "fvg_atr_period",
        "fvg_min_width_ticks",
        "ob_lookback_bars",
        "ob_max_base_bars",
        "zone_expiry_bars_5m",
        "trigger_breakout_lookback",
        "trigger_zone_lookback",
        "trigger_confirm_lookback",
        "min_candles_1m",
        "min_candles_5m",
        "min_candles_15m",
        "regime_ema_fast",
        "regime_ema_slow",
        "regime_adx_period",
        "regime_slope_lookback",
        "reentry_cooldown_bars",
        "rsi_period",
        "bb_period",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "consecutive_bearish_count",
        "pivot_left",
        "pivot_right",
        "double_bottom_lookback_bars",
        "max_hold_bars",
        "strategy_cooldown_bars",
    }:
        return int(value)
    if key in {"fee_rate", "risk_per_trade_pct", "max_daily_loss_pct", "trailing_stop_pct", "partial_take_profit_threshold", "partial_take_profit_ratio", "partial_stop_loss_ratio", "atr_stop_mult", "atr_trailing_mult", "sell_profit_threshold", "stop_loss_threshold", "max_relative_spread", "max_candle_missing_rate", "sr_cluster_band_pct", "fvg_min_width_atr_mult", "displacement_min_body_ratio", "displacement_min_atr_mult", "zone_reentry_buffer_pct", "trigger_rejection_wick_ratio", "regime_adx_min", "rsi_long_threshold", "rsi_neutral_low", "rsi_neutral_high", "bb_std", "double_bottom_tolerance_pct", "entry_score_threshold", "rsi_oversold_weight", "bb_touch_weight", "divergence_weight", "macd_cross_weight", "engulfing_weight", "band_deviation_weight", "take_profit_r", "partial_take_profit_r", "partial_take_profit_size"}:
        return float(value)
    if key in {"sell_requires_profit", "regime_filter_enabled", "cooldown_on_loss_exits_only", "rsi_neutral_filter_enabled", "macd_histogram_filter_enabled", "engulfing_strict", "engulfing_include_wick", "require_band_reentry_on_second_bottom", "require_neckline_break", "divergence_signal_enabled", "partial_take_profit_enabled", "move_stop_to_breakeven_after_partial"}:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    for key, env_key in _ENV_KEY_MAP.items():
        raw_value = os.getenv(env_key)
        if raw_value is None:
            continue
        config[key] = _parse_env_value(key, raw_value)
    return config


def _validate_schema(config: dict[str, Any]) -> None:
    required_types = {
        "do_not_trading": list,
        "mode": str,
        "paper_initial_krw": (int, float),
        "fee_rate": (int, float),
        "min_order_krw": int,
        "max_holdings": int,
        "buy_divisor": int,
        "position_sizing_mode": str,
        "max_order_krw_by_cash_management": int,
        "min_buyable_krw": int,
        "correlation_groups": dict,
        "risk_per_trade_pct": (int, float),
        "max_daily_loss_pct": (int, float),
        "max_consecutive_losses": int,
        "max_concurrent_positions": int,
        "max_correlated_positions": int,
        "trailing_stop_pct": (int, float),
        "partial_take_profit_threshold": (int, float),
        "partial_take_profit_ratio": (int, float),
        "partial_stop_loss_ratio": (int, float),
        "exit_mode": str,
        "atr_period": int,
        "atr_stop_mult": (int, float),
        "atr_trailing_mult": (int, float),
        "swing_lookback": int,
        "candle_interval": int,
        "macd_n_fast": int,
        "macd_n_slow": int,
        "macd_n_signal": int,
        "min_candle_extra": int,
        "buy_rsi_threshold": int,
        "sell_profit_threshold": (int, float),
        "sell_requires_profit": bool,
        "stop_loss_threshold": (int, float),
        "krw_markets": list,
        "universe_top_n1": int,
        "universe_watch_n2": int,
        "low_spec_watch_cap_n2": int,
        "max_relative_spread": (int, float),
        "max_candle_missing_rate": (int, float),
        "sr_pivot_left": int,
        "sr_pivot_right": int,
        "sr_cluster_band_pct": (int, float),
        "sr_min_touches": int,
        "sr_lookback_bars": int,
        "zone_priority_mode": str,
        "fvg_atr_period": int,
        "fvg_min_width_atr_mult": (int, float),
        "fvg_min_width_ticks": int,
        "displacement_min_body_ratio": (int, float),
        "displacement_min_atr_mult": (int, float),
        "ob_lookback_bars": int,
        "ob_max_base_bars": int,
        "zone_expiry_bars_5m": int,
        "zone_reentry_buffer_pct": (int, float),
        "trigger_rejection_wick_ratio": (int, float),
        "trigger_breakout_lookback": int,
        "trigger_zone_lookback": int,
        "trigger_confirm_lookback": int,
        "trigger_mode": str,
        "min_candles_1m": int,
        "min_candles_5m": int,
        "min_candles_15m": int,
        "regime_filter_enabled": bool,
        "regime_ema_fast": int,
        "regime_ema_slow": int,
        "regime_adx_period": int,
        "regime_adx_min": (int, float),
        "regime_slope_lookback": int,
        "reentry_cooldown_bars": int,
        "cooldown_on_loss_exits_only": bool,
        "strategy_cooldown_bars": int,
        "strategy_name": str,
        "rsi_period": int,
        "rsi_long_threshold": (int, float),
        "rsi_neutral_filter_enabled": bool,
        "rsi_neutral_low": (int, float),
        "rsi_neutral_high": (int, float),
        "bb_period": int,
        "bb_std": (int, float),
        "bb_touch_mode": str,
        "macd_fast": int,
        "macd_slow": int,
        "macd_signal": int,
        "macd_histogram_filter_enabled": bool,
        "engulfing_strict": bool,
        "engulfing_include_wick": bool,
        "consecutive_bearish_count": int,
        "pivot_left": int,
        "pivot_right": int,
        "double_bottom_lookback_bars": int,
        "double_bottom_tolerance_pct": (int, float),
        "require_band_reentry_on_second_bottom": bool,
        "require_neckline_break": bool,
        "divergence_signal_enabled": bool,
        "entry_score_threshold": (int, float),
        "rsi_oversold_weight": (int, float),
        "bb_touch_weight": (int, float),
        "divergence_weight": (int, float),
        "macd_cross_weight": (int, float),
        "engulfing_weight": (int, float),
        "band_deviation_weight": (int, float),
        "entry_mode": str,
        "stop_mode_long": str,
        "take_profit_r": (int, float),
        "partial_take_profit_enabled": bool,
        "partial_take_profit_r": (int, float),
        "partial_take_profit_size": (int, float),
        "move_stop_to_breakeven_after_partial": bool,
        "max_hold_bars": int,
    }

    for key, expected in required_types.items():
        if key not in config:
            raise ConfigValidationError(f"Missing required config key: {key}")
        if not isinstance(config[key], expected):
            raise ConfigValidationError(f"Config key '{key}' has invalid type: {type(config[key]).__name__}")

    if config["mode"] not in {"live", "paper", "dry_run"}:
        raise ConfigValidationError("mode must be one of: live, paper, dry_run")

    positive_keys = [
        "paper_initial_krw",
        "min_order_krw",
        "max_holdings",
        "buy_divisor",
        "max_concurrent_positions",
        "max_correlated_positions",
        "atr_period",
        "swing_lookback",
        "candle_interval",
        "macd_n_fast",
        "macd_n_slow",
        "macd_n_signal",
        "universe_top_n1",
        "universe_watch_n2",
        "low_spec_watch_cap_n2",
        "sr_pivot_left",
        "sr_pivot_right",
        "sr_min_touches",
        "sr_lookback_bars",
        "fvg_atr_period",
        "fvg_min_width_ticks",
        "ob_lookback_bars",
        "ob_max_base_bars",
        "zone_expiry_bars_5m",
        "trigger_breakout_lookback",
        "trigger_zone_lookback",
        "trigger_confirm_lookback",
        "min_candles_1m",
        "min_candles_5m",
        "min_candles_15m",
        "regime_ema_fast",
        "regime_ema_slow",
        "regime_adx_period",
        "regime_slope_lookback",
        "rsi_period",
        "bb_period",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "consecutive_bearish_count",
        "pivot_left",
        "pivot_right",
        "double_bottom_lookback_bars",
    ]
    for key in positive_keys:
        if config[key] <= 0:
            raise ConfigValidationError(f"Config key '{key}' must be > 0")

    if not 0 <= config["fee_rate"] < 1:
        raise ConfigValidationError("fee_rate must be in [0, 1)")
    if config["position_sizing_mode"] not in {"risk_first", "cash_split_first"}:
        raise ConfigValidationError("position_sizing_mode must be one of: risk_first, cash_split_first")
    if config["max_order_krw_by_cash_management"] < 0:
        raise ConfigValidationError("max_order_krw_by_cash_management must be >= 0")
    if config["min_buyable_krw"] < 0:
        raise ConfigValidationError("min_buyable_krw must be >= 0")
    if not 0 < config["risk_per_trade_pct"] <= 1:
        raise ConfigValidationError("risk_per_trade_pct must be in (0, 1]")
    if not 0 <= config["max_daily_loss_pct"] <= 1:
        raise ConfigValidationError("max_daily_loss_pct must be in [0, 1]")
    if config["max_consecutive_losses"] < 0:
        raise ConfigValidationError("max_consecutive_losses must be >= 0")
    if not 0 <= config["trailing_stop_pct"] <= 1:
        raise ConfigValidationError("trailing_stop_pct must be in [0, 1]")
    if config["partial_take_profit_threshold"] <= 1:
        raise ConfigValidationError("partial_take_profit_threshold must be > 1")
    if not 0 <= config["partial_take_profit_ratio"] <= 1:
        raise ConfigValidationError("partial_take_profit_ratio must be in [0, 1]")
    if not 0 <= config["partial_stop_loss_ratio"] <= 1:
        raise ConfigValidationError("partial_stop_loss_ratio must be in [0, 1]")
    if config["exit_mode"] not in {"fixed_pct", "atr"}:
        raise ConfigValidationError("exit_mode must be one of: fixed_pct, atr")
    if config["atr_stop_mult"] <= 0:
        raise ConfigValidationError("atr_stop_mult must be > 0")
    if config["atr_trailing_mult"] < 0:
        raise ConfigValidationError("atr_trailing_mult must be >= 0")
    if config.get("correlation_groups") is None:
        config["correlation_groups"] = {}
    if not isinstance(config.get("correlation_groups"), dict):
        raise ConfigValidationError("correlation_groups must be a dict")

    if not 0 <= config["buy_rsi_threshold"] <= 100:
        raise ConfigValidationError("buy_rsi_threshold must be in [0, 100]")
    if config["sell_profit_threshold"] <= 0:
        raise ConfigValidationError("sell_profit_threshold must be > 0")
    if not 0 < config["stop_loss_threshold"] < 1:
        raise ConfigValidationError("stop_loss_threshold must be in (0, 1)")
    if config["macd_n_fast"] >= config["macd_n_slow"]:
        raise ConfigValidationError("macd_n_fast must be smaller than macd_n_slow")
    if config["max_relative_spread"] < 0:
        raise ConfigValidationError("max_relative_spread must be >= 0")
    if not 0 <= config["max_candle_missing_rate"] <= 1:
        raise ConfigValidationError("max_candle_missing_rate must be in [0, 1]")

    if config["sr_pivot_left"] <= 0 or config["sr_pivot_right"] <= 0:
        raise ConfigValidationError("sr_pivot_left and sr_pivot_right must be > 0")
    if config["sr_min_touches"] <= 0:
        raise ConfigValidationError("sr_min_touches must be > 0")
    if config["sr_cluster_band_pct"] < 0:
        raise ConfigValidationError("sr_cluster_band_pct must be >= 0")
    if config["zone_priority_mode"] not in {"intersection", "setup_only"}:
        raise ConfigValidationError("zone_priority_mode must be one of: intersection, setup_only")
    if config["fvg_min_width_atr_mult"] < 0:
        raise ConfigValidationError("fvg_min_width_atr_mult must be >= 0")
    if config["displacement_min_body_ratio"] <= 0:
        raise ConfigValidationError("displacement_min_body_ratio must be > 0")
    if config["displacement_min_atr_mult"] <= 0:
        raise ConfigValidationError("displacement_min_atr_mult must be > 0")
    if config["zone_reentry_buffer_pct"] < 0:
        raise ConfigValidationError("zone_reentry_buffer_pct must be >= 0")
    if config["trigger_rejection_wick_ratio"] <= 0:
        raise ConfigValidationError("trigger_rejection_wick_ratio must be > 0")
    if config["trigger_mode"] not in {"strict", "balanced", "adaptive"}:
        raise ConfigValidationError("trigger_mode must be one of: strict, balanced, adaptive")
    if config["regime_ema_fast"] >= config["regime_ema_slow"]:
        raise ConfigValidationError("regime_ema_fast must be smaller than regime_ema_slow")
    if config["regime_adx_min"] < 0:
        raise ConfigValidationError("regime_adx_min must be >= 0")
    if config["reentry_cooldown_bars"] < 0:
        raise ConfigValidationError("reentry_cooldown_bars must be >= 0")

    if config["strategy_name"] not in {"sr_ob_fvg", "rsi_bb_reversal_long"}:
        raise ConfigValidationError("strategy_name must be one of: sr_ob_fvg, rsi_bb_reversal_long")
    if not 0 <= config["rsi_long_threshold"] <= 100:
        raise ConfigValidationError("rsi_long_threshold must be in [0, 100]")
    if not 0 <= config["rsi_neutral_low"] <= 100 or not 0 <= config["rsi_neutral_high"] <= 100:
        raise ConfigValidationError("rsi_neutral_low/high must be in [0, 100]")
    if config["rsi_neutral_low"] > config["rsi_neutral_high"]:
        raise ConfigValidationError("rsi_neutral_low must be <= rsi_neutral_high")
    if config["bb_std"] <= 0:
        raise ConfigValidationError("bb_std must be > 0")
    if config["bb_touch_mode"] not in {"touch_only", "break_only", "touch_or_break"}:
        raise ConfigValidationError("bb_touch_mode must be one of: touch_only, break_only, touch_or_break")
    if config["macd_fast"] >= config["macd_slow"]:
        raise ConfigValidationError("macd_fast must be smaller than macd_slow")
    if config["double_bottom_tolerance_pct"] < 0:
        raise ConfigValidationError("double_bottom_tolerance_pct must be >= 0")
    if config["entry_score_threshold"] < 0:
        raise ConfigValidationError("entry_score_threshold must be >= 0")
    for weight_key in (
        "rsi_oversold_weight",
        "bb_touch_weight",
        "divergence_weight",
        "macd_cross_weight",
        "engulfing_weight",
        "band_deviation_weight",
    ):
        if config[weight_key] < 0:
            raise ConfigValidationError(f"{weight_key} must be >= 0")
    if config["entry_mode"] not in {"close", "next_open"}:
        raise ConfigValidationError("entry_mode must be one of: close, next_open")
    if config["stop_mode_long"] not in {"swing_low", "lower_band", "conservative"}:
        raise ConfigValidationError("stop_mode_long must be one of: swing_low, lower_band, conservative")
    if config["take_profit_r"] <= 0:
        raise ConfigValidationError("take_profit_r must be > 0")
    if config["partial_take_profit_r"] <= 0:
        raise ConfigValidationError("partial_take_profit_r must be > 0")
    if not 0 <= config["partial_take_profit_size"] <= 1:
        raise ConfigValidationError("partial_take_profit_size must be in [0, 1]")
    if config["max_hold_bars"] < 0 or config["strategy_cooldown_bars"] < 0:
        raise ConfigValidationError("max_hold_bars and strategy_cooldown_bars must be >= 0")


def load_trading_config() -> TradingConfig:
    path = Path(os.getenv("TRADING_CONFIG_FILE", _default_config_path()))
    raw_config = _load_module_config(path)
    raw_config = _apply_env_overrides(raw_config)
    _validate_schema(raw_config)
    return TradingConfig(**raw_config)
