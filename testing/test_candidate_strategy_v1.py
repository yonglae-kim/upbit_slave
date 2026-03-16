import unittest
from dataclasses import replace
from typing import cast

import core.strategies.candidate_v1 as candidate_v1
from core.config import TradingConfig
from core.decision_core import evaluate_market
from core.decision_models import (
    DecisionContext,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    StrategySignal,
)
from core.position_policy import PositionOrderPolicy
from core.strategy import StrategyParams, classify_market_regime


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


def candles_from_closes(
    closes_oldest: list[float],
    *,
    spread: float = 0.35,
) -> list[dict[str, object]]:
    candles_oldest: list[dict[str, object]] = []
    prev_close = closes_oldest[0] - 0.2
    for close_price in closes_oldest:
        open_price = prev_close
        high_price = max(open_price, close_price) + spread
        low_price = min(open_price, close_price) - spread
        candles_oldest.append(candle(open_price, high_price, low_price, close_price))
        prev_close = close_price
    return list(reversed(candles_oldest))


def trade_price(candle_data: dict[str, object]) -> float:
    value = candle_data.get("trade_price", 0.0)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def numeric_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def object_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        raw_mapping = cast(dict[object, object], value)
        return {str(key): item for key, item in raw_mapping.items()}
    return {}


def contract_test_params() -> StrategyParams:
    config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
    return replace(
        config.to_strategy_params(),
        strategy_name="candidate_v1",
        regime_ema_fast=5,
        regime_ema_slow=10,
        regime_adx_period=5,
        regime_adx_min=10.0,
        regime_slope_lookback=2,
    )


def contract_test_1m() -> list[dict[str, object]]:
    closes_oldest = [
        100.0,
        100.25,
        100.5,
        100.8,
        101.1,
        101.35,
        101.6,
        101.9,
        102.1,
        101.8,
        101.45,
        101.2,
        102.35,
    ]
    return candles_from_closes(closes_oldest, spread=0.22)


def contract_test_5m() -> list[dict[str, object]]:
    closes_oldest = [100.0 + (idx * 0.45) for idx in range(18)]
    return candles_from_closes(closes_oldest, spread=0.4)


def contract_test_15m() -> list[dict[str, object]]:
    closes_oldest = [100.0 + (idx * 0.9) for idx in range(40)]
    return candles_from_closes(closes_oldest, spread=0.6)


