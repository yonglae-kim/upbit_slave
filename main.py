from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
import traceback
from typing import cast

from core.config import TradingConfig
from core.config_loader import ConfigValidationError, load_trading_config
from core.engine import TradingEngine
from core.interfaces import Broker
from core.runtime_readiness import runtime_status_payload
from core.runtime_logging import configure_runtime_logging
from infra.paper_broker import PaperBroker
from infra.upbit_ws_client import UpbitWebSocketClient
from message.notifier import Notifier


class NoopNotifier(Notifier):
    def send(self, message: str) -> None:
        print("[NOTIFY]", message)
        logging.getLogger("upbit_slave").info("notifier.message message=%s", message)


def create_broker(config: TradingConfig) -> Broker:
    if config.mode in {"paper", "dry_run"}:
        return cast(
            Broker,
            PaperBroker(initial_krw=config.paper_initial_krw, fee_rate=config.fee_rate),
        )

    if (
        getattr(config, "live_authorization", None) is not True
        or getattr(config, "runtime_promotion_allowed", None) is not True
    ):
        raise ConfigValidationError(
            "live broker construction requires explicit runtime authorization"
        )

    if os.getenv("TRADING_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise ConfigValidationError("live broker construction is disabled offline")

    from infra.upbit_broker import UpbitBroker, UpbitLiveAuthorization

    return cast(Broker, UpbitBroker(authorization=UpbitLiveAuthorization()))


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
    if trading_config.mode not in {"paper", "dry_run"} and (
        getattr(trading_config, "live_authorization", None) is not True
        or getattr(trading_config, "runtime_promotion_allowed", None) is not True
    ):
        raise ConfigValidationError(
            "live websocket construction requires explicit runtime authorization"
        )
    trade_broker = broker or create_broker(trading_config)
    trade_notifier = notifier or create_notifier(trading_config)

    websocket_client = ws_client
    if websocket_client is None and trading_config.mode not in {"paper", "dry_run"}:
        from infra.upbit_broker import UpbitLiveAuthorization

        websocket_client = UpbitWebSocketClient(
            authorization=UpbitLiveAuthorization(),
            default_format=trading_config.ws_data_format
        )

    return TradingEngine(
        trade_broker, trade_notifier, trading_config, ws_client=websocket_client
    )


def run_scheduler(
    engine: TradingEngine, poll_interval_seconds: int = 30, error_retry_seconds: int = 5
):
    logger = configure_runtime_logging()
    logger.info(
        "scheduler.started poll_interval_seconds=%d error_retry_seconds=%d",
        poll_interval_seconds,
        error_retry_seconds,
    )
    engine.start()
    try:
        while True:
            try:
                logger.info("scheduler.cycle_started")
                print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                engine.run_once()
                logger.info("scheduler.cycle_completed")
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
                logger.exception(
                    "scheduler.cycle_failed file=%s line=%d error_type=%s",
                    fname,
                    lineno,
                    exc_type.__name__ if exc_type is not None else "unknown",
                )
                print(exc_type, fname, lineno, e)
                traceback.print_exc()
                time.sleep(error_retry_seconds)
    finally:
        engine.shutdown()
        logger.info("scheduler.stopped")


def print_runtime_status(config: TradingConfig) -> int:
    """Print runtime readiness as JSON without constructing a broker."""
    print(json.dumps(runtime_status_payload(config), ensure_ascii=False, sort_keys=True))
    return 0


def run_one_cycle(engine: TradingEngine) -> int:
    """Run exactly one trading cycle and always release runtime resources."""
    logger = configure_runtime_logging()
    logger.info("one_cycle.started")
    try:
        engine.start()
        engine.run_once()
        logger.info("one_cycle.completed")
        return 0
    finally:
        engine.shutdown()
        logger.info("one_cycle.stopped")


if __name__ == "__main__":
    configure_runtime_logging()
    if sys.argv[1:] == ["--runtime-status"]:
        raise SystemExit(print_runtime_status(APP_CONFIG))
    if sys.argv[1:] == ["--once"]:
        raise SystemExit(run_one_cycle(create_engine()))
    run_scheduler(create_engine())
