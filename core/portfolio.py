from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class PortfolioState:
    available_krw: float
    my_coins: list[dict[str, Any]]
    held_markets: list[str]


def to_safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def handle_krw_account(item: dict[str, Any]) -> float | None:
    balance = to_safe_float(item.get("balance", 0))
    locked = to_safe_float(item.get("locked", 0))
    tradable_balance = balance + locked

    if tradable_balance <= 0:
        return None

    return balance


def handle_coin_account(item: dict[str, Any], my_coins: list[dict[str, Any]], held_markets: list[str], excluded: Iterable[str]) -> None:
    balance = to_safe_float(item.get("balance", 0))
    locked = to_safe_float(item.get("locked", 0))
    tradable_balance = balance + locked

    if tradable_balance <= 0:
        return
    if item["currency"] in excluded:
        return

    normalized_item = dict(item)
    normalized_item["balance"] = balance
    normalized_item["locked"] = locked
    normalized_item["tradable_balance"] = tradable_balance
    my_coins.append(normalized_item)
    held_markets.append("KRW-" + item["currency"])


def normalize_accounts(accounts: list[dict[str, Any]], excluded: Iterable[str]) -> PortfolioState:
    my_coins: list[dict[str, Any]] = []
    held_markets: list[str] = []
    avail_krw = 0.0

    for item in accounts:
        if item["unit_currency"] != "KRW":
            continue

        if item["currency"] == "KRW":
            account_krw = handle_krw_account(item)
            if account_krw is not None:
                avail_krw = account_krw
            continue

        handle_coin_account(item, my_coins, held_markets, excluded)

    return PortfolioState(available_krw=avail_krw, my_coins=my_coins, held_markets=held_markets)
