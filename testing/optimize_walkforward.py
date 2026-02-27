from __future__ import annotations

import argparse
import itertools
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import WALKFORWARD_DEFAULT_UPDATE_CRITERIA
from core.config_loader import _ENV_KEY_MAP, load_trading_config
from testing.backtest_runner import BacktestRunner


DEFAULT_PATTERN_DOC_PATH = "testing/optimize_walkforward_patterns.md"


@dataclass
class ObjectiveThresholds:
    min_trades: int = int(WALKFORWARD_DEFAULT_UPDATE_CRITERIA["min_oos_trades"])
    min_win_rate: float = float(WALKFORWARD_DEFAULT_UPDATE_CRITERIA["min_oos_win_rate"])
    max_overfit_gap_pct: float = float(WALKFORWARD_DEFAULT_UPDATE_CRITERIA["max_overfit_gap_pct"])
    max_efficiency_gap: float = float(WALKFORWARD_DEFAULT_UPDATE_CRITERIA["max_efficiency_gap"])


@dataclass
class StageResult:
    stage: str
    phase: str
    params: dict[str, float | int]
    objective_score: float
    accepted: bool
    reject_reason: str
    cagr_oos: float
    mdd_oos: float
    trades_oos: int
    win_rate_oos: float
    cagr_is: float
    mdd_is: float
    trades_is: int
    win_rate_is: float
    overfit_gap_pct: float
    efficiency_gap: float
    report_path: str


BASE_PARAM_GROUPS: dict[str, dict[str, list[float | int]]] = {
    "entry": {
        "rsi_long_threshold": [26, 29, 32, 35],
        "bb_std": [1.8, 2.0, 2.2, 2.4],
        "entry_score_threshold": [2.0, 2.4, 2.8, 3.2],
    },
    "exit": {
        "take_profit_r": [1.4, 1.8, 2.2, 2.6],
        "atr_stop_mult": [1.1, 1.4, 1.7],
        "atr_trailing_mult": [1.6, 2.0, 2.4],
    },
    "regime": {
        "regime_adx_min": [14.0, 18.0, 22.0, 26.0],
        "regime_slope_lookback": [2, 3, 4, 5],
        "displacement_min_atr_mult": [0.9, 1.1, 1.3, 1.5],
    },
    "sizing": {
        "risk_per_trade_pct": [0.04, 0.07, 0.1, 0.13],
        "quality_multiplier_high": [1.05, 1.1, 1.15, 1.2],
        "quality_multiplier_low": [0.65, 0.7, 0.75],
    },
}


FINE_GRID_SPREAD: dict[str, float] = {
    "rsi_long_threshold": 1,
    "bb_std": 0.1,
    "entry_score_threshold": 0.2,
    "take_profit_r": 0.2,
    "atr_stop_mult": 0.1,
    "atr_trailing_mult": 0.1,
    "regime_adx_min": 2.0,
    "regime_slope_lookback": 1,
    "displacement_min_atr_mult": 0.1,
    "risk_per_trade_pct": 0.01,
    "quality_multiplier_high": 0.03,
    "quality_multiplier_low": 0.03,
}


