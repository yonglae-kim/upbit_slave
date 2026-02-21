import datetime
import os
import sys
import time

import apis
import message.tele as tele
import slave_constants
import strategy.strategy as st

UPBIT_FEE_RATE = 0.0005
MIN_ORDER_KRW = 5000

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
    if macd['MACD'].iloc[-3] < macd['MACD'].iloc[-2] or macd['MACD'].iloc[-2] > \
            macd['MACD'].iloc[-1]:
        return False
    if macd['MACD'].iloc[-1] > 0:
        return False
    return True


def to_safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def handle_krw_account(item):
    balance = to_safe_float(item.get("balance", 0))
    locked = to_safe_float(item.get("locked", 0))
    tradable_balance = balance + locked

    if tradable_balance <= 0:
        return None

    return balance


def handle_coin_account(item, my_coins, has_coin):
    balance = to_safe_float(item.get("balance", 0))
    locked = to_safe_float(item.get("locked", 0))
    tradable_balance = balance + locked

    if tradable_balance <= 0:
        return
    if item['currency'] in slave_constants.DO_NOT_TRADING:
        return

    item['balance'] = balance
    item['locked'] = locked
    item['tradable_balance'] = tradable_balance
    my_coins.append(item)
    has_coin.append("KRW-" + item['currency'])


while 1:
    try:
        accounts = apis.get_accounts()
        my_coins = []
        has_coin = []
        avail_krw = 0.0
        for item in accounts:
            if item['unit_currency'] != 'KRW':
                continue

            if item['currency'] == "KRW":
                account_krw = handle_krw_account(item)
                if account_krw is not None:
                    avail_krw = account_krw
                continue

            handle_coin_account(item, my_coins, has_coin)

        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '보유코인 :', has_coin)
        for account in my_coins:
            data = apis.get_candles_minutes("KRW-" + account['currency'], interval=3)

            if check_sell(data, float(account['avg_buy_price'])) or float(data[0]['trade_price']) < float(
                    account['avg_buy_price']) * 0.975:
                apis.ask_market("KRW-" + account['currency'], account['balance'])
                print("SELL", "KRW-" + account['currency'], str(account['balance']) + account['currency'],
                      data[0]['trade_price'])
                tele.sendMessage("SELL " + "KRW-" + account['currency'] + " " + str(data[0]['trade_price']) + " "
                                 + str(((float(data[0]['trade_price']) - float(account['avg_buy_price'])) / float(
                    account['avg_buy_price'])) * 100) + "%")
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
                    order_krw = (avail_krw / 5) * (1 - UPBIT_FEE_RATE)
                    if order_krw < MIN_ORDER_KRW:
                        print("SKIP", ticker['market'], "주문 가능 금액 부족", str(int(order_krw)) + "원")
                        continue
                    if avail_krw - order_krw < MIN_ORDER_KRW:
                        print("SKIP", ticker['market'], "주문 후 잔액 최소금액 미만", str(int(avail_krw - order_krw)) + "원")
                        continue

                    apis.bid_price(ticker['market'], order_krw)
                    print("BUY", ticker['market'], str(int(order_krw)) + "원", data[0]['trade_price'])
                    tele.sendMessage("BUY " + ticker['market'] + " " + str(data[0]['trade_price']))
                    avail_krw -= order_krw
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
