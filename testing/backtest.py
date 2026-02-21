import datetime
import os.path

import openpyxl  # noqa: F401
import pandas as pd

import apis
from core.strategy import StrategyParams, check_buy, check_sell, preprocess_candles

# prepare data
candles_day = []
test_market = 'KRW-BTC'
path = 'backdata_candle_day.xlsx'
buffer_cnt = 200
multiple_cnt = 3
minutes_candle_type = 3
strategy_params = StrategyParams(
    buy_rsi_threshold=30,
    macd_n_fast=12,
    macd_n_slow=26,
    macd_n_signal=9,
    sell_profit_threshold=1.0,
)

if not os.path.exists(path):
    print("make back data excel file : ", path)
    date_time = datetime.datetime.now()
    for _ in range(multiple_cnt):  # buffer_cnt * multiple_cnt = 1000 days
        candles_day.extend(
            apis.get_candles(test_market, candle_type="minutes/" + str(minutes_candle_type), count=buffer_cnt,
                             to=date_time.strftime("%Y-%m-%d %H:%M:%S")))
        date_time -= datetime.timedelta(minutes=buffer_cnt * minutes_candle_type)

    # excel 로 저장
    candles_day = pd.DataFrame(candles_day)
    candles_day.to_excel(excel_writer=path)
    print(candles_day)

candles_day = pd.read_excel(path, sheet_name='Sheet1')
#  remove unnamed index column
candles_day.drop(candles_day.columns[0], axis=1, inplace=True)

raw_data = preprocess_candles(list(candles_day.T.to_dict().values()), source_order="newest")

fee = 0.0005  # upbit 원화거래 수수료 0.05%
init_amount = 1000000  # 초기 시드머니
amount = init_amount
hold_coin = 0
for i in range(len(raw_data), buffer_cnt, -1):
    end = i
    start = max(end - buffer_cnt, 0)

    test_data = raw_data[start:end]
    current_price = test_data[0]['trade_price']

    if hold_coin == 0 and check_buy(test_data, strategy_params):
        print('BUY', test_data[0]['candle_date_time_kst'], "구매가:", current_price)
        hold_coin += (amount * (1 - fee)) / current_price
        amount = 0
    elif hold_coin > 0 and check_sell(test_data, avg_buy_price=current_price, params=strategy_params):
        amount += hold_coin * current_price * (1 - fee)
        hold_coin = 0
        print('SELL', test_data[0]['candle_date_time_kst'], "판매가:", current_price)

percent = (((amount + (hold_coin * raw_data[0]['trade_price'])) - init_amount) / init_amount) * 100
print("수익률 :", str(round(percent, 2)) + '%')
