from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import strategy.strategy as st


@dataclass(frozen=True)
class StrategyParams:
    buy_rsi_threshold: int = 35
    macd_n_fast: int = 12
    macd_n_slow: int = 26
    macd_n_signal: int = 9
    min_candle_extra: int = 3
    sell_profit_threshold: float = 1.01
    stop_loss_threshold: float = 0.975


def preprocess_candles(data: Sequence[dict[str, Any]], source_order: str = "newest") -> list[dict[str, Any]]:
    candles = list(data)
    if source_order not in {"newest", "oldest"}:
        raise ValueError("source_order must be 'newest' or 'oldest'")
    if source_order == "oldest":
        candles.reverse()
    return candles


def has_minimum_candles(data: Sequence[dict[str, Any]], params: StrategyParams) -> bool:
    return len(data) >= params.macd_n_slow + params.macd_n_signal + params.min_candle_extra


def get_recent_triplet(series):
    if len(series) < 3:
        return None

    window = series.iloc[-3:]
    if window.isna().any():
        return None

    return window.iloc[0], window.iloc[1], window.iloc[2]


def is_buy_macd_pattern(macd_triplet) -> bool:
    old, mid, new = macd_triplet
    return old >= mid <= new


def is_sell_macd_diff_pattern(macd_diff_triplet) -> bool:
    old, _mid, new = macd_diff_triplet
    return old > new


def check_sell(data: Sequence[dict[str, Any]], avg_buy_price: float, params: StrategyParams, source_order: str = "newest") -> bool:
    candles = preprocess_candles(data, source_order=source_order)
    if not has_minimum_candles(candles, params):
        return False

    macd = st.macd(
        candles,
        n_fast=params.macd_n_fast,
        n_slow=params.macd_n_slow,
        n_signal=params.macd_n_signal,
    )
    macd_diff_triplet = get_recent_triplet(macd["MACDDiff"])
    if macd_diff_triplet is None:
        return False

    current_price = float(candles[0]["trade_price"])
    if avg_buy_price * params.sell_profit_threshold > current_price:
        return False

    return is_sell_macd_diff_pattern(macd_diff_triplet)


def check_buy(data: Sequence[dict[str, Any]], params: StrategyParams, source_order: str = "newest") -> bool:
    candles = preprocess_candles(data, source_order=source_order)
    if not has_minimum_candles(candles, params):
        return False

    rsi = st.rsi(candles)
    macd = st.macd(
        candles,
        n_fast=params.macd_n_fast,
        n_slow=params.macd_n_slow,
        n_signal=params.macd_n_signal,
    )
    macd_triplet = get_recent_triplet(macd["MACD"])
    macd_diff_triplet = get_recent_triplet(macd["MACDDiff"])
    if macd_triplet is None or macd_diff_triplet is None:
        return False

    if rsi > params.buy_rsi_threshold:
        return False
    if not is_buy_macd_pattern(macd_triplet):
        return False
    if macd_triplet[-1] > 0:
        return False

    return True


def should_buy(data, config) -> bool:
    return check_buy(data, config.to_strategy_params())


def should_sell(data, avg_buy_price: float, config) -> bool:
    return check_sell(data, avg_buy_price, config.to_strategy_params())
