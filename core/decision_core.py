from __future__ import annotations

from dataclasses import asdict, replace
from typing import cast

from core.decision_models import DecisionContext, DecisionIntent, StrategySignal
from core.position_policy import (
    PositionExitState,
    PositionOrderPolicy,
    dump_position_exit_state,
    evaluate_position_state,
)
from core.strategy import classify_market_regime, regime_filter_diagnostics
from core.strategy import StrategyParams
from core.strategy_registry import RegisteredStrategy, get_strategy


def evaluate_market(
    context: DecisionContext,
    *,
    strategy_params: StrategyParams,
    order_policy: PositionOrderPolicy,
) -> DecisionIntent:
    strategy = get_strategy(context.strategy_name)
    if _has_open_position(context):
        return _evaluate_exit(
            context,
            strategy_params=strategy_params,
            order_policy=order_policy,
            strategy=strategy,
        )
    return _evaluate_entry(
        context,
        strategy_params=strategy_params,
        strategy=strategy,
    )


def _evaluate_entry(
    context: DecisionContext,
    *,
    strategy_params: StrategyParams,
    strategy: RegisteredStrategy,
) -> DecisionIntent:
    effective_strategy_params, regime, regime_diagnostics = (
        _resolve_entry_strategy_params(
            context,
            strategy_params=strategy_params,
        )
    )
    entry_signal = _evaluate_entry_signal(
        context,
        strategy_params=effective_strategy_params,
        strategy=strategy,
    )
    entry_diagnostics = _entry_diagnostics(
        context,
        entry_signal=entry_signal,
        strategy=strategy,
        effective_strategy_params=effective_strategy_params,
        regime=regime,
        regime_diagnostics=regime_diagnostics,
    )
    if not entry_signal.accepted:
        return DecisionIntent(
            action="hold",
            reason=entry_signal.reason,
            diagnostics=entry_diagnostics,
            next_position_state=dict(context.position.state),
        )

    next_position_state = _build_entry_position_state(
        context,
        entry_signal,
        regime=regime,
    )
    return DecisionIntent(
        action="enter",
        reason=entry_signal.reason,
        diagnostics=entry_diagnostics,
        next_position_state=next_position_state,
    )


def _evaluate_exit(
    context: DecisionContext,
    *,
    strategy_params: StrategyParams,
    order_policy: PositionOrderPolicy,
    strategy: RegisteredStrategy,
) -> DecisionIntent:
    price = _current_price(context)
    current_atr = _market_metric(context, "current_atr")
    swing_low = _market_metric(context, "swing_low")
    state_payload = dict(context.position.state)
    state_payload["bars_held"] = max(0, _state_int(state_payload, "bars_held")) + 1
    avg_buy_price = float(context.position.entry_price or 0.0)
    strategy_entry_price = _state_float(state_payload, "entry_price")
    if strategy_entry_price <= 0:
        strategy_entry_price = avg_buy_price
    sell_decision_rule = _sell_decision_rule(context)
    policy_signal_exit = signal_exit = False

    signal_exit = bool(
        strategy.exit_evaluator(
            _strategy_market_data(context),
            strategy_params,
            entry_price=strategy_entry_price,
            initial_stop_price=_state_float(state_payload, "initial_stop_price"),
            risk_per_unit=_state_float(state_payload, "risk_per_unit"),
        )
    )
    policy_signal_exit = signal_exit if sell_decision_rule != "and" else False
    decision, next_position_state = evaluate_position_state(
        order_policy,
        state_payload=state_payload,
        avg_buy_price=avg_buy_price,
        current_price=price,
        signal_exit=policy_signal_exit,
        current_atr=current_atr,
        swing_low=swing_low,
        strategy_name=strategy.runtime_name,
        partial_take_profit_enabled=bool(strategy_params.partial_take_profit_enabled),
        partial_take_profit_r=float(strategy_params.partial_take_profit_r),
        partial_take_profit_size=float(strategy_params.partial_take_profit_size),
        move_stop_to_breakeven_after_partial=bool(
            strategy_params.move_stop_to_breakeven_after_partial
        ),
        max_hold_bars=int(strategy_params.max_hold_bars),
    )
    diagnostics = _with_strategy_name(
        strategy.name,
        {
            **decision.diagnostics,
            "signal_exit": signal_exit,
            "sell_decision_rule": sell_decision_rule,
            "qty_ratio": float(decision.qty_ratio),
        },
    )
    if sell_decision_rule == "and" and (not signal_exit or not decision.should_exit):
        return DecisionIntent(
            action="hold",
            reason="hold",
            diagnostics=diagnostics,
            next_position_state=next_position_state,
        )

    if decision.should_exit:
        action = "exit_full" if float(decision.qty_ratio) >= 1.0 else "exit_partial"
        if action == "exit_full":
            next_position_state = dump_position_exit_state(PositionExitState())
        return DecisionIntent(
            action=action,
            reason=decision.reason,
            diagnostics=diagnostics,
            next_position_state=next_position_state,
        )

    return DecisionIntent(
        action="hold",
        reason="hold",
        diagnostics=diagnostics,
        next_position_state=next_position_state,
    )


