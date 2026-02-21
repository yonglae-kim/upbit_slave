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
    }:
        return int(value)
    if key in {"fee_rate", "sell_profit_threshold", "stop_loss_threshold"}:
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


def load_trading_config() -> TradingConfig:
    path = Path(os.getenv("TRADING_CONFIG_FILE", _default_config_path()))
    raw_config = _load_module_config(path)
    raw_config = _apply_env_overrides(raw_config)
    _validate_schema(raw_config)
    return TradingConfig(**raw_config)
