from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExitDecision:
    should_exit: bool
    qty_ratio: float = 0.0
    reason: str = "hold"


@dataclass
class PositionExitState:
    peak_price: float = 0.0
    partial_take_profit_done: bool = False


class PositionOrderPolicy:
    def __init__(
        self,
        *,
        stop_loss_threshold: float,
        trailing_stop_pct: float,
        partial_take_profit_threshold: float,
        partial_take_profit_ratio: float,
        partial_stop_loss_ratio: float,
    ):
        self.stop_loss_threshold = float(stop_loss_threshold)
        self.trailing_stop_pct = max(0.0, float(trailing_stop_pct))
        self.partial_take_profit_threshold = float(partial_take_profit_threshold)
        self.partial_take_profit_ratio = min(1.0, max(0.0, float(partial_take_profit_ratio)))
        self.partial_stop_loss_ratio = min(1.0, max(0.0, float(partial_stop_loss_ratio)))

    def evaluate(
        self,
        *,
        state: PositionExitState,
        avg_buy_price: float,
        current_price: float,
        signal_exit: bool,
    ) -> ExitDecision:
        if avg_buy_price <= 0 or current_price <= 0:
            return ExitDecision(should_exit=False)

        state.peak_price = max(state.peak_price, current_price)
        hard_stop_price = avg_buy_price * self.stop_loss_threshold

        if current_price <= hard_stop_price:
            if not state.partial_take_profit_done and self.partial_stop_loss_ratio < 1.0:
                state.partial_take_profit_done = True
                return ExitDecision(True, self.partial_stop_loss_ratio, "partial_stop_loss")
            return ExitDecision(True, 1.0, "stop_loss")

        if (
            not state.partial_take_profit_done
            and self.partial_take_profit_ratio > 0
            and current_price >= avg_buy_price * self.partial_take_profit_threshold
        ):
            state.partial_take_profit_done = True
            return ExitDecision(True, self.partial_take_profit_ratio, "partial_take_profit")

        if self.trailing_stop_pct > 0:
            trailing_floor = state.peak_price * (1 - self.trailing_stop_pct)
            if current_price <= trailing_floor:
                return ExitDecision(True, 1.0, "trailing_stop")

        if signal_exit:
            return ExitDecision(True, 1.0, "strategy_signal")

        return ExitDecision(False)
