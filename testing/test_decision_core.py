import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    _ = unittest.main()
