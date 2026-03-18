from __future__ import annotations

import datetime
import os
import sys
import time
import traceback
from typing import cast

from core.config import TradingConfig
from core.config_loader import load_trading_config
from core.engine import TradingEngine
from core.interfaces import Broker
from infra.paper_broker import PaperBroker
from infra.upbit_ws_client import UpbitWebSocketClient
from message.notifier import Notifier


class NoopNotifier(Notifier):
    def send(self, message: str) -> None:
        print("[NOTIFY]", message)


def create_broker(config: TradingConfig) -> Broker:
    if config.mode in {"paper", "dry_run"}:
        return cast(
            Broker,
            PaperBroker(initial_krw=config.paper_initial_krw, fee_rate=config.fee_rate),
        )

    from infra.upbit_broker import UpbitBroker

    return cast(Broker, cast(object, UpbitBroker()))


def create_notifier(config: TradingConfig) -> Notifier:
    _ = config
    return NoopNotifier()


APP_CONFIG = load_trading_config()


def create_engine(
    broker: Broker | None = None,
    notifier: Notifier | None = None,
    config: TradingConfig | None = None,
    ws_client: UpbitWebSocketClient | None = None,
) -> TradingEngine:
    trading_config = config or APP_CONFIG
    trade_broker = broker or create_broker(trading_config)
    trade_notifier = notifier or create_notifier(trading_config)

    websocket_client = ws_client
    if websocket_client is None and trading_config.mode not in {"paper", "dry_run"}:
        websocket_client = UpbitWebSocketClient(
            default_format=trading_config.ws_data_format
        )

    return TradingEngine(
        trade_broker, trade_notifier, trading_config, ws_client=websocket_client
    )


def run_scheduler(
    engine: TradingEngine, poll_interval_seconds: int = 30, error_retry_seconds: int = 5
):
    engine.start()
    try:
        while True:
            try:
                print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                engine.run_once()
                time.sleep(poll_interval_seconds)
            except KeyboardInterrupt:
                sys.exit()
            except Exception as e:
                exc_type, _exc_obj, exc_tb = sys.exc_info()
                if exc_tb is not None:
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    lineno = exc_tb.tb_lineno
                else:
                    fname = "<unknown>"
                    lineno = 0
                print(exc_type, fname, lineno, e)
                traceback.print_exc()
                time.sleep(error_retry_seconds)
    finally:
        engine.shutdown()


if __name__ == "__main__":
    run_scheduler(create_engine())
