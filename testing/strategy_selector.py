from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SelectorConstraints:
    min_monthly_trades_increase: float = 0.30
    mdd_buffer: float = 0.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(v: bool) -> str:
    return "pass" if v else "fail"


def _build_robustness_map(
    sensitivity_df: pd.DataFrame | None,
    baseline_row: pd.Series,
    constraints: SelectorConstraints,
) -> dict[str, float]:
    if sensitivity_df is None or sensitivity_df.empty or "profile" not in sensitivity_df.columns:
        return {}

    df = sensitivity_df.copy()
    if "perturbation_pct" in df.columns:
        perturb = pd.to_numeric(df["perturbation_pct"], errors="coerce").abs()
        mask = perturb.between(10.0, 20.0)
        filtered = df.loc[mask].copy()
        if not filtered.empty:
            df = filtered

    baseline_monthly = _to_float(baseline_row.get("oos_monthly_trades"), _to_float(baseline_row.get("monthly_trades"), 0.0))
    baseline_expectancy = _to_float(baseline_row.get("oos_expectancy"), _to_float(baseline_row.get("expectancy"), 0.0))
    baseline_profit_factor = _to_float(baseline_row.get("oos_profit_factor"), _to_float(baseline_row.get("profit_factor"), 0.0))
    baseline_mdd = _to_float(baseline_row.get("oos_mdd"), _to_float(baseline_row.get("mdd"), 0.0))

    req_monthly = baseline_monthly * (1.0 + constraints.min_monthly_trades_increase)
    robustness: dict[str, float] = {}
    for profile, group in df.groupby("profile"):
        monthly = pd.to_numeric(group.get("oos_monthly_trades", group.get("monthly_trades")), errors="coerce")
        expectancy = pd.to_numeric(group.get("oos_expectancy", group.get("expectancy")), errors="coerce")
        profit_factor = pd.to_numeric(group.get("oos_profit_factor", group.get("profit_factor")), errors="coerce")
        mdd = pd.to_numeric(group.get("oos_mdd", group.get("mdd")), errors="coerce")
        valid = monthly.notna() & expectancy.notna() & profit_factor.notna() & mdd.notna()
        if not valid.any():
            robustness[str(profile)] = 0.0
            continue
        pass_mask = (
            (monthly >= req_monthly)
            & (expectancy >= baseline_expectancy)
            & (profit_factor >= baseline_profit_factor)
            & (mdd <= baseline_mdd + constraints.mdd_buffer)
        )
        robustness[str(profile)] = float(pass_mask[valid].mean())
    return robustness


