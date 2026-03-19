import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import core.strategies.candidate_v1 as candidate_v1
from core.config import TradingConfig
from core.decision_core import evaluate_market
from core.decision_models import (
    DecisionContext,
    DecisionIntent,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    StrategySignal,
)
from core.position_policy import ExitDecision
from core.position_policy import PositionOrderPolicy
from core.strategy import StrategyParams
from core.strategy_registry import RegisteredStrategy


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
    spread: float,
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


class DecisionModelsTest(unittest.TestCase):
    def test_market_position_and_portfolio_snapshots_are_plain_data(self):
        market = MarketSnapshot(symbol="KRW-BTC", candles_by_timeframe={"1m": []})
        position = PositionSnapshot()
        portfolio = PortfolioSnapshot(available_krw=1_000_000.0)

        self.assertEqual(market.symbol, "KRW-BTC")
        self.assertEqual(market.candles_by_timeframe, {"1m": []})
        self.assertIsNone(position.market)
        self.assertEqual(position.quantity, 0.0)
        self.assertEqual(position.state, {})
        self.assertEqual(portfolio.available_krw, 1_000_000.0)
        self.assertEqual(portfolio.open_positions, 0)
        self.assertEqual(portfolio.state, {})

    def test_decision_context_carries_strategy_and_snapshots(self):
        market = MarketSnapshot(symbol="KRW-BTC", candles_by_timeframe={"1m": []})
        position = PositionSnapshot(market="KRW-BTC", quantity=0.1)
        portfolio = PortfolioSnapshot(available_krw=500_000.0, open_positions=1)

        context = DecisionContext(
            strategy_name="baseline",
            market=market,
            position=position,
            portfolio=portfolio,
        )

        self.assertEqual(context.strategy_name, "baseline")
        self.assertIs(context.market, market)
        self.assertIs(context.position, position)
        self.assertIs(context.portfolio, portfolio)
        self.assertEqual(context.diagnostics, {})

    def test_decision_intent_contract_exposes_action_reason_and_state_payload(self):
        previous_state = {"cooldown": 2}
        intent = DecisionIntent(
            action="hold",
            reason="waiting_for_signal",
            diagnostics={"entry_score": 0.0},
            next_position_state={"cooldown": 0},
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "waiting_for_signal")
        self.assertEqual(intent.diagnostics, {"entry_score": 0.0})
        self.assertEqual(intent.next_position_state, {"cooldown": 0})
        self.assertNotEqual(intent.next_position_state, previous_state)

    def test_strategy_signal_contract_is_plain_data_for_shared_core(self):
        signal = StrategySignal(
            accepted=True,
            reason="entry_ready",
            diagnostics={"regime": "strong_trend", "entry_score": 3.1},
        )

        self.assertTrue(signal.accepted)
        self.assertEqual(signal.reason, "entry_ready")
        self.assertEqual(
            signal.diagnostics,
            {"regime": "strong_trend", "entry_score": 3.1},
        )


