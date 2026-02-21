from __future__ import annotations

from datetime import datetime, timezone
import math

from core.candle_buffer import CandleBuffer
from core.config import TradingConfig
from core.interfaces import Broker
from core.order_state import OrderRecord, OrderStatus
from core.portfolio import normalize_accounts
from core.reconciliation import apply_my_asset_event, apply_my_order_event
from core.risk import RiskManager
from core.strategy import check_buy, check_sell, preprocess_candles
from core.universe import UniverseBuilder, filter_by_missing_rate
from infra.upbit_ws_client import UpbitWebSocketClient
from message.notifier import Notifier


class TradingEngine:
    def __init__(
        self,
        broker: Broker,
        notifier: Notifier,
        config: TradingConfig,
        ws_client: UpbitWebSocketClient | None = None,
    ):
        self.broker = broker
        self.notifier = notifier
        self.config = config
        self.ws_client = ws_client
        self._order_sequence = 0
        self.orders_by_identifier: dict[str, OrderRecord] = {}
        self.portfolio_snapshot: dict[str, dict[str, float]] = {}
        self.order_timeout_seconds = 120
        self.max_order_retries = max(0, int(config.max_order_retries))
        self.partial_fill_timeout_scale = max(0.1, float(config.partial_fill_timeout_scale))
        self.partial_fill_reduce_ratio = min(1.0, max(0.1, float(config.partial_fill_reduce_ratio)))
        self.trailing_stop_pct = max(0.0, float(config.trailing_stop_pct))
        self.universe = UniverseBuilder(config)
        self.candle_buffer = CandleBuffer(maxlen_by_interval={1: 300, 5: 300, 15: 300, config.candle_interval: 300})
        self.risk = RiskManager(
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_daily_loss_pct=config.max_daily_loss_pct,
            max_consecutive_losses=config.max_consecutive_losses,
            max_concurrent_positions=config.max_concurrent_positions,
            min_order_krw=config.min_order_krw,
        )
        self._high_watermarks: dict[str, float] = {}

        if self.ws_client:
            self.ws_client.on_message = self._route_ws_message

    def start(self) -> None:
        if not self.ws_client:
            return

        self.initialize_markets()
        self.bootstrap_open_orders()
        self.ws_client.connect()
        self.ws_client.subscribe("ticker", self.config.krw_markets, data_format=self.config.ws_data_format)

    def shutdown(self) -> None:
        if self.ws_client:
            self.ws_client.close()

    def initialize_markets(self) -> None:
        if self.config.krw_markets:
            return

        markets = self.broker.get_markets()
        self.config.krw_markets = self.universe.collect_krw_markets(markets)

    def run_once(self) -> None:
        self.initialize_markets()
        self.reconcile_orders()
        strategy_params = self.config.to_strategy_params()

        accounts = self.broker.get_accounts()
        portfolio = normalize_accounts(accounts, self.config.do_not_trading)
        self.risk.set_baseline_equity(portfolio.available_krw)
        print("보유코인 :", portfolio.held_markets)

        for account in portfolio.my_coins:
            market = "KRW-" + account["currency"]
            data = self._get_strategy_candles(market)
            avg_buy_price = float(account["avg_buy_price"])
            if avg_buy_price <= 0:
                continue
            current_price = float(data["1m"][0]["trade_price"])

            if self._should_exit_position(market, data, avg_buy_price, current_price, strategy_params):
                requested_volume = float(account["balance"])
                preflight = self._preflight_order(
                    market=market,
                    side="ask",
                    requested_value=requested_volume,
                    reference_price=current_price,
                )
                if not preflight["ok"]:
                    self._notify_preflight_failure(preflight)
                    continue
                identifier = self._next_order_identifier(market, "ask")
                response = self.broker.sell_market(market, preflight["order_value"], identifier=identifier)
                self._record_accepted_order(response, identifier, market, "ask", preflight["order_value"])
                print("SELL_ACCEPTED", market, str(account["balance"]) + account["currency"], current_price)
                delta = ((current_price - avg_buy_price) / avg_buy_price) * 100
                self.risk.record_trade_result((current_price - avg_buy_price) * requested_volume)
                self._high_watermarks.pop(market, None)
                self.notifier.send(f"SELL_ACCEPTED {market} {current_price} {delta}%")

        self._try_buy(portfolio.available_krw, portfolio.held_markets, strategy_params)

    def _try_buy(self, available_krw: float, held_markets: list[str], strategy_params) -> None:
        if available_krw <= self.config.min_buyable_krw:
            return
        if len(held_markets) >= self.config.max_holdings:
            return

        tickers = self.broker.get_ticker(", ".join(self.config.krw_markets))
        watch_markets = self.universe.select_watch_markets(tickers)

        candles_by_market = {market: self._get_strategy_candles(market) for market in watch_markets}
        watch_markets = filter_by_missing_rate(
            watch_markets,
            {market: candles["1m"] for market, candles in candles_by_market.items()},
            max_missing_rate=self.config.max_candle_missing_rate,
        )

        for market in watch_markets:
            if market in held_markets:
                continue

            data = candles_by_market[market]
            if not check_buy(data, strategy_params):
                continue

            risk_decision = self.risk.allow_entry(available_krw=available_krw, held_markets=held_markets)
            if not risk_decision.allowed:
                continue

            order_krw = min(
                (available_krw / self.config.buy_divisor) * (1 - self.config.fee_rate),
                risk_decision.order_krw,
            )
            if order_krw < self.config.min_order_krw:
                continue
            if available_krw - order_krw < self.config.min_order_krw:
                continue

            reference_price = float(data["1m"][0]["trade_price"])
            preflight = self._preflight_order(
                market=market,
                side="bid",
                requested_value=order_krw,
                reference_price=reference_price,
            )
            if not preflight["ok"]:
                self._notify_preflight_failure(preflight)
                continue

            identifier = self._next_order_identifier(market, "bid")
            response = self.broker.buy_market(market, preflight["order_value"], identifier=identifier)
            self._record_accepted_order(response, identifier, market, "bid", preflight["order_value"])
            print("BUY_ACCEPTED", market, str(int(preflight["order_value"])) + "원", data["1m"][0]["trade_price"])
            self.notifier.send(f"BUY_ACCEPTED {market} {data['1m'][0]['trade_price']}")
            break

    def _get_strategy_candles(self, market: str) -> dict[str, list[dict]]:
        intervals = {1: "1m", 5: "5m", 15: "15m"}
        result: dict[str, list[dict]] = {}
        for interval, key in intervals.items():
            raw = self.candle_buffer.get_candles(
                market,
                interval,
                lambda selected_market, selected_interval: self.broker.get_candles(
                    selected_market,
                    interval=selected_interval,
                ),
            )
            result[key] = preprocess_candles(raw, source_order="newest")
        return result

    def _next_order_identifier(self, market: str, side: str) -> str:
        self._order_sequence += 1
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        return f"{market}:{side}:{timestamp}:{self._order_sequence}"


    def _route_ws_message(self, message: dict) -> None:
        message_type = message.get("type") or message.get("ty")
        if message_type == "myOrder":
            apply_my_order_event(message, self.orders_by_identifier)
            return

        if message_type == "myAsset":
            apply_my_asset_event(message, self.portfolio_snapshot)

    def reconcile_orders(self) -> None:
        now = datetime.now(timezone.utc)
        for order in list(self.orders_by_identifier.values()):
            if order.state in {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}:
                continue

            timeout_limit = self.order_timeout_seconds
            if order.state == OrderStatus.PARTIALLY_FILLED:
                timeout_limit *= self.partial_fill_timeout_scale

            age_seconds = (now - order.updated_at).total_seconds()
            if age_seconds >= timeout_limit:
                self._on_order_timeout(order)

            if 0 < order.filled_qty < order.requested_qty and order.state == OrderStatus.ACCEPTED:
                order.state = OrderStatus.PARTIALLY_FILLED

    def _on_order_timeout(self, order: OrderRecord) -> None:
        if order.state == OrderStatus.PARTIALLY_FILLED:
            self._cancel_open_order(order)
            remaining_qty = max(0.0, order.requested_qty - order.filled_qty)
            retry_qty = remaining_qty * self.partial_fill_reduce_ratio
            if retry_qty >= 1e-12 and order.retry_count < self.max_order_retries:
                self._retry_order(order, retry_qty)
            return

        if order.state == OrderStatus.ACCEPTED:
            self._cancel_open_order(order)
            if order.retry_count < self.max_order_retries:
                self._retry_order(order, order.requested_qty)

    def _cancel_open_order(self, order: OrderRecord) -> None:
        if not hasattr(self.broker, "cancel_order"):
            return
        if not order.uuid:
            return
        self.broker.cancel_order(order.uuid)
        order.state = OrderStatus.CANCELED
        order.updated_at = datetime.now(timezone.utc)

    def _retry_order(self, origin: OrderRecord, qty: float) -> None:
        reference_price = self._get_market_trade_price(origin.market)
        if reference_price <= 0:
            self._notify_preflight_failure(
                {
                    "ok": False,
                    "code": "PREFLIGHT_PRICE_UNAVAILABLE",
                    "market": origin.market,
                    "side": origin.side,
                    "requested": qty,
                    "rounded_price": 0.0,
                    "order_value": qty,
                    "notional": 0.0,
                }
            )
            return
        preflight = self._preflight_order(
            market=origin.market,
            side=origin.side,
            requested_value=qty,
            reference_price=reference_price,
        )
        if not preflight["ok"]:
            self._notify_preflight_failure(preflight)
            return

        identifier = self._next_order_identifier(origin.market, origin.side)
        if origin.side == "bid":
            response = self.broker.buy_market(origin.market, preflight["order_value"], identifier=identifier)
        else:
            response = self.broker.sell_market(origin.market, preflight["order_value"], identifier=identifier)

        retried = self._record_accepted_order(
            response,
            identifier,
            origin.market,
            origin.side,
            preflight["order_value"],
        )
        retried.retry_count = origin.retry_count + 1

    def _get_market_trade_price(self, market: str) -> float:
        tickers = self.broker.get_ticker(market)
        if not isinstance(tickers, list) or not tickers:
            return 0.0
        return float(tickers[0].get("trade_price", 0.0) or 0.0)

    def _krw_tick_size(self, price: float) -> float:
        if price >= 2_000_000:
            return 1000.0
        if price >= 1_000_000:
            return 500.0
        if price >= 500_000:
            return 100.0
        if price >= 100_000:
            return 50.0
        if price >= 10_000:
            return 10.0
        if price >= 1_000:
            return 1.0
        if price >= 100:
            return 0.1
        if price >= 10:
            return 0.01
        if price >= 1:
            return 0.001
        if price >= 0.1:
            return 0.0001
        if price >= 0.01:
            return 0.00001
        if price >= 0.001:
            return 0.000001
        return 0.0000001

    def _round_to_tick(self, value: float, tick: float) -> float:
        return math.floor(value / tick) * tick

    def _preflight_order(self, market: str, side: str, requested_value: float, reference_price: float) -> dict:
        if requested_value <= 0 or reference_price <= 0:
            return {
                "ok": False,
                "code": "PREFLIGHT_INVALID_INPUT",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": 0.0,
                "order_value": 0.0,
                "notional": 0.0,
            }

        tick = self._krw_tick_size(reference_price)
        rounded_price = self._round_to_tick(reference_price, tick)
        if rounded_price <= 0:
            return {
                "ok": False,
                "code": "PREFLIGHT_PRICE_ROUNDING_FAILED",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": rounded_price,
                "order_value": requested_value,
                "notional": 0.0,
            }

        if side == "bid":
            order_value = float(int(requested_value))
            notional = order_value
            rounded_qty = order_value / rounded_price
        else:
            rounded_qty = round(requested_value, 8)
            order_value = rounded_qty
            notional = rounded_qty * rounded_price

        if notional < self.config.min_order_krw:
            return {
                "ok": False,
                "code": "PREFLIGHT_MIN_NOTIONAL",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": rounded_price,
                "order_value": order_value,
                "notional": notional,
            }

        recomputed_notional = rounded_qty * rounded_price
        if order_value <= 0 or rounded_qty <= 0 or recomputed_notional < self.config.min_order_krw:
            return {
                "ok": False,
                "code": "PREFLIGHT_RECOMPUTE_INVALID",
                "market": market,
                "side": side,
                "requested": requested_value,
                "rounded_price": rounded_price,
                "order_value": order_value,
                "notional": recomputed_notional,
            }

        return {
            "ok": True,
            "code": "PREFLIGHT_OK",
            "market": market,
            "side": side,
            "requested": requested_value,
            "rounded_price": rounded_price,
            "order_value": order_value,
            "notional": recomputed_notional,
        }

    def _notify_preflight_failure(self, result: dict) -> None:
        code = result.get("code", "PREFLIGHT_UNKNOWN")
        market = result.get("market")
        side = result.get("side")
        requested = result.get("requested")
        rounded_price = result.get("rounded_price")
        notional = result.get("notional")
        print("ORDER_PREFLIGHT_BLOCKED", code, market, side, requested, rounded_price, notional)
        self.notifier.send(f"ORDER_PREFLIGHT_BLOCKED {code} {market} {side} req={requested} notional={notional}")

    def _should_exit_position(self, market: str, data: dict[str, list[dict]], avg_buy_price: float, current_price: float, strategy_params) -> bool:
        trailing_stop = self._trailing_stop_triggered(market, current_price)
        take_profit_or_signal = check_sell(data, avg_buy_price, strategy_params)
        hard_stop = current_price < avg_buy_price * strategy_params.stop_loss_threshold
        return trailing_stop or take_profit_or_signal or hard_stop

    def _trailing_stop_triggered(self, market: str, current_price: float) -> bool:
        peak = self._high_watermarks.get(market, current_price)
        peak = max(peak, current_price)
        self._high_watermarks[market] = peak
        if self.trailing_stop_pct <= 0:
            return False
        return current_price <= peak * (1 - self.trailing_stop_pct)

    def bootstrap_open_orders(self) -> None:
        if not hasattr(self.broker, "get_open_orders"):
            return

        open_orders = self.broker.get_open_orders()
        if not isinstance(open_orders, list):
            return

        for event in open_orders:
            if not isinstance(event, dict):
                continue
            apply_my_order_event(event, self.orders_by_identifier)

    def _record_accepted_order(
        self,
        response,
        identifier: str,
        market: str,
        side: str,
        requested_qty: float,
    ) -> OrderRecord:
        response_data = response if isinstance(response, dict) else {}
        order_uuid = response_data.get("uuid")
        record = OrderRecord.accepted(
            uuid=order_uuid,
            identifier=identifier,
            market=market,
            side=side,
            requested_qty=requested_qty,
        )
        self.orders_by_identifier[identifier] = record
        return record
