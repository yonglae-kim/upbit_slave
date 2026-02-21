from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from core.config import TradingConfig


@dataclass
class UniverseBuilder:
    config: TradingConfig

    def collect_krw_markets(self, markets: Iterable[dict[str, Any]]) -> list[str]:
        return collect_krw_markets(markets, self.config.do_not_trading)

    def select_watch_markets(self, tickers: Iterable[dict[str, Any]]) -> list[str]:
        candidates = [ticker for ticker in tickers if ticker.get("market")]
        candidates = filter_by_relative_spread(candidates, self.config.max_relative_spread)
        candidates = select_top_by_trading_value(candidates, self.config.universe_top_n1)
        return limit_watch_markets(candidates, self.config.universe_watch_n2)


def collect_krw_markets(markets: Iterable[dict[str, Any]], excluded_keywords: list[str]) -> list[str]:
    krw_markets = []
    for item in markets:
        market = str(item.get("market", ""))
        if not market.startswith("KRW-"):
            continue
        if any(excluded in market for excluded in excluded_keywords):
            continue
        krw_markets.append(market)
    return krw_markets


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def select_top_by_trading_value(tickers: Iterable[dict[str, Any]], top_n1: int) -> list[dict[str, Any]]:
    if top_n1 <= 0:
        return []

    ranked = sorted(
        tickers,
        key=lambda ticker: _to_float(
            ticker.get("acc_trade_price_24h", ticker.get("acc_trade_price", ticker.get("trade_volume", 0.0)))
        ),
        reverse=True,
    )
    return ranked[:top_n1]


def limit_watch_markets(selected_tickers: Iterable[dict[str, Any]], watch_n2: int) -> list[str]:
    if watch_n2 <= 0:
        return []

    return [ticker["market"] for ticker in selected_tickers][:watch_n2]


def filter_by_relative_spread(tickers: Iterable[dict[str, Any]], max_relative_spread: float) -> list[dict[str, Any]]:
    if max_relative_spread <= 0:
        return list(tickers)

    filtered = []
    for ticker in tickers:
        ask = _to_float(ticker.get("ask_price"))
        bid = _to_float(ticker.get("bid_price"))
        last = _to_float(ticker.get("trade_price", ticker.get("last", 0.0)))

        if ask <= 0 or bid <= 0 or last <= 0:
            filtered.append(ticker)
            continue

        spread = (ask - bid) / last
        if spread <= max_relative_spread:
            filtered.append(ticker)
    return filtered


def filter_by_missing_rate(
    markets: Iterable[str],
    candles_by_market: dict[str, list[dict[str, Any]]],
    max_missing_rate: float,
) -> list[str]:
    if max_missing_rate < 0:
        return list(markets)

    selected = []
    for market in markets:
        candles = candles_by_market.get(market, [])
        if not candles:
            continue

        missing_count = sum(1 for candle in candles if bool(candle.get("missing")))
        missing_rate = missing_count / len(candles)
        if missing_rate <= max_missing_rate:
            selected.append(market)
    return selected
