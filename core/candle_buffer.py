from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Callable


class CandleBuffer:
    def __init__(self, maxlen_by_interval: dict[int, int] | None = None):
        self.maxlen_by_interval = maxlen_by_interval or {1: 300, 5: 300, 15: 300}
        self._buffers: dict[str, dict[int, deque[dict[str, Any]]]] = defaultdict(dict)

    def get_candles(
        self,
        market: str,
        interval: int,
        fetcher: Callable[[str, int], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        candles = fetcher(market, interval)
        self.update(market, interval, candles)
        return self.snapshot(market, interval)

    def update(self, market: str, interval: int, candles: list[dict[str, Any]]) -> None:
        if interval not in self.maxlen_by_interval:
            raise ValueError(f"Unsupported interval: {interval}")

        buffer = self._buffers[market].get(interval)
        if buffer is None:
            buffer = deque(maxlen=self.maxlen_by_interval[interval])
            self._buffers[market][interval] = buffer

        normalized = self._normalize_to_oldest(candles)
        for candle in normalized:
            self._append_with_alignment(buffer, interval, candle)

    def snapshot(self, market: str, interval: int) -> list[dict[str, Any]]:
        buffer = self._buffers.get(market, {}).get(interval)
        if buffer is None:
            return []
        return [deepcopy(candle) for candle in reversed(buffer)]

    def _normalize_to_oldest(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candles:
            return []

        with_timestamp = [c for c in candles if self._parse_candle_time(c) is not None]
        if len(with_timestamp) == len(candles):
            return sorted(candles, key=lambda c: self._parse_candle_time(c))

        return list(reversed(candles))

    def _append_with_alignment(self, buffer: deque[dict[str, Any]], interval: int, candle: dict[str, Any]) -> None:
        candle = deepcopy(candle)
        candle.setdefault("missing", False)

        if not buffer:
            buffer.append(candle)
            return

        expected_delta = timedelta(minutes=interval)
        previous = buffer[-1]
        prev_time = self._parse_candle_time(previous)
        current_time = self._parse_candle_time(candle)

        if prev_time is not None and current_time is not None:
            gap = current_time - prev_time
            while gap > expected_delta:
                filler_time = prev_time + expected_delta
                filler = self._build_missing_candle(previous, filler_time)
                buffer.append(filler)
                previous = filler
                prev_time = filler_time
                gap = current_time - prev_time

        buffer.append(candle)

    def _build_missing_candle(self, prev: dict[str, Any], at_time: datetime) -> dict[str, Any]:
        close_price = float(prev.get("trade_price", prev.get("close", 0.0)))
        return {
            "candle_date_time_utc": at_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "trade_price": close_price,
            "opening_price": close_price,
            "high_price": close_price,
            "low_price": close_price,
            "candle_acc_trade_volume": 0.0,
            "missing": True,
        }

    def _parse_candle_time(self, candle: dict[str, Any]) -> datetime | None:
        raw = candle.get("candle_date_time_utc") or candle.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return datetime.utcfromtimestamp(float(raw) / 1000.0)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        return None
