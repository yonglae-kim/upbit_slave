import openpyxl
import pandas as pd
import datetime
import os.path
import apis

# prepare data
candles_day = []
test_market = 'KRW-BTC'
path = 'backdata_candle_day.xlsx'
buffer_cnt = 200
multiple_cnt = 5

if not os.path.exists(path):
    print("make back data excel file : ", path)
    date_time = datetime.datetime.now()
    for _ in range(multiple_cnt):  # buffer_cnt * multiple_cnt = 1000 days
        candles_day.extend(apis.get_candles(test_market, count=buffer_cnt, to=date_time.strftime("%Y-%m-%d %H:%M:%S")))
        date_time -= datetime.timedelta(days=buffer_cnt)

    # excel 로 저장
    candles_day = pd.DataFrame(candles_day)
    candles_day.to_excel(excel_writer=path)
    print(candles_day)

candles_day = pd.read_excel(path, sheet_name='Sheet1')
#  remove unnamed index column
candles_day.drop(candles_day.columns[0], axis=1, inplace=True)

raw_data = list(candles_day.T.to_dict().values())

for i in range(len(raw_data), buffer_cnt, -1):
    end = i
    start = end - buffer_cnt
    if start < 0:
        start = 0

    test_data = raw_data[start:end]