def _evaluate_entry_signal(
    context: DecisionContext,
    *,
    strategy_params: StrategyParams,
    strategy: RegisteredStrategy,
) -> StrategySignal:
    result = strategy.entry_evaluator(_strategy_market_data(context), strategy_params)
    accepted = bool(getattr(result, "accepted", getattr(result, "final_pass", False)))
    reason = str(getattr(result, "reason", "hold"))
    diagnostics = dict(getattr(result, "diagnostics", {}) or {})
    return StrategySignal(
        accepted=accepted,
        reason=reason,
        diagnostics=diagnostics,
    )


def _build_entry_position_state(
    context: DecisionContext,
    entry_signal: StrategySignal,
    *,
    regime: str,
) -> dict[str, object]:
    diagnostics = dict(entry_signal.diagnostics)
    price = _current_price(context)
    entry_price = _value_as_float(diagnostics.get("entry_price"), price)
    stop_price = _value_as_float(diagnostics.get("stop_price"), entry_price)
    risk_per_unit = _value_as_float(
        diagnostics.get("r_value"),
        max(entry_price - stop_price, 0.0),
    )
    return {
        "peak_price": price,
        "entry_atr": _market_metric(context, "current_atr"),
        "entry_swing_low": _market_metric(context, "swing_low"),
        "entry_price": entry_price,
        "initial_stop_price": stop_price,
        "risk_per_unit": risk_per_unit,
        "bars_held": 0,
        "entry_regime": regime,
        "partial_take_profit_done": False,
        "strategy_partial_done": False,
        "breakeven_armed": False,
        "highest_r": 0.0,
        "lowest_r": 0.0,
        "drawdown_from_peak_r": 0.0,
    }


def _strategy_market_data(
    context: DecisionContext,
) -> dict[str, list[dict[str, object]]]:
    return {
        timeframe: list(candles)
        for timeframe, candles in context.market.candles_by_timeframe.items()
    }


def _entry_diagnostics(
    context: DecisionContext,
    *,
    entry_signal: StrategySignal,
    strategy: RegisteredStrategy,
    effective_strategy_params: StrategyParams,
    regime: str,
    regime_diagnostics: dict[str, object],
) -> dict[str, object]:
    diagnostics = dict(entry_signal.diagnostics)
    sizing = _build_entry_sizing(
        context,
        diagnostics=diagnostics,
    )
    quality_score = _value_as_float(diagnostics.get("quality_score"), 0.0)
    return _with_strategy_name(
        strategy.name,
        {
            **diagnostics,
            "regime": regime,
            "entry_regime": regime,
            "regime_diagnostics": regime_diagnostics,
            "quality_score": quality_score,
            "quality_bucket": _sizing_label(sizing, "quality_bucket", default="low"),
            "quality_multiplier": _sizing_float(sizing, "quality_multiplier"),
            "market_damping": dict(_sizing_state(sizing, "market_damping")),
            "sizing": sizing,
            "effective_strategy_params": asdict(effective_strategy_params),
        },
    )


