from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

import strategy.strategy as st

if TYPE_CHECKING:
    from core.config import TradingConfig


def has_minimum_candles(data: Sequence[dict[str, Any]], config: "TradingConfig") -> bool:
    return len(data) >= config.macd_n_slow + config.macd_n_signal + config.min_candle_extra


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


def should_sell(data: Sequence[dict[str, Any]], avg_buy_price: float, config: "TradingConfig") -> bool:
    if not has_minimum_candles(data, config):
        return False

    macd = st.macd(
        data,
        n_fast=config.macd_n_fast,
        n_slow=config.macd_n_slow,
        n_signal=config.macd_n_signal,
    )
    macd_diff_triplet = get_recent_triplet(macd["MACDDiff"])
    if macd_diff_triplet is None:
        return False

    current_price = float(data[0]["trade_price"])
    if avg_buy_price * config.sell_profit_threshold > current_price:
        return False

    return is_sell_macd_diff_pattern(macd_diff_triplet)


def should_buy(data: Sequence[dict[str, Any]], config: "TradingConfig") -> bool:
    if not has_minimum_candles(data, config):
        return False

    rsi = st.rsi(data)
    macd = st.macd(
        data,
        n_fast=config.macd_n_fast,
        n_slow=config.macd_n_slow,
        n_signal=config.macd_n_signal,
    )
    macd_triplet = get_recent_triplet(macd["MACD"])
    macd_diff_triplet = get_recent_triplet(macd["MACDDiff"])
    if macd_triplet is None or macd_diff_triplet is None:
        return False

    if rsi > config.buy_rsi_threshold:
        return False
    if not is_buy_macd_pattern(macd_triplet):
        return False
    if macd_triplet[-1] > 0:
        return False

    return True
