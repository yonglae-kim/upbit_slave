from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from core.config import TradingConfig


@dataclass
class UniverseDropReason:
    market: str
    stage: str
    reason: str
    value: float | None = None
    threshold: float | int | None = None


@dataclass
class UniverseSelectionResult:
    watch_markets: list[str]
    drop_reasons: list[UniverseDropReason] = field(default_factory=list)
    total_candidates: int = 0


@dataclass
class UniverseBuilder:
    config: TradingConfig

    def collect_krw_markets(self, markets: Iterable[dict[str, Any]]) -> list[str]:
        return collect_krw_markets(markets, self.config.do_not_trading)

    def select_watch_markets(self, tickers: Iterable[dict[str, Any]]) -> list[str]:
        result = self.select_watch_markets_with_report(tickers)
        return result.watch_markets

    def select_watch_markets_with_report(
        self,
        tickers: Iterable[dict[str, Any]],
        candles_by_market: dict[str, list[dict[str, Any]]] | None = None,
    ) -> UniverseSelectionResult:
        candidates = [ticker for ticker in tickers if ticker.get("market")]
        drop_reasons: list[UniverseDropReason] = []

        top_selected, top_drops = select_top_by_trading_value_with_drops(candidates, self.config.universe_top_n1)
        drop_reasons.extend(top_drops)

        spread_selected, spread_drops = filter_by_relative_spread_with_drops(top_selected, self.config.max_relative_spread)
        drop_reasons.extend(spread_drops)

        current_markets = [ticker["market"] for ticker in spread_selected]
        if candles_by_market is not None:
            missing_selected, missing_drops = filter_by_missing_rate_with_drops(
                current_markets,
                candles_by_market,
                self.config.max_candle_missing_rate,
            )
            drop_reasons.extend(missing_drops)
            spread_selected = [ticker for ticker in spread_selected if ticker["market"] in missing_selected]

        final_tickers, cap_drops = limit_watch_tickers_with_drops(spread_selected, self.config.low_spec_watch_cap_n2)
        drop_reasons.extend(cap_drops)

        return UniverseSelectionResult(
            watch_markets=[ticker["market"] for ticker in final_tickers],
            drop_reasons=drop_reasons,
            total_candidates=len(candidates),
        )


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
    selected, _drops = select_top_by_trading_value_with_drops(tickers, top_n1)
    return selected


def select_top_by_trading_value_with_drops(
    tickers: Iterable[dict[str, Any]], top_n1: int
) -> tuple[list[dict[str, Any]], list[UniverseDropReason]]:
    if top_n1 <= 0:
        return [], [
            UniverseDropReason(
                market=str(ticker.get("market", "")),
                stage="top_n1",
                reason="top_n1_disabled",
                threshold=top_n1,
            )
            for ticker in tickers
            if ticker.get("market")
        ]

    ranked = sorted(
        tickers,
        key=lambda ticker: _to_float(
            ticker.get("acc_trade_price_24h", ticker.get("acc_trade_price", ticker.get("trade_volume", 0.0)))
        ),
        reverse=True,
    )
    selected = ranked[:top_n1]
    dropped = [
        UniverseDropReason(
            market=ticker["market"],
            stage="top_n1",
            reason="outside_top_n1_24h_trading_value",
            value=_to_float(
                ticker.get("acc_trade_price_24h", ticker.get("acc_trade_price", ticker.get("trade_volume", 0.0)))
            ),
            threshold=top_n1,
        )
        for ticker in ranked[top_n1:]
        if ticker.get("market")
    ]
    return selected, dropped


def limit_watch_markets(selected_tickers: Iterable[dict[str, Any]], watch_n2: int) -> list[str]:
    if watch_n2 <= 0:
        return []

    return [ticker["market"] for ticker in selected_tickers][:watch_n2]


def limit_watch_tickers_with_drops(
    selected_tickers: Iterable[dict[str, Any]],
    watch_n2: int,
) -> tuple[list[dict[str, Any]], list[UniverseDropReason]]:
    if watch_n2 <= 0:
        drops = [
            UniverseDropReason(
                market=ticker["market"],
                stage="watch_n2",
                reason="low_spec_cap_disabled",
                threshold=watch_n2,
            )
            for ticker in selected_tickers
            if ticker.get("market")
        ]
        return [], drops

    selected_list = list(selected_tickers)
    selected = selected_list[:watch_n2]
    dropped = [
        UniverseDropReason(
            market=ticker["market"],
            stage="watch_n2",
            reason="over_low_spec_cap_n2",
            threshold=watch_n2,
        )
        for ticker in selected_list[watch_n2:]
        if ticker.get("market")
    ]
    return selected, dropped


def filter_by_relative_spread(tickers: Iterable[dict[str, Any]], max_relative_spread: float) -> list[dict[str, Any]]:
    filtered, _drops = filter_by_relative_spread_with_drops(tickers, max_relative_spread)
    return filtered


def filter_by_relative_spread_with_drops(
    tickers: Iterable[dict[str, Any]],
    max_relative_spread: float,
) -> tuple[list[dict[str, Any]], list[UniverseDropReason]]:
    if max_relative_spread <= 0:
        return list(tickers), []

    filtered = []
    drops = []
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
            continue

        market = ticker.get("market")
        if market:
            drops.append(
                UniverseDropReason(
                    market=str(market),
                    stage="relative_spread",
                    reason="relative_spread_exceeded",
                    value=spread,
                    threshold=max_relative_spread,
                )
            )
    return filtered, drops


def filter_by_missing_rate(
    markets: Iterable[str],
    candles_by_market: dict[str, list[dict[str, Any]]],
    max_missing_rate: float,
) -> list[str]:
    selected, _drops = filter_by_missing_rate_with_drops(markets, candles_by_market, max_missing_rate)
    return selected


def filter_by_missing_rate_with_drops(
    markets: Iterable[str],
    candles_by_market: dict[str, list[dict[str, Any]]],
    max_missing_rate: float,
) -> tuple[list[str], list[UniverseDropReason]]:
    if max_missing_rate < 0:
        return list(markets), []

    selected = []
    drops = []
    for market in markets:
        candles = candles_by_market.get(market, [])
        if not candles:
            drops.append(
                UniverseDropReason(
                    market=market,
                    stage="missing_rate",
                    reason="missing_candle_data",
                )
            )
            continue

        missing_count = sum(1 for candle in candles if bool(candle.get("missing")))
        missing_rate = missing_count / len(candles)
        if missing_rate <= max_missing_rate:
            selected.append(market)
            continue

        drops.append(
            UniverseDropReason(
                market=market,
                stage="missing_rate",
                reason="missing_rate_exceeded",
                value=missing_rate,
                threshold=max_missing_rate,
            )
        )
    return selected, drops
