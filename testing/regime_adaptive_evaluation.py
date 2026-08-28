from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Callable, Final, List, Mapping, Optional, Tuple

from testing.cross_sectional_momentum_evaluation import (
    AlignedMarketData,
    EvaluationInputError,
    MARKETS,
)
from testing.regime_adaptive_models import (
    STRATEGY_BY_REGIME,
    EvaluationWindow,
    Regime,
    RegimeAdaptiveConfig,
    RegimeAdaptiveResult,
    RegimeCount,
    Strategy,
    StrategySummary,
    TradeRecord,
)


_Returns = Tuple[float, ...]
_Selector = Callable[[_Returns, int, RegimeAdaptiveConfig], Optional[int]]
_REGIMES: Final[Tuple[Regime, ...]] = (Regime.BULL, Regime.SIDEWAYS, Regime.BEAR)
_STRATEGIES: Final[Tuple[Strategy, ...]] = (
    Strategy.MOMENTUM,
    Strategy.CONTRARIAN,
    Strategy.CASH,
)


def classify_regime(btc_return: float, config: RegimeAdaptiveConfig) -> Regime:
    """Classify one completed BTC return using inclusive configured bounds."""
    if btc_return >= config.bull_threshold:
        return Regime.BULL
    if btc_return <= config.bear_threshold:
        return Regime.BEAR
    return Regime.SIDEWAYS


def strategy_for(regime: Regime) -> Strategy:
    """Return the explicit strategy mapped to a BTC regime."""
    return STRATEGY_BY_REGIME[regime]


def _best_index(returns: _Returns, highest: bool) -> int:
    best_index = 0
    for index in range(1, len(returns)):
        better = returns[index] > returns[best_index] if highest else returns[index] < returns[best_index]
        if better:
            best_index = index
    return best_index


def _select_momentum(
    returns: _Returns, _breadth: int, _config: RegimeAdaptiveConfig,
) -> Optional[int]:
    selected = _best_index(returns, True)
    return selected if returns[selected] > 0.0 else None


def _select_contrarian(
    returns: _Returns, breadth: int, config: RegimeAdaptiveConfig,
) -> Optional[int]:
    selected = _best_index(returns, False)
    if breadth < config.breadth_min or returns[selected] > config.selected_return_max:
        return None
    return selected


def _select_cash(
    _returns: _Returns, _breadth: int, _config: RegimeAdaptiveConfig,
) -> Optional[int]:
    return None


_SELECTOR_BY_STRATEGY: Final[Mapping[Strategy, _Selector]] = {
    Strategy.MOMENTUM: _select_momentum,
    Strategy.CONTRARIAN: _select_contrarian,
    Strategy.CASH: _select_cash,
}


def _validate_data(
    data: AlignedMarketData, config: RegimeAdaptiveConfig, window: EvaluationWindow,
) -> None:
    if data.markets != MARKETS:
        raise EvaluationInputError("data must contain the fixed eight-market universe in order")
    if not data.timestamps:
        raise EvaluationInputError("aligned market data must not be empty")
    if len(data.closes) != len(MARKETS) or len(data.lows) != len(MARKETS):
        raise EvaluationInputError("close and low dimensions must match the market universe")
    previous: Optional[datetime] = None
    for timestamp in data.timestamps:
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise EvaluationInputError("market timestamps must be UTC")
        if previous is not None and timestamp <= previous:
            raise EvaluationInputError("market timestamps must be strictly increasing")
        previous = timestamp
    for closes, lows in zip(data.closes, data.lows):
        if len(closes) != len(data.timestamps) or len(lows) != len(data.timestamps):
            raise EvaluationInputError("market rows must have equal dimensions")
        for close, low in zip(closes, lows):
            if not isfinite(close) or not isfinite(low) or close <= 0.0 or low <= 0.0:
                raise EvaluationInputError("market close and low values must be finite and positive")
            if low > close:
                raise EvaluationInputError("market low must not exceed close")
    first_index = max(config.regime_lookback, config.momentum_lookback)
    if first_index >= len(data.timestamps):
        raise EvaluationInputError("market data does not contain sufficient evaluation history")


def _returns_at(data: AlignedMarketData, index: int, lookback: int) -> _Returns:
    return tuple(
        closes[index] / closes[index - lookback] - 1.0
        for closes in data.closes
    )


