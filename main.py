import datetime
import os
import sys
import time

import apis
import message.tele as tele
import slave_constants
from core.config import TradingConfig
from core.engine import TradingEngine


class LiveExecutor:
    def get_markets(self):
        return apis.get_markets()

    def get_accounts(self):
        return apis.get_accounts()

    def get_ticker(self, markets):
        return apis.get_ticker(markets)

    def get_candles_minutes(self, market, interval, count=200):
        return apis.get_candles_minutes(market, count=count, interval=interval)

    def ask_market(self, market, volume):
        return apis.ask_market(market, volume)

    def bid_price(self, market, price):
        return apis.bid_price(market, price)


class TelegramNotifier:
    def send(self, message: str) -> None:
        tele.sendMessage(message)


def create_engine(executor=None, notifier=None, config=None):
    trading_config = config or TradingConfig(
        do_not_trading=slave_constants.DO_NOT_TRADING,
    )
    trade_executor = executor or LiveExecutor()
    trade_notifier = notifier or TelegramNotifier()
    return TradingEngine(trade_executor, trade_notifier, trading_config)


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
