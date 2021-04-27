import apis
import pandas as pd

import strategy.strategy

list_krw_market = []
list_btc_market = []
list_usdt_market = []
dict_market_name = {}

# result = apis.get_accounts()
#
# for item in result:
#     print(item)

# init market list.
result = apis.get_markets()
list_market = []
for item in result:
    if 'KRW' in item['market']:
        list_krw_market.append(item['market'])
    elif 'BTC' in item['market']:
        list_btc_market.append(item['market'])
    elif 'USDT' in item['market']:
        list_usdt_market.append(item['market'])
    dict_market_name[item['market']] = item['korean_name']

#get current trade price
# result = apis.get_ticker(",".join(list_krw_market))
# for item in result:
#     print(dict_market_name[item['market']], item['trade_price'])

#get candles
result = apis.get_candles_minutes(list_krw_market[0], 200, 10)

rsi = strategy.strategy.rsi(result)
print(list_krw_market[0], 'rsi', rsi)