import unittest
from unittest.mock import patch

from core.config import TradingConfig
from core.engine import TradingEngine
from core.order_state import OrderStatus


class BuyOnlyBroker:
    def __init__(self):
        self.buy_calls = []

    def get_markets(self):
        return [{"market": "KRW-BTC"}]

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

    def get_ticker(self, _markets):
        return [{"market": "KRW-BTC", "trade_volume": 1000}]

    def get_candles(self, _market, interval, count=200):
        _ = interval, count
        return [{"trade_price": 100.0} for _ in range(3)]

    def buy_market(self, market, price, identifier=None):
        self.buy_calls.append((market, price, identifier))
        return {"uuid": "order-uuid-1"}

    def sell_market(self, market, volume, identifier=None):
        _ = market, volume, identifier
        return {}


class DummyNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


class TradingEngineOrderAcceptanceTest(unittest.TestCase):
    @patch("core.engine.check_buy", return_value=True)
    def test_market_buy_is_recorded_as_accepted(self, _mock_check_buy):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, notifier, config)

        engine.run_once()

        self.assertEqual(len(broker.buy_calls), 1)
        _, _, identifier = broker.buy_calls[0]
        self.assertIsNotNone(identifier)
        self.assertIn(identifier, engine.orders_by_identifier)

        order = engine.orders_by_identifier[identifier]
        self.assertEqual(order.state, OrderStatus.ACCEPTED)
        self.assertEqual(order.filled_qty, 0.0)
        self.assertEqual(order.uuid, "order-uuid-1")


if __name__ == "__main__":
    unittest.main()
