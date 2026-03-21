import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import core.engine as engine_module
from core.config import TradingConfig
from core.decision_models import DecisionIntent
from core.engine import TradingEngine
from core.order_state import OrderStatus


class BuyOnlyBroker:
    def __init__(self):
        self.buy_calls = []

    def get_markets(self):
        return [{"market": "KRW-BTC"}]

    def get_accounts(self):
        return [
            {
                "unit_currency": "KRW",
                "currency": "KRW",
                "balance": "100000",
                "locked": "0",
                "avg_buy_price": "0",
            }
        ]

    def get_ticker(self, markets):
        _ = markets
        return [{"market": "KRW-BTC", "trade_price": 100000.0, "trade_volume": 1000}]

    def get_candles(self, market, interval, count=200) -> list[dict[str, float | str]]:
        _ = market, interval, count
        return [{"trade_price": 100.0} for _ in range(3)]

    def buy_market(self, market, price, identifier=None):
        self.buy_calls.append((market, price, identifier))
        return {"uuid": "order-uuid-1"}

    def sell_market(self, market, volume, identifier=None):
        _ = market, volume, identifier
        return {}

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return []

    def cancel_order(self, order_uuid):
        _ = order_uuid
        return {"state": "cancel"}

    def get_order(self, order_uuid):
        _ = order_uuid
        return {"state": "wait"}


def _entry_candles() -> list[dict[str, float | str]]:
    candles_oldest: list[dict[str, float | str]] = [
        {
            "opening_price": 100 - i * 0.2,
            "high_price": 101 - i * 0.2,
            "low_price": 99 - i * 0.25,
            "trade_price": 100 - i * 0.25,
        }
        for i in range(80)
    ]
    return list(reversed(candles_oldest))


class RealSeamEntryBroker(BuyOnlyBroker):
    def get_ticker(self, markets):
        _ = markets
        return [
            {
                "market": "KRW-BTC",
                "trade_price": 80.25,
                "trade_volume": 1000.0,
                "bid_price": 80.2,
                "ask_price": 80.3,
            }
        ]

    def get_candles(self, market, interval, count=200) -> list[dict[str, float | str]]:
        _ = market, count
        if interval == 1:
            return list(_entry_candles())
        if interval == 5:
            return list(_entry_candles())
        if interval == 15:
            candles_oldest: list[dict[str, float | str]] = []
            price = 100.0
            for _ in range(240):
                open_price = price
                close_price = price + 0.4
                candles_oldest.append(
                    {
                        "opening_price": open_price,
                        "high_price": close_price + 0.1,
                        "low_price": open_price - 0.1,
                        "trade_price": close_price,
                    }
                )
                price += 0.35
            return list(reversed(candles_oldest))
        return super().get_candles(market, interval, count)


class DummyNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


class TimeoutFlowBroker(BuyOnlyBroker):
    def __init__(self):
        super().__init__()
        self.cancel_calls = []
        self.get_order_calls = []

    def get_open_orders(self, market=None, states=("wait", "watch")):
        _ = market, states
        return [
            {
                "identifier": "open-1",
                "uuid": "open-uuid-1",
                "market": "KRW-BTC",
                "side": "bid",
                "state": "wait",
                "volume": "20000",
                "executed_volume": "0",
            }
        ]

    def get_order(self, order_uuid):
        self.get_order_calls.append(order_uuid)
        return {"uuid": order_uuid, "state": "wait"}

    def cancel_order(self, order_uuid):
        self.cancel_calls.append(order_uuid)
        return {"uuid": order_uuid, "state": "cancel"}


