from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.decision_models import StrategySignal
from core.strategy import StrategyParams
from core.strategies import baseline, candidate_v1, ict_v1


class UnknownStrategyError(ValueError):
    pass


@dataclass(frozen=True)
class RegisteredStrategy:
    canonical_name: str
    entry_evaluator: Callable[
        [dict[str, list[dict[str, object]]], StrategyParams], StrategySignal
    ]
    exit_evaluator: Callable[..., bool]
    aliases: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.canonical_name

    @property
    def runtime_name(self) -> str:
        legacy_name = str(self.metadata.get("legacy_strategy_name", "")).strip()
        return legacy_name or self.canonical_name


_REGISTERED_STRATEGIES: dict[str, RegisteredStrategy] = {
    baseline.STRATEGY_NAME: RegisteredStrategy(
        canonical_name=baseline.STRATEGY_NAME,
        entry_evaluator=baseline.evaluate_long_entry,
        exit_evaluator=baseline.should_exit_long,
        aliases=(baseline.LEGACY_STRATEGY_NAME,),
        metadata={
            "legacy_strategy_name": baseline.LEGACY_STRATEGY_NAME,
            "surface_module": "core.strategies.baseline",
        },
    ),
    candidate_v1.STRATEGY_NAME: RegisteredStrategy(
        canonical_name=candidate_v1.STRATEGY_NAME,
        entry_evaluator=candidate_v1.evaluate_long_entry,
        exit_evaluator=candidate_v1.should_exit_long,
        metadata={
            "surface_module": "core.strategies.candidate_v1",
        },
    ),
    ict_v1.STRATEGY_NAME: RegisteredStrategy(
        canonical_name=ict_v1.STRATEGY_NAME,
        entry_evaluator=ict_v1.evaluate_long_entry,
        exit_evaluator=ict_v1.should_exit_long,
        metadata={
            "surface_module": "core.strategies.ict_v1",
        },
    ),
}

_STRATEGY_ALIASES: dict[str, str] = {
    baseline.LEGACY_STRATEGY_NAME: baseline.STRATEGY_NAME,
}


def normalize_strategy_name(name: str) -> str:
    normalized_name = str(name or "").strip().lower()
    if not normalized_name:
        raise UnknownStrategyError("strategy_name must not be empty")
    return _STRATEGY_ALIASES.get(normalized_name, normalized_name)


def get_strategy(name: str) -> RegisteredStrategy:
    normalized_name = normalize_strategy_name(name)
    strategy = _REGISTERED_STRATEGIES.get(normalized_name)
    if strategy is None:
        supported_names = ", ".join(sorted(supported_strategy_names()))
        raise UnknownStrategyError(
            f"unknown strategy_name '{name}'. supported: {supported_names}"
        )
    return strategy


def supported_strategy_names() -> tuple[str, ...]:
    return tuple(sorted({*_REGISTERED_STRATEGIES.keys(), *_STRATEGY_ALIASES.keys()}))
