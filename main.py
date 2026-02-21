import datetime
import os
import sys
import time

import slave_constants
from core.config import TradingConfig
from core.engine import TradingEngine
from infra.paper_broker import PaperBroker
from infra.upbit_broker import UpbitBroker
from message.notifier import Notifier
from message.tele import TelegramNotifier


class NoopNotifier(Notifier):
    def send(self, message: str) -> None:
        print("[NOTIFY]", message)


def create_broker(config: TradingConfig):
    if config.mode in {"paper", "dry_run"}:
        return PaperBroker(initial_krw=config.paper_initial_krw, fee_rate=config.fee_rate)
    return UpbitBroker()


def create_notifier(config: TradingConfig):
    if config.mode in {"paper", "dry_run"}:
        return NoopNotifier()
    return TelegramNotifier()


def create_engine(broker=None, notifier=None, config=None):
    trading_config = config or TradingConfig(
        do_not_trading=slave_constants.DO_NOT_TRADING,
        mode=getattr(slave_constants, "MODE", "live"),
        paper_initial_krw=getattr(slave_constants, "PAPER_INITIAL_KRW", 1_000_000),
    )
    trade_broker = broker or create_broker(trading_config)
    trade_notifier = notifier or create_notifier(trading_config)
    return TradingEngine(trade_broker, trade_notifier, trading_config)


def run_scheduler(engine: TradingEngine, poll_interval_seconds: int = 30, error_retry_seconds: int = 5):
    while True:
        try:
            print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            engine.run_once()
            time.sleep(poll_interval_seconds)
        except KeyboardInterrupt:
            sys.exit()
        except Exception as e:
            exc_type, _exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno, e)
            time.sleep(error_retry_seconds)


if __name__ == "__main__":
    run_scheduler(create_engine())
