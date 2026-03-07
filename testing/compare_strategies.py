from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from testing.backtest_runner import BacktestRunner
from testing.strategy_selector import SelectorConstraints, save_recommendation, select_recommendation


@dataclass(frozen=True)
class StrategyProfile:
    key: str
    label: str
    description: str


PROFILES: list[StrategyProfile] = [
    StrategyProfile("baseline", "Baseline", "현행 전략"),
    StrategyProfile("a", "A", "완화형: n-of-k + 중복필터 축소"),
    StrategyProfile("b", "B", "상위추세+하위눌림"),
    StrategyProfile("c", "C", "돌파+재지지"),
]


def _to_num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _safe_compounded(period_returns_pct: pd.Series) -> float:
    values = _to_num(period_returns_pct)
    if values.empty:
        return 0.0
    return float((values.div(100).add(1.0).prod() - 1.0) * 100)


def _aggregate_segment_metrics(df: pd.DataFrame) -> dict[str, float | int]:
    if df.empty:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "mdd": 0.0,
            "avg_rr": 0.0,
            "trades": 0,
            "monthly_trades": 0.0,
            "avg_holding": 0.0,
            "longest_no_trade_bars": 0,
            "recent_3m": 0.0,
            "recent_6m": 0.0,
            "recent_12m": 0.0,
        }

    period_returns = _to_num(df.get("period_return", pd.Series(dtype=float)))
    trades_series = _to_num(df.get("trades", pd.Series(dtype=float)), default=0.0)
    cagr_series = _to_num(df.get("cagr", pd.Series(dtype=float)))
    win_rate_series = _to_num(df.get("win_rate", pd.Series(dtype=float)))
    expectancy_series = _to_num(df.get("expectancy", pd.Series(dtype=float)))
    mdd_series = _to_num(df.get("mdd", pd.Series(dtype=float)))
    profit_loss_ratio_series = _to_num(df.get("profit_loss_ratio", pd.Series(dtype=float)))
    holding_series = _to_num(df.get("avg_holding_minutes", pd.Series(dtype=float)))
    longest_no_trade_bars = int(_to_num(df.get("longest_no_trade_bars", pd.Series(dtype=float))).max())

    gross_profit = (_to_num(df.get("avg_profit", pd.Series(dtype=float))) * win_rate_series.div(100.0).clip(lower=0.0)).mean()
    gross_loss = (abs(_to_num(df.get("avg_loss", pd.Series(dtype=float)))) * (1.0 - win_rate_series.div(100.0).clip(0.0, 1.0))).mean()
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

    total_trades = int(trades_series.sum())
    total_return = _safe_compounded(period_returns)
    observed_days = max(1.0, float(_to_num(df.get("observed_days", pd.Series(dtype=float))).sum()))
    monthly_trades = float(total_trades * 30.0 / observed_days)

    def tail_return(months: int) -> float:
        days = months * 30
        candidates = df.copy()
        if "oos_start" in candidates.columns:
            ts = pd.to_datetime(candidates["oos_start"], errors="coerce")
            end_ts = ts.max()
            if pd.notna(end_ts):
                start_ts = end_ts - pd.Timedelta(days=days)
                mask = ts >= start_ts
                filtered = candidates.loc[mask]
                if not filtered.empty:
                    return _safe_compounded(filtered.get("period_return", pd.Series(dtype=float)))
        segment_lookback = max(1, int(round(months / 1.5)))
        return _safe_compounded(candidates.tail(segment_lookback).get("period_return", pd.Series(dtype=float)))

    return {
        "total_return": total_return,
        "cagr": float(cagr_series.mean()),
        "win_rate": float(win_rate_series.mean()),
        "profit_factor": profit_factor,
        "expectancy": float(expectancy_series.mean()),
        "mdd": float(mdd_series.mean()),
        "avg_rr": float(profit_loss_ratio_series.mean()),
        "trades": total_trades,
        "monthly_trades": monthly_trades,
        "avg_holding": float(holding_series.mean()),
        "longest_no_trade_bars": longest_no_trade_bars,
        "recent_3m": tail_return(3),
        "recent_6m": tail_return(6),
        "recent_12m": tail_return(12),
    }


