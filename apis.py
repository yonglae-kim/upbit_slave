import jwt
import uuid
import hashlib
import slave_constants
import pandas as pd
from urllib.parse import urlencode, unquote

import requests

# need to slave_constants.py
# ex) slave_constants.py
# ACCESS_KEY = 'your access key'
# SECRET_KEY = 'your scret key'
# SERVER_URL = 'https://api.upbit.com'
access_key = slave_constants.ACCESS_KEY
secret_key = slave_constants.SECRET_KEY
server_url = slave_constants.SERVER_URL

CONNECT_TIMEOUT = 3.05
READ_TIMEOUT = 10
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)
_session = requests.Session()
_last_remaining_req = None


class ApiRequestError(Exception):
    def __init__(self, status_code, payload, remaining_req=None):
        super().__init__(f"Upbit API request failed with status {status_code}")
        self.status_code = status_code
        self.payload = payload
        self.remaining_req = remaining_req


def parse_remaining_req(remaining_req_header):
    if not remaining_req_header:
        return None

    parsed = {}
    for token in remaining_req_header.split(';'):
        key, _sep, value = token.strip().partition('=')
        if not key or not value:
            continue
        parsed[key] = int(value) if value.isdigit() else value
    return parsed or None


def get_last_remaining_req():
    return _last_remaining_req


def _build_rate_limit_signal(status_code, payload, remaining_req, retry_after=None):
    signal = {
        "ok": False,
        "error_type": "rate_limit",
        "status_code": status_code,
        "error": payload,
        "remaining_req": remaining_req,
        "retry_after": retry_after,
        "should_stop_loop": status_code == 418,
    }
    return signal


def _request(method, path, *, params=None, headers=None, timeout=TIMEOUT):
    global _last_remaining_req

    response = _session.request(
        method=method,
        url=server_url + path,
        params=params,
        headers=headers,
        timeout=timeout,
    )

    remaining_req = parse_remaining_req(response.headers.get("Remaining-Req"))
    _last_remaining_req = remaining_req

    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text}

    if response.status_code in (429, 418):
        retry_after_header = response.headers.get("Retry-After")
        retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else None
        return _build_rate_limit_signal(response.status_code, payload, remaining_req, retry_after)

    if not 200 <= response.status_code < 300:
        raise ApiRequestError(response.status_code, payload, remaining_req)

    return payload


def build_query_string(params):
    """
    Build an Upbit-compatible query string.

    If key order must be preserved, pass an OrderedDict or a list of tuples.
    """
    return unquote(urlencode(params, doseq=True))

# query는 dict 타입
def get_payload(query=None):
    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
    }

    if not query:
        return payload

    query_string = query if isinstance(query, str) else build_query_string(query)

    m = hashlib.sha512()
    m.update(query_string.encode())
    payload['query_hash'] = m.hexdigest()
    payload['query_hash_alg'] = 'SHA512'
    return payload


def get_accounts():
    jwt_token = jwt.encode(get_payload(), secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}

    return _request("GET", "/v1/accounts", headers=headers)


def get_markets():
    querystring = {"isDetails": "false"}
    return _request("GET", "/v1/market/all", params=querystring)


def get_ticker(markets):
    querystring = {"markets": markets}
    return _request("GET", "/v1/ticker", params=querystring)


def get_candles(market="KRW-BTC", count=200, candle_type="days", to=None):
    querystring = {"market": market, "count": str(count)}
    if to:
        querystring["to"] = to

    return _request("GET", "/v1/candles/" + candle_type, params=querystring)


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

    query_string = build_query_string(query)

    jwt_token = jwt.encode(get_payload(query_string), secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}

    return _request("POST", "/v1/orders", params=query, headers=headers)


# 시장가 매수
def bid_price(market="KRW-BTC", price=100.0):
    return orders(market, "bid", 0, price, "price")


# 시장가 매도
def ask_market(market="KRW-BTC", volumn=1.0):
    return orders(market, "ask", volumn, 0, "market")
