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
    def _default_candidate_params(self) -> StrategyParams:
        config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
        return replace(config.to_strategy_params(), strategy_name="candidate_v1")

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

    def _strong_trend_15m(self, candle_count: int = 40) -> list[dict[str, object]]:
        closes_oldest = [100.0 + (idx * 0.9) for idx in range(candle_count)]
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

    def _broken_5m_reset(self) -> list[dict[str, object]]:
        closes_oldest = [
            100.0,
            100.5,
            101.0,
            101.4,
            101.8,
            102.1,
            102.4,
            102.6,
            102.2,
            101.7,
            101.3,
            101.0,
            100.8,
            100.7,
            100.6,
            100.55,
            100.5,
            100.45,
        ]
        return candles_from_closes(closes_oldest, spread=0.45)

    def _shallow_5m_reset(self) -> list[dict[str, object]]:
        candles_newest = self._trend_5m()
        candles_newest[1]["low_price"] = 107.15
        candles_newest[2]["low_price"] = 107.2
        candles_newest[3]["low_price"] = 107.25
        return candles_newest

    def _reset_low_dominant_5m(self) -> list[dict[str, object]]:
        closes_oldest = [
            99.0,
            99.3,
            99.6,
            99.9,
            100.2,
            100.6,
            101.0,
            101.3,
            101.0,
            100.8,
            101.4,
            101.9,
        ]
        candles_newest = candles_from_closes(closes_oldest, spread=0.22)
        candles_newest[1]["low_price"] = 100.55
        candles_newest[2]["low_price"] = 100.7
        return candles_newest

    def _pullback_reclaim_1m(
        self,
        *,
        final_close: float = 102.35,
        final_open: float | None = None,
        deep_pullback_low: float | None = None,
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
            final_close,
        ]
        candles_newest = candles_from_closes(closes_oldest, spread=0.22)
        if final_open is not None:
            candles_newest[0]["opening_price"] = final_open
        if deep_pullback_low is not None:
            candles_newest[1]["low_price"] = deep_pullback_low
        return candles_newest

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

    def _market_data_with_symbol(
        self,
        *,
        symbol: str,
        candles_1m: list[dict[str, object]],
        candles_15m: list[dict[str, object]],
        candles_5m: list[dict[str, object]] | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        return {
            "1m": candles_1m,
            "5m": self._trend_5m() if candles_5m is None else candles_5m,
            "15m": candles_15m,
            "meta": [{"symbol": symbol}],
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

    def test_default_candidate_params_can_evaluate_on_short_horizon_15m_data(self):
        params = replace(self._default_candidate_params(), regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(candle_count=60),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.diagnostics["regime"], "strong_trend")

    def test_normalize_strategy_params_clamps_candidate_regime_window_exactly(self):
        params = replace(
            self._default_candidate_params(),
            regime_ema_fast=50,
            regime_ema_slow=200,
        )

        normalized = candidate_v1.normalize_strategy_params(params)

        self.assertEqual(normalized.regime_ema_fast, 8)
        self.assertEqual(normalized.regime_ema_slow, 34)

    def test_default_candidate_params_keep_true_15m_insufficiency_explicit(self):
        params = replace(self._default_candidate_params(), regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(candle_count=30),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "insufficient_15m_candles")
        self.assertGreater(numeric_value(result.diagnostics["required_15m"]), 30)
        self.assertLess(numeric_value(result.diagnostics["required_15m"]), 200)
        self.assertEqual(result.diagnostics["actual_15m"], 30)

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
        self.assertEqual(result.diagnostics["required_5m"], 8)
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
        self.assertEqual(result.diagnostics["regime_map_state"], "blocked")
        self.assertEqual(result.diagnostics["expected_hold_type"], "none")

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
        self.assertGreater(numeric_value(result.diagnostics["entry_score"]), 3.0)
        self.assertGreater(numeric_value(result.diagnostics["quality_score"]), 0.5)
        self.assertGreater(numeric_value(result.diagnostics["signal_quality"]), 0.5)
        self.assertEqual(result.diagnostics["expected_hold_type"], "trend_expansion")
        self.assertEqual(result.diagnostics["regime_map_state"], "trend_ready")
        self.assertEqual(
            numeric_value(result.diagnostics["invalidation_price"]),
            numeric_value(result.diagnostics["stop_price"]),
        )
        self.assertIn("reclaim_recovery_ratio", result.diagnostics)
        self.assertIn("pullback_depth_ratio", result.diagnostics)

    def test_rejects_when_5m_reset_context_is_lost_even_if_1m_reclaims(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(),
            candles_5m=self._broken_5m_reset(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "trend_context_fail")
        self.assertEqual(result.diagnostics["regime_map_state"], "trend_ready")
        self.assertFalse(result.diagnostics["trend_confirmed_5m"])

    def test_rejects_when_5m_setup_window_is_not_ready_even_if_trend_holds(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(),
            candles_5m=self._shallow_5m_reset(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "setup_context_fail")
        self.assertEqual(result.diagnostics["regime_map_state"], "trend_ready")
        self.assertTrue(result.diagnostics["trend_confirmed_5m"])
        self.assertFalse(result.diagnostics["setup_ready"])

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
        self.assertEqual(result.diagnostics["regime_map_state"], "trend_ready")
        self.assertEqual(result.diagnostics["expected_hold_type"], "trend_rotation")

    def test_accepts_partial_reclaim_that_recovers_most_of_pullback(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(final_close=101.95),
            candles_15m=self._strong_trend_15m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertTrue(result.diagnostics["reclaim_confirmed"])
        self.assertEqual(result.diagnostics["entry_price"], 101.95)
        self.assertEqual(result.diagnostics["stop_price"], 100.98)
        self.assertLess(abs(numeric_value(result.diagnostics["r_value"]) - 0.97), 1e-9)
        self.assertGreater(numeric_value(result.diagnostics["entry_score"]), 3.0)
        self.assertGreater(numeric_value(result.diagnostics["quality_score"]), 0.0)

    def test_accepts_reclaim_exactly_at_reclaim_floor_boundary(self):
        params = self._make_params(regime_adx_min=10.0, entry_score_threshold=3.25)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(final_close=101.65),
            candles_15m=self._strong_trend_15m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.diagnostics["reclaim_floor"], 101.65)
        self.assertEqual(result.diagnostics["entry_price"], 101.65)

    def test_rejects_boundary_reclaim_when_final_candle_is_not_bullish(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(
                final_close=101.65,
                final_open=101.8,
            ),
            candles_15m=self._strong_trend_15m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "reclaim_missing")
        self.assertFalse(result.diagnostics["reclaim_confirmed"])

    def test_rejects_when_pullback_is_oversized_even_if_reclaim_floor_is_recovered(
        self,
    ):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(
                final_close=101.95,
                deep_pullback_low=100.2,
            ),
            candles_15m=self._strong_trend_15m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "pullback_too_deep")
        self.assertGreater(
            numeric_value(result.diagnostics["pullback_depth_ratio"]), 1.3
        )

    def test_accepted_trade_diagnostics_vary_with_reclaim_strength(self):
        params = self._make_params(regime_adx_min=10.0)
        partial = candidate_v1.evaluate_long_entry(
            self._market_data(
                candles_1m=self._pullback_reclaim_1m(final_close=101.95),
                candles_15m=self._strong_trend_15m(),
            ),
            params,
        )
        stronger = candidate_v1.evaluate_long_entry(
            self._market_data(
                candles_1m=self._pullback_reclaim_1m(final_close=102.35),
                candles_15m=self._strong_trend_15m(),
            ),
            params,
        )

        self.assertTrue(partial.accepted)
        self.assertTrue(stronger.accepted)
        self.assertLess(
            numeric_value(partial.diagnostics["reclaim_recovery_ratio"]),
            numeric_value(stronger.diagnostics["reclaim_recovery_ratio"]),
        )
        self.assertLess(
            numeric_value(partial.diagnostics["entry_score"]),
            numeric_value(stronger.diagnostics["entry_score"]),
        )
        self.assertLess(
            numeric_value(partial.diagnostics["quality_score"]),
            numeric_value(stronger.diagnostics["quality_score"]),
        )

    def test_rejects_when_continuation_bounce_is_too_weak(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(final_close=101.55),
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

    def test_accepted_entry_initializes_proof_window_diagnostics(self):
        params = self._make_params(regime_adx_min=10.0)
        result = candidate_v1.evaluate_long_entry(
            self._market_data_with_symbol(
                symbol="KRW-BTC",
                candles_1m=self._pullback_reclaim_1m(),
                candles_15m=self._strong_trend_15m(),
            ),
            params,
        )

        self.assertTrue(result.accepted)
        self.assertTrue(result.diagnostics["proof_window_active"])
        self.assertFalse(result.diagnostics["proof_window_promoted"])
        self.assertEqual(result.diagnostics["proof_window_status"], "pending")
        self.assertEqual(result.diagnostics["proof_window_start_bar"], 0)
        self.assertEqual(result.diagnostics["proof_window_elapsed_bars"], 0)
        self.assertEqual(result.diagnostics["proof_window_max_bars"], 3)
        self.assertEqual(
            result.diagnostics["proof_window_max_favorable_excursion_r"], 0.0
        )
        self.assertGreater(
            numeric_value(result.diagnostics["proof_window_promotion_threshold_r"]),
            0.0,
        )
        self.assertEqual(result.diagnostics["proof_window_symbol_profile"], "default")
        self.assertEqual(result.diagnostics["proof_window_cooldown_hint_bars"], 0)

    def test_symbol_conditioned_proof_defaults_raise_threshold_for_weak_symbol(self):
        params = self._make_params(regime_adx_min=10.0)
        btc_result = candidate_v1.evaluate_long_entry(
            self._market_data_with_symbol(
                symbol="KRW-BTC",
                candles_1m=self._pullback_reclaim_1m(),
                candles_15m=self._strong_trend_15m(),
            ),
            params,
        )
        ada_result = candidate_v1.evaluate_long_entry(
            self._market_data_with_symbol(
                symbol="KRW-ADA",
                candles_1m=self._pullback_reclaim_1m(),
                candles_15m=self._strong_trend_15m(),
            ),
            params,
        )

        self.assertTrue(btc_result.accepted)
        self.assertTrue(ada_result.accepted)
        self.assertGreater(
            numeric_value(ada_result.diagnostics["proof_window_promotion_threshold_r"]),
            numeric_value(btc_result.diagnostics["proof_window_promotion_threshold_r"]),
        )
        self.assertGreater(
            numeric_value(ada_result.diagnostics["proof_window_cooldown_hint_bars"]),
            numeric_value(btc_result.diagnostics["proof_window_cooldown_hint_bars"]),
        )
        self.assertEqual(
            btc_result.diagnostics["proof_window_symbol_profile"], "default"
        )
        self.assertEqual(ada_result.diagnostics["proof_window_symbol_profile"], "weak")
        self.assertLess(
            numeric_value(ada_result.diagnostics["proof_window_max_bars"]),
            numeric_value(btc_result.diagnostics["proof_window_max_bars"]),
        )

    def test_uses_5m_reset_low_as_invalidation_when_it_is_lower_than_1m_pullback(self):
        params = self._make_params(regime_adx_min=10.0)
        data = self._market_data(
            candles_1m=self._pullback_reclaim_1m(),
            candles_15m=self._strong_trend_15m(),
            candles_5m=self._reset_low_dominant_5m(),
        )

        result = candidate_v1.evaluate_long_entry(data, params)

        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.diagnostics["stop_basis"], "reset_low_5m")
        self.assertLess(
            numeric_value(result.diagnostics["stop_price"]),
            100.98,
        )

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
        self.assertEqual(intent.diagnostics["regime_map_state"], "trend_ready")
        self.assertEqual(intent.diagnostics["expected_hold_type"], "trend_expansion")
        self.assertEqual(intent.diagnostics["stop_basis"], "pullback_low")
        self.assertEqual(
            intent.next_position_state["entry_regime"],
            intent.diagnostics["entry_regime"],
        )
        self.assertGreater(numeric_value(intent.diagnostics["entry_score"]), 0.0)
        self.assertGreater(numeric_value(intent.diagnostics["quality_score"]), 0.0)
        self.assertGreater(numeric_value(intent.diagnostics["signal_quality"]), 0.0)
        self.assertEqual(intent.diagnostics["entry_price"], 102.35)
        self.assertEqual(intent.diagnostics["stop_price"], 100.98)
        self.assertEqual(intent.diagnostics["invalidation_price"], 100.98)
        self.assertLess(abs(numeric_value(intent.diagnostics["r_value"]) - 1.37), 1e-9)
        self.assertEqual(intent.next_position_state["entry_price"], 102.35)
        self.assertEqual(intent.next_position_state["initial_stop_price"], 100.98)

    def test_evaluate_market_persists_candidate_stop_context_for_shared_exit_policy(
        self,
    ):
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
        self.assertEqual(intent.diagnostics["stop_basis"], "pullback_low")
        self.assertEqual(
            intent.next_position_state["stop_basis"], intent.diagnostics["stop_basis"]
        )
        self.assertEqual(
            numeric_value(intent.next_position_state["risk_per_unit"]),
            numeric_value(intent.diagnostics["r_value"]),
        )
        self.assertEqual(
            numeric_value(intent.next_position_state["initial_stop_price"]),
            numeric_value(intent.diagnostics["stop_price"]),
        )

    def test_evaluate_market_bypasses_quality_bucket_multiplier_for_candidate(self):
        candles_1m = self._pullback_reclaim_1m(final_close=101.95)
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
        self.assertEqual(intent.reason, "ok")
        self.assertEqual(intent.diagnostics["stop_basis"], "pullback_low")
        self.assertEqual(
            numeric_value(intent.diagnostics["r_value"]),
            numeric_value(intent.diagnostics["entry_price"])
            - numeric_value(intent.diagnostics["stop_price"]),
        )
        self.assertGreater(numeric_value(intent.diagnostics["entry_score"]), 0.0)
        self.assertGreater(numeric_value(intent.diagnostics["quality_score"]), 0.0)
        self.assertEqual(intent.diagnostics["quality_multiplier"], 1.0)
        sizing = object_dict(intent.diagnostics["sizing"])
        self.assertEqual(
            sizing["final_order_krw"],
            sizing["base_order_krw"],
        )
        self.assertEqual(
            sizing["base_order_krw"],
            sizing["risk_sized_order_krw"],
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
