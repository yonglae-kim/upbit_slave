import unittest
from dataclasses import replace
from unittest.mock import patch

import core.strategies.candidate_v1 as candidate_v1
from core.config import TradingConfig
from core.strategy import StrategyParams


def candle(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> dict[str, object]:
    return {
        "opening_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "trade_price": close_price,
    }


class CandidateStrategyV1Test(unittest.TestCase):
    def _make_params(self, **overrides: object) -> StrategyParams:
        config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
        params = replace(config.to_strategy_params(), strategy_name="candidate_v1")
        return replace(params, **overrides)

    def _market_data(self, price: float = 101.4) -> dict[str, list[dict[str, object]]]:
        return {
            "1m": [candle(price - 0.2, price + 0.2, price - 0.4, price)],
            "5m": [candle(100.8, 101.2, 100.4, 101.0)],
            "15m": [candle(100.5, 101.5, 100.0, 101.2)],
            "meta": [{"symbol": "KRW-BTC"}],
        }

    def _passing_debug(self) -> dict[str, object]:
        return {
            "final_pass": True,
            "fail_code": "pass",
            "regime_filter_metrics": {"pass": True, "regime": "strong_trend"},
            "zones_total": 3,
            "zones_active": 1,
            "sr_flip_pass": True,
            "sr_flip_level": {
                "bias": "resistance",
                "lower": 100.0,
                "upper": 100.4,
                "score": 0.9,
            },
            "selected_zone": {
                "type": "ob",
                "bias": "bullish",
                "lower": 100.2,
                "upper": 100.8,
            },
            "trigger_pass": True,
        }

    def test_entry_maps_debug_engine_pass_to_strategy_signal(self):
        with patch.object(
            candidate_v1,
            "debug_entry",
            create=True,
            return_value=self._passing_debug(),
        ):
            result = candidate_v1.evaluate_long_entry(
                self._market_data(),
                self._make_params(entry_score_threshold=3.6),
            )

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.diagnostics["regime"], "strong_trend")
        self.assertEqual(result.diagnostics["selected_zone_type"], "ob")
        self.assertTrue(result.diagnostics["sr_flip_pass"])
        self.assertTrue(result.diagnostics["proof_window_active"])
        self.assertGreater(result.diagnostics["entry_score"], 3.6)
        self.assertGreater(
            result.diagnostics["entry_price"], result.diagnostics["stop_price"]
        )

    def test_entry_returns_helper_fail_code_when_setup_is_rejected(self):
        with patch.object(
            candidate_v1,
            "debug_entry",
            create=True,
            return_value={
                "final_pass": False,
                "fail_code": "sr_flip_hold_miss",
                "regime_filter_metrics": {"pass": True, "regime": "strong_trend"},
                "zones_total": 1,
                "zones_active": 1,
                "sr_flip_pass": False,
                "sr_flip_level": None,
                "selected_zone": None,
                "trigger_pass": False,
            },
        ):
            result = candidate_v1.evaluate_long_entry(
                self._market_data(),
                self._make_params(),
            )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "sr_flip_hold_miss")
        self.assertFalse(result.diagnostics["proof_window_active"])
        self.assertFalse(result.diagnostics["sr_flip_pass"])

    def test_entry_rejects_when_stop_is_not_below_entry(self):
        debug_payload = self._passing_debug()
        debug_payload["selected_zone"] = {
            "type": "ob",
            "bias": "bullish",
            "lower": 101.5,
            "upper": 101.8,
        }
        debug_payload["sr_flip_level"] = {
            "bias": "resistance",
            "lower": 101.6,
            "upper": 101.9,
            "score": 0.9,
        }
        with patch.object(
            candidate_v1,
            "debug_entry",
            create=True,
            return_value=debug_payload,
        ):
            result = candidate_v1.evaluate_long_entry(
                self._market_data(price=101.4),
                self._make_params(),
            )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "safety_fail")

    def test_should_exit_long_delegates_to_strategy_sell_engine(self):
        with patch.object(
            candidate_v1,
            "check_sell",
            create=True,
            return_value=True,
        ) as sell_mock:
            result = candidate_v1.should_exit_long(
                self._market_data(),
                self._make_params(),
                entry_price=100.0,
                initial_stop_price=98.0,
                risk_per_unit=2.0,
            )

        self.assertTrue(result)
        self.assertEqual(sell_mock.call_args.kwargs["avg_buy_price"], 100.0)
        sell_params = sell_mock.call_args.kwargs["params"]
        self.assertEqual(sell_params.trigger_mode, "adaptive")
        self.assertEqual(sell_params.required_trigger_count, 1)


if __name__ == "__main__":
    unittest.main()
