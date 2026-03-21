from __future__ import annotations

from typing import Any, Sequence

from core.strategy import StrategyParams, detect_fvg_zones, detect_ob_zones
from core.strategies.ict_sessions import is_in_silver_bullet_window


UNICORN_MAX_ENTRY_OVERLAP_RATIO = 2.0 / 3.0


def _price(candle: dict[str, object], key: str) -> float:
    value = candle.get(key, 0.0)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _overlap(
    lower_a: float, upper_a: float, lower_b: float, upper_b: float
) -> tuple[float, float] | None:
    lower = max(lower_a, lower_b)
    upper = min(upper_a, upper_b)
    if upper <= lower:
        return None
    return lower, upper


def detect_bullish_turtle_soup(
    candles_newest: Sequence[dict[str, object]],
) -> dict[str, object]:
    candles = list(candles_newest)
    if len(candles) < 4:
        return {"pass": False, "reason": "insufficient_candles"}

    reclaim_candle = candles[0]
    sweep_candle = candles[1]
    prior_candles = candles[2:]
    reference_low = min(_price(candle, "low_price") for candle in prior_candles)
    sweep_low = _price(sweep_candle, "low_price")
    reclaim_close = _price(reclaim_candle, "trade_price")
    if sweep_low >= reference_low:
        return {
            "pass": False,
            "reason": "no_sweep",
            "reference_low": reference_low,
            "sweep_low": sweep_low,
        }
    if reclaim_close <= reference_low:
        return {
            "pass": False,
            "reason": "no_reclaim",
            "reference_low": reference_low,
            "sweep_low": sweep_low,
        }
    return {
        "pass": True,
        "reason": "ok",
        "reference_low": reference_low,
        "sweep_low": sweep_low,
        "entry_price": reclaim_close,
        "stop_price": sweep_low,
        "score": 4.0,
    }


def detect_bullish_unicorn(
    candles_newest: Sequence[dict[str, object]],
    params: StrategyParams,
) -> dict[str, object]:
    candles = list(candles_newest)
    if len(candles) < 3:
        return {"pass": False, "reason": "insufficient_candles"}

    bullish_fvgs = [
        zone
        for zone in detect_fvg_zones(candles, params)
        if zone.get("bias") == "bullish"
    ]
    bullish_obs = [
        zone
        for zone in detect_ob_zones(candles, params)
        if zone.get("bias") == "bullish"
    ]
    current_price = _price(candles[0], "trade_price")
    best_match: dict[str, object] | None = None
    best_overlap_upper = float("-inf")
    best_high_entry_reject: dict[str, object] | None = None
    best_high_entry_reject_overlap_upper = float("-inf")

    for fvg in bullish_fvgs:
        fvg_lower = _as_float(fvg.get("lower"))
        fvg_upper = _as_float(fvg.get("upper"))
        for ob in bullish_obs:
            ob_lower = _as_float(ob.get("lower"))
            ob_upper = _as_float(ob.get("upper"))
            overlap = _overlap(fvg_lower, fvg_upper, ob_lower, ob_upper)
            if overlap is None:
                continue
            overlap_lower, overlap_upper = overlap
            if not (overlap_lower <= current_price <= overlap_upper):
                continue
            overlap_width = overlap_upper - overlap_lower
            if overlap_width <= 0:
                continue
            overlap_entry_ratio = (current_price - overlap_lower) / overlap_width
            if overlap_entry_ratio > UNICORN_MAX_ENTRY_OVERLAP_RATIO:
                reject_candidate: dict[str, object] = {
                    "pass": False,
                    "reason": "entry_too_high_in_overlap",
                    "overlap_lower": overlap_lower,
                    "overlap_upper": overlap_upper,
                    "entry_price": current_price,
                }
                if overlap_upper > best_high_entry_reject_overlap_upper:
                    best_high_entry_reject = reject_candidate
                    best_high_entry_reject_overlap_upper = overlap_upper
                continue
            candidate: dict[str, object] = {
                "pass": True,
                "reason": "ok",
                "overlap_lower": overlap_lower,
                "overlap_upper": overlap_upper,
                "entry_price": current_price,
                "stop_price": min(
                    _price(candles[0], "low_price"),
                    _as_float(ob.get("lower")),
                ),
                "score": 3.0,
                "fvg_zone": dict(fvg),
                "ob_zone": dict(ob),
            }
            if overlap_upper > best_overlap_upper:
                best_match = candidate
                best_overlap_upper = overlap_upper

    if best_match is not None:
        return best_match
    if best_high_entry_reject is not None:
        return best_high_entry_reject
    return {"pass": False, "reason": "no_overlap"}


