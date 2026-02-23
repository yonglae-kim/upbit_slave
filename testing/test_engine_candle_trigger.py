import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from core.config import TradingConfig
from core.engine import TradingEngine

class TriggerBroker:
    def __init__(self):
        self._candles = {
            1: [{"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 10000.0}],
            5: [{"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 10000.0}],
            15: [{"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 10000.0}],
        }

    def get_markets(self):
        return [{"market": "KRW-BTC"}]

    def get_accounts(self):
        return []

    def get_ticker(self, _markets):
        return [{"market": "KRW-BTC", "trade_volume": 1000.0}]

    def get_candles(self, _market, interval, count=200):
        _ = count
        return list(self._candles[interval])

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
        self.sell_orders.append({"market": market, "volume": volume, "identifier": identifier})
        return {"uuid": f"sell-{len(self.sell_orders)}"}

    def buy_market(self, market, value, identifier=None):
        _ = (market, value, identifier)
        return {"uuid": "buy-ignored"}

class DummyNotifier:
    def send(self, _message: str):
        return None

class TradingEngineCandleTriggerTest(unittest.TestCase):
    def test_strategy_runs_once_per_closed_1m_candle(self):
        broker = TriggerBroker()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, DummyNotifier(), config)

        data = engine._get_strategy_candles("KRW-BTC")
        self.assertTrue(engine._should_run_strategy("KRW-BTC", data))
        self.assertFalse(engine._should_run_strategy("KRW-BTC", data))

        broker._candles[1] = [{"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 101.0}]
        data = engine._get_strategy_candles("KRW-BTC")
        self.assertTrue(engine._should_run_strategy("KRW-BTC", data))

    def test_strategy_blocks_when_latest_candle_is_missing(self):
        broker = TriggerBroker()
        config = TradingConfig(do_not_trading=[], krw_markets=["KRW-BTC"])
        engine = TradingEngine(broker, DummyNotifier(), config)

        data = {
            "1m": [{"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 100.0, "missing": True}],
            "5m": [{"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 100.0, "missing": False}],
            "15m": [{"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 100.0, "missing": False}],
        }

        self.assertFalse(engine._should_run_strategy("KRW-BTC", data))

    def test_time_stop_exits_when_max_hold_bars_reached(self):
        broker = TimeStopBroker()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            max_hold_bars=2,
            exit_mode="fixed_pct",
            min_buyable_krw=1_000_000_000,
        )
        engine = TradingEngine(broker, DummyNotifier(), config)

        with patch("core.engine.check_sell", return_value=False):
            engine.run_once()
            self.assertEqual(len(broker.sell_orders), 0)
            self.assertEqual(engine._position_exit_states["KRW-BTC"].bars_held, 1)

            broker._candles[1] = [{"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 10000.0}]
            engine.run_once()

        self.assertEqual(len(broker.sell_orders), 1)
        self.assertEqual(broker.sell_orders[0]["market"], "KRW-BTC")
        self.assertAlmostEqual(broker.sell_orders[0]["volume"], 1.0)
        self.assertNotIn("KRW-BTC", engine._position_exit_states)
        self.assertEqual(engine._last_exit_snapshot_by_market["KRW-BTC"]["reason"], "time_stop")

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

        blocked = engine._is_reentry_cooldown_active("KRW-BTC", datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc))
        allowed = engine._is_reentry_cooldown_active("KRW-BTC", datetime(2024, 1, 1, 0, 7, tzinfo=timezone.utc))

        self.assertTrue(blocked)
        self.assertFalse(allowed)

if __name__ == "__main__":
    unittest.main()
