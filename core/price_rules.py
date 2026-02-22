from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def krw_tick_size(price: float) -> float:
    if price >= 2_000_000:
        return 1000.0
    if price >= 1_000_000:
        return 500.0
    if price >= 500_000:
        return 100.0
    if price >= 100_000:
        return 50.0
    if price >= 10_000:
        return 10.0
    if price >= 1_000:
        return 1.0
    if price >= 100:
        return 0.1
    if price >= 10:
        return 0.01
    if price >= 1:
        return 0.001
    if price >= 0.1:
        return 0.0001
    if price >= 0.01:
        return 0.00001
    if price >= 0.001:
        return 0.000001
    return 0.0000001


def round_down_to_tick(value: float, tick: float) -> float:
    return math.floor(value / tick) * tick


def min_krw_tick_from_candles(
    candles_newest: Sequence[Mapping[str, Any]],
    price_key: str = "trade_price",
    default_price: float = 1.0,
) -> float:
    min_price = min((float(c[price_key]) for c in candles_newest if price_key in c), default=default_price)
    return krw_tick_size(min_price)