class RoundTripBroker(BuyOnlyBroker):
    def __init__(self):
        super().__init__()
        self.sell_calls = []
        self.asset_balance = 0.0
        self.avg_buy_price = 0.0
        self.latest_trade_price = 100.0
        self.latest_1m_time = "2024-01-01T00:01:00"
        self.latest_5m_time = "2024-01-01T00:00:00"
        self.latest_15m_time = "2024-01-01T00:00:00"

    def get_accounts(self):
        accounts = [
            {
                "unit_currency": "KRW",
                "currency": "KRW",
                "balance": "100000",
                "locked": "0",
                "avg_buy_price": "0",
            }
        ]
        if self.asset_balance > 0:
            accounts.append(
                {
                    "unit_currency": "KRW",
                    "currency": "BTC",
                    "balance": str(self.asset_balance),
                    "locked": "0",
                    "avg_buy_price": str(self.avg_buy_price),
                }
            )
        return accounts

    def get_ticker(self, markets):
        _ = markets
        return [
            {
                "market": "KRW-BTC",
                "trade_price": self.latest_trade_price,
                "trade_volume": 1000.0,
                "bid_price": self.latest_trade_price - 0.2,
                "ask_price": self.latest_trade_price + 0.2,
            }
        ]

    def get_candles(self, market, interval, count=200):
        _ = market, count
        candle_time = self.latest_1m_time
        if interval == 5:
            candle_time = self.latest_5m_time
        elif interval == 15:
            candle_time = self.latest_15m_time
        candle = {
            "candle_date_time_utc": candle_time,
            "opening_price": self.latest_trade_price - 1.0,
            "high_price": self.latest_trade_price + 1.5,
            "low_price": self.latest_trade_price - 2.0,
            "trade_price": self.latest_trade_price,
        }
        return [dict(candle) for _ in range(5)]

    def buy_market(self, market, price, identifier=None):
        response = super().buy_market(market, price, identifier=identifier)
        self.asset_balance = 100.0
        self.avg_buy_price = self.latest_trade_price
        return response

    def sell_market(self, market, volume, identifier=None):
        self.sell_calls.append((market, volume, identifier))
        self.asset_balance = 0.0
        return {"uuid": f"sell-{len(self.sell_calls)}"}


