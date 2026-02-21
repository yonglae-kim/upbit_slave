from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass
class EntryDecision:
    allowed: bool
    reason: str = "ok"
    order_krw: float = 0.0


class RiskManager:
    def __init__(
        self,
        *,
        risk_per_trade_pct: float,
        max_daily_loss_pct: float,
        max_consecutive_losses: int,
        max_concurrent_positions: int,
        min_order_krw: float,
    ):
        self.risk_per_trade_pct = max(0.0, float(risk_per_trade_pct))
        self.max_daily_loss_pct = max(0.0, float(max_daily_loss_pct))
        self.max_consecutive_losses = max(0, int(max_consecutive_losses))
        self.max_concurrent_positions = max(1, int(max_concurrent_positions))
        self.min_order_krw = float(min_order_krw)

        self._baseline_equity: float | None = None
        self._loss_streak = 0
        self._realized_pnl_today = 0.0
        self._pnl_day = date.today()

    def reset_daily_if_needed(self, now: datetime | None = None) -> None:
        current_date = (now or datetime.now(timezone.utc)).date()
        if current_date != self._pnl_day:
            self._pnl_day = current_date
            self._realized_pnl_today = 0.0
            self._loss_streak = 0

    def set_baseline_equity(self, total_equity_krw: float) -> None:
        equity = max(0.0, float(total_equity_krw))
        if self._baseline_equity is None and equity > 0:
            self._baseline_equity = equity

    def record_trade_result(self, pnl_krw: float) -> None:
        self.reset_daily_if_needed()
        pnl = float(pnl_krw)
        self._realized_pnl_today += pnl
        if pnl < 0:
            self._loss_streak += 1
        elif pnl > 0:
            self._loss_streak = 0

    def _daily_loss_limit_breached(self) -> bool:
        if self._baseline_equity is None or self._baseline_equity <= 0:
            return False
        max_daily_loss = self._baseline_equity * self.max_daily_loss_pct
        return -self._realized_pnl_today >= max_daily_loss > 0

    def allow_entry(self, *, available_krw: float, held_markets: list[str]) -> EntryDecision:
        self.reset_daily_if_needed()

        if len(held_markets) >= self.max_concurrent_positions:
            return EntryDecision(allowed=False, reason="max_concurrent_positions")
        if self.max_consecutive_losses and self._loss_streak >= self.max_consecutive_losses:
            return EntryDecision(allowed=False, reason="max_consecutive_losses")
        if self._daily_loss_limit_breached():
            return EntryDecision(allowed=False, reason="max_daily_loss")

        order_krw = float(available_krw) * self.risk_per_trade_pct
        if order_krw < self.min_order_krw:
            return EntryDecision(allowed=False, reason="risk_sized_order_too_small")

        return EntryDecision(allowed=True, reason="ok", order_krw=order_krw)
