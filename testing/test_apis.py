import importlib
import hashlib
import sys
import types
import unittest
from collections import OrderedDict
from unittest.mock import patch


class DummyResponse:
    def __init__(self, status_code=200, body=None, headers=None, text=""):
        self.status_code = status_code
        self._body = {"ok": True} if body is None else body
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._body


class ApiJwtNonceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules["jwt"] = types.SimpleNamespace(encode=lambda payload, secret: "")
        sys.modules["pandas"] = types.SimpleNamespace()
        fake_session = types.SimpleNamespace(request=lambda **kwargs: None)
        sys.modules["requests"] = types.SimpleNamespace(Session=lambda: fake_session)
        fake_constants = types.SimpleNamespace(
            ACCESS_KEY="test-access-key",
            SECRET_KEY="test-secret-key",
            SERVER_URL="https://example.com",
        )
        sys.modules["slave_constants"] = fake_constants
        cls.apis = importlib.import_module("apis")

    @staticmethod
    def _fake_encode(payload, _secret):
        return f"jwt-{payload['nonce']}"

    @patch("apis._session.request", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode)
    def test_get_accounts_generates_new_jwt_every_call(self, _mock_encode, mock_request):
        self.apis.get_accounts()
        self.apis.get_accounts()

        first_header = mock_request.call_args_list[0].kwargs["headers"]["Authorization"]
        second_header = mock_request.call_args_list[1].kwargs["headers"]["Authorization"]

        self.assertNotEqual(first_header, second_header)

    @patch("apis._session.request", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode)
    def test_orders_generates_new_jwt_every_call(self, _mock_encode, mock_request):
        self.apis.orders(market="KRW-BTC", side="bid", volume=0.1, price=1000, ord_type="limit")
        self.apis.orders(market="KRW-BTC", side="bid", volume=0.1, price=1000, ord_type="limit")

        first_header = mock_request.call_args_list[0].kwargs["headers"]["Authorization"]
        second_header = mock_request.call_args_list[1].kwargs["headers"]["Authorization"]

        self.assertNotEqual(first_header, second_header)

    def test_build_query_string_with_list_values(self):
        params = OrderedDict([
            ("market", "KRW-BTC"),
            ("states[]", ["wait", "watch"]),
            ("limit", 10),
        ])

        query_string = self.apis.build_query_string(params)

        self.assertEqual(query_string, "market=KRW-BTC&states[]=wait&states[]=watch&limit=10")

    def test_build_query_string_with_repeated_keys_tuple_list(self):
        params = [
            ("pairs", "KRW-BTC"),
            ("pairs", "KRW-ETH"),
            ("cursor", "abc123"),
        ]

        query_string = self.apis.build_query_string(params)

        self.assertEqual(query_string, "pairs=KRW-BTC&pairs=KRW-ETH&cursor=abc123")

    def test_get_payload_query_hash_matches_fixed_vector(self):
        query_string = "market=KRW-BTC&states[]=wait&states[]=watch&limit=10"

        payload = self.apis.get_payload(query_string)

        self.assertEqual(
            payload["query_hash"],
            "e3cfc649139c595e1c26a8aa2b3c8504f4b15011fc2b819081451e5e845172bd5dbbb5110ec5d7a3d1d32ff71f46a78323a040e8bedf8672021fd2206190a3a8",
        )
        self.assertEqual(payload["query_hash_alg"], "SHA512")

    @patch("apis._session.request", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode)
    def test_orders_hash_input_uses_build_query_string(self, mock_encode, _mock_request):
        self.apis.orders(market="KRW-BTC", side="bid", volume=0.1, price=1000, ord_type="limit")

        payload_arg = mock_encode.call_args.args[0]
        expected_query = "market=KRW-BTC&side=bid&ord_type=limit&volume=0.1&price=1000"
        expected_hash = hashlib.sha512(expected_query.encode()).hexdigest()

        self.assertEqual(payload_arg["query_hash"], expected_hash)

    @patch("apis._session.request", return_value=DummyResponse(headers={"Remaining-Req": "group=market; min=59; sec=9"}))
    def test_request_parses_remaining_req_header(self, _mock_request):
        self.apis.get_markets()

        self.assertEqual(
            self.apis.get_last_remaining_req(),
            {"group": "market", "min": 59, "sec": 9},
        )

    @patch("apis._session.request", return_value=DummyResponse(status_code=429, body={"error": "too_many"}))
    def test_request_returns_rate_limit_signal(self, _mock_request):
        response = self.apis.get_markets()

        self.assertFalse(response["ok"])
        self.assertEqual(response["status_code"], 429)
        self.assertEqual(response["error_type"], "rate_limit")

    @patch("apis._session.request", return_value=DummyResponse(status_code=500, body={"error": "oops"}))
    def test_request_raises_api_request_error_for_non_2xx(self, _mock_request):
        with self.assertRaises(self.apis.ApiRequestError) as context:
            self.apis.get_markets()

        self.assertEqual(context.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
