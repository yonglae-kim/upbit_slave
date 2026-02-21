from __future__ import annotations

from typing import Any, Protocol


class Broker(Protocol):
    def get_markets(self) -> list[dict[str, Any]]:
        ...

    def get_accounts(self) -> list[dict[str, Any]]:
        ...

    def get_ticker(self, markets: str) -> list[dict[str, Any]]:
        ...

    def get_candles(self, market: str, interval: int, count: int = 200) -> list[dict[str, Any]]:
        ...

    def buy_market(self, market: str, price: float, identifier: str | None = None) -> Any:
        ...

    def sell_market(self, market: str, volume: float, identifier: str | None = None) -> Any:
        ...
