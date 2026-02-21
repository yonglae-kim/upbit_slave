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
    "min_buyable_krw": "TRADING_MIN_BUYABLE_KRW",
    "candle_interval": "TRADING_CANDLE_INTERVAL",
    "macd_n_fast": "TRADING_MACD_N_FAST",
    "macd_n_slow": "TRADING_MACD_N_SLOW",
    "macd_n_signal": "TRADING_MACD_N_SIGNAL",
    "min_candle_extra": "TRADING_MIN_CANDLE_EXTRA",
    "buy_rsi_threshold": "TRADING_BUY_RSI_THRESHOLD",
    "sell_profit_threshold": "TRADING_SELL_PROFIT_THRESHOLD",
    "stop_loss_threshold": "TRADING_STOP_LOSS_THRESHOLD",
    "krw_markets": "TRADING_KRW_MARKETS",
    "universe_top_n1": "TRADING_UNIVERSE_TOP_N1",
    "universe_watch_n2": "TRADING_UNIVERSE_WATCH_N2",
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
    "min_candles_1m": "TRADING_MIN_CANDLES_1M",
    "min_candles_5m": "TRADING_MIN_CANDLES_5M",
    "min_candles_15m": "TRADING_MIN_CANDLES_15M",
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
        "min_buyable_krw",
        "candle_interval",
        "macd_n_fast",
        "macd_n_slow",
        "macd_n_signal",
        "min_candle_extra",
        "buy_rsi_threshold",
        "universe_top_n1",
        "universe_watch_n2",
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
        "min_candles_1m",
        "min_candles_5m",
        "min_candles_15m",
    }:
        return int(value)
    if key in {"fee_rate", "sell_profit_threshold", "stop_loss_threshold", "max_relative_spread", "max_candle_missing_rate", "sr_cluster_band_pct", "fvg_min_width_atr_mult", "displacement_min_body_ratio", "displacement_min_atr_mult", "zone_reentry_buffer_pct", "trigger_rejection_wick_ratio"}:
        return float(value)
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
        "min_buyable_krw": int,
        "candle_interval": int,
        "macd_n_fast": int,
        "macd_n_slow": int,
        "macd_n_signal": int,
        "min_candle_extra": int,
        "buy_rsi_threshold": int,
        "sell_profit_threshold": (int, float),
        "stop_loss_threshold": (int, float),
        "krw_markets": list,
        "universe_top_n1": int,
        "universe_watch_n2": int,
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
        "min_candles_1m": int,
        "min_candles_5m": int,
        "min_candles_15m": int,
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
        "min_buyable_krw",
        "candle_interval",
        "macd_n_fast",
        "macd_n_slow",
        "macd_n_signal",
        "universe_top_n1",
        "universe_watch_n2",
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
        "min_candles_1m",
        "min_candles_5m",
        "min_candles_15m",
    ]
    for key in positive_keys:
        if config[key] <= 0:
            raise ConfigValidationError(f"Config key '{key}' must be > 0")

    if not 0 <= config["fee_rate"] < 1:
        raise ConfigValidationError("fee_rate must be in [0, 1)")
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


def load_trading_config() -> TradingConfig:
    path = Path(os.getenv("TRADING_CONFIG_FILE", _default_config_path()))
    raw_config = _load_module_config(path)
    raw_config = _apply_env_overrides(raw_config)
    _validate_schema(raw_config)
    return TradingConfig(**raw_config)
