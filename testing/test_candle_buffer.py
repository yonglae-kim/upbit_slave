import unittest

from core.candle_buffer import CandleBuffer


class CandleBufferTest(unittest.TestCase):
    def test_missing_gap_is_filled_for_1m_interval(self):
        buffer = CandleBuffer(maxlen_by_interval={1: 10, 5: 10, 15: 10})

        candles = [
            {"candle_date_time_utc": "2024-01-01T00:03:00", "trade_price": 103},
            {"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 101},
            {"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 100},
        ]

        buffer.update("KRW-BTC", 1, candles)
        snapshot = list(reversed(buffer.snapshot("KRW-BTC", 1)))  # oldest -> newest

        self.assertEqual(len(snapshot), 4)
        self.assertEqual(snapshot[2]["candle_date_time_utc"], "2024-01-01T00:02:00")
        self.assertTrue(snapshot[2]["missing"])
        self.assertEqual(snapshot[2]["trade_price"], 101.0)

    def test_ring_buffer_maxlen_is_respected(self):
        buffer = CandleBuffer(maxlen_by_interval={1: 3, 5: 3, 15: 3})

        candles = [
            {"candle_date_time_utc": "2024-01-01T00:00:00", "trade_price": 100},
            {"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 101},
            {"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 102},
            {"candle_date_time_utc": "2024-01-01T00:03:00", "trade_price": 103},
        ]

        buffer.update("KRW-BTC", 1, candles)
        snapshot = buffer.snapshot("KRW-BTC", 1)

        self.assertEqual(len(snapshot), 3)
        self.assertEqual(snapshot[0]["candle_date_time_utc"], "2024-01-01T00:03:00")

    def test_out_of_order_candle_is_rejected(self):
        buffer = CandleBuffer(maxlen_by_interval={1: 10, 5: 10, 15: 10})

        buffer.update("KRW-BTC", 1, [{"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 102}])
        buffer.update("KRW-BTC", 1, [{"candle_date_time_utc": "2024-01-01T00:01:00", "trade_price": 101}])

        snapshot = buffer.snapshot("KRW-BTC", 1)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["candle_date_time_utc"], "2024-01-01T00:02:00")
        self.assertEqual(buffer.contamination_stats["out_of_order"], 1)

    def test_duplicate_candle_overwrites_latest(self):
        buffer = CandleBuffer(maxlen_by_interval={1: 10, 5: 10, 15: 10})

        buffer.update("KRW-BTC", 1, [{"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 100}])
        buffer.update("KRW-BTC", 1, [{"candle_date_time_utc": "2024-01-01T00:02:00", "trade_price": 105}])

        snapshot = buffer.snapshot("KRW-BTC", 1)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["trade_price"], 105)
        self.assertEqual(buffer.contamination_stats["duplicate"], 1)

    def test_parse_candle_time_returns_utc_aware_datetime(self):
        buffer = CandleBuffer(maxlen_by_interval={1: 10, 5: 10, 15: 10})

        parsed_iso = buffer.parse_candle_time({"candle_date_time_utc": "2024-01-01T00:00:00"})
        parsed_epoch = buffer.parse_candle_time({"timestamp": 1704067200000})

        self.assertIsNotNone(parsed_iso)
        self.assertIsNotNone(parsed_epoch)
        self.assertIsNotNone(parsed_iso.tzinfo)
        self.assertIsNotNone(parsed_epoch.tzinfo)
        self.assertEqual(parsed_iso.utcoffset().total_seconds(), 0)
        self.assertEqual(parsed_epoch.utcoffset().total_seconds(), 0)



if __name__ == "__main__":
    unittest.main()
