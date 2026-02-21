from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.order_state import OrderRecord, OrderStatus


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def apply_my_order_event(event: dict[str, Any], order_store: dict[str, OrderRecord]) -> OrderRecord:
    """Apply a myOrder event and return the updated order record.

    `myOrder` is treated as the single source of truth for order state transitions.
    """

    identifier = str(event.get("identifier") or event.get("id") or "")
    uuid = event.get("uuid")
    if not identifier and uuid:
        identifier = str(uuid)

    if not identifier:
        raise ValueError("myOrder event is missing identifier/uuid")

    existing = order_store.get(identifier)
    market = str(event.get("market") or (existing.market if existing else ""))
    side = str(event.get("side") or (existing.side if existing else ""))

    requested_qty = _to_float(
        event.get("volume")
        or event.get("requested_volume")
        or (existing.requested_qty if existing else 0.0)
    )

    executed_volume = _to_float(event.get("executed_volume"), default=-1.0)
    if executed_volume < 0:
        remaining = _to_float(event.get("remaining_volume"), default=-1.0)
        if remaining >= 0 and requested_qty > 0:
            executed_volume = max(0.0, requested_qty - remaining)
        else:
            executed_volume = existing.filled_qty if existing else 0.0

    state_value = str(event.get("state") or "").lower()
    if state_value in {"wait", "watch"}:
        next_state = OrderStatus.ACCEPTED
    elif state_value in {"done", "trade"}:
        next_state = OrderStatus.FILLED
    elif state_value in {"cancel", "cancelled"}:
        next_state = OrderStatus.CANCELED
    elif state_value in {"reject", "rejected"}:
        next_state = OrderStatus.REJECTED
    elif requested_qty > 0 and 0 < executed_volume < requested_qty:
        next_state = OrderStatus.PARTIALLY_FILLED
    else:
        next_state = existing.state if existing else OrderStatus.ACCEPTED

    if next_state == OrderStatus.ACCEPTED and requested_qty > 0 and 0 < executed_volume < requested_qty:
        next_state = OrderStatus.PARTIALLY_FILLED

    record = OrderRecord(
        uuid=str(uuid) if uuid else (existing.uuid if existing else None),
        identifier=identifier,
        market=market,
        side=side,
        requested_qty=requested_qty,
        filled_qty=executed_volume,
        state=next_state,
        updated_at=datetime.now(timezone.utc),
    )
    order_store[identifier] = record
    return record


def apply_my_asset_event(event: dict[str, Any], portfolio_store: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Apply a myAsset snapshot event as a reconciliation helper."""

    assets = event.get("assets")
    if assets is None:
        assets = event.get("accounts")
    if assets is None and event.get("currency"):
        assets = [event]

    if not isinstance(assets, list):
        return portfolio_store

    snapshot: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        currency = str(asset.get("currency") or "")
        if not currency:
            continue
        snapshot[currency] = {
            "balance": _to_float(asset.get("balance")),
            "locked": _to_float(asset.get("locked")),
            "avg_buy_price": _to_float(asset.get("avg_buy_price")),
        }

    if snapshot:
        portfolio_store.clear()
        portfolio_store.update(snapshot)

    return portfolio_store
