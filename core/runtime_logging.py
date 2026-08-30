from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final


LOGGER_NAME: Final = "upbit_slave"
DEFAULT_LOG_PATH: Final = "runtime_logs/trading.log"
DEFAULT_MAX_BYTES: Final = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT: Final = 3
_LOG_LEVELS: Final = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def configure_runtime_logging(
    *,
    log_path: Path | str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> logging.Logger:
    """Configure one bounded file logger for the live runtime."""
    resolved_path = _resolve_log_path(log_path)
    effective_max_bytes = max(
        1,
        max_bytes if max_bytes is not None else _env_int(
            "TRADING_LOG_MAX_BYTES", DEFAULT_MAX_BYTES
        ),
    )
    effective_backup_count = max(
        1,
        backup_count if backup_count is not None else _env_int(
            "TRADING_LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT
        ),
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_env_log_level())
    logger.propagate = False
    _replace_file_handlers(
        logger,
        resolved_path,
        effective_max_bytes,
        effective_backup_count,
    )
    return logger


def _resolve_log_path(log_path: Path | str | None) -> Path:
    if log_path is not None:
        return Path(log_path)
    configured_path = os.getenv("TRADING_LOG_PATH", DEFAULT_LOG_PATH).strip()
    return Path(configured_path or DEFAULT_LOG_PATH)


def _env_int(name: str, fallback: int) -> int:
    raw_value = os.getenv(name, "").strip()
    try:
        return int(raw_value)
    except ValueError:
        return fallback


def _env_log_level() -> int:
    level_name = os.getenv("TRADING_LOG_LEVEL", "INFO").strip().upper()
    return _LOG_LEVELS.get(level_name, logging.INFO)


def _replace_file_handlers(
    logger: logging.Logger,
    log_path: Path,
    max_bytes: int,
    backup_count: int,
) -> None:
    resolved_path = log_path.expanduser().resolve()
    for handler in tuple(logger.handlers):
        if not isinstance(handler, RotatingFileHandler):
            continue
        handler_path = Path(handler.baseFilename).resolve()
        if (
            handler_path == resolved_path
            and handler.maxBytes == max_bytes
            and handler.backupCount == backup_count
        ):
            return
        logger.removeHandler(handler)
        handler.close()

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        resolved_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)
