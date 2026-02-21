import queue
import unittest

from infra.upbit_ws_client import UpbitWebSocketClient


class DummyWebSocketApp:
    def __init__(self):
        self.sent_messages = []

    def send(self, payload):
        self.sent_messages.append(payload)


class UpbitWebSocketClientTest(unittest.TestCase):
    def test_subscriptions_are_restored_on_reconnect(self):
        client = UpbitWebSocketClient(default_format="SIMPLE")
        dummy_ws = DummyWebSocketApp()
        client._ws_app = dummy_ws
        client._ensure_monitor_thread = lambda: None

        client.subscribe("ticker", ["KRW-BTC"], data_format="SIMPLE_LIST")
        self.assertEqual(dummy_ws.sent_messages, [])

        client._on_open(dummy_ws)
        self.assertEqual(len(dummy_ws.sent_messages), 1)
        self.assertIn('"format": "SIMPLE_LIST"', dummy_ws.sent_messages[0])

    def test_message_is_dispatched_to_callback_and_queue(self):
        received = []
        message_queue = queue.Queue()
        client = UpbitWebSocketClient(on_message=received.append, message_queue=message_queue)

        payload = b'{"type":"ticker","code":"KRW-BTC"}'
        client._on_message(None, payload)

        self.assertEqual(received[0]["code"], "KRW-BTC")
        queued = message_queue.get_nowait()
        self.assertEqual(queued["type"], "ticker")


if __name__ == "__main__":
    unittest.main()
