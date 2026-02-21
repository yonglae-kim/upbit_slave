from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass
class OrderRecord:
    uuid: str | None
    identifier: str
    market: str
    side: str
    requested_qty: float
    filled_qty: float
    state: OrderStatus
    updated_at: datetime
    retry_count: int = 0

    @classmethod
    def accepted(
        cls,
        *,
        identifier: str,
        market: str,
        side: str,
        requested_qty: float,
        uuid: str | None = None,
    ) -> "OrderRecord":
        return cls(
            uuid=uuid,
            identifier=identifier,
            market=market,
            side=side,
            requested_qty=float(requested_qty),
            filled_qty=0.0,
            state=OrderStatus.ACCEPTED,
            updated_at=datetime.now(timezone.utc),
            retry_count=0,
        )