def _resolve_entry_strategy_params(
    context: DecisionContext,
    *,
    strategy_params: StrategyParams,
) -> tuple[StrategyParams, str, dict[str, object]]:
    c15 = list(context.market.candles_by_timeframe.get("15m", []))
    selection_regime = classify_market_regime(c15, strategy_params)
    override_map = _diagnostic_map(context, "regime_strategy_overrides")
    override_value = override_map.get(selection_regime)
    overrides = _dict_str_object(override_value)
    effective_strategy_params = strategy_params
    for key, value in overrides.items():
        if hasattr(effective_strategy_params, key):
            effective_strategy_params = replace(
                effective_strategy_params, **{key: value}
            )
    regime = classify_market_regime(c15, effective_strategy_params)
    regime_diagnostics = dict(
        regime_filter_diagnostics(c15, effective_strategy_params) or {}
    )
    return effective_strategy_params, str(regime or "unknown"), regime_diagnostics


def _build_entry_sizing(
    context: DecisionContext,
    *,
    diagnostics: dict[str, object],
) -> dict[str, object]:
    sizing_policy = _diagnostic_map(context, "entry_sizing_policy")
    available_krw = float(context.portfolio.available_krw)
    entry_price = _value_as_float(
        diagnostics.get("entry_price"), _current_price(context)
    )
    stop_price = _value_as_float(diagnostics.get("stop_price"), entry_price)
    risk_per_unit = _value_as_float(
        diagnostics.get("r_value"),
        max(entry_price - stop_price, 0.0),
    )
    risk_per_trade_pct = _map_float(sizing_policy, "risk_per_trade_pct")
    risk_sized_order_krw = _compute_risk_sized_order_krw(
        available_krw=available_krw,
        risk_per_trade_pct=risk_per_trade_pct,
        entry_price=entry_price,
        stop_price=stop_price,
    )
    fee_rate = _map_float(sizing_policy, "fee_rate")
    max_holdings = max(1, _map_int(sizing_policy, "max_holdings", default=1))
    cash_split_order_krw = (available_krw / max_holdings) * (1 - fee_rate)
    hard_cash_limit_krw = available_krw * (1 - fee_rate)
    configured_cash_cap = _map_float(sizing_policy, "max_order_krw_by_cash_management")
    if configured_cash_cap <= 0:
        configured_cash_cap = cash_split_order_krw
    position_sizing_mode = _map_label(
        sizing_policy,
        "position_sizing_mode",
        default="risk_first",
    )
    if position_sizing_mode == "cash_split_first":
        cash_cap_order_krw = min(cash_split_order_krw, hard_cash_limit_krw)
        if _map_float(sizing_policy, "max_order_krw_by_cash_management") > 0:
            cash_cap_order_krw = min(
                cash_cap_order_krw,
                _map_float(sizing_policy, "max_order_krw_by_cash_management"),
            )
    else:
        cash_cap_order_krw = min(hard_cash_limit_krw, configured_cash_cap)
    base_order_krw = min(risk_sized_order_krw, cash_cap_order_krw)

    quality_score = _value_as_float(diagnostics.get("quality_score"), 0.0)
    if not bool(diagnostics.get("use_quality_multiplier", True)):
        quality_bucket = "disabled"
        raw_quality_multiplier = 1.0
    else:
        low_threshold = _map_float(sizing_policy, "quality_score_low_threshold")
        high_threshold = _map_float(sizing_policy, "quality_score_high_threshold")
        if quality_score >= high_threshold:
            quality_bucket = "high"
            raw_quality_multiplier = _map_float(
                sizing_policy, "quality_multiplier_high", default=1.0
            )
        elif quality_score >= low_threshold:
            quality_bucket = "mid"
            raw_quality_multiplier = _map_float(
                sizing_policy, "quality_multiplier_mid", default=1.0
            )
        else:
            quality_bucket = "low"
            raw_quality_multiplier = _map_float(
                sizing_policy, "quality_multiplier_low", default=1.0
            )
    quality_multiplier = _clamp_quality_multiplier(
        raw_quality_multiplier=raw_quality_multiplier,
        min_bound=_map_float(
            sizing_policy, "quality_multiplier_min_bound", default=0.7
        ),
        max_bound=_map_float(
            sizing_policy, "quality_multiplier_max_bound", default=1.2
        ),
        baseline_equity=_map_float(sizing_policy, "baseline_equity"),
        realized_pnl_today=_map_float(sizing_policy, "realized_pnl_today"),
        max_daily_loss_pct=_map_float(sizing_policy, "max_daily_loss_pct"),
    )
    final_order_krw = base_order_krw * quality_multiplier
    market_damping = _compute_market_damping(context)
    damping_factor = _sizing_float(market_damping, "damping_factor", default=1.0)
    final_order_krw *= damping_factor
    return {
        "risk_sized_order_krw": risk_sized_order_krw,
        "cash_cap_order_krw": cash_cap_order_krw,
        "base_order_krw": base_order_krw,
        "final_order_krw": final_order_krw,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "risk_per_unit": risk_per_unit,
        "quality_bucket": quality_bucket,
        "quality_multiplier": quality_multiplier,
        "market_damping": market_damping,
    }