def select_recommendation(
    comparison_df: pd.DataFrame,
    constraints: SelectorConstraints,
    sensitivity_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if comparison_df.empty:
        raise ValueError("comparison_df is empty")

    df = comparison_df.copy()
    df["profile"] = df["profile"].astype(str)

    baseline_candidates = df.loc[df["profile"] == "baseline"]
    if baseline_candidates.empty:
        raise ValueError("baseline profile not found in comparison_df")
    baseline = baseline_candidates.iloc[0]

    baseline_monthly = _to_float(baseline.get("oos_monthly_trades"), _to_float(baseline.get("monthly_trades"), 0.0))
    baseline_expectancy = _to_float(baseline.get("oos_expectancy"), _to_float(baseline.get("expectancy"), 0.0))
    baseline_profit_factor = _to_float(baseline.get("oos_profit_factor"), _to_float(baseline.get("profit_factor"), 0.0))
    baseline_mdd = _to_float(baseline.get("oos_mdd"), _to_float(baseline.get("mdd"), 0.0))

    required_monthly = baseline_monthly * (1.0 + constraints.min_monthly_trades_increase)

    robustness_map = _build_robustness_map(sensitivity_df, baseline, constraints)

    df["target_monthly_trades"] = required_monthly
    df["rule_monthly_trades"] = pd.to_numeric(df.get("oos_monthly_trades", df.get("monthly_trades")), errors="coerce") >= required_monthly
    df["rule_expectancy"] = pd.to_numeric(df.get("oos_expectancy", df.get("expectancy")), errors="coerce") >= baseline_expectancy
    df["rule_profit_factor"] = pd.to_numeric(df.get("oos_profit_factor", df.get("profit_factor")), errors="coerce") >= baseline_profit_factor
    df["rule_mdd"] = pd.to_numeric(df.get("oos_mdd", df.get("mdd")), errors="coerce") <= (baseline_mdd + constraints.mdd_buffer)
    df["constraint_pass_count"] = (
        df[["rule_monthly_trades", "rule_expectancy", "rule_profit_factor", "rule_mdd"]]
        .fillna(False)
        .sum(axis=1)
        .astype(int)
    )
    df["all_constraints_pass"] = df["constraint_pass_count"] == 4
    df["robustness_score"] = df["profile"].map(robustness_map).fillna(0.0)

    oos_monthly = pd.to_numeric(df.get("oos_monthly_trades", df.get("monthly_trades")), errors="coerce").fillna(0.0)
    oos_expectancy = pd.to_numeric(df.get("oos_expectancy", df.get("expectancy")), errors="coerce").fillna(0.0)
    oos_profit_factor = pd.to_numeric(df.get("oos_profit_factor", df.get("profit_factor")), errors="coerce").fillna(0.0)
    oos_mdd = pd.to_numeric(df.get("oos_mdd", df.get("mdd")), errors="coerce").fillna(0.0)
    oos_win_rate = pd.to_numeric(df.get("oos_win_rate", df.get("win_rate")), errors="coerce").fillna(0.0)

    monthly_gain = (oos_monthly - required_monthly).clip(lower=0.0)
    expectancy_gain = (oos_expectancy - baseline_expectancy).clip(lower=0.0)
    profit_factor_gain = (oos_profit_factor - baseline_profit_factor).clip(lower=0.0)
    mdd_headroom = ((baseline_mdd + constraints.mdd_buffer) - oos_mdd).clip(lower=0.0)
    win_rate_gain = (oos_win_rate - _to_float(baseline.get("oos_win_rate"), _to_float(baseline.get("win_rate"), 0.0))).clip(lower=0.0)

    df["selection_score"] = (
        monthly_gain * 0.30
        + expectancy_gain * 0.30
        + profit_factor_gain * 0.25
        + mdd_headroom * 0.10
        + df["robustness_score"] * 0.30
        + win_rate_gain * 0.02
    )

    preferred_pool = df.loc[df["all_constraints_pass"]].copy()
    if preferred_pool.empty:
        preferred_pool = df.copy()

    preferred_pool = preferred_pool.sort_values(
        by=[
            "all_constraints_pass",
            "constraint_pass_count",
            "robustness_score",
            "selection_score",
            "oos_expectancy",
            "oos_profit_factor",
            "oos_monthly_trades",
        ],
        ascending=[False, False, False, False, False, False, False],
    )
    selected = preferred_pool.iloc[0]

    recommendation = {
        "recommended_profile": str(selected["profile"]),
        "recommended_label": str(selected.get("profile_label", selected["profile"])),
        "description": str(selected.get("description", "")),
        "all_constraints_pass": bool(selected["all_constraints_pass"]),
        "constraint_pass_count": int(selected["constraint_pass_count"]),
        "constraint_results": {
            "monthly_trades": _bool(bool(selected["rule_monthly_trades"])),
            "expectancy": _bool(bool(selected["rule_expectancy"])),
            "profit_factor": _bool(bool(selected["rule_profit_factor"])),
            "mdd": _bool(bool(selected["rule_mdd"])),
        },
        "guardrail_note": "win_rate는 보조지표로만 사용하며 단독 최적화 기준으로 사용하지 않습니다.",
        "thresholds": {
            "required_monthly_trades": required_monthly,
            "baseline_expectancy": baseline_expectancy,
            "baseline_profit_factor": baseline_profit_factor,
            "max_allowed_mdd": baseline_mdd + constraints.mdd_buffer,
            "min_monthly_trades_increase": constraints.min_monthly_trades_increase,
            "mdd_buffer": constraints.mdd_buffer,
        },
        "metrics": {
            "oos_monthly_trades": _to_float(selected.get("oos_monthly_trades"), _to_float(selected.get("monthly_trades"), 0.0)),
            "oos_expectancy": _to_float(selected.get("oos_expectancy"), _to_float(selected.get("expectancy"), 0.0)),
            "oos_profit_factor": _to_float(selected.get("oos_profit_factor"), _to_float(selected.get("profit_factor"), 0.0)),
            "oos_mdd": _to_float(selected.get("oos_mdd"), _to_float(selected.get("mdd"), 0.0)),
            "oos_win_rate": _to_float(selected.get("oos_win_rate"), _to_float(selected.get("win_rate"), 0.0)),
            "robustness_score": _to_float(selected.get("robustness_score"), 0.0),
            "selection_score": _to_float(selected.get("selection_score"), 0.0),
        },
    }

    return df, recommendation


def save_recommendation(recommendation: dict[str, Any], *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(recommendation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    c = recommendation["constraint_results"]
    m = recommendation["metrics"]
    t = recommendation["thresholds"]
    lines = [
        "# Final Strategy Recommendation",
        "",
        f"- recommended_profile: **{recommendation['recommended_profile']}** ({recommendation['recommended_label']})",
        f"- description: {recommendation['description']}",
        f"- constraints: {recommendation['constraint_pass_count']}/4 pass (all_pass={recommendation['all_constraints_pass']})",
        f"- guardrail: {recommendation['guardrail_note']}",
        "",
        "## Constraint Checks",
        "",
        f"- monthly_trades: {c['monthly_trades']} (required >= {t['required_monthly_trades']:.3f})",
        f"- expectancy: {c['expectancy']} (baseline >= {t['baseline_expectancy']:.6f})",
        f"- profit_factor: {c['profit_factor']} (baseline >= {t['baseline_profit_factor']:.6f})",
        f"- mdd: {c['mdd']} (max <= {t['max_allowed_mdd']:.6f})",
        "",
        "## Recommended OOS Metrics",
        "",
        f"- oos_monthly_trades: {m['oos_monthly_trades']:.6f}",
        f"- oos_expectancy: {m['oos_expectancy']:.6f}",
        f"- oos_profit_factor: {m['oos_profit_factor']:.6f}",
        f"- oos_mdd: {m['oos_mdd']:.6f}",
        f"- oos_win_rate (auxiliary only): {m['oos_win_rate']:.6f}",
        f"- robustness_score: {m['robustness_score']:.6f}",
        f"- selection_score: {m['selection_score']:.6f}",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
