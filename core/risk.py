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
        max_correlated_positions: int,
        correlation_groups: dict[str, str] | None,
        min_order_krw: float,
        quality_multiplier_min_bound: float = 0.7,
        quality_multiplier_max_bound: float = 1.2,
    ):
        self.risk_per_trade_pct = max(0.0, float(risk_per_trade_pct))
        self.max_daily_loss_pct = max(0.0, float(max_daily_loss_pct))
        self.max_consecutive_losses = max(0, int(max_consecutive_losses))
        self.max_concurrent_positions = max(1, int(max_concurrent_positions))
        self.max_correlated_positions = max(1, int(max_correlated_positions))
        self.correlation_groups = correlation_groups or {}
        self.min_order_krw = float(min_order_krw)
        self.quality_multiplier_min_bound = max(0.1, float(quality_multiplier_min_bound))
        self.quality_multiplier_max_bound = max(self.quality_multiplier_min_bound, float(quality_multiplier_max_bound))

        # Baseline policy:
        # - Keep one baseline equity snapshot per UTC day.
        # - Reset realized PnL/loss streak exactly on UTC day rollover.
        # - Baseline is set by set_baseline_equity(total_equity_krw) and can be refreshed
        #   once per new UTC day using the first positive total_equity_krw observation.
        self._baseline_equity: float | None = None
        self._baseline_day = date.today()
        self._loss_streak = 0
        self._realized_pnl_today = 0.0
        self._pnl_day = date.today()

    def reset_daily_if_needed(self, now: datetime | None = None) -> None:
        """Reset daily trackers at UTC day rollover.

        Tracking policy:
        - Realized PnL and consecutive-loss streak are day-scoped and cleared when
          UTC date changes.
        - Baseline equity is also day-scoped. The baseline value itself is cleared on
          rollover and re-initialized by the next set_baseline_equity() call with a
          positive total_equity_krw value.
        """
        current_date = (now or datetime.now(timezone.utc)).date()
        if current_date != self._pnl_day:
            self._pnl_day = current_date
            self._realized_pnl_today = 0.0
            self._loss_streak = 0
            self._baseline_equity = None
            self._baseline_day = current_date

    def set_baseline_equity(self, total_equity_krw: float, now: datetime | None = None) -> None:
        """Set daily baseline from total equity (cash + marked coin value)."""
        self.reset_daily_if_needed(now)
        current_date = (now or datetime.now(timezone.utc)).date()
        equity = max(0.0, float(total_equity_krw))

        if self._baseline_day != current_date:
            self._baseline_day = current_date
            self._baseline_equity = None

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

    def clamp_quality_multiplier(self, quality_multiplier: float) -> float:
        clamped = min(self.quality_multiplier_max_bound, max(self.quality_multiplier_min_bound, float(quality_multiplier)))
        if self._baseline_equity is None or self._baseline_equity <= 0 or self.max_daily_loss_pct <= 0:
            return clamped

        max_daily_loss = self._baseline_equity * self.max_daily_loss_pct
        if max_daily_loss <= 0:
            return clamped

        remaining_loss_budget = max_daily_loss + self._realized_pnl_today
        remaining_ratio = remaining_loss_budget / max_daily_loss
        dynamic_cap = self.quality_multiplier_max_bound
        if remaining_ratio <= 0.1:
            dynamic_cap = min(dynamic_cap, 0.8)
        elif remaining_ratio <= 0.2:
            dynamic_cap = min(dynamic_cap, 1.0)

        return min(dynamic_cap, max(self.quality_multiplier_min_bound, clamped))

    def compute_risk_sized_order_krw(self, *, available_krw: float, entry_price: float, stop_price: float) -> float:
        if available_krw <= 0 or entry_price <= 0 or stop_price <= 0 or entry_price <= stop_price:
            return 0.0
        risk_budget_krw = float(available_krw) * self.risk_per_trade_pct
        if risk_budget_krw <= 0:
            return 0.0

        per_unit_risk = entry_price - stop_price
        qty = risk_budget_krw / per_unit_risk
        if qty <= 0:
            return 0.0
        notional = qty * entry_price
        return min(float(available_krw), notional)

    def _market_group(self, market: str) -> str | None:
        return self.correlation_groups.get(market)

    def _correlated_exposure_breached(self, *, candidate_market: str, held_markets: list[str]) -> bool:
        group = self._market_group(candidate_market)
        if not group:
            return False

        correlated_count = sum(1 for market in held_markets if self._market_group(market) == group)
        return correlated_count >= self.max_correlated_positions

    def allow_entry(self, *, available_krw: float, held_markets: list[str], candidate_market: str) -> EntryDecision:
        self.reset_daily_if_needed()

        if len(held_markets) >= self.max_concurrent_positions:
            return EntryDecision(allowed=False, reason="max_concurrent_positions")
        if self._correlated_exposure_breached(candidate_market=candidate_market, held_markets=held_markets):
            return EntryDecision(allowed=False, reason="max_correlated_positions")
        if self.max_consecutive_losses and self._loss_streak >= self.max_consecutive_losses:
            return EntryDecision(allowed=False, reason="max_consecutive_losses")
        if self._daily_loss_limit_breached():
            return EntryDecision(allowed=False, reason="max_daily_loss")

        if float(available_krw) < self.min_order_krw:
            return EntryDecision(allowed=False, reason="risk_sized_order_too_small")

        return EntryDecision(allowed=True, reason="ok")
