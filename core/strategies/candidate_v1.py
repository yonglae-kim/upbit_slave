from __future__ import annotations

from collections.abc import Sequence

from core.decision_models import StrategySignal
from core.strategy import StrategyParams, classify_market_regime


STRATEGY_NAME = "candidate_v1"
MIN_CANDLES_1M = 6
MIN_CANDLES_5M = 6


def _price(candle: dict[str, object], key: str, fallback: str = "trade_price") -> float:
    value = candle.get(key, candle.get(fallback, 0.0))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _candles_oldest(
    candles_newest: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    return list(reversed(list(candles_newest)))


def _trend_confirmation_5m(candles_newest: Sequence[dict[str, object]]) -> bool:
    candles = _candles_oldest(candles_newest)
    if len(candles) < 6:
        return False
    recent_lows = [_price(candle, "low_price") for candle in candles[-3:]]
    prior_lows = [_price(candle, "low_price") for candle in candles[-6:-3]]
    recent_closes = [_price(candle, "trade_price") for candle in candles[-3:]]
    return min(recent_lows) > min(prior_lows) and recent_closes[-1] > recent_closes[0]


def _pullback_reclaim_signal(
    candles_newest: Sequence[dict[str, object]],
) -> dict[str, float | bool]:
    candles = _candles_oldest(candles_newest)
    if len(candles) < 6:
        return {
            "pullback_seen": False,
            "reclaim_confirmed": False,
            "reclaim_level": 0.0,
            "pullback_low": 0.0,
            "entry_price": 0.0,
        }

    impulse_slice = candles[-6:-3]
    pullback_slice = candles[-3:-1]
    reclaim_candle = candles[-1]

    reclaim_level = max(_price(candle, "trade_price") for candle in impulse_slice)
    pullback_low = min(_price(candle, "low_price") for candle in pullback_slice)
    last_pullback_close = _price(pullback_slice[-1], "trade_price")
    entry_price = _price(reclaim_candle, "trade_price")
    reclaim_confirmed = entry_price > reclaim_level and entry_price > _price(
        reclaim_candle, "opening_price"
    )
    pullback_seen = pullback_low < reclaim_level and last_pullback_close < reclaim_level

    return {
        "pullback_seen": pullback_seen,
        "reclaim_confirmed": reclaim_confirmed,
        "reclaim_level": float(reclaim_level),
        "pullback_low": float(pullback_low),
        "entry_price": float(entry_price),
    }


def evaluate_long_entry(
    data: dict[str, list[dict[str, object]]],
    params: StrategyParams,
) -> StrategySignal:
    candles_1m = list(data.get("1m", []))
    candles_5m = list(data.get("5m", []))
    candles_15m = list(data.get("15m", []))
    required_15m = max(
        int(params.regime_ema_slow),
        int(params.regime_adx_period) + 1,
        int(params.regime_slope_lookback) + 1,
    )
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
    regime = classify_market_regime(candles_15m, params)
    regime_ok = regime in {"strong_trend", "weak_trend"}
    trend_confirmed_5m = _trend_confirmation_5m(candles_5m)
    pullback = _pullback_reclaim_signal(candles_1m)
    pullback_seen = bool(pullback["pullback_seen"])
    reclaim_confirmed = bool(pullback["reclaim_confirmed"])
    entry_price = float(pullback["entry_price"])
    stop_price = float(pullback["pullback_low"])
    risk = max(entry_price - stop_price, 0.0)
    safety_pass = entry_price > 0 and stop_price > 0 and risk > 0
    entry_score = (
        float(regime_ok)
        + float(trend_confirmed_5m)
        + float(pullback_seen)
        + float(reclaim_confirmed)
    )
    score_pass = entry_score >= float(params.entry_score_threshold)

    filter_pass = regime_ok
    setup_pass = trend_confirmed_5m and pullback_seen
    trigger_pass = reclaim_confirmed
    final_pass = (
        filter_pass and setup_pass and trigger_pass and safety_pass and score_pass
    )

    if not regime_ok:
        reason = "regime_blocked"
    elif not trend_confirmed_5m:
        reason = "trend_context_fail"
    elif not pullback_seen:
        reason = "pullback_missing"
    elif not reclaim_confirmed:
        reason = "reclaim_missing"
    elif not safety_pass:
        reason = "safety_fail"
    elif not score_pass:
        reason = "score_below_threshold"
    else:
        reason = "ok"

    quality_score = (
        0.55 if regime == "strong_trend" else 0.5 if regime == "weak_trend" else 0.0
    )
    diagnostics: dict[str, object] = {
        "regime": str(regime or "unknown"),
        "trend_confirmed_5m": trend_confirmed_5m,
        "pullback_seen": pullback_seen,
        "reclaim_confirmed": reclaim_confirmed,
        "reclaim_level": float(pullback["reclaim_level"]),
        "pullback_low": stop_price,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "stop_basis": "pullback_low",
        "r_value": risk,
        "entry_score": entry_score,
        "score_threshold": float(params.entry_score_threshold),
        "quality_score": quality_score,
        "use_quality_multiplier": False,
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
    "should_exit_long",
]
