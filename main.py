import apis

list_krw_market = []
list_btc_market = []
list_usdt_market = []
dict_market_name = {}

# result = apis.get_accounts()
#
# for item in result:
#     print(item)

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

result = apis.get_ticker(",".join(list_krw_market))
for item in result:
    print(dict_market_name[item['market']], item['trade_price'])
