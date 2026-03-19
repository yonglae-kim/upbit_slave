from __future__ import annotations

from dataclasses import replace

from core.decision_models import StrategySignal
from core.strategy import StrategyParams, check_sell, regime_filter_diagnostics
from core.strategies.ict_models import (
    detect_bullish_ote,
    detect_bullish_silver_bullet,
    detect_bullish_turtle_soup,
    detect_bullish_unicorn,
)


STRATEGY_NAME = "ict_v1"


def _price(candle: dict[str, object], key: str) -> float:
    value = candle.get(key, 0.0)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def normalize_strategy_params(params: StrategyParams) -> StrategyParams:
    normalized = replace(
        params,
        strategy_name=STRATEGY_NAME,
        regime_filter_enabled=True,
        regime_ema_fast=max(2, min(int(params.regime_ema_fast), 12)),
        regime_ema_slow=max(3, min(int(params.regime_ema_slow), 24)),
        partial_take_profit_enabled=True,
        partial_take_profit_r=max(1.0, float(params.partial_take_profit_r)),
        partial_take_profit_size=max(0.0, float(params.partial_take_profit_size)),
        move_stop_to_breakeven_after_partial=True,
    )
    if normalized.regime_ema_slow <= normalized.regime_ema_fast:
        normalized = replace(
            normalized,
            regime_ema_slow=int(normalized.regime_ema_fast) + 1,
        )
    if str(normalized.trigger_mode).strip().lower() == "adaptive":
        normalized = replace(normalized, trigger_mode="balanced")
    if int(normalized.required_trigger_count) < 2:
        normalized = replace(normalized, required_trigger_count=2)
    return normalized


def _reject(
    reason: str,
    model_results: dict[str, dict[str, object]],
    *,
    extra_diagnostics: dict[str, object] | None = None,
) -> StrategySignal:
    diagnostics: dict[str, object] = {
        "setup_model": "none",
        "entry_price": 0.0,
        "stop_price": 0.0,
        "invalidation_price": 0.0,
        "r_value": 0.0,
        "tp1_r": 1.0,
        "tp2_r": 2.0,
        "model_results": model_results,
    }
    if extra_diagnostics:
        diagnostics = {**diagnostics, **extra_diagnostics}
    return StrategySignal(accepted=False, reason=reason, diagnostics=diagnostics)


def _passes_bullish_micro_trigger(
    candles_1m: list[dict[str, object]], params: StrategyParams
) -> dict[str, object]:
    lookback = max(1, int(params.trigger_breakout_lookback))
    if len(candles_1m) < lookback + 1:
        return {"pass": False, "reason": "trigger_insufficient_candles"}

    latest = candles_1m[0]
    latest_open = _price(latest, "opening_price")
    latest_close = _price(latest, "trade_price")
    if latest_close <= latest_open:
        return {"pass": False, "reason": "trigger_not_bullish"}

    prior = candles_1m[1 : 1 + lookback]
    prior_high = max(_price(candle, "high_price") for candle in prior)
    if latest_close <= prior_high:
        return {
            "pass": False,
            "reason": "trigger_breakout_miss",
            "prior_high": prior_high,
        }
    return {"pass": True, "reason": "ok", "prior_high": prior_high}


def evaluate_long_entry(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
) -> StrategySignal:
    effective_params = normalize_strategy_params(params)
    candles_1m = list(data.get("1m", []))
    candles_5m = list(data.get("5m", []))
    candles_15m = list(data.get("15m", []))
    if (
        len(candles_1m) < effective_params.min_candles_1m
        or len(candles_5m) < effective_params.min_candles_5m
        or len(candles_15m) < effective_params.min_candles_15m
    ):
        return _reject("insufficient_candles", {})

    regime_diagnostics = regime_filter_diagnostics(candles_15m, effective_params)
    if not regime_diagnostics.get("pass", False):
        return _reject(
            "regime_filter_fail",
            {},
            extra_diagnostics={"regime_diagnostics": dict(regime_diagnostics)},
        )

    trigger_result = _passes_bullish_micro_trigger(candles_1m, effective_params)
    if not trigger_result.get("pass", False):
        return _reject(
            "trigger_fail",
            {},
            extra_diagnostics={"trigger_result": dict(trigger_result)},
        )

    entry_price = _price(candles_1m[0], "trade_price")
    turtle_soup = dict(detect_bullish_turtle_soup(candles_5m))
    unicorn = dict(detect_bullish_unicorn(candles_5m, effective_params))
    silver_bullet = dict(
        detect_bullish_silver_bullet(candles_5m, candles_1m[0], effective_params)
    )
    ote = dict(detect_bullish_ote(candles_15m, entry_price=entry_price))

    model_results = {
        "turtle_soup": turtle_soup,
        "unicorn": unicorn,
        "silver_bullet": silver_bullet,
        "ote": ote,
    }
    accepted_candidates: list[tuple[str, dict[str, object]]] = []
    for model_name, model_result in model_results.items():
        if not model_result.get("pass", False):
            continue
        stop_price = _as_float(model_result.get("stop_price"))
        risk = max(entry_price - stop_price, 0.0)
        if entry_price <= 0 or stop_price <= 0 or risk <= 0:
            continue
        accepted_candidates.append(
            (
                model_name,
                {
                    **model_result,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "r_value": risk,
                },
            )
        )

    if not accepted_candidates:
        return _reject("no_valid_setup", model_results)

    setup_model, selected = max(
        accepted_candidates,
        key=lambda item: (_as_float(item[1].get("score")), item[0]),
    )
    diagnostics = {
        "setup_model": setup_model,
        "entry_price": _as_float(selected.get("entry_price")),
        "stop_price": _as_float(selected.get("stop_price")),
        "invalidation_price": _as_float(selected.get("stop_price")),
        "r_value": _as_float(selected.get("r_value")),
        "tp1_r": float(effective_params.partial_take_profit_r),
        "tp2_r": float(effective_params.take_profit_r),
        "entry_regime": str(regime_diagnostics.get("regime", "unknown")),
        "regime_diagnostics": dict(regime_diagnostics),
        "trigger_result": dict(trigger_result),
        "model_results": model_results,
    }
    return StrategySignal(accepted=True, reason="ok", diagnostics=diagnostics)


def should_exit_long(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
    *,
    entry_price: float,
    initial_stop_price: float,
    risk_per_unit: float,
) -> bool:
    effective_params = normalize_strategy_params(params)
    candles_1m = list(data.get("1m", []))
    current_price = _price(candles_1m[0], "trade_price") if candles_1m else 0.0
    effective_risk = risk_per_unit
    if effective_risk <= 0 and entry_price > 0 and initial_stop_price > 0:
        effective_risk = max(entry_price - initial_stop_price, 0.0)
    if current_price <= 0 or entry_price <= 0 or effective_risk <= 0:
        return False
    tp2_price = entry_price + (effective_risk * float(effective_params.take_profit_r))
    return current_price >= tp2_price


__all__ = [
    "STRATEGY_NAME",
    "StrategySignal",
    "evaluate_long_entry",
    "normalize_strategy_params",
    "should_exit_long",
]
