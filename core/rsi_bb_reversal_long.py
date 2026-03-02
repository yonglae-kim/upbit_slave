from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReversalSignal:
    filter_pass: bool
    setup_pass: bool
    trigger_pass: bool
    final_pass: bool
    reason: str
    diagnostics: dict[str, Any]


def _price(candle: dict[str, Any], key: str, fallback: str = "trade_price") -> float:
    return float(candle.get(key, candle.get(fallback, 0.0)))


def _closes_oldest(candles_newest: list[dict[str, Any]]) -> list[float]:
    return [_price(c, "trade_price") for c in reversed(candles_newest)]


def calc_rsi_series(candles_newest: list[dict[str, Any]], period: int) -> list[float]:
    closes = _closes_oldest(candles_newest)
    if period <= 0 or len(closes) < period + 1:
        return [0.0] * len(closes)

    deltas = [0.0]
    for i in range(1, len(closes)):
        deltas.append(closes[i] - closes[i - 1])

    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period

    rsi = [0.0] * len(closes)
    for idx in range(period, len(closes)):
        if idx > period:
            avg_gain = ((avg_gain * (period - 1)) + gains[idx]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[idx]) / period
        if avg_loss == 0:
            rsi[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[idx] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _ema(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return [0.0] * len(values)
    alpha = 2.0 / (period + 1)
    out: list[float] = []
    cur = values[0]
    for value in values:
        cur = (value * alpha) + (cur * (1 - alpha))
        out.append(cur)
    return out


def calc_macd_series(candles_newest: list[dict[str, Any]], fast: int, slow: int, signal: int) -> tuple[list[float], list[float], list[float]]:
    closes = _closes_oldest(candles_newest)
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def calc_bollinger_series(candles_newest: list[dict[str, Any]], period: int, std_mult: float) -> tuple[list[float], list[float], list[float]]:
    closes = _closes_oldest(candles_newest)
    n = len(closes)
    mid = [0.0] * n
    up = [0.0] * n
    low = [0.0] * n
    if period <= 0:
        return mid, up, low
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = sum(window) / period
        variance = sum((v - m) ** 2 for v in window) / period
        std = variance ** 0.5
        mid[i] = m
        up[i] = m + (std_mult * std)
        low[i] = m - (std_mult * std)
    return mid, up, low


def detect_pivot_lows(candles_newest: list[dict[str, Any]], left: int, right: int, upto_index: int | None = None) -> list[int]:
    """Return pivot-low indices in oldest-order indexing.

    Pivot i is confirmed only when i + right <= upto_index, which prevents lookahead bias.
    """
    candles = list(reversed(candles_newest))
    if not candles:
        return []
    if upto_index is None:
        upto_index = len(candles) - 1
    pivots: list[int] = []
    for i in range(left, upto_index - right + 1):
        cur_low = _price(candles[i], "low_price")
        left_slice = candles[i - left : i]
        right_slice = candles[i + 1 : i + 1 + right]
        if all(cur_low <= _price(c, "low_price") for c in left_slice + right_slice):
            pivots.append(i)
    return pivots


def is_bullish_engulfing(candles_newest: list[dict[str, Any]], idx_oldest: int, strict: bool = True, include_wick: bool = False) -> bool:
    candles = list(reversed(candles_newest))
    if idx_oldest <= 0 or idx_oldest >= len(candles):
        return False
    prev_candle = candles[idx_oldest - 1]
    cur_candle = candles[idx_oldest]
    prev_open, prev_close = _price(prev_candle, "opening_price"), _price(prev_candle, "trade_price")
    cur_open, cur_close = _price(cur_candle, "opening_price"), _price(cur_candle, "trade_price")

    if not (prev_close < prev_open and cur_close > cur_open):
        return False

    prev_low_body, prev_high_body = min(prev_open, prev_close), max(prev_open, prev_close)
    cur_low_body, cur_high_body = min(cur_open, cur_close), max(cur_open, cur_close)

    if include_wick:
        prev_low = _price(prev_candle, "low_price")
        prev_high = _price(prev_candle, "high_price")
        return cur_low_body <= prev_low and cur_high_body >= prev_high

    if strict:
        return cur_low_body <= prev_low_body and cur_high_body >= prev_high_body
    return cur_low_body < prev_high_body and cur_high_body > prev_low_body


def match_bb_touch_mode(candle: dict[str, Any], lower_band: float, mode: str) -> bool:
    touch = _price(candle, "low_price") <= lower_band
    brk = _price(candle, "trade_price") < lower_band
    if mode == "touch_only":
        return touch
    if mode == "break_only":
        return brk
    return touch or brk


def has_consecutive_bearish(candles_newest: list[dict[str, Any]], idx_oldest: int, count: int) -> bool:
    candles = list(reversed(candles_newest))
    if idx_oldest - count < 0:
        return False
    for i in range(idx_oldest - count, idx_oldest):
        if _price(candles[i], "trade_price") >= _price(candles[i], "opening_price"):
            return False
    return True


def detect_double_bottom(
    candles_newest: list[dict[str, Any]],
    pivot_lows: list[int],
    lower_band: list[float],
    lookback_bars: int,
    tolerance_pct: float,
    require_band_reentry: bool,
    require_neckline_break: bool,
    eval_idx: int,
) -> dict[str, Any]:
    recent = [p for p in pivot_lows if eval_idx - p <= lookback_bars]
    if len(recent) < 2:
        return {"pass": False, "reason": "insufficient_pivots"}
    p1, p2 = recent[-2], recent[-1]
    candles = list(reversed(candles_newest))
    low1 = _price(candles[p1], "low_price")
    low2 = _price(candles[p2], "low_price")
    gap_pct = (abs(low1 - low2) / max(min(low1, low2), 1e-9)) * 100.0
    if gap_pct > tolerance_pct:
        return {"pass": False, "reason": "tolerance_fail", "p1": p1, "p2": p2, "gap_pct": gap_pct}

    if require_band_reentry and not match_bb_touch_mode(candles[p2], lower_band[p2], "touch_or_break"):
        return {"pass": False, "reason": "band_reentry_fail", "p1": p1, "p2": p2}

    neckline = max(_price(c, "high_price") for c in candles[p1 : p2 + 1])
    if require_neckline_break and _price(candles[eval_idx], "trade_price") <= neckline:
        return {"pass": False, "reason": "neckline_fail", "p1": p1, "p2": p2, "neckline": neckline}

    return {"pass": True, "reason": "ok", "p1": p1, "p2": p2, "low1": low1, "low2": low2, "neckline": neckline}


def is_bullish_rsi_divergence(pivot_lows: list[int], candles_newest: list[dict[str, Any]], rsi_series: list[float], eval_idx: int) -> dict[str, Any]:
    recent = [p for p in pivot_lows if p <= eval_idx]
    if len(recent) < 2:
        return {"pass": False, "reason": "insufficient_pivots"}
    p1, p2 = recent[-2], recent[-1]
    candles = list(reversed(candles_newest))
    low1 = _price(candles[p1], "low_price")
    low2 = _price(candles[p2], "low_price")
    rsi1 = rsi_series[p1]
    rsi2 = rsi_series[p2]
    passed = low2 < low1 and rsi2 > rsi1
    return {"pass": passed, "reason": "ok" if passed else "rule_fail", "p1": p1, "p2": p2, "low1": low1, "low2": low2, "rsi1": rsi1, "rsi2": rsi2}


def is_macd_bullish_cross(macd_line: list[float], signal_line: list[float], hist: list[float], idx: int, histogram_filter: bool) -> bool:
    if idx <= 0 or idx >= len(macd_line) or idx >= len(signal_line):
        return False
    crossed = macd_line[idx - 1] <= signal_line[idx - 1] and macd_line[idx] > signal_line[idx]
    if not crossed:
        return False
    if histogram_filter and idx >= 2:
        return hist[idx] > hist[idx - 1]
    return True


def _compute_stop_price(candles_oldest: list[dict[str, Any]], lower_band: list[float], idx: int, stop_mode: str) -> float:
    swing_low = min(_price(c, "low_price") for c in candles_oldest[max(0, idx - 5) : idx + 1])
    lb = lower_band[idx]
    if stop_mode == "lower_band":
        return lb
    if stop_mode == "conservative":
        return min(lb, swing_low)
    return swing_low


def _compute_stop_context(candles_oldest: list[dict[str, Any]], lower_band: list[float], idx: int, stop_mode: str) -> dict[str, float | str]:
    swing_low = min(_price(c, "low_price") for c in candles_oldest[max(0, idx - 5) : idx + 1])
    lb = lower_band[idx]
    if stop_mode == "lower_band":
        stop_price = lb
    elif stop_mode == "conservative":
        stop_price = min(lb, swing_low)
    else:
        stop_price = swing_low
    return {
        "stop_price": float(stop_price),
        "stop_mode_long": str(stop_mode),
        "entry_swing_low": float(swing_low),
        "entry_lower_band": float(lb),
    }


def _regime_alignment_score(candles_15m_newest: list[dict[str, Any]]) -> float:
    candles = list(reversed(candles_15m_newest))
    if len(candles) < 30:
        return 0.5

    closes = [_price(c, "trade_price") for c in candles]
    fast = _ema(closes, 20)
    slow = _ema(closes, 50)
    if len(fast) < 4 or len(slow) < 4:
        return 0.5

    trend_up = fast[-1] > slow[-1]
    slope_up = fast[-1] > fast[-4]
    if trend_up and slope_up:
        return 1.0
    if trend_up or slope_up:
        return 0.6
    return 0.2


def evaluate_long_entry(data: dict[str, list[dict[str, Any]]], params: Any) -> ReversalSignal:
    candles_newest = list(data.get("1m", []))
    candles_oldest = list(reversed(candles_newest))
    n = len(candles_oldest)
    warmup = max(params.bb_period + 2, params.rsi_period + 2, params.macd_slow + params.macd_signal + 2, params.pivot_left + params.pivot_right + 2)
    if n < warmup:
        return ReversalSignal(False, False, False, False, "insufficient_candles", {"warmup": warmup, "len": n})

    eval_idx = n - 1
    if params.entry_mode == "next_open":
        eval_idx = n - 2
        if eval_idx <= 1:
            return ReversalSignal(False, False, False, False, "insufficient_next_open_candles", {})

    rsi_series = calc_rsi_series(candles_newest, params.rsi_period)
    _bb_mid, _bb_up, bb_low = calc_bollinger_series(candles_newest, params.bb_period, params.bb_std)
    macd_line, signal_line, hist = calc_macd_series(candles_newest, params.macd_fast, params.macd_slow, params.macd_signal)
    pivots = detect_pivot_lows(candles_newest, params.pivot_left, params.pivot_right, upto_index=eval_idx)

    rsi_value = rsi_series[eval_idx]
    neutral_block = params.rsi_neutral_filter_enabled and params.rsi_neutral_low <= rsi_value <= params.rsi_neutral_high
    raw_rsi_oversold_strength = 0.0
    if rsi_value <= params.rsi_long_threshold and params.rsi_long_threshold > 0:
        raw_rsi_oversold_strength = min(1.0, (params.rsi_long_threshold - rsi_value) / params.rsi_long_threshold)
    rsi_oversold_strength = 0.0 if neutral_block else raw_rsi_oversold_strength
    filter_pass = rsi_oversold_strength > 0.0

    bb_event = match_bb_touch_mode(candles_oldest[eval_idx], bb_low[eval_idx], params.bb_touch_mode)
    bearish_ok = has_consecutive_bearish(candles_newest, eval_idx, params.consecutive_bearish_count)
    db = detect_double_bottom(
        candles_newest,
        pivots,
        bb_low,
        params.double_bottom_lookback_bars,
        params.double_bottom_tolerance_pct,
        params.require_band_reentry_on_second_bottom,
        params.require_neckline_break,
        eval_idx,
    )
    bb_width = max(_bb_up[eval_idx] - bb_low[eval_idx], 1e-9)
    bb_touch_depth = max(0.0, bb_low[eval_idx] - _price(candles_oldest[eval_idx], "low_price"))
    bb_touch_strength = min(1.0, bb_touch_depth / bb_width)
    if bb_event:
        bb_touch_strength = max(bb_touch_strength, 0.5)

    recent_window = candles_oldest[max(0, eval_idx - 20) : eval_idx + 1]
    recent_ranges = [_price(c, "high_price") - _price(c, "low_price") for c in recent_window]
    avg_recent_range = (sum(recent_ranges) / len(recent_ranges)) if recent_ranges else 0.0
    band_breakout_strength = 0.0
    if avg_recent_range > 0:
        band_breakout_strength = min(1.0, bb_touch_depth / avg_recent_range)

    setup_pass = bb_event and bearish_ok and bool(db.get("pass", False))

    engulfing = is_bullish_engulfing(candles_newest, eval_idx, strict=params.engulfing_strict, include_wick=params.engulfing_include_wick)
    trigger_pass = engulfing

    div = is_bullish_rsi_divergence(pivots, candles_newest, rsi_series, eval_idx)
    macd_cross = is_macd_bullish_cross(macd_line, signal_line, hist, eval_idx, params.macd_histogram_filter_enabled)
    special_setup = params.divergence_signal_enabled and div.get("pass", False) and macd_cross and engulfing

    divergence_strength = 0.0
    if int(div.get("p1", -1)) >= 0 and int(div.get("p2", -1)) >= 0:
        price_drop = max(float(div.get("low1", 0.0)) - float(div.get("low2", 0.0)), 0.0)
        rsi_rise = max(float(div.get("rsi2", 0.0)) - float(div.get("rsi1", 0.0)), 0.0)
        norm_price_drop = price_drop / max(float(div.get("low1", 1e-9)), 1e-9)
        norm_rsi_rise = rsi_rise / 100.0
        divergence_strength = min(1.0, (norm_price_drop * 12.0) + (norm_rsi_rise * 3.0))

    regime_alignment = _regime_alignment_score(list(data.get("15m", [])))
    quality_score = max(0.0, min(1.0, (divergence_strength * 0.4) + (band_breakout_strength * 0.35) + (regime_alignment * 0.25)))

    entry_score = (
        (float(params.rsi_oversold_weight) * rsi_oversold_strength)
        + (float(params.bb_touch_weight) * bb_touch_strength)
        + (float(params.divergence_weight) * (1.0 if div.get("pass", False) else 0.0))
        + (float(params.macd_cross_weight) * (1.0 if macd_cross else 0.0))
        + (float(params.engulfing_weight) * (1.0 if engulfing else 0.0))
        + (float(params.band_deviation_weight) * band_breakout_strength)
    )

    entry_price = _price(candles_oldest[n - 1 if params.entry_mode == "next_open" else eval_idx], "trade_price")
    stop_context = _compute_stop_context(candles_oldest, bb_low, eval_idx, params.stop_mode_long)
    stop_price = float(stop_context["stop_price"])
    risk = max(entry_price - stop_price, 1e-9)
    tp_price = entry_price + (risk * params.take_profit_r)
    stop_valid = stop_price < entry_price
    risk_valid = risk > 1e-9
    safety_pass = stop_valid and risk_valid
    score_pass = entry_score >= float(params.entry_score_threshold)

    final_pass = filter_pass and setup_pass and trigger_pass and safety_pass and score_pass

    diag = {
        "state": {"filter": filter_pass, "setup": setup_pass, "trigger": trigger_pass, "special": special_setup, "safety": safety_pass},
        "symbol": str(data.get("symbol", "UNKNOWN")),
        "rsi": rsi_value,
        "bb_lower": bb_low[eval_idx],
        "bb_width": bb_width,
        "score_threshold": float(params.entry_score_threshold),
        "entry_score": float(entry_score),
        "score_components": {
            "rsi_oversold": float(rsi_oversold_strength),
            "bb_touch": float(bb_touch_strength),
            "divergence": 1.0 if div.get("pass", False) else 0.0,
            "macd_cross": 1.0 if macd_cross else 0.0,
            "engulfing": 1.0 if engulfing else 0.0,
            "band_deviation": float(band_breakout_strength),
        },
        "quality_score": float(quality_score),
        "quality_components": {
            "divergence_strength": float(divergence_strength),
            "band_breakout_strength": float(band_breakout_strength),
            "regime_alignment": float(regime_alignment),
        },
        "score_weights": {
            "rsi_oversold_weight": float(params.rsi_oversold_weight),
            "bb_touch_weight": float(params.bb_touch_weight),
            "divergence_weight": float(params.divergence_weight),
            "macd_cross_weight": float(params.macd_cross_weight),
            "engulfing_weight": float(params.engulfing_weight),
            "band_deviation_weight": float(params.band_deviation_weight),
        },
        "bb_event": bb_event,
        "engulfing": engulfing,
        "double_bottom": db,
        "divergence": div,
        "macd_cross": macd_cross,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "stop_mode_long": str(stop_context["stop_mode_long"]),
        "entry_swing_low": float(stop_context["entry_swing_low"]),
        "entry_lower_band": float(stop_context["entry_lower_band"]),
        "tp_price": tp_price,
        "r_value": risk,
        "stop_valid": stop_valid,
        "risk_valid": risk_valid,
    }
    if final_pass:
        reason = "ok"
    elif not filter_pass:
        reason = "filter_fail"
    elif not setup_pass or not trigger_pass:
        reason = "trigger_fail"
    elif not safety_pass:
        reason = "safety_fail"
    else:
        reason = "score_below_threshold"
    return ReversalSignal(filter_pass, setup_pass, trigger_pass, final_pass, reason, diag)


def should_exit_long(
    data: dict[str, list[dict[str, Any]]],
    params: Any,
    *,
    entry_price: float,
    initial_stop_price: float,
    risk_per_unit: float,
) -> bool:
    candles = list(data.get("1m", []))
    if not candles or entry_price <= 0:
        return False

    # Policy-assist signal only: derive R-distance from entry-time risk snapshot
    # instead of using a percent proxy on current avg price.
    resolved_risk = max(float(risk_per_unit), 0.0)
    if resolved_risk <= 0 and initial_stop_price > 0:
        resolved_risk = max(float(entry_price) - float(initial_stop_price), 0.0)
    if resolved_risk <= 0:
        return False

    close_now = _price(candles[0], "trade_price")
    return close_now >= float(entry_price) + resolved_risk


def compute_stop_price_for_test(candles_newest: list[dict[str, Any]], lower_band: list[float], idx_oldest: int, mode: str) -> float:
    return _compute_stop_price(list(reversed(candles_newest)), lower_band, idx_oldest, mode)
