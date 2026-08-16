from __future__ import annotations

from dataclasses import replace

from core.decision_models import StrategySignal
from core.strategy import StrategyParams


STRATEGY_NAME = "nfi_v1"
_VOLUME_MULTIPLIER = 1.1


def _number(
    candle: dict[str, object], key: str = "trade_price", fallback: str = "trade_price"
) -> float:
    if not isinstance(candle, dict):
        return 0.0
    value = candle.get(key, candle.get(fallback, 0.0))
    return float(value) if isinstance(value, (int, float)) else 0.0


def _ema(candles: list[dict[str, object]], period: int) -> float:
    closes = [_number(candle) for candle in reversed(candles)]
    if not closes:
        return 0.0
    alpha = 2.0 / (period + 1)
    value = closes[0]
    for close in closes[1:]:
        value = (close * alpha) + (value * (1.0 - alpha))
    return value


def _rsi(candles: list[dict[str, object]], period: int) -> float:
    closes = [_number(candle) for candle in reversed(candles)]
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    window = changes[-period:]
    gains = sum(change for change in window if change > 0)
    losses = sum(-change for change in window if change < 0)
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + (gains / losses)))


def _average_volume(candles: list[dict[str, object]]) -> float:
    volumes = [_number(candle, "candle_acc_trade_volume") for candle in candles]
    return sum(volumes) / len(volumes) if volumes else 0.0


def normalize_strategy_params(params: StrategyParams) -> StrategyParams:
    return replace(
        params,
        strategy_name=STRATEGY_NAME,
        regime_filter_enabled=True,
        regime_ema_fast=max(2, min(int(params.regime_ema_fast), 12)),
        regime_ema_slow=max(3, min(int(params.regime_ema_slow), 24)),
        take_profit_r=max(1.5, float(params.take_profit_r)),
    )


def _reject(reason: str, diagnostics: dict[str, object]) -> StrategySignal:
    return StrategySignal(
        accepted=False,
        reason=reason,
        diagnostics={
            "setup_model": "nfi_pullback",
            "entry_price": 0.0,
            "stop_price": 0.0,
            "r_value": 0.0,
            **diagnostics,
        },
    )


def evaluate_long_entry(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
) -> StrategySignal:
    effective = normalize_strategy_params(params)
    raw_candles = (data.get("1m"), data.get("5m"), data.get("15m"))
    if not all(isinstance(candles, list) for candles in raw_candles):
        return _reject("malformed_candles", {"actual_candles": raw_candles})
    candles_1m, candles_5m, candles_15m = raw_candles
    required = (
        effective.min_candles_1m,
        effective.min_candles_5m,
        effective.min_candles_15m,
    )
    actual = (len(candles_1m), len(candles_5m), len(candles_15m))
    if not all(
        all(isinstance(candle, dict) for candle in candles)
        for candles in (candles_1m, candles_5m, candles_15m)
    ):
        return _reject("malformed_candles", {"actual_candles": actual})
    if any(actual[index] < required[index] for index in range(3)):
        return _reject("insufficient_candles", {"required_candles": required, "actual_candles": actual})

    slow_period = max(int(effective.regime_ema_slow), int(effective.regime_ema_fast) + 1)
    trend_fast = _ema(candles_15m, int(effective.regime_ema_fast))
    trend_slow = _ema(candles_15m, slow_period)
    trend_close = _number(candles_15m[0])
    trend_pass = trend_fast > trend_slow and trend_close > trend_fast

    latest = candles_5m[0]
    previous = candles_5m[1]
    latest_close = _number(latest)
    previous_close = _number(previous)
    latest_ema = _ema(candles_5m, int(effective.regime_ema_fast))
    pullback_pass = previous_close < latest_ema and latest_close > latest_ema
    bullish_reclaim = _number(latest, "opening_price") < latest_close
    volume_average = _average_volume(candles_5m[1:])
    volume_pass = (
        volume_average > 0
        and _number(latest, "candle_acc_trade_volume")
        >= volume_average * _VOLUME_MULTIPLIER
    )
    rsi = _rsi(candles_5m, max(2, int(effective.rsi_period)))
    rsi_pass = max(40.0, float(effective.rsi_long_threshold)) <= rsi <= 70.0
    diagnostics = {
        "trend_pass": trend_pass,
        "pullback_pass": pullback_pass,
        "bullish_reclaim": bullish_reclaim,
        "volume_pass": volume_pass,
        "rsi_pass": rsi_pass,
        "rsi_overbought": rsi > 70.0,
        "trend_ema_fast": trend_fast,
        "trend_ema_slow": trend_slow,
        "rsi": rsi,
        "volume_average": volume_average,
    }
    if not trend_pass:
        return _reject("higher_timeframe_trend_fail", diagnostics)
    if not all((pullback_pass, bullish_reclaim, volume_pass, rsi_pass)):
        return _reject("pullback_confirmation_fail", diagnostics)

    entry_price = _number(candles_1m[0])
    swing_low = min(_number(candle, "low_price") for candle in candles_5m[:3])
    stop_price = min(swing_low, _number(candles_1m[0], "low_price"))
    risk = entry_price - stop_price
    if entry_price <= 0 or stop_price <= 0 or risk <= 0:
        return _reject("invalid_risk_geometry", diagnostics)
    return StrategySignal(
        accepted=True,
        reason="ok",
        diagnostics={
            "setup_model": "nfi_pullback",
            "entry_tag": "trend_pullback_volume_confirmed",
            "entry_price": entry_price,
            "stop_price": stop_price,
            "invalidation_price": stop_price,
            "r_value": risk,
            "tp1_r": 1.0,
            "tp2_r": float(effective.take_profit_r),
            **diagnostics,
        },
    )


def should_exit_long(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
    *,
    entry_price: float,
    initial_stop_price: float,
    risk_per_unit: float,
) -> bool:
    raw_1m = data.get("1m")
    raw_15m = data.get("15m")
    if not isinstance(raw_1m, list) or not isinstance(raw_15m, list):
        return False
    candles_1m = raw_1m
    candles_15m = raw_15m
    if (
        not candles_1m
        or not all(isinstance(candle, dict) for candle in candles_1m)
        or not all(isinstance(candle, dict) for candle in candles_15m)
        or entry_price <= 0
        or initial_stop_price <= 0
        or risk_per_unit <= 0
    ):
        return False
    current_price = _number(candles_1m[0])
    target = entry_price + (risk_per_unit * normalize_strategy_params(params).take_profit_r)
    trend_failed = bool(candles_15m) and _number(candles_15m[0]) < _ema(
        candles_15m, max(2, int(params.regime_ema_fast))
    )
    return current_price <= initial_stop_price or current_price >= target or trend_failed
