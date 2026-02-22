from __future__ import annotations

import datetime
import math
import os.path
from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass, field
from statistics import pstdev

import openpyxl  # noqa: F401
import pandas as pd

import apis
from core.config_loader import load_trading_config
from core.position_policy import ExitDecision, PositionExitState, PositionOrderPolicy
from core.strategy import check_buy, check_sell, preprocess_candles


@dataclass
class SegmentResult:
    segment_id: int
    insample_start: str
    insample_end: str
    oos_start: str
    oos_end: str
    trades: int
    attempted_entries: int
    fill_rate: float
    return_pct: float
    cagr: float
    mdd: float
    sharpe: float
    exit_reason_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class BacktestPositionState:
    avg_buy_price: float = 0.0
    exit_state: PositionExitState = field(default_factory=PositionExitState)


class BacktestRunner:
    MAX_CANDLE_LIMIT = 200

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
    ):
        self.market = market
        self.path = path
        self.buffer_cnt = buffer_cnt
        self.multiple_cnt = multiple_cnt
        self.config = load_trading_config()
        self.strategy_params = self.config.to_strategy_params()
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
        )
        self.sell_decision_rule = str(sell_decision_rule).lower().strip()
        if self.sell_decision_rule not in {"or", "and"}:
            raise ValueError("sell_decision_rule must be 'or' or 'and'")

    def _resolve_exit_decision(self, *, state: BacktestPositionState, current_price: float, signal_exit: bool) -> ExitDecision:
        policy_decision = self.order_policy.evaluate(
            state=state.exit_state,
            avg_buy_price=state.avg_buy_price,
            current_price=current_price,
            signal_exit=False,
        )
        if self.sell_decision_rule == "and":
            if signal_exit and policy_decision.should_exit:
                return policy_decision
            return ExitDecision(should_exit=False)

        if policy_decision.should_exit:
            return policy_decision
        if signal_exit:
            return ExitDecision(should_exit=True, qty_ratio=1.0, reason="signal_exit")
        return ExitDecision(should_exit=False)

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
            "1m": base,
            "5m": self._resample_candles(base, timeframe_minutes=5),
            "15m": self._resample_candles(base, timeframe_minutes=15),
        }

    def _calc_metrics(self, equity_curve: list[float], trades: int, attempted_entries: int) -> tuple[float, float, float, float]:
        if not equity_curve:
            return 0.0, 0.0, 0.0, 0.0
        start = equity_curve[0]
        end = equity_curve[-1]
        total_return = (end / start) - 1 if start > 0 else 0.0

        periods_per_year = (60 * 24 * 365) / self.config.candle_interval
        years = max(len(equity_curve) / periods_per_year, 1e-9)
        cagr = ((end / start) ** (1 / years) - 1) if start > 0 and end > 0 else -1.0

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

        fill_rate = trades / attempted_entries if attempted_entries > 0 else 0.0
        return total_return * 100, cagr * 100, abs(mdd) * 100, sharpe, fill_rate

    def _run_segment(self, data_newest: list[dict], init_amount: float, segment_id: int) -> SegmentResult:
        amount = init_amount
        hold_coin = 0.0
        attempted_entries = 0
        trades = 0
        equity_curve = [init_amount]
        position_state = BacktestPositionState()
        exit_reason_counts: Counter[str] = Counter()

        for i in range(len(data_newest), self.buffer_cnt - 1, -1):
            end = i
            start = max(end - self.buffer_cnt, 0)
            test_data = data_newest[start:end]
            current_price = float(test_data[0]["trade_price"])
            mtf_data = self._build_mtf_candles(test_data)

            if hold_coin == 0:
                attempted_entries += 1
                if check_buy(mtf_data, self.strategy_params):
                    trades += 1
                    entry_price = current_price * (1 + (self.spread_rate / 2) + self.slippage_rate)
                    hold_coin += (amount * (1 - self.config.fee_rate)) / entry_price
                    position_state.avg_buy_price = entry_price
                    position_state.exit_state = PositionExitState(peak_price=current_price)
                    amount = 0.0
            else:
                signal_exit = check_sell(mtf_data, avg_buy_price=position_state.avg_buy_price, params=self.strategy_params)
                decision = self._resolve_exit_decision(
                    state=position_state,
                    current_price=current_price,
                    signal_exit=signal_exit,
                )
                if decision.should_exit:
                    qty_ratio = min(1.0, max(0.0, float(decision.qty_ratio)))
                    if qty_ratio <= 0:
                        continue
                    exit_price = current_price * (1 - (self.spread_rate / 2) - self.slippage_rate)
                    sell_qty = hold_coin * qty_ratio
                    amount += sell_qty * exit_price * (1 - self.config.fee_rate)
                    hold_coin = max(0.0, hold_coin - sell_qty)
                    normalized_reason = "signal_exit" if decision.reason == "strategy_signal" else decision.reason
                    exit_reason_counts[normalized_reason] += 1
                    if hold_coin <= 0:
                        hold_coin = 0.0
                        position_state = BacktestPositionState()

            equity_curve.append(self._mark_to_market(amount, hold_coin, current_price))

        total_return, cagr, mdd, sharpe, fill_rate = self._calc_metrics(equity_curve, trades, attempted_entries)
        oldest = data_newest[-1]["candle_date_time_kst"]
        newest = data_newest[0]["candle_date_time_kst"]
        return SegmentResult(
            segment_id=segment_id,
            insample_start=oldest,
            insample_end=newest,
            oos_start=oldest,
            oos_end=newest,
            trades=trades,
            attempted_entries=attempted_entries,
            fill_rate=fill_rate,
            return_pct=total_return,
            cagr=cagr,
            mdd=mdd,
            sharpe=sharpe,
            exit_reason_counts=dict(exit_reason_counts),
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
                attempted_entries=segment.attempted_entries,
                fill_rate=segment.fill_rate,
                return_pct=segment.return_pct,
                cagr=segment.cagr,
                mdd=segment.mdd,
                sharpe=segment.sharpe,
                exit_reason_counts=segment.exit_reason_counts,
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
                }
                for row in results
            ]
        )
        if not reason_df.empty:
            df = pd.concat([df.drop(columns=["exit_reason_counts"]), reason_df], axis=1)
        df.to_csv(self.segment_report_path, index=False)

        summary = df[["return_pct", "cagr", "mdd", "sharpe", "fill_rate"]].mean().to_dict() if not df.empty else {}
        print(f"synthetic shortage candles applied: {shortage_count}")
        print(f"walk-forward segments saved: {self.segment_report_path}")
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
    ).run()
