import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
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
        return [{"market": "KRW-BTC", "trade_price": 100000.0, "trade_volume": 1000}]

    def get_candles(self, _market, interval, count=200):
        _ = interval, count
        return [{"trade_price": 100.0} for _ in range(3)]

    def buy_market(self, market, price, identifier=None):
        self.buy_calls.append((market, price, identifier))
        return {"uuid": "order-uuid-1"}

    def sell_market(self, market, volume, identifier=None):
        _ = market, volume, identifier
        return {}

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return []

    def cancel_order(self, order_uuid):
        _ = order_uuid
        return {"state": "cancel"}

    def get_order(self, order_uuid):
        _ = order_uuid
        return {"state": "wait"}


class DummyNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


class TimeoutFlowBroker(BuyOnlyBroker):
    def __init__(self):
        super().__init__()
        self.cancel_calls = []
        self.get_order_calls = []

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return [
            {
                "identifier": "open-1",
                "uuid": "open-uuid-1",
                "market": "KRW-BTC",
                "side": "bid",
                "state": "wait",
                "volume": "20000",
                "executed_volume": "0",
            }
        ]

    def get_order(self, order_uuid):
        self.get_order_calls.append(order_uuid)
        return {"uuid": order_uuid, "state": "wait"}

    def cancel_order(self, order_uuid):
        self.cancel_calls.append(order_uuid)
        return {"uuid": order_uuid, "state": "cancel"}


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



    @patch("core.engine.check_buy", return_value=False)
    def test_run_once_prints_runtime_status_with_balance_and_stage(self, _mock_check_buy):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, notifier, config)

        with patch("builtins.print") as mock_print:
            engine.run_once()

        printed = "\n".join(" ".join(map(str, call.args)) for call in mock_print.call_args_list)
        self.assertIn("[STATUS] stage=evaluating_positions", printed)
        self.assertIn("available_krw=100000", printed)
        self.assertIn("holdings=0/1", printed)
        self.assertIn("[STATUS] stage=cycle_complete", printed)

    def test_preflight_blocks_buy_when_notional_below_exchange_minimum(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"], min_order_krw=5000)
        engine = TradingEngine(broker, notifier, config)

        result = engine._preflight_order(
            market="KRW-BTC",
            side="bid",
            requested_value=4999.9,
            reference_price=100000.0,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PREFLIGHT_MIN_NOTIONAL")

    def test_preflight_blocks_sell_when_recomputed_notional_is_invalid(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"], min_order_krw=5000)
        engine = TradingEngine(broker, notifier, config)

        result = engine._preflight_order(
            market="KRW-BTC",
            side="ask",
            requested_value=0.000000001,
            reference_price=100000.0,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PREFLIGHT_MIN_NOTIONAL")


    @patch("core.engine.check_buy", return_value=True)
    def test_buy_entry_boundary_by_final_order_amount(self, _mock_check_buy):
        for available_krw, expected_buy in ((8_000, False), (15_000, True), (25_000, True)):
            with self.subTest(available_krw=available_krw):
                broker = BuyOnlyBroker()
                broker.get_accounts = lambda value=available_krw: [
                    {
                        "unit_currency": "KRW",
                        "currency": "KRW",
                        "balance": str(value),
                        "locked": "0",
                        "avg_buy_price": "0",
                    }
                ]
                notifier = DummyNotifier()
                config = TradingConfig(
                    do_not_trading=[],
                    krw_markets=["KRW-BTC"],
                    min_order_krw=5_000,
                    min_buyable_krw=0,
                    max_holdings=2,
                )
                engine = TradingEngine(broker, notifier, config)

                engine.run_once()

                self.assertEqual(len(broker.buy_calls) == 1, expected_buy)

    @patch("core.engine.check_buy", return_value=True)
    def test_risk_gate_blocks_buy_on_loss_streak(self, _mock_check_buy):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"], max_consecutive_losses=2)
        engine = TradingEngine(broker, notifier, config)
        engine.risk.record_trade_result(-1000)
        engine.risk.record_trade_result(-1000)

        engine.run_once()

        self.assertEqual(len(broker.buy_calls), 0)
        self.assertEqual(engine.orders_by_identifier, {})


    def test_preflight_rounds_price_with_same_krw_tick_boundaries(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"], min_order_krw=5000)
        engine = TradingEngine(broker, notifier, config)

        boundary_cases = [
            (1000.4, 1000.0),
            (10000.9, 10000.0),
            (100049.9, 100000.0),
        ]

        for reference_price, expected in boundary_cases:
            result = engine._preflight_order(
                market="KRW-BTC",
                side="bid",
                requested_value=10000,
                reference_price=reference_price,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["rounded_price"], expected)

    def test_timeout_cancel_and_reorder_flow(self):
        broker = TimeoutFlowBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"], max_order_retries=1)
        engine = TradingEngine(broker, notifier, config)
        engine.bootstrap_open_orders()

        stale = engine.orders_by_identifier["open-1"]
        stale.state = OrderStatus.ACCEPTED
        stale.updated_at = datetime.now(timezone.utc) - timedelta(seconds=engine.order_timeout_seconds + 1)

        engine.reconcile_orders()

        self.assertGreaterEqual(broker.get_order_calls.count("open-uuid-1"), 1)
        self.assertEqual(broker.cancel_calls, ["open-uuid-1"])
        self.assertEqual(len(broker.buy_calls), 1)
        self.assertIn(":root=open-1", broker.buy_calls[0][2])

    def test_trade_reason_log_keeps_recent_10_records(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, notifier, config)

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "recent_trade_reasons.txt"
            engine._trade_reason_log_path = log_path

            for idx in range(12):
                side = "BUY" if idx % 2 == 0 else "SELL"
                engine._append_trade_reason(
                    side=side,
                    market="KRW-BTC",
                    reason=f"reason-{idx}",
                    price=1000 + idx,
                    qty=0.12345678 if idx == 11 else None,
                    notional_krw=10000 if idx == 11 else None,
                    qty_ratio=0.5 if idx == 11 else None,
                )

            self.assertTrue(log_path.exists())
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 10)
            self.assertIn("reason-2", lines[0])
            self.assertIn("qty=n/a | notional_krw=n/a | qty_ratio=n/a", lines[0])
            self.assertIn("reason-11", lines[-1])
            self.assertIn("qty=0.12345678 | notional_krw=10000 | qty_ratio=0.5000", lines[-1])


if __name__ == "__main__":
    unittest.main()
