import importlib
import hashlib
import os
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
        sys.modules["jwt"] = types.SimpleNamespace(encode=lambda payload, secret, algorithm=None: "")
        sys.modules["pandas"] = types.SimpleNamespace()
        fake_session = types.SimpleNamespace(request=lambda **kwargs: None)
        sys.modules["requests"] = types.SimpleNamespace(Session=lambda: fake_session)
        fake_constants = types.SimpleNamespace(
            ACCESS_KEY="test-access-key",
            SECRET_KEY="test-secret-key",
            SERVER_URL="https://example.com",
        )
        sys.modules["slave_constants"] = fake_constants
        cls.apis = cls._reload_apis_module(debug_env="0")

    @classmethod
    def _reload_apis_module(cls, debug_env=None):
        if debug_env is None:
            os.environ.pop("UPBIT_API_DEBUG", None)
        else:
            os.environ["UPBIT_API_DEBUG"] = debug_env

        sys.modules.pop("apis", None)
        return importlib.import_module("apis")

    @staticmethod
    def _fake_encode(payload, _secret, algorithm=None):
        return f"jwt-{payload['nonce']}"

    @staticmethod
    def _fake_encode_bytes(payload, _secret, algorithm=None):
        return f"jwt-{payload['nonce']}".encode("utf-8")

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

    def test_get_payload_nonce_is_uuid_v4_length(self):
        payload = self.apis.get_payload()

        self.assertEqual(len(payload["nonce"]), 36)
        self.assertEqual(payload["nonce"].count("-"), 4)

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
        self.assertEqual(payload_arg["query_hash_alg"], "SHA512")
        self.assertEqual(mock_encode.call_args.kwargs["algorithm"], "HS512")

    @patch("apis._session.request", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode_bytes)
    def test_get_accounts_decodes_jwt_bytes_and_uses_hs512(self, mock_encode, mock_request):
        self.apis.get_accounts()

        auth_header = mock_request.call_args.kwargs["headers"]["Authorization"]

        self.assertTrue(auth_header.startswith("Bearer jwt-"))
        self.assertEqual(mock_encode.call_args.kwargs["algorithm"], "HS512")


    @patch("apis._session.request", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode)
    def test_orders_include_identifier_in_query_hash(self, mock_encode, _mock_request):
        self.apis.orders(
            market="KRW-BTC",
            side="bid",
            volume=0.1,
            price=1000,
            ord_type="limit",
            identifier="engine-1",
        )

        payload_arg = mock_encode.call_args.args[0]
        expected_query = "market=KRW-BTC&side=bid&ord_type=limit&volume=0.1&price=1000&identifier=engine-1"
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

    @patch("builtins.print")
    def test_request_debug_log_disabled_by_default(self, mock_print):
        apis = self._reload_apis_module(debug_env="0")
        with patch("apis._session.request", return_value=DummyResponse()):
            response = apis.get_markets()

        self.assertEqual(response, {"ok": True})
        mock_print.assert_not_called()

    @patch("builtins.print")
    def test_request_debug_log_enabled_and_authorization_masked(self, mock_print):
        apis = self._reload_apis_module(debug_env="yes")
        with patch("apis.jwt.encode", return_value="abcdefghijklmnopqrstuvwxyz0123456789"):
            with patch("apis._session.request", return_value=DummyResponse(headers={"Remaining-Req": "group=order; min=59; sec=8"})):
                response = apis.get_accounts()

        self.assertEqual(response, {"ok": True})
        printed_messages = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn("[UPBIT_API_DEBUG] REQUEST", printed_messages)
        self.assertIn("[UPBIT_API_DEBUG] RESPONSE", printed_messages)
        self.assertIn("Authorization': 'Bearer ****23456789", printed_messages)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", printed_messages)

    def test_request_behavior_unchanged_when_debug_enabled(self):
        apis = self._reload_apis_module(debug_env="true")

        with patch("apis._session.request", return_value=DummyResponse(status_code=500, body={"error": "oops"})):
            with self.assertRaises(apis.ApiRequestError) as context:
                apis.get_markets()

        self.assertEqual(context.exception.status_code, 500)

    @patch("apis.time.sleep")
    @patch("apis.time.monotonic", side_effect=[10.10, 11.05])
    def test_group_throttle_strengthens_when_remaining_sec_is_zero(self, _mock_monotonic, mock_sleep):
        throttle = self.apis.GroupThrottle({"order": 10})
        throttle.update_remaining("order", {"group": "order", "sec": 0}, observed_at=10.0)

        throttle.wait("order")

        self.assertEqual(mock_sleep.call_count, 1)
        self.assertAlmostEqual(mock_sleep.call_args.args[0], 0.9, places=2)

    @patch("apis.time.sleep")
    @patch("apis.time.monotonic", return_value=20.10)
    def test_group_throttle_relaxes_when_remaining_sec_is_high(self, _mock_monotonic, mock_sleep):
        throttle = self.apis.GroupThrottle({"order": 10})
        throttle.update_remaining("order", {"group": "order", "sec": 8}, observed_at=20.0)

        throttle.wait("order")

        mock_sleep.assert_not_called()

    @patch("apis._session.request", return_value=DummyResponse(headers={"Remaining-Req": "group=order; min=59; sec=6"}))
    def test_request_stores_remaining_req_by_group(self, _mock_request):
        self.apis.get_accounts()

        self.assertEqual(
            self.apis.get_remaining_req_by_group("order"),
            {"group": "order", "min": 59, "sec": 6},
        )

    @patch("apis.time.sleep")
    @patch("apis._session.request", return_value=DummyResponse(status_code=429, body={"error": "too_many"}))
    def test_429_opens_group_circuit_breaker(self, _mock_request, _mock_sleep):
        self.apis.get_accounts()

        self.assertGreater(self.apis._group_throttle._circuit_open_until.get("default", 0), 0)


if __name__ == "__main__":
    unittest.main()
