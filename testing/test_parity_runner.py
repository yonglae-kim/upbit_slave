import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "slave_constants" not in sys.modules:
    slave_constants = types.ModuleType("slave_constants")
    setattr(slave_constants, "ACCESS_KEY", "x")
    setattr(slave_constants, "SECRET_KEY", "y")
    setattr(slave_constants, "SERVER_URL", "https://api.upbit.com")
    sys.modules["slave_constants"] = slave_constants

from testing.parity_runner import ParityRunner
import core.strategies.candidate_v1 as candidate_v1


FIXTURE_DIR = ROOT / "testing" / "fixtures"


class ParityRunnerTest(unittest.TestCase):
    def _artifact(self, payload: dict[str, object]) -> dict[str, Any]:
        return cast(dict[str, Any], payload)

    def _fixture_path(self) -> Path:
        return FIXTURE_DIR / "parity_baseline_cases.json"

    def _candidate_fixture_path(self) -> Path:
        return FIXTURE_DIR / "parity_candidate_v1_cases.json"

    def _candidate_debug(self, *, accepted: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "final_pass": accepted,
            "fail_code": "pass" if accepted else "pullback_missing",
            "regime_filter_metrics": {"pass": True, "regime": "strong_trend"},
            "zones_total": 3,
            "zones_active": 1,
            "selected_zone": {
                "type": "ob",
                "bias": "bullish",
                "lower": 100.9,
                "upper": 101.5,
            },
            "sr_flip_pass": accepted,
            "sr_flip_level": {
                "bias": "resistance",
                "lower": 100.8,
                "upper": 101.2,
                "score": 0.9,
            },
            "trigger_pass": accepted,
        }
        if not accepted:
            payload["selected_zone"] = None
            payload["sr_flip_level"] = None
        return payload

    def _candidate_debug_side_effect(
        self,
        data: dict[str, list[dict[str, object]]],
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        latest = data.get("1m", [{}])[0]
        latest_close_raw = latest.get("trade_price", 0.0)
        latest_close = (
            float(latest_close_raw)
            if isinstance(latest_close_raw, (int, float))
            else 0.0
        )
        return self._candidate_debug(accepted=latest_close >= 102.3)

    def test_uses_strategy_default_fixture_when_fixture_is_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "baseline_parity.json"

            artifact = self._artifact(
                ParityRunner(
                    strategy_name="baseline",
                    fixture_path=None,
                    output_path=str(output_path),
                ).run()
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(artifact["strategy_name"], "baseline")
            self.assertEqual(int(artifact["snapshot_count"]), 3)
            self.assertTrue(bool(artifact["pass"]))

    def _assert_schema(self, artifact: dict[str, Any]) -> None:
        self.assertEqual(
            set(artifact),
            {
                "strategy_name",
                "snapshot_count",
                "matched_intent_count",
                "matched_reason_count",
                "matched_size_count",
                "mismatch_rows",
                "pass",
            },
        )

    def test_writes_pass_artifact_with_required_schema(self):
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "candidate_v1_parity.json"

            artifact = self._artifact(
                ParityRunner(
                    strategy_name="baseline",
                    fixture_path=str(self._fixture_path()),
                    output_path=str(output_path),
                ).run()
            )

            self.assertTrue(output_path.exists())
            self._assert_schema(artifact)
            self.assertEqual(artifact["strategy_name"], "baseline")
            self.assertEqual(int(artifact["snapshot_count"]), 3)
            self.assertEqual(int(artifact["matched_intent_count"]), 3)
            self.assertEqual(int(artifact["matched_reason_count"]), 3)
            self.assertEqual(int(artifact["matched_size_count"]), 3)
            self.assertEqual(artifact["mismatch_rows"], [])
            self.assertTrue(bool(artifact["pass"]))

    def test_candidate_fixture_produces_candidate_strategy_parity_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "candidate_v1_parity.json"

            with (
                patch.object(
                    candidate_v1,
                    "debug_entry",
                    side_effect=self._candidate_debug_side_effect,
                ),
                patch.object(
                    candidate_v1,
                    "check_sell",
                    return_value=False,
                ),
            ):
                artifact = self._artifact(
                    ParityRunner(
                        strategy_name="candidate_v1",
                        fixture_path=str(self._candidate_fixture_path()),
                        output_path=str(output_path),
                    ).run()
                )

            self.assertTrue(output_path.exists())
            self._assert_schema(artifact)
            self.assertEqual(artifact["strategy_name"], "candidate_v1")
            self.assertEqual(int(artifact["snapshot_count"]), 3)
            self.assertTrue(bool(artifact["pass"]))

    def test_fails_closed_when_no_snapshots_are_evaluated(self):
        with tempfile.TemporaryDirectory() as td:
            fixture_path = Path(td) / "empty_cases.json"
            output_path = Path(td) / "candidate_v1_parity.json"
            fixture_path.write_text("[]", encoding="utf-8")

            artifact = self._artifact(
                ParityRunner(
                    strategy_name="baseline",
                    fixture_path=str(fixture_path),
                    output_path=str(output_path),
                ).run()
            )

            self.assertEqual(int(artifact["snapshot_count"]), 0)
            self.assertEqual(int(artifact["matched_intent_count"]), 0)
            self.assertEqual(int(artifact["matched_reason_count"]), 0)
            self.assertEqual(int(artifact["matched_size_count"]), 0)
            self.assertFalse(bool(artifact["pass"]))

    def test_writes_fail_artifact_when_parity_mismatch_exists(self):
        with tempfile.TemporaryDirectory() as td:
            fixture_path = Path(td) / "parity_cases.json"
            output_path = Path(td) / "candidate_v1_parity.json"
            cases = cast(
                list[dict[str, Any]],
                json.loads(self._fixture_path().read_text(encoding="utf-8")),
            )
            cases[0]["expected"]["reason"] = "unexpected_reason"
            fixture_path.write_text(json.dumps(cases, indent=2), encoding="utf-8")

            artifact = self._artifact(
                ParityRunner(
                    strategy_name="baseline",
                    fixture_path=str(fixture_path),
                    output_path=str(output_path),
                ).run()
            )

            self.assertTrue(output_path.exists())
            self._assert_schema(artifact)
            self.assertFalse(bool(artifact["pass"]))
            self.assertEqual(int(artifact["snapshot_count"]), 3)
            self.assertLess(
                int(artifact["matched_reason_count"]),
                int(artifact["snapshot_count"]),
            )
            mismatch_rows = cast(list[object], artifact["mismatch_rows"])
            self.assertGreater(len(mismatch_rows), 0)
            mismatch_row = cast(dict[str, object], mismatch_rows[0])
            self.assertEqual(
                set(mismatch_row),
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
            self.assertEqual(
                set(cast(dict[str, object], mismatch_row["expected"])),
                {"action", "reason", "size"},
            )
            self.assertEqual(
                set(cast(dict[str, object], mismatch_row["actual"])),
                {"action", "reason", "size"},
            )


if __name__ == "__main__":
    unittest.main()
