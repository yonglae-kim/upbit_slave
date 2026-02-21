import unittest

from core.config import TradingConfig
from core.engine import TradingEngine


class TriggerBroker:
    def __init__(self):
        self._candles = {
            1: [{"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 100.0}],
            5: [{"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 100.0}],
            15: [{"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 100.0}],
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


if __name__ == "__main__":
    unittest.main()
