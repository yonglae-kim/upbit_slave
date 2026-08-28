from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from testing.cross_sectional_momentum_evaluation import (
    AlignedMarketData,
    Candle,
    EvaluationInputError,
    align_series,
)
from testing.regime_adaptive_evaluation import (
    EvaluationWindow,
    Regime,
    RegimeAdaptiveConfig,
    Strategy,
    classify_regime,
    run_evaluation,
    strategy_for,
)
from testing.regime_adaptive_models import (
    EvaluationWindow as ModelEvaluationWindow,
    RegimeAdaptiveConfig as ModelRegimeAdaptiveConfig,
)


MARKETS = (
    "KRW-ADA", "KRW-AVAX", "KRW-BTC", "KRW-DOGE",
    "KRW-ETH", "KRW-LINK", "KRW-SOL", "KRW-XRP",
)


def _candles(closes: List[float], lows: Optional[List[float]] = None) -> Tuple[Candle, ...]:
    """Build deterministic UTC candle fixtures."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    low_values = closes if lows is None else lows
    return tuple(
        Candle(start + timedelta(minutes=5 * index), close, low_values[index])
        for index, close in enumerate(closes)
    )


def _aligned(
    close_rows: Tuple[List[float], ...], low_rows: Optional[Tuple[List[float], ...]] = None,
) -> AlignedMarketData:
    """Build the fixed universe from common timestamps."""
    lows = close_rows if low_rows is None else low_rows
    return align_series(tuple(
        (market, _candles(closes, low_values))
        for market, closes, low_values in zip(MARKETS, close_rows, lows)
    ))


def _config(**overrides: float) -> RegimeAdaptiveConfig:
    """Return a short deterministic configuration for unit scenarios."""
    values = {
        "regime_lookback": 1,
        "bull_threshold": 0.03,
        "bear_threshold": -0.03,
        "momentum_lookback": 1,
        "hold_bars": 1,
        "breadth_min": 5,
        "selected_return_max": -0.005,
        "stop_loss_pct": 0.03,
        "exposure": 0.50,
        "fee": 0.0005,
        "spread": 0.0003,
        "slippage": 0.0002,
    }
    values.update(overrides)
    return RegimeAdaptiveConfig(**values)


def _window(data: AlignedMarketData) -> EvaluationWindow:
    """Cover every fixture candle in a UTC half-open window."""
    return EvaluationWindow(data.timestamps[0], data.timestamps[-1] + timedelta(minutes=5))


class TestRegimeAdaptiveEvaluation(unittest.TestCase):
    def test_direct_model_imports_preserve_python_38_slots_and_defaults(self) -> None:
        # Given: the model classes are imported directly from their defining module.
        window = ModelEvaluationWindow(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        )
        config = ModelRegimeAdaptiveConfig()

        # When: the default model instances are inspected.
        # Then: Python 3.8-compatible slots are present and the default is retained.
        self.assertFalse(hasattr(window, "__dict__"))
        self.assertFalse(hasattr(config, "__dict__"))
        self.assertEqual(config.regime_lookback, 288)

    def test_threshold_boundaries_and_explicit_strategy_mapping(self) -> None:
        # Given: inclusive bull/bear boundaries and one interior BTC return.
        config = _config()

        # When: completed BTC returns are classified and routed.
        routed = tuple(
            (classify_regime(value, config), strategy_for(classify_regime(value, config)))
            for value in (0.03, 0.0, -0.03)
        )

        # Then: exact boundaries are bull/bear and the interior is sideways.
        self.assertEqual(routed, (
            (Regime.BULL, Strategy.MOMENTUM),
            (Regime.SIDEWAYS, Strategy.CONTRARIAN),
            (Regime.BEAR, Strategy.CASH),
        ))

    def test_invalid_thresholds_and_insufficient_history_fail_closed(self) -> None:
        # Given: overlapping/nonfinite thresholds and no completed lookback bar.
        with self.assertRaises(EvaluationInputError):
            RegimeAdaptiveConfig(bull_threshold=-0.03, bear_threshold=0.03)
        with self.assertRaises(EvaluationInputError):
            RegimeAdaptiveConfig(bull_threshold=float("nan"))
        data = _aligned(tuple([100.0, 101.0] for _ in MARKETS))

        # When: evaluation needs a lookback longer than the available history.
        # Then: it rejects the input before producing a misleading cash result.
        with self.assertRaises(EvaluationInputError):
            run_evaluation(data, _config(regime_lookback=2), _window(data))

    def test_bear_regime_is_cash_with_zero_trades(self) -> None:
        # Given: BTC is at or below the bear boundary at every completed decision.
        rows = tuple([100.0, 97.0, 94.0, 91.0] for _ in MARKETS)
        data = _aligned(rows)

        # When: the sequential evaluator runs the bear-only fixture.
        result = run_evaluation(data, _config(), _window(data))

        # Then: all decisions are cash and no position is opened.
        self.assertEqual(result.regime_labels, (Regime.BEAR, Regime.BEAR, Regime.BEAR))
        self.assertEqual(result.trades, 0)
        cash = next(item for item in result.strategy_summaries if item.strategy is Strategy.CASH)
        self.assertEqual(cash.trades, 0)

    def test_sideways_routes_to_contrarian_bounce(self) -> None:
        # Given: sideways BTC, six positive markets, and ADA as the largest loser.
        rows = (
            [100.0, 98.0, 99.0, 99.0],
            [100.0, 101.0, 101.0, 101.0],
            [100.0, 100.0, 100.0, 100.0],
            [100.0, 101.0, 101.0, 101.0],
            [100.0, 101.0, 101.0, 101.0],
            [100.0, 101.0, 101.0, 101.0],
            [100.0, 101.0, 101.0, 101.0],
            [100.0, 101.0, 101.0, 101.0],
        )
        data = _aligned(rows)

        # When: the sideways decision is evaluated.
        result = run_evaluation(data, _config(stop_loss_pct=0.0), _window(data))

        # Then: the lowest-return market is selected by the contrarian route.
        self.assertEqual(result.trades, 1)
        trade = result.trade_records[0]
        self.assertEqual(trade.regime, Regime.SIDEWAYS)
        self.assertEqual(trade.strategy, Strategy.CONTRARIAN)
        self.assertEqual(trade.market, "KRW-ADA")
        self.assertEqual(trade.breadth, 6)

    def test_shared_costs_exposure_and_sequential_compounding(self) -> None:
        # Given: two non-overlapping bull trades on one shared equity path.
        rows = (
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 104.0, 108.0, 112.0, 116.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 110.0, 121.0, 133.1, 146.41],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
        )
        data = _aligned(rows)
        config = _config(stop_loss_pct=0.0)

        # When: both trades are compounded with exposure and fixed two-sided costs.
        result = run_evaluation(data, config, _window(data))
        side_cost = config.fee + config.spread + config.slippage
        expected_net = 110.0 * (1.0 - side_cost) / (100.0 * (1.0 + side_cost)) - 1.0

        # Then: costs apply on both sides and total return is sequential, not summed.
        self.assertEqual(result.trades, 2)
        self.assertEqual(result.trade_records[0].entry_time, data.timestamps[1])
        self.assertEqual(result.trade_records[0].exit_time, data.timestamps[2])
        self.assertAlmostEqual(result.trade_records[0].net_return, expected_net)
        self.assertAlmostEqual(result.trade_records[0].portfolio_return, 0.5 * expected_net)
        self.assertAlmostEqual(result.total_return, (1.0 + 0.5 * expected_net) ** 2 - 1.0)
        self.assertNotAlmostEqual(result.total_return, 2.0 * 0.5 * expected_net)

    def test_stop_uses_real_future_low_and_outputs_are_finite(self) -> None:
        # Given: a bull entry whose next real low crosses the stop price.
        closes = tuple(
            [100.0, 105.0, 105.0, 105.0] if market == "KRW-ADA" else [100.0, 104.0, 104.0, 104.0]
            for market in MARKETS
        )
        lows = list(closes)
        lows[0] = [100.0, 100.0, 96.0, 100.0]
        data = _aligned(closes, tuple(lows))

        # When: the evaluator scans real low prices through the holding bar.
        result = run_evaluation(data, _config(exposure=1.0), _window(data))
        trade = result.trade_records[0]

        # Then: stop exit and every returned numeric field are finite and auditable.
        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit_time, data.timestamps[2])
        self.assertEqual(trade.exit_price, 101.85)
        numeric_values = (
            result.total_return, result.max_drawdown, trade.entry_price, trade.exit_price,
            trade.gross_return, trade.net_return, trade.portfolio_return, trade.btc_return,
        )
        self.assertTrue(all(math.isfinite(value) for value in numeric_values))

    def test_selection_uses_decision_prices_without_overlap(self) -> None:
        # Given: a future ETH spike that must not influence the earlier ADA selection.
        rows = (
            [100.0, 104.0, 104.0, 108.0, 108.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 103.5, 107.0, 110.5, 114.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 100.0, 200.0, 100.0, 100.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0, 100.0, 100.0],
        )
        data = _aligned(rows)

        # When: the evaluator makes sequential one-bar decisions.
        result = run_evaluation(data, _config(stop_loss_pct=0.0, exposure=1.0), _window(data))

        # Then: the first trade uses ADA's completed return, and trades never overlap.
        self.assertGreaterEqual(result.trades, 2)
        first, second = result.trade_records[:2]
        self.assertEqual(first.market, "KRW-ADA")
        self.assertEqual(first.entry_time, data.timestamps[1])
        self.assertEqual(first.entry_price, 104.0)
        self.assertGreaterEqual(second.entry_time, first.exit_time)


if __name__ == "__main__":
    unittest.main()
