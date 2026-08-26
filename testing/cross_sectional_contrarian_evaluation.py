from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Final, List, Optional, Tuple

from testing.cross_sectional_momentum_evaluation import (
    MARKETS,
    AlignedMarketData,
    Candle,
    EvaluationInputError,
    align_series,
    validate_manifest as _validate_manifest,
)


CANDIDATE: Final[str] = "cross_sectional_contrarian_bounce"
_MANIFEST_REQUIRED_KEYS: Final = frozenset(
    {"fetched_at_utc", "interval_minutes", "markets", "requested_rows_per_market", "source", "synthetic_rows"},
)
_MANIFEST_OPTIONAL_KEYS: Final = frozenset(
    {"collection_start_utc", "collection_end_utc", "evaluation_start_utc", "evaluation_end_utc", "notes"},
)
_MARKET_MANIFEST_REQUIRED_KEYS: Final = frozenset(
    {"first_utc", "last_utc", "missing_5m_gaps", "path", "requests", "rows", "synthetic_rows"},
)
_MARKET_MANIFEST_KEY_SHAPES: Final = (
    _MARKET_MANIFEST_REQUIRED_KEYS,
    _MARKET_MANIFEST_REQUIRED_KEYS | {"max_gap_minutes"},
)


def validate_manifest(path: Path) -> Tuple[Tuple[str, Path], ...]:
    """Require the exact real-data manifest before checking safe source paths."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise EvaluationInputError("invalid manifest") from error
    if not isinstance(payload, dict):
        raise EvaluationInputError("invalid manifest")
    manifest_keys = set(payload)
    if not _MANIFEST_REQUIRED_KEYS.issubset(manifest_keys):
        raise EvaluationInputError("manifest is missing required top-level keys")
    if manifest_keys - _MANIFEST_REQUIRED_KEYS - _MANIFEST_OPTIONAL_KEYS:
        raise EvaluationInputError("manifest has unknown top-level keys")
    if type(payload["synthetic_rows"]) is not int or payload["synthetic_rows"] != 0:
        raise EvaluationInputError("manifest synthetic_rows must be integer zero")
    market_payload = payload["markets"]
    if not isinstance(market_payload, dict) or set(market_payload) != set(MARKETS):
        raise EvaluationInputError("manifest must contain exactly eight fixed markets")
    for market in MARKETS:
        item = market_payload[market]
        if not isinstance(item, dict) or set(item) not in _MARKET_MANIFEST_KEY_SHAPES:
            raise EvaluationInputError("manifest has invalid market keys: " + market)
        if not isinstance(item["path"], str):
            raise EvaluationInputError("manifest path is not text: " + market)
        if type(item["synthetic_rows"]) is not int or item["synthetic_rows"] != 0:
            raise EvaluationInputError("manifest synthetic_rows must be integer zero: " + market)
    try:
        return _validate_manifest(path)
    except EvaluationInputError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise EvaluationInputError("invalid manifest") from error


@dataclass(frozen=True)
class ContrarianConfig:  # noqa: SLOTS_OK - Python 3.8 compatibility
    """Fixed evaluation parameters for the contrarian bounce candidate."""

    momentum_lookback: int = 36
    hold_bars: int = 48
    btc_gate_lookback: int = 72
    btc_gate_threshold: float = 0.0
    breadth_min: int = 5
    selected_return_max: float = -0.005
    stop_loss_pct: float = 0.03
    exposure: float = 0.50
    fee: float = 0.0005
    spread: float = 0.0003
    slippage: float = 0.0002

    def __post_init__(self) -> None:
        if self.momentum_lookback <= 0 or self.hold_bars <= 0 or self.btc_gate_lookback <= 0:
            raise EvaluationInputError("lookback and holding bars must be positive")
        if not all(
            isfinite(value)
            for value in (
                self.btc_gate_threshold,
                self.selected_return_max,
                self.stop_loss_pct,
                self.exposure,
                self.fee,
                self.spread,
                self.slippage,
            )
        ):
            raise EvaluationInputError("configuration floats must be finite")
        if not 1 <= self.breadth_min <= len(MARKETS):
            raise EvaluationInputError("breadth_min must be between one and eight")
        if not 0.0 <= self.exposure <= 1.0:
            raise EvaluationInputError("exposure must be between zero and one")
        if self.stop_loss_pct < 0.0 or self.fee < 0.0 or self.spread < 0.0 or self.slippage < 0.0:
            raise EvaluationInputError("stop and cost rates must be non-negative")
        if self.one_side_cost >= 1.0:
            raise EvaluationInputError("one-sided cost must be less than one")

    @property
    def one_side_cost(self) -> float:
        """Return the fixed fee, spread, and slippage for one side."""
        return self.fee + self.spread + self.slippage


@dataclass(frozen=True)
class EvaluationWindow:  # noqa: SLOTS_OK - Python 3.8 compatibility
    """A UTC half-open evaluation window."""

    start: Optional[datetime] = None
    end: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise EvaluationInputError("evaluation window must be half-open and ordered")


@dataclass(frozen=True)
class TradeRecord:  # noqa: SLOTS_OK - Python 3.8 compatibility
    """One sequential position with decision and cost audit fields."""

    market: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    exit_reason: str
    selected_return: float
    btc_return: float
    breadth_positive: int
    gross_return: float
    net_return: float
    portfolio_return: float


@dataclass(frozen=True)
class BacktestResult:  # noqa: SLOTS_OK - Python 3.8 compatibility
    """Compounded evaluation result and its complete sequential trades."""

    total_return: float
    max_drawdown: float
    trades: int
    winning_trades: int
    trade_records: Tuple[TradeRecord, ...]


def _select_market(
    data: AlignedMarketData,
    index: int,
    config: ContrarianConfig,
) -> Optional[Tuple[int, float, float, int]]:
    """Return the lowest-return market when both gates permit a trade."""
    returns = tuple(
        closes[index] / closes[index - config.momentum_lookback] - 1.0
        for closes in data.closes
    )
    btc_index = data.markets.index("KRW-BTC")
    btc_closes = data.closes[btc_index]
    btc_return = btc_closes[index] / btc_closes[index - config.btc_gate_lookback] - 1.0
    breadth_positive = sum(value > 0.0 for value in returns)
    if btc_return <= config.btc_gate_threshold or breadth_positive < config.breadth_min:
        return None
    selected_index = min(range(len(returns)), key=lambda item: (returns[item], item))
    selected_return = returns[selected_index]
    if selected_return > config.selected_return_max:
        return None
    return selected_index, selected_return, btc_return, breadth_positive


def _net_return(entry_price: float, exit_price: float, side_cost: float) -> float:
    """Apply fixed costs at entry and exit to a price return."""
    return exit_price * (1.0 - side_cost) / (entry_price * (1.0 + side_cost)) - 1.0


def run_portfolio(
    data: AlignedMarketData,
    config: ContrarianConfig,
    window: Optional[EvaluationWindow] = None,
) -> BacktestResult:
    """Run a non-overlapping, evaluation-only portfolio on common real candles."""
    if data.markets != MARKETS:
        raise EvaluationInputError("evaluation requires the fixed eight-market universe")
    first_index = max(config.momentum_lookback, config.btc_gate_lookback)
    last_entry = len(data.timestamps) - config.hold_bars
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    records: List[TradeRecord] = []
    index = first_index
    while index < last_entry:
        timestamp = data.timestamps[index]
        if window is not None and window.start is not None and timestamp < window.start:
            index += 1
            continue
        if window is not None and window.end is not None and timestamp >= window.end:
            break
        selection = _select_market(data, index, config)
        if selection is None:
            index += 1
            continue
        market_index, selected_return, btc_return, breadth_positive = selection
        exit_index = index + config.hold_bars
        entry_price = data.closes[market_index][index]
        exit_price = data.closes[market_index][exit_index]
        exit_reason = "time"
        if config.stop_loss_pct > 0.0:
            stop_price = entry_price * (1.0 - config.stop_loss_pct)
            for probe in range(index + 1, exit_index + 1):
                if data.lows[market_index][probe] <= stop_price:
                    exit_index, exit_price, exit_reason = probe, stop_price, "stop"
                    break
        if window is not None and window.end is not None and data.timestamps[exit_index] >= window.end:
            index += 1
            continue
        gross_return = exit_price / entry_price - 1.0
        net_return = _net_return(entry_price, exit_price, config.one_side_cost)
        portfolio_return = config.exposure * net_return
        equity *= 1.0 + portfolio_return
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
        records.append(
            TradeRecord(
                data.markets[market_index],
                timestamp,
                data.timestamps[exit_index],
                entry_price,
                exit_price,
                exit_reason,
                selected_return,
                btc_return,
                breadth_positive,
                gross_return,
                net_return,
                portfolio_return,
            ),
        )
        index = exit_index + 1
    return BacktestResult(
        equity - 1.0,
        max_drawdown,
        len(records),
        sum(record.net_return > 0.0 for record in records),
        tuple(records),
    )
