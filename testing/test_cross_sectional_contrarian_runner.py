from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook

from testing import cross_sectional_contrarian_runner as runner
from testing.cross_sectional_contrarian_evaluation import EvaluationInputError, validate_manifest


class TestCrossSectionalContrarianRunner(unittest.TestCase):
    def test_actual_manifest_metadata_is_allowed_but_unknown_keys_are_rejected(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source_manifest = root / "testing/artifacts/nfi_multi_3m_5m/manifest.json"
        self.assertEqual(len(validate_manifest(source_manifest)), 8)

        payload = json.loads(source_manifest.read_text(encoding="utf-8"))
        payload["unknown_metadata"] = True
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(EvaluationInputError, "unknown top-level keys"):
                validate_manifest(manifest)

    def test_manifest_rejects_malformed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"markets": []}), encoding="utf-8")

            with self.assertRaises(EvaluationInputError):
                validate_manifest(manifest)

    def test_manifest_rejects_synthetic_rows(self) -> None:
        source_manifest = Path(__file__).resolve().parents[1] / "testing/artifacts/nfi_multi_30d_5m/manifest.json"
        payload = json.loads(source_manifest.read_text(encoding="utf-8"))
        payload["markets"]["KRW-BTC"]["synthetic_rows"] = 1
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(EvaluationInputError):
                validate_manifest(manifest)

    def test_manifest_rejects_fractional_or_boolean_synthetic_rows(self) -> None:
        source_manifest = Path(__file__).resolve().parents[1] / "testing/artifacts/nfi_multi_30d_5m/manifest.json"
        original = json.loads(source_manifest.read_text(encoding="utf-8"))
        cases = (
            ("top-level", lambda payload, value: payload.__setitem__("synthetic_rows", value)),
            ("market", lambda payload, value: payload["markets"]["KRW-BTC"].__setitem__("synthetic_rows", value)),
        )
        for label, mutate in cases:
            for value in (0.5, False):
                with self.subTest(label=label, value=value):
                    payload = json.loads(json.dumps(original))
                    mutate(payload, value)
                    with tempfile.TemporaryDirectory() as directory:
                        manifest = Path(directory) / "manifest.json"
                        manifest.write_text(json.dumps(payload), encoding="utf-8")

                        with self.assertRaises(EvaluationInputError):
                            validate_manifest(manifest)

    def test_runner_emits_machine_contract_and_complete_trade_records(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source_manifest = root / "testing/artifacts/nfi_multi_30d_5m/manifest.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            command = [
                sys.executable, "-B", "-m", "testing.cross_sectional_contrarian_runner",
                "--manifest", str(source_manifest), "--output", str(output),
                "--window-start", "2026-07-18T00:00:00Z", "--window-end", "2026-08-16T00:00:00Z",
                "--momentum-lookback", "36", "--hold-bars", "48", "--btc-gate-lookback", "72",
                "--btc-gate-threshold", "0.0", "--breadth-min", "5", "--selected-return-max", "-0.005",
                "--stop-loss-pct", "0.03", "--exposure", "0.50", "--fee", "0.0005",
                "--spread", "0.0003", "--slippage", "0.0002",
            ]
            completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(payload["candidate"], "cross_sectional_contrarian_bounce")
        self.assertTrue(payload["evaluation_only"])
        self.assertEqual(payload["windows"]["convention"], "half_open_utc")
        self.assertEqual(payload["windows"]["start"], "2026-07-18T00:00:00Z")
        self.assertEqual(payload["windows"]["end"], "2026-08-16T00:00:00Z")
        self.assertEqual(payload["integrity"]["fixed_universe"], True)
        self.assertEqual(payload["integrity"]["synthetic_rows"], 0)
        self.assertEqual(payload["integrity"]["forward_fill"], False)
        self.assertEqual(payload["aggregate"]["trades"], len(payload["trades"]))
        self.assertEqual(set(payload["per_market"]), {
            "KRW-ADA", "KRW-AVAX", "KRW-BTC", "KRW-DOGE",
            "KRW-ETH", "KRW-LINK", "KRW-SOL", "KRW-XRP",
        })

    def test_cli_rejects_non_finite_float_before_loading_data(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = root / "testing/artifacts/nfi_multi_30d_5m/manifest.json"
        for option in (
            "--btc-gate-threshold", "--selected-return-max", "--stop-loss-pct",
            "--exposure", "--fee", "--spread", "--slippage",
        ):
            with self.subTest(option=option):
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(EvaluationInputError, "configuration floats must be finite"):
                        runner.main([
                            "--manifest", str(manifest), "--output", str(Path(directory) / "out.json"),
                            "--window-start", "2026-07-18T00:00:00Z", "--window-end", "2026-08-16T00:00:00Z",
                            option, "nan",
                        ])

    def test_cli_rejects_malformed_utc_without_traceback(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = root / "testing/artifacts/nfi_multi_30d_5m/manifest.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            completed = subprocess.run(
                [
                    sys.executable, "-B", "-m", "testing.cross_sectional_contrarian_runner",
                    "--manifest", str(manifest), "--output", str(output),
                    "--window-start", "not-a-utc", "--window-end", "2026-08-16T00:00:00Z",
                ],
                cwd=str(root), capture_output=True, text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "invalid UTC timestamp: not-a-utc\n")
        self.assertNotIn("Traceback", completed.stderr)
        self.assertFalse(output.exists())

    def test_loaded_candles_reject_non_finite_non_positive_or_inverted_values(self) -> None:
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for close, low in ((float("nan"), 1.0), (0.0, 0.0), (1.0, 2.0)):
            with self.subTest(close=close, low=low):
                with self.assertRaisesRegex(EvaluationInputError, "invalid candle values: KRW-ADA"):
                    runner._validate_loaded_candles("KRW-ADA", (runner.Candle(timestamp, close, low),))

    def test_local_workbook_failure_is_a_concise_input_error(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source_manifest = root / "testing/artifacts/nfi_multi_30d_5m/manifest.json"
        payload = json.loads(source_manifest.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=str(root / "testing")) as directory:
            directory_path = Path(directory)
            workbook_path = directory_path / "invalid.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["candle_date_time_utc", "low_price", "trade_price"])
            sheet.append(["2026-08-01T00:00:00", 2.0, 1.0])
            workbook.save(workbook_path)
            workbook.close()
            payload["markets"]["KRW-ADA"]["path"] = workbook_path.relative_to(root).as_posix()
            manifest = directory_path / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(EvaluationInputError, "invalid candle values: KRW-ADA"):
                runner._load_data(manifest)


if __name__ == "__main__":
    unittest.main()