class TradingEngineOrderAcceptanceTest(unittest.TestCase):
    def test_recent_trade_log_loader_supports_python38_string_lines(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()

        class _CompatLine:
            def __init__(self, value: str):
                self.value = value

            def startswith(self, prefix: str) -> bool:
                return self.value.startswith(prefix)

            def __str__(self) -> str:
                return self.value

        class _CompatText:
            def splitlines(self):
                return [
                    _CompatLine(
                        'PAYLOAD_JSON: {"market": "KRW-BTC", "entry_reason": "ok"}'
                    )
                ]

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "recent_trades.txt"
            log_path.write_text("placeholder\n", encoding="utf-8")
            config = TradingConfig(
                do_not_trading=[],
                krw_markets=["KRW-BTC"],
                strategy_name="baseline",
                recent_trade_log_path=str(log_path),
            )

            with patch.object(Path, "read_text", return_value=_CompatText()):
                engine = TradingEngine(broker, notifier, config)

            self.assertEqual(len(engine._recent_trade_records), 1)
            self.assertEqual(engine._recent_trade_records[0]["market"], "KRW-BTC")

    def test_full_exit_writes_recent_trade_log_with_reasons_and_candles(self):
        broker = RoundTripBroker()
        notifier = DummyNotifier()

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "recent_trades.txt"
            config = TradingConfig(
                do_not_trading=[],
                krw_markets=["KRW-BTC"],
                strategy_name="baseline",
                recent_trade_log_path=str(log_path),
            )
            engine = TradingEngine(broker, notifier, config)

            entry_intent = DecisionIntent(
                action="enter",
                reason="zone_reclaim",
                diagnostics={
                    "strategy_name": "baseline",
                    "entry_score": 3.2,
                    "entry_regime": "weak_trend",
                    "quality_score": 0.81,
                    "quality_bucket": "high",
                    "quality_multiplier": 1.15,
                    "regime_diagnostics": {"regime": "weak_trend", "pass": True},
                    "sizing": {
                        "risk_sized_order_krw": 18000.0,
                        "cash_cap_order_krw": 15000.0,
                        "base_order_krw": 15000.0,
                        "final_order_krw": 12345.0,
                        "entry_price": 101.0,
                        "stop_price": 95.0,
                        "risk_per_unit": 6.0,
                    },
                },
                next_position_state={
                    "peak_price": 100.0,
                    "entry_atr": 1.5,
                    "entry_swing_low": 95.0,
                    "entry_price": 101.0,
                    "initial_stop_price": 95.0,
                    "risk_per_unit": 6.0,
                    "bars_held": 0,
                    "entry_regime": "weak_trend",
                    "partial_take_profit_done": False,
                    "strategy_partial_done": False,
                    "breakeven_armed": False,
                    "highest_r": 0.0,
                    "lowest_r": 0.0,
                    "drawdown_from_peak_r": 0.0,
                },
            )
            exit_intent = DecisionIntent(
                action="exit_full",
                reason="stop_loss",
                diagnostics={"strategy_name": "baseline", "qty_ratio": 1.0},
                next_position_state={},
            )

            with (
                patch(
                    "core.engine.evaluate_market",
                    create=True,
                    side_effect=[entry_intent, exit_intent],
                ),
                patch.object(engine, "_should_run_strategy", return_value=True),
                patch.object(
                    engine,
                    "_refresh_watch_markets_if_needed",
                    return_value=["KRW-BTC"],
                ),
            ):
                engine.run_once()
                broker.latest_trade_price = 96.0
                broker.latest_1m_time = "2024-01-01T00:04:00"
                broker.latest_5m_time = "2024-01-01T00:05:00"
                broker.latest_15m_time = "2024-01-01T00:15:00"
                engine.run_once()

            self.assertTrue(log_path.exists())
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("Entry Reason: zone_reclaim", text)
            self.assertIn("Final Exit Reason: stop_loss", text)
            self.assertIn("Entry Candles:", text)
            self.assertIn("Exit Candles:", text)
            self.assertIn("PAYLOAD_JSON:", text)

    def test_recent_trade_log_keeps_only_latest_ten_completed_trades(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "recent_trades.txt"
            config = TradingConfig(
                do_not_trading=[],
                krw_markets=["KRW-BTC"],
                strategy_name="baseline",
                recent_trade_log_path=str(log_path),
            )
            engine = TradingEngine(broker, notifier, config)

            for idx in range(11):
                engine._store_completed_trade_record(
                    {
                        "market": f"KRW-COIN-{idx:02d}",
                        "entry_reason": f"entry-{idx:02d}",
                        "final_exit_reason": f"exit-{idx:02d}",
                        "closed_at": f"2024-01-01T00:{idx:02d}:00+00:00",
                    }
                )

            text = log_path.read_text(encoding="utf-8")
            self.assertEqual(text.count("PAYLOAD_JSON:"), 10)
            self.assertNotIn("KRW-COIN-00", text)
            self.assertIn("KRW-COIN-10", text)

    def test_recent_trade_log_preserves_latest_ten_after_reload(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "recent_trades.txt"
            config = TradingConfig(
                do_not_trading=[],
                krw_markets=["KRW-BTC"],
                strategy_name="baseline",
                recent_trade_log_path=str(log_path),
            )
            first_engine = TradingEngine(broker, notifier, config)

            for idx in range(10):
                first_engine._store_completed_trade_record(
                    {
                        "market": f"KRW-COIN-{idx:02d}",
                        "entry_reason": f"entry-{idx:02d}",
                        "final_exit_reason": f"exit-{idx:02d}",
                        "closed_at": f"2024-01-01T00:{idx:02d}:00+00:00",
                    }
                )

            reloaded_engine = TradingEngine(broker, notifier, config)
            reloaded_engine._store_completed_trade_record(
                {
                    "market": "KRW-COIN-10",
                    "entry_reason": "entry-10",
                    "final_exit_reason": "exit-10",
                    "closed_at": "2024-01-01T00:10:00+00:00",
                }
            )

            text = log_path.read_text(encoding="utf-8")
            self.assertEqual(text.count("PAYLOAD_JSON:"), 10)
            self.assertNotIn("KRW-COIN-00", text)
            self.assertIn("KRW-COIN-10", text)

    def test_paper_candidate_runtime_accepts_matching_promote_artifact(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        decision_path = (
            Path(__file__).resolve().parent / "artifacts" / "candidate_v1_decision.json"
        )

        with patch.dict(
            os.environ,
            {
                "TRADING_MODE": "paper",
                "TRADING_STRATEGY_NAME": "candidate_v1",
                "TRADING_STRATEGY_DECISION_PATH": str(decision_path),
            },
            clear=False,
        ):
            from core.config_loader import load_trading_config

            config = load_trading_config()

        engine = TradingEngine(broker, notifier, config)

        intent = DecisionIntent(
            action="enter",
            reason="ok",
            diagnostics={
                "strategy_name": "candidate_v1",
                "entry_score": 3.1,
                "entry_regime": "weak_trend",
                "regime_diagnostics": {"regime": "weak_trend", "pass": True},
                "quality_score": 0.82,
                "quality_bucket": "high",
                "quality_multiplier": 1.0,
                "effective_strategy_params": {
                    "strategy_name": "candidate_v1",
                    "take_profit_r": 2.0,
                    "entry_score_threshold": 2.2,
                },
                "sizing": {
                    "risk_sized_order_krw": 18000.0,
                    "cash_cap_order_krw": 15000.0,
                    "base_order_krw": 15000.0,
                    "final_order_krw": 12345.0,
                    "entry_price": 101.0,
                    "stop_price": 95.0,
                    "risk_per_unit": 6.0,
                },
            },
            next_position_state={
                "peak_price": 100.0,
                "entry_atr": 1.5,
                "entry_swing_low": 95.0,
                "entry_price": 101.0,
                "initial_stop_price": 95.0,
                "risk_per_unit": 6.0,
                "bars_held": 0,
                "entry_regime": "weak_trend",
                "partial_take_profit_done": False,
                "strategy_partial_done": False,
                "breakeven_armed": False,
                "highest_r": 0.0,
                "lowest_r": 0.0,
                "drawdown_from_peak_r": 0.0,
            },
        )

        with (
            patch(
                "core.engine.evaluate_market",
                create=True,
                return_value=intent,
            ) as evaluate_market_mock,
            patch.object(
                engine,
                "_refresh_watch_markets_if_needed",
                return_value=["KRW-BTC"],
            ),
        ):
            engine.run_once()

        self.assertEqual(config.strategy_decision_path, str(decision_path))
        self.assertEqual(
            evaluate_market_mock.call_args.args[0].strategy_name, "candidate_v1"
        )
        self.assertEqual(len(broker.buy_calls), 1)

    def test_paper_candidate_runtime_rejects_reject_decision_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            decision_path = Path(td) / "rejected_candidate_v1_decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "candidate_strategy": "candidate_v1",
                        "decision": "reject",
                        "oos_gate": {"pass": False},
                        "parity_gate": {
                            "pass": True,
                            "strategy_name": "candidate_v1",
                            "expected_strategy_name": "candidate_v1",
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "TRADING_MODE": "paper",
                    "TRADING_STRATEGY_NAME": "candidate_v1",
                    "TRADING_STRATEGY_DECISION_PATH": str(decision_path),
                },
                clear=False,
            ):
                from core.config_loader import (
                    ConfigValidationError,
                    load_trading_config,
                )

                with self.assertRaises(ConfigValidationError):
                    load_trading_config()

    def test_paper_candidate_runtime_rejects_mismatched_decision_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            decision_path = Path(td) / "baseline_decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "candidate_strategy": "baseline",
                        "decision": "promote",
                        "oos_gate": {"pass": True},
                        "parity_gate": {
                            "pass": True,
                            "strategy_name": "baseline",
                            "expected_strategy_name": "baseline",
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "TRADING_MODE": "paper",
                    "TRADING_STRATEGY_NAME": "candidate_v1",
                    "TRADING_STRATEGY_DECISION_PATH": str(decision_path),
                },
                clear=False,
            ):
                from core.config_loader import (
                    ConfigValidationError,
                    load_trading_config,
                )

                with self.assertRaises(ConfigValidationError):
                    load_trading_config()

    def test_market_buy_is_recorded_as_accepted(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[], krw_markets=["KRW-BTC"], strategy_name="baseline"
        )
        engine = TradingEngine(broker, notifier, config)

        intent = DecisionIntent(
            action="enter",
            reason="ok",
            diagnostics={
                "strategy_name": "baseline",
                "entry_score": 3.1,
                "entry_regime": "weak_trend",
                "regime_diagnostics": {"regime": "weak_trend", "pass": True},
                "quality_score": 0.82,
                "quality_bucket": "high",
                "quality_multiplier": 1.15,
                "effective_strategy_params": {
                    "strategy_name": "baseline",
                    "take_profit_r": 2.6,
                    "entry_score_threshold": 2.9,
                },
                "sizing": {
                    "risk_sized_order_krw": 18000.0,
                    "cash_cap_order_krw": 15000.0,
                    "base_order_krw": 15000.0,
                    "final_order_krw": 12345.0,
                    "entry_price": 101.0,
                    "stop_price": 95.0,
                    "risk_per_unit": 6.0,
                },
            },
            next_position_state={
                "peak_price": 100.0,
                "entry_atr": 1.5,
                "entry_swing_low": 95.0,
                "entry_price": 101.0,
                "initial_stop_price": 95.0,
                "risk_per_unit": 6.0,
                "bars_held": 0,
                "entry_regime": "weak_trend",
                "partial_take_profit_done": False,
                "strategy_partial_done": False,
                "breakeven_armed": False,
                "highest_r": 0.0,
                "lowest_r": 0.0,
                "drawdown_from_peak_r": 0.0,
            },
        )

        with (
            patch(
                "core.engine.evaluate_market",
                create=True,
                return_value=intent,
            ) as evaluate_market_mock,
            patch.object(
                engine,
                "_refresh_watch_markets_if_needed",
                return_value=["KRW-BTC"],
            ),
        ):
            engine.run_once()

        evaluate_market_mock.assert_called_once()
        context = evaluate_market_mock.call_args.args[0]
        self.assertEqual(context.strategy_name, "baseline")
        self.assertEqual(context.market.symbol, "KRW-BTC")
        self.assertEqual(context.position.quantity, 0.0)
        self.assertEqual(context.portfolio.available_krw, 100000.0)

        self.assertEqual(len(broker.buy_calls), 1)
        _, order_value, identifier = broker.buy_calls[0]
        self.assertIsNotNone(identifier)
        self.assertEqual(order_value, 12345.0)
        self.assertIn(identifier, engine.orders_by_identifier)

        order = engine.orders_by_identifier[identifier]
        self.assertEqual(order.state, OrderStatus.ACCEPTED)
        self.assertEqual(order.filled_qty, 0.0)
        self.assertEqual(order.uuid, "order-uuid-1")
        self.assertEqual(engine._position_exit_states["KRW-BTC"].entry_price, 101.0)
        self.assertEqual(engine._position_exit_states["KRW-BTC"].risk_per_unit, 6.0)
        self.assertEqual(
            engine._position_exit_states["KRW-BTC"].entry_regime, "weak_trend"
        )
        self.assertEqual(
            engine._entry_tracking_by_market["KRW-BTC"]["final_order_krw"], 12345.0
        )
        self.assertEqual(
            engine._entry_tracking_by_market["KRW-BTC"]["quality_bucket"], "high"
        )
        self.assertEqual(
            engine._entry_strategy_params_by_market["KRW-BTC"].strategy_name,
            "baseline",
        )
        self.assertEqual(
            engine._entry_strategy_params_by_market["KRW-BTC"].take_profit_r,
            2.6,
        )

    def test_run_once_prints_runtime_status_with_balance_and_stage(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[], krw_markets=["KRW-BTC"], strategy_name="baseline"
        )
        engine = TradingEngine(broker, notifier, config)

        with (
            patch(
                "core.engine.evaluate_market",
                create=True,
                return_value=DecisionIntent(action="hold", reason="hold"),
            ),
            patch("builtins.print") as mock_print,
        ):
            engine.run_once()

        printed = "\n".join(
            " ".join(map(str, call.args)) for call in mock_print.call_args_list
        )
        self.assertIn("[STATUS] stage=evaluating_positions", printed)
        self.assertIn("available_krw=100000", printed)
        self.assertIn("holdings=0/1", printed)
        self.assertIn("[STATUS] stage=cycle_complete", printed)

    def test_preflight_blocks_buy_when_notional_below_exchange_minimum(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[], krw_markets=["KRW-BTC"], min_order_krw=5000
        )
        engine = TradingEngine(broker, notifier, config)

        result = engine._preflight_order(
            market="KRW-BTC",
            side="bid",
            requested_value=4999.9,
            reference_price=100000.0,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PREFLIGHT_MIN_NOTIONAL")

    def test_preflight_blocks_sell_when_recomputed_notional_is_invalid(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[], krw_markets=["KRW-BTC"], min_order_krw=5000
        )
        engine = TradingEngine(broker, notifier, config)

        result = engine._preflight_order(
            market="KRW-BTC",
            side="ask",
            requested_value=0.000000001,
            reference_price=100000.0,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PREFLIGHT_MIN_NOTIONAL")

    def test_buy_entry_boundary_by_final_order_amount(self):
        for available_krw, expected_buy in (
            (8_000, False),
            (15_000, True),
            (25_000, True),
        ):
            with self.subTest(available_krw=available_krw):
                broker = BuyOnlyBroker()
                broker.get_accounts = lambda value=available_krw: [
                    {
                        "unit_currency": "KRW",
                        "currency": "KRW",
                        "balance": str(value),
                        "locked": "0",
                        "avg_buy_price": "0",
                    }
                ]
                notifier = DummyNotifier()
                config = TradingConfig(
                    do_not_trading=[],
                    krw_markets=["KRW-BTC"],
                    strategy_name="baseline",
                    min_order_krw=5_000,
                    min_buyable_krw=0,
                    max_holdings=2,
                )
                engine = TradingEngine(broker, notifier, config)

                with (
                    patch(
                        "core.engine.evaluate_market",
                        create=True,
                        return_value=DecisionIntent(
                            action="enter",
                            reason="ok",
                            diagnostics={
                                "strategy_name": "baseline",
                                "entry_score": 2.8,
                                "quality_score": 0.4,
                                "quality_bucket": "mid",
                                "quality_multiplier": 1.0,
                                "entry_regime": "weak_trend",
                                "regime_diagnostics": {
                                    "regime": "weak_trend",
                                    "pass": True,
                                },
                                "sizing": {
                                    "risk_sized_order_krw": float(available_krw),
                                    "cash_cap_order_krw": 6000.0,
                                    "base_order_krw": 6000.0,
                                    "final_order_krw": 4000.0
                                    if not expected_buy
                                    else 6000.0,
                                    "entry_price": 100.0,
                                    "stop_price": 97.5,
                                    "risk_per_unit": 2.5,
                                },
                            },
                            next_position_state={
                                "peak_price": 100.0,
                                "entry_atr": 1.0,
                                "entry_swing_low": 95.0,
                                "entry_price": 100.0,
                                "initial_stop_price": 97.5,
                                "risk_per_unit": 2.5,
                                "bars_held": 0,
                                "entry_regime": "weak_trend",
                                "partial_take_profit_done": False,
                                "strategy_partial_done": False,
                                "breakeven_armed": False,
                                "highest_r": 0.0,
                                "lowest_r": 0.0,
                                "drawdown_from_peak_r": 0.0,
                            },
                        ),
                    ) as evaluate_market_mock,
                    patch.object(
                        engine,
                        "_refresh_watch_markets_if_needed",
                        return_value=["KRW-BTC"],
                    ),
                ):
                    engine.run_once()

                self.assertTrue(evaluate_market_mock.called)

                self.assertEqual(len(broker.buy_calls) == 1, expected_buy)

    def test_risk_gate_blocks_buy_on_loss_streak(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            strategy_name="baseline",
            max_consecutive_losses=2,
        )
        engine = TradingEngine(broker, notifier, config)
        engine.risk.record_trade_result(-1000)
        engine.risk.record_trade_result(-1000)

        with (
            patch(
                "core.engine.evaluate_market",
                create=True,
                return_value=DecisionIntent(
                    action="enter",
                    reason="ok",
                    diagnostics={"strategy_name": "baseline", "entry_score": 2.8},
                    next_position_state={
                        "peak_price": 100.0,
                        "entry_atr": 1.0,
                        "entry_swing_low": 95.0,
                        "entry_price": 100.0,
                        "initial_stop_price": 97.5,
                        "risk_per_unit": 2.5,
                        "bars_held": 0,
                        "entry_regime": "weak_trend",
                        "partial_take_profit_done": False,
                        "strategy_partial_done": False,
                        "breakeven_armed": False,
                        "highest_r": 0.0,
                        "lowest_r": 0.0,
                        "drawdown_from_peak_r": 0.0,
                    },
                ),
            ) as evaluate_market_mock,
            patch.object(
                engine,
                "_refresh_watch_markets_if_needed",
                return_value=["KRW-BTC"],
            ),
        ):
            engine.run_once()

        self.assertTrue(evaluate_market_mock.called)
        self.assertEqual(len(broker.buy_calls), 0)
        self.assertEqual(engine.orders_by_identifier, {})

    def test_try_buy_uses_shared_seam_for_regime_and_sizing(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[],
            krw_markets=["KRW-BTC"],
            strategy_name="baseline",
            min_order_krw=5_000,
            min_buyable_krw=0,
            max_holdings=2,
        )
        engine = TradingEngine(broker, notifier, config)

        with (
            patch.object(
                engine, "_refresh_watch_markets_if_needed", return_value=["KRW-BTC"]
            ),
            patch.object(
                engine,
                "_resolve_strategy_params_for_regime",
                side_effect=AssertionError("engine should not branch strategy params"),
            ),
            patch(
                "core.engine.evaluate_market",
                create=True,
                return_value=DecisionIntent(
                    action="enter",
                    reason="ok",
                    diagnostics={
                        "strategy_name": "baseline",
                        "entry_score": 2.8,
                        "entry_regime": "strong_trend",
                        "regime_diagnostics": {"regime": "strong_trend", "pass": True},
                        "quality_score": 0.75,
                        "quality_bucket": "high",
                        "quality_multiplier": 1.15,
                        "sizing": {
                            "risk_sized_order_krw": 22000.0,
                            "cash_cap_order_krw": 18000.0,
                            "base_order_krw": 18000.0,
                            "final_order_krw": 7777.0,
                            "entry_price": 100.0,
                            "stop_price": 97.5,
                            "risk_per_unit": 2.5,
                        },
                    },
                    next_position_state={
                        "peak_price": 100.0,
                        "entry_atr": 1.0,
                        "entry_swing_low": 95.0,
                        "entry_price": 100.0,
                        "initial_stop_price": 97.5,
                        "risk_per_unit": 2.5,
                        "bars_held": 0,
                        "entry_regime": "strong_trend",
                        "partial_take_profit_done": False,
                        "strategy_partial_done": False,
                        "breakeven_armed": False,
                        "highest_r": 0.0,
                        "lowest_r": 0.0,
                        "drawdown_from_peak_r": 0.0,
                    },
                ),
            ),
        ):
            engine.run_once()

        self.assertFalse(hasattr(engine_module, "classify_market_regime"))
        self.assertEqual(len(broker.buy_calls), 1)
        self.assertEqual(broker.buy_calls[0][1], 7777.0)
        self.assertEqual(
            engine._entry_tracking_by_market["KRW-BTC"]["regime"], "strong_trend"
        )
        self.assertEqual(
            engine._entry_tracking_by_market["KRW-BTC"]["final_order_krw"], 7777.0
        )

    def test_real_entry_seam_supports_legacy_default_strategy_surface(self):
        broker = RealSeamEntryBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[],
            strategy_name="rsi_bb_reversal_long",
            krw_markets=["KRW-BTC"],
            min_order_krw=5_000,
            min_buyable_krw=0,
            entry_score_threshold=0.0,
        )
        engine = TradingEngine(broker, notifier, config)

        with (
            patch.object(
                engine,
                "_refresh_watch_markets_if_needed",
                return_value=["KRW-BTC"],
            ),
            patch.object(
                config,
                "all_regime_strategy_overrides",
                return_value={
                    "strong_trend": {
                        "entry_score_threshold": 0.0,
                        "take_profit_r": 3.3,
                    }
                },
            ),
        ):
            engine.run_once()

        self.assertEqual(config.strategy_name, "rsi_bb_reversal_long")
        self.assertEqual(len(broker.buy_calls), 1)
        self.assertEqual(
            engine._entry_strategy_params_by_market["KRW-BTC"].strategy_name,
            "baseline",
        )
        self.assertEqual(
            engine._entry_strategy_params_by_market["KRW-BTC"].take_profit_r,
            3.3,
        )
        self.assertIn("KRW-BTC", engine._position_exit_states)
        final_order_krw = engine._entry_tracking_by_market["KRW-BTC"]["final_order_krw"]
        self.assertIsInstance(final_order_krw, float)
        assert isinstance(final_order_krw, float)
        self.assertEqual(final_order_krw, 69965.0)
        self.assertEqual(
            engine._position_exit_states["KRW-BTC"].entry_regime,
            engine._entry_tracking_by_market["KRW-BTC"]["regime"],
        )

    def test_preflight_rounds_price_with_same_krw_tick_boundaries(self):
        broker = BuyOnlyBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[], krw_markets=["KRW-BTC"], min_order_krw=5000
        )
        engine = TradingEngine(broker, notifier, config)

        boundary_cases = [
            (1000.4, 1000.0),
            (10000.9, 10000.0),
            (100049.9, 100000.0),
        ]

        for reference_price, expected in boundary_cases:
            result = engine._preflight_order(
                market="KRW-BTC",
                side="bid",
                requested_value=10000,
                reference_price=reference_price,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["rounded_price"], expected)

    def test_timeout_cancel_and_reorder_flow(self):
        broker = TimeoutFlowBroker()
        notifier = DummyNotifier()
        config = TradingConfig(
            do_not_trading=[], krw_markets=["KRW-BTC"], max_order_retries=1
        )
        engine = TradingEngine(broker, notifier, config)
        engine.bootstrap_open_orders()

        stale = engine.orders_by_identifier["open-1"]
        stale.state = OrderStatus.ACCEPTED
        stale.updated_at = datetime.now(timezone.utc) - timedelta(
            seconds=engine.order_timeout_seconds + 1
        )

        engine.reconcile_orders()

        self.assertGreaterEqual(broker.get_order_calls.count("open-uuid-1"), 1)
        self.assertEqual(broker.cancel_calls, ["open-uuid-1"])
        self.assertEqual(len(broker.buy_calls), 1)
        self.assertIn(":root=open-1", broker.buy_calls[0][2])


if __name__ == "__main__":
    unittest.main()