class CandidateStrategyV1Test(unittest.TestCase):
    def _make_params(self, **overrides: object) -> StrategyParams:
        config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
        params = replace(
            config.to_strategy_params(),
            strategy_name="candidate_v1",
            regime_ema_fast=5,
            regime_ema_slow=10,
            regime_adx_period=5,
            regime_slope_lookback=2,
        )
        return replace(params, **overrides)

    def _make_order_policy(self) -> PositionOrderPolicy:
        config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
        return PositionOrderPolicy(
            stop_loss_threshold=config.stop_loss_threshold,
            trailing_stop_pct=config.trailing_stop_pct,
            partial_take_profit_threshold=config.partial_take_profit_threshold,
            partial_take_profit_ratio=config.partial_take_profit_ratio,
            partial_stop_loss_ratio=config.partial_stop_loss_ratio,
            exit_mode=config.exit_mode,
            atr_period=config.atr_period,
            atr_stop_mult=config.atr_stop_mult,
            atr_trailing_mult=config.atr_trailing_mult,
            swing_lookback=config.swing_lookback,
        )

    def _strong_trend_15m(self) -> list[dict[str, object]]:
        closes_oldest = [100.0 + (idx * 0.9) for idx in range(40)]
        return candles_from_closes(closes_oldest, spread=0.6)

    def _weak_trend_15m(self) -> list[dict[str, object]]:
        price = 100.0
        closes_oldest: list[float] = []
        for step in [0.85, -0.35, 0.75, -0.25, 0.65, -0.2] * 8:
            price += step
            closes_oldest.append(price)
        return candles_from_closes(closes_oldest, spread=0.7)

    def _sideways_15m(self) -> list[dict[str, object]]:
        closes_oldest = [100.0 + ((-1) ** idx) * 0.25 for idx in range(40)]
        return candles_from_closes(closes_oldest, spread=0.8)

    def _trend_5m(self) -> list[dict[str, object]]:
        closes_oldest = [100.0 + (idx * 0.45) for idx in range(18)]
        return candles_from_closes(closes_oldest, spread=0.4)

    def _pullback_reclaim_1m(
        self, *, reclaim_confirmed: bool = True
    ) -> list[dict[str, object]]:
        closes_oldest = [
            100.0,
            100.25,
            100.5,
            100.8,
            101.1,
            101.35,
            101.6,
            101.9,
            102.1,
            101.8,
            101.45,
            101.2,
            102.35 if reclaim_confirmed else 101.95,
        ]
        return candles_from_closes(closes_oldest, spread=0.22)

    def _market_data(
        self,
        *,
        candles_1m: list[dict[str, object]],
        candles_15m: list[dict[str, object]],
        candles_5m: list[dict[str, object]] | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        return {
            "1m": candles_1m,
            "5m": self._trend_5m() if candles_5m is None else candles_5m,
            "15m": candles_15m,
        }

    def test_insufficient_1m_data_is_explicitly_reported(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m()[:4],
            candles_15m=self._strong_trend_15m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "insufficient_1m_candles")
        self.assertEqual(result.diagnostics["required_1m"], 6)
        self.assertEqual(result.diagnostics["actual_1m"], 4)

    def test_insufficient_15m_data_is_explicitly_reported(self):
        params = self._make_params(regime_adx_min=10.0)
        short_15m = self._strong_trend_15m()[:8]
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=short_15m,
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "insufficient_15m_candles")
        self.assertEqual(result.diagnostics["required_15m"], 10)
        self.assertEqual(result.diagnostics["actual_15m"], 8)

    def test_insufficient_5m_data_is_explicitly_reported(self):
        params = self._make_params(regime_adx_min=10.0)
        short_5m = self._trend_5m()[:4]
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(),
            candles_5m=short_5m,
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "insufficient_5m_candles")
        self.assertEqual(result.diagnostics["required_5m"], 6)
        self.assertEqual(result.diagnostics["actual_5m"], 4)

    def test_skips_sideways_regime_even_with_pullback_reclaim_shape(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._sideways_15m(),
        )

        self.assertEqual(classify_market_regime(data["15m"], params), "sideways")

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "regime_blocked")
        self.assertEqual(result.diagnostics["regime"], "sideways")

    def test_enters_on_strong_trend_pullback_reclaim_setup(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(),
        )

        self.assertEqual(classify_market_regime(data["15m"], params), "strong_trend")

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.diagnostics["regime"], "strong_trend")
        self.assertTrue(result.diagnostics["trend_confirmed_5m"])
        self.assertTrue(result.diagnostics["reclaim_confirmed"])
        self.assertGreater(
            numeric_value(result.diagnostics["entry_price"]),
            numeric_value(result.diagnostics["stop_price"]),
        )
        self.assertEqual(
            numeric_value(result.diagnostics["r_value"]),
            numeric_value(result.diagnostics["entry_price"])
            - numeric_value(result.diagnostics["stop_price"]),
        )
        self.assertEqual(result.diagnostics["entry_score"], 4.0)
        self.assertEqual(result.diagnostics["quality_score"], 0.55)

    def test_enters_on_weak_trend_pullback_reclaim_setup(self):
        params = self._make_params(regime_adx_min=90.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._weak_trend_15m(),
        )

        self.assertEqual(classify_market_regime(data["15m"], params), "weak_trend")

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.diagnostics["regime"], "weak_trend")

    def test_rejects_when_reclaim_confirmation_is_missing(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(reclaim_confirmed=False),
            candles_15m=self._strong_trend_15m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "reclaim_missing")
        self.assertFalse(result.diagnostics["reclaim_confirmed"])

    def test_diagnostics_are_stable_and_include_stop_basis_and_regime(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(),
        )

        first = candidate_v1.evaluate_long_entry(data, params)
        second = candidate_v1.evaluate_long_entry(data, params)

        self.assertEqual(first.diagnostics, second.diagnostics)
        self.assertEqual(first.diagnostics["regime"], "strong_trend")
        self.assertEqual(first.diagnostics["stop_basis"], "pullback_low")
        self.assertIn("stop_price", first.diagnostics)
        self.assertIn("r_value", first.diagnostics)

    def test_candidate_strategy_has_no_strategy_exit_signal(self):
        self.assertFalse(
            candidate_v1.should_exit_long(
                self._market_data(
                    candles_1m=self._pullback_reclaim_1m(),
                    candles_15m=self._strong_trend_15m(),
                ),
                self._make_params(regime_adx_min=10.0),
                entry_price=102.35,
                initial_stop_price=101.2,
                risk_per_unit=1.15,
            )
        )

    def test_evaluate_market_enters_candidate_v1_through_shared_seam(self):
        candles_1m = self._pullback_reclaim_1m()
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=self._market_data(
                    candles_1m=candles_1m,
                    candles_15m=self._strong_trend_15m(),
                ),
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_params(regime_adx_min=10.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.reason, "ok")
        self.assertEqual(intent.diagnostics["strategy_name"], "candidate_v1")
        self.assertEqual(intent.diagnostics["entry_regime"], "strong_trend")
        self.assertEqual(
            intent.diagnostics["regime"], intent.diagnostics["entry_regime"]
        )
        self.assertEqual(intent.diagnostics["stop_basis"], "pullback_low")
        self.assertEqual(
            intent.next_position_state["entry_regime"],
            intent.diagnostics["entry_regime"],
        )
        self.assertEqual(intent.diagnostics["entry_score"], 4.0)
        self.assertEqual(intent.diagnostics["quality_score"], 0.55)
        self.assertEqual(intent.diagnostics["entry_price"], 102.35)
        self.assertEqual(intent.diagnostics["stop_price"], 100.98)
        self.assertLess(abs(numeric_value(intent.diagnostics["r_value"]) - 1.37), 1e-9)
        self.assertEqual(intent.next_position_state["entry_price"], 102.35)
        self.assertEqual(intent.next_position_state["initial_stop_price"], 100.98)

    def test_evaluate_market_bypasses_quality_bucket_multiplier_for_candidate(self):
        candles_1m = self._pullback_reclaim_1m()
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=self._market_data(
                    candles_1m=candles_1m,
                    candles_15m=self._strong_trend_15m(),
                ),
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
            diagnostics={
                "entry_sizing_policy": {
                    "risk_per_trade_pct": 0.01,
                    "fee_rate": 0.0,
                    "max_holdings": 1,
                    "position_sizing_mode": "risk_first",
                    "max_order_krw_by_cash_management": 1_000_000.0,
                    "quality_score_low_threshold": 0.35,
                    "quality_score_high_threshold": 0.5,
                    "quality_multiplier_low": 0.7,
                    "quality_multiplier_mid": 1.1,
                    "quality_multiplier_high": 1.8,
                    "quality_multiplier_min_bound": 0.7,
                    "quality_multiplier_max_bound": 2.0,
                }
            },
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_params(regime_adx_min=10.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.diagnostics["quality_multiplier"], 1.0)
        sizing = object_dict(intent.diagnostics["sizing"])
        self.assertEqual(
            sizing["final_order_krw"],
            sizing["base_order_krw"],
        )

    def test_entry_regime_owns_seam_label_when_overrides_are_active(self):
        candles_1m = self._pullback_reclaim_1m()
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=self._market_data(
                    candles_1m=candles_1m,
                    candles_15m=self._strong_trend_15m(),
                ),
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
            diagnostics={
                "regime_strategy_overrides": {
                    "strong_trend": {"quality_score_high_threshold": 0.95}
                }
            },
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_params(regime_adx_min=10.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.diagnostics["entry_regime"], "strong_trend")
        self.assertEqual(intent.diagnostics["regime"], "strong_trend")
        self.assertEqual(intent.next_position_state["entry_regime"], "strong_trend")

    def test_seam_regime_label_tracks_post_override_classification(self):
        candles_1m = self._pullback_reclaim_1m()
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=self._market_data(
                    candles_1m=candles_1m,
                    candles_15m=self._strong_trend_15m(),
                ),
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
            diagnostics={
                "regime_strategy_overrides": {"strong_trend": {"regime_adx_min": 200.0}}
            },
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_params(regime_adx_min=10.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "regime_blocked")
        self.assertEqual(intent.diagnostics["entry_regime"], "sideways")
        self.assertEqual(intent.diagnostics["regime"], "sideways")


class SharedEntrySignalContractTest(unittest.TestCase):
    def test_candidate_entry_evaluator_returns_strategy_agnostic_signal(self):
        params = contract_test_params()
        data = {
            "1m": contract_test_1m(),
            "5m": contract_test_5m(),
            "15m": contract_test_15m(),
        }

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertIsInstance(result, StrategySignal)


if __name__ == "__main__":
    _ = unittest.main()
