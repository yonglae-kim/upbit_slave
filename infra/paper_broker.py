from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    volume: float
    avg_buy_price: float


class PaperBroker:
    def __init__(self, candles_by_market=None, initial_krw: float = 1_000_000, fee_rate: float = 0.0005):
        self.candles_by_market = candles_by_market or {}
        self.krw_balance = float(initial_krw)
        self.fee_rate = fee_rate
        self.positions: dict[str, Position] = {}

    def _current_price(self, market: str) -> float:
        candles = self.candles_by_market.get(market, [])
        if not candles:
            raise ValueError(f"No candle data for {market}")
        return float(candles[0]["trade_price"])

    def get_markets(self):
        return [{"market": market} for market in self.candles_by_market.keys()]

    def get_accounts(self):
        accounts = [
            {
                "unit_currency": "KRW",
                "currency": "KRW",
                "balance": str(self.krw_balance),
                "locked": "0",
                "avg_buy_price": "0",
            }
        ]

        for market, position in self.positions.items():
            currency = market.replace("KRW-", "", 1)
            accounts.append(
                {
                    "unit_currency": "KRW",
                    "currency": currency,
                    "balance": str(position.volume),
                    "locked": "0",
                    "avg_buy_price": str(position.avg_buy_price),
                }
            )

        return accounts

    def get_ticker(self, markets: str):
        requested = [market.strip() for market in markets.split(",") if market.strip()]
        tickers = []
        for market in requested:
            if market not in self.candles_by_market:
                continue
            candles = self.candles_by_market[market]
            trade_volume = float(candles[0].get("candle_acc_trade_volume", 0)) if candles else 0.0
            tickers.append({"market": market, "trade_volume": trade_volume})
        return tickers

    def get_candles(self, market: str, interval: int, count: int = 200):
        _ = interval
        return self.candles_by_market.get(market, [])[:count]

    def buy_market(self, market: str, price: float):
        order_krw = min(float(price), self.krw_balance)
        if order_krw <= 0:
            return {"status": "rejected", "reason": "insufficient_krw"}

        fill_price = self._current_price(market)
        filled_volume = (order_krw * (1 - self.fee_rate)) / fill_price
        self.krw_balance -= order_krw

        current = self.positions.get(market)
        if current is None:
            self.positions[market] = Position(volume=filled_volume, avg_buy_price=fill_price)
        else:
            total_cost = (current.volume * current.avg_buy_price) + (filled_volume * fill_price)
            total_volume = current.volume + filled_volume
            self.positions[market] = Position(volume=total_volume, avg_buy_price=total_cost / total_volume)

        return {"status": "filled", "market": market, "price": fill_price, "volume": filled_volume}

    def sell_market(self, market: str, volume: float):
        position = self.positions.get(market)
        if position is None:
            return {"status": "rejected", "reason": "no_position"}

        sell_volume = min(float(volume), position.volume)
        if sell_volume <= 0:
            return {"status": "rejected", "reason": "invalid_volume"}

        fill_price = self._current_price(market)
        proceeds = sell_volume * fill_price * (1 - self.fee_rate)
        self.krw_balance += proceeds

        remaining_volume = position.volume - sell_volume
        if remaining_volume <= 0:
            del self.positions[market]
        else:
            self.positions[market] = Position(volume=remaining_volume, avg_buy_price=position.avg_buy_price)

        return {"status": "filled", "market": market, "price": fill_price, "volume": sell_volume}
