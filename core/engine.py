from __future__ import annotations

from typing import Any, Protocol

from core.config import TradingConfig
from core.portfolio import normalize_accounts
from core.strategy import should_buy, should_sell


class TradeExecutor(Protocol):
    def get_markets(self) -> list[dict[str, Any]]:
        ...

    def get_accounts(self) -> list[dict[str, Any]]:
        ...

    def get_ticker(self, markets: str) -> list[dict[str, Any]]:
        ...

    def get_candles_minutes(self, market: str, interval: int, count: int = 200) -> list[dict[str, Any]]:
        ...

    def ask_market(self, market: str, volume: float) -> Any:
        ...

    def bid_price(self, market: str, price: float) -> Any:
        ...


class Notifier(Protocol):
    def send(self, message: str) -> None:
        ...


class TradingEngine:
    def __init__(self, executor: TradeExecutor, notifier: Notifier, config: TradingConfig):
        self.executor = executor
        self.notifier = notifier
        self.config = config

    def initialize_markets(self) -> None:
        if self.config.krw_markets:
            return

        markets = self.executor.get_markets()
        self.config.krw_markets = [
            item["market"]
            for item in markets
            if item["market"].startswith("KRW-")
            and not any(excluded in item["market"] for excluded in self.config.do_not_trading)
        ]

    def run_once(self) -> None:
        self.initialize_markets()

        accounts = self.executor.get_accounts()
        portfolio = normalize_accounts(accounts, self.config.do_not_trading)
        print("보유코인 :", portfolio.held_markets)

        for account in portfolio.my_coins:
            market = "KRW-" + account["currency"]
            data = self.executor.get_candles_minutes(market, interval=self.config.candle_interval)
            avg_buy_price = float(account["avg_buy_price"])
            current_price = float(data[0]["trade_price"])

            if should_sell(data, avg_buy_price, self.config) or current_price < avg_buy_price * self.config.stop_loss_threshold:
                self.executor.ask_market(market, account["balance"])
                print("SELL", market, str(account["balance"]) + account["currency"], current_price)
                delta = ((current_price - avg_buy_price) / avg_buy_price) * 100
                self.notifier.send(f"SELL {market} {current_price} {delta}%")

        self._try_buy(portfolio.available_krw, portfolio.held_markets)

    def _try_buy(self, available_krw: float, held_markets: list[str]) -> None:
        if available_krw <= self.config.min_buyable_krw:
            return
        if len(held_markets) >= self.config.max_holdings:
            return

        tickers = self.executor.get_ticker(", ".join(self.config.krw_markets))
        tickers.sort(key=lambda x: float(x["trade_volume"]), reverse=True)

        for ticker in tickers:
            market = ticker["market"]
            if market in held_markets:
                continue

            data = self.executor.get_candles_minutes(market, interval=self.config.candle_interval)
            if not should_buy(data, self.config):
                continue

            order_krw = (available_krw / self.config.buy_divisor) * (1 - self.config.fee_rate)
            if order_krw < self.config.min_order_krw:
                continue
            if available_krw - order_krw < self.config.min_order_krw:
                continue

            self.executor.bid_price(market, order_krw)
            print("BUY", market, str(int(order_krw)) + "원", data[0]["trade_price"])
            self.notifier.send(f"BUY {market} {data[0]['trade_price']}")
            break