def is_price_in_ote_long_pocket(
    *,
    price: float,
    dealing_range_low: float,
    dealing_range_high: float,
) -> dict[str, object]:
    if dealing_range_high <= dealing_range_low:
        return {"pass": False, "reason": "invalid_dealing_range"}
    dealing_range = dealing_range_high - dealing_range_low
    pocket_lower = dealing_range_high - (dealing_range * 0.79)
    pocket_upper = dealing_range_high - (dealing_range * 0.62)
    passed = pocket_lower <= price <= pocket_upper
    return {
        "pass": passed,
        "reason": "ok" if passed else "outside_ote_pocket",
        "pocket_lower": pocket_lower,
        "pocket_upper": pocket_upper,
        "entry_price": price,
        "stop_price": dealing_range_low,
        "score": 2.0,
    }


def select_recent_dealing_range(
    candles_newest: Sequence[dict[str, object]],
) -> dict[str, object]:
    candles = list(candles_newest)
    if len(candles) < 2:
        return {"pass": False, "reason": "insufficient_candles"}
    prior_candles = candles[1:]
    dealing_range_low = min(_price(candle, "low_price") for candle in prior_candles)
    dealing_range_high = max(_price(candle, "high_price") for candle in prior_candles)
    if dealing_range_high <= dealing_range_low:
        return {"pass": False, "reason": "invalid_dealing_range"}
    return {
        "pass": True,
        "reason": "ok",
        "dealing_range_low": dealing_range_low,
        "dealing_range_high": dealing_range_high,
    }


def detect_bullish_ote(
    candles_15m_newest: Sequence[dict[str, object]],
    *,
    entry_price: float,
) -> dict[str, object]:
    dealing_range = select_recent_dealing_range(candles_15m_newest)
    if not dealing_range.get("pass", False):
        return dict(dealing_range)
    result = is_price_in_ote_long_pocket(
        price=entry_price,
        dealing_range_low=_as_float(dealing_range.get("dealing_range_low")),
        dealing_range_high=_as_float(dealing_range.get("dealing_range_high")),
    )
    result["dealing_range_low"] = dealing_range["dealing_range_low"]
    result["dealing_range_high"] = dealing_range["dealing_range_high"]
    return result


def detect_bullish_silver_bullet(
    candles_5m_newest: Sequence[dict[str, object]],
    entry_candle_1m: dict[str, object],
    params: StrategyParams,
) -> dict[str, object]:
    if not is_in_silver_bullet_window(entry_candle_1m):
        return {"pass": False, "reason": "outside_silver_bullet_window"}
    if _price(entry_candle_1m, "trade_price") <= _price(
        entry_candle_1m, "opening_price"
    ):
        return {"pass": False, "reason": "no_bullish_trigger"}

    entry_price = _price(entry_candle_1m, "trade_price")
    bullish_fvgs = [
        zone
        for zone in detect_fvg_zones(candles_5m_newest, params)
        if zone.get("bias") == "bullish"
    ]
    for zone in bullish_fvgs:
        lower = float(zone.get("lower", 0.0))
        upper = float(zone.get("upper", 0.0))
        if lower <= entry_price <= upper:
            return {
                "pass": True,
                "reason": "ok",
                "entry_price": entry_price,
                "stop_price": lower,
                "zone_lower": lower,
                "zone_upper": upper,
                "score": 2.5,
                "fvg_zone": dict(zone),
            }
    return {"pass": False, "reason": "no_fvg_retrace"}


__all__ = [
    "detect_bullish_ote",
    "detect_bullish_silver_bullet",
    "detect_bullish_turtle_soup",
    "detect_bullish_unicorn",
    "is_price_in_ote_long_pocket",
    "select_recent_dealing_range",
]
