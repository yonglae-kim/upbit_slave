from __future__ import annotations

from core.rsi_bb_reversal_long import (
    ReversalSignal,
    evaluate_long_entry as evaluate_long_entry_impl,
    should_exit_long,
)
from core.decision_models import StrategySignal


STRATEGY_NAME = "baseline"
LEGACY_STRATEGY_NAME = "rsi_bb_reversal_long"


def evaluate_long_entry(
    data: dict[str, list[dict[str, object]]],
    params: object,
) -> StrategySignal:
    result = evaluate_long_entry_impl(data, params)
    return StrategySignal(
        accepted=bool(result.final_pass),
        reason=str(result.reason),
        diagnostics=dict(result.diagnostics),
    )


__all__ = [
    "LEGACY_STRATEGY_NAME",
    "ReversalSignal",
    "StrategySignal",
    "STRATEGY_NAME",
    "evaluate_long_entry",
    "should_exit_long",
]
