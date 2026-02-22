import datetime
import sys
import types
import unittest
from unittest.mock import patch

if 'slave_constants' not in sys.modules:
    sys.modules['slave_constants'] = types.SimpleNamespace(ACCESS_KEY='x', SECRET_KEY='y', SERVER_URL='https://api.upbit.com')

from testing.backtest_runner import BacktestRunner


class BacktestRunnerTest(unittest.TestCase):
    def _candle(self, ts: datetime.datetime, price: float):
        return {
            "market": "KRW-BTC",
            "candle_date_time_kst": ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "opening_price": price,
            "high_price": price,
            "low_price": price,
            "trade_price": price,
            "candle_acc_trade_volume": 1,
        }

    def test_shortage_policy_pads_missing_candles(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i) for i in range(5)]

        padded, shortage = runner._apply_shortage_policy(candles)

        self.assertEqual(len(padded), 8)
        self.assertEqual(shortage, 3)
        self.assertTrue(padded[-1].get("missing", False))

    def test_target_count_expands_for_lookback_days(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, lookback_days=7)
        self.assertGreaterEqual(runner._target_count(), 7 * 24 * 20)

    def test_filter_recent_days_uses_latest_window(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, lookback_days=7)
        latest = datetime.datetime(2024, 1, 15, 0, 0, 0)
        candles = [self._candle(latest - datetime.timedelta(days=i), 10000 + i) for i in range(10)]

        filtered = runner._filter_recent_days(candles)

        self.assertEqual(filtered[0]["candle_date_time_kst"], candles[0]["candle_date_time_kst"])
        self.assertLessEqual(len(filtered), len(candles))
        self.assertGreaterEqual(len(filtered), 7)

    def test_oos_windows_is_clamped_to_two_or_more(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2, oos_windows=1)
        self.assertEqual(runner.oos_windows, 2)


    def test_build_mtf_candles_resamples_ohlcv(self):
        runner = BacktestRunner(buffer_cnt=4, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 5, 0)
        candles = [
            {
                **self._candle(base - datetime.timedelta(minutes=i), 100 + i),
                "opening_price": 100 + i,
                "high_price": 101 + (i * 2),
                "low_price": 99 - i,
                "trade_price": 100.5 + i,
                "candle_acc_trade_volume": 1 + i,
            }
            for i in range(6)
        ]

        mtf = runner._build_mtf_candles(candles)

        self.assertEqual(set(mtf.keys()), {"1m", "5m", "15m"})
        self.assertEqual(len(mtf["1m"]), 6)
        self.assertEqual(len(mtf["5m"]), 2)
        latest_5m = mtf["5m"][0]
        self.assertEqual(latest_5m["opening_price"], candles[0]["opening_price"])
        self.assertEqual(latest_5m["trade_price"], candles[0]["trade_price"])
        self.assertEqual(latest_5m["high_price"], max(c["high_price"] for c in candles[:1]))
        self.assertEqual(latest_5m["low_price"], min(c["low_price"] for c in candles[:1]))

        older_5m = mtf["5m"][1]
        bucket = candles[1:]
        self.assertEqual(older_5m["opening_price"], bucket[-1]["opening_price"])
        self.assertEqual(older_5m["trade_price"], bucket[0]["trade_price"])
        self.assertEqual(older_5m["high_price"], max(c["high_price"] for c in bucket))
        self.assertEqual(older_5m["low_price"], min(c["low_price"] for c in bucket))
        self.assertEqual(older_5m["candle_acc_trade_volume"], sum(c["candle_acc_trade_volume"] for c in bucket))


    @patch("testing.backtest_runner.check_buy", return_value=False)
    def test_run_segment_when_len_equals_buffer_runs_once(self, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + i) for i in range(3)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        args, _ = _check_buy.call_args
        self.assertIsInstance(args[0], dict)
        self.assertEqual(set(args[0].keys()), {"1m", "5m", "15m"})
        self.assertEqual(result.attempted_entries, 1)
        self.assertEqual(result.trades, 0)

    @patch("testing.backtest_runner.check_buy", return_value=True)
    @patch("testing.backtest_runner.check_sell", return_value=True)
    def test_run_segment_applies_costs_and_metrics(self, _check_sell, _check_buy):
        runner = BacktestRunner(buffer_cnt=3, multiple_cnt=2, spread_rate=0.001, slippage_rate=0.001)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0)
        candles = [self._candle(base - datetime.timedelta(minutes=3 * i), 10000 + (10 * i)) for i in range(10)]

        result = runner._run_segment(candles, init_amount=1_000_000, segment_id=1)

        self.assertGreaterEqual(result.trades, 1)
        self.assertGreaterEqual(result.fill_rate, 0)
        self.assertLessEqual(result.fill_rate, 1)
        self.assertIsInstance(result.sharpe, float)


if __name__ == "__main__":
    unittest.main()
