import unittest

from core.config import TradingConfig
from core.engine import TradingEngine


class DummyBroker:
    def get_markets(self):
        return [{"market": "KRW-BTC"}, {"market": "BTC-ETH"}]


class DummyNotifier:
    def send(self, message: str):
        pass


class DummyWsClient:
    def __init__(self):
        self.connected = False
        self.closed = False
        self.subscriptions = []

    def connect(self):
        self.connected = True

    def subscribe(self, subscription_type, markets, data_format=None):
        self.subscriptions.append((subscription_type, markets, data_format))

    def close(self):
        self.closed = True


class TradingEngineWebSocketHookTest(unittest.TestCase):
    def test_start_and_shutdown_hook_websocket_client(self):
        config = TradingConfig(do_not_trading=[], ws_data_format="SIMPLE_LIST")
        ws_client = DummyWsClient()
        engine = TradingEngine(DummyBroker(), DummyNotifier(), config, ws_client=ws_client)

        engine.start()
        engine.shutdown()

        self.assertTrue(ws_client.connected)
        self.assertTrue(ws_client.closed)
        self.assertEqual(ws_client.subscriptions[0], ("ticker", ["KRW-BTC"], "SIMPLE_LIST"))


if __name__ == "__main__":
    unittest.main()
