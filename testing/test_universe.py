import unittest

from core.config import TradingConfig
from core.universe import (
    UniverseBuilder,
    collect_krw_markets,
    filter_by_missing_rate,
    is_market_excluded,
    select_top_by_trading_value_with_drops,
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

    def test_collect_krw_markets_uses_exact_match_only(self):
        markets = [
            {"market": "KRW-ETH"},
            {"market": "KRW-ETHW"},
            {"market": "KRW-CETH"},
        ]

        selected = collect_krw_markets(markets, excluded_keywords=["ETH"])
        self.assertEqual(selected, ["KRW-ETHW", "KRW-CETH"])

    def test_is_market_excluded_supports_exact_symbol_and_market_match(self):
        self.assertTrue(is_market_excluded("KRW-ETH", ["ETH"]))
        self.assertTrue(is_market_excluded("KRW-ETH", ["KRW-ETH"]))
        self.assertFalse(is_market_excluded("KRW-ETHW", ["ETH"]))
        self.assertFalse(is_market_excluded("KRW-CETH", ["ETH"]))

    def test_top_n_and_spread_filter(self):
        config = TradingConfig(
            do_not_trading=[],
            universe_top_n1=3,
            universe_watch_n2=2,
            low_spec_watch_cap_n2=2,
            max_relative_spread=0.002,
        )
        builder = UniverseBuilder(config)

        tickers = [
            {"market": "KRW-A", "acc_trade_price_24h": 5000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-B", "acc_trade_price_24h": 4000, "ask_price": 101.0, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-C", "acc_trade_price_24h": 3000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-D", "acc_trade_price_24h": 2000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
        ]
        turnover_5m_by_market = {"KRW-A": 500, "KRW-B": 400, "KRW-C": 300, "KRW-D": 200}

        selected = builder.select_watch_markets_with_report(
            tickers,
            turnover_5m_by_market=turnover_5m_by_market,
        ).watch_markets
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

    def test_sequential_filters_record_drop_reasons(self):
        config = TradingConfig(
            do_not_trading=[],
            universe_top_n1=3,
            low_spec_watch_cap_n2=1,
            max_relative_spread=0.002,
            max_candle_missing_rate=0.2,
        )
        builder = UniverseBuilder(config)

        tickers = [
            {"market": "KRW-A", "acc_trade_price_24h": 5000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-B", "acc_trade_price_24h": 4000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-C", "acc_trade_price_24h": 3000, "ask_price": 101.0, "bid_price": 100.0, "trade_price": 100.0},
            {"market": "KRW-D", "acc_trade_price_24h": 2000, "ask_price": 100.1, "bid_price": 100.0, "trade_price": 100.0},
        ]
        turnover_5m_by_market = {"KRW-A": 500, "KRW-B": 400, "KRW-C": 300}
        candles_by_market = {
            "KRW-A": [{"missing": False}] * 10,
            "KRW-B": [{"missing": True}] * 4 + [{"missing": False}] * 6,
            "KRW-C": [{"missing": False}] * 10,
        }

        result = builder.select_watch_markets_with_report(
            tickers,
            candles_by_market=candles_by_market,
            turnover_5m_by_market=turnover_5m_by_market,
        )

        self.assertEqual(result.watch_markets, ["KRW-A"])
        reason_by_market = {(item.market, item.stage): item.reason for item in result.drop_reasons}
        self.assertEqual(reason_by_market[("KRW-D", "top_n1")], "missing_5m_turnover")
        self.assertEqual(reason_by_market[("KRW-C", "relative_spread")], "relative_spread_exceeded")
        self.assertEqual(reason_by_market[("KRW-B", "missing_rate")], "missing_rate_exceeded")

    def test_top_n_falls_back_to_24h_trading_value_when_5m_turnover_not_provided(self):
        tickers = [
            {"market": "KRW-A", "acc_trade_price_24h": 2000},
            {"market": "KRW-B", "acc_trade_price_24h": 3000},
            {"market": "KRW-C", "acc_trade_price_24h": 1000},
        ]

        selected, drops = select_top_by_trading_value_with_drops(tickers, top_n1=2)

        self.assertEqual([item["market"] for item in selected], ["KRW-B", "KRW-A"])
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0].market, "KRW-C")
        self.assertEqual(drops[0].reason, "outside_top_n1_24h_trading_value")


if __name__ == "__main__":
    unittest.main()
