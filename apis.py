import jwt
import uuid
import hashlib
import slave_constants
import pandas as pd
from urllib.parse import urlencode

import requests

# need to slave_constants.py
# ex) slave_constants.py
# ACCESS_KEY = 'your access key'
# SECRET_KEY = 'your scret key'
# SERVER_URL = 'https://api.upbit.com'
access_key = slave_constants.ACCESS_KEY
secret_key = slave_constants.SECRET_KEY
server_url = slave_constants.SERVER_URL

payload_non_param = {
    'access_key': access_key,
    'nonce': str(uuid.uuid4()),
}


# query는 dict 타입
def get_payload(query=None):
    if not query:
        return payload_non_param

    m = hashlib.sha512()
    m.update(urlencode(query).encode())
    query_hash = m.hexdigest()
    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
        'query_hash': query_hash,
        'query_hash_alg': 'SHA512',
    }
    return payload


def get_accounts():
    jwt_token = jwt.encode(get_payload(), secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}

    res = requests.get(server_url + "/v1/accounts", headers=headers)
    return res.json()


def get_markets():
    querystring = {"isDetails": "false"}
    res = requests.get(server_url + "/v1/market/all", params=querystring)
    return res.json()


def get_ticker(markets):
    querystring = {"markets": markets}
    res = requests.get(server_url + "/v1/ticker", params=querystring)
    return res.json()


def get_candles(market="KRW-BTC", count=200, candle_type="days", to=None):
    querystring = {"market": market, "count": str(count)}
    if to:
        querystring["to"] = to

    res = requests.get(server_url + "/v1/candles/" + candle_type, params=querystring)
    return res.json()


def get_candles_minutes(market="KRW-BTC", count=200, interval=10):
    return get_candles(market, count, "minutes/" + str(interval))


def get_candles_day(market="KRW-BTC", count=200):
    return get_candles(market, count, "days")


def get_candles_week(market="KRW-BTC", count=200):
    return get_candles(market, count, "weeks")


def get_candles_month(market="KRW-BTC", count=200):
    return get_candles(market, count, "months")


def orders(market="KRW-BTC", side="bid", volume=0.01, price=100.0, ord_type="limit"):
    query = {
        'market': market,
        'side': side,
        'ord_type': ord_type,
    }

    if volume > 0:
        query['volume'] = str(volume)

    if price > 0:
        query['price'] = str(price)

    query_string = urlencode(query).encode()

    m = hashlib.sha512()
    m.update(query_string)
    query_hash = m.hexdigest()

    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
        'query_hash': query_hash,
        'query_hash_alg': 'SHA512',
    }

    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}

    res = requests.post(server_url + "/v1/orders", params=query, headers=headers)
    return res.json()


# 시장가 매수
def bid_price(market="KRW-BTC", price=100.0):
    return orders(market, "bid", 0, price, "price")


# 시장가 매도
def ask_market(market="KRW-BTC", volumn=1.0):
    return orders(market, "ask", volumn, 0, "market")
