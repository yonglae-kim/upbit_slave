import unittest
from datetime import datetime, timedelta, timezone

from core.config import TradingConfig
from core.engine import TradingEngine
from core.order_state import OrderRecord, OrderStatus
from core.reconciliation import apply_my_asset_event, apply_my_order_event


class DummyNotifier:
    def send(self, _message):
        pass


class BrokerWithOpenOrders:
    def get_markets(self):
        return [{"market": "KRW-BTC"}]

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return [
            {
                "identifier": "boot-1",
                "uuid": "u-1",
                "market": "KRW-BTC",
                "side": "bid",
                "state": "wait",
                "volume": "2",
                "executed_volume": "0.5",
            }
        ]


class TradingEngineReconciliationTest(unittest.TestCase):
    def test_apply_my_order_event_tracks_partial_fill(self):
        store = {}
        updated = apply_my_order_event(
            {
                "identifier": "id-1",
                "uuid": "u-1",
                "market": "KRW-BTC",
                "side": "bid",
                "state": "wait",
                "volume": "3",
                "executed_volume": "1.2",
            },
            store,
        )

        self.assertEqual(updated.state, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(store["id-1"].filled_qty, 1.2)

    def test_apply_my_asset_event_updates_snapshot(self):
        snapshot = {"BTC": {"balance": 0.1, "locked": 0.0, "avg_buy_price": 1.0}}
        apply_my_asset_event(
            {
                "assets": [
                    {"currency": "KRW", "balance": "1000", "locked": "0", "avg_buy_price": "0"},
                    {"currency": "BTC", "balance": "0.2", "locked": "0.01", "avg_buy_price": "90000"},
                ]
            },
            snapshot,
        )

        self.assertEqual(set(snapshot.keys()), {"KRW", "BTC"})
        self.assertEqual(snapshot["BTC"]["balance"], 0.2)

    def test_bootstrap_and_timeout_hook(self):
        class HookEngine(TradingEngine):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.timeout_called = []

            def _on_order_timeout(self, order):
                self.timeout_called.append(order.identifier)

        engine = HookEngine(BrokerWithOpenOrders(), DummyNotifier(), TradingConfig(do_not_trading=[]))
        engine.bootstrap_open_orders()
        self.assertIn("boot-1", engine.orders_by_identifier)

        stale = engine.orders_by_identifier["boot-1"]
        stale.updated_at = datetime.now(timezone.utc) - timedelta(seconds=engine.order_timeout_seconds + 1)
        stale.state = OrderStatus.ACCEPTED
        engine.reconcile_orders()

        self.assertIn("boot-1", engine.timeout_called)
        self.assertEqual(stale.state, OrderStatus.PARTIALLY_FILLED)

    def test_ws_router_uses_myorder_and_myasset_roles(self):
        engine = TradingEngine(BrokerWithOpenOrders(), DummyNotifier(), TradingConfig(do_not_trading=[]))

        engine._route_ws_message(
            {
                "type": "myOrder",
                "identifier": "ws-1",
                "market": "KRW-BTC",
                "side": "ask",
                "state": "done",
                "volume": "1",
                "executed_volume": "1",
            }
        )
        engine._route_ws_message(
            {
                "type": "myAsset",
                "assets": [{"currency": "KRW", "balance": "5000", "locked": "0", "avg_buy_price": "0"}],
            }
        )

        self.assertEqual(engine.orders_by_identifier["ws-1"].state, OrderStatus.FILLED)
        self.assertEqual(engine.portfolio_snapshot["KRW"]["balance"], 5000.0)


if __name__ == "__main__":
    unittest.main()
