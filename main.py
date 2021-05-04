import datetime
import os
import sys
import time

import apis
import message.tele as tele
import slave_constants
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


def check_sell(data, avg_buy_price):
    macd = st.macd(data)

    if avg_buy_price * 1.01 > float(data[0]['trade_price']):
        return False
    if macd['MACDDiff'].iloc[-3] > macd['MACDDiff'].iloc[-1]:
        return True

    return False


def check_buy(data):
    rsi = st.rsi(data)
    macd = st.macd(data)

    if rsi > 35:
        return False
    if macd['MACDSignal'].iloc[-3] < macd['MACDSignal'].iloc[-2] or macd['MACDSignal'].iloc[-2] > \
            macd['MACDSignal'].iloc[-1]:
        return False
    if macd['MACDSignal'].iloc[-1] > 0:
        return False
    return True


while 1:
    try:
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

        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '보유코인 :', has_coin)
        for account in my_coins:
            data = apis.get_candles_minutes("KRW-" + account['currency'], interval=5)

            if check_sell(data, float(account['avg_buy_price'])) or float(data[0]['trade_price']) < float(
                    account['avg_buy_price']) * 0.975:
                apis.ask_market("KRW-" + account['currency'], float(account['balance']))
                print("SELL", "KRW-" + account['currency'], account['balance'] + account['currency'],
                      data[0]['trade_price'])
                tele.sendMessage("SELL " + "KRW-" + account['currency'] + " " + str(data[0]['trade_price']) + " "
                                 + str((float(data[0]['trade_price']) - float(account['avg_buy_price'])) / float(
                    account['avg_buy_price'])) + "%")
                time.sleep(5)

        if avail_krw > 20000 and len(has_coin) < 4:
            tickers = apis.get_ticker(', '.join(list_krw_market))
            tickers.sort(key=lambda x: float(x['trade_volume']), reverse=True)
            time.sleep(5)
            for ticker in tickers:
                if ticker['market'] in has_coin:
                    print(ticker['market'], "has already ")
                    continue
                data = apis.get_candles_minutes(ticker['market'], interval=3)
                if check_buy(data):
                    apis.bid_price(ticker['market'], avail_krw / 2)
                    print("BUY", ticker['market'], str(avail_krw // 5) + "원", data[0]['trade_price'])
                    tele.sendMessage("BUY " + ticker['market'] + " " + str(data[0]['trade_price']))
                    avail_krw -= avail_krw // 5
                    break
                time.sleep(1)
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        print(exc_type, fname, exc_tb.tb_lineno, e)
    finally:
        time.sleep(30)
