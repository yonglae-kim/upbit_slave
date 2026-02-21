import unittest

from core.position_policy import PositionExitState, PositionOrderPolicy
from core.risk import RiskManager


class RiskAndPolicyTest(unittest.TestCase):
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

    def test_position_policy_partial_take_profit_then_trailing(self):
        policy = PositionOrderPolicy(
            stop_loss_threshold=0.97,
            trailing_stop_pct=0.02,
            partial_take_profit_threshold=1.02,
            partial_take_profit_ratio=0.5,
            partial_stop_loss_ratio=1.0,
        )
        state = PositionExitState(peak_price=100.0)

        partial = policy.evaluate(state=state, avg_buy_price=100.0, current_price=103.0, signal_exit=False)
        self.assertTrue(partial.should_exit)
        self.assertEqual(partial.reason, "partial_take_profit")
        self.assertEqual(partial.qty_ratio, 0.5)

        trailing = policy.evaluate(state=state, avg_buy_price=100.0, current_price=100.8, signal_exit=False)
        self.assertTrue(trailing.should_exit)
        self.assertEqual(trailing.reason, "trailing_stop")
        self.assertEqual(trailing.qty_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
