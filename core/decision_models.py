from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


Candle = Dict[str, Any]
SnapshotState = Dict[str, Any]


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    candles_by_timeframe: dict[str, list[Candle]] = field(default_factory=dict)
    price: float | None = None
    diagnostics: SnapshotState = field(default_factory=dict)


@dataclass(frozen=True)
class PositionSnapshot:
    market: str | None = None
    quantity: float = 0.0
    entry_price: float | None = None
    state: SnapshotState = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioSnapshot:
    available_krw: float
    open_positions: int = 0
    state: SnapshotState = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionContext:
    strategy_name: str
    market: MarketSnapshot
    position: PositionSnapshot
    portfolio: PortfolioSnapshot
    diagnostics: SnapshotState = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionIntent:
    action: str
    reason: str
    diagnostics: SnapshotState = field(default_factory=dict)
    next_position_state: SnapshotState = field(default_factory=dict)


@dataclass(frozen=True)
class StrategySignal:
    accepted: bool
    reason: str
    diagnostics: SnapshotState = field(default_factory=dict)
