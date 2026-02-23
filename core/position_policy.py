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
    entry_atr: float = 0.0
    entry_swing_low: float = 0.0
    entry_price: float = 0.0
    initial_stop_price: float = 0.0
    risk_per_unit: float = 0.0
    bars_held: int = 0
    strategy_partial_done: bool = False
    breakeven_armed: bool = False


class PositionOrderPolicy:
    def __init__(
        self,
        *,
        stop_loss_threshold: float,
        trailing_stop_pct: float,
        partial_take_profit_threshold: float,
        partial_take_profit_ratio: float,
        partial_stop_loss_ratio: float,
        exit_mode: str = "fixed_pct",
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        atr_trailing_mult: float = 1.0,
        swing_lookback: int = 5,
    ):
        self.stop_loss_threshold = float(stop_loss_threshold)
        self.trailing_stop_pct = max(0.0, float(trailing_stop_pct))
        self.partial_take_profit_threshold = float(partial_take_profit_threshold)
        self.partial_take_profit_ratio = min(1.0, max(0.0, float(partial_take_profit_ratio)))
        self.partial_stop_loss_ratio = min(1.0, max(0.0, float(partial_stop_loss_ratio)))
        self.exit_mode = str(exit_mode).strip().lower() or "fixed_pct"
        self.atr_period = max(1, int(atr_period))
        self.atr_stop_mult = max(0.0, float(atr_stop_mult))
        self.atr_trailing_mult = max(0.0, float(atr_trailing_mult))
        self.swing_lookback = max(1, int(swing_lookback))

    def evaluate(
        self,
        *,
        state: PositionExitState,
        avg_buy_price: float,
        current_price: float,
        signal_exit: bool,
        current_atr: float = 0.0,
        swing_low: float = 0.0,
        strategy_name: str = "",
        partial_take_profit_enabled: bool = False,
        partial_take_profit_r: float = 1.0,
        partial_take_profit_size: float = 0.0,
        move_stop_to_breakeven_after_partial: bool = False,
    ) -> ExitDecision:
        if avg_buy_price <= 0 or current_price <= 0:
            return ExitDecision(should_exit=False)

        state.bars_held = max(0, int(state.bars_held)) + 1
        state.peak_price = max(state.peak_price, current_price)
        if state.entry_price <= 0:
            state.entry_price = float(avg_buy_price)

        strategy_mode = str(strategy_name).lower().strip() == "rsi_bb_reversal_long"

        strategy_partial_enabled = (
            strategy_mode
            and partial_take_profit_enabled
            and partial_take_profit_size > 0
            and partial_take_profit_r > 0
        )

        if strategy_partial_enabled and state.risk_per_unit <= 0:
            fallback_stop = state.initial_stop_price if state.initial_stop_price > 0 else avg_buy_price * self.stop_loss_threshold
            state.risk_per_unit = max(state.entry_price - fallback_stop, 0.0)

        if self.exit_mode == "atr":
            hard_stop_price = self._atr_stop_price(state, avg_buy_price, current_atr, swing_low)
        else:
            hard_stop_price = avg_buy_price * self.stop_loss_threshold

        if strategy_partial_enabled and state.breakeven_armed and move_stop_to_breakeven_after_partial:
            hard_stop_price = max(hard_stop_price, state.entry_price)

        if current_price <= hard_stop_price:
            if not state.partial_take_profit_done and self.partial_stop_loss_ratio < 1.0:
                state.partial_take_profit_done = True
                return ExitDecision(True, self.partial_stop_loss_ratio, "partial_stop_loss")
            return ExitDecision(True, 1.0, "stop_loss")

        if strategy_partial_enabled and not state.strategy_partial_done:
            target_price = state.entry_price + (state.risk_per_unit * partial_take_profit_r)
            if state.risk_per_unit > 0 and current_price >= target_price:
                state.strategy_partial_done = True
                if move_stop_to_breakeven_after_partial:
                    state.breakeven_armed = True
                return ExitDecision(True, min(1.0, max(0.0, partial_take_profit_size)), "strategy_partial_take_profit")

        if (
            not strategy_partial_enabled
            and not state.partial_take_profit_done
            and self.partial_take_profit_ratio > 0
            and current_price >= avg_buy_price * self.partial_take_profit_threshold
        ):
            state.partial_take_profit_done = True
            return ExitDecision(True, self.partial_take_profit_ratio, "partial_take_profit")

        trailing_floor = 0.0
        if self.exit_mode == "atr":
            trailing_floor = self._atr_trailing_floor(state, current_atr)
        elif self.trailing_stop_pct > 0:
            trailing_floor = state.peak_price * (1 - self.trailing_stop_pct)

        if trailing_floor > 0 and current_price <= trailing_floor:
            return ExitDecision(True, 1.0, "trailing_stop")

        if signal_exit:
            return ExitDecision(True, 1.0, "strategy_signal")

        return ExitDecision(False)

    def _atr_stop_price(
        self,
        state: PositionExitState,
        avg_buy_price: float,
        current_atr: float,
        swing_low: float,
    ) -> float:
        atr_value = self._resolve_entry_atr(state, current_atr)
        atr_stop = avg_buy_price - (atr_value * self.atr_stop_mult) if atr_value > 0 else 0.0
        swing_base = self._resolve_entry_swing_low(state, swing_low)
        stop_candidates = [price for price in (atr_stop, swing_base) if price > 0]
        if stop_candidates:
            return max(stop_candidates)
        return avg_buy_price * self.stop_loss_threshold

    def _atr_trailing_floor(self, state: PositionExitState, current_atr: float) -> float:
        atr_value = self._resolve_entry_atr(state, current_atr)
        if atr_value <= 0 or self.atr_trailing_mult <= 0:
            return 0.0
        return state.peak_price - (atr_value * self.atr_trailing_mult)

    @staticmethod
    def _resolve_entry_atr(state: PositionExitState, current_atr: float) -> float:
        if state.entry_atr > 0:
            return state.entry_atr
        if current_atr > 0:
            state.entry_atr = float(current_atr)
            return state.entry_atr
        return 0.0

    @staticmethod
    def _resolve_entry_swing_low(state: PositionExitState, swing_low: float) -> float:
        if state.entry_swing_low > 0:
            return state.entry_swing_low
        if swing_low > 0:
            state.entry_swing_low = float(swing_low)
            return state.entry_swing_low
        return 0.0
