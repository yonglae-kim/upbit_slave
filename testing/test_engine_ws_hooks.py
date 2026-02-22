import unittest

from core.config import TradingConfig
from core.engine import TradingEngine


class DummyBroker:
    def get_markets(self):
        return [{"market": "KRW-BTC"}, {"market": "BTC-ETH"}]

    def get_order(self, order_uuid):
        return {"uuid": order_uuid, "state": "wait"}


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

    def subscribe(self, subscription_type, markets=None, data_format=None, is_private=False, extra_payload=None):
        self.subscriptions.append((subscription_type, markets or [], data_format, is_private))

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
        self.assertEqual(ws_client.subscriptions[0], ("ticker", ["KRW-BTC"], "SIMPLE_LIST", False))
        self.assertIn(("myOrder", [], "SIMPLE_LIST", True), ws_client.subscriptions)
        self.assertIn(("myAsset", [], "SIMPLE_LIST", True), ws_client.subscriptions)

    def test_route_private_events_update_state(self):
        config = TradingConfig(do_not_trading=[], ws_data_format="SIMPLE_LIST")
        ws_client = DummyWsClient()
        engine = TradingEngine(DummyBroker(), DummyNotifier(), config, ws_client=ws_client)

        engine._route_ws_message({
            "type": "myOrder",
            "uuid": "uuid-1",
            "identifier": "id-1",
            "market": "KRW-BTC",
            "side": "bid",
            "volume": "1",
            "executed_volume": "1",
            "state": "done",
        })
        engine._route_ws_message({
            "type": "myAsset",
            "assets": [{"currency": "KRW", "balance": "1000", "locked": "100", "avg_buy_price": "0"}],
        })

        self.assertEqual(engine.orders_by_identifier["id-1"].filled_qty, 1.0)
        self.assertEqual(engine.portfolio_snapshot["KRW"]["balance"], 1000.0)


if __name__ == "__main__":
    unittest.main()
