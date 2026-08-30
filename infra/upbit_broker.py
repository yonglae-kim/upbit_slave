from __future__ import annotations

from typing import Optional

import apis


class UpbitAuthorizationError(PermissionError):
    """Raised when an Upbit adapter lacks its explicit live capability."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(operation)

    def __str__(self) -> str:
        return "Upbit live authorization is required for {}".format(self.operation)


class UpbitLiveAuthorization:
    """Explicit capability required by concrete Upbit adapters."""

    __slots__ = ()


class UpbitBroker:
    def __init__(
        self, *, authorization: Optional[UpbitLiveAuthorization] = None
    ) -> None:
        self._authorization = authorization
        self._require_authorization("construction")

    def _require_authorization(self, operation: str) -> None:
        if not isinstance(self._authorization, UpbitLiveAuthorization):
            raise UpbitAuthorizationError(operation)

    def get_markets(self):
        self._require_authorization("get_markets")
        return apis.get_markets()

    def get_accounts(self):
        self._require_authorization("get_accounts")
        return apis.get_accounts()

    def get_ticker(self, markets):
        self._require_authorization("get_ticker")
        return apis.get_ticker(markets)

    def get_candles(self, market, interval, count=200):
        self._require_authorization("get_candles")
        return apis.get_candles_minutes(market, count=count, interval=interval)

    def buy_market(self, market, price, identifier=None):
        self._require_authorization("buy_market")
        return apis.bid_price(market, price, identifier=identifier)

    def sell_market(self, market, volume, identifier=None):
        self._require_authorization("sell_market")
        return apis.ask_market(market, volume, identifier=identifier)


    def get_open_orders(self, market=None, states=("wait", "watch")):
        self._require_authorization("get_open_orders")
        return apis.get_open_orders(market=market, states=states)

    def cancel_order(self, order_uuid):
        self._require_authorization("cancel_order")
        return apis.cancel_order(order_uuid)

    def get_order(self, order_uuid):
        self._require_authorization("get_order")
        return apis.get_order(order_uuid=order_uuid)

    def get_order_by_identifier(self, identifier):
        self._require_authorization("get_order_by_identifier")
        return apis.get_order(identifier=identifier)
