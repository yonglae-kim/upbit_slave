from __future__ import annotations

from dataclasses import replace
from collections.abc import Sequence

from core.decision_models import StrategySignal
from core.strategy import StrategyParams, classify_market_regime


STRATEGY_NAME = "candidate_v1"
MIN_CANDLES_1M = 6
MIN_CANDLES_5M = 8
SHORT_HORIZON_REGIME_EMA_FAST_MAX = 8
SHORT_HORIZON_REGIME_EMA_SLOW_MAX = 34
MIN_RECLAIM_RECOVERY_RATIO = 0.5
MAX_PULLBACK_DEPTH_RATIO = 1.3


def _ema_last(candles_newest: Sequence[dict[str, object]], period: int) -> float:
    candles = _candles_oldest(candles_newest)
    closes = [_price(candle, "trade_price") for candle in candles]
    if not closes:
        return 0.0
    alpha = 2.0 / (max(period, 1) + 1)
    ema = closes[0]
    for close_price in closes[1:]:
        ema = (close_price * alpha) + (ema * (1 - alpha))
    return float(ema)


def _price(candle: dict[str, object], key: str, fallback: str = "trade_price") -> float:
    value = candle.get(key, candle.get(fallback, 0.0))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _numeric(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _candles_oldest(
    candles_newest: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    return list(reversed(list(candles_newest)))


def _candles_from_data(
    data: dict[str, list[dict[str, object]]],
    timeframe: str,
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
    max_bars = max(1, int(_numeric(defaults.get("proof_window_max_bars"))))
    promotion_threshold_r = max(
        0.0,
        _numeric(defaults.get("proof_window_promotion_threshold_r")),
    )
    cooldown_hint_bars = max(
        0,
        int(_numeric(defaults.get("proof_window_cooldown_hint_bars"))),
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
    regime_ema_fast = max(
        2,
        min(int(params.regime_ema_fast), SHORT_HORIZON_REGIME_EMA_FAST_MAX),
    )
    regime_ema_slow = min(
        int(params.regime_ema_slow),
        SHORT_HORIZON_REGIME_EMA_SLOW_MAX,
    )
    if regime_ema_slow <= regime_ema_fast:
        regime_ema_slow = regime_ema_fast + 1
    return replace(
        params,
        regime_ema_fast=regime_ema_fast,
        regime_ema_slow=regime_ema_slow,
    )


def _required_15m_candles(params: StrategyParams) -> int:
    return max(
        int(params.regime_ema_slow),
        int(params.regime_adx_period) + 1,
        int(params.regime_slope_lookback) + 1,
    )


def _compact_regime_map(
    candles_newest: Sequence[dict[str, object]],
    params: StrategyParams,
) -> dict[str, object]:
    regime = classify_market_regime(candles_newest, params)
    regime_ready = regime in {"strong_trend", "weak_trend"}
    fast_ema = _ema_last(candles_newest, max(2, int(params.regime_ema_fast)))
    slow_ema = _ema_last(candles_newest, max(3, int(params.regime_ema_slow)))
    latest_close = _price(candles_newest[0], "trade_price") if candles_newest else 0.0
    regime_strength = (
        1.0 if regime == "strong_trend" else 0.75 if regime == "weak_trend" else 0.0
    )
    return {
        "regime": str(regime or "unknown"),
        "regime_map_state": "trend_ready" if regime_ready else "blocked",
        "expected_hold_type": (
            "trend_expansion"
            if regime == "strong_trend"
            else "trend_rotation"
            if regime == "weak_trend"
            else "none"
        ),
        "regime_strength": float(regime_strength),
        "ema_fast_15m": float(fast_ema),
        "ema_slow_15m": float(slow_ema),
        "latest_close_15m": float(latest_close),
    }


def _five_minute_setup(
    candles_newest: Sequence[dict[str, object]],
) -> dict[str, float | bool]:
    candles = _candles_oldest(candles_newest)
    if len(candles) < MIN_CANDLES_5M:
        return {
            "trend_confirmed": False,
            "setup_ready": False,
            "setup_quality": 0.0,
            "pullback_depth_ratio": 0.0,
            "reset_low": 0.0,
            "anchor_high": 0.0,
        }

    lows = [_price(candle, "low_price") for candle in candles]
    highs = [_price(candle, "high_price") for candle in candles]
    closes = [_price(candle, "trade_price") for candle in candles]
    fast_ema = _ema_last(list(reversed(candles)), 5)
    slow_ema = _ema_last(list(reversed(candles)), 9)

    prior_lows = lows[-8:-4]
    recent_lows = lows[-4:-1]
    anchor_high = max(highs[-6:-1])
    reset_low = min(recent_lows)
    impulse_floor = min(prior_lows)
    depth_denominator = max(anchor_high - impulse_floor, 1e-9)
    pullback_depth_ratio = max(anchor_high - reset_low, 0.0) / depth_denominator
    last_close = closes[-1]
    trend_confirmed = last_close > fast_ema > slow_ema and min(recent_lows) > min(
        prior_lows
    )
    setup_ready = trend_confirmed and 0.12 <= pullback_depth_ratio <= 0.75
    pullback_quality = max(0.0, 1.0 - abs(pullback_depth_ratio - 0.38) / 0.38)
    setup_quality = (0.55 if trend_confirmed else 0.0) + (0.45 * pullback_quality)
    return {
        "trend_confirmed": trend_confirmed,
        "setup_ready": setup_ready,
        "setup_quality": float(min(setup_quality, 1.0)),
        "pullback_depth_ratio": float(pullback_depth_ratio),
        "reset_low": float(reset_low),
        "anchor_high": float(anchor_high),
    }


def _pullback_reclaim_signal(
    candles_newest: Sequence[dict[str, object]],
) -> dict[str, float | bool]:
    candles = _candles_oldest(candles_newest)
    if len(candles) < 6:
        return {
            "pullback_seen": False,
            "reclaim_confirmed": False,
            "reclaim_level": 0.0,
            "reclaim_recovery_ratio": 0.0,
            "pullback_depth_ratio": 0.0,
            "pullback_too_deep": False,
            "pullback_low": 0.0,
            "entry_price": 0.0,
            "micro_breakout_level": 0.0,
        }

    impulse_slice = candles[-6:-3]
    pullback_slice = candles[-3:-1]
    reclaim_candle = candles[-1]

    reclaim_level = max(_price(candle, "trade_price") for candle in impulse_slice)
    pullback_low = min(_price(candle, "low_price") for candle in pullback_slice)
    last_pullback_close = _price(pullback_slice[-1], "trade_price")
    entry_price = _price(reclaim_candle, "trade_price")
    micro_breakout_level = max(
        _price(candle, "high_price") for candle in candles[-4:-1]
    )
    reclaim_gap = max(reclaim_level - last_pullback_close, 0.0)
    reclaim_floor = last_pullback_close + (reclaim_gap * MIN_RECLAIM_RECOVERY_RATIO)
    micro_trigger_floor = max(
        reclaim_floor,
        micro_breakout_level - reclaim_gap,
    )
    reclaim_recovery_ratio = (
        max(entry_price - last_pullback_close, 0.0) / reclaim_gap
        if reclaim_gap > 0
        else 0.0
    )
    pullback_depth_ratio = (
        max(reclaim_level - pullback_low, 0.0) / reclaim_gap if reclaim_gap > 0 else 0.0
    )
    reclaim_confirmed = entry_price >= micro_trigger_floor and entry_price > _price(
        reclaim_candle, "opening_price"
    )
    pullback_too_deep = pullback_depth_ratio > MAX_PULLBACK_DEPTH_RATIO
    pullback_seen = pullback_low < reclaim_level and last_pullback_close < reclaim_level

    return {
        "pullback_seen": pullback_seen,
        "reclaim_confirmed": reclaim_confirmed,
        "reclaim_level": float(reclaim_level),
        "reclaim_floor": float(reclaim_floor),
        "micro_trigger_floor": float(micro_trigger_floor),
        "reclaim_recovery_ratio": float(reclaim_recovery_ratio),
        "pullback_depth_ratio": float(pullback_depth_ratio),
        "pullback_too_deep": pullback_too_deep,
        "pullback_low": float(pullback_low),
        "entry_price": float(entry_price),
        "micro_breakout_level": float(micro_breakout_level),
    }


def evaluate_long_entry(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
) -> StrategySignal:
    candles_1m = _candles_from_data(data, "1m")
    candles_5m = _candles_from_data(data, "5m")
    candles_15m = _candles_from_data(data, "15m")
    symbol = _symbol_from_data(data)
    regime_params = normalize_strategy_params(params)
    required_15m = _required_15m_candles(regime_params)
    if len(candles_1m) < MIN_CANDLES_1M:
        return StrategySignal(
            accepted=False,
            reason="insufficient_1m_candles",
            diagnostics={
                "required_1m": MIN_CANDLES_1M,
                "actual_1m": len(candles_1m),
            },
        )
    if len(candles_5m) < MIN_CANDLES_5M:
        return StrategySignal(
            accepted=False,
            reason="insufficient_5m_candles",
            diagnostics={
                "required_5m": MIN_CANDLES_5M,
                "actual_5m": len(candles_5m),
            },
        )
    if len(candles_15m) < required_15m:
        return StrategySignal(
            accepted=False,
            reason="insufficient_15m_candles",
            diagnostics={
                "required_15m": required_15m,
                "actual_15m": len(candles_15m),
            },
        )
    regime_map = _compact_regime_map(candles_15m, regime_params)
    regime = str(regime_map["regime"])
    regime_ok = bool(regime_map["regime_map_state"] == "trend_ready")
    setup_5m = _five_minute_setup(candles_5m)
    trend_confirmed_5m = bool(setup_5m["trend_confirmed"])
    pullback = _pullback_reclaim_signal(candles_1m)
    pullback_seen = bool(pullback["pullback_seen"])
    reclaim_confirmed = bool(pullback["reclaim_confirmed"])
    pullback_too_deep = bool(pullback["pullback_too_deep"])
    entry_price = float(pullback["entry_price"])
    pullback_stop = float(pullback["pullback_low"])
    reset_stop = float(setup_5m["reset_low"] or pullback_stop)
    stop_price = min(pullback_stop, reset_stop)
    stop_basis = "reset_low_5m" if reset_stop < pullback_stop else "pullback_low"
    risk = max(entry_price - stop_price, 0.0)
    safety_pass = entry_price > 0 and stop_price > 0 and risk > 0
    continuation_quality = min(
        float(pullback["reclaim_recovery_ratio"]) / 1.25,
        1.0,
    )
    signal_quality = min(
        1.0,
        (0.4 * _numeric(regime_map["regime_strength"]))
        + (0.3 * _numeric(setup_5m["setup_quality"]))
        + (0.3 * continuation_quality),
    )
    entry_score = (
        (1.2 * float(regime_ok))
        + (1.0 * float(setup_5m["setup_ready"]))
        + (0.6 * float(pullback_seen))
        + (1.2 * continuation_quality if reclaim_confirmed else 0.0)
    )
    score_pass = entry_score >= float(params.entry_score_threshold)

    filter_pass = regime_ok
    setup_pass = (
        bool(setup_5m["setup_ready"]) and pullback_seen and not pullback_too_deep
    )
    trigger_pass = reclaim_confirmed
    final_pass = (
        filter_pass and setup_pass and trigger_pass and safety_pass and score_pass
    )

    if not regime_ok:
        reason = "regime_blocked"
    elif not trend_confirmed_5m:
        reason = "trend_context_fail"
    elif not bool(setup_5m["setup_ready"]):
        reason = "setup_context_fail"
    elif not pullback_seen:
        reason = "pullback_missing"
    elif pullback_too_deep:
        reason = "pullback_too_deep"
    elif not reclaim_confirmed:
        reason = "reclaim_missing"
    elif not safety_pass:
        reason = "safety_fail"
    elif not score_pass:
        reason = "score_below_threshold"
    else:
        reason = "ok"

    regime_quality_base = (
        0.47 if regime == "strong_trend" else 0.42 if regime == "weak_trend" else 0.0
    )
    quality_score = regime_quality_base + (0.08 * continuation_quality)
    diagnostics: dict[str, object] = {
        "regime": str(regime or "unknown"),
        "regime_map_state": str(regime_map["regime_map_state"]),
        "expected_hold_type": str(regime_map["expected_hold_type"]),
        "trend_confirmed_5m": trend_confirmed_5m,
        "setup_ready": bool(setup_5m["setup_ready"]),
        "setup_quality": float(setup_5m["setup_quality"]),
        "pullback_seen": pullback_seen,
        "pullback_too_deep": pullback_too_deep,
        "reclaim_confirmed": reclaim_confirmed,
        "reclaim_level": float(pullback["reclaim_level"]),
        "reclaim_floor": float(pullback["reclaim_floor"]),
        "micro_breakout_level": float(pullback["micro_breakout_level"]),
        "reclaim_recovery_ratio": float(pullback["reclaim_recovery_ratio"]),
        "pullback_depth_ratio": float(pullback["pullback_depth_ratio"]),
        "setup_depth_ratio": float(setup_5m["pullback_depth_ratio"]),
        "continuation_quality": continuation_quality,
        "pullback_low": pullback_stop,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "invalidation_price": stop_price,
        "stop_basis": stop_basis,
        "r_value": risk,
        "entry_score": entry_score,
        "score_threshold": float(params.entry_score_threshold),
        "quality_score": quality_score,
        "signal_quality": signal_quality,
        "use_quality_multiplier": False,
        **_proof_window_diagnostics(symbol, active=final_pass),
    }
    return StrategySignal(
        accepted=final_pass,
        reason=reason,
        diagnostics=diagnostics,
    )


def should_exit_long(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
    *,
    entry_price: float,
    initial_stop_price: float,
    risk_per_unit: float,
) -> bool:
    _ = data, params, entry_price, initial_stop_price, risk_per_unit
    return False


__all__ = [
    "STRATEGY_NAME",
    "StrategySignal",
    "evaluate_long_entry",
    "normalize_strategy_params",
    "should_exit_long",
]