def _portfolio_sum(
    records: Tuple[TradeRecord, ...],
    regime: Optional[Regime] = None,
    strategy: Optional[Strategy] = None,
) -> float:
    return sum(
        record.portfolio_return
        for record in records
        if (regime is None or record.regime is regime)
        and (strategy is None or record.strategy is strategy)
    )


def _regime_counts(labels: Tuple[Regime, ...], records: Tuple[TradeRecord, ...]) -> Tuple[RegimeCount, ...]:
    return tuple(
        RegimeCount(
            regime,
            sum(label is regime for label in labels),
            sum(record.regime is regime for record in records),
            _portfolio_sum(records, regime=regime),
        )
        for regime in _REGIMES
    )


def _strategy_summaries(records: Tuple[TradeRecord, ...]) -> Tuple[StrategySummary, ...]:
    return tuple(
        StrategySummary(
            strategy,
            sum(record.strategy is strategy for record in records),
            sum(record.strategy is strategy and record.net_return > 0.0 for record in records),
            _portfolio_sum(records, strategy=strategy),
        )
        for strategy in _STRATEGIES
    )


def run_evaluation(
    data: AlignedMarketData, config: RegimeAdaptiveConfig, window: EvaluationWindow,
) -> RegimeAdaptiveResult:
    """Evaluate one fixed universe through a sequential, non-overlapping path."""
    _validate_data(data, config, window)
    btc_index = MARKETS.index("KRW-BTC")
    first_index = max(config.regime_lookback, config.momentum_lookback)
    labels: List[Regime] = []
    for index in range(first_index, len(data.timestamps)):
        timestamp = data.timestamps[index]
        if window.start <= timestamp < window.end:
            btc_return = (
                data.closes[btc_index][index]
                / data.closes[btc_index][index - config.regime_lookback]
                - 1.0
            )
            labels.append(classify_regime(btc_return, config))

    equity, peak, max_drawdown = 1.0, 1.0, 0.0
    records: List[TradeRecord] = []
    index = first_index
    while index < len(data.timestamps):
        timestamp = data.timestamps[index]
        if timestamp < window.start:
            index += 1
            continue
        if timestamp >= window.end:
            break
        btc_return = (
            data.closes[btc_index][index]
            / data.closes[btc_index][index - config.regime_lookback]
            - 1.0
        )
        regime = classify_regime(btc_return, config)
        strategy = strategy_for(regime)
        returns = _returns_at(data, index, config.momentum_lookback)
        breadth = sum(value > 0.0 for value in returns)
        selected_index = _SELECTOR_BY_STRATEGY[strategy](returns, breadth, config)
        exit_index = index + config.hold_bars
        if selected_index is None or exit_index >= len(data.timestamps):
            index += 1
            continue
        if data.timestamps[exit_index] >= window.end:
            index += 1
            continue
        entry_price = data.closes[selected_index][index]
        exit_price = data.closes[selected_index][exit_index]
        exit_reason = "time"
        if config.stop_loss_pct > 0.0:
            stop_price = entry_price * (1.0 - config.stop_loss_pct)
            for probe in range(index + 1, exit_index + 1):
                if data.lows[selected_index][probe] <= stop_price:
                    exit_index, exit_price, exit_reason = probe, stop_price, "stop"
                    break
        gross_return = exit_price / entry_price - 1.0
        net_return = (
            exit_price * (1.0 - config.one_side_cost)
            / (entry_price * (1.0 + config.one_side_cost))
            - 1.0
        )
        portfolio_return = config.exposure * net_return
        equity *= 1.0 + portfolio_return
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
        records.append(TradeRecord(
            data.markets[selected_index],
            regime,
            strategy,
            timestamp,
            data.timestamps[exit_index],
            entry_price,
            exit_price,
            gross_return,
            net_return,
            portfolio_return,
            btc_return,
            breadth,
            exit_reason,
        ))
        index = exit_index + 1
    record_tuple = tuple(records)
    label_tuple = tuple(labels)
    return RegimeAdaptiveResult(
        equity - 1.0,
        max_drawdown,
        record_tuple,
        label_tuple,
        _regime_counts(label_tuple, record_tuple),
        _strategy_summaries(record_tuple),
    )
