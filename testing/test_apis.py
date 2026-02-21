import importlib
import sys
import types
import unittest
from unittest.mock import patch


class DummyResponse:
    def json(self):
        return {"ok": True}


class ApiJwtNonceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules["jwt"] = types.SimpleNamespace(encode=lambda payload, secret: "")
        sys.modules["pandas"] = types.SimpleNamespace()
        sys.modules["requests"] = types.SimpleNamespace(get=None, post=None)
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

    @patch("apis.requests.get", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode)
    def test_get_accounts_generates_new_jwt_every_call(self, _mock_encode, mock_get):
        self.apis.get_accounts()
        self.apis.get_accounts()

        first_header = mock_get.call_args_list[0].kwargs["headers"]["Authorization"]
        second_header = mock_get.call_args_list[1].kwargs["headers"]["Authorization"]

        self.assertNotEqual(first_header, second_header)

    @patch("apis.requests.post", return_value=DummyResponse())
    @patch("apis.jwt.encode", side_effect=_fake_encode)
    def test_orders_generates_new_jwt_every_call(self, _mock_encode, mock_post):
        self.apis.orders(market="KRW-BTC", side="bid", volume=0.1, price=1000, ord_type="limit")
        self.apis.orders(market="KRW-BTC", side="bid", volume=0.1, price=1000, ord_type="limit")

        first_header = mock_post.call_args_list[0].kwargs["headers"]["Authorization"]
        second_header = mock_post.call_args_list[1].kwargs["headers"]["Authorization"]

        self.assertNotEqual(first_header, second_header)


if __name__ == "__main__":
    unittest.main()
