import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd
import types

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "slave_constants" not in sys.modules:
    sys.modules["slave_constants"] = types.SimpleNamespace(ACCESS_KEY="x", SECRET_KEY="y", SERVER_URL="https://api.upbit.com")

from testing.optimize_walkforward import ObjectiveThresholds, WalkForwardOptimizer


class OptimizeWalkForwardTest(unittest.TestCase):
    def test_score_segments_rejects_overfit_gap(self):
        with tempfile.TemporaryDirectory() as td:
            optimizer = WalkForwardOptimizer(
                market="KRW-BTC",
                path="unused.xlsx",
                result_csv_path=str(Path(td) / "results.csv"),
                thresholds=ObjectiveThresholds(min_trades=2, min_win_rate=30.0, max_overfit_gap_pct=5.0, max_efficiency_gap=1.0),
                max_candidates_per_phase=2,
            )

            df = pd.DataFrame(
                [
                    {"period_return": 20.0, "cagr": 30.0, "mdd": 8.0, "trades": 3, "win_rate": 55.0},
                    {"period_return": -10.0, "cagr": 4.0, "mdd": 12.0, "trades": 3, "win_rate": 40.0},
                ]
            )

            scored = optimizer._score_segments(df)

            self.assertFalse(scored["accepted"])
            self.assertEqual(scored["reject_reason"], "overfit_gap_too_large")
            self.assertGreater(scored["overfit_gap_pct"], 5.0)

    def test_optimize_saves_csv_and_pattern_doc(self):
        with tempfile.TemporaryDirectory() as td:
            result_csv = Path(td) / "opt_results.csv"
            pattern_doc = Path(td) / "patterns.md"
            optimizer = WalkForwardOptimizer(
                market="KRW-BTC",
                path="unused.xlsx",
                result_csv_path=str(result_csv),
                pattern_doc_path=str(pattern_doc),
                thresholds=ObjectiveThresholds(min_trades=1, min_win_rate=10.0, max_overfit_gap_pct=100.0, max_efficiency_gap=100.0),
                beam_width=1,
                max_candidates_per_phase=1,
            )

            def fake_run_single(*, params, report_path):
                return {
                    "objective_score": 99.0,
                    "accepted": True,
                    "reject_reason": "accepted",
                    "cagr_oos": 12.0,
                    "mdd_oos": 8.0,
                    "trades_oos": 10,
                    "win_rate_oos": 52.0,
                    "cagr_is": 13.0,
                    "mdd_is": 7.0,
                    "trades_is": 10,
                    "win_rate_is": 53.0,
                    "overfit_gap_pct": 1.0,
                    "efficiency_gap": 0.2,
                }

            optimizer._run_single = fake_run_single  # type: ignore[method-assign]

            df = optimizer.optimize()

            self.assertFalse(df.empty)
            self.assertTrue(result_csv.exists())
            self.assertTrue(pattern_doc.exists())
            text = pattern_doc.read_text(encoding="utf-8")
            self.assertIn("운영 기본값 반영 기준", text)


if __name__ == "__main__":
    unittest.main()
