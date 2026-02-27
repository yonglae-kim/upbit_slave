import unittest
from datetime import datetime, timezone

from core.portfolio import normalize_accounts
from core.position_policy import PositionExitState, PositionOrderPolicy
from core.risk import RiskManager


class RiskAndPolicyTest(unittest.TestCase):

    def test_normalize_accounts_includes_total_equity_krw(self):
        accounts = [
            {"unit_currency": "KRW", "currency": "KRW", "balance": "100000", "locked": "0"},
            {
                "unit_currency": "KRW",
                "currency": "BTC",
                "balance": "0.1",
                "locked": "0.0",
                "avg_buy_price": "50000000",
            },
        ]

        normalized = normalize_accounts(accounts, excluded=[])

        self.assertEqual(normalized.available_krw, 100_000)
        self.assertEqual(normalized.total_equity_krw, 5_100_000)

    def test_risk_sized_order_krw_uses_stop_distance(self):
        risk = RiskManager(
            risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.05,
            max_consecutive_losses=3,
            max_concurrent_positions=4,
            max_correlated_positions=1,
            correlation_groups={},
            min_order_krw=5000,
        )

        order_krw = risk.compute_risk_sized_order_krw(
            available_krw=1_000_000,
            entry_price=100.0,
            stop_price=95.0,
        )

        self.assertEqual(order_krw, 200_000)

    def test_correlation_exposure_blocks_entry(self):
        risk = RiskManager(
            risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.05,
            max_consecutive_losses=3,
            max_concurrent_positions=4,
            max_correlated_positions=1,
            correlation_groups={"KRW-BTC": "majors", "KRW-ETH": "majors"},
            min_order_krw=5000,
        )

        decision = risk.allow_entry(
            available_krw=100_000,
            held_markets=["KRW-BTC"],
            candidate_market="KRW-ETH",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "max_correlated_positions")


    def test_daily_loss_limit_uses_cash_only_total_equity(self):
        risk = RiskManager(
            risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.05,
            max_consecutive_losses=3,
            max_concurrent_positions=4,
            max_correlated_positions=1,
            correlation_groups={},
            min_order_krw=5000,
        )

        risk.set_baseline_equity(1_000_000)
        risk.record_trade_result(-40_000)
        decision = risk.allow_entry(available_krw=100_000, held_markets=[], candidate_market="KRW-XRP")
        self.assertTrue(decision.allowed)

        risk.record_trade_result(-10_000)
        decision = risk.allow_entry(available_krw=100_000, held_markets=[], candidate_market="KRW-XRP")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "max_daily_loss")

    def test_quality_multiplier_clamp_respects_bounds_and_daily_loss_budget(self):
        risk = RiskManager(
            risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.05,
            max_consecutive_losses=3,
            max_concurrent_positions=4,
            max_correlated_positions=1,
            correlation_groups={},
            min_order_krw=5000,
            quality_multiplier_min_bound=0.7,
            quality_multiplier_max_bound=1.2,
        )
        risk.set_baseline_equity(1_000_000)
        self.assertEqual(risk.clamp_quality_multiplier(1.5), 1.2)

        risk.record_trade_result(-45_000)
        self.assertEqual(risk.clamp_quality_multiplier(1.2), 0.8)

    def test_daily_loss_limit_uses_coin_heavy_total_equity_and_resets_on_utc_rollover(self):
        risk = RiskManager(
            risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.05,
            max_consecutive_losses=3,
            max_concurrent_positions=4,
            max_correlated_positions=1,
            correlation_groups={},
            min_order_krw=5000,
        )

        # total_equity=3,000,000 -> daily limit=150,000
        risk.set_baseline_equity(3_000_000)
        risk.record_trade_result(-100_000)
        decision = risk.allow_entry(available_krw=100_000, held_markets=[], candidate_market="KRW-ETH")
        self.assertTrue(decision.allowed)

        risk.record_trade_result(-50_000)
        decision = risk.allow_entry(available_krw=100_000, held_markets=[], candidate_market="KRW-ETH")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "max_daily_loss")

        # UTC day rollover resets daily trackers and baseline is refreshed by new equity
        risk.reset_daily_if_needed(now=datetime(2099, 1, 1, 0, 1, tzinfo=timezone.utc))
        risk.set_baseline_equity(2_000_000, now=datetime(2099, 1, 1, 0, 1, tzinfo=timezone.utc))
        decision = risk.allow_entry(available_krw=100_000, held_markets=[], candidate_market="KRW-ETH")
        self.assertTrue(decision.allowed)

    def test_position_policy_partial_take_profit_then_trailing(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.97,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.02,
            partial_take_profit_ratio=0.5,
            partial_stop_loss_ratio=1.0,
        )
        state = PositionExitState(peak_price=100.0, bars_held=8)

        partial = policy.evaluate(state=state, avg_buy_price=100.0, current_price=103.0, signal_exit=False)
        self.assertTrue(partial.should_exit)
        self.assertEqual(partial.reason, "partial_take_profit")
        self.assertEqual(partial.qty_ratio, 0.5)

        trailing = policy.evaluate(state=state, avg_buy_price=100.0, current_price=100.8, signal_exit=False)
        self.assertTrue(trailing.should_exit)
        self.assertEqual(trailing.reason, "trailing_stop")
        self.assertEqual(trailing.qty_ratio, 1.0)


    def test_position_policy_fixed_pct_vs_atr_mode(self):
        fixed_policy = PositionOrderPolicy(
            stop_loss_threshold=0.97,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            exit_mode="fixed_pct",
        )
        atr_policy = PositionOrderPolicy(
            stop_loss_threshold=0.97,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            exit_mode="atr",
            atr_stop_mult=2.0,
            atr_trailing_mult=0.0,
        )

        fixed_state = PositionExitState(peak_price=100.0)
        atr_state = PositionExitState(peak_price=100.0, entry_atr=5.0, entry_swing_low=90.0)

        fixed_decision = fixed_policy.evaluate(
            state=fixed_state,
            avg_buy_price=100.0,
            current_price=92.0,
            signal_exit=False,
            current_atr=5.0,
            swing_low=90.0,
        )
        atr_decision = atr_policy.evaluate(
            state=atr_state,
            avg_buy_price=100.0,
            current_price=92.0,
            signal_exit=False,
            current_atr=5.0,
            swing_low=90.0,
        )

        self.assertTrue(fixed_decision.should_exit)
        self.assertEqual(fixed_decision.reason, "stop_loss")
        self.assertFalse(atr_decision.should_exit)

    def test_strategy_signal_uses_dynamic_r_guard(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.97,
            trailing_stop_pct=0.0,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
        )

        defensive_state = PositionExitState(
            peak_price=105.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="defensive",
            bars_held=1,
        )
        defensive_blocked = policy.evaluate(
            state=defensive_state,
            avg_buy_price=100.0,
            current_price=110.0,
            signal_exit=True,
            current_atr=6.0,
            strategy_name="rsi_bb_reversal_long",
        )

        bull_state = PositionExitState(
            peak_price=106.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="bull",
            bars_held=30,
        )
        bull_allowed = policy.evaluate(
            state=bull_state,
            avg_buy_price=100.0,
            current_price=107.0,
            signal_exit=True,
            current_atr=1.0,
            strategy_name="rsi_bb_reversal_long",
        )

        self.assertFalse(defensive_blocked.should_exit)
        self.assertTrue(bull_allowed.should_exit)
        self.assertEqual(bull_allowed.reason, "strategy_signal")

    def test_strategy_partial_take_profit_arms_breakeven_stop(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.0,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
        )
        state = PositionExitState(
            peak_price=100.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
        )

        partial = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=105.0,
            signal_exit=False,
            strategy_name="rsi_bb_reversal_long",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )
        breakeven_stop = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=100.0,
            signal_exit=False,
            strategy_name="rsi_bb_reversal_long",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )

        self.assertTrue(partial.should_exit)
        self.assertEqual(partial.reason, "strategy_partial_take_profit")
        self.assertTrue(state.breakeven_armed)
        self.assertTrue(breakeven_stop.should_exit)
        self.assertEqual(breakeven_stop.reason, "stop_loss")


if __name__ == "__main__":
    unittest.main()
