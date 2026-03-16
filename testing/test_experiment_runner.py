import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "slave_constants" not in sys.modules:
    slave_constants = types.ModuleType("slave_constants")
    setattr(slave_constants, "ACCESS_KEY", "x")
    setattr(slave_constants, "SECRET_KEY", "y")
    setattr(slave_constants, "SERVER_URL", "https://api.upbit.com")
    sys.modules["slave_constants"] = slave_constants

from testing.experiment_runner import ExperimentRunner


FIXTURE_DIR = ROOT / "testing" / "fixtures"


class ExperimentRunnerTest(unittest.TestCase):
    def _artifact(self, payload: dict[str, object]) -> dict[str, Any]:
        return cast(dict[str, Any], payload)

    def _assert_schema(self, artifact: dict[str, Any]) -> None:
        self.assertEqual(
            set(artifact),
            {
                "baseline_strategy",
                "candidate_strategy",
                "run_config",
                "cost_model",
                "baseline_metrics",
                "candidate_metrics",
                "delta_metrics",
                "oos_gate",
                "parity_gate",
                "decision",
                "reasons",
            },
        )

    def _fixture(self, name: str) -> str:
        return str(FIXTURE_DIR / name)

    def _assert_oos_gate_contract(self, artifact: dict[str, Any]) -> None:
        oos_gate = cast(dict[str, object], artifact["oos_gate"])
        self.assertEqual(
            set(oos_gate),
            {
                "pass",
                "candidate_accepted",
                "baseline_objective_score",
                "candidate_objective_score",
                "candidate_reject_reason",
            },
        )

    def _assert_parity_gate_contract(self, artifact: dict[str, Any]) -> None:
        parity_gate = cast(dict[str, object], artifact["parity_gate"])
        self.assertEqual(
            set(parity_gate),
            {
                "pass",
                "artifact_path",
                "snapshot_count",
                "mismatch_rows",
                "strategy_name",
                "expected_strategy_name",
            },
        )

    def test_writes_promote_artifact_for_synthetic_better_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "candidate_v1_decision.json"
            parity_output_path = Path(td) / "candidate_v1_parity.json"

            artifact = self._artifact(
                ExperimentRunner(
                    market="KRW-BTC",
                    lookback_days=90,
                    strategy_name="baseline",
                    candidate_name="candidate_v1",
                    output_path=str(output_path),
                    baseline_report_path=self._fixture("baseline_segments.csv"),
                    candidate_report_path=self._fixture(
                        "candidate_better_segments.csv"
                    ),
                    parity_fixture_path=self._fixture("parity_candidate_v1_cases.json"),
                    parity_output_path=str(parity_output_path),
                ).run()
            )

            self.assertTrue(output_path.exists())
            self.assertTrue(parity_output_path.exists())
            self._assert_schema(artifact)
            self._assert_oos_gate_contract(artifact)
            self._assert_parity_gate_contract(artifact)
            self.assertEqual(artifact["baseline_strategy"], "baseline")
            self.assertEqual(artifact["candidate_strategy"], "candidate_v1")
            self.assertEqual(artifact["decision"], "promote")
            self.assertEqual(cast(list[object], artifact["reasons"]), [])
            self.assertTrue(cast(dict[str, Any], artifact["oos_gate"])["pass"])
            self.assertTrue(cast(dict[str, Any], artifact["parity_gate"])["pass"])
            self.assertEqual(
                cast(dict[str, Any], artifact["parity_gate"])["strategy_name"],
                "candidate_v1",
            )
            self.assertEqual(
                cast(dict[str, Any], artifact["parity_gate"])["expected_strategy_name"],
                "candidate_v1",
            )

    def test_writes_reject_artifact_for_synthetic_worse_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "candidate_v1_decision.json"
            parity_output_path = Path(td) / "candidate_v1_parity.json"

            artifact = self._artifact(
                ExperimentRunner(
                    market="KRW-BTC",
                    lookback_days=90,
                    strategy_name="baseline",
                    candidate_name="candidate_v1",
                    output_path=str(output_path),
                    baseline_report_path=self._fixture("baseline_segments.csv"),
                    candidate_report_path=self._fixture("candidate_worse_segments.csv"),
                    parity_fixture_path=self._fixture("parity_candidate_v1_cases.json"),
                    parity_output_path=str(parity_output_path),
                ).run()
            )

            self.assertTrue(output_path.exists())
            self._assert_schema(artifact)
            self.assertEqual(artifact["decision"], "reject")
            self.assertFalse(cast(dict[str, Any], artifact["oos_gate"])["pass"])
            self.assertTrue(cast(dict[str, Any], artifact["parity_gate"])["pass"])
            self.assertTrue(
                any(
                    "trades_below_min" in str(reason)
                    for reason in cast(list[object], artifact["reasons"])
                )
            )

    def test_rejects_when_parity_strategy_identity_does_not_match_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "candidate_v1_decision.json"
            parity_output_path = Path(td) / "candidate_v1_parity.json"

            artifact = self._artifact(
                ExperimentRunner(
                    market="KRW-BTC",
                    lookback_days=90,
                    strategy_name="baseline",
                    candidate_name="candidate_v1",
                    output_path=str(output_path),
                    baseline_report_path=self._fixture("baseline_segments.csv"),
                    candidate_report_path=self._fixture(
                        "candidate_better_segments.csv"
                    ),
                    parity_fixture_path=self._fixture("parity_candidate_v1_cases.json"),
                    parity_strategy_name="baseline",
                    parity_output_path=str(parity_output_path),
                ).run()
            )

            self.assertEqual(artifact["decision"], "reject")
            self.assertFalse(cast(dict[str, Any], artifact["parity_gate"])["pass"])
            self.assertEqual(
                cast(dict[str, Any], artifact["parity_gate"])["strategy_name"],
                "baseline",
            )
            self.assertEqual(
                cast(dict[str, Any], artifact["parity_gate"])["expected_strategy_name"],
                "candidate_v1",
            )
            self.assertTrue(
                any(
                    "parity_strategy_mismatch" in str(reason)
                    for reason in cast(list[object], artifact["reasons"])
                )
            )

    def test_writes_reject_artifact_when_parity_mismatches_exist(self):
        with tempfile.TemporaryDirectory() as td:
            parity_fixture_path = Path(td) / "parity_cases.json"
            output_path = Path(td) / "candidate_v1_decision.json"
            parity_output_path = Path(td) / "candidate_v1_parity.json"
            cases = cast(
                list[dict[str, Any]],
                json.loads(
                    Path(self._fixture("parity_baseline_cases.json")).read_text(
                        encoding="utf-8"
                    )
                ),
            )
            cases[1]["expected"]["size"] = 1.0
            parity_fixture_path.write_text(
                json.dumps(cases, indent=2), encoding="utf-8"
            )

            artifact = self._artifact(
                ExperimentRunner(
                    market="KRW-BTC",
                    lookback_days=90,
                    strategy_name="baseline",
                    candidate_name="candidate_v1",
                    output_path=str(output_path),
                    baseline_report_path=self._fixture("baseline_segments.csv"),
                    candidate_report_path=self._fixture(
                        "candidate_better_segments.csv"
                    ),
                    parity_fixture_path=str(parity_fixture_path),
                    parity_output_path=str(parity_output_path),
                ).run()
            )

            self.assertTrue(output_path.exists())
            self.assertTrue(parity_output_path.exists())
            self._assert_schema(artifact)
            self._assert_oos_gate_contract(artifact)
            self._assert_parity_gate_contract(artifact)
            self.assertEqual(artifact["decision"], "reject")
            self.assertTrue(cast(dict[str, Any], artifact["oos_gate"])["pass"])
            self.assertFalse(cast(dict[str, Any], artifact["parity_gate"])["pass"])
            mismatch_rows = cast(
                list[dict[str, object]],
                cast(dict[str, Any], artifact["parity_gate"])["mismatch_rows"],
            )
            self.assertGreater(len(mismatch_rows), 0)
            self.assertEqual(
                set(mismatch_rows[0]),
                {
                    "index",
                    "name",
                    "expected",
                    "actual",
                    "intent_match",
                    "reason_match",
                    "size_match",
                },
            )
            self.assertTrue(
                any(
                    "parity" in str(reason)
                    for reason in cast(list[object], artifact["reasons"])
                )
            )


if __name__ == "__main__":
    unittest.main()