def _compute_market_damping(context: DecisionContext) -> dict[str, object]:
    damping_policy = _diagnostic_map(context, "market_damping_policy")
    if not bool(damping_policy.get("enabled", False)):
        return {}
    ticker = _market_state(context, "ticker")
    ask = _value_as_float(ticker.get("ask_price"), 0.0)
    bid = _value_as_float(ticker.get("bid_price"), 0.0)
    last = _value_as_float(ticker.get("trade_price"), _current_price(context))
    relative_spread = ((ask - bid) / last) if ask > 0 and bid > 0 and last > 0 else 0.0
    max_spread = max(1e-9, _map_float(damping_policy, "max_spread", default=0.003))
    spread_factor = (
        min(1.0, max_spread / relative_spread) if relative_spread > 0 else 1.0
    )
    trade_value_24h = _value_as_float(
        ticker.get("acc_trade_price_24h")
        or ticker.get("acc_trade_price")
        or ticker.get("trade_volume"),
        0.0,
    )
    min_trade_value = max(
        1.0, _map_float(damping_policy, "min_trade_value_24h", default=1.0)
    )
    trade_value_factor = (
        min(1.0, trade_value_24h / min_trade_value) if trade_value_24h > 0 else 0.0
    )
    liquidity_factor = min(spread_factor, trade_value_factor)
    atr_period = max(2, _map_int(damping_policy, "atr_period", default=14))
    atr = _atr_from_market(context, period=atr_period)
    atr_ratio = atr / last if atr > 0 and last > 0 else 0.0
    max_atr_ratio = max(1e-9, _map_float(damping_policy, "max_atr_ratio", default=0.03))
    volatility_factor = min(1.0, max_atr_ratio / atr_ratio) if atr_ratio > 0 else 1.0
    reasons: list[str] = []
    if spread_factor < 1.0:
        reasons.append(f"high_spread:{relative_spread:.6f}>{max_spread:.6f}")
    if trade_value_factor < 1.0:
        reasons.append(
            f"low_trade_value_24h:{trade_value_24h:.0f}<{min_trade_value:.0f}"
        )
    if volatility_factor < 1.0:
        reasons.append(f"high_atr_ratio:{atr_ratio:.6f}>{max_atr_ratio:.6f}")
    return {
        "liquidity_factor": liquidity_factor,
        "volatility_factor": volatility_factor,
        "damping_factor": min(liquidity_factor, volatility_factor),
        "reasons": reasons,
    }


def _compute_risk_sized_order_krw(
    *,
    available_krw: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_price: float,
) -> float:
    if (
        available_krw <= 0
        or entry_price <= 0
        or stop_price <= 0
        or entry_price <= stop_price
    ):
        return 0.0
    risk_budget_krw = available_krw * max(0.0, risk_per_trade_pct)
    if risk_budget_krw <= 0:
        return 0.0
    per_unit_risk = entry_price - stop_price
    qty = risk_budget_krw / per_unit_risk
    if qty <= 0:
        return 0.0
    return min(available_krw, qty * entry_price)


