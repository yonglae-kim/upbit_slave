from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields


@dataclass
class ExitDecision:
    should_exit: bool
    qty_ratio: float = 0.0
    reason: str = "hold"
    diagnostics: dict[str, float | str] = field(default_factory=dict)


@dataclass
class PositionExitState:
    peak_price: float = 0.0
    partial_take_profit_done: bool = False
    entry_atr: float = 0.0
    entry_swing_low: float = 0.0
    entry_price: float = 0.0
    initial_stop_price: float = 0.0
    stop_basis: str = "unknown"
    risk_per_unit: float = 0.0
    bars_held: int = 0
    strategy_partial_done: bool = False
    breakeven_armed: bool = False
    entry_regime: str = "unknown"
    highest_r: float = 0.0
    lowest_r: float = 0.0
    drawdown_from_peak_r: float = 0.0
    proof_window_active: bool = False
    proof_window_promoted: bool = False
    proof_window_status: str = "inactive"
    proof_window_start_bar: int = 0
    proof_window_elapsed_bars: int = 0
    proof_window_max_bars: int = 0
    proof_window_max_favorable_excursion_r: float = 0.0
    proof_window_promotion_threshold_r: float = 0.0
    proof_window_cooldown_hint_bars: int = 0
    proof_window_symbol_profile: str = "default"

    def reset_after_full_exit(self) -> None:
        self.bars_held = 0
        self.partial_take_profit_done = False
        self.strategy_partial_done = False
        self.breakeven_armed = False
        self.highest_r = 0.0
        self.lowest_r = 0.0
        self.drawdown_from_peak_r = 0.0
        self.proof_window_active = False
        self.proof_window_promoted = False
        self.proof_window_status = "inactive"
        self.proof_window_start_bar = 0
        self.proof_window_elapsed_bars = 0
        self.proof_window_max_bars = 0
        self.proof_window_max_favorable_excursion_r = 0.0
        self.proof_window_promotion_threshold_r = 0.0
        self.proof_window_cooldown_hint_bars = 0
        self.proof_window_symbol_profile = "default"


_POSITION_EXIT_STATE_FIELD_NAMES = {
    state_field.name for state_field in fields(PositionExitState)
}


def load_position_exit_state(
    state_payload: dict[str, object] | None = None,
) -> PositionExitState:
    payload = dict(state_payload or {})
    return PositionExitState(
        peak_price=_payload_float(payload, "peak_price"),
        partial_take_profit_done=_payload_bool(payload, "partial_take_profit_done"),
        entry_atr=_payload_float(payload, "entry_atr"),
        entry_swing_low=_payload_float(payload, "entry_swing_low"),
        entry_price=_payload_float(payload, "entry_price"),
        initial_stop_price=_payload_float(payload, "initial_stop_price"),
        stop_basis=_payload_str(payload, "stop_basis", default="unknown"),
        risk_per_unit=_payload_float(payload, "risk_per_unit"),
        bars_held=_payload_int(payload, "bars_held"),
        strategy_partial_done=_payload_bool(payload, "strategy_partial_done"),
        breakeven_armed=_payload_bool(payload, "breakeven_armed"),
        entry_regime=_payload_str(payload, "entry_regime", default="unknown"),
        highest_r=_payload_float(payload, "highest_r"),
        lowest_r=_payload_float(payload, "lowest_r"),
        drawdown_from_peak_r=_payload_float(payload, "drawdown_from_peak_r"),
        proof_window_active=_payload_bool(payload, "proof_window_active"),
        proof_window_promoted=_payload_bool(payload, "proof_window_promoted"),
        proof_window_status=_payload_str(
            payload, "proof_window_status", default="inactive"
        ),
        proof_window_start_bar=_payload_int(payload, "proof_window_start_bar"),
        proof_window_elapsed_bars=_payload_int(payload, "proof_window_elapsed_bars"),
        proof_window_max_bars=_payload_int(payload, "proof_window_max_bars"),
        proof_window_max_favorable_excursion_r=_payload_float(
            payload, "proof_window_max_favorable_excursion_r"
        ),
        proof_window_promotion_threshold_r=_payload_float(
            payload, "proof_window_promotion_threshold_r"
        ),
        proof_window_cooldown_hint_bars=_payload_int(
            payload, "proof_window_cooldown_hint_bars"
        ),
        proof_window_symbol_profile=_payload_str(
            payload, "proof_window_symbol_profile", default="default"
        ),
    )


