from __future__ import annotations

import datetime
import math
import os.path
from dataclasses import dataclass
from statistics import pstdev

import openpyxl  # noqa: F401
import pandas as pd

import apis
from core.config_loader import load_trading_config
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
        oos_windows: int = 1,
        segment_report_path: str = "backtest_walkforward_segments.csv",
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
        self.oos_windows = max(1, int(oos_windows))
        self.segment_report_path = segment_report_path

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
        target_count = self.buffer_cnt * self.multiple_cnt

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
        target_count = self.buffer_cnt * self.multiple_cnt
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
        avg_buy_price = 0.0

        for i in range(len(data_newest), self.buffer_cnt, -1):
            end = i
            start = max(end - self.buffer_cnt, 0)
            test_data = data_newest[start:end]
            current_price = float(test_data[0]["trade_price"])

            if hold_coin == 0:
                attempted_entries += 1
                if check_buy(test_data, self.strategy_params):
                    trades += 1
                    entry_price = current_price * (1 + (self.spread_rate / 2) + self.slippage_rate)
                    hold_coin += (amount * (1 - self.config.fee_rate)) / entry_price
                    avg_buy_price = entry_price
                    amount = 0.0
            else:
                if check_sell(test_data, avg_buy_price=avg_buy_price, params=self.strategy_params):
                    exit_price = current_price * (1 - (self.spread_rate / 2) - self.slippage_rate)
                    amount += hold_coin * exit_price * (1 - self.config.fee_rate)
                    hold_coin = 0.0

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
        )

    def run(self):
        raw_data, shortage_count = self._load_or_create_data()
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
            )
            results.append(segment)
            segment_id += 1

        if not results and len(raw_data) >= self.buffer_cnt:
            results.append(self._run_segment(raw_data, init_amount, segment_id=1))

        df = pd.DataFrame([r.__dict__ for r in results])
        df.to_csv(self.segment_report_path, index=False)

        summary = df[["return_pct", "cagr", "mdd", "sharpe", "fill_rate"]].mean().to_dict() if not df.empty else {}
        print(f"synthetic shortage candles applied: {shortage_count}")
        print(f"walk-forward segments saved: {self.segment_report_path}")
        print("평균 성과:", {k: round(v, 4) for k, v in summary.items()})
        return summary


if __name__ == "__main__":
    BacktestRunner().run()