def _clamp_quality_multiplier(
    *,
    raw_quality_multiplier: float,
    min_bound: float,
    max_bound: float,
    baseline_equity: float,
    realized_pnl_today: float,
    max_daily_loss_pct: float,
) -> float:
    clamped = min(max_bound, max(min_bound, raw_quality_multiplier))
    if baseline_equity <= 0 or max_daily_loss_pct <= 0:
        return clamped
    max_daily_loss = baseline_equity * max_daily_loss_pct
    if max_daily_loss <= 0:
        return clamped
    remaining_loss_budget = max_daily_loss + realized_pnl_today
    remaining_ratio = remaining_loss_budget / max_daily_loss
    dynamic_cap = max_bound
    if remaining_ratio <= 0.1:
        dynamic_cap = min(dynamic_cap, 0.8)
    elif remaining_ratio <= 0.2:
        dynamic_cap = min(dynamic_cap, 1.0)
    return min(dynamic_cap, max(min_bound, clamped))


def _atr_from_market(context: DecisionContext, *, period: int) -> float:
    candles_newest = list(context.market.candles_by_timeframe.get("1m", []))
    if period <= 0:
        return 0.0
    candles = list(reversed(candles_newest))
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    for index in range(1, len(candles)):
        cur, prev = candles[index], candles[index - 1]
        high = _value_as_float(
            cur.get("high_price"), _value_as_float(cur.get("trade_price"), 0.0)
        )
        low = _value_as_float(
            cur.get("low_price"), _value_as_float(cur.get("trade_price"), 0.0)
        )
        prev_close = _value_as_float(prev.get("trade_price"), 0.0)
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if not trs:
        return 0.0
    window = trs[-min(period, len(trs)) :]
    return sum(window) / len(window)


def _diagnostic_map(context: DecisionContext, key: str) -> dict[str, object]:
    value = context.diagnostics.get(key)
    return _dict_str_object(value)


def _market_state(context: DecisionContext, key: str) -> dict[str, object]:
    value = context.market.diagnostics.get(key)
    return _dict_str_object(value)


def _map_float(mapping: dict[str, object], key: str, *, default: float = 0.0) -> float:
    return _value_as_float(mapping.get(key), default)


def _map_int(mapping: dict[str, object], key: str, *, default: int = 0) -> int:
    value = mapping.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _map_label(mapping: dict[str, object], key: str, *, default: str) -> str:
    value = mapping.get(key)
    if value is None:
        return default
    label = str(value).strip()
    return label or default


def _sizing_float(sizing: dict[str, object], key: str, default: float = 0.0) -> float:
    return _value_as_float(sizing.get(key), default)


def _sizing_label(sizing: dict[str, object], key: str, *, default: str) -> str:
    value = sizing.get(key)
    if value is None:
        return default
    label = str(value).strip()
    return label or default


def _sizing_state(sizing: dict[str, object], key: str) -> dict[str, object]:
    value = sizing.get(key)
    return _dict_str_object(value)


def _dict_str_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    raw_mapping = cast(dict[object, object], value)
    for key, item in raw_mapping.items():
        normalized[str(key)] = item
    return normalized


def _with_strategy_name(
    strategy_name: str, diagnostics: dict[str, object]
) -> dict[str, object]:
    return {
        "strategy_name": strategy_name,
        **dict(diagnostics),
    }


def _has_open_position(context: DecisionContext) -> bool:
    return (
        float(context.position.quantity) > 0.0
        and float(context.position.entry_price or 0.0) > 0.0
    )


def _current_price(context: DecisionContext) -> float:
    if context.market.price is not None:
        return float(context.market.price)
    candles = list(context.market.candles_by_timeframe.get("1m", []))
    if candles:
        return _value_as_float(candles[0].get("trade_price"), 0.0)
    return 0.0


def _market_metric(context: DecisionContext, key: str) -> float:
    return _value_as_float(context.market.diagnostics.get(key), 0.0)


def _sell_decision_rule(context: DecisionContext) -> str:
    value = context.diagnostics.get("sell_decision_rule")
    if value is None:
        return "or"
    resolved = str(value).strip().lower()
    if resolved in {"or", "and"}:
        return resolved
    return "or"


def _state_float(state_payload: dict[str, object], key: str) -> float:
    return _value_as_float(state_payload.get(key), 0.0)


def _state_int(state_payload: dict[str, object], key: str) -> int:
    value = state_payload.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _value_as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return default