class DecisionCoreTest(unittest.TestCase):
    def _make_params(self) -> StrategyParams:
        config = TradingConfig(do_not_trading=[], strategy_name="baseline")
        return replace(
            config.to_strategy_params(),
            rsi_period=2,
            bb_period=2,
            pivot_left=1,
            pivot_right=1,
            regime_ema_fast=5,
            regime_ema_slow=10,
            regime_adx_period=5,
            regime_adx_min=10.0,
            regime_slope_lookback=2,
        )

    def _make_candidate_params(self) -> StrategyParams:
        config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
        return replace(
            config.to_strategy_params(),
            strategy_name="candidate_v1",
            regime_adx_min=10.0,
        )

    def _make_order_policy(self) -> PositionOrderPolicy:
        config = TradingConfig(do_not_trading=[], strategy_name="baseline")
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

    def _make_candidate_order_policy(self) -> PositionOrderPolicy:
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

    def _make_ict_params(self) -> StrategyParams:
        config = TradingConfig(do_not_trading=[], strategy_name="ict_v1")
        return config.to_strategy_params()

    def _make_ict_order_policy(self) -> PositionOrderPolicy:
        config = TradingConfig(do_not_trading=[], strategy_name="ict_v1")
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

    def _ready_candidate_debug(self, **overrides: object) -> dict[str, object]:
        result: dict[str, object] = {
            "final_pass": True,
            "fail_code": "pass",
            "regime_filter_metrics": {"pass": True, "regime": "strong_trend"},
            "zones_total": 3,
            "zones_active": 1,
            "selected_zone": {
                "type": "ob",
                "bias": "bullish",
                "lower": 100.9,
                "upper": 101.5,
            },
            "sr_flip_pass": True,
            "sr_flip_level": {
                "bias": "resistance",
                "lower": 100.8,
                "upper": 101.2,
                "score": 0.9,
            },
            "trigger_pass": True,
        }
        result.update(overrides)
        return result

    def _evaluate_candidate_entry_with_ready_zone(
        self,
        market_data: dict[str, list[dict[str, object]]],
        params: StrategyParams,
    ) -> StrategySignal:
        with patch.object(
            candidate_v1,
            "debug_entry",
            return_value=self._ready_candidate_debug(),
        ):
            return candidate_v1.evaluate_long_entry(market_data, params)

    def _evaluate_market_with_ready_zone(
        self,
        context: DecisionContext,
        *,
        strategy_params: StrategyParams,
        order_policy: PositionOrderPolicy,
    ) -> DecisionIntent:
        with patch.object(
            candidate_v1,
            "debug_entry",
            return_value=self._ready_candidate_debug(),
        ):
            return evaluate_market(
                context,
                strategy_params=strategy_params,
                order_policy=order_policy,
            )

    def test_hold_returns_copied_next_position_state_when_entry_does_not_pass(self):
        context = DecisionContext(
            strategy_name="baseline",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={"1m": self._entry_candles()},
                price=80.25,
            ),
            position=PositionSnapshot(state={"cooldown": 2}),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )
        params = self._make_params()

        intent = evaluate_market(
            context,
            strategy_params=replace(params, entry_score_threshold=999.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "score_below_threshold")
        self.assertEqual(intent.next_position_state, {"cooldown": 2})
        self.assertIsNot(intent.next_position_state, context.position.state)

    def test_enter_returns_baseline_diagnostics_and_next_position_state(self):
        market = MarketSnapshot(
            symbol="KRW-BTC",
            candles_by_timeframe={
                "1m": self._entry_candles(),
                "15m": self._weak_trend_candles(),
            },
            price=80.25,
            diagnostics={"current_atr": 1.5, "swing_low": 78.0, "regime": "weak_trend"},
        )
        context = DecisionContext(
            strategy_name="baseline",
            market=market,
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )
        params = self._make_params()

        intent = evaluate_market(
            context,
            strategy_params=replace(params, entry_score_threshold=0.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.reason, "ok")
        self.assertEqual(intent.diagnostics["strategy_name"], "baseline")
        self.assertIn("entry_score", intent.diagnostics)
        self.assertIn("stop_price", intent.diagnostics)
        self.assertEqual(intent.next_position_state["entry_regime"], "strong_trend")
        self.assertEqual(intent.next_position_state["entry_atr"], 1.5)
        self.assertEqual(intent.next_position_state["entry_swing_low"], 78.0)
        self.assertEqual(intent.next_position_state["peak_price"], 80.25)
        self.assertEqual(
            intent.next_position_state["initial_stop_price"],
            intent.diagnostics["stop_price"],
        )

    def test_exit_partial_returns_policy_state_without_mutating_snapshot(self):
        market = MarketSnapshot(
            symbol="KRW-BTC",
            candles_by_timeframe={
                "1m": [candle(102.0, 103.5, 101.8, 103.0)],
                "15m": [candle(102.0, 103.5, 101.8, 103.0)],
            },
            price=103.0,
            diagnostics={
                "current_atr": 1.0,
                "swing_low": 95.0,
                "regime": "strong_trend",
            },
        )
        initial_state: dict[str, object] = {
            "peak_price": 100.0,
            "entry_price": 100.0,
            "initial_stop_price": 95.0,
            "risk_per_unit": 5.0,
            "bars_held": 7,
        }
        context = DecisionContext(
            strategy_name="baseline",
            market=market,
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state=initial_state,
            ),
            portfolio=PortfolioSnapshot(available_krw=500_000.0, open_positions=1),
        )
        params = self._make_params()

        intent = evaluate_market(
            context,
            strategy_params=replace(params, entry_score_threshold=0.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(intent.action, "exit_partial")
        self.assertEqual(intent.reason, "partial_take_profit")
        self.assertTrue(intent.next_position_state["partial_take_profit_done"])
        self.assertEqual(intent.next_position_state["bars_held"], 8)
        self.assertEqual(intent.next_position_state["peak_price"], 103.0)
        self.assertIn("hard_stop_price", intent.diagnostics)
        self.assertEqual(context.position.state, initial_state)

    def test_exit_uses_cost_basis_for_policy_and_state_entry_for_strategy_signal(self):
        exit_evaluator = Mock(return_value=False)
        strategy = RegisteredStrategy(
            canonical_name="baseline",
            entry_evaluator=Mock(),
            exit_evaluator=exit_evaluator,
            aliases=("rsi_bb_reversal_long",),
            metadata={"legacy_strategy_name": "rsi_bb_reversal_long"},
        )
        context = DecisionContext(
            strategy_name="baseline",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={"1m": [candle(111.0, 111.0, 111.0, 111.0)]},
                price=111.0,
                diagnostics={"current_atr": 1.0, "swing_low": 95.0},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=120.0,
                state={
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 2,
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=500_000.0, open_positions=1),
        )

        with (
            patch("core.decision_core.get_strategy", return_value=strategy),
            patch(
                "core.decision_core.evaluate_position_state",
                return_value=(ExitDecision(False), {"bars_held": 3}),
            ) as evaluate_state_mock,
        ):
            intent = evaluate_market(
                context,
                strategy_params=self._make_params(),
                order_policy=self._make_order_policy(),
            )

        self.assertEqual(intent.action, "hold")
        exit_evaluator.assert_called_once()
        self.assertEqual(exit_evaluator.call_args.kwargs["entry_price"], 100.0)
        self.assertEqual(evaluate_state_mock.call_args.kwargs["avg_buy_price"], 120.0)

    def test_sell_decision_rule_and_requires_signal_and_policy(self):
        strategy = RegisteredStrategy(
            canonical_name="baseline",
            entry_evaluator=Mock(),
            exit_evaluator=Mock(return_value=False),
            aliases=("rsi_bb_reversal_long",),
            metadata={"legacy_strategy_name": "rsi_bb_reversal_long"},
        )
        context = DecisionContext(
            strategy_name="baseline",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={"1m": [candle(90.0, 90.0, 90.0, 90.0)]},
                price=90.0,
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=500_000.0, open_positions=1),
            diagnostics={"sell_decision_rule": "and"},
        )

        with (
            patch("core.decision_core.get_strategy", return_value=strategy),
            patch(
                "core.decision_core.evaluate_position_state",
                return_value=(ExitDecision(True, 1.0, "stop_loss"), {"bars_held": 1}),
            ),
        ):
            intent = evaluate_market(
                context,
                strategy_params=self._make_params(),
                order_policy=self._make_order_policy(),
            )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "hold")
        self.assertEqual(intent.next_position_state, {"bars_held": 1})

    def test_full_exit_resets_next_position_state(self):
        strategy = RegisteredStrategy(
            canonical_name="baseline",
            entry_evaluator=Mock(),
            exit_evaluator=Mock(return_value=True),
            aliases=("rsi_bb_reversal_long",),
            metadata={"legacy_strategy_name": "rsi_bb_reversal_long"},
        )
        context = DecisionContext(
            strategy_name="baseline",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={"1m": [candle(106.0, 106.0, 106.0, 106.0)]},
                price=106.0,
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 110.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 10,
                    "partial_take_profit_done": True,
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=500_000.0, open_positions=1),
        )

        with (
            patch("core.decision_core.get_strategy", return_value=strategy),
            patch(
                "core.decision_core.evaluate_position_state",
                return_value=(
                    ExitDecision(True, 1.0, "strategy_signal"),
                    {"bars_held": 11},
                ),
            ),
        ):
            intent = evaluate_market(
                context,
                strategy_params=self._make_params(),
                order_policy=self._make_order_policy(),
            )

        self.assertEqual(intent.action, "exit_full")
        self.assertEqual(intent.reason, "strategy_signal")
        self.assertEqual(intent.next_position_state["bars_held"], 0)
        self.assertFalse(intent.next_position_state["partial_take_profit_done"])
        self.assertEqual(intent.next_position_state["entry_price"], 0.0)

    def test_ict_v1_exit_partial_flows_through_shared_seam(self):
        context = DecisionContext(
            strategy_name="ict_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": [candle(104.8, 105.2, 104.7, 105.0)],
                    "15m": [candle(104.8, 105.2, 104.7, 105.0)],
                },
                price=105.0,
                diagnostics={"current_atr": 1.0, "swing_low": 95.0},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 100.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 7,
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=500_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_ict_params(),
            order_policy=self._make_ict_order_policy(),
        )

        self.assertEqual(intent.action, "exit_partial")
        self.assertEqual(intent.reason, "strategy_partial_take_profit")
        self.assertTrue(intent.next_position_state["strategy_partial_done"])
        self.assertTrue(intent.next_position_state["breakeven_armed"])

    def test_ict_v1_tp2_strategy_exit_flows_through_shared_seam(self):
        context = DecisionContext(
            strategy_name="ict_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": [candle(109.8, 110.2, 109.7, 110.0)],
                    "15m": [candle(109.8, 110.2, 109.7, 110.0)],
                },
                price=110.0,
                diagnostics={"current_atr": 1.0, "swing_low": 95.0},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 110.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 9,
                    "strategy_partial_done": True,
                    "breakeven_armed": True,
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=500_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_ict_params(),
            order_policy=self._make_ict_order_policy(),
        )

        self.assertEqual(intent.action, "exit_full")
        self.assertEqual(intent.reason, "strategy_signal")
        self.assertEqual(intent.next_position_state["bars_held"], 0)
        self.assertFalse(intent.next_position_state["strategy_partial_done"])
        self.assertFalse(intent.next_position_state["breakeven_armed"])

    def test_legacy_baseline_alias_matches_canonical_baseline_through_seam(self):
        market = MarketSnapshot(
            symbol="KRW-BTC",
            candles_by_timeframe={
                "1m": self._entry_candles(),
                "15m": self._entry_candles(),
            },
            price=80.25,
            diagnostics={"current_atr": 1.5, "swing_low": 78.0, "regime": "weak_trend"},
        )
        canonical_context = DecisionContext(
            strategy_name="baseline",
            market=market,
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )
        legacy_context = DecisionContext(
            strategy_name="rsi_bb_reversal_long",
            market=market,
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )
        params = self._make_params()

        canonical_intent = evaluate_market(
            canonical_context,
            strategy_params=replace(params, entry_score_threshold=0.0),
            order_policy=self._make_order_policy(),
        )
        legacy_intent = evaluate_market(
            legacy_context,
            strategy_params=replace(params, entry_score_threshold=0.0),
            order_policy=self._make_order_policy(),
        )

        self.assertEqual(legacy_intent.action, canonical_intent.action)
        self.assertEqual(legacy_intent.reason, canonical_intent.reason)
        self.assertEqual(
            legacy_intent.next_position_state, canonical_intent.next_position_state
        )
        self.assertEqual(legacy_intent.diagnostics, canonical_intent.diagnostics)
        self.assertEqual(legacy_intent.diagnostics["strategy_name"], "baseline")

    def test_candidate_v1_short_horizon_regime_label_stays_stable_through_seam(self):
        candles_1m = self._candidate_pullback_reclaim_1m(final_close=101.95)
        market_data = {
            "1m": candles_1m,
            "5m": self._candidate_trend_5m(),
            "15m": self._candidate_strong_trend_15m(candle_count=60),
        }
        entry_signal = self._evaluate_candidate_entry_with_ready_zone(
            market_data,
            self._make_candidate_params(),
        )
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=market_data,
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )

        intent = self._evaluate_market_with_ready_zone(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertTrue(entry_signal.accepted)
        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.reason, entry_signal.reason)
        self.assertEqual(
            intent.diagnostics["entry_regime"], entry_signal.diagnostics["regime"]
        )
        self.assertEqual(
            intent.diagnostics["regime"], entry_signal.diagnostics["regime"]
        )
        self.assertEqual(intent.diagnostics["stop_basis"], "sr_flip_zone_low")
        self.assertEqual(
            intent.diagnostics["entry_price"],
            entry_signal.diagnostics["entry_price"],
        )
        self.assertEqual(
            intent.diagnostics["stop_price"],
            entry_signal.diagnostics["stop_price"],
        )
        self.assertEqual(
            intent.diagnostics["r_value"],
            entry_signal.diagnostics["r_value"],
        )
        self.assertEqual(
            intent.next_position_state["entry_regime"],
            intent.diagnostics["entry_regime"],
        )
        self.assertEqual(
            intent.next_position_state["entry_price"], intent.diagnostics["entry_price"]
        )
        self.assertEqual(
            intent.next_position_state["initial_stop_price"],
            intent.diagnostics["stop_price"],
        )

    def test_candidate_v1_seam_exposes_exact_normalized_regime_window(self):
        candles_1m = self._candidate_pullback_reclaim_1m()
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": candles_1m,
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )

        intent = self._evaluate_market_with_ready_zone(
            context,
            strategy_params=replace(
                self._make_candidate_params(),
                regime_ema_fast=50,
                regime_ema_slow=200,
            ),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        effective_params = intent.diagnostics["effective_strategy_params"]
        self.assertIsInstance(effective_params, dict)
        if not isinstance(effective_params, dict):
            self.fail("effective_strategy_params should be a dict")
        self.assertEqual(effective_params.get("regime_ema_fast"), 12)
        self.assertEqual(effective_params.get("regime_ema_slow"), 48)

    def test_candidate_v1_seam_uses_reset_low_stop_basis_when_lower(self):
        candles_1m = self._candidate_pullback_reclaim_1m()
        candles_5m = candles_from_closes(
            [
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
            ],
            spread=0.22,
        )
        candles_5m[1]["low_price"] = 100.55
        candles_5m[2]["low_price"] = 100.7
        market_data = {
            "1m": candles_1m,
            "5m": candles_5m,
            "15m": self._candidate_strong_trend_15m(candle_count=60),
        }
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=market_data,
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )

        intent = self._evaluate_market_with_ready_zone(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.diagnostics["stop_basis"], "sr_flip_zone_low")
        self.assertEqual(
            intent.next_position_state["stop_basis"],
            intent.diagnostics["stop_basis"],
        )
        self.assertEqual(
            intent.next_position_state["initial_stop_price"],
            intent.diagnostics["stop_price"],
        )

    def test_candidate_v1_entry_persists_proof_window_state_through_shared_seam(self):
        candles_1m = self._candidate_pullback_reclaim_1m()
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-ADA",
                candles_by_timeframe={
                    "1m": candles_1m,
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )

        intent = self._evaluate_market_with_ready_zone(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertTrue(intent.next_position_state["proof_window_active"])
        self.assertFalse(intent.next_position_state["proof_window_promoted"])
        self.assertEqual(intent.next_position_state["proof_window_status"], "pending")
        self.assertEqual(intent.next_position_state["proof_window_elapsed_bars"], 0)
        self.assertEqual(
            intent.next_position_state["proof_window_max_favorable_excursion_r"], 0.0
        )
        self.assertEqual(
            intent.next_position_state["proof_window_promotion_threshold_r"],
            intent.diagnostics["proof_window_promotion_threshold_r"],
        )
        self.assertEqual(
            intent.next_position_state["proof_window_cooldown_hint_bars"],
            intent.diagnostics["proof_window_cooldown_hint_bars"],
        )
        self.assertEqual(
            intent.next_position_state["proof_window_symbol_profile"], "default"
        )

    def test_candidate_v1_proof_window_does_not_promote_from_elapsed_bars_alone(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=101.0,
                diagnostics={"current_atr": 0.8, "swing_low": 95.0},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 100.0,
                    "entry_atr": 0.8,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 2,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                    "stop_basis": "pullback_low",
                    "proof_window_active": True,
                    "proof_window_promoted": False,
                    "proof_window_status": "pending",
                    "proof_window_start_bar": 0,
                    "proof_window_elapsed_bars": 2,
                    "proof_window_max_bars": 3,
                    "proof_window_max_favorable_excursion_r": 0.0,
                    "proof_window_promotion_threshold_r": 0.6,
                    "proof_window_cooldown_hint_bars": 0,
                    "proof_window_symbol_profile": "default",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "hold")
        self.assertEqual(intent.next_position_state["proof_window_elapsed_bars"], 3)
        self.assertEqual(intent.next_position_state["proof_window_status"], "expired")
        self.assertFalse(intent.next_position_state["proof_window_active"])
        self.assertFalse(intent.next_position_state["proof_window_promoted"])
        self.assertLess(
            abs(
                numeric_value(
                    intent.next_position_state["proof_window_max_favorable_excursion_r"]
                )
                - 0.2
            ),
            1e-9,
        )

    def test_candidate_v1_initial_defense_keeps_entry_defined_pullback_stop(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=101.15,
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=102.35,
                state={
                    "peak_price": 102.35,
                    "entry_atr": 0.8,
                    "entry_swing_low": 101.1,
                    "entry_price": 102.35,
                    "initial_stop_price": 100.98,
                    "risk_per_unit": 1.37,
                    "bars_held": 0,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                    "stop_basis": "pullback_low",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "hold")
        self.assertEqual(intent.diagnostics["strategy_name"], "candidate_v1")
        self.assertEqual(intent.diagnostics["stop_basis"], "pullback_low")
        self.assertEqual(intent.diagnostics["exit_stage"], "initial_defense")
        self.assertLess(numeric_value(intent.diagnostics["hard_stop_price"]), 101.15)
        self.assertEqual(
            numeric_value(intent.diagnostics["hard_stop_price"]),
            numeric_value(intent.diagnostics["initial_stop_price"]),
        )
        self.assertEqual(
            numeric_value(intent.diagnostics["initial_stop_price"]),
            100.98,
        )
        self.assertEqual(
            numeric_value(intent.next_position_state["initial_stop_price"]),
            100.98,
        )

    def test_candidate_v1_trailing_stop_preserves_exit_diagnostics(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=102.5,
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=102.35,
                state={
                    "peak_price": 105.0,
                    "entry_atr": 0.8,
                    "entry_swing_low": 101.1,
                    "entry_price": 102.35,
                    "initial_stop_price": 100.98,
                    "risk_per_unit": 1.37,
                    "bars_held": 24,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 2.5,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 1.82,
                    "stop_basis": "pullback_low",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "exit_full")
        self.assertEqual(intent.reason, "trailing_stop")
        self.assertEqual(intent.diagnostics["strategy_name"], "candidate_v1")
        self.assertEqual(intent.diagnostics["stop_basis"], "pullback_low")
        self.assertEqual(intent.diagnostics["exit_stage"], "late_trailing")
        self.assertIn("hard_stop_price", intent.diagnostics)
        self.assertIn("risk_per_unit", intent.diagnostics)

    def test_candidate_v1_does_not_trail_out_before_profit_room_even_if_old(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=103.0,
                diagnostics={"current_atr": 1.0, "swing_low": 101.1},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 104.0,
                    "entry_atr": 1.0,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 30,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.8,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.4,
                    "stop_basis": "pullback_low",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "hold")
        self.assertEqual(intent.diagnostics["exit_stage"], "initial_defense")

    def test_candidate_v1_does_not_scale_out_on_generic_partial_take_profit(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=102.2,
                diagnostics={"current_atr": 1.0, "swing_low": 101.1},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 106.0,
                    "entry_atr": 1.0,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 12,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 1.2,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.3,
                    "stop_basis": "pullback_low",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "hold")
        self.assertEqual(intent.diagnostics["exit_stage"], "mid_management")

    def test_candidate_v1_active_proof_window_promotes_on_threshold_hit(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=102.4,
                diagnostics={"current_atr": 1.0, "swing_low": 101.1},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 102.4,
                    "entry_atr": 1.0,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 1,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.48,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                    "stop_basis": "pullback_low",
                    "proof_window_active": True,
                    "proof_window_promoted": False,
                    "proof_window_status": "pending",
                    "proof_window_start_bar": 0,
                    "proof_window_elapsed_bars": 1,
                    "proof_window_max_bars": 3,
                    "proof_window_max_favorable_excursion_r": 0.48,
                    "proof_window_promotion_threshold_r": 0.35,
                    "proof_window_cooldown_hint_bars": 0,
                    "proof_window_symbol_profile": "default",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertFalse(intent.diagnostics["proof_window_active"])
        self.assertTrue(intent.diagnostics["proof_window_promoted"])
        self.assertEqual(intent.diagnostics["proof_window_status"], "promoted")

    def test_candidate_v1_expired_proof_window_cannot_promote_late(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=103.2,
                diagnostics={"current_atr": 1.0, "swing_low": 101.1},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 103.2,
                    "entry_atr": 1.0,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 4,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.2,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                    "stop_basis": "pullback_low",
                    "proof_window_active": False,
                    "proof_window_promoted": False,
                    "proof_window_status": "expired",
                    "proof_window_start_bar": 0,
                    "proof_window_elapsed_bars": 3,
                    "proof_window_max_bars": 3,
                    "proof_window_max_favorable_excursion_r": 0.2,
                    "proof_window_promotion_threshold_r": 0.35,
                    "proof_window_cooldown_hint_bars": 0,
                    "proof_window_symbol_profile": "default",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertFalse(intent.diagnostics["proof_window_active"])
        self.assertFalse(intent.diagnostics["proof_window_promoted"])
        self.assertEqual(intent.diagnostics["proof_window_status"], "expired")

    def test_candidate_v1_proof_window_state_gates_trailing_progression(self):
        market = MarketSnapshot(
            symbol="KRW-BTC",
            candles_by_timeframe={
                "1m": self._candidate_pullback_reclaim_1m(),
                "5m": self._candidate_trend_5m(),
                "15m": self._candidate_strong_trend_15m(candle_count=60),
            },
            price=112.0,
            diagnostics={"current_atr": 1.0, "swing_low": 101.1},
        )
        expired_context = DecisionContext(
            strategy_name="candidate_v1",
            market=market,
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 115.0,
                    "entry_atr": 1.0,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 30,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 3.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.6,
                    "stop_basis": "pullback_low",
                    "proof_window_active": False,
                    "proof_window_promoted": False,
                    "proof_window_status": "expired",
                    "proof_window_start_bar": 0,
                    "proof_window_elapsed_bars": 3,
                    "proof_window_max_bars": 3,
                    "proof_window_max_favorable_excursion_r": 0.2,
                    "proof_window_promotion_threshold_r": 0.35,
                    "proof_window_cooldown_hint_bars": 0,
                    "proof_window_symbol_profile": "default",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )
        promoted_context = DecisionContext(
            strategy_name="candidate_v1",
            market=market,
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=100.0,
                state={
                    "peak_price": 115.0,
                    "entry_atr": 1.0,
                    "entry_swing_low": 95.0,
                    "entry_price": 100.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 30,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 3.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.6,
                    "stop_basis": "pullback_low",
                    "proof_window_active": False,
                    "proof_window_promoted": True,
                    "proof_window_status": "promoted",
                    "proof_window_start_bar": 0,
                    "proof_window_elapsed_bars": 2,
                    "proof_window_max_bars": 3,
                    "proof_window_max_favorable_excursion_r": 0.6,
                    "proof_window_promotion_threshold_r": 0.35,
                    "proof_window_cooldown_hint_bars": 0,
                    "proof_window_symbol_profile": "default",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        expired_intent = evaluate_market(
            expired_context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )
        promoted_intent = evaluate_market(
            promoted_context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(expired_intent.action, "hold")
        self.assertEqual(expired_intent.reason, "hold")
        self.assertEqual(expired_intent.diagnostics["exit_stage"], "initial_defense")
        self.assertFalse(expired_intent.diagnostics["proof_window_promoted"])
        self.assertEqual(promoted_intent.action, "exit_full")
        self.assertEqual(promoted_intent.reason, "trailing_stop")
        self.assertEqual(promoted_intent.diagnostics["exit_stage"], "late_trailing")
        self.assertTrue(promoted_intent.diagnostics["proof_window_promoted"])

    def test_candidate_v1_exits_on_expired_failed_proof_without_symbol_lane(self):
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": self._candidate_pullback_reclaim_1m(),
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=399.0,
                diagnostics={"current_atr": 1.0, "swing_low": 395.0},
            ),
            position=PositionSnapshot(
                market="KRW-BTC",
                quantity=0.1,
                entry_price=400.0,
                state={
                    "peak_price": 401.0,
                    "entry_atr": 1.0,
                    "entry_swing_low": 395.0,
                    "entry_price": 400.0,
                    "initial_stop_price": 395.0,
                    "risk_per_unit": 5.0,
                    "bars_held": 2,
                    "entry_regime": "strong_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.2,
                    "lowest_r": -0.2,
                    "drawdown_from_peak_r": 0.4,
                    "stop_basis": "pullback_low",
                    "proof_window_active": False,
                    "proof_window_promoted": False,
                    "proof_window_status": "expired",
                    "proof_window_start_bar": 0,
                    "proof_window_elapsed_bars": 2,
                    "proof_window_max_bars": 3,
                    "proof_window_max_favorable_excursion_r": 0.2,
                    "proof_window_promotion_threshold_r": 0.35,
                    "proof_window_cooldown_hint_bars": 0,
                    "proof_window_symbol_profile": "default",
                },
            ),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0, open_positions=1),
        )

        intent = evaluate_market(
            context,
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "exit_full")
        self.assertEqual(intent.reason, "proof_window_fail")
        self.assertEqual(intent.diagnostics["proof_window_status"], "expired")

    def test_candidate_v1_override_keeps_regime_labels_coherent_through_seam(self):
        candles_1m = self._candidate_pullback_reclaim_1m()
        market_data = {
            "1m": candles_1m,
            "5m": self._candidate_trend_5m(),
            "15m": self._candidate_strong_trend_15m(candle_count=60),
        }
        params = replace(self._make_candidate_params(), regime_ema_slow=200)
        entry_signal = self._evaluate_candidate_entry_with_ready_zone(
            market_data, params
        )
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe=market_data,
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
        )

        self.assertTrue(entry_signal.accepted)

        intent = self._evaluate_market_with_ready_zone(
            context,
            strategy_params=params,
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.reason, "ok")
        self.assertEqual(
            intent.diagnostics["entry_regime"], entry_signal.diagnostics["regime"]
        )
        self.assertEqual(
            intent.diagnostics["regime"], entry_signal.diagnostics["regime"]
        )
        self.assertEqual(
            intent.next_position_state["entry_regime"],
            entry_signal.diagnostics["regime"],
        )

    def test_candidate_v1_shared_regime_override_path_does_not_lower_threshold(self):
        config = TradingConfig(do_not_trading=[], strategy_name="candidate_v1")
        candles_1m = self._candidate_pullback_reclaim_1m(final_close=101.95)
        context = DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol="KRW-BTC",
                candles_by_timeframe={
                    "1m": candles_1m,
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=trade_price(candles_1m[0]),
                diagnostics={"current_atr": 0.8, "swing_low": 101.1},
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
            diagnostics={
                "regime_strategy_overrides": {
                    "strong_trend": config.regime_strategy_overrides("strong_trend")
                }
            },
        )

        intent = self._evaluate_market_with_ready_zone(
            context,
            strategy_params=replace(
                self._make_candidate_params(), entry_score_threshold=5.5
            ),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "score_below_threshold")
        effective_params = intent.diagnostics["effective_strategy_params"]
        self.assertIsInstance(effective_params, dict)
        if not isinstance(effective_params, dict):
            self.fail("effective_strategy_params should be a dict")
        self.assertEqual(effective_params.get("entry_score_threshold"), 5.5)

    def _entry_candles(self) -> list[dict[str, object]]:
        candles_oldest = [
            candle(100 - i * 0.2, 101 - i * 0.2, 99 - i * 0.25, 100 - i * 0.25)
            for i in range(80)
        ]
        return list(reversed(candles_oldest))

    def _weak_trend_candles(self) -> list[dict[str, object]]:
        price = 100.0
        candles_oldest: list[dict[str, object]] = []
        for step in [0.85, -0.35, 0.75, -0.25, 0.65, -0.2] * 8:
            price += step
            candles_oldest.append(
                candle(
                    price - 0.25,
                    price + 0.55,
                    price - 0.7,
                    price,
                )
            )
        return list(reversed(candles_oldest))

    def _candidate_pullback_reclaim_1m(
        self, *, final_close: float = 102.35
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
        return candles_from_closes(closes_oldest, spread=0.22)

    def _candidate_trend_5m(self) -> list[dict[str, object]]:
        closes_oldest = [100.0 + (idx * 0.45) for idx in range(18)]
        return candles_from_closes(closes_oldest, spread=0.4)

    def _candidate_strong_trend_15m(
        self, *, candle_count: int = 40
    ) -> list[dict[str, object]]:
        closes_oldest = [100.0 + (idx * 0.9) for idx in range(candle_count)]
        return candles_from_closes(closes_oldest, spread=0.6)

    def _candidate_market_profile_context(
        self,
        *,
        symbol: str,
        trade_value_24h: float,
        spread_bps: float,
    ) -> DecisionContext:
        candles_1m = self._candidate_pullback_reclaim_1m(final_close=102.35)
        trade_price_value = trade_price(candles_1m[0])
        ask_price = trade_price_value * (1.0 + (spread_bps / 20000.0))
        bid_price = trade_price_value * (1.0 - (spread_bps / 20000.0))
        return DecisionContext(
            strategy_name="candidate_v1",
            market=MarketSnapshot(
                symbol=symbol,
                candles_by_timeframe={
                    "1m": candles_1m,
                    "5m": self._candidate_trend_5m(),
                    "15m": self._candidate_strong_trend_15m(candle_count=60),
                },
                price=trade_price_value,
                diagnostics={
                    "current_atr": 0.8,
                    "swing_low": 101.1,
                    "ticker": {
                        "market": symbol,
                        "trade_price": trade_price_value,
                        "ask_price": ask_price,
                        "bid_price": bid_price,
                        "acc_trade_price_24h": trade_value_24h,
                    },
                },
            ),
            position=PositionSnapshot(),
            portfolio=PortfolioSnapshot(available_krw=1_000_000.0),
            diagnostics={
                "entry_sizing_policy": {
                    "risk_per_trade_pct": 0.01,
                    "fee_rate": 0.0005,
                    "max_holdings": 3,
                    "position_sizing_mode": "risk_first",
                    "max_order_krw_by_cash_management": 300000,
                },
                "market_damping_policy": {
                    "enabled": True,
                    "max_spread": 0.003,
                    "min_trade_value_24h": 100_000_000_000.0,
                    "atr_period": 14,
                    "max_atr_ratio": 0.03,
                },
            },
        )

    def test_candidate_v1_blocks_entry_on_poor_market_profile(self):
        intent = self._evaluate_market_with_ready_zone(
            self._candidate_market_profile_context(
                symbol="KRW-ANKR",
                trade_value_24h=5_000_000_000.0,
                spread_bps=20.0,
            ),
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "hold")
        self.assertEqual(intent.reason, "market_profile_blocked")
        self.assertLess(
            float(intent.diagnostics["market_damping"]["damping_factor"]),
            0.5,
        )

    def test_candidate_v1_keeps_entry_on_healthy_market_profile(self):
        intent = self._evaluate_market_with_ready_zone(
            self._candidate_market_profile_context(
                symbol="KRW-BTC",
                trade_value_24h=300_000_000_000.0,
                spread_bps=0.04,
            ),
            strategy_params=self._make_candidate_params(),
            order_policy=self._make_candidate_order_policy(),
        )

        self.assertEqual(intent.action, "enter")
        self.assertEqual(intent.reason, "ok")
        self.assertGreaterEqual(
            float(intent.diagnostics["market_damping"]["damping_factor"]),
            0.5,
        )


if __name__ == "__main__":
    _ = unittest.main()
