from __future__ import annotations

import apis


class UpbitBroker:
    def get_markets(self):
        return apis.get_markets()

    def get_accounts(self):
        return apis.get_accounts()

    def get_ticker(self, markets):
        return apis.get_ticker(markets)

    def get_candles(self, market, interval, count=200):
        return apis.get_candles_minutes(market, count=count, interval=interval)

    def buy_market(self, market, price):
        return apis.bid_price(market, price)

    def sell_market(self, market, volume):
        return apis.ask_market(market, volume)
