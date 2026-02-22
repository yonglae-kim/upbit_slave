from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

from core.price_rules import min_krw_tick_from_candles
from typing import Any, Sequence


@dataclass(frozen=True)
class StrategyParams:
    buy_rsi_threshold: int = 35
    macd_n_fast: int = 12
    macd_n_slow: int = 26
    macd_n_signal: int = 9
    min_candle_extra: int = 3
    sell_profit_threshold: float = 1.01
    stop_loss_threshold: float = 0.975
    sr_pivot_left: int = 2
    sr_pivot_right: int = 2
    sr_cluster_band_pct: float = 0.0025
    sr_min_touches: int = 2
    sr_lookback_bars: int = 120
    sr_touch_weight: float = 0.5
    sr_recency_weight: float = 0.3
    sr_volume_weight: float = 0.2
    zone_priority_mode: str = "intersection"
    fvg_atr_period: int = 14
    fvg_min_width_atr_mult: float = 0.2
    fvg_min_width_ticks: int = 2
    displacement_min_body_ratio: float = 0.6
    displacement_min_atr_mult: float = 1.2
    ob_lookback_bars: int = 80
    ob_max_base_bars: int = 6
    zone_expiry_bars_5m: int = 36
    zone_reentry_buffer_pct: float = 0.0005
    trigger_rejection_wick_ratio: float = 0.35
    trigger_breakout_lookback: int = 3
    min_candles_1m: int = 80
    min_candles_5m: int = 120
    min_candles_15m: int = 120


def preprocess_candles(data: Sequence[dict[str, Any]], source_order: str = "newest") -> list[dict[str, Any]]:
    candles = list(data)
    if source_order not in {"newest", "oldest"}:
        raise ValueError("source_order must be 'newest' or 'oldest'")
    if source_order == "oldest":
        candles.reverse()
    return candles


def _price(candle: dict[str, Any], key: str, fallback: str = "trade_price") -> float:
    value = candle.get(key, candle.get(fallback, 0.0))
    return float(value)


def _atr(candles_newest: Sequence[dict[str, Any]], period: int) -> float:
    candles = list(reversed(candles_newest))
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        high = _price(cur, "high_price")
        low = _price(cur, "low_price")
        prev_close = _price(prev, "trade_price")
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if not trs:
        return 0.0
    window = trs[-min(period, len(trs)) :]
    return sum(window) / len(window)


def detect_sr_pivots(candles_newest: Sequence[dict[str, Any]], left: int, right: int) -> list[dict[str, Any]]:
    candles = list(reversed(candles_newest))
    pivots: list[dict[str, Any]] = []
    for i in range(left, len(candles) - right):
        candle = candles[i]
        high = _price(candle, "high_price")
        low = _price(candle, "low_price")
        left_slice = candles[i - left : i]
        right_slice = candles[i + 1 : i + 1 + right]
        turnover = float(candle.get("candle_acc_trade_price", candle.get("trade_volume", 0.0)))
        if all(high >= _price(c, "high_price") for c in left_slice + right_slice):
            pivots.append({"type": "resistance", "price": high, "index": i, "turnover": turnover})
        if all(low <= _price(c, "low_price") for c in left_slice + right_slice):
            pivots.append({"type": "support", "price": low, "index": i, "turnover": turnover})
    return pivots


def cluster_sr_levels(pivots: Sequence[dict[str, Any]], band_pct: float, min_touches: int) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for pivot in pivots:
        matched = False
        for cluster in clusters:
            mid = cluster["mid"]
            if mid == 0:
                continue
            if abs(pivot["price"] - mid) / mid <= band_pct and cluster["bias"] == pivot["type"]:
                cluster["prices"].append(pivot["price"])
                cluster["touches"] += 1
                cluster["last_index"] = max(cluster["last_index"], pivot["index"])
                cluster["mid"] = sum(cluster["prices"]) / len(cluster["prices"])
                cluster["turnover_sum"] += float(pivot.get("turnover", 0.0))
                matched = True
                break
        if not matched:
            clusters.append(
                {
                    "bias": pivot["type"],
                    "prices": [pivot["price"]],
                    "touches": 1,
                    "last_index": pivot["index"],
                    "mid": pivot["price"],
                    "turnover_sum": float(pivot.get("turnover", 0.0)),
                }
            )

    return [
        {
            "bias": cluster["bias"],
            "lower": min(cluster["prices"]),
            "upper": max(cluster["prices"]),
            "mid": cluster["mid"],
            "touches": cluster["touches"],
            "last_index": cluster["last_index"],
            "turnover": cluster["turnover_sum"],
        }
        for cluster in clusters
        if cluster["touches"] >= min_touches
    ]


