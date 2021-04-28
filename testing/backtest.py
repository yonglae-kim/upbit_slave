import openpyxl
import pandas as pd
import datetime
import os.path
import strategy.strategy as st
import apis
import time

# prepare data
candles_day = []
test_market = 'KRW-XRP'
path = 'backdata_candle_day.xlsx'
buffer_cnt = 200
multiple_cnt = 2
minutes_candle_type = 10

if not os.path.exists(path):
    print("make back data excel file : ", path)
    date_time = datetime.datetime.now()
    for _ in range(multiple_cnt):  # buffer_cnt * multiple_cnt = 1000 days
        candles_day.extend(apis.get_candles(test_market, candle_type="minutes/" + str(minutes_candle_type), count=buffer_cnt,
                                            to=date_time.strftime("%Y-%m-%d %H:%M:%S")))
        date_time -= datetime.timedelta(minutes=buffer_cnt * minutes_candle_type)

    # excel 로 저장
    candles_day = pd.DataFrame(candles_day)
    candles_day.to_excel(excel_writer=path)
    print(candles_day)

candles_day = pd.read_excel(path, sheet_name='Sheet1')
#  remove unnamed index column
candles_day.drop(candles_day.columns[0], axis=1, inplace=True)

raw_data = list(candles_day.T.to_dict().values())

is_buy = False

fee = 0.0005  # upbit 원화거래 수수료 0.05%
init_amount = 1000000  # 초기 시드머니
amount = init_amount
hold_coin = 0
for i in range(len(raw_data), buffer_cnt, -1):
    end = i
    start = end - buffer_cnt
    if start < 0:
        start = 0

    test_data = raw_data[start:end]


    def check_buy(data):
        ichimoku = st.ichimoku_cloud(data)
        cur_price = data[0]['trade_price']
        if abs(ichimoku['senkou_span_a'] - ichimoku['senkou_span_b']) > cur_price * 0.1:
            return False

        if ichimoku['tenkan_sen'] < ichimoku['senkou_span_a'] or ichimoku['tenkan_sen'] < ichimoku['senkou_span_b']:
            return False

        return True

    def check_sell(data):
        ichimoku = st.ichimoku_cloud(data)
        cur_price = data[0]['trade_price']
        if cur_price < ichimoku['senkou_span_b']:
            return True
        return False


    rsi = st.rsi(test_data)
    if hold_coin == 0 and check_buy(test_data):
        print('BUY', test_data[0]['candle_date_time_kst'], "구매가:", test_data[0]['trade_price'], rsi)
        hold_coin += (amount * (1 - fee)) / test_data[0]['trade_price']
        amount = 0
        is_buy = True
    elif hold_coin > 0 and check_sell(test_data):
        amount += hold_coin * test_data[0]['trade_price'] * (1 - fee)
        hold_coin = 0
        print('SELL', test_data[0]['candle_date_time_kst'], "판매가:", test_data[0]['trade_price'], rsi)

percent = (((amount + (hold_coin * raw_data[0]['trade_price'])) - init_amount) / init_amount) * 100
print("수익률 :", str(round(percent, 2)) + '%')


