import queue
import unittest
from unittest.mock import Mock, patch

from infra.upbit_broker import UpbitAuthorizationError, UpbitLiveAuthorization
from infra.upbit_ws_client import UpbitWebSocketClient


class DummyWebSocketApp:
    def __init__(self):
        self.sent_messages = []

    def send(self, payload):
        self.sent_messages.append(payload)


class PrivateAwareClient(UpbitWebSocketClient):
    def __init__(self):
        super().__init__(
            authorization=UpbitLiveAuthorization(),
            auth_headers_provider=lambda: {"Authorization": "Bearer test-token"},
        )


class UpbitWebSocketClientTest(unittest.TestCase):
    def test_subscriptions_are_restored_on_reconnect(self):
        client = UpbitWebSocketClient(
            authorization=UpbitLiveAuthorization(), default_format="SIMPLE"
        )
        dummy_ws = DummyWebSocketApp()
        client._ws_app = dummy_ws
        client._ensure_monitor_thread = lambda: None

        client.subscribe("ticker", ["KRW-BTC"], data_format="SIMPLE_LIST")
        self.assertEqual(dummy_ws.sent_messages, [])

        client._on_open(dummy_ws)
        self.assertEqual(len(dummy_ws.sent_messages), 1)
        self.assertIn('"format": "SIMPLE_LIST"', dummy_ws.sent_messages[0])

    def test_unauthorized_connect_does_not_construct_or_run_websocket_client(self):
        with patch("infra.upbit_ws_client.threading.Thread") as thread_constructor:
            with self.assertRaises(UpbitAuthorizationError):
                client = UpbitWebSocketClient()
                client.connect()

        thread_constructor.assert_not_called()

    def test_authorized_connect_starts_mocked_connection_thread(self):
        with patch("infra.upbit_ws_client.threading.Thread") as thread_constructor:
            client = UpbitWebSocketClient(authorization=UpbitLiveAuthorization())
            client.connect()

        thread_constructor.assert_called_once_with(
            target=client._run_connection_loop, daemon=True
        )
        thread_constructor.return_value.start.assert_called_once_with()

    def test_private_auth_rechecks_authorization_before_provider(self):
        provider = Mock(return_value={"Authorization": "Bearer test-token"})
        client = UpbitWebSocketClient(
            authorization=UpbitLiveAuthorization(),
            auth_headers_provider=provider,
        )
        client._authorization = None

        with self.assertRaises(UpbitAuthorizationError):
            client._build_private_auth_payload()

        provider.assert_not_called()

    def test_message_is_dispatched_to_callback_and_queue(self):
        received = []
        message_queue = queue.Queue()
        client = UpbitWebSocketClient(
            authorization=UpbitLiveAuthorization(),
            on_message=received.append,
            message_queue=message_queue,
        )

        payload = b'{"type":"ticker","code":"KRW-BTC"}'
        client._on_message(None, payload)

        self.assertEqual(received[0]["code"], "KRW-BTC")
        queued = message_queue.get_nowait()
        self.assertEqual(queued["type"], "ticker")

    def test_private_subscription_payload_contains_auth_token(self):
        client = PrivateAwareClient()
        payload = client._build_subscription_payload("myOrder", [], "SIMPLE", is_private=True)

        body = payload[1]
        self.assertEqual(body["type"], "myOrder")
        self.assertEqual(body["authorizationToken"], "Bearer test-token")
        self.assertNotIn("codes", body)

    def test_private_headers_are_built_when_private_subscription_exists(self):
        client = PrivateAwareClient()
        client.subscribe("myAsset", is_private=True)

        headers = client._build_ws_headers()
        self.assertEqual(headers, ["Authorization: Bearer test-token"])

    def test_private_endpoint_rejects_non_upbit_url_before_authentication(self):
        provider = Mock(return_value={"Authorization": "Bearer test-token"})

        with self.assertRaisesRegex(ValueError, "official Upbit"):
            UpbitWebSocketClient(
                authorization=UpbitLiveAuthorization(),
                private_ws_url="wss://attacker.example/websocket/v1/private",
                auth_headers_provider=provider,
            )

        provider.assert_not_called()

    def test_private_endpoint_recheck_precedes_bearer_header_creation(self):
        provider = Mock(return_value={"Authorization": "Bearer test-token"})
        client = UpbitWebSocketClient(
            authorization=UpbitLiveAuthorization(),
            auth_headers_provider=provider,
        )
        client.private_ws_url = "wss://attacker.example/websocket/v1/private"
        client._subscriptions[("myAsset", (), "SIMPLE", True)] = []

        with self.assertRaisesRegex(ValueError, "official Upbit"):
            client._build_ws_headers()

        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
