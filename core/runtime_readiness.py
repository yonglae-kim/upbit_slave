from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from core.config import TradingConfig


DEFAULT_KILL_SWITCH_PATH: Final = "runtime_logs/KILL_SWITCH"
KILL_SWITCH_ACTIVE_REASON: Final = "kill_switch_active"
KILL_SWITCH_UNREADABLE_REASON: Final = "kill_switch_unreadable"
LIVE_AUTHORIZATION_REQUIRED_REASON: Final = "live_authorization_required"
UNKNOWN_RUNTIME_MODE_REASON: Final = "unknown_runtime_mode"
RECONCILIATION_BLOCKED_REASON: Final = "reconciliation_blocked"

_PAPER_MODES: Final = frozenset({"paper", "dry_run"})
_BROKER_KIND_BY_MODE: Final = {
    "paper": "paper",
    "dry_run": "paper",
    "live": "upbit_live",
}


class RuntimeStatusPayload(TypedDict):
    mode: str
    strategy: str
    broker_kind: str
    entries_allowed: bool
    reason: str | None
    kill_switch_path: str
    kill_switch_active: bool
    live_authorization: bool
    runtime_promotion_allowed: bool


@dataclass(frozen=True)
class RuntimeStatus:
    mode: str
    strategy: str
    broker_kind: str
    entries_allowed: bool
    reason: str | None
    kill_switch_path: str
    kill_switch_active: bool
    live_authorization: bool
    runtime_promotion_allowed: bool

    def to_payload(self) -> RuntimeStatusPayload:
        return {
            "mode": self.mode,
            "strategy": self.strategy,
            "broker_kind": self.broker_kind,
            "entries_allowed": self.entries_allowed,
            "reason": self.reason,
            "kill_switch_path": self.kill_switch_path,
            "kill_switch_active": self.kill_switch_active,
            "live_authorization": self.live_authorization,
            "runtime_promotion_allowed": self.runtime_promotion_allowed,
        }


class RuntimeReadiness:
    """Evaluate entry readiness and latch the first blocking state."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self._latched_status: RuntimeStatus | None = None

    def status(
        self,
        *,
        reconciliation_blocked: bool = False,
        reconciliation_reason: str | None = None,
    ) -> RuntimeStatus:
        if self._latched_status is not None:
            return self._latched_status

        status = _evaluate_status(
            self.config,
            reconciliation_blocked=reconciliation_blocked,
            reconciliation_reason=reconciliation_reason,
        )
        if not status.entries_allowed:
            self._latched_status = status
        return status


def runtime_status_payload(config: TradingConfig) -> RuntimeStatusPayload:
    """Return the non-networking machine-readable runtime status payload."""
    return RuntimeReadiness(config).status().to_payload()


def _evaluate_status(
    config: TradingConfig,
    *,
    reconciliation_blocked: bool,
    reconciliation_reason: str | None,
) -> RuntimeStatus:
    mode = str(config.mode or "").strip().lower()
    strategy = str(getattr(config, "strategy_name", ""))
    kill_switch_path = str(
        getattr(config, "kill_switch_path", DEFAULT_KILL_SWITCH_PATH)
    )
    live_authorization = getattr(config, "live_authorization", False) is True
    runtime_promotion_allowed = (
        getattr(config, "runtime_promotion_allowed", False) is True
    )
    broker_kind = _BROKER_KIND_BY_MODE.get(mode, "unknown")
    kill_switch_active, kill_switch_reason = _kill_switch_state(kill_switch_path)

    if reconciliation_blocked:
        return _blocked_status(
            mode=mode,
            strategy=strategy,
            broker_kind=broker_kind,
            reason=reconciliation_reason or RECONCILIATION_BLOCKED_REASON,
            kill_switch_path=kill_switch_path,
            kill_switch_active=kill_switch_active,
            live_authorization=live_authorization,
            runtime_promotion_allowed=runtime_promotion_allowed,
        )
    if kill_switch_reason is not None:
        return _blocked_status(
            mode=mode,
            strategy=strategy,
            broker_kind=broker_kind,
            reason=kill_switch_reason,
            kill_switch_path=kill_switch_path,
            kill_switch_active=kill_switch_active,
            live_authorization=live_authorization,
            runtime_promotion_allowed=runtime_promotion_allowed,
        )
    if mode in _PAPER_MODES:
        return RuntimeStatus(
            mode=mode,
            strategy=strategy,
            broker_kind=broker_kind,
            entries_allowed=True,
            reason=None,
            kill_switch_path=kill_switch_path,
            kill_switch_active=False,
            live_authorization=live_authorization,
            runtime_promotion_allowed=runtime_promotion_allowed,
        )
    if mode == "live" and not (
        live_authorization and runtime_promotion_allowed
    ):
        return _blocked_status(
            mode=mode,
            strategy=strategy,
            broker_kind=broker_kind,
            reason=LIVE_AUTHORIZATION_REQUIRED_REASON,
            kill_switch_path=kill_switch_path,
            kill_switch_active=False,
            live_authorization=live_authorization,
            runtime_promotion_allowed=runtime_promotion_allowed,
        )
    if mode == "live":
        return RuntimeStatus(
            mode=mode,
            strategy=strategy,
            broker_kind=broker_kind,
            entries_allowed=True,
            reason=None,
            kill_switch_path=kill_switch_path,
            kill_switch_active=False,
            live_authorization=live_authorization,
            runtime_promotion_allowed=runtime_promotion_allowed,
        )
    return _blocked_status(
        mode=mode,
        strategy=strategy,
        broker_kind=broker_kind,
        reason=UNKNOWN_RUNTIME_MODE_REASON,
        kill_switch_path=kill_switch_path,
        kill_switch_active=False,
        live_authorization=live_authorization,
        runtime_promotion_allowed=runtime_promotion_allowed,
    )


def _blocked_status(
    *,
    mode: str,
    strategy: str,
    broker_kind: str,
    reason: str,
    kill_switch_path: str,
    kill_switch_active: bool,
    live_authorization: bool,
    runtime_promotion_allowed: bool,
) -> RuntimeStatus:
    return RuntimeStatus(
        mode=mode,
        strategy=strategy,
        broker_kind=broker_kind,
        entries_allowed=False,
        reason=reason,
        kill_switch_path=kill_switch_path,
        kill_switch_active=kill_switch_active,
        live_authorization=live_authorization,
        runtime_promotion_allowed=runtime_promotion_allowed,
    )


def _kill_switch_state(path_value: str) -> tuple[bool, str | None]:
    if not path_value.strip():
        return False, KILL_SWITCH_UNREADABLE_REASON
    try:
        Path(path_value).stat()
    except FileNotFoundError:
        return False, None
    except (OSError, ValueError):
        return False, KILL_SWITCH_UNREADABLE_REASON
    return True, KILL_SWITCH_ACTIVE_REASON
