from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.decision_models import StrategySignal
from core.strategy import StrategyParams, check_sell, debug_entry


STRATEGY_NAME = "candidate_v1"
REGIME_EMA_FAST_MAX = 12
REGIME_EMA_SLOW_MAX = 48
MIN_CANDIDATE_REQUIRED_TRIGGER_COUNT = 2
MIN_CANDIDATE_SELL_PROFIT_THRESHOLD = 1.003


def _price(candle: dict[str, object], key: str, fallback: str = "trade_price") -> float:
    value = candle.get(key, candle.get(fallback, 0.0))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(default)


def _candles_from_data(
    data: dict[str, list[dict[str, object]]], timeframe: str
) -> list[dict[str, object]]:
    return list(data.get(timeframe, []))


def _symbol_from_data(data: dict[str, list[dict[str, object]]]) -> str:
    meta = list(data.get("meta", []))
    if not meta:
        return ""
    value = meta[0].get("symbol")
    if value is None:
        return ""
    return str(value).strip().upper()


def _proof_window_diagnostics(symbol: str, *, active: bool) -> dict[str, object]:
    from importlib import import_module

    defaults_module = import_module("core.candidate_strategy_defaults")
    resolve_defaults = getattr(defaults_module, "candidate_v1_proof_window_defaults")
    defaults = dict(resolve_defaults(symbol))
    max_bars = max(1, int(float(defaults.get("proof_window_max_bars", 1))))
    promotion_threshold_r = max(
        0.0,
        float(defaults.get("proof_window_promotion_threshold_r", 0.0)),
    )
    cooldown_hint_bars = max(
        0,
        int(float(defaults.get("proof_window_cooldown_hint_bars", 0))),
    )
    symbol_profile = str(defaults.get("proof_window_symbol_profile") or "default")
    return {
        "proof_window_active": active,
        "proof_window_promoted": False,
        "proof_window_status": "pending" if active else "inactive",
        "proof_window_start_bar": 0,
        "proof_window_elapsed_bars": 0,
        "proof_window_max_bars": max_bars,
        "proof_window_max_favorable_excursion_r": 0.0,
        "proof_window_promotion_threshold_r": promotion_threshold_r,
        "proof_window_cooldown_hint_bars": cooldown_hint_bars,
        "proof_window_symbol_profile": symbol_profile,
    }


def normalize_strategy_params(params: StrategyParams) -> StrategyParams:
    regime_ema_fast = max(2, min(int(params.regime_ema_fast), REGIME_EMA_FAST_MAX))
    regime_ema_slow = min(int(params.regime_ema_slow), REGIME_EMA_SLOW_MAX)
    if regime_ema_slow <= regime_ema_fast:
        regime_ema_slow = regime_ema_fast + 1
    normalized = replace(
        params,
        strategy_name=STRATEGY_NAME,
        regime_filter_enabled=True,
        regime_ema_fast=regime_ema_fast,
        regime_ema_slow=regime_ema_slow,
    )
    if str(normalized.trigger_mode).strip().lower() == "adaptive":
        normalized = replace(normalized, trigger_mode="balanced")
    if int(normalized.required_trigger_count) < MIN_CANDIDATE_REQUIRED_TRIGGER_COUNT:
        normalized = replace(
            normalized,
            required_trigger_count=MIN_CANDIDATE_REQUIRED_TRIGGER_COUNT,
        )
    if not bool(normalized.sell_requires_profit):
        normalized = replace(normalized, sell_requires_profit=True)
    if float(normalized.sell_profit_threshold) < MIN_CANDIDATE_SELL_PROFIT_THRESHOLD:
        normalized = replace(
            normalized,
            sell_profit_threshold=MIN_CANDIDATE_SELL_PROFIT_THRESHOLD,
        )
    return normalized


def _exit_strategy_params(params: StrategyParams) -> StrategyParams:
    normalized = normalize_strategy_params(params)
    return replace(normalized, trigger_mode="adaptive", required_trigger_count=1)


def _regime_label(debug: dict[str, object]) -> str:
    regime_metrics = debug.get("regime_filter_metrics")
    if isinstance(regime_metrics, dict):
        value = regime_metrics.get("regime")
        if value is not None:
            return str(value)
    return "unknown"


def _expected_hold_type(regime: str) -> str:
    if regime == "strong_trend":
        return "trend_expansion"
    if regime == "weak_trend":
        return "trend_rotation"
    return "none"


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        raw = value
        return {str(key): item for key, item in raw.items()}
    return {}


