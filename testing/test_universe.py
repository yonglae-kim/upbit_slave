import unittest

from core.config import TradingConfig
from core.universe import (
    UniverseBuilder,
    collect_krw_markets,
    filter_by_missing_rate,
)


class UniverseRulesTest(unittest.TestCase):
    def test_collect_krw_markets_excludes_blocklist(self):
        markets = [
            {"market": "KRW-BTC"},
            {"market": "BTC-ETH"},
            {"market": "KRW-XRP"},
            {"market": "KRW-TSHP"},
        ]

        selected = collect_krw_markets(markets, excluded_keywords=["TSHP"])
        self.assertEqual(selected, ["KRW-BTC", "KRW-XRP"])

    def test_top_n_and_spread_filter(self):
        config = TradingConfig(
            do_not_trading=[],
            universe_top_n1=3,
            universe_watch_n2=2,
            max_relative_spread=0.002,
        )
        builder = UniverseBuilder(config)

        tickers = [
            {"market": "KRW-A", "acc_trade_price_24h": 5000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-B", "acc_trade_price_24h": 4000, "ask_price": 101.0, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-C", "acc_trade_price_24h": 3000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-D", "acc_trade_price_24h": 2000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
        ]

        selected = builder.select_watch_markets(tickers)
        self.assertEqual(selected, ["KRW-A", "KRW-C"])

    def test_missing_rate_filter(self):
        markets = ["KRW-A", "KRW-B", "KRW-C"]
        candles_by_market = {
            "KRW-A": [{"missing": False}] * 10,
            "KRW-B": [{"missing": False}] * 8 + [{"missing": True}] * 2,
            "KRW-C": [{"missing": True}] * 4,
        }

        selected = filter_by_missing_rate(markets, candles_by_market, max_missing_rate=0.2)
        self.assertEqual(selected, ["KRW-A", "KRW-B"])


if __name__ == "__main__":
    unittest.main()