def dump_position_exit_state(state: PositionExitState) -> dict[str, object]:
    return asdict(state)


def _payload_float(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _payload_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return False


def _payload_str(payload: dict[str, object], key: str, *, default: str) -> str:
    value = payload.get(key)
    if value is None:
        return default
    resolved = str(value).strip()
    return resolved or default


def evaluate_position_state(
    policy: "PositionOrderPolicy",
    *,
    state_payload: dict[str, object] | None = None,
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
    max_hold_bars: int = 0,
) -> tuple[ExitDecision, dict[str, object]]:
    local_state = load_position_exit_state(state_payload)
    decision = policy.evaluate(
        state=local_state,
        avg_buy_price=avg_buy_price,
        current_price=current_price,
        signal_exit=signal_exit,
        current_atr=current_atr,
        swing_low=swing_low,
        strategy_name=strategy_name,
        partial_take_profit_enabled=partial_take_profit_enabled,
        partial_take_profit_r=partial_take_profit_r,
        partial_take_profit_size=partial_take_profit_size,
        move_stop_to_breakeven_after_partial=move_stop_to_breakeven_after_partial,
        max_hold_bars=max_hold_bars,
    )
    return decision, dump_position_exit_state(local_state)


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
        self.partial_take_profit_ratio = min(
            1.0, max(0.0, float(partial_take_profit_ratio))
        )
        self.partial_stop_loss_ratio = min(
            1.0, max(0.0, float(partial_stop_loss_ratio))
        )
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
        max_hold_bars: int = 0,
    ) -> ExitDecision:
        if avg_buy_price <= 0 or current_price <= 0:
            return ExitDecision(should_exit=False)

        state.peak_price = max(state.peak_price, current_price)
        if state.entry_price <= 0:
            state.entry_price = float(avg_buy_price)

        if max(0, int(max_hold_bars)) > 0 and max(0, int(state.bars_held)) >= int(
            max_hold_bars
        ):
            return ExitDecision(True, 1.0, "time_stop")

        normalized_strategy_name = str(strategy_name).lower().strip()
        strategy_mode = normalized_strategy_name == "rsi_bb_reversal_long"

        strategy_partial_enabled = (
            normalized_strategy_name != "candidate_v1"
            and partial_take_profit_enabled
            and partial_take_profit_size > 0
            and partial_take_profit_r > 0
        )

        if strategy_partial_enabled and state.risk_per_unit <= 0:
            fallback_stop = (
                state.initial_stop_price
                if state.initial_stop_price > 0
                else avg_buy_price * self.stop_loss_threshold
            )
            state.risk_per_unit = max(state.entry_price - fallback_stop, 0.0)

        current_r = 0.0
        if state.risk_per_unit > 0 and state.entry_price > 0:
            current_r = (current_price - state.entry_price) / state.risk_per_unit
            peak_r = (state.peak_price - state.entry_price) / state.risk_per_unit
            state.highest_r = max(float(state.highest_r), float(peak_r))
            state.lowest_r = min(float(state.lowest_r), float(current_r))
            state.drawdown_from_peak_r = max(state.highest_r - current_r, 0.0)

        candidate_mode = str(strategy_name).lower().strip() == "candidate_v1"
        candidate_requires_proof_promotion = (
            candidate_mode
            and self._has_proof_window_state(state)
            and not bool(state.proof_window_promoted)
        )

        exit_stage = "initial_defense"
        if state.highest_r >= 1.0 or (not candidate_mode and state.bars_held >= 8):
            exit_stage = "mid_management"
        if state.highest_r >= 2.0 or (not candidate_mode and state.bars_held >= 24):
            exit_stage = "late_trailing"
        if candidate_requires_proof_promotion:
            exit_stage = "initial_defense"

        if self.exit_mode == "atr":
            hard_stop_price = self._atr_stop_price(
                state, avg_buy_price, current_atr, swing_low
            )
        else:
            hard_stop_price = avg_buy_price * self.stop_loss_threshold

        entry_defined_stop = 0.0
        if state.initial_stop_price > 0 and str(
            state.stop_basis
        ).strip().lower() not in {"", "unknown"}:
            entry_defined_stop = float(state.initial_stop_price)

        if exit_stage == "initial_defense" and entry_defined_stop > 0:
            hard_stop_price = entry_defined_stop
        elif state.risk_per_unit > 0 and state.entry_price > 0:
            if exit_stage == "initial_defense":
                hard_stop_price = max(
                    hard_stop_price, state.entry_price - (state.risk_per_unit * 0.85)
                )
            elif candidate_mode and exit_stage == "mid_management":
                if entry_defined_stop > 0:
                    hard_stop_price = max(hard_stop_price, entry_defined_stop)
                if state.breakeven_armed or state.highest_r >= 1.5:
                    hard_stop_price = max(hard_stop_price, state.entry_price)
            elif exit_stage in {"mid_management", "late_trailing"} and (
                state.breakeven_armed or state.highest_r >= 1.0
            ):
                hard_stop_price = max(hard_stop_price, state.entry_price)

        if (
            strategy_partial_enabled
            and state.breakeven_armed
            and move_stop_to_breakeven_after_partial
        ):
            hard_stop_price = max(hard_stop_price, state.entry_price)

        atr_to_risk = 0.0
        if state.risk_per_unit > 0 and current_atr > 0:
            atr_to_risk = current_atr / state.risk_per_unit

        stop_diagnostics: dict[str, float | str] = {
            "exit_stage": exit_stage,
            "hard_stop_price": float(hard_stop_price),
            "entry_price": float(state.entry_price),
            "initial_stop_price": float(state.initial_stop_price),
            "stop_basis": str(state.stop_basis or "unknown"),
            "risk_per_unit": float(state.risk_per_unit),
            "atr_to_risk": float(atr_to_risk),
            "bars_held": float(max(0, int(state.bars_held))),
            "highest_r": float(state.highest_r),
        }

        if (
            candidate_mode
            and not state.proof_window_active
            and not state.proof_window_promoted
            and str(state.proof_window_status).strip().lower() == "expired"
            and current_r <= 0.0
        ):
            return ExitDecision(
                True,
                1.0,
                "proof_window_fail",
                diagnostics=stop_diagnostics,
            )

        if current_price <= hard_stop_price:
            if (
                not state.partial_take_profit_done
                and self.partial_stop_loss_ratio < 1.0
            ):
                state.partial_take_profit_done = True
                return ExitDecision(
                    True,
                    self.partial_stop_loss_ratio,
                    "partial_stop_loss",
                    diagnostics=stop_diagnostics,
                )
            return ExitDecision(True, 1.0, "stop_loss", diagnostics=stop_diagnostics)

        if (
            strategy_partial_enabled
            and exit_stage != "initial_defense"
            and not state.strategy_partial_done
        ):
            target_price = state.entry_price + (
                state.risk_per_unit * partial_take_profit_r
            )
            if state.risk_per_unit > 0 and current_price >= target_price:
                state.strategy_partial_done = True
                if move_stop_to_breakeven_after_partial:
                    state.breakeven_armed = True
                return ExitDecision(
                    True,
                    min(1.0, max(0.0, partial_take_profit_size)),
                    "strategy_partial_take_profit",
                    diagnostics=stop_diagnostics,
                )

        if (
            not candidate_mode
            and not strategy_partial_enabled
            and exit_stage != "initial_defense"
            and not state.partial_take_profit_done
            and self.partial_take_profit_ratio > 0
            and current_price >= avg_buy_price * self.partial_take_profit_threshold
        ):
            state.partial_take_profit_done = True
            return ExitDecision(
                True,
                self.partial_take_profit_ratio,
                "partial_take_profit",
                diagnostics=stop_diagnostics,
            )

        trailing_floor = 0.0
        if self.exit_mode == "atr":
            trailing_floor = self._atr_trailing_floor(state, current_atr)
        elif self.trailing_stop_pct > 0:
            trailing_floor = state.peak_price * (1 - self.trailing_stop_pct)

        if (
            trailing_floor > 0
            and state.risk_per_unit > 0
            and exit_stage == "late_trailing"
        ):
            trailing_floor = max(
                trailing_floor, state.peak_price - (state.risk_per_unit * 0.7)
            )

        if candidate_mode and exit_stage != "late_trailing":
            trailing_floor = 0.0

        if trailing_floor > 0 and current_price <= trailing_floor:
            return ExitDecision(
                True,
                1.0,
                "trailing_stop",
                diagnostics=stop_diagnostics,
            )

        if signal_exit:
            if strategy_mode and state.risk_per_unit > 0:
                required_r = self._strategy_signal_required_r(
                    entry_regime=state.entry_regime,
                    bars_held=state.bars_held,
                    current_atr=current_atr,
                    risk_per_unit=state.risk_per_unit,
                )
                if current_r < required_r:
                    return ExitDecision(False, diagnostics=stop_diagnostics)
            return ExitDecision(True, 1.0, "strategy_signal")

        return ExitDecision(False, diagnostics=stop_diagnostics)

    def _atr_stop_price(
        self,
        state: PositionExitState,
        avg_buy_price: float,
        current_atr: float,
        swing_low: float,
    ) -> float:
        atr_value = self._resolve_entry_atr(state, current_atr)
        atr_stop = (
            avg_buy_price - (atr_value * self.atr_stop_mult) if atr_value > 0 else 0.0
        )
        swing_base = self._resolve_entry_swing_low(state, swing_low)
        stop_candidates = [price for price in (atr_stop, swing_base) if price > 0]
        if stop_candidates:
            return max(stop_candidates)
        return avg_buy_price * self.stop_loss_threshold

    def _atr_trailing_floor(
        self, state: PositionExitState, current_atr: float
    ) -> float:
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

    @staticmethod
    def _strategy_signal_required_r(
        *, entry_regime: str, bars_held: int, current_atr: float, risk_per_unit: float
    ) -> float:
        regime = str(entry_regime).strip().lower()
        regime_base = {
            "strong_trend": 1.2,
            "weak_trend": 1.6,
            "sideways": 2.2,
            # Backward compatibility
            "bull": 1.2,
            "neutral": 1.6,
            "defensive": 2.2,
        }.get(regime, 1.8)

        hold_adjust = 0.0
        if bars_held >= 48:
            hold_adjust = -0.6
        elif bars_held >= 24:
            hold_adjust = -0.3

        vol_adjust = 0.0
        if risk_per_unit > 0 and current_atr > 0:
            atr_to_risk = current_atr / risk_per_unit
            if atr_to_risk >= 1.2:
                vol_adjust = 0.6
            elif atr_to_risk >= 0.8:
                vol_adjust = 0.3
            elif atr_to_risk <= 0.4:
                vol_adjust = -0.2

        return min(3.0, max(1.0, regime_base + hold_adjust + vol_adjust))

    @staticmethod
    def _has_proof_window_state(state: PositionExitState) -> bool:
        status = str(state.proof_window_status or "").strip().lower()
        return (
            bool(state.proof_window_active)
            or bool(state.proof_window_promoted)
            or status not in {"", "inactive", "unknown"}
            or int(state.proof_window_max_bars) > 0
            or float(state.proof_window_promotion_threshold_r) > 0
        )
