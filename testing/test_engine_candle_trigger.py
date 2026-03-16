import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from core.config import TradingConfig
from core.decision_models import DecisionIntent
from core.engine import TradingEngine


class TriggerBroker:
    def __init__(self):
        self.buy_orders = []
        self._candles = {
            1: [
                {"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 10000.0}
            ],
            5: [
                {"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 10000.0}
            ],
            15: [
                {"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 10000.0}
            ],
        }

    def get_markets(self):
        return [{"market": "KRW-BTC"}]

    def get_accounts(self):
        return []

    def get_ticker(self, markets):
        _ = markets
        return [{"market": "KRW-BTC", "trade_volume": 1000.0}]

    def get_candles(self, market, interval, count=200):
        _ = market, count
        return list(self._candles[interval])

    def buy_market(self, market, price, identifier=None):
        self.buy_orders.append(
            {"market": market, "value": price, "identifier": identifier}
        )
        return {"uuid": f"buy-{len(self.buy_orders)}"}

    def sell_market(self, market, volume, identifier=None):
        _ = market, volume, identifier
        return {"uuid": "sell-ignored"}

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return []

    def cancel_order(self, order_uuid):
        _ = order_uuid
        return {"state": "cancel"}

    def get_order(self, order_uuid):
        _ = order_uuid
        return {"state": "wait"}


class TimeStopBroker(TriggerBroker):
    def __init__(self):
        super().__init__()
        self.sell_orders = []

    def get_accounts(self):
        return [
            {"unit_currency": "KRW", "currency": "KRW", "balance": "0", "locked": "0"},
            {
                "unit_currency": "KRW",
                "currency": "BTC",
                "balance": "1.0",
                "locked": "0",
                "avg_buy_price": "10000.0",
            },
        ]

    def sell_market(self, market, volume, identifier=None):
        self.sell_orders.append(
            {"market": market, "volume": volume, "identifier": identifier}
        )
        return {"uuid": f"sell-{len(self.sell_orders)}"}

    def buy_market(self, market, price, identifier=None):
        _ = (market, price, identifier)
        return {"uuid": "buy-ignored"}


class DummyNotifier:
    def send(self, message: str):
        _ = message
        return None


class TradingEngineCandleTriggerTest(unittest.TestCase):
    def test_strategy_runs_once_per_closed_1m_candle(self):
        broker = TriggerBroker()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, DummyNotifier(), config)

        data = engine._get_strategy_candles("KRW-BTC")
        self.assertTrue(engine._should_run_strategy("KRW-BTC", data))
        self.assertFalse(engine._should_run_strategy("KRW-BTC", data))

        broker._candles[1] = [
            {"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 101.0}
        ]
        data = engine._get_strategy_candles("KRW-BTC")
        self.assertTrue(engine._should_run_strategy("KRW-BTC", data))

    def test_strategy_blocks_when_latest_candle_is_missing(self):
        broker = TriggerBroker()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, DummyNotifier(), config)

        data = {
            "1m": [
                {
                    "candle_date_time_utc": "2024-01-01T00:01:00",
                    "trade_price": 100.0,
                    "missing": True,
                }
            ],
            "5m": [
                {
                    "candle_date_time_utc": "2024-01-01T00:00:00",
                    "trade_price": 100.0,
                    "missing": False,
                }
            ],
            "15m": [
                {
                    "candle_date_time_utc": "2024-01-01T00:00:00",
                    "trade_price": 100.0,
                    "missing": False,
                }
            ],
        }

        self.assertFalse(engine._should_run_strategy("KRW-BTC", data))

    def test_time_stop_exits_when_max_hold_bars_reached(self):
        broker = TimeStopBroker()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            strategy_name="baseline",
            exit_mode="fixed_pct",
            min_buyable_krw=1_000_000_000,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)

        intents = [
            DecisionIntent(
                action="hold",
                reason="hold",
                diagnostics={"strategy_name": "baseline", "qty_ratio": 0.0},
                next_position_state={
                    "peak_price": 10000.0,
                    "entry_atr": 0.0,
                    "entry_swing_low": 10000.0,
                    "entry_price": 10000.0,
                    "initial_stop_price": 9750.0,
                    "risk_per_unit": 250.0,
                    "bars_held": 1,
                    "entry_regime": "weak_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                },
            ),
            DecisionIntent(
                action="exit_full",
                reason="time_stop",
                diagnostics={"strategy_name": "baseline", "qty_ratio": 1.0},
                next_position_state={},
            ),
        ]

        with patch(
            "core.engine.evaluate_market",
            create=True,
            side_effect=intents,
        ) as evaluate_market_mock:
            engine.run_once()
            self.assertEqual(len(broker.sell_orders), 0)
            self.assertEqual(engine._position_exit_states["KRW-BTC"].bars_held, 1)

            broker._candles[1] = [
                {"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 10000.0}
            ]
            engine.run_once()

        self.assertEqual(evaluate_market_mock.call_count, 2)
        self.assertEqual(len(broker.sell_orders), 1)
        self.assertEqual(broker.sell_orders[0]["market"], "KRW-BTC")
        self.assertAlmostEqual(broker.sell_orders[0]["volume"], 1.0)
        self.assertNotIn("KRW-BTC", engine._position_exit_states)
        self.assertEqual(
            engine._last_exit_snapshot_by_market["KRW-BTC"]["reason"], "time_stop"
        )

    def test_reentry_cooldown_blocks_same_market_and_counts_failures(self):
        broker = TriggerBroker()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            reentry_cooldown_bars=2,
            cooldown_on_loss_exits_only=True,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)
        engine._last_exit_snapshot_by_market["KRW-BTC"] = {
            "time": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            "reason": "stop_loss",
        }

        blocked = engine._is_reentry_cooldown_active(
            "KRW-BTC", datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc)
        )
        allowed = engine._is_reentry_cooldown_active(
            "KRW-BTC", datetime(2024, 1, 1, 0, 7, tzinfo=timezone.utc)
        )

        self.assertTrue(blocked)
        self.assertFalse(allowed)

    def test_strategy_exit_snapshot_is_recorded_for_strategy_signal_only(self):
        broker = TimeStopBroker()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            strategy_name="baseline",
            exit_mode="fixed_pct",
            min_buyable_krw=1_000_000_000,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)

        with (
            patch(
                "core.engine.evaluate_market",
                create=True,
                side_effect=[
                    DecisionIntent(
                        action="exit_full",
                        reason="time_stop",
                        diagnostics={"strategy_name": "baseline", "qty_ratio": 1.0},
                        next_position_state={},
                    ),
                    DecisionIntent(
                        action="exit_full",
                        reason="strategy_signal",
                        diagnostics={"strategy_name": "baseline", "qty_ratio": 1.0},
                        next_position_state={},
                    ),
                ],
            ) as evaluate_market_mock,
            patch.object(engine, "_should_run_strategy", return_value=True),
        ):
            engine.run_once()
            broker._candles[1] = [
                {"candle_date_time_utc": "2024-01-01T00:03:00", "trade_price": 10000.0}
            ]
            engine.run_once()

        self.assertEqual(evaluate_market_mock.call_count, 2)
        self.assertEqual(len(broker.sell_orders), 2)
        self.assertEqual(
            engine._last_exit_snapshot_by_market["KRW-BTC"]["reason"], "strategy_signal"
        )

        self.assertEqual(
            engine._last_strategy_exit_snapshot_by_market["KRW-BTC"]["reason"],
            "strategy_signal",
        )

    def test_strategy_cooldown_blocks_buy_and_counts_failure(self):
        broker = TriggerBroker()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            strategy_cooldown_bars=2,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)
        engine._last_strategy_exit_snapshot_by_market["KRW-BTC"] = {
            "time": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            "reason": "strategy_signal",
        }

        with patch(
            "core.engine.evaluate_market",
            create=True,
            return_value=DecisionIntent(
                action="enter",
                reason="ok",
                diagnostics={"strategy_name": "baseline", "entry_score": 2.8},
                next_position_state={
                    "peak_price": 10000.0,
                    "entry_atr": 0.0,
                    "entry_swing_low": 10000.0,
                    "entry_price": 10000.0,
                    "initial_stop_price": 9750.0,
                    "risk_per_unit": 250.0,
                    "bars_held": 0,
                    "entry_regime": "weak_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                },
            ),
        ) as evaluate_market_mock:
            engine._try_buy(
                available_krw=100000,
                held_markets=[],
                strategy_params=config.to_strategy_params(),
            )

        self.assertTrue(evaluate_market_mock.called)
        self.assertEqual(len(broker.buy_orders), 0)
        self.assertEqual(engine.debug_counters["fail_strategy_cooldown"], 1)

    def test_real_exit_seam_uses_engine_default_position_state_payload_when_missing(
        self,
    ):
        broker = TimeStopBroker()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            max_hold_bars=0,
            exit_mode="fixed_pct",
            min_buyable_krw=1_000_000_000,
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)
        broker._candles[1] = [
            {"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 10500.0}
        ]

        self.assertNotIn("KRW-BTC", engine._position_exit_states)

        with patch.object(
            engine,
            "_default_position_state_payload",
            wraps=engine._default_position_state_payload,
        ) as default_state_mock:
            engine.run_once()

        default_state_mock.assert_called_once()
        self.assertEqual(len(broker.sell_orders), 1)
        self.assertAlmostEqual(broker.sell_orders[0]["volume"], 0.5)
        self.assertIn("KRW-BTC", engine._position_exit_states)
        self.assertTrue(engine._position_exit_states["KRW-BTC"].strategy_partial_done)
        self.assertTrue(engine._position_exit_states["KRW-BTC"].breakeven_armed)


if __name__ == "__main__":
    unittest.main()
