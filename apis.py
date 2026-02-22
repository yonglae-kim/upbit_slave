import hashlib
import os
import threading
import time
import uuid
from urllib.parse import urlencode, unquote

import jwt
import requests

import slave_constants

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


def _parse_env_bool(value):
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


UPBIT_API_DEBUG = _parse_env_bool(os.getenv("UPBIT_API_DEBUG"))

API_GROUP_ORDER = "order"
API_GROUP_DEFAULT = "default"
GROUP_SECOND_LIMITS = {
    API_GROUP_ORDER: 7,
    API_GROUP_DEFAULT: 25,
}
MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 1


class ApiRequestError(Exception):
    def __init__(self, status_code, payload, remaining_req=None):
        super().__init__(f"Upbit API request failed with status {status_code}")
        self.status_code = status_code
        self.payload = payload
        self.remaining_req = remaining_req


class NonceGenerator:
    def __init__(self):
        self._lock = threading.Lock()
        self._process_prefix = f"{os.getpid()}-{uuid.uuid4().hex}"
        self._counter = 0

    def next(self):
        with self._lock:
            self._counter += 1
            return f"{self._process_prefix}-{int(time.time_ns())}-{self._counter}"


class GroupThrottle:
    def __init__(self, second_limits):
        self._second_limits = dict(second_limits)
        self._lock = threading.Lock()
        self._window_start = {}
        self._count_in_window = {}

    def wait(self, group):
        second_limit = self._second_limits.get(group)
        if not second_limit:
            return

        while True:
            sleep_seconds = 0
            now = time.monotonic()
            with self._lock:
                current_window = int(now)
                if self._window_start.get(group) != current_window:
                    self._window_start[group] = current_window
                    self._count_in_window[group] = 0

                used = self._count_in_window[group]
                if used < second_limit:
                    self._count_in_window[group] = used + 1
                    return

                sleep_seconds = (current_window + 1) - now

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)


_nonce_generator = NonceGenerator()
_group_throttle = GroupThrottle(GROUP_SECOND_LIMITS)


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


def _auth_headers(query=None):
    if UPBIT_API_DEBUG:
        if query is None:
            query_summary = None
        elif len(str(query)) > 200:
            query_summary = f"{str(query)[:200]}...(len={len(str(query))})"
        else:
            query_summary = str(query)

        print(
            f"[UPBIT_API_DEBUG] AUTH_HEADERS query={query_summary} "
            f"query_hash_input_exists={query is not None}"
        )

    jwt_token = jwt.encode(get_payload(query), secret_key)
    return {"Authorization": f"Bearer {jwt_token}"}


def _mask_bearer_token(token):
    if not token:
        return token

    if not token.startswith("Bearer "):
        return "****"

    raw_token = token[7:]
    if not raw_token:
        return "Bearer ****"

    return f"Bearer ****{raw_token[-8:]}"


def _mask_headers_for_log(headers):
    masked = dict(headers or {})
    if "Authorization" in masked:
        masked["Authorization"] = _mask_bearer_token(masked["Authorization"])
    return masked


def _extract_upbit_error_payload(payload):
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return {
            "name": error.get("name"),
            "message": error.get("message"),
        }
    return payload