class WalkForwardOptimizer:
    def __init__(
        self,
        *,
        market: str,
        path: str,
        result_csv_path: str,
        pattern_doc_path: str = DEFAULT_PATTERN_DOC_PATH,
        thresholds: ObjectiveThresholds | None = None,
        beam_width: int = 5,
        max_candidates_per_phase: int = 64,
        insample_windows: int = 2,
        oos_windows: int = 2,
        lookback_days: int | None = None,
    ):
        self.market = market
        self.path = path
        self.result_csv_path = result_csv_path
        self.pattern_doc_path = pattern_doc_path
        self.thresholds = thresholds or ObjectiveThresholds()
        self.beam_width = max(1, int(beam_width))
        self.max_candidates_per_phase = max(1, int(max_candidates_per_phase))
        self.insample_windows = max(1, int(insample_windows))
        self.oos_windows = max(2, int(oos_windows))
        self.lookback_days = int(lookback_days) if lookback_days else None
        self.base_config = load_trading_config()

    def optimize(self) -> pd.DataFrame:
        base_params = self._base_params()
        beam: list[dict[str, float | int]] = [base_params]
        all_results: list[StageResult] = []

        for stage_name in ("entry", "exit", "regime", "sizing"):
            coarse_candidates = self._build_candidates(stage_name, beam, fine=False)
            coarse_results = self._evaluate_candidates(stage_name, "coarse", coarse_candidates)
            all_results.extend(coarse_results)
            beam = self._next_beam(coarse_results, fallback=beam)

            fine_candidates = self._build_candidates(stage_name, beam, fine=True)
            fine_results = self._evaluate_candidates(stage_name, "fine", fine_candidates)
            all_results.extend(fine_results)
            beam = self._next_beam(fine_results, fallback=beam)

        df = pd.DataFrame([r.__dict__ for r in all_results])
        if not df.empty:
            df = df.sort_values(["accepted", "objective_score"], ascending=[False, False]).reset_index(drop=True)
        Path(self.result_csv_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.result_csv_path, index=False)
        self._write_pattern_doc(df)
        return df

    def _base_params(self) -> dict[str, float | int]:
        base: dict[str, float | int] = {}
        for group in BASE_PARAM_GROUPS.values():
            for name in group:
                base[name] = getattr(self.base_config, name)
        return base

    def _build_candidates(self, stage: str, beam: list[dict[str, float | int]], *, fine: bool) -> list[dict[str, float | int]]:
        stage_grid = BASE_PARAM_GROUPS[stage]
        per_param_values: dict[str, list[float | int]] = {}
        for name, coarse_values in stage_grid.items():
            per_param_values[name] = self._fine_values(name, beam[0][name]) if fine else list(coarse_values)

        names = list(per_param_values)
        combos = list(itertools.product(*(per_param_values[name] for name in names)))
        if len(combos) > self.max_candidates_per_phase:
            stride = max(1, len(combos) // self.max_candidates_per_phase)
            combos = combos[::stride][: self.max_candidates_per_phase]

        candidates: list[dict[str, float | int]] = []
        for seed in beam:
            for combo in combos:
                candidate = dict(seed)
                for key, value in zip(names, combo):
                    candidate[key] = value
                candidates.append(candidate)

        unique: list[dict[str, float | int]] = []
        seen: set[tuple[tuple[str, float | int], ...]] = set()
        for row in candidates:
            marker = tuple(sorted(row.items()))
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(row)
        return unique

    def _fine_values(self, name: str, center: float | int) -> list[float | int]:
        step = FINE_GRID_SPREAD[name]
        points = [center - step, center, center + step]
        if isinstance(center, int):
            return sorted({max(1, int(round(v))) for v in points})
        return sorted({round(float(v), 6) for v in points if float(v) > 0})

    def _evaluate_candidates(self, stage: str, phase: str, candidates: list[dict[str, float | int]]) -> list[StageResult]:
        rows: list[StageResult] = []
        for idx, params in enumerate(candidates, start=1):
            report_path = self._report_path(stage, phase, idx)
            metrics = self._run_single(params=params, report_path=report_path)
            rows.append(
                StageResult(
                    stage=stage,
                    phase=phase,
                    params=params,
                    objective_score=metrics["objective_score"],
                    accepted=metrics["accepted"],
                    reject_reason=metrics["reject_reason"],
                    cagr_oos=metrics["cagr_oos"],
                    mdd_oos=metrics["mdd_oos"],
                    trades_oos=metrics["trades_oos"],
                    win_rate_oos=metrics["win_rate_oos"],
                    cagr_is=metrics["cagr_is"],
                    mdd_is=metrics["mdd_is"],
                    trades_is=metrics["trades_is"],
                    win_rate_is=metrics["win_rate_is"],
                    overfit_gap_pct=metrics["overfit_gap_pct"],
                    efficiency_gap=metrics["efficiency_gap"],
                    report_path=report_path,
                )
            )
        return rows

    def _run_single(self, *, params: dict[str, float | int], report_path: str) -> dict[str, Any]:
        previous_env = {name: os.environ.get(name) for name in self._env_keys_for_params(params)}
        try:
            for param_name, value in params.items():
                env_key = _ENV_KEY_MAP.get(param_name)
                if env_key:
                    os.environ[env_key] = str(value)
            runner = BacktestRunner(
                market=self.market,
                path=self.path,
                insample_windows=self.insample_windows,
                oos_windows=self.oos_windows,
                lookback_days=self.lookback_days,
                segment_report_path=report_path,
            )
            runner.run()
            segment_df = pd.read_csv(report_path)
            scored = self._score_segments(segment_df)
            scored["report_path"] = report_path
            return scored
        finally:
            for env_key, old_value in previous_env.items():
                if old_value is None:
                    os.environ.pop(env_key, None)
                else:
                    os.environ[env_key] = old_value

    def _score_segments(self, segment_df: pd.DataFrame) -> dict[str, Any]:
        if segment_df.empty:
            return {
                "objective_score": -1_000.0,
                "accepted": False,
                "reject_reason": "empty_segments",
                "cagr_oos": 0.0,
                "mdd_oos": 0.0,
                "trades_oos": 0,
                "win_rate_oos": 0.0,
                "cagr_is": 0.0,
                "mdd_is": 0.0,
                "trades_is": 0,
                "win_rate_is": 0.0,
                "overfit_gap_pct": 999.0,
                "efficiency_gap": 999.0,
            }

        mid = max(1, int(math.ceil(len(segment_df) / 2)))
        is_df = segment_df.iloc[:mid]
        oos_df = segment_df.iloc[mid:]
        if oos_df.empty:
            oos_df = is_df.copy()

        is_metrics = self._aggregate(is_df)
        oos_metrics = self._aggregate(oos_df)

        overfit_gap_pct = is_metrics["compounded_return_pct"] - oos_metrics["compounded_return_pct"]
        efficiency_gap = is_metrics["expectancy_per_trade"] - oos_metrics["expectancy_per_trade"]

        score = self._objective_score(oos_metrics)
        accepted, reason = self._acceptance(oos_metrics, overfit_gap_pct, efficiency_gap)

        return {
            "objective_score": score,
            "accepted": accepted,
            "reject_reason": reason,
            "cagr_oos": oos_metrics["cagr"],
            "mdd_oos": oos_metrics["mdd"],
            "trades_oos": oos_metrics["trades"],
            "win_rate_oos": oos_metrics["win_rate"],
            "cagr_is": is_metrics["cagr"],
            "mdd_is": is_metrics["mdd"],
            "trades_is": is_metrics["trades"],
            "win_rate_is": is_metrics["win_rate"],
            "overfit_gap_pct": overfit_gap_pct,
            "efficiency_gap": efficiency_gap,
        }

    def _aggregate(self, df: pd.DataFrame) -> dict[str, float | int]:
        cagr = float(pd.to_numeric(df.get("cagr", pd.Series([0.0])), errors="coerce").fillna(0.0).mean())
        mdd = float(pd.to_numeric(df.get("mdd", pd.Series([0.0])), errors="coerce").fillna(0.0).mean())
        trades = int(pd.to_numeric(df.get("trades", pd.Series([0])), errors="coerce").fillna(0).sum())
        win_rate = float(pd.to_numeric(df.get("win_rate", pd.Series([0.0])), errors="coerce").fillna(0.0).mean())
        period_return = pd.to_numeric(df.get("period_return", pd.Series([0.0])), errors="coerce").fillna(0.0)
        compounded_return_pct = float((period_return.div(100).add(1).prod() - 1) * 100)
        expectancy_per_trade = compounded_return_pct / max(1, trades)
        return {
            "cagr": cagr,
            "mdd": mdd,
            "trades": trades,
            "win_rate": win_rate,
            "compounded_return_pct": compounded_return_pct,
            "expectancy_per_trade": expectancy_per_trade,
        }

    def _objective_score(self, oos_metrics: dict[str, float | int]) -> float:
        trade_ratio = min(1.0, float(oos_metrics["trades"]) / max(1, self.thresholds.min_trades))
        win_ratio = min(1.0, float(oos_metrics["win_rate"]) / max(1e-9, self.thresholds.min_win_rate))
        cagr_component = float(oos_metrics["cagr"])
        mdd_penalty = max(0.0, float(oos_metrics["mdd"]) - 12.0)
        return (1.2 * cagr_component) - (1.7 * mdd_penalty) + (10.0 * trade_ratio) + (8.0 * win_ratio)

    def _acceptance(self, oos_metrics: dict[str, float | int], overfit_gap_pct: float, efficiency_gap: float) -> tuple[bool, str]:
        if int(oos_metrics["trades"]) < self.thresholds.min_trades:
            return False, "trades_below_min"
        if float(oos_metrics["win_rate"]) < self.thresholds.min_win_rate:
            return False, "win_rate_below_min"
        if overfit_gap_pct > self.thresholds.max_overfit_gap_pct:
            return False, "overfit_gap_too_large"
        if efficiency_gap > self.thresholds.max_efficiency_gap:
            return False, "efficiency_gap_too_large"
        return True, "accepted"

    def _next_beam(self, results: list[StageResult], *, fallback: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
        ranked = sorted(results, key=lambda row: (row.accepted, row.objective_score), reverse=True)
        top = ranked[: self.beam_width]
        if not top:
            return fallback
        return [dict(row.params) for row in top]

    def _env_keys_for_params(self, params: dict[str, float | int]) -> list[str]:
        return [key for name in params if (key := _ENV_KEY_MAP.get(name))]

    def _report_path(self, stage: str, phase: str, idx: int) -> str:
        base = Path(self.result_csv_path).with_suffix("")
        return str(base.parent / f"{base.name}_{stage}_{phase}_{idx:03d}_segments.csv")

    def _write_pattern_doc(self, df: pd.DataFrame) -> None:
        Path(self.pattern_doc_path).parent.mkdir(parents=True, exist_ok=True)
        accepted = df[df["accepted"]] if not df.empty else pd.DataFrame()
        target = accepted.head(10) if not accepted.empty else df.head(10)

        lines: list[str] = [
            "# Walk-forward 상위 조합 공통 패턴",
            "",
            "이 문서는 `testing/optimize_walkforward.py` 결과를 기반으로 운영 기본값(`core/config.py`) 업데이트 후보를 검토하기 위한 자료입니다.",
            "",
            "## 기본 업데이트 게이트",
            f"- OOS 거래수 >= {self.thresholds.min_trades}",
            f"- OOS 승률 >= {self.thresholds.min_win_rate}%",
            f"- 과최적화 격차(=IS 누적수익률 - OOS 누적수익률) <= {self.thresholds.max_overfit_gap_pct}%p",
            f"- 효율성 격차(=IS 기대수익/트레이드 - OOS 기대수익/트레이드) <= {self.thresholds.max_efficiency_gap}",
            "",
        ]

        if target.empty:
            lines.append("- 분석 가능한 결과가 없어 패턴을 생성하지 못했습니다.")
        else:
            lines.append("## 상위 조합 파라미터 빈도")
            lines.append("")
            for param_name in self._base_params().keys():
                values = [row[param_name] for row in target["params"]]
                top_value = pd.Series(values).value_counts().idxmax()
                frequency = pd.Series(values).value_counts().max()
                lines.append(f"- `{param_name}`: 최빈값 `{top_value}` ({frequency}/{len(values)})")
            lines.extend(["", "## 운영 기본값 반영 기준", "", "- 상위 10개 중 70% 이상이 동일한 값일 때 기본값 반영 후보로 지정합니다.", "- 반영 전, 동일 조합으로 최근 구간 재검증(run 1회)을 수행합니다."])

        Path(self.pattern_doc_path).write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Walk-forward stage tuning optimizer")
    parser.add_argument("--market", default="KRW-BTC")
    parser.add_argument("--path", default="backdata_candle_day.xlsx")
    parser.add_argument("--result-csv", default="testing/optimize_walkforward_results.csv")
    parser.add_argument("--pattern-doc", default=DEFAULT_PATTERN_DOC_PATH)
    parser.add_argument("--insample-windows", type=int, default=2)
    parser.add_argument("--oos-windows", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--beam-width", type=int, default=5)
    parser.add_argument("--max-candidates-per-phase", type=int, default=64)
    parser.add_argument("--min-trades", type=int, default=8)
    parser.add_argument("--min-win-rate", type=float, default=38.0)
    parser.add_argument("--max-overfit-gap-pct", type=float, default=40.0)
    parser.add_argument("--max-efficiency-gap", type=float, default=1.2)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    thresholds = ObjectiveThresholds(
        min_trades=args.min_trades,
        min_win_rate=args.min_win_rate,
        max_overfit_gap_pct=args.max_overfit_gap_pct,
        max_efficiency_gap=args.max_efficiency_gap,
    )
    optimizer = WalkForwardOptimizer(
        market=args.market,
        path=args.path,
        result_csv_path=args.result_csv,
        pattern_doc_path=args.pattern_doc,
        thresholds=thresholds,
        beam_width=args.beam_width,
        max_candidates_per_phase=args.max_candidates_per_phase,
        insample_windows=args.insample_windows,
        oos_windows=args.oos_windows,
        lookback_days=args.lookback_days,
    )
    df = optimizer.optimize()
    print(f"saved optimization results: {args.result_csv} ({len(df)} rows)")
    print(f"saved pattern report: {args.pattern_doc}")


if __name__ == "__main__":
    main()
