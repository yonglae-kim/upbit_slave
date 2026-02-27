from __future__ import annotations

from typing import Protocol


def format_entry_summary(
    *,
    market: str,
    entry_price: float,
    entry_score: float,
    quality_bucket: str,
    final_order_krw: float,
) -> str:
    return (
        f"[ENTRY] {market} px={entry_price:.4f} score={entry_score:.3f} "
        f"bucket={quality_bucket} order={int(final_order_krw)}KRW"
    )


def format_exit_summary(
    *,
    market: str,
    exit_price: float,
    reason: str,
    realized_r: float,
    daily_pnl_krw: float,
) -> str:
    return (
        f"[EXIT] {market} px={exit_price:.4f} reason={reason} "
        f"R={realized_r:.3f} daily_pnl={int(daily_pnl_krw)}KRW"
    )


class Notifier(Protocol):
    def send(self, message: str) -> None:
        ...