def _request(
    method,
    path,
    *,
    params=None,
    headers=None,
    timeout=TIMEOUT,
    group=API_GROUP_DEFAULT,
    max_retries=MAX_RATE_LIMIT_RETRIES,
):
    global _last_remaining_req

    merged_headers = dict(headers or {})

    for attempt in range(max_retries + 1):
        _group_throttle.wait(group)
        if UPBIT_API_DEBUG:
            print(
                f"[UPBIT_API_DEBUG] REQUEST method={method} path={path} url={server_url + path} "
                f"params={params} group={group} attempt={attempt} headers={_mask_headers_for_log(merged_headers)}"
            )

        response = _session.request(
            method=method,
            url=server_url + path,
            params=params,
            headers=merged_headers,
            timeout=timeout,
        )

        remaining_req = parse_remaining_req(response.headers.get("Remaining-Req"))
        _last_remaining_req = remaining_req

        if UPBIT_API_DEBUG:
            print(
                f"[UPBIT_API_DEBUG] RESPONSE method={method} path={path} status={response.status_code} "
                f"remaining_req={remaining_req}"
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text}

        if response.status_code in (429, 418):
            retry_after_header = response.headers.get("Retry-After")
            retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else None
            if attempt < max_retries:
                backoff_seconds = retry_after if retry_after is not None else DEFAULT_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(backoff_seconds)
                continue
            return _build_rate_limit_signal(response.status_code, payload, remaining_req, retry_after)

        if not 200 <= response.status_code < 300:
            if UPBIT_API_DEBUG:
                debug_header_keys = ("Remaining-Req", "Request-Id", "Date", "Content-Type", "Authorization")
                response_headers_for_log = {
                    key: response.headers.get(key)
                    for key in debug_header_keys
                    if response.headers.get(key) is not None
                }
                response_headers_for_log = _mask_headers_for_log(response_headers_for_log)

                print(
                    f"[UPBIT_API_DEBUG] ERROR method={method} path={path} group={group} attempt={attempt} "
                    f"status_code={response.status_code} payload={_extract_upbit_error_payload(payload)} "
                    f"headers={response_headers_for_log}"
                )
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
        'nonce': _nonce_generator.next(),
    }

    if UPBIT_API_DEBUG:
        nonce = payload['nonce']
        masked_nonce = f"{nonce[:18]}...{nonce[-8:]}" if len(nonce) > 32 else nonce
        print(
            f"[UPBIT_API_DEBUG] PAYLOAD_BASE nonce={masked_nonce} "
            f"query_provided={query is not None}"
        )

    if not query:
        if UPBIT_API_DEBUG:
            print("[UPBIT_API_DEBUG] PAYLOAD_HASH query_hash_present=False")
        return payload

    query_string = query if isinstance(query, str) else build_query_string(query)

    m = hashlib.sha512()
    m.update(query_string.encode())
    payload['query_hash'] = m.hexdigest()
    payload['query_hash_alg'] = 'SHA512'

    if UPBIT_API_DEBUG:
        query_summary = query_string if len(query_string) <= 200 else f"{query_string[:200]}...(len={len(query_string)})"
        print(
            f"[UPBIT_API_DEBUG] PAYLOAD_HASH query_hash_present=True "
            f"query_string={query_summary} query_hash_prefix={payload['query_hash'][:16]}"
        )

    return payload


def get_accounts():
    return _request("GET", "/v1/accounts", headers=_auth_headers())


def get_markets():
    querystring = {"isDetails": "false"}
    return _request("GET", "/v1/market/all", params=querystring)


def get_ticker(markets):
    querystring = {"markets": markets}
    return _request("GET", "/v1/ticker", params=querystring)


def load_default_krw_universe(excluded_keywords=None):
    from core.universe import collect_krw_markets

    markets = get_markets()
    return collect_krw_markets(markets, excluded_keywords or [])


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


def orders(market="KRW-BTC", side="bid", volume=0.01, price=100.0, ord_type="limit", identifier=None):
    query = {
        'market': market,
        'side': side,
        'ord_type': ord_type,
    }

    if volume > 0:
        query['volume'] = str(volume)

    if price > 0:
        query['price'] = str(price)

    if identifier:
        query['identifier'] = str(identifier)

    query_string = build_query_string(query)

    return _request(
        "POST",
        "/v1/orders",
        params=query,
        headers=_auth_headers(query_string),
        group=API_GROUP_ORDER,
    )


# 시장가 매수
def bid_price(market="KRW-BTC", price=100.0, identifier=None):
    return orders(market, "bid", 0, price, "price", identifier=identifier)


# 시장가 매도
def ask_market(market="KRW-BTC", volumn=1.0, identifier=None):
    return orders(market, "ask", volumn, 0, "market", identifier=identifier)


def get_open_orders(market=None, states=("wait", "watch")):
    query = {}
    if market:
        query["market"] = market
    if states:
        query["states[]"] = list(states)

    query_string = build_query_string(query) if query else None
    if UPBIT_API_DEBUG:
        print(
            f"[UPBIT_API_DEBUG] OPEN_ORDERS query={query or None} "
            f"query_string={query_string}"
        )

    return _request(
        "GET",
        "/v1/orders/open",
        params=query or None,
        headers=_auth_headers(query_string),
        group=API_GROUP_ORDER,
    )
