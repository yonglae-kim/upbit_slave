import unittest
from datetime import datetime, timezone

from core.portfolio import normalize_accounts
from core.position_policy import PositionExitState, PositionOrderPolicy
from core.risk import RiskManager


class RiskAndPolicyTest(unittest.TestCase):
    def test_normalize_accounts_includes_total_equity_krw(self):
        accounts = [
            {
                "unit_currency": "KRW",
                "currency": "KRW",
                "balance": "100000",
                "locked": "0",
            },
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
        decision = risk.allow_entry(
            available_krw=100_000, held_markets=[], candidate_market="KRW-XRP"
        )
        self.assertTrue(decision.allowed)

        risk.record_trade_result(-10_000)
        decision = risk.allow_entry(
            available_krw=100_000, held_markets=[], candidate_market="KRW-XRP"
        )
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

    def test_daily_loss_limit_uses_coin_heavy_total_equity_and_resets_on_utc_rollover(
        self,
    ):
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
        decision = risk.allow_entry(
            available_krw=100_000, held_markets=[], candidate_market="KRW-ETH"
        )
        self.assertTrue(decision.allowed)

        risk.record_trade_result(-50_000)
        decision = risk.allow_entry(
            available_krw=100_000, held_markets=[], candidate_market="KRW-ETH"
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "max_daily_loss")

        # UTC day rollover resets daily trackers and baseline is refreshed by new equity
        risk.reset_daily_if_needed(now=datetime(2099, 1, 1, 0, 1, tzinfo=timezone.utc))
        risk.set_baseline_equity(
            2_000_000, now=datetime(2099, 1, 1, 0, 1, tzinfo=timezone.utc)
        )
        decision = risk.allow_entry(
            available_krw=100_000, held_markets=[], candidate_market="KRW-ETH"
        )
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

        partial = policy.evaluate(
            state=state, avg_buy_price=100.0, current_price=103.0, signal_exit=False
        )
        self.assertTrue(partial.should_exit)
        self.assertEqual(partial.reason, "partial_take_profit")
        self.assertEqual(partial.qty_ratio, 0.5)

        trailing = policy.evaluate(
            state=state, avg_buy_price=100.0, current_price=100.8, signal_exit=False
        )
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
        atr_state = PositionExitState(
            peak_price=100.0, entry_atr=5.0, entry_swing_low=90.0
        )

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

    def test_ict_v1_strategy_partial_take_profit_arms_fee_aware_breakeven_stop(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.0,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            fee_rate=0.0005,
        )
        state = PositionExitState(
            peak_price=100.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            bars_held=7,
        )

        partial = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=105.0,
            signal_exit=False,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )
        breakeven_stop = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=100.05,
            signal_exit=False,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )

        self.assertTrue(partial.should_exit)
        self.assertEqual(partial.reason, "strategy_partial_take_profit")
        self.assertTrue(state.strategy_partial_done)
        self.assertTrue(state.breakeven_armed)
        self.assertTrue(breakeven_stop.should_exit)
        self.assertEqual(breakeven_stop.reason, "stop_loss")
        self.assertTrue(
            float(breakeven_stop.diagnostics["breakeven_floor_price"]) > 100.0
        )

    def test_candidate_mode_does_not_activate_trailing_on_bars_held_alone(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
        )
        state = PositionExitState(
            peak_price=104.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=30,
            highest_r=0.8,
            lowest_r=0.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=103.0,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="candidate_v1",
        )

        self.assertFalse(decision.should_exit)
        self.assertEqual(decision.diagnostics["exit_stage"], "initial_defense")

    def test_candidate_mode_requires_proof_promotion_before_late_trailing(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
        )
        expired_state = PositionExitState(
            peak_price=115.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=30,
            highest_r=3.0,
            lowest_r=0.0,
        )
        expired_state.__dict__.update(
            {
                "proof_window_active": False,
                "proof_window_promoted": False,
                "proof_window_status": "expired",
            }
        )

        promoted_state = PositionExitState(
            peak_price=115.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=30,
            highest_r=3.0,
            lowest_r=0.0,
        )
        promoted_state.__dict__.update(
            {
                "proof_window_active": False,
                "proof_window_promoted": True,
                "proof_window_status": "promoted",
            }
        )

        expired_decision = policy.evaluate(
            state=expired_state,
            avg_buy_price=100.0,
            current_price=112.0,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="candidate_v1",
        )
        promoted_decision = policy.evaluate(
            state=promoted_state,
            avg_buy_price=100.0,
            current_price=112.0,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="candidate_v1",
        )

        self.assertFalse(expired_decision.should_exit)
        self.assertEqual(expired_decision.diagnostics["exit_stage"], "initial_defense")
        self.assertTrue(promoted_decision.should_exit)
        self.assertEqual(promoted_decision.reason, "trailing_stop")
        self.assertEqual(promoted_decision.diagnostics["exit_stage"], "late_trailing")

    def test_non_candidate_mode_does_not_trail_below_breakeven_before_1r(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            exit_mode="fixed_pct",
        )
        state = PositionExitState(
            peak_price=103.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=24,
            highest_r=0.6,
            lowest_r=0.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=100.5,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )

        self.assertFalse(decision.should_exit)
        self.assertNotEqual(decision.reason, "trailing_stop")
        self.assertEqual(decision.diagnostics["exit_stage"], "mid_management")

    def test_ict_v1_exits_stale_trade_without_progress(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            stale_trade_max_bars=8,
            stale_trade_min_progress_r=0.5,
        )
        state = PositionExitState(
            peak_price=102.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=8,
            highest_r=0.4,
            lowest_r=0.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=101.5,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )

        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "stale_trade_time_exit")

    def test_ict_v1_does_not_stale_exit_once_protection_is_secured(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            stale_trade_max_bars=8,
            stale_trade_min_progress_r=0.5,
        )
        state = PositionExitState(
            peak_price=102.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=8,
            highest_r=0.4,
            lowest_r=0.0,
            breakeven_armed=True,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=101.5,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )

        self.assertFalse(decision.should_exit)
        self.assertNotEqual(decision.reason, "stale_trade_time_exit")

    def test_hard_stop_precedes_stale_trade_exit_for_ict_v1(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            stale_trade_max_bars=8,
            stale_trade_min_progress_r=0.5,
        )
        state = PositionExitState(
            peak_price=102.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=8,
            highest_r=0.4,
            lowest_r=-1.2,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=94.8,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
        )

        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "stop_loss")

    def test_max_hold_bars_remains_absolute_timeout_after_stale_trade_window(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            stale_trade_max_bars=8,
            stale_trade_min_progress_r=0.5,
        )
        state = PositionExitState(
            peak_price=103.5,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=24,
            highest_r=0.8,
            lowest_r=0.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=102.5,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
            max_hold_bars=24,
        )

        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "time_stop")

    def test_hard_stop_precedes_max_hold_timeout(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
        )
        state = PositionExitState(
            peak_price=102.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=24,
            highest_r=0.4,
            lowest_r=-1.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=94.5,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="ict_v1",
            partial_take_profit_enabled=True,
            partial_take_profit_r=1.0,
            partial_take_profit_size=0.5,
            move_stop_to_breakeven_after_partial=True,
            max_hold_bars=24,
        )

        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "stop_loss")

    def test_candidate_mode_ignores_ict_v1_stale_trade_rule(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
            stale_trade_max_bars=8,
            stale_trade_min_progress_r=0.5,
        )
        state = PositionExitState(
            peak_price=102.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=8,
            highest_r=0.4,
            lowest_r=0.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=101.5,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="candidate_v1",
            partial_take_profit_enabled=False,
        )

        self.assertFalse(decision.should_exit)
        self.assertNotEqual(decision.reason, "stale_trade_time_exit")

    def test_candidate_exits_on_expired_failed_proof_without_symbol_lane(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.05,
            partial_take_profit_ratio=0.0,
            partial_stop_loss_ratio=1.0,
        )
        weak_state = PositionExitState(
            peak_price=401.0,
            entry_price=400.0,
            initial_stop_price=395.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=2,
            highest_r=0.2,
            lowest_r=-0.2,
        )
        weak_state.__dict__.update(
            {
                "proof_window_active": False,
                "proof_window_promoted": False,
                "proof_window_status": "expired",
                "proof_window_max_bars": 3,
                "proof_window_promotion_threshold_r": 0.35,
                "proof_window_symbol_profile": "default",
            }
        )

        decision = policy.evaluate(
            state=weak_state,
            avg_buy_price=400.0,
            current_price=399.0,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="candidate_v1",
        )

        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "proof_window_fail")
        self.assertEqual(decision.qty_ratio, 1.0)

    def test_candidate_mode_ignores_generic_partial_take_profit_branch(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.95,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.02,
            partial_take_profit_ratio=0.5,
            partial_stop_loss_ratio=1.0,
        )
        state = PositionExitState(
            peak_price=106.0,
            entry_price=100.0,
            initial_stop_price=95.0,
            risk_per_unit=5.0,
            entry_regime="strong_trend",
            bars_held=12,
            highest_r=1.2,
            lowest_r=0.0,
        )

        decision = policy.evaluate(
            state=state,
            avg_buy_price=100.0,
            current_price=102.2,
            signal_exit=False,
            current_atr=1.0,
            strategy_name="candidate_v1",
            partial_take_profit_enabled=False,
        )

        self.assertFalse(decision.should_exit)
        self.assertEqual(decision.diagnostics["exit_stage"], "mid_management")


if __name__ == "__main__":
    unittest.main()