def score_sr_levels(sr_levels: Sequence[dict[str, Any]], total_bars: int, params: StrategyParams) -> list[dict[str, Any]]:
    if not sr_levels:
        return []

    max_turnover = max(float(level.get("turnover", 0.0)) for level in sr_levels)
    scored: list[dict[str, Any]] = []
    for level in sr_levels:
        touches = int(level.get("touches", 0))
        touch_score = min(1.0, touches / max(params.sr_min_touches, 1))

        age = max(0, total_bars - int(level.get("last_index", 0)))
        recency_score = 1.0 - min(1.0, age / max(total_bars, 1))

        turnover = float(level.get("turnover", 0.0))
        volume_score = turnover / max_turnover if max_turnover > 0 else 0.0

        score = (
            params.sr_touch_weight * touch_score
            + params.sr_recency_weight * recency_score
            + params.sr_volume_weight * volume_score
        )

        enriched = dict(level)
        enriched["score"] = score
        scored.append(enriched)

    return sorted(scored, key=lambda item: item["score"], reverse=True)


def detect_fvg_zones(candles_newest: Sequence[dict[str, Any]], params: StrategyParams) -> list[dict[str, Any]]:
    candles = list(reversed(candles_newest))
    atr = _atr(candles_newest, params.fvg_atr_period)
    tick = min_krw_tick_from_candles(candles_newest)
    min_width = max(atr * params.fvg_min_width_atr_mult, tick * params.fvg_min_width_ticks)
    zones: list[dict[str, Any]] = []

    for i in range(2, len(candles)):
        c0, c1, c2 = candles[i - 2], candles[i - 1], candles[i]
        gap_up = _price(c2, "low_price") - _price(c0, "high_price")
        gap_down = _price(c0, "low_price") - _price(c2, "high_price")
        body = abs(_price(c1, "trade_price") - _price(c1, "opening_price"))
        range_size = max(_price(c1, "high_price") - _price(c1, "low_price"), 1e-8)
        displacement_ok = body / range_size >= params.displacement_min_body_ratio and range_size >= atr * params.displacement_min_atr_mult

        if gap_up >= min_width and displacement_ok:
            zones.append({"type": "fvg", "bias": "bullish", "lower": _price(c0, "high_price"), "upper": _price(c2, "low_price"), "created_index": i})
        if gap_down >= min_width and displacement_ok:
            zones.append({"type": "fvg", "bias": "bearish", "lower": _price(c2, "high_price"), "upper": _price(c0, "low_price"), "created_index": i})
    return zones


def detect_ob_zones(candles_newest: Sequence[dict[str, Any]], params: StrategyParams) -> list[dict[str, Any]]:
    candles = list(reversed(candles_newest))
    atr = _atr(candles_newest, params.fvg_atr_period)
    zones: list[dict[str, Any]] = []
    for i in range(1, len(candles)):
        cur = candles[i]
        cur_open = _price(cur, "opening_price")
        cur_close = _price(cur, "trade_price")
        cur_range = max(_price(cur, "high_price") - _price(cur, "low_price"), 1e-8)
        body_ratio = abs(cur_close - cur_open) / cur_range
        displacement = cur_range >= atr * params.displacement_min_atr_mult and body_ratio >= params.displacement_min_body_ratio
        if not displacement:
            continue

        if cur_close > cur_open:
            for lookback in range(1, min(params.ob_max_base_bars, i) + 1):
                base = candles[i - lookback]
                if _price(base, "trade_price") < _price(base, "opening_price"):
                    zones.append({"type": "ob", "bias": "bullish", "lower": _price(base, "low_price"), "upper": _price(base, "high_price"), "created_index": i})
                    break
        else:
            for lookback in range(1, min(params.ob_max_base_bars, i) + 1):
                base = candles[i - lookback]
                if _price(base, "trade_price") > _price(base, "opening_price"):
                    zones.append({"type": "ob", "bias": "bearish", "lower": _price(base, "low_price"), "upper": _price(base, "high_price"), "created_index": i})
                    break
    return zones


def filter_active_zones(zones: Sequence[dict[str, Any]], current_price: float, current_index: int, params: StrategyParams) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for zone in zones:
        age = current_index - int(zone["created_index"])
        if age > params.zone_expiry_bars_5m:
            continue

        buffer = zone["upper"] * params.zone_reentry_buffer_pct
        if zone["bias"] == "bullish" and current_price < zone["lower"] - buffer:
            continue
        if zone["bias"] == "bearish" and current_price > zone["upper"] + buffer:
            continue
        active.append(zone)
    return active


