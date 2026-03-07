import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from testing.strategy_selector import SelectorConstraints, save_recommendation, select_recommendation


class StrategySelectorTest(unittest.TestCase):
    def test_select_recommendation_applies_constraints_and_robustness(self):
        comparison_df = pd.DataFrame(
            [
                {
                    "profile": "baseline",
                    "profile_label": "Baseline",
                    "description": "base",
                    "oos_monthly_trades": 10.0,
                    "oos_expectancy": 0.10,
                    "oos_profit_factor": 1.20,
                    "oos_mdd": 8.0,
                    "oos_win_rate": 50.0,
                },
                {
                    "profile": "a",
                    "profile_label": "A",
                    "description": "candidate-a",
                    "oos_monthly_trades": 13.5,
                    "oos_expectancy": 0.12,
                    "oos_profit_factor": 1.25,
                    "oos_mdd": 8.1,
                    "oos_win_rate": 49.0,
                },
                {
                    "profile": "b",
                    "profile_label": "B",
                    "description": "candidate-b",
                    "oos_monthly_trades": 14.0,
                    "oos_expectancy": 0.13,
                    "oos_profit_factor": 1.30,
                    "oos_mdd": 7.9,
                    "oos_win_rate": 52.0,
                },
            ]
        )
        sensitivity_df = pd.DataFrame(
            [
                {"profile": "a", "perturbation_pct": -10, "oos_monthly_trades": 13.2, "oos_expectancy": 0.11, "oos_profit_factor": 1.22, "oos_mdd": 8.1},
                {"profile": "a", "perturbation_pct": 20, "oos_monthly_trades": 11.5, "oos_expectancy": 0.09, "oos_profit_factor": 1.15, "oos_mdd": 8.5},
                {"profile": "b", "perturbation_pct": -10, "oos_monthly_trades": 13.9, "oos_expectancy": 0.12, "oos_profit_factor": 1.29, "oos_mdd": 7.8},
                {"profile": "b", "perturbation_pct": 20, "oos_monthly_trades": 14.3, "oos_expectancy": 0.12, "oos_profit_factor": 1.28, "oos_mdd": 7.9},
            ]
        )

        selected_df, recommendation = select_recommendation(
            comparison_df,
            constraints=SelectorConstraints(min_monthly_trades_increase=0.30, mdd_buffer=0.5),
            sensitivity_df=sensitivity_df,
        )

        row_a = selected_df.loc[selected_df["profile"] == "a"].iloc[0]
        self.assertAlmostEqual(float(row_a["robustness_score"]), 0.5, places=6)
        self.assertEqual(recommendation["recommended_profile"], "b")
        self.assertIn("win_rate", recommendation["guardrail_note"])

    def test_save_recommendation_writes_json_and_markdown(self):
        recommendation = {
            "recommended_profile": "b",
            "recommended_label": "B",
            "description": "candidate-b",
            "all_constraints_pass": True,
            "constraint_pass_count": 4,
            "constraint_results": {
                "monthly_trades": "pass",
                "expectancy": "pass",
                "profit_factor": "pass",
                "mdd": "pass",
            },
            "guardrail_note": "win_rate는 보조지표",
            "thresholds": {
                "required_monthly_trades": 13.0,
                "baseline_expectancy": 0.1,
                "baseline_profit_factor": 1.2,
                "max_allowed_mdd": 8.5,
                "min_monthly_trades_increase": 0.3,
                "mdd_buffer": 0.5,
            },
            "metrics": {
                "oos_monthly_trades": 14.0,
                "oos_expectancy": 0.13,
                "oos_profit_factor": 1.3,
                "oos_mdd": 7.9,
                "oos_win_rate": 52.0,
                "robustness_score": 1.0,
                "selection_score": 2.0,
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            json_path = base / "final_recommendation.json"
            md_path = base / "final_recommendation.md"
            save_recommendation(recommendation, json_path=json_path, markdown_path=md_path)

            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["recommended_profile"], "b")
            self.assertIn("Final Strategy Recommendation", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