def _split_is_oos(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df.copy(), df.copy()
    mid = max(1, int((len(df) + 1) // 2))
    is_df = df.iloc[:mid].copy()
    oos_df = df.iloc[mid:].copy()
    if oos_df.empty:
        oos_df = is_df.copy()
    return is_df, oos_df


def _format_value(name: str, value: Any) -> str:
    if name in {"trades", "longest_no_trade_bars"}:
        return f"{int(value)}"
    if name in {"monthly_trades", "profit_factor", "expectancy", "avg_rr", "avg_holding"}:
        return f"{float(value):.3f}"
    return f"{float(value):.2f}"


def _generate_markdown(df: pd.DataFrame, output_path: Path) -> None:
    metric_order = [
        "total_return", "cagr", "win_rate", "profit_factor", "expectancy", "mdd", "avg_rr",
        "trades", "monthly_trades", "avg_holding", "longest_no_trade_bars",
        "recent_3m", "recent_6m", "recent_12m",
        "oos_total_return", "oos_cagr", "oos_win_rate", "oos_profit_factor", "oos_expectancy", "oos_mdd", "oos_avg_rr",
        "oos_trades", "oos_monthly_trades", "oos_avg_holding", "oos_longest_no_trade_bars",
        "oos_recent_3m", "oos_recent_6m", "oos_recent_12m",
    ]
    lines = [
        "# Strategy Comparison Report",
        "",
        "동일 데이터/수수료/슬리피지/기간 조건에서 Baseline, A, B, C 프로파일 비교 결과입니다.",
        "",
        "## Summary Table",
        "",
    ]
    header = ["Profile", *metric_order]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for _, row in df.iterrows():
        cells = [str(row["profile_label"])] + [_format_value(col, row[col]) for col in metric_order]
        lines.append("| " + " | ".join(cells) + " |")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_comparison(args: argparse.Namespace) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for profile in PROFILES:
        segment_path = output_dir / f"backtest_walkforward_segments_{profile.key}.csv"
        runner = BacktestRunner(
            market=args.market,
            path=args.path,
            buffer_cnt=args.buffer_cnt,
            multiple_cnt=args.multiple_cnt,
            insample_windows=args.insample_windows,
            oos_windows=args.oos_windows,
            lookback_days=args.lookback_days,
            spread_rate=args.spread_rate,
            slippage_rate=args.slippage_rate,
            segment_report_path=str(segment_path),
            strategy_profile=profile.key,
        )
        runner.run()
        segment_df = pd.read_csv(segment_path)
        full_metrics = _aggregate_segment_metrics(segment_df)
        _, oos_df = _split_is_oos(segment_df)
        oos_metrics = _aggregate_segment_metrics(oos_df)

        record: dict[str, Any] = {
            "profile": profile.key,
            "profile_label": profile.label,
            "description": profile.description,
            "segment_report_path": str(segment_path),
            **full_metrics,
        }
        for key, value in oos_metrics.items():
            record[f"oos_{key}"] = value
        records.append(record)

    result_df = pd.DataFrame(records)

    sensitivity_df = None
    sensitivity_path = str(getattr(args, "sensitivity_csv", "") or "").strip()
    if sensitivity_path:
        sensitivity_df = pd.read_csv(sensitivity_path)

    selected_df, recommendation = select_recommendation(
        result_df,
        constraints=SelectorConstraints(
            min_monthly_trades_increase=float(args.min_monthly_trades_increase),
            mdd_buffer=float(args.mdd_buffer),
        ),
        sensitivity_df=sensitivity_df,
    )

    csv_path = output_dir / args.result_csv
    selected_df.to_csv(csv_path, index=False)

    md_path = output_dir / args.report_md
    _generate_markdown(selected_df, md_path)

    final_recommendation_json = output_dir / args.final_recommendation_json
    final_recommendation_md = output_dir / args.final_recommendation_md
    save_recommendation(recommendation, json_path=final_recommendation_json, markdown_path=final_recommendation_md)
    print(f"strategy comparison csv saved: {csv_path}")
    print(f"strategy comparison markdown saved: {md_path}")
    print(f"final recommendation json saved: {final_recommendation_json}")
    print(f"final recommendation markdown saved: {final_recommendation_md}")
    return selected_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare strategy profiles using a shared walk-forward backtest pipeline.")
    parser.add_argument("--market", default="KRW-BTC")
    parser.add_argument("--path", default="backdata_candle_day.xlsx")
    parser.add_argument("--buffer-cnt", type=int, default=200)
    parser.add_argument("--multiple-cnt", type=int, default=6)
    parser.add_argument("--insample-windows", type=int, default=2)
    parser.add_argument("--oos-windows", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--spread-rate", type=float, default=0.0003)
    parser.add_argument("--slippage-rate", type=float, default=0.0002)
    parser.add_argument("--output-dir", default="testing/reports")
    parser.add_argument("--result-csv", default="strategy_comparison.csv")
    parser.add_argument("--report-md", default="strategy_comparison.md")
    parser.add_argument("--sensitivity-csv", default="", help="optional csv containing perturbation results for robustness_score")
    parser.add_argument("--min-monthly-trades-increase", type=float, default=0.30)
    parser.add_argument("--mdd-buffer", type=float, default=0.0)
    parser.add_argument("--final-recommendation-json", default="final_recommendation.json")
    parser.add_argument("--final-recommendation-md", default="final_recommendation.md")
    return parser.parse_args()


if __name__ == "__main__":
    run_comparison(parse_args())
