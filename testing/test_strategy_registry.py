import unittest

from core.config import TradingConfig
from core.decision_models import StrategySignal
from core.strategy import StrategyParams
from core.strategy_registry import (
    UnknownStrategyError,
    get_strategy,
    normalize_strategy_name,
)


class StrategyRegistryTest(unittest.TestCase):
    def test_lookup_baseline_strategy(self):
        strategy = get_strategy("baseline")

        self.assertEqual(strategy.name, "baseline")
        self.assertEqual(strategy.canonical_name, "baseline")
        self.assertTrue(callable(strategy.entry_evaluator))
        self.assertTrue(callable(strategy.exit_evaluator))
        self.assertEqual(strategy.aliases, ("rsi_bb_reversal_long",))
        self.assertEqual(
            strategy.metadata["surface_module"], "core.strategies.baseline"
        )
        self.assertEqual(
            strategy.metadata["legacy_strategy_name"], "rsi_bb_reversal_long"
        )

    def test_legacy_alias_normalizes_to_canonical_strategy_identity(self):
        canonical_strategy = get_strategy("baseline")
        alias_strategy = get_strategy(" rsi_bb_reversal_long ")

        self.assertEqual(normalize_strategy_name(" rsi_bb_reversal_long "), "baseline")
        self.assertEqual(alias_strategy.canonical_name, "baseline")
        self.assertEqual(alias_strategy.name, canonical_strategy.name)
        self.assertTrue(callable(alias_strategy.entry_evaluator))
        self.assertTrue(callable(alias_strategy.exit_evaluator))
        self.assertEqual(alias_strategy.metadata, canonical_strategy.metadata)

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(UnknownStrategyError):
            _ = get_strategy("does_not_exist")

    def test_baseline_config_preserves_canonical_strategy_name(self):
        config = TradingConfig(do_not_trading=[], strategy_name="baseline")

        params = config.to_strategy_params()

        self.assertIsInstance(params, StrategyParams)
        self.assertEqual(params.strategy_name, "baseline")

    def test_registered_strategies_return_shared_strategy_signal_contract(self):
        baseline = get_strategy("baseline")
        candidate = get_strategy("candidate_v1")
        config = TradingConfig(do_not_trading=[], strategy_name="baseline")
        params = config.to_strategy_params()

        baseline_result = baseline.entry_evaluator({"1m": [], "15m": []}, params)
        candidate_result = candidate.entry_evaluator(
            {"1m": [], "5m": [], "15m": []}, params
        )

        self.assertIsInstance(baseline_result, StrategySignal)
        self.assertIsInstance(candidate_result, StrategySignal)


if __name__ == "__main__":
    _ = unittest.main()
