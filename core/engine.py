from __future__ import annotations

from datetime import datetime, timezone

from core.config import TradingConfig
from core.interfaces import Broker
from core.order_state import OrderRecord
from core.portfolio import normalize_accounts
from core.strategy import check_buy, check_sell, preprocess_candles
from infra.upbit_ws_client import UpbitWebSocketClient
from message.notifier import Notifier


class TradingEngine:
    def __init__(
        self,
        broker: Broker,
        notifier: Notifier,
        config: TradingConfig,
        ws_client: UpbitWebSocketClient | None = None,
    ):
        self.broker = broker
        self.notifier = notifier
        self.config = config
        self.ws_client = ws_client
        self._order_sequence = 0
        self.orders_by_identifier: dict[str, OrderRecord] = {}

    def start(self) -> None:
        if not self.ws_client:
            return

        self.initialize_markets()
        self.ws_client.connect()
        self.ws_client.subscribe("ticker", self.config.krw_markets, data_format=self.config.ws_data_format)

    def shutdown(self) -> None:
        if self.ws_client:
            self.ws_client.close()

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
                requested_volume = float(account["balance"])
                identifier = self._next_order_identifier(market, "ask")
                response = self.broker.sell_market(market, requested_volume, identifier=identifier)
                self._record_accepted_order(response, identifier, market, "ask", requested_volume)
                print("SELL_ACCEPTED", market, str(account["balance"]) + account["currency"], current_price)
                delta = ((current_price - avg_buy_price) / avg_buy_price) * 100
                self.notifier.send(f"SELL_ACCEPTED {market} {current_price} {delta}%")

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

            identifier = self._next_order_identifier(market, "bid")
            response = self.broker.buy_market(market, order_krw, identifier=identifier)
            self._record_accepted_order(response, identifier, market, "bid", order_krw)
            print("BUY_ACCEPTED", market, str(int(order_krw)) + "원", data[0]["trade_price"])
            self.notifier.send(f"BUY_ACCEPTED {market} {data[0]['trade_price']}")
            break

    def _next_order_identifier(self, market: str, side: str) -> str:
        self._order_sequence += 1
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        return f"{market}:{side}:{timestamp}:{self._order_sequence}"

    def _record_accepted_order(
        self,
        response,
        identifier: str,
        market: str,
        side: str,
        requested_qty: float,
    ) -> None:
        response_data = response if isinstance(response, dict) else {}
        order_uuid = response_data.get("uuid")
        self.orders_by_identifier[identifier] = OrderRecord.accepted(
            uuid=order_uuid,
            identifier=identifier,
            market=market,
            side=side,
            requested_qty=requested_qty,
        )
