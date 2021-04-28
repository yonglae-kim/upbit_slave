import apis
import slave_constants
import time
import strategy.strategy as st

list_krw_market = []
list_btc_market = []
list_usdt_market = []
dict_market_name = {}

# init market list.
result = apis.get_markets()
list_market = []
for item in result:
    if 'KRW' in item['market']:
        is_add = True
        for market in slave_constants.DO_NOT_TRADING:
            if market in item['market']:
                is_add = False
        if not is_add:
            continue
        list_krw_market.append(item['market'])
    elif 'BTC' in item['market']:
        list_btc_market.append(item['market'])
    elif 'USDT' in item['market']:
        list_usdt_market.append(item['market'])
    dict_market_name[item['market']] = item['korean_name']


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


while 1:
    accounts = apis.get_accounts()
    my_coins = []
    has_coin = []
    for item in accounts:
        if item['unit_currency'] != 'KRW':
            continue
        if item['balance'] == 0:
            continue
        if item['currency'] in slave_constants.DO_NOT_TRADING:
            continue
        if item['currency'] == "KRW":
            avail_krw = float(item['balance'])
            continue
        my_coins.append(item)
        has_coin.append("KRW-" + item['currency'])

    for account in my_coins:
        data = apis.get_candles_minutes("KRW-" + account['currency'], interval=10)
        if check_sell(data):
            apis.ask_market("KRW-" + account['currency'], float(account['balance']))
            print("SELL", "KRW-" + account['currency'], account['balance'] + account['currency'],
                  data[0]['trade_price'])

    if avail_krw > 20000 and len(has_coin) < 6:
        tickers = apis.get_ticker(', '.join(list_krw_market))
        tickers.sort(key=lambda x: float(x['trade_volume']), reverse=True)
        for ticker in tickers[:15]:
            if ticker['market'] in has_coin:
                print(ticker['market'], "has already ")
                continue
            data = apis.get_candles_minutes(ticker['market'], interval=10)
            if check_buy(data):
                apis.bid_price(ticker['market'], avail_krw / 5)
                print("BUY", ticker['market'], str(avail_krw // 5) + "원", data[0]['trade_price'])
                avail_krw -= avail_krw // 5

    time.sleep(60)
