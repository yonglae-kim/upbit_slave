import unittest
from datetime import datetime, timedelta, timezone

from core.config import TradingConfig
from core.engine import TradingEngine


class UniverseRefreshBroker:
    def __init__(self):
        self.candle_calls = []

    def get_markets(self):
        return [{"market": "KRW-A"}, {"market": "KRW-B"}]

    def get_accounts(self):
        return [
            {
                "unit_currency": "KRW",
                "currency": "KRW",
                "balance": "100000",
                "locked": "0",
                "avg_buy_price": "0",
            }
        ]

    def get_ticker(self, markets):
        selected = [m.strip() for m in str(markets).split(",") if m.strip()]
        return [
            {
                "market": market,
                "trade_price": 100.0,
                "ask_price": 100.1,
                "bid_price": 100.0,
                "acc_trade_price_24h": 1000.0,
            }
            for market in selected
        ]

    def get_candles(self, market, interval, count=200):
        self.candle_calls.append((market, interval, count))
        if count == 10 and interval == 1:
            return [
                {"candle_acc_trade_price": 100.0, "trade_price": 100.0}
                for _ in range(10)
            ]
        return [
            {"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 100.0}
            for _ in range(60)
        ]

    def buy_market(self, market, price, identifier=None):
        _ = market, price, identifier
        return {"uuid": "buy-uuid"}

    def sell_market(self, market, volume, identifier=None):
        _ = market, volume, identifier
        return {"uuid": "sell-uuid"}

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return []

    def cancel_order(self, order_uuid):
        _ = order_uuid
        return {"state": "cancel"}

    def get_order(self, order_uuid):
        _ = order_uuid
        return {"state": "done"}


class DummyNotifier:
    def send(self, message: str):
        _ = message
        return None


class TradingEngineUniverseRefreshTest(unittest.TestCase):
    def test_universe_10m_scan_refreshes_hourly(self):
        broker = UniverseRefreshBroker()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-A", "KRW-B"])
        engine = TradingEngine(broker, DummyNotifier(), config)

        engine._refresh_watch_markets_if_needed()
        first_scan_calls = [
            call for call in broker.candle_calls if call[1] == 1 and call[2] == 10
        ]
        self.assertEqual(len(first_scan_calls), 2)

        engine._refresh_watch_markets_if_needed()
        second_scan_calls = [
            call for call in broker.candle_calls if call[1] == 1 and call[2] == 10
        ]
        self.assertEqual(len(second_scan_calls), 2)

        engine._last_universe_refreshed_at = datetime.now(timezone.utc) - timedelta(
            hours=1, minutes=1
        )
        engine._refresh_watch_markets_if_needed()
        third_scan_calls = [
            call for call in broker.candle_calls if call[1] == 1 and call[2] == 10
        ]
        self.assertEqual(len(third_scan_calls), 4)

    def test_universe_refresh_applies_ict_v1_ranking_overlay_when_candles_available(
        self,
    ):
        class ICTUniverseRefreshBroker(UniverseRefreshBroker):
            def get_ticker(self, markets):
                _ = markets
                return [
                    {
                        "market": "KRW-A",
                        "trade_price": 100.0,
                        "ask_price": 100.1,
                        "bid_price": 100.0,
                        "acc_trade_price_24h": 1000.0,
                    },
                    {
                        "market": "KRW-B",
                        "trade_price": 100.0,
                        "ask_price": 100.1,
                        "bid_price": 100.0,
                        "acc_trade_price_24h": 1000.0,
                    },
                ]

            def get_candles(self, market, interval, count=200):
                self.candle_calls.append((market, interval, count))
                if count == 10 and interval == 1:
                    values = {"KRW-A": 120.0, "KRW-B": 110.0}
                    return [
                        {"candle_acc_trade_price": values[market], "trade_price": 100.0}
                        for _ in range(10)
                    ]
                if interval == 1:
                    if market == "KRW-A":
                        return [
                            {
                                "candle_date_time_utc": "2024-01-01T00:01:00",
                                "trade_price": 100.0,
                                "opening_price": 100.0,
                                "high_price": 100.2,
                                "low_price": 99.8,
                            },
                            {
                                "candle_date_time_utc": "2024-01-01T00:02:00",
                                "trade_price": 100.0,
                                "opening_price": 100.0,
                                "high_price": 100.2,
                                "low_price": 99.8,
                            },
                            {
                                "candle_date_time_utc": "2024-01-01T00:03:00",
                                "trade_price": 100.0,
                                "opening_price": 100.0,
                                "high_price": 100.2,
                                "low_price": 99.8,
                            },
                        ]
                    return [
                        {
                            "candle_date_time_utc": "2024-01-01T00:01:00",
                            "trade_price": 100.8,
                            "opening_price": 100.0,
                            "high_price": 101.0,
                            "low_price": 99.8,
                        },
                        {
                            "candle_date_time_utc": "2024-01-01T00:02:00",
                            "trade_price": 102.4,
                            "opening_price": 100.8,
                            "high_price": 102.7,
                            "low_price": 100.5,
                        },
                        {
                            "candle_date_time_utc": "2024-01-01T00:03:00",
                            "trade_price": 105.0,
                            "opening_price": 102.4,
                            "high_price": 105.3,
                            "low_price": 102.1,
                        },
                    ]
                return [
                    {
                        "candle_date_time_utc": "2024-01-01T00:01:00",
                        "trade_price": 100.0,
                    }
                    for _ in range(60)
                ]

        broker = ICTUniverseRefreshBroker()
        config = TradingConfig(
            do_not_trading=[],
            strategy_name="ict_v1",
            krw_markets=["KRW-A", "KRW-B"],
            universe_top_n1=2,
            low_spec_watch_cap_n2=1,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)

        watch_markets = engine._refresh_watch_markets_if_needed()

        self.assertEqual(watch_markets, ["KRW-B"])


if __name__ == "__main__":
    unittest.main()
