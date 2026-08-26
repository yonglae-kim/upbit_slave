from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence, Tuple

from testing.cross_sectional_contrarian_evaluation import (
    MARKETS,
    Candle,
    ContrarianConfig,
    EvaluationInputError,
    EvaluationWindow,
    align_series,
    run_portfolio,
)


def _candles(closes: Sequence[float], lows: Optional[Sequence[float]] = None) -> Tuple[Candle, ...]:
    selected_lows = tuple(closes) if lows is None else tuple(lows)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        Candle(start + timedelta(minutes=5 * index), close, selected_lows[index])
        for index, close in enumerate(closes)
    )


def _assets(
    rows: Tuple[Sequence[float], ...],
    lows: Optional[Tuple[Sequence[float], ...]] = None,
) -> Tuple[Tuple[str, Tuple[Candle, ...]], ...]:
    input_order = (1, 2, 0, 3, 4, 5, 6, 7)  # BTC, ADA, AVAX, then the remaining fixed markets.
    return tuple(
        (
            market,
            _candles(
                rows[input_order[index]],
                None if lows is None else lows[input_order[index]],
            ),
        )
        for index, market in enumerate(MARKETS)
    )


class TestCrossSectionalContrarianEvaluation(unittest.TestCase):
    def test_selects_lowest_return_when_btc_and_breadth_gates_pass(self) -> None:
        rows = (
            (100.0, 100.0, 102.0, 102.0),
            (100.0, 100.0, 90.0, 90.0),
            (100.0, 100.0, 102.0, 102.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 99.0, 99.0),
            (100.0, 100.0, 100.0, 100.0),
        )
        result = run_portfolio(
            align_series(_assets(rows)),
            ContrarianConfig(momentum_lookback=2, hold_bars=1, btc_gate_lookback=2, fee=0.0, spread=0.0, slippage=0.0),
        )

        self.assertEqual(result.trades, 1)
        self.assertEqual(result.trade_records[0].market, "KRW-ADA")
        self.assertAlmostEqual(result.trade_records[0].selected_return, -0.10, places=7)
        self.assertAlmostEqual(result.trade_records[0].btc_return, 0.02, places=7)
        self.assertEqual(result.trade_records[0].breadth_positive, 5)

    def test_btc_gate_uses_its_own_lookback(self) -> None:
        rows = (
            (100.0, 105.0, 110.0, 110.0),
            (100.0, 100.0, 90.0, 90.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
        )

        result = run_portfolio(
            align_series(_assets(rows)),
            ContrarianConfig(
                momentum_lookback=1,
                hold_bars=1,
                btc_gate_lookback=2,
                btc_gate_threshold=0.08,
                breadth_min=1,
                fee=0.0,
                spread=0.0,
                slippage=0.0,
            ),
        )

        self.assertEqual(result.trades, 1)
        self.assertEqual(result.trade_records[0].market, "KRW-ADA")
        self.assertAlmostEqual(result.trade_records[0].btc_return, 0.10, places=7)

    def test_config_rejects_non_finite_float_values(self) -> None:
        for field in (
            "btc_gate_threshold",
            "selected_return_max",
            "stop_loss_pct",
            "exposure",
            "fee",
            "spread",
            "slippage",
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(EvaluationInputError, "configuration floats must be finite"):
                    ContrarianConfig(**{field: float("nan")})

    def test_btc_gate_blocks_when_btc_return_is_not_strictly_positive(self) -> None:
        rows = (
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.0, 90.0, 90.0),
            (100.0, 100.0, 102.0, 102.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 99.0, 99.0),
            (100.0, 100.0, 100.0, 100.0),
        )

        result = run_portfolio(
            align_series(_assets(rows)),
            ContrarianConfig(momentum_lookback=2, hold_bars=1, btc_gate_lookback=2, fee=0.0, spread=0.0, slippage=0.0),
        )

        self.assertEqual(result.trades, 0)

    def test_breadth_gate_blocks_when_fewer_than_five_returns_are_positive(self) -> None:
        rows = (
            (100.0, 100.0, 102.0, 102.0),
            (100.0, 100.0, 90.0, 90.0),
            (100.0, 100.0, 102.0, 102.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 101.0, 101.0),
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.0, 99.0, 99.0),
            (100.0, 100.0, 100.0, 100.0),
        )

        result = run_portfolio(
            align_series(_assets(rows)),
            ContrarianConfig(momentum_lookback=2, hold_bars=1, btc_gate_lookback=2, fee=0.0, spread=0.0, slippage=0.0),
        )

        self.assertEqual(result.trades, 0)

    def test_real_low_stop_then_two_sided_cost_and_exposure_are_applied(self) -> None:
        rows = (
            (100.0, 110.0, 110.0, 110.0),
            (100.0, 90.0, 90.0, 90.0),
            (100.0, 110.0, 110.0, 110.0),
            (100.0, 105.0, 105.0, 105.0),
            (100.0, 105.0, 105.0, 105.0),
            (100.0, 105.0, 105.0, 105.0),
            (100.0, 95.0, 95.0, 95.0),
            (100.0, 100.0, 100.0, 100.0),
        )
        lows = tuple(rows[index] if index != 1 else (100.0, 90.0, 80.0, 90.0) for index in range(8))
        config = ContrarianConfig(
            momentum_lookback=1,
            hold_bars=2,
            btc_gate_lookback=1,
            stop_loss_pct=0.10,
            exposure=0.50,
            fee=0.001,
            spread=0.002,
            slippage=0.003,
        )

        result = run_portfolio(align_series(_assets(rows, lows)), config)

        side_cost = config.fee + config.spread + config.slippage
        net_return = 81.0 * (1.0 - side_cost) / (90.0 * (1.0 + side_cost)) - 1.0
        trade = result.trade_records[0]
        self.assertEqual(result.trades, 1)
        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit_price, 81.0)
        self.assertAlmostEqual(trade.net_return, net_return, places=7)
        self.assertAlmostEqual(trade.portfolio_return, net_return * 0.50, places=7)
        self.assertAlmostEqual(result.total_return, net_return * 0.50, places=7)

    def test_window_is_half_open_at_entry_timestamp(self) -> None:
        rows = (
            (100.0, 99.0, 101.0, 102.0, 102.0),
            (100.0, 100.0, 90.0, 90.0, 90.0),
            (100.0, 100.0, 102.0, 103.0, 103.0),
            (100.0, 100.0, 101.0, 102.0, 102.0),
            (100.0, 100.0, 101.0, 102.0, 102.0),
            (100.0, 100.0, 101.0, 102.0, 102.0),
            (100.0, 100.0, 99.0, 99.0, 99.0),
            (100.0, 100.0, 100.0, 100.0, 100.0),
        )
        data = align_series(_assets(rows))
        config = ContrarianConfig(momentum_lookback=2, hold_bars=1, btc_gate_lookback=2, fee=0.0, spread=0.0, slippage=0.0)

        excluded = run_portfolio(data, config, EvaluationWindow(end=data.timestamps[2]))
        included = run_portfolio(data, config, EvaluationWindow(end=data.timestamps[4]))

        self.assertEqual(excluded.trades, 0)
        self.assertEqual(included.trades, 1)
        self.assertEqual(included.trade_records[0].entry_time, data.timestamps[2])

    def test_window_excludes_trade_exiting_at_window_end(self) -> None:
        rows = (
            (100.0, 99.0, 101.0, 102.0),
            (100.0, 100.0, 90.0, 90.0),
            (100.0, 100.0, 102.0, 103.0),
            (100.0, 100.0, 101.0, 102.0),
            (100.0, 100.0, 101.0, 102.0),
            (100.0, 100.0, 101.0, 102.0),
            (100.0, 100.0, 99.0, 99.0),
            (100.0, 100.0, 100.0, 100.0),
        )
        data = align_series(_assets(rows))
        config = ContrarianConfig(momentum_lookback=2, hold_bars=1, btc_gate_lookback=2, fee=0.0, spread=0.0, slippage=0.0)

        result = run_portfolio(data, config, EvaluationWindow(end=data.timestamps[3]))

        self.assertEqual(result.trades, 0)

    def test_trades_do_not_overlap_or_use_future_selection_prices(self) -> None:
        rows = (
            (100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0),
            (100.0, 90.0, 80.0, 80.0, 70.0, 70.0, 70.0),
            (100.0,) * 7,
            (100.0,) * 7,
            (100.0,) * 7,
            (100.0,) * 7,
            (100.0,) * 7,
            (100.0,) * 7,
        )
        data = align_series(_assets(rows))
        config = ContrarianConfig(
            momentum_lookback=1,
            hold_bars=2,
            btc_gate_lookback=1,
            breadth_min=1,
            stop_loss_pct=0.0,
            fee=0.0,
            spread=0.0,
            slippage=0.0,
        )

        result = run_portfolio(data, config)

        self.assertEqual(result.trades, 2)
        self.assertEqual(
            tuple(record.entry_time for record in result.trade_records),
            (data.timestamps[1], data.timestamps[4]),
        )
        self.assertAlmostEqual(result.trade_records[0].selected_return, -0.10, places=7)

if __name__ == "__main__":
    unittest.main()
