from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from openpyxl import Workbook

from testing.cross_sectional_momentum_evaluation import EvaluationInputError
from testing.regime_adaptive_runner import _load_market, _parse_utc, main


MANIFEST = Path("testing/artifacts/nfi_multi_3m_5m/manifest.json")
COMMON_ARGS = [
    "--manifest", str(MANIFEST),
    "--window-start", "2026-05-25T00:00:00Z",
    "--window-end", "2026-08-25T00:00:00Z",
    "--regime-lookback", "288",
    "--bull-threshold", "0.03",
    "--bear-threshold", "-0.03",
    "--momentum-lookback", "36",
    "--hold-bars", "48",
    "--breadth-min", "5",
    "--selected-return-max", "-0.005",
    "--stop-loss-pct", "0.03",
    "--exposure", "0.50",
    "--fee", "0.0005",
    "--spread", "0.0003",
    "--slippage", "0.0002",
]


class TestRegimeAdaptiveRunner(unittest.TestCase):
    def test_cli_emits_regime_adaptive_contract(self) -> None:
        # Given: the canonical fixed-universe manifest and real offline workbooks.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            stdout = io.StringIO()

            # When: the runner executes the complete offline CLI configuration.
            with redirect_stdout(stdout):
                exit_code = main(COMMON_ARGS + ["--output", str(output)])
            payload = json.loads(output.read_text(encoding="utf-8"))

        # Then: output is evaluation-only with every regime/strategy and finite metrics.
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["evaluation_only"])
        self.assertEqual(payload["strategy_by_regime"], {
            "bull": "cross_sectional_momentum",
            "sideways": "cross_sectional_contrarian_bounce",
            "bear": "cash_defensive",
        })
        self.assertEqual(set(payload["regime_counts"]), {"bull", "sideways", "bear"})
        self.assertEqual(set(payload["strategy_summaries"]), {
            "cross_sectional_momentum", "cross_sectional_contrarian_bounce", "cash_defensive",
        })
        self.assertTrue(math.isfinite(payload["total_return"]))
        self.assertTrue(math.isfinite(payload["max_drawdown"]))
        self.assertEqual(payload["regime_counts"]["bear"]["trades"], 0)
        self.assertEqual(json.loads(stdout.getvalue()), payload)

    def test_cli_rejects_reversed_or_offsetless_utc_window(self) -> None:
        # Given: malformed explicit UTC timestamps and a reversed half-open window.
        with self.assertRaises(EvaluationInputError):
            _parse_utc("2026-05-25T00:00:00")

        # When: the CLI constructs its ordered evaluation window.
        with self.assertRaises(EvaluationInputError):
            main(COMMON_ARGS + [
                "--output", "ignored.json",
                "--window-start", "2026-08-25T00:00:00Z",
                "--window-end", "2026-05-25T00:00:00Z",
                "--fee", "0.0005", "--spread", "0.0003", "--slippage", "0.0002",
            ])

        # Then: no data load or result is allowed for invalid boundaries.

    def test_workbook_rejects_nonfinite_candle_values(self) -> None:
        # Given: a workbook row with a non-finite low value.
        with tempfile.TemporaryDirectory(dir="testing/artifacts") as directory:
            source = Path(directory) / "invalid.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["candle_date_time_utc", "opening_price", "high_price", "low_price", "trade_price"])
            sheet.append(["2026-05-24T00:00:00Z", 100.0, 101.0, float("nan"), 100.0])
            workbook.save(source)
            workbook.close()

            # When: the runner loads the malformed workbook at its file boundary.
            with self.assertRaises(EvaluationInputError):
                _load_market("KRW-BTC", source)

        # Then: malformed candle values fail closed before alignment/evaluation.


if __name__ == "__main__":
    unittest.main()
