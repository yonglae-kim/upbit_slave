from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, cast

import pandas as pd

from core.config import WALKFORWARD_DEFAULT_UPDATE_CRITERIA
from core.config_loader import load_trading_config
from testing.optimize_walkforward import ObjectiveThresholds, WalkForwardOptimizer
from testing.parity_runner import (
    DEFAULT_FIXTURE_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_PARITY_OUTPUT_PATH,
    ParityRunner,
    default_fixture_path_for_strategy,
)


DEFAULT_DECISION_OUTPUT_PATH = "testing/artifacts/candidate_v1_decision.json"
DEFAULT_BASELINE_REPORT_PATH = "testing/fixtures/baseline_segments.csv"
DEFAULT_CANDIDATE_REPORT_PATH = "testing/fixtures/candidate_better_segments.csv"


class ExperimentRunner:
    market: str
    lookback_days: int | None
    strategy_name: str
    candidate_name: str
    output_path: str
    baseline_report_path: str
    candidate_report_path: str
    parity_fixture_path: str
    parity_output_path: str
    parity_strategy_name: str

    def __init__(
        self,
        *,
        market: str,
        lookback_days: int | None,
        strategy_name: str,
        candidate_name: str,
        output_path: str = DEFAULT_DECISION_OUTPUT_PATH,
        baseline_report_path: str = DEFAULT_BASELINE_REPORT_PATH,
        candidate_report_path: str = DEFAULT_CANDIDATE_REPORT_PATH,
        parity_fixture_path: str | None = None,
        parity_output_path: str = DEFAULT_PARITY_OUTPUT_PATH,
        parity_strategy_name: str | None = None,
    ) -> None:
        self.market = market
        self.lookback_days = int(lookback_days) if lookback_days is not None else None
        self.strategy_name = strategy_name
        self.candidate_name = candidate_name
        self.output_path = output_path
        self.baseline_report_path = baseline_report_path
        self.candidate_report_path = candidate_report_path
        self.parity_fixture_path = (
            parity_fixture_path or default_fixture_path_for_strategy(candidate_name)
        )
        self.parity_output_path = parity_output_path
        self.parity_strategy_name = parity_strategy_name or candidate_name
        self.config = load_trading_config()
        self.thresholds = ObjectiveThresholds()

    def run(self) -> dict[str, object]:
        baseline_metrics = self._score_report(self.baseline_report_path)
        candidate_metrics = self._score_report(self.candidate_report_path)
        parity_artifact = ParityRunner(
            strategy_name=self.parity_strategy_name,
            fixture_path=self.parity_fixture_path,
            output_path=self.parity_output_path,
        ).run()

        baseline_objective_score = self._as_float(
            baseline_metrics.get("objective_score")
        )
        candidate_objective_score = self._as_float(
            candidate_metrics.get("objective_score")
        )
        candidate_accepted = bool(candidate_metrics.get("accepted"))
        parity_strategy_name = self._as_str(parity_artifact.get("strategy_name"))
        parity_strategy_matches = parity_strategy_name == self.candidate_name
        parity_pass = bool(parity_artifact.get("pass")) and parity_strategy_matches
        candidate_beats_baseline = candidate_accepted and (
            candidate_objective_score >= baseline_objective_score
        )
        reasons: list[str] = []

        candidate_reject_reason = self._as_str(candidate_metrics.get("reject_reason"))
        if not candidate_accepted:
            reasons.append(f"candidate_oos_reject_reason:{candidate_reject_reason}")
        if candidate_accepted and not candidate_beats_baseline:
            reasons.append("candidate_objective_score_below_baseline")
        if not parity_pass:
            reasons.append("parity_mismatch_detected")
        if not parity_strategy_matches:
            reasons.append(
                f"parity_strategy_mismatch:{parity_strategy_name}!={self.candidate_name}"
            )

        artifact: dict[str, object] = {
            "baseline_strategy": self.strategy_name,
            "candidate_strategy": self.candidate_name,
            "run_config": {
                "market": self.market,
                "lookback_days": self.lookback_days,
                "thresholds": dict(WALKFORWARD_DEFAULT_UPDATE_CRITERIA),
                "baseline_report_path": self.baseline_report_path,
                "candidate_report_path": self.candidate_report_path,
                "parity_fixture_path": self.parity_fixture_path,
                "parity_output_path": self.parity_output_path,
            },
            "cost_model": {
                "fee_rate": float(self.config.fee_rate),
                "source": "core.config.TradingConfig.fee_rate",
            },
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "delta_metrics": self._delta_metrics(baseline_metrics, candidate_metrics),
            "oos_gate": {
                "pass": candidate_beats_baseline,
                "candidate_accepted": candidate_accepted,
                "baseline_objective_score": baseline_objective_score,
                "candidate_objective_score": candidate_objective_score,
                "candidate_reject_reason": candidate_reject_reason,
            },
            "parity_gate": {
                "pass": parity_pass,
                "artifact_path": self.parity_output_path,
                "snapshot_count": self._as_int(parity_artifact.get("snapshot_count")),
                "mismatch_rows": self._list_of_objects(
                    parity_artifact.get("mismatch_rows")
                ),
                "strategy_name": parity_strategy_name,
                "expected_strategy_name": self.candidate_name,
            },
            "decision": "promote"
            if candidate_beats_baseline and parity_pass
            else "reject",
            "reasons": reasons,
        }
        self._write_json(self.output_path, artifact)
        return artifact

    def _score_report(self, report_path: str) -> dict[str, object]:
        optimizer = WalkForwardOptimizer(
            market=self.market,
            path="unused.xlsx",
            result_csv_path=str(Path(self.output_path).with_suffix(".csv")),
            thresholds=self.thresholds,
            lookback_days=self.lookback_days,
        )
        scored = optimizer._score_segments(pd.read_csv(report_path))
        return cast(dict[str, object], scored)

    def _delta_metrics(
        self, baseline_metrics: dict[str, object], candidate_metrics: dict[str, object]
    ) -> dict[str, float]:
        numeric_keys = (
            "objective_score",
            "cagr_oos",
            "mdd_oos",
            "trades_oos",
            "win_rate_oos",
            "cagr_is",
            "mdd_is",
            "trades_is",
            "win_rate_is",
            "overfit_gap_pct",
            "efficiency_gap",
        )
        return {
            key: self._as_float(candidate_metrics.get(key))
            - self._as_float(baseline_metrics.get(key))
            for key in numeric_keys
        }

    def _write_json(self, path: str, payload: Mapping[str, object]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _list_of_objects(self, value: object) -> list[object]:
        if not isinstance(value, list):
            return []
        return list(value)

    def _as_float(self, value: object) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    def _as_int(self, value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value))
            except ValueError:
                return 0
        return 0

    def _as_str(self, value: object) -> str:
        if value is None:
            return ""
        return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit candidate promotion decision artifact"
    )
    _ = parser.add_argument("--market", default="KRW-BTC")
    _ = parser.add_argument("--lookback-days", type=int, default=90)
    _ = parser.add_argument("--strategy", default="baseline")
    _ = parser.add_argument("--candidate", default="candidate_v1")
    _ = parser.add_argument("--output", default=DEFAULT_DECISION_OUTPUT_PATH)
    _ = parser.add_argument("--baseline-report", default=DEFAULT_BASELINE_REPORT_PATH)
    _ = parser.add_argument("--candidate-report", default=DEFAULT_CANDIDATE_REPORT_PATH)
    _ = parser.add_argument("--parity-fixture", default=None)
    _ = parser.add_argument("--parity-output", default=DEFAULT_PARITY_OUTPUT_PATH)
    _ = parser.add_argument("--parity-strategy", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    artifact = ExperimentRunner(
        market=str(args.market),
        lookback_days=cast(int | None, args.lookback_days),
        strategy_name=str(args.strategy),
        candidate_name=str(args.candidate),
        output_path=str(args.output),
        baseline_report_path=str(args.baseline_report),
        candidate_report_path=str(args.candidate_report),
        parity_fixture_path=(
            None if args.parity_fixture in (None, "") else str(args.parity_fixture)
        ),
        parity_output_path=str(args.parity_output),
        parity_strategy_name=(
            None if args.parity_strategy in (None, "") else str(args.parity_strategy)
        ),
    ).run()
    print(f"saved decision artifact: {args.output} decision={artifact['decision']}")


if __name__ == "__main__":
    main()
