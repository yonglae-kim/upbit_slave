from __future__ import annotations

from core.config import TradingConfig
from core.interfaces import Broker
from message.notifier import Notifier
from core.portfolio import normalize_accounts
from core.strategy import check_buy, check_sell, preprocess_candles


class TradingEngine:
    def __init__(self, broker: Broker, notifier: Notifier, config: TradingConfig):
        self.broker = broker
        self.notifier = notifier
        self.config = config

    def initialize_markets(self) -> None:
        if self.config.krw_markets:
            return

        markets = self.broker.get_markets()
        self.config.krw_markets = [
            item["market"]
            for item in markets
            if item["market"].startswith("KRW-")
            and not any(excluded in item["market"] for excluded in self.config.do_not_trading)
        ]

    def run_once(self) -> None:
        self.initialize_markets()
        strategy_params = self.config.to_strategy_params()

        accounts = self.broker.get_accounts()
        portfolio = normalize_accounts(accounts, self.config.do_not_trading)
        print("보유코인 :", portfolio.held_markets)

        for account in portfolio.my_coins:
            market = "KRW-" + account["currency"]
            data = preprocess_candles(
                self.broker.get_candles(market, interval=self.config.candle_interval),
                source_order="newest",
            )
            avg_buy_price = float(account["avg_buy_price"])
            current_price = float(data[0]["trade_price"])

            if check_sell(data, avg_buy_price, strategy_params) or current_price < avg_buy_price * strategy_params.stop_loss_threshold:
                self.broker.sell_market(market, account["balance"])
                print("SELL", market, str(account["balance"]) + account["currency"], current_price)
                delta = ((current_price - avg_buy_price) / avg_buy_price) * 100
                self.notifier.send(f"SELL {market} {current_price} {delta}%")

        self._try_buy(portfolio.available_krw, portfolio.held_markets, strategy_params)

    def _try_buy(self, available_krw: float, held_markets: list[str], strategy_params) -> None:
        if available_krw <= self.config.min_buyable_krw:
            return
        if len(held_markets) >= self.config.max_holdings:
            return

        tickers = self.broker.get_ticker(", ".join(self.config.krw_markets))
        tickers.sort(key=lambda x: float(x["trade_volume"]), reverse=True)

        for ticker in tickers:
            market = ticker["market"]
            if market in held_markets:
                continue

            data = preprocess_candles(
                self.broker.get_candles(market, interval=self.config.candle_interval),
                source_order="newest",
            )
            if not check_buy(data, strategy_params):
                continue

            order_krw = (available_krw / self.config.buy_divisor) * (1 - self.config.fee_rate)
            if order_krw < self.config.min_order_krw:
                continue
            if available_krw - order_krw < self.config.min_order_krw:
                continue

            self.broker.buy_market(market, order_krw)
            print("BUY", market, str(int(order_krw)) + "원", data[0]["trade_price"])
            self.notifier.send(f"BUY {market} {data[0]['trade_price']}")
            break
