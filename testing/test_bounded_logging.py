import logging
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from core.engine import TradingEngine
from core.runtime_logging import configure_runtime_logging


class BoundedLoggingTest(unittest.TestCase):
    def test_recent_trade_report_is_bounded_in_utf8_bytes(self):
        source = "header\n" + ("거래내역\n" * 200)

        with patch.dict(os.environ, {"TRADING_RECENT_TRADE_LOG_MAX_BYTES": "128"}):
            bounded = TradingEngine._bound_recent_trade_log(
                source, TradingEngine._recent_trade_log_max_bytes()
            )

        self.assertLessEqual(len(bounded.encode("utf-8")), 128)
        self.assertIn("recent trade log truncated", bounded)

    def test_engine_structured_events_are_written_to_bounded_logger(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "trading.log"
            logger = configure_runtime_logging(
                log_path=log_path,
                max_bytes=256,
                backup_count=2,
            )
            try:
                with redirect_stdout(StringIO()):
                    TradingEngine.__new__(TradingEngine)._emit_structured_log(
                        "TEST_EVENT", market="KRW-BTC"
                    )
                for handler in logger.handlers:
                    handler.flush()

                log_text = log_path.read_text(encoding="utf-8")
                self.assertIn("engine.event", log_text)
                self.assertIn("TEST_EVENT", log_text)
            finally:
                for handler in tuple(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()

    def test_rotates_runtime_log_with_bounded_file_count_and_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "trading.log"
            logger = configure_runtime_logging(
                log_path=log_path,
                max_bytes=256,
                backup_count=2,
            )
            try:
                for index in range(30):
                    logger.info("order.lifecycle index=%d payload=%s", index, "x" * 32)
                for handler in logger.handlers:
                    handler.flush()

                log_files = sorted(Path(temp_dir).glob("trading.log*"))
                self.assertEqual(len(log_files), 3)
                self.assertTrue(log_path.exists())
                self.assertTrue(all(path.stat().st_size <= 256 for path in log_files))
            finally:
                for handler in tuple(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()


if __name__ == "__main__":
    unittest.main()