def evaluate_long_entry(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
) -> StrategySignal:
    effective_params = normalize_strategy_params(params)
    debug = debug_entry(data, effective_params, side="buy")
    symbol = _symbol_from_data(data)
    regime = _regime_label(debug)
    selected_zone = _as_mapping(debug.get("selected_zone"))
    sr_flip_level = _as_mapping(debug.get("sr_flip_level"))
    candles_1m = _candles_from_data(data, "1m")
    entry_price = _price(candles_1m[0], "trade_price") if candles_1m else 0.0
    stop_candidates = [
        float(value)
        for value in (
            selected_zone.get("lower"),
            sr_flip_level.get("lower"),
        )
        if isinstance(value, (int, float)) and float(value) > 0
    ]
    stop_price = (
        min(stop_candidates)
        - (entry_price * float(effective_params.zone_reentry_buffer_pct))
        if stop_candidates and entry_price > 0
        else 0.0
    )
    risk = max(entry_price - stop_price, 0.0)
    trigger_pass = bool(debug.get("trigger_pass", False))
    sr_flip_pass = bool(debug.get("sr_flip_pass", False))
    zone_type = str(selected_zone.get("type") or "")
    flip_score = _as_float(sr_flip_level.get("score"), 0.0)
    zone_type_bonus = 0.55 if zone_type == "ob" else 0.45 if zone_type == "fvg" else 0.0
    entry_score = (
        1.25 * float(sr_flip_pass)
        + 1.0 * float(bool(selected_zone))
        + 1.0 * float(trigger_pass)
        + 1.4 * min(max(flip_score, 0.0), 1.0)
        + zone_type_bonus
    )
    quality_score = min(
        1.0,
        (0.5 * min(max(flip_score, 0.0), 1.0))
        + (0.2 * float(sr_flip_pass))
        + (0.2 * float(trigger_pass))
        + (0.1 * float(zone_type == "ob")),
    )
    safety_pass = entry_price > 0 and stop_price > 0 and risk > 0
    score_pass = entry_score >= float(effective_params.entry_score_threshold)
    helper_pass = bool(debug.get("final_pass", False))
    accepted = helper_pass and safety_pass and score_pass

    if not helper_pass:
        reason = str(debug.get("fail_code") or "hold")
    elif not safety_pass:
        reason = "safety_fail"
    elif not score_pass:
        reason = "score_below_threshold"
    else:
        reason = "ok"

    diagnostics: dict[str, object] = {
        "regime": regime,
        "entry_regime": regime,
        "expected_hold_type": _expected_hold_type(regime),
        "regime_filter_metrics": _as_mapping(debug.get("regime_filter_metrics")),
        "zones_total": int(debug.get("zones_total", 0) or 0),
        "zones_active": int(debug.get("zones_active", 0) or 0),
        "selected_zone": selected_zone or None,
        "selected_zone_type": zone_type,
        "selected_zone_lower": _as_float(selected_zone.get("lower"), 0.0),
        "selected_zone_upper": _as_float(selected_zone.get("upper"), 0.0),
        "sr_flip_pass": sr_flip_pass,
        "sr_flip_level": sr_flip_level or None,
        "sr_flip_break_index": int(debug.get("sr_flip_break_index", -1) or -1),
        "sr_flip_retest_index": int(debug.get("sr_flip_retest_index", -1) or -1),
        "sr_flip_hold_index": int(debug.get("sr_flip_hold_index", -1) or -1),
        "trigger_pass": trigger_pass,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "invalidation_price": stop_price,
        "stop_basis": "sr_flip_zone_low",
        "r_value": risk,
        "entry_score": entry_score,
        "score_threshold": float(effective_params.entry_score_threshold),
        "quality_score": quality_score,
        "signal_quality": quality_score,
        "use_quality_multiplier": False,
        "effective_strategy_params": {
            "strategy_name": STRATEGY_NAME,
            "trigger_mode": effective_params.trigger_mode,
            "required_trigger_count": int(effective_params.required_trigger_count),
            "sell_requires_profit": bool(effective_params.sell_requires_profit),
            "sell_profit_threshold": float(effective_params.sell_profit_threshold),
            "entry_score_threshold": float(effective_params.entry_score_threshold),
        },
        **_proof_window_diagnostics(symbol, active=accepted),
    }
    return StrategySignal(accepted=accepted, reason=reason, diagnostics=diagnostics)


def should_exit_long(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
    *,
    entry_price: float,
    initial_stop_price: float,
    risk_per_unit: float,
) -> bool:
    effective_params = _exit_strategy_params(params)
    return bool(
        check_sell(
            data,
            avg_buy_price=entry_price,
            params=effective_params,
            entry_price=entry_price,
            initial_stop_price=initial_stop_price,
            risk_per_unit=risk_per_unit,
        )
    )


__all__ = [
    "STRATEGY_NAME",
    "StrategySignal",
    "evaluate_long_entry",
    "normalize_strategy_params",
    "should_exit_long",
]
