from __future__ import annotations

import datetime
import json
import math
import os.path
from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass, field, replace
from statistics import median, pstdev

import openpyxl  # noqa: F401
import pandas as pd

import apis
from core.rsi_bb_reversal_long import evaluate_long_entry
from core.config_loader import load_trading_config
from core.position_policy import ExitDecision, PositionExitState, PositionOrderPolicy
from core.strategy import check_buy, check_sell, classify_market_regime, debug_entry, preprocess_candles, zone_debug_metrics


@dataclass
class SegmentResult:
    segment_id: int
    insample_start: str
    insample_end: str
    oos_start: str
    oos_end: str
    trades: int
    entries: int = 0
    closed_trades: int = 0
    attempted_entries: int = 0
    candidate_entries: int = 0
    triggered_entries: int = 0
    avg_zones_total: float = 0.0
    avg_zones_active: float = 0.0
    fill_rate: float = 0.0
    return_pct: float = 0.0
    period_return: float = 0.0
    return_per_trade: float = 0.0
    cagr: float = 0.0
    cagr_valid: bool = True
    observed_days: float = 0.0
    mdd: float = 0.0
    sharpe: float = 0.0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    profit_loss_ratio: float = 0.0
    expectancy: float = 0.0
    compounded_return_pct: float = 0.0
    segment_return_std: float = 0.0
    segment_return_median: float = 0.0
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_r_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    entry_fail_counts: dict[str, int] = field(default_factory=dict)
    avg_entry_score: float = 0.0
    score_q25: float = 0.0
    score_q50: float = 0.0
    score_q75: float = 0.0
    score_win_rate_q1: float = 0.0
    score_win_rate_q2: float = 0.0
    score_win_rate_q3: float = 0.0
    score_win_rate_q4: float = 0.0
    regime_trade_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    quality_bucket_stats: dict[str, dict[str, float]] = field(default_factory=dict)




@dataclass
class TradeLedgerEntry:
    entry_price: float
    exit_price: float
    fee: float
    pnl: float
    r_multiple: float
    reason: str
    holding_minutes: float
    entry_regime: str = "unknown"
    entry_score: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    fee_estimate_krw: float = 0.0
    slippage_estimate_krw: float = 0.0


@dataclass
class BacktestPositionState:
    avg_buy_price: float = 0.0
    exit_state: PositionExitState = field(default_factory=PositionExitState)
    last_exit_at: str = ""
    last_exit_reason: str = ""
    last_exit_bar_index: int = -1


