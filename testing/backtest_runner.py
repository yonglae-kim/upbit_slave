from __future__ import annotations

import datetime
import os.path

import openpyxl  # noqa: F401
import pandas as pd

import apis
from core.config_loader import load_trading_config
from core.strategy import check_buy, check_sell, preprocess_candles


class BacktestRunner:
    def __init__(
        self,
        market: str = "KRW-BTC",
        path: str = "backdata_candle_day.xlsx",
        buffer_cnt: int = 200,
        multiple_cnt: int = 3,
    ):
        self.market = market
        self.path = path
        self.buffer_cnt = buffer_cnt
        self.multiple_cnt = multiple_cnt
        self.config = load_trading_config()
        self.strategy_params = self.config.to_strategy_params()

    def _load_or_create_data(self):
        candles = []
        if not os.path.exists(self.path):
            print("make back data excel file : ", self.path)
            date_time = datetime.datetime.now()
            for _ in range(self.multiple_cnt):
                candles.extend(
                    apis.get_candles(
                        self.market,
                        candle_type=f"minutes/{self.config.candle_interval}",
                        count=self.buffer_cnt,
                        to=date_time.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                )
                date_time -= datetime.timedelta(minutes=self.buffer_cnt * self.config.candle_interval)

            candles_df = pd.DataFrame(candles)
            candles_df.to_excel(excel_writer=self.path)

        candles_df = pd.read_excel(self.path, sheet_name="Sheet1")
        candles_df.drop(candles_df.columns[0], axis=1, inplace=True)
        return preprocess_candles(list(candles_df.T.to_dict().values()), source_order="newest")

    def run(self):
        raw_data = self._load_or_create_data()
        init_amount = float(self.config.paper_initial_krw)
        amount = init_amount
        hold_coin = 0.0

        for i in range(len(raw_data), self.buffer_cnt, -1):
            end = i
            start = max(end - self.buffer_cnt, 0)
            test_data = raw_data[start:end]
            current_price = float(test_data[0]["trade_price"])

            if hold_coin == 0 and check_buy(test_data, self.strategy_params):
                print("BUY", test_data[0]["candle_date_time_kst"], "구매가:", current_price)
                hold_coin += (amount * (1 - self.config.fee_rate)) / current_price
                amount = 0
            elif hold_coin > 0 and check_sell(test_data, avg_buy_price=current_price, params=self.strategy_params):
                amount += hold_coin * current_price * (1 - self.config.fee_rate)
                hold_coin = 0
                print("SELL", test_data[0]["candle_date_time_kst"], "판매가:", current_price)

        percent = (((amount + (hold_coin * raw_data[0]["trade_price"])) - init_amount) / init_amount) * 100
        print("수익률 :", str(round(percent, 2)) + "%")
        return percent


if __name__ == "__main__":
    BacktestRunner().run()