def _intersects(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return max(a["lower"], b["lower"]) <= min(a["upper"], b["upper"])


def pick_best_zone(sr_levels: Sequence[dict[str, Any]], setup_zones: Sequence[dict[str, Any]], side: str, params: StrategyParams) -> dict[str, Any] | None:
    target_bias = "support" if side == "buy" else "resistance"
    setup_bias = "bullish" if side == "buy" else "bearish"

    sr_side = [s for s in sr_levels if s["bias"] == target_bias]
    setup_side = [z for z in setup_zones if z["bias"] == setup_bias]

    best: dict[str, Any] | None = None
    best_score = -1
    for zone in setup_side:
        score = 1
        if zone["type"] == "ob":
            score += 1
        if zone["type"] == "fvg":
            score += 1
        for sr in sr_side:
            sr_band = {"lower": sr["lower"], "upper": sr["upper"]}
            if _intersects(zone, sr_band):
                score += 2 + float(sr.get("score", 0.0))
                break
        if score > best_score:
            best_score = score
            best = zone

    if params.zone_priority_mode == "intersection":
        return best
    return setup_side[0] if setup_side else None


def check_trigger_1m(candles_newest: Sequence[dict[str, Any]], zone: dict[str, Any], side: str, params: StrategyParams) -> bool:
    if len(candles_newest) < params.trigger_breakout_lookback + 2:
        return False

    latest = candles_newest[0]
    previous = candles_newest[1 : params.trigger_breakout_lookback + 1]
    latest_close = _price(latest, "trade_price")
    latest_open = _price(latest, "opening_price")
    latest_high = _price(latest, "high_price")
    latest_low = _price(latest, "low_price")
    range_size = max(latest_high - latest_low, 1e-8)

    if side == "buy":
        near_zone = zone["lower"] <= latest_low <= zone["upper"]
        breakout = latest_close > max(_price(c, "high_price") for c in previous)
        rejection = (min(latest_open, latest_close) - latest_low) / range_size >= params.trigger_rejection_wick_ratio
        return near_zone and breakout and rejection

    near_zone = zone["lower"] <= latest_high <= zone["upper"]
    breakout = latest_close < min(_price(c, "low_price") for c in previous)
    rejection = (latest_high - max(latest_open, latest_close)) / range_size >= params.trigger_rejection_wick_ratio
    return near_zone and breakout and rejection


def _normalize_timeframes(data: Any) -> dict[str, list[dict[str, Any]]] | None:
    if isinstance(data, dict):
        c1 = list(data.get("1m", []))
        c5 = list(data.get("5m", []))
        c15 = list(data.get("15m", []))
        return {"1m": c1, "5m": c5, "15m": c15}
    if isinstance(data, Sequence):
        if os.getenv("STRATEGY_ALLOW_SEQUENCE_FALLBACK_FOR_TESTS") != "1":
            return None
        warnings.warn(
            "Sequence timeframe fallback is test-only and disabled in production by default.",
            RuntimeWarning,
            stacklevel=2,
        )
        candles = list(data)
        return {"1m": candles, "5m": candles, "15m": candles}
    return None


def _check_entry(data: Any, params: StrategyParams, side: str, source_order: str = "newest") -> bool:
    tf = _normalize_timeframes(data)
    if tf is None:
        return False

    c1 = preprocess_candles(tf["1m"], source_order=source_order)
    c5 = preprocess_candles(tf["5m"], source_order=source_order)
    c15 = preprocess_candles(tf["15m"], source_order=source_order)

    if len(c1) < params.min_candles_1m or len(c5) < params.min_candles_5m or len(c15) < params.min_candles_15m:
        return False

    pivots = detect_sr_pivots(c15[: params.sr_lookback_bars], params.sr_pivot_left, params.sr_pivot_right)
    sr_levels = cluster_sr_levels(pivots, params.sr_cluster_band_pct, params.sr_min_touches)
    sr_levels = score_sr_levels(sr_levels, total_bars=len(c15[: params.sr_lookback_bars]), params=params)

    zones = detect_fvg_zones(c5[: params.ob_lookback_bars], params) + detect_ob_zones(c5[: params.ob_lookback_bars], params)
    current_price_5m = _price(c5[0], "trade_price")
    active = filter_active_zones(zones, current_price_5m, current_index=len(c5[: params.ob_lookback_bars]), params=params)
    selected = pick_best_zone(sr_levels, active, side=side, params=params)
    if selected is None:
        return False

    return check_trigger_1m(c1, selected, side=side, params=params)


def check_buy(data: Any, params: StrategyParams, source_order: str = "newest") -> bool:
    return _check_entry(data, params, side="buy", source_order=source_order)


def check_sell(data: Any, avg_buy_price: float, params: StrategyParams, source_order: str = "newest") -> bool:
    if not _check_entry(data, params, side="sell", source_order=source_order):
        return False
    tf = _normalize_timeframes(data)
    if tf is None or not tf["1m"]:
        return False
    candles = preprocess_candles(tf["1m"], source_order=source_order)
    current_price = _price(candles[0], "trade_price")
    return current_price >= avg_buy_price * params.sell_profit_threshold


def should_buy(data, config) -> bool:
    return check_buy(data, config.to_strategy_params())


def should_sell(data, avg_buy_price: float, config) -> bool:
    return check_sell(data, avg_buy_price, config.to_strategy_params())