class BacktestRunner:
    MAX_CANDLE_LIMIT = 200
    MIN_CAGR_OBSERVATION_DAYS = 90
    ABNORMAL_CAGR_THRESHOLD_PCT = 500

    def __init__(
        self,
        market: str = "KRW-BTC",
        path: str = "backdata_candle_day.xlsx",
        buffer_cnt: int = 200,
        multiple_cnt: int = 6,
        spread_rate: float = 0.0003,
        slippage_rate: float = 0.0002,
        insample_windows: int = 2,
        oos_windows: int = 2,
        segment_report_path: str = "backtest_walkforward_segments.csv",
        lookback_days: int | None = None,
        sell_decision_rule: str = "or",
        debug_mode: bool = False,
        debug_report_path: str = "backtest_entry_failures.csv",
        zone_profile: str | None = None,
        zone_expiry_bars_5m: int | None = None,
        fvg_min_width_atr_mult: float | None = None,
        displacement_min_atr_mult: float | None = None,
    ):
        self.market = market
        self.path = path
        self.buffer_cnt = buffer_cnt
        self.multiple_cnt = multiple_cnt
        self.config = load_trading_config()
        self.mtf_timeframes = self._resolve_mtf_timeframes()
        self.zone_profile = zone_profile
        self.zone_overrides = {
            "zone_expiry_bars_5m": zone_expiry_bars_5m,
            "fvg_min_width_atr_mult": fvg_min_width_atr_mult,
            "displacement_min_atr_mult": displacement_min_atr_mult,
        }
        self.strategy_params = self._build_effective_strategy_params()
        self.spread_rate = max(0.0, float(spread_rate))
        self.slippage_rate = max(0.0, float(slippage_rate))
        self.insample_windows = max(1, int(insample_windows))
        # Ensure each OOS segment has more than one evaluation step.
        self.oos_windows = max(2, int(oos_windows))
        self.segment_report_path = segment_report_path
        self.lookback_days = int(lookback_days) if lookback_days else None
        if self.lookback_days is not None and self.lookback_days <= 0:
            raise ValueError("lookback_days must be > 0")
        self.order_policy = PositionOrderPolicy(
            stop_loss_threshold=self.config.stop_loss_threshold,
            trailing_stop_pct=self.config.trailing_stop_pct,
            partial_take_profit_threshold=self.config.partial_take_profit_threshold,
            partial_take_profit_ratio=self.config.partial_take_profit_ratio,
            partial_stop_loss_ratio=self.config.partial_stop_loss_ratio,
            exit_mode=self.config.exit_mode,
            atr_period=self.config.atr_period,
            atr_stop_mult=self.config.atr_stop_mult,
            atr_trailing_mult=self.config.atr_trailing_mult,
            swing_lookback=self.config.swing_lookback,
        )
        self.sell_decision_rule = str(sell_decision_rule).lower().strip()
        self.debug_mode = bool(debug_mode)
        self.debug_report_path = debug_report_path
        self.required_base_bars_for_regime = self._required_base_bars_for_regime()
        self.required_base_bars_for_mtf_minimums = self._required_base_bars_for_mtf_minimums()
        if self.sell_decision_rule not in {"or", "and"}:
            raise ValueError("sell_decision_rule must be 'or' or 'and'")
        self._validate_mtf_capacity(raise_on_failure=False)

    def _resolve_mtf_timeframes(self) -> dict[str, int]:
        base_interval = max(1, int(self.config.candle_interval))

        def align(target: int) -> int:
            if target <= base_interval:
                return base_interval
            return int(math.ceil(target / base_interval) * base_interval)

        return {
            "1m": align(1),
            "5m": align(5),
            "15m": align(15),
        }

    def _build_effective_strategy_params(self):
        raw_params = self.config.to_strategy_params(zone_profile=self.zone_profile, zone_overrides=self.zone_overrides)

        def scaled_min(target_tf: int, target_min: int, actual_tf: int) -> int:
            target_duration = max(1, int(target_min)) * target_tf
            return max(1, int(math.ceil(target_duration / max(1, actual_tf))))

        return replace(
            raw_params,
            min_candles_1m=scaled_min(1, raw_params.min_candles_1m, self.mtf_timeframes["1m"]),
            min_candles_5m=scaled_min(5, raw_params.min_candles_5m, self.mtf_timeframes["5m"]),
            min_candles_15m=scaled_min(15, raw_params.min_candles_15m, self.mtf_timeframes["15m"]),
        )

    def _validate_mtf_capacity(self, raise_on_failure: bool = False) -> dict[str, int]:
        base_interval = max(1, int(self.config.candle_interval))
        available: dict[str, int] = {}
        for key, minutes in self.mtf_timeframes.items():
            ratio = max(1, int(math.ceil(minutes / base_interval)))
            available[key] = max(1, int(math.ceil(self.buffer_cnt / ratio)))
        required_min = {
            "1m": int(self.strategy_params.min_candles_1m),
            "5m": int(self.strategy_params.min_candles_5m),
            "15m": int(self.strategy_params.min_candles_15m),
        }
        regime_required_15m = self._required_regime_15m_candles() if bool(self.strategy_params.regime_filter_enabled) else 0
        required = dict(required_min)
        if regime_required_15m > 0:
            required["15m"] = max(required_min["15m"], regime_required_15m)

        insufficient = {key: (available[key], required[key]) for key in required if available[key] < required[key]}
        if insufficient:
            details = []
            for key, values in insufficient.items():
                available_cnt, required_cnt = values
                min_required = required_min[key]
                if key == "15m":
                    details.append(
                        f"{key}: available={available_cnt} < required={required_cnt} "
                        f"(min_candles 기준={min_required}, regime 기준={regime_required_15m})"
                    )
                else:
                    details.append(
                        f"{key}: available={available_cnt} < required={required_cnt} "
                        f"(min_candles 기준={min_required})"
                    )
            detail = ", ".join(details)
            message = (
                "insufficient MTF candle capacity for backtest buffer_cnt="
                f"{self.buffer_cnt} (base={self.config.candle_interval}m, tf={self.mtf_timeframes}): {detail}. "
                "Increase buffer_cnt or lower min_candles/regime thresholds."
            )
            if raise_on_failure:
                raise ValueError(message)
            print(f"[WARN] {message}")
        return available

    def _required_regime_15m_candles(self) -> int:
        return max(
            int(self.strategy_params.regime_ema_slow),
            int(self.strategy_params.regime_adx_period) + 1,
            int(self.strategy_params.regime_slope_lookback) + 1,
        )

    def _required_base_bars_for_target_tf(self, *, target_tf_minutes: int, target_tf_bars: int) -> int:
        base_interval = max(1, int(self.config.candle_interval))
        ratio = max(1, int(math.ceil(max(1, int(target_tf_minutes)) / base_interval)))
        return max(1, int(target_tf_bars)) * ratio

    def _required_base_bars_for_regime(self) -> int:
        if not bool(self.strategy_params.regime_filter_enabled):
            return 0
        required_15m = self._required_regime_15m_candles()
        return self._required_base_bars_for_target_tf(target_tf_minutes=self.mtf_timeframes["15m"], target_tf_bars=required_15m)

    def _required_base_bars_for_mtf_minimums(self) -> int:
        requirements = (
            self._required_base_bars_for_target_tf(
                target_tf_minutes=self.mtf_timeframes["1m"],
                target_tf_bars=int(self.strategy_params.min_candles_1m),
            ),
            self._required_base_bars_for_target_tf(
                target_tf_minutes=self.mtf_timeframes["5m"],
                target_tf_bars=int(self.strategy_params.min_candles_5m),
            ),
            self._required_base_bars_for_target_tf(
                target_tf_minutes=self.mtf_timeframes["15m"],
                target_tf_bars=int(self.strategy_params.min_candles_15m),
            ),
        )
        return max(requirements)

    @staticmethod
    def _resolve_entry_regime(mtf_data: dict[str, list[dict]], strategy_params) -> str:
        try:
            regime = classify_market_regime(mtf_data.get("15m", []), strategy_params)
        except Exception:
            return "unknown"
        return regime if regime in {"strong_trend", "weak_trend", "sideways"} else "unknown"

    @staticmethod
    def _build_regime_trade_stats(ledger: list[TradeLedgerEntry]) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[TradeLedgerEntry]] = {"strong_trend": [], "weak_trend": [], "sideways": [], "unknown": []}
        for trade in ledger:
            regime = str(getattr(trade, "entry_regime", "unknown") or "unknown").strip().lower()
            grouped.setdefault(regime, []).append(trade)

        summary: dict[str, dict[str, float]] = {}
        for regime, trades in grouped.items():
            pnls = [trade.pnl for trade in trades]
            wins = [pnl for pnl in pnls if pnl > 0]
            summary[regime] = {
                "trades": float(len(trades)),
                "win_rate": float((len(wins) / len(trades) * 100.0) if trades else 0.0),
                "expectancy": float((sum(pnls) / len(pnls)) if pnls else 0.0),
            }
        return summary

    @staticmethod
    def _build_quality_bucket_stats(rows: list[tuple[str, float]]) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
        for bucket, pnl in rows:
            key = str(bucket or "low").strip().lower()
            grouped.setdefault(key, []).append(float(pnl))

        result: dict[str, dict[str, float]] = {}
        for bucket, pnls in grouped.items():
            wins = [p for p in pnls if p > 0]
            result[bucket] = {
                "trades": float(len(pnls)),
                "win_rate": float((len(wins) / len(pnls) * 100.0) if pnls else 0.0),
                "expectancy": float((sum(pnls) / len(pnls)) if pnls else 0.0),
            }
        return result

    @staticmethod
    def _score_win_rates_by_quantile(score_pnl_rows: list[tuple[float, float]]) -> dict[str, float]:
        if not score_pnl_rows:
            return {"q1": 0.0, "q2": 0.0, "q3": 0.0, "q4": 0.0}

        df = pd.DataFrame(score_pnl_rows, columns=["score", "pnl"])
        if df["score"].nunique(dropna=True) < 2:
            win_rate = float((df["pnl"] > 0).mean() * 100.0)
            return {"q1": win_rate, "q2": win_rate, "q3": win_rate, "q4": win_rate}

        df["bucket"] = pd.qcut(df["score"], q=4, labels=["q1", "q2", "q3", "q4"], duplicates="drop")
        result = {"q1": 0.0, "q2": 0.0, "q3": 0.0, "q4": 0.0}
        grouped = df.dropna(subset=["bucket"]).groupby("bucket", observed=False)["pnl"]
        for bucket, pnl_series in grouped:
            result[str(bucket)] = float((pnl_series > 0).mean() * 100.0)
        return result

    @staticmethod
    def _build_exit_reason_r_stats(ledger: list[TradeLedgerEntry]) -> dict[str, dict[str, float]]:
        by_reason: dict[str, list[float]] = {}
        for entry in ledger:
            by_reason.setdefault(str(entry.reason), []).append(float(entry.r_multiple))

        result: dict[str, dict[str, float]] = {}
        for reason, values in by_reason.items():
            ordered = sorted(values)
            if not ordered:
                continue
            q10_index = max(0, int((len(ordered) - 1) * 0.1))
            result[reason] = {
                "mean": float(sum(ordered) / len(ordered)),
                "median": float(median(ordered)),
                "p10": float(ordered[q10_index]),
            }
        return result

    def _resolve_exit_decision(
        self,
        *,
        state: BacktestPositionState,
        current_price: float,
        signal_exit: bool,
        current_atr: float = 0.0,
        swing_low: float = 0.0,
    ) -> ExitDecision:
        policy_signal_exit = signal_exit if self.sell_decision_rule != "and" else False
        policy_decision = self.order_policy.evaluate(
            state=state.exit_state,
            avg_buy_price=state.avg_buy_price,
            current_price=current_price,
            signal_exit=policy_signal_exit,
            current_atr=current_atr,
            swing_low=swing_low,
            strategy_name=str(getattr(self.strategy_params, "strategy_name", "")),
            partial_take_profit_enabled=bool(getattr(self.strategy_params, "partial_take_profit_enabled", False)),
            partial_take_profit_r=float(getattr(self.strategy_params, "partial_take_profit_r", 1.0)),
            partial_take_profit_size=float(getattr(self.strategy_params, "partial_take_profit_size", 0.0)),
            move_stop_to_breakeven_after_partial=bool(
                getattr(self.strategy_params, "move_stop_to_breakeven_after_partial", False)
            ),
            max_hold_bars=int(getattr(self.strategy_params, "max_hold_bars", 0)),
        )
        if self.sell_decision_rule == "and":
            if signal_exit and policy_decision.should_exit:
                return policy_decision
            return ExitDecision(should_exit=False)

        if policy_decision.should_exit:
            return policy_decision
        return ExitDecision(should_exit=False)


    def _is_reentry_cooldown_active(self, state: BacktestPositionState, bar_index: int) -> bool:
        cooldown_bars = max(0, int(self.config.reentry_cooldown_bars))
        if cooldown_bars <= 0 or state.last_exit_bar_index < 0:
            return False

        if self.config.cooldown_on_loss_exits_only and state.last_exit_reason not in {"trailing_stop", "stop_loss"}:
            return False

        elapsed_bars = max(0, bar_index - state.last_exit_bar_index)
        return elapsed_bars < cooldown_bars


    def _latest_atr(self, candles_newest: list[dict], period: int) -> float:
        if period <= 0:
            return 0.0
        candles = list(reversed(candles_newest))
        if len(candles) < 2:
            return 0.0
        trs: list[float] = []
        for i in range(1, len(candles)):
            cur, prev = candles[i], candles[i - 1]
            high = float(cur.get("high_price", cur.get("trade_price", 0.0)))
            low = float(cur.get("low_price", cur.get("trade_price", 0.0)))
            prev_close = float(prev.get("trade_price", 0.0))
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        if not trs:
            return 0.0
        window = trs[-min(period, len(trs)) :]
        return sum(window) / len(window)

    def _latest_swing_low(self, candles_newest: list[dict], lookback: int) -> float:
        window = candles_newest[: max(1, lookback)]
        if not window:
            return 0.0
        return min(float(candle.get("low_price", candle.get("trade_price", 0.0))) for candle in window)

    def _target_count(self) -> int:
        base_count = self.buffer_cnt * self.multiple_cnt
        if self.lookback_days is None:
            return base_count
        candles_per_day = math.ceil((24 * 60) / self.config.candle_interval)
        required_count = candles_per_day * self.lookback_days
        return max(base_count, required_count)

    def _normalize_candle(self, candle: dict) -> dict:
        normalized = dict(candle)
        for key in ("opening_price", "high_price", "low_price", "trade_price", "candle_acc_trade_volume"):
            if key in normalized:
                normalized[key] = float(normalized[key])
        return normalized

    def _fetch_chunk(self, to_dt: datetime.datetime | None) -> list[dict]:
        to_arg = to_dt.strftime("%Y-%m-%d %H:%M:%S") if to_dt else None
        response = apis.get_candles(
            self.market,
            candle_type=f"minutes/{self.config.candle_interval}",
            count=min(self.buffer_cnt, self.MAX_CANDLE_LIMIT),
            to=to_arg,
        )
        return [self._normalize_candle(candle) for candle in response]

    def _backfill_rest_chunks(self) -> list[dict]:
        candles: list[dict] = []
        seen_times: set[str] = set()
        cursor: datetime.datetime | None = None
        target_count = self._target_count()

        while len(candles) < target_count:
            chunk = self._fetch_chunk(cursor)
            if not chunk:
                break

            appended = 0
            for candle in chunk:
                ts = str(candle["candle_date_time_kst"])
                if ts in seen_times:
                    continue
                seen_times.add(ts)
                candles.append(candle)
                appended += 1

            oldest = chunk[-1]
            oldest_ts = datetime.datetime.strptime(oldest["candle_date_time_kst"], "%Y-%m-%dT%H:%M:%S")
            cursor = oldest_ts - datetime.timedelta(minutes=self.config.candle_interval)
            if appended == 0:
                break

        return candles[:target_count]

    def _apply_shortage_policy(self, candles_newest: list[dict]) -> tuple[list[dict], int]:
        """When backfill is shorter than target, prepend synthetic missing candles using prior close."""
        target_count = self._target_count()
        if len(candles_newest) >= target_count or not candles_newest:
            return candles_newest[:target_count], 0

        short_cnt = target_count - len(candles_newest)
        last = candles_newest[-1]
        last_time = datetime.datetime.strptime(last["candle_date_time_kst"], "%Y-%m-%dT%H:%M:%S")
        close_price = float(last["trade_price"])
        padding: list[dict] = []

        for i in range(short_cnt, 0, -1):
            ts = last_time - datetime.timedelta(minutes=self.config.candle_interval * i)
            padding.append(
                {
                    "market": self.market,
                    "candle_date_time_kst": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "opening_price": close_price,
                    "high_price": close_price,
                    "low_price": close_price,
                    "trade_price": close_price,
                    "candle_acc_trade_volume": 0.0,
                    "missing": True,
                }
            )

        return candles_newest + padding, short_cnt

    def _filter_recent_days(self, candles_newest: list[dict]) -> list[dict]:
        if self.lookback_days is None or not candles_newest:
            return candles_newest
        newest_time = datetime.datetime.strptime(candles_newest[0]["candle_date_time_kst"], "%Y-%m-%dT%H:%M:%S")
        threshold = newest_time - datetime.timedelta(days=self.lookback_days)
        filtered = [
            candle
            for candle in candles_newest
            if datetime.datetime.strptime(candle["candle_date_time_kst"], "%Y-%m-%dT%H:%M:%S") >= threshold
        ]
        return filtered or candles_newest

    def _load_or_create_data(self) -> tuple[list[dict], int]:
        if not os.path.exists(self.path):
            print("make back data excel file : ", self.path)
            candles = self._backfill_rest_chunks()
            candles, short_cnt = self._apply_shortage_policy(candles)
            pd.DataFrame(candles).to_excel(excel_writer=self.path)
            print(f"backfill shortage filled with synthetic candles: {short_cnt}")

        candles_df = pd.read_excel(self.path, sheet_name="Sheet1")
        candles_df.drop(candles_df.columns[0], axis=1, inplace=True)
        records = [self._normalize_candle(rec) for rec in list(candles_df.T.to_dict().values())]
        processed = preprocess_candles(records, source_order="newest")
        return self._apply_shortage_policy(processed)

    def _mark_to_market(self, cash: float, hold_coin: float, current_price: float) -> float:
        exit_multiplier = 1 - self.config.fee_rate - (self.spread_rate / 2) - self.slippage_rate
        return cash + hold_coin * current_price * max(exit_multiplier, 0.0)

    def _resample_candles(self, candles_newest: list[dict], timeframe_minutes: int) -> list[dict]:
        if timeframe_minutes <= 1:
            return [dict(candle) for candle in candles_newest]
        if not candles_newest:
            return []

        candles_oldest = list(reversed(candles_newest))
        bucketed: list[dict] = []
        current_bucket: dict | None = None
        current_bucket_ts: datetime.datetime | None = None

        for candle in candles_oldest:
            ts = datetime.datetime.strptime(candle["candle_date_time_kst"], "%Y-%m-%dT%H:%M:%S")
            bucket_ts = ts.replace(minute=(ts.minute // timeframe_minutes) * timeframe_minutes, second=0, microsecond=0)

            if current_bucket is None or current_bucket_ts != bucket_ts:
                if current_bucket is not None:
                    bucketed.append(current_bucket)
                current_bucket_ts = bucket_ts
                current_bucket = {
                    "market": candle.get("market", self.market),
                    "candle_date_time_kst": bucket_ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "opening_price": float(candle["opening_price"]),
                    "high_price": float(candle["high_price"]),
                    "low_price": float(candle["low_price"]),
                    "trade_price": float(candle["trade_price"]),
                    "candle_acc_trade_volume": float(candle.get("candle_acc_trade_volume", 0.0)),
                }
                continue

            # Explicit OHLCV resampling rules per timeframe bucket.
            current_bucket["high_price"] = max(float(current_bucket["high_price"]), float(candle["high_price"]))
            current_bucket["low_price"] = min(float(current_bucket["low_price"]), float(candle["low_price"]))
            current_bucket["trade_price"] = float(candle["trade_price"])
            current_bucket["candle_acc_trade_volume"] = float(current_bucket["candle_acc_trade_volume"]) + float(
                candle.get("candle_acc_trade_volume", 0.0)
            )

        if current_bucket is not None:
            bucketed.append(current_bucket)

        return list(reversed(bucketed))

    def _build_mtf_candles(self, candles_newest: list[dict]) -> dict[str, list[dict]]:
        base = [dict(candle) for candle in candles_newest]
        return {
            "1m": self._resample_candles(base, timeframe_minutes=self.mtf_timeframes["1m"]),
            "5m": self._resample_candles(base, timeframe_minutes=self.mtf_timeframes["5m"]),
            "15m": self._resample_candles(base, timeframe_minutes=self.mtf_timeframes["15m"]),
        }

    def _calc_metrics(
        self,
        equity_curve: list[float],
        trades: int,
        attempted_entries: int,
        candidate_entries: int,
        triggered_entries: int,
    ) -> tuple[float, float, float, float, float, float, bool, float]:
        if not equity_curve:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, 0.0
        start = equity_curve[0]
        end = equity_curve[-1]
        total_return = (end / start) - 1 if start > 0 else 0.0
        period_return = total_return * 100
        return_per_trade = period_return / trades if trades > 0 else 0.0

        periods_per_year = (60 * 24 * 365) / self.config.candle_interval
        observed_days = max(len(equity_curve) - 1, 0) * self.config.candle_interval / (60 * 24)
        years = max(len(equity_curve) / periods_per_year, 1e-9)
        cagr_valid = observed_days >= self.MIN_CAGR_OBSERVATION_DAYS
        cagr = float("nan")
        if cagr_valid and start > 0 and end > 0:
            cagr = ((end / start) ** (1 / years) - 1) * 100

        peak = equity_curve[0]
        mdd = 0.0
        for value in equity_curve:
            peak = max(peak, value)
            drawdown = (value - peak) / peak if peak > 0 else 0.0
            mdd = min(mdd, drawdown)

        rets = []
        for idx in range(1, len(equity_curve)):
            prev = equity_curve[idx - 1]
            if prev <= 0:
                continue
            rets.append((equity_curve[idx] / prev) - 1)

        if not rets:
            sharpe = 0.0
        else:
            mean_ret = sum(rets) / len(rets)
            vol = pstdev(rets)
            annualize = math.sqrt(periods_per_year)
            sharpe = (mean_ret / vol) * annualize if vol > 0 else 0.0

        # attempted/triggered entries are exposed for reporting parity with segment CSV,
        # while fill_rate intentionally tracks candidate zone quality.
        _ = attempted_entries
        _ = triggered_entries
        fill_rate = trades / candidate_entries if candidate_entries > 0 else 0.0
        return period_return, return_per_trade, cagr, abs(mdd) * 100, sharpe, fill_rate, cagr_valid, observed_days

    def _build_fail_summary(self, fail_counts: dict[str, int]) -> dict[str, int | str]:
        counters = Counter(fail_counts)
        regime_fail_total = sum(count for code, count in counters.items() if str(code).startswith("regime_filter_fail"))
        return {
            "fail_insufficient_candles": int(counters.get("insufficient_candles", 0)),
            "fail_no_selected_zone": int(counters.get("no_selected_zone", 0)),
            "fail_trigger_fail": int(counters.get("trigger_fail", 0)),
            "fail_invalid_timeframe": int(counters.get("invalid_timeframe", 0)),
            "fail_regime_filter_fail": int(regime_fail_total),
            "fail_reentry_cooldown": int(counters.get("fail_reentry_cooldown", 0)),
            "dominant_fail_code": max(counters, key=counters.get) if counters else "none",
        }

    def _calc_trade_stats(self, ledger: list[TradeLedgerEntry]) -> tuple[float, float, float, float, float]:
        if not ledger:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        pnls = [entry.pnl for entry in ledger]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]
        win_rate = (len(wins) / len(ledger)) * 100
        avg_profit = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        profit_loss_ratio = (avg_profit / abs(avg_loss)) if avg_loss < 0 else 0.0
        expectancy = sum(pnls) / len(pnls)
        return win_rate, avg_profit, avg_loss, profit_loss_ratio, expectancy

    def _run_segment(self, data_newest: list[dict], init_amount: float, segment_id: int) -> SegmentResult:
        amount = init_amount
        hold_coin = 0.0
        attempted_entries = 0
        candidate_entries = 0
        triggered_entries = 0
        zone_debug_samples = 0
        zones_total_sum = 0
        zones_active_sum = 0
        entries = 0
        closed_trades = 0
        equity_curve = [init_amount]
        position_state = BacktestPositionState()
        exit_reason_counts: Counter[str] = Counter()
        entry_fail_counts: Counter[str] = Counter()
        trade_ledger: list[TradeLedgerEntry] = []
        entry_scores: list[float] = []
        trade_score_rows: list[tuple[float, float]] = []
        trade_quality_rows: list[tuple[str, float]] = []
        active_trade: dict[str, float | str] | None = None
        required_window_size = max(
            int(self.buffer_cnt),
            int(self.required_base_bars_for_regime),
            int(self.required_base_bars_for_mtf_minimums),
        )
        # Keep warm-up history inside current segment only (no in-sample leakage).
        segment_floor = 0

        max_current_index = max(len(data_newest) - self.buffer_cnt, segment_floor)
        for bar_index, current_index in enumerate(range(max_current_index, segment_floor - 1, -1)):
            end = min(len(data_newest), current_index + required_window_size)
            start = max(current_index, segment_floor)
            test_data = data_newest[start:end]
            current_price = float(test_data[0]["trade_price"])
            mtf_data = self._build_mtf_candles(test_data)
            current_atr = self._latest_atr(test_data, self.config.atr_period)
            swing_low = self._latest_swing_low(test_data, self.config.swing_lookback)

            if hold_coin == 0:
                strategy_name = str(getattr(self.strategy_params, "strategy_name", "")).lower().strip()
                entry_eval = evaluate_long_entry(mtf_data, self.strategy_params) if strategy_name == "rsi_bb_reversal_long" else None
                if entry_eval is not None:
                    entry_scores.append(float(entry_eval.diagnostics.get("entry_score", 0.0) or 0.0))

                debug = debug_entry(mtf_data, self.strategy_params, side="buy")
                zones_total, zones_active, has_candidate_entry = zone_debug_metrics(debug)
                if has_candidate_entry:
                    candidate_entries += 1
                    attempted_entries += 1

                if debug:
                    zone_debug_samples += 1
                    zones_total_sum += zones_total
                    zones_active_sum += zones_active

                if self.debug_mode:
                    buy_signal = bool(debug.get("final_pass", False))
                else:
                    buy_signal = check_buy(mtf_data, self.strategy_params)

                blocked_by_cooldown = buy_signal and self._is_reentry_cooldown_active(position_state, bar_index)
                if blocked_by_cooldown:
                    buy_signal = False
                    entry_fail_counts["fail_reentry_cooldown"] += 1

                if not buy_signal and debug and not blocked_by_cooldown:
                    fail_code = str(debug.get("fail_code", "unknown"))
                    if fail_code == "regime_filter_fail":
                        regime_reason = str(debug.get("regime_filter_reason", "unknown"))
                        fail_code = f"regime_filter_fail:{regime_reason}"
                    entry_fail_counts[fail_code] += 1

                if buy_signal:
                    triggered_entries += 1
                    entries += 1
                    quality_score = float(entry_eval.diagnostics.get("quality_score", 0.0) or 0.0) if entry_eval else 0.0
                    if quality_score >= float(self.config.quality_score_high_threshold):
                        quality_bucket = "high"
                        quality_multiplier = float(self.config.quality_multiplier_high)
                    elif quality_score >= float(self.config.quality_score_low_threshold):
                        quality_bucket = "mid"
                        quality_multiplier = float(self.config.quality_multiplier_mid)
                    else:
                        quality_bucket = "low"
                        quality_multiplier = float(self.config.quality_multiplier_low)
                    quality_multiplier = min(float(self.config.quality_multiplier_max_bound), max(float(self.config.quality_multiplier_min_bound), quality_multiplier))
                    base_entry_amount = amount * 0.8
                    pre_entry_amount = min(amount, base_entry_amount * quality_multiplier)
                    entry_price = current_price * (1 + (self.spread_rate / 2) + self.slippage_rate)
                    hold_coin += (pre_entry_amount * (1 - self.config.fee_rate)) / entry_price
                    position_state.avg_buy_price = entry_price
                    initial_stop_price = entry_price * self.config.stop_loss_threshold
                    risk_per_unit = max(entry_price - initial_stop_price, 0.0)
                    position_state.exit_state = PositionExitState(
                        peak_price=current_price,
                        entry_atr=current_atr,
                        entry_swing_low=swing_low,
                        entry_price=entry_price,
                        initial_stop_price=initial_stop_price,
                        risk_per_unit=risk_per_unit,
                        entry_regime=self._resolve_entry_regime(mtf_data, self.strategy_params),
                    )
                    active_trade = {
                        "entry_price": entry_price,
                        "entry_time": str(test_data[0]["candle_date_time_kst"]),
                        "invested_cash": pre_entry_amount,
                        "entry_fee": pre_entry_amount * self.config.fee_rate,
                        "entry_score": float(entry_eval.diagnostics.get("entry_score", 0.0) or 0.0) if entry_eval else 0.0,
                        "quality_score": quality_score,
                        "quality_bucket": quality_bucket,
                        "quality_multiplier": quality_multiplier,
                        "entry_regime": str(position_state.exit_state.entry_regime or "unknown"),
                        "sold_qty": 0.0,
                        "gross_exit_notional": 0.0,
                        "exit_fee": 0.0,
                        "net_exit_cash": 0.0,
                    }
                    print(
                        json.dumps(
                            {
                                "type": "ENTRY_DIAGNOSTICS",
                                "market": self.market,
                                "entry_score": float(active_trade["entry_score"]),
                                "quality_score": float(active_trade["quality_score"]),
                                "quality_bucket": str(active_trade["quality_bucket"]),
                                "quality_multiplier": float(active_trade["quality_multiplier"]),
                                "entry_regime": str(active_trade["entry_regime"]),
                                "sizing": {
                                    "base_order_krw": int(base_entry_amount),
                                    "final_order_krw": int(pre_entry_amount),
                                    "entry_price": float(entry_price),
                                    "risk_per_unit": float(risk_per_unit),
                                },
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                    amount = max(0.0, amount - pre_entry_amount)
            else:
                signal_exit = check_sell(
                    mtf_data,
                    avg_buy_price=position_state.avg_buy_price,
                    params=self.strategy_params,
                    entry_price=position_state.exit_state.entry_price,
                    initial_stop_price=position_state.exit_state.initial_stop_price,
                    risk_per_unit=position_state.exit_state.risk_per_unit,
                )
                decision = self._resolve_exit_decision(
                    state=position_state,
                    current_price=current_price,
                    signal_exit=signal_exit,
                    current_atr=current_atr,
                    swing_low=swing_low,
                )
                if decision.should_exit:
                    qty_ratio = min(1.0, max(0.0, float(decision.qty_ratio)))
                    if qty_ratio <= 0:
                        continue
                    exit_price = current_price * (1 - (self.spread_rate / 2) - self.slippage_rate)
                    sell_qty = hold_coin * qty_ratio
                    gross_notional = sell_qty * exit_price
                    exit_fee = gross_notional * self.config.fee_rate
                    amount += gross_notional - exit_fee
                    hold_coin = max(0.0, hold_coin - sell_qty)
                    if active_trade is not None:
                        active_trade["sold_qty"] = float(active_trade["sold_qty"]) + sell_qty
                        active_trade["gross_exit_notional"] = float(active_trade["gross_exit_notional"]) + gross_notional
                        active_trade["exit_fee"] = float(active_trade["exit_fee"]) + exit_fee
                        active_trade["net_exit_cash"] = float(active_trade["net_exit_cash"]) + (gross_notional - exit_fee)
                    normalized_reason = "signal_exit" if decision.reason == "strategy_signal" else decision.reason
                    exit_reason_counts[normalized_reason] += 1
                    if hold_coin <= 0:
                        completed_exit_state = position_state.exit_state
                        hold_coin = 0.0
                        position_state.last_exit_at = test_data[0]["candle_date_time_kst"]
                        position_state.last_exit_reason = normalized_reason
                        position_state.last_exit_bar_index = bar_index
                        position_state.avg_buy_price = 0.0
                        position_state.exit_state = PositionExitState()
                        if active_trade is not None and float(active_trade["sold_qty"]) > 0:
                            closed_trades += 1
                            entry_time = datetime.datetime.strptime(str(active_trade["entry_time"]), "%Y-%m-%dT%H:%M:%S")
                            exit_time = datetime.datetime.strptime(test_data[0]["candle_date_time_kst"], "%Y-%m-%dT%H:%M:%S")
                            holding_minutes = max(0.0, (exit_time - entry_time).total_seconds() / 60)
                            avg_exit_price = float(active_trade["gross_exit_notional"]) / float(active_trade["sold_qty"])
                            pnl = float(active_trade["net_exit_cash"]) - float(active_trade["invested_cash"])
                            risk_amount = float(active_trade["invested_cash"]) * max(self.config.stop_loss_threshold, 1e-9)
                            r_multiple = pnl / risk_amount if risk_amount > 0 else 0.0
                            trade_ledger.append(
                                TradeLedgerEntry(
                                    entry_price=float(active_trade["entry_price"]),
                                    exit_price=float(avg_exit_price),
                                    fee=float(active_trade["entry_fee"]) + float(active_trade["exit_fee"]),
                                    pnl=float(pnl),
                                    r_multiple=float(r_multiple),
                                    reason=normalized_reason,
                                    holding_minutes=float(holding_minutes),
                                    entry_regime=str(active_trade.get("entry_regime", "unknown") or "unknown"),
                                    entry_score=float(active_trade.get("entry_score", 0.0) or 0.0),
                                    mfe_r=float(completed_exit_state.highest_r),
                                    mae_r=abs(min(0.0, float(completed_exit_state.lowest_r))),
                                    fee_estimate_krw=float(active_trade["entry_fee"]) + float(active_trade["exit_fee"]),
                                    slippage_estimate_krw=float(active_trade["invested_cash"]) * self.slippage_rate,
                                )
                            )
                            print(
                                json.dumps(
                                    {
                                        "type": "EXIT_DIAGNOSTICS",
                                        "market": self.market,
                                        "exit_reason": normalized_reason,
                                        "holding_minutes": float(holding_minutes),
                                        "mfe_r": float(completed_exit_state.highest_r),
                                        "mae_r": abs(min(0.0, float(completed_exit_state.lowest_r))),
                                        "realized_r": float(r_multiple),
                                        "fee_estimate_krw": float(active_trade["entry_fee"]) + float(active_trade["exit_fee"]),
                                        "slippage_estimate_krw": float(active_trade["invested_cash"]) * self.slippage_rate,
                                        "entry_score": float(active_trade.get("entry_score", 0.0) or 0.0),
                                        "entry_regime": str(active_trade.get("entry_regime", "unknown") or "unknown"),
                                    },
                                    ensure_ascii=False,
                                    sort_keys=True,
                                )
                            )
                            trade_score_rows.append((float(active_trade.get("entry_score", 0.0) or 0.0), float(pnl)))
                            trade_quality_rows.append((str(active_trade.get("quality_bucket", "low") or "low"), float(pnl)))
                        active_trade = None

            equity_curve.append(self._mark_to_market(amount, hold_coin, current_price))

        total_return, return_per_trade, cagr, mdd, sharpe, fill_rate, cagr_valid, observed_days = self._calc_metrics(
            equity_curve,
            entries,
            attempted_entries,
            candidate_entries,
            triggered_entries,
        )
        win_rate, avg_profit, avg_loss, profit_loss_ratio, expectancy = self._calc_trade_stats(trade_ledger)
        exit_reason_r_stats = self._build_exit_reason_r_stats(trade_ledger)
        oldest = data_newest[-1]["candle_date_time_kst"]
        newest = data_newest[0]["candle_date_time_kst"]
        avg_zones_total = zones_total_sum / zone_debug_samples if zone_debug_samples > 0 else 0.0
        avg_zones_active = zones_active_sum / zone_debug_samples if zone_debug_samples > 0 else 0.0
        score_q25 = float(pd.Series(entry_scores).quantile(0.25)) if entry_scores else 0.0
        score_q50 = float(pd.Series(entry_scores).quantile(0.50)) if entry_scores else 0.0
        score_q75 = float(pd.Series(entry_scores).quantile(0.75)) if entry_scores else 0.0
        score_win_rates = self._score_win_rates_by_quantile(trade_score_rows)
        regime_trade_stats = self._build_regime_trade_stats(trade_ledger)
        quality_bucket_stats = self._build_quality_bucket_stats(trade_quality_rows)
        return SegmentResult(
            segment_id=segment_id,
            insample_start=oldest,
            insample_end=newest,
            oos_start=oldest,
            oos_end=newest,
            trades=entries,
            entries=entries,
            closed_trades=closed_trades,
            attempted_entries=attempted_entries,
            candidate_entries=candidate_entries,
            triggered_entries=triggered_entries,
            avg_zones_total=avg_zones_total,
            avg_zones_active=avg_zones_active,
            fill_rate=fill_rate,
            return_pct=total_return,
            period_return=total_return,
            return_per_trade=return_per_trade,
            cagr=cagr,
            cagr_valid=cagr_valid,
            observed_days=observed_days,
            mdd=mdd,
            sharpe=sharpe,
            win_rate=win_rate,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            profit_loss_ratio=profit_loss_ratio,
            expectancy=expectancy,
            exit_reason_counts=dict(exit_reason_counts),
            exit_reason_r_stats=exit_reason_r_stats,
            entry_fail_counts=dict(entry_fail_counts),
            avg_entry_score=(sum(entry_scores) / len(entry_scores)) if entry_scores else 0.0,
            score_q25=score_q25,
            score_q50=score_q50,
            score_q75=score_q75,
            score_win_rate_q1=score_win_rates.get("q1", 0.0),
            score_win_rate_q2=score_win_rates.get("q2", 0.0),
            score_win_rate_q3=score_win_rates.get("q3", 0.0),
            score_win_rate_q4=score_win_rates.get("q4", 0.0),
            regime_trade_stats=regime_trade_stats,
            quality_bucket_stats=quality_bucket_stats,
        )

    def run(self):
        raw_data, shortage_count = self._load_or_create_data()
        raw_data = self._filter_recent_days(raw_data)
        init_amount = float(self.config.paper_initial_krw)
        in_len = self.insample_windows * self.buffer_cnt
        oos_len = self.oos_windows * self.buffer_cnt
        step = oos_len
        results: list[SegmentResult] = []

        max_start = max(len(raw_data) - (in_len + oos_len), 0)
        segment_id = 1
        for start in range(0, max_start + 1, step):
            insample = raw_data[start : start + in_len]
            oos = raw_data[start + in_len : start + in_len + oos_len]
            if len(insample) < self.buffer_cnt or len(oos) < self.buffer_cnt:
                continue
            segment = self._run_segment(oos, init_amount, segment_id=segment_id)
            segment = SegmentResult(
                segment_id=segment.segment_id,
                insample_start=insample[-1]["candle_date_time_kst"],
                insample_end=insample[0]["candle_date_time_kst"],
                oos_start=oos[-1]["candle_date_time_kst"],
                oos_end=oos[0]["candle_date_time_kst"],
                trades=segment.trades,
                entries=segment.entries,
                closed_trades=segment.closed_trades,
                attempted_entries=segment.attempted_entries,
                candidate_entries=segment.candidate_entries,
                triggered_entries=segment.triggered_entries,
                avg_zones_total=segment.avg_zones_total,
                avg_zones_active=segment.avg_zones_active,
                fill_rate=segment.fill_rate,
                return_pct=segment.return_pct,
                period_return=segment.period_return,
                return_per_trade=segment.return_per_trade,
                cagr=segment.cagr,
                cagr_valid=segment.cagr_valid,
                observed_days=segment.observed_days,
                mdd=segment.mdd,
                sharpe=segment.sharpe,
                win_rate=segment.win_rate,
                avg_profit=segment.avg_profit,
                avg_loss=segment.avg_loss,
                profit_loss_ratio=segment.profit_loss_ratio,
                expectancy=segment.expectancy,
                exit_reason_counts=segment.exit_reason_counts,
                exit_reason_r_stats=segment.exit_reason_r_stats,
                entry_fail_counts=segment.entry_fail_counts,
                avg_entry_score=segment.avg_entry_score,
                score_q25=segment.score_q25,
                score_q50=segment.score_q50,
                score_q75=segment.score_q75,
                score_win_rate_q1=segment.score_win_rate_q1,
                score_win_rate_q2=segment.score_win_rate_q2,
                score_win_rate_q3=segment.score_win_rate_q3,
                score_win_rate_q4=segment.score_win_rate_q4,
                regime_trade_stats=segment.regime_trade_stats,
                quality_bucket_stats=segment.quality_bucket_stats,
            )
            results.append(segment)
            segment_id += 1

        if not results and len(raw_data) >= self.buffer_cnt:
            results.append(self._run_segment(raw_data, init_amount, segment_id=1))

        df = pd.DataFrame([r.__dict__ for r in results])
        reason_df = pd.DataFrame(
            [
                {
                    "exit_reason_signal_exit": row.exit_reason_counts.get("signal_exit", 0),
                    "exit_reason_stop_loss": row.exit_reason_counts.get("stop_loss", 0),
                    "exit_reason_trailing_stop": row.exit_reason_counts.get("trailing_stop", 0),
                    "exit_reason_partial_take_profit": row.exit_reason_counts.get("partial_take_profit", 0),
                    "exit_reason_partial_stop_loss": row.exit_reason_counts.get("partial_stop_loss", 0),
                    "exit_reason_signal_exit_mean_r": row.exit_reason_r_stats.get("signal_exit", {}).get("mean", 0.0),
                    "exit_reason_signal_exit_median_r": row.exit_reason_r_stats.get("signal_exit", {}).get("median", 0.0),
                    "exit_reason_signal_exit_p10_r": row.exit_reason_r_stats.get("signal_exit", {}).get("p10", 0.0),
                    "exit_reason_stop_loss_mean_r": row.exit_reason_r_stats.get("stop_loss", {}).get("mean", 0.0),
                    "exit_reason_stop_loss_median_r": row.exit_reason_r_stats.get("stop_loss", {}).get("median", 0.0),
                    "exit_reason_stop_loss_p10_r": row.exit_reason_r_stats.get("stop_loss", {}).get("p10", 0.0),
                    "exit_reason_trailing_stop_mean_r": row.exit_reason_r_stats.get("trailing_stop", {}).get("mean", 0.0),
                    "exit_reason_trailing_stop_median_r": row.exit_reason_r_stats.get("trailing_stop", {}).get("median", 0.0),
                    "exit_reason_trailing_stop_p10_r": row.exit_reason_r_stats.get("trailing_stop", {}).get("p10", 0.0),
                    "exit_reason_partial_take_profit_mean_r": row.exit_reason_r_stats.get("partial_take_profit", {}).get("mean", 0.0),
                    "exit_reason_partial_take_profit_median_r": row.exit_reason_r_stats.get("partial_take_profit", {}).get("median", 0.0),
                    "exit_reason_partial_take_profit_p10_r": row.exit_reason_r_stats.get("partial_take_profit", {}).get("p10", 0.0),
                    "exit_reason_partial_stop_loss_mean_r": row.exit_reason_r_stats.get("partial_stop_loss", {}).get("mean", 0.0),
                    "exit_reason_partial_stop_loss_median_r": row.exit_reason_r_stats.get("partial_stop_loss", {}).get("median", 0.0),
                    "exit_reason_partial_stop_loss_p10_r": row.exit_reason_r_stats.get("partial_stop_loss", {}).get("p10", 0.0),
                    "regime_strong_trend_trades": row.regime_trade_stats.get("strong_trend", {}).get("trades", 0.0),
                    "regime_strong_trend_win_rate": row.regime_trade_stats.get("strong_trend", {}).get("win_rate", 0.0),
                    "regime_strong_trend_expectancy": row.regime_trade_stats.get("strong_trend", {}).get("expectancy", 0.0),
                    "regime_weak_trend_trades": row.regime_trade_stats.get("weak_trend", {}).get("trades", 0.0),
                    "regime_weak_trend_win_rate": row.regime_trade_stats.get("weak_trend", {}).get("win_rate", 0.0),
                    "regime_weak_trend_expectancy": row.regime_trade_stats.get("weak_trend", {}).get("expectancy", 0.0),
                    "regime_sideways_trades": row.regime_trade_stats.get("sideways", {}).get("trades", 0.0),
                    "regime_sideways_win_rate": row.regime_trade_stats.get("sideways", {}).get("win_rate", 0.0),
                    "regime_sideways_expectancy": row.regime_trade_stats.get("sideways", {}).get("expectancy", 0.0),
                    "quality_bucket_low_trades": row.quality_bucket_stats.get("low", {}).get("trades", 0.0),
                    "quality_bucket_low_win_rate": row.quality_bucket_stats.get("low", {}).get("win_rate", 0.0),
                    "quality_bucket_low_expectancy": row.quality_bucket_stats.get("low", {}).get("expectancy", 0.0),
                    "quality_bucket_mid_trades": row.quality_bucket_stats.get("mid", {}).get("trades", 0.0),
                    "quality_bucket_mid_win_rate": row.quality_bucket_stats.get("mid", {}).get("win_rate", 0.0),
                    "quality_bucket_mid_expectancy": row.quality_bucket_stats.get("mid", {}).get("expectancy", 0.0),
                    "quality_bucket_high_trades": row.quality_bucket_stats.get("high", {}).get("trades", 0.0),
                    "quality_bucket_high_win_rate": row.quality_bucket_stats.get("high", {}).get("win_rate", 0.0),
                    "quality_bucket_high_expectancy": row.quality_bucket_stats.get("high", {}).get("expectancy", 0.0),
                }
                for row in results
            ]
        )
        fail_df = pd.DataFrame([self._build_fail_summary(row.entry_fail_counts) for row in results])
        if not reason_df.empty:
            df = pd.concat(
                [df.drop(columns=["exit_reason_counts", "exit_reason_r_stats", "entry_fail_counts", "regime_trade_stats", "quality_bucket_stats"], errors="ignore"), reason_df],
                axis=1,
            )
        if not fail_df.empty:
            df = pd.concat([df, fail_df], axis=1)
        if not df.empty:
            period_returns = pd.to_numeric(df["period_return"], errors="coerce").fillna(0.0)
            compounded = (period_returns.div(100).add(1.0).prod() - 1.0) * 100
            df["compounded_return_pct"] = compounded
            df["segment_return_std"] = float(period_returns.std(ddof=0))
            df["segment_return_median"] = float(period_returns.median())
        df.to_csv(self.segment_report_path, index=False)

        for row in results:
            if row.trades > 0 or not row.entry_fail_counts:
                continue
            top_reasons = Counter(row.entry_fail_counts).most_common(3)
            reasons_text = ", ".join(f"{code}={count}" for code, count in top_reasons)
            print(f"[WARN] segment {row.segment_id} has trades=0, top fail reasons: {reasons_text}")

        if self.debug_mode and results:
            debug_df = pd.DataFrame(
                [
                    {
                        "segment_id": row.segment_id,
                        "attempted_entries": row.attempted_entries,
                        "candidate_entries": row.candidate_entries,
                        "triggered_entries": row.triggered_entries,
                        "trades": row.trades,
                        "signal_zero": row.trades == 0,
                        **self._build_fail_summary(row.entry_fail_counts),
                    }
                    for row in results
                ]
            )
            debug_df.to_csv(self.debug_report_path, index=False)

        summary = (
            df[["period_return", "return_per_trade", "return_pct", "cagr", "mdd", "sharpe", "fill_rate"]].mean(
                numeric_only=True
            ).to_dict()
            if not df.empty
            else {}
        )
        summary["initial_amount_krw"] = init_amount
        if not df.empty:
            period_values = pd.to_numeric(df["period_return"], errors="coerce").fillna(0.0).tolist()
            summary["compounded_return_pct"] = (math.prod((1 + (value / 100)) for value in period_values) - 1) * 100
            summary["period_return_std"] = pstdev(period_values) if period_values else 0.0
            summary["period_return_median"] = median(period_values) if period_values else 0.0
        summary["final_amount_krw"] = summary["initial_amount_krw"] * (1 + (summary.get("compounded_return_pct", 0.0) / 100))
        abnormal_cagr_rows = (
            df[df["cagr_valid"] & df["cagr"].abs().gt(self.ABNORMAL_CAGR_THRESHOLD_PCT)] if not df.empty else pd.DataFrame()
        )
        print(f"synthetic shortage candles applied: {shortage_count}")
        print(f"walk-forward segments saved: {self.segment_report_path}")
        if self.debug_mode:
            print(f"entry failure debug saved: {self.debug_report_path}")
        if not abnormal_cagr_rows.empty:
            ids = ", ".join(str(int(v)) for v in abnormal_cagr_rows["segment_id"].tolist())
            print(
                "[WARN] abnormal CAGR detected in segments "
                f"({ids}) with threshold ±{self.ABNORMAL_CAGR_THRESHOLD_PCT}%"
            )
        print("평균 성과:", {k: round(v, 4) for k, v in summary.items()})
        return summary


if __name__ == "__main__":
    parser = ArgumentParser(description="Run backtest with optional recent lookback window")
    parser.add_argument("--market", default="KRW-BTC")
    parser.add_argument("--path", default="backdata_candle_day.xlsx")
    parser.add_argument("--buffer-cnt", type=int, default=200)
    parser.add_argument("--multiple-cnt", type=int, default=6)
    parser.add_argument("--insample-windows", type=int, default=2)
    parser.add_argument("--oos-windows", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--segment-report-path", default="backtest_walkforward_segments.csv")
    parser.add_argument("--sell-decision-rule", choices=["or", "and"], default="or")
    parser.add_argument("--debug-mode", action="store_true")
    parser.add_argument("--debug-report-path", default="backtest_entry_failures.csv")
    parser.add_argument(
        "--zone-profile",
        choices=["conservative", "balanced", "aggressive", "krw_eth_relaxed"],
        default=None,
        help="Zone tuning profile override. krw_eth_relaxed is a reproducible KRW-ETH example.",
    )
    parser.add_argument("--zone-expiry-bars-5m", type=int, default=None)
    parser.add_argument("--fvg-min-width-atr-mult", type=float, default=None)
    parser.add_argument("--displacement-min-atr-mult", type=float, default=None)
    args = parser.parse_args()

    BacktestRunner(
        market=args.market,
        path=args.path,
        buffer_cnt=args.buffer_cnt,
        multiple_cnt=args.multiple_cnt,
        insample_windows=args.insample_windows,
        oos_windows=args.oos_windows,
        lookback_days=args.lookback_days,
        segment_report_path=args.segment_report_path,
        sell_decision_rule=args.sell_decision_rule,
        debug_mode=args.debug_mode,
        debug_report_path=args.debug_report_path,
        zone_profile=args.zone_profile,
        zone_expiry_bars_5m=args.zone_expiry_bars_5m,
        fvg_min_width_atr_mult=args.fvg_min_width_atr_mult,
        displacement_min_atr_mult=args.displacement_min_atr_mult,
    ).run()
