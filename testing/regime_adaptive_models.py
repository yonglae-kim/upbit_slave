from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from typing import Final, Mapping, Tuple

from testing.cross_sectional_momentum_evaluation import MARKETS, EvaluationInputError


class Regime(str, Enum):
    """BTC state used to select one evaluation-only strategy."""

    BULL = "bull"
    SIDEWAYS = "sideways"
    BEAR = "bear"


class Strategy(str, Enum):
    """Strategy selected by a portfolio regime."""

    MOMENTUM = "cross_sectional_momentum"
    CONTRARIAN = "cross_sectional_contrarian_bounce"
    CASH = "cash_defensive"


@dataclass(frozen=True)  # noqa: SLOTS_OK - Python 3.8 compatibility
class EvaluationWindow:
    """Timezone-aware UTC half-open evaluation window."""

    __slots__ = ("start", "end")
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise EvaluationInputError("evaluation window timestamps must include UTC")
        if self.start.utcoffset() != timedelta(0) or self.end.utcoffset() != timedelta(0):
            raise EvaluationInputError("evaluation window timestamps must be UTC")
        if self.start >= self.end:
            raise EvaluationInputError("evaluation window must be half-open and ordered")


@dataclass(frozen=True, init=False)  # noqa: SLOTS_OK - Python 3.8 compatibility
class RegimeAdaptiveConfig:
    """Validated parameters for the sequential regime router."""

    __slots__ = (
        "regime_lookback", "bull_threshold", "bear_threshold", "momentum_lookback",
        "hold_bars", "breadth_min", "selected_return_max", "stop_loss_pct", "exposure",
        "fee", "spread", "slippage",
    )
    regime_lookback: int
    bull_threshold: float
    bear_threshold: float
    momentum_lookback: int
    hold_bars: int
    breadth_min: int
    selected_return_max: float
    stop_loss_pct: float
    exposure: float
    fee: float
    spread: float
    slippage: float

    def __init__(
        self,
        regime_lookback: int = 288,
        bull_threshold: float = 0.03,
        bear_threshold: float = -0.03,
        momentum_lookback: int = 36,
        hold_bars: int = 48,
        breadth_min: int = 5,
        selected_return_max: float = -0.005,
        stop_loss_pct: float = 0.03,
        exposure: float = 0.50,
        fee: float = 0.0005,
        spread: float = 0.0003,
        slippage: float = 0.0002,
    ) -> None:
        object.__setattr__(self, "regime_lookback", regime_lookback)
        object.__setattr__(self, "bull_threshold", bull_threshold)
        object.__setattr__(self, "bear_threshold", bear_threshold)
        object.__setattr__(self, "momentum_lookback", momentum_lookback)
        object.__setattr__(self, "hold_bars", hold_bars)
        object.__setattr__(self, "breadth_min", breadth_min)
        object.__setattr__(self, "selected_return_max", selected_return_max)
        object.__setattr__(self, "stop_loss_pct", stop_loss_pct)
        object.__setattr__(self, "exposure", exposure)
        object.__setattr__(self, "fee", fee)
        object.__setattr__(self, "spread", spread)
        object.__setattr__(self, "slippage", slippage)
        self.__post_init__()

    def __post_init__(self) -> None:
        if min(self.regime_lookback, self.momentum_lookback, self.hold_bars) <= 0:
            raise EvaluationInputError("lookbacks and hold bars must be positive")
        if self.bull_threshold <= self.bear_threshold:
            raise EvaluationInputError("bull threshold must exceed bear threshold")
        rates = (self.bull_threshold, self.bear_threshold, self.selected_return_max,
                 self.stop_loss_pct, self.exposure, self.fee, self.spread, self.slippage)
        if any(not isfinite(value) for value in rates):
            raise EvaluationInputError("regime, risk, and cost values must be finite")
        if not 0 <= self.breadth_min <= len(MARKETS):
            raise EvaluationInputError("breadth minimum is outside the market universe")
        if self.selected_return_max > 0.0:
            raise EvaluationInputError("selected return maximum must be non-positive")
        if not 0.0 <= self.stop_loss_pct < 1.0:
            raise EvaluationInputError("stop loss must be within [0, 1)")
        if not 0.0 <= self.exposure <= 1.0:
            raise EvaluationInputError("exposure must be within [0, 1]")
        if any(value < 0.0 for value in (self.fee, self.spread, self.slippage)):
            raise EvaluationInputError("fee, spread, and slippage must be non-negative")

    @property
    def one_side_cost(self) -> float:
        """Return the common entry or exit cost rate."""
        return self.fee + self.spread + self.slippage


@dataclass(frozen=True)  # noqa: SLOTS_OK - Python 3.8 compatibility
class TradeRecord:
    """One non-overlapping trade on the shared portfolio path."""

    __slots__ = (
        "market", "regime", "strategy", "entry_time", "exit_time", "entry_price",
        "exit_price", "gross_return", "net_return", "portfolio_return", "btc_return",
        "breadth", "exit_reason",
    )
    market: str
    regime: Regime
    strategy: Strategy
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    gross_return: float
    net_return: float
    portfolio_return: float
    btc_return: float
    breadth: int
    exit_reason: str

    @property
    def reason(self) -> str:
        """Return the exit reason under the short legacy spelling."""
        return self.exit_reason


@dataclass(frozen=True)  # noqa: SLOTS_OK - Python 3.8 compatibility
class RegimeCount:
    """Decision-label and executed-trade aggregate for one regime."""

    __slots__ = ("regime", "labels", "trades", "portfolio_return")
    regime: Regime
    labels: int
    trades: int
    portfolio_return: float


@dataclass(frozen=True)  # noqa: SLOTS_OK - Python 3.8 compatibility
class StrategySummary:
    """Executed-trade aggregate for one strategy."""

    __slots__ = ("strategy", "trades", "winning_trades", "portfolio_return")
    strategy: Strategy
    trades: int
    winning_trades: int
    portfolio_return: float


@dataclass(frozen=True)  # noqa: SLOTS_OK - Python 3.8 compatibility
class RegimeAdaptiveResult:
    """Compounded portfolio result and auditable summaries."""

    __slots__ = (
        "total_return", "max_drawdown", "trade_records", "regime_labels", "regime_counts",
        "strategy_summaries",
    )
    total_return: float
    max_drawdown: float
    trade_records: Tuple[TradeRecord, ...]
    regime_labels: Tuple[Regime, ...]
    regime_counts: Tuple[RegimeCount, ...]
    strategy_summaries: Tuple[StrategySummary, ...]

    @property
    def trades(self) -> int:
        """Return the number of executed trades."""
        return len(self.trade_records)


STRATEGY_BY_REGIME: Final[Mapping[Regime, Strategy]] = {
    Regime.BULL: Strategy.MOMENTUM,
    Regime.SIDEWAYS: Strategy.CONTRARIAN,
    Regime.BEAR: Strategy.CASH,
}
