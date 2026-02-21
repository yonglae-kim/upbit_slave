from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict

if TYPE_CHECKING:
    import websocket


MessageHandler = Callable[[Dict[str, Any]], None]


class UpbitWebSocketClient:
    def __init__(
        self,
        *,
        ws_url: str = "wss://api.upbit.com/websocket/v1",
        ping_interval_seconds: int = 30,
        idle_timeout_seconds: int = 120,
        reconnect_delay_seconds: int = 3,
        default_format: str = "SIMPLE",
        on_message: MessageHandler | None = None,
        message_queue: queue.Queue[dict[str, Any]] | None = None,
    ):
        self.ws_url = ws_url
        self.ping_interval_seconds = ping_interval_seconds
        self.idle_timeout_seconds = idle_timeout_seconds
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.default_format = default_format
        self.on_message = on_message
        self.message_queue = message_queue

        self._lock = threading.Lock()
        self._subscriptions: dict[tuple[str, tuple[str, ...], str], list[dict[str, Any]]] = {}
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._last_message_ts = 0.0

        self._loop_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._ws_app: Any | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected_event.is_set()

    def connect(self) -> None:
        if self._loop_thread and self._loop_thread.is_alive():
            return

        self._stop_event.clear()
        self._loop_thread = threading.Thread(target=self._run_connection_loop, daemon=True)
        self._loop_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._connected_event.clear()

        ws_app = self._ws_app
        if ws_app:
            ws_app.close()

        if self._loop_thread:
            self._loop_thread.join(timeout=5)
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def subscribe(self, subscription_type: str, markets: list[str], data_format: str | None = None) -> None:
        payload = self._build_subscription_payload(subscription_type, markets, data_format)
        key = self._subscription_key(subscription_type, markets, data_format or self.default_format)

        with self._lock:
            self._subscriptions[key] = payload

        self._send_payload(payload)

    def _subscription_key(self, subscription_type: str, markets: list[str], data_format: str) -> tuple[str, tuple[str, ...], str]:
        return subscription_type, tuple(sorted(markets)), data_format

    def _build_subscription_payload(
        self,
        subscription_type: str,
        markets: list[str],
        data_format: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_format = data_format or self.default_format
        return [
            {"ticket": str(uuid.uuid4())},
            {"type": subscription_type, "codes": markets, "isOnlyRealtime": True},
            {"format": selected_format},
        ]

    def _run_connection_loop(self) -> None:
        while not self._stop_event.is_set():
            import websocket

            self._ws_app = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._ws_app.run_forever(skip_utf8_validation=True)

            if self._stop_event.is_set():
                break

            time.sleep(self.reconnect_delay_seconds)

    def _ensure_monitor_thread(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._monitor_thread = threading.Thread(target=self._monitor_connection, daemon=True)
        self._monitor_thread.start()

    def _monitor_connection(self) -> None:
        while not self._stop_event.is_set():
            if not self.is_connected:
                time.sleep(1)
                continue

            now = time.time()
            idle_seconds = now - self._last_message_ts
            if idle_seconds >= self.idle_timeout_seconds:
                ws_app = self._ws_app
                if ws_app:
                    ws_app.close()
                time.sleep(1)
                continue

            ws_app = self._ws_app
            if ws_app and ws_app.sock and ws_app.sock.connected:
                ws_app.sock.ping()

            time.sleep(self.ping_interval_seconds)

    def _on_open(self, ws_app: Any) -> None:
        self._connected_event.set()
        self._last_message_ts = time.time()

        self._ensure_monitor_thread()
        self._restore_subscriptions()

    def _on_message(self, ws_app: Any, message: bytes | str) -> None:
        self._last_message_ts = time.time()

        if isinstance(message, bytes):
            decoded = json.loads(message.decode("utf-8"))
        else:
            decoded = json.loads(message)

        if self.on_message:
            self.on_message(decoded)

        if self.message_queue:
            self.message_queue.put(decoded)

    def _on_error(self, ws_app: Any, error: Any) -> None:
        self._connected_event.clear()
        print("[UpbitWebSocketClient] error:", error)

    def _on_close(self, ws_app: Any, close_status_code: Any, close_msg: Any) -> None:
        self._connected_event.clear()

    def _restore_subscriptions(self) -> None:
        with self._lock:
            payloads = list(self._subscriptions.values())

        for payload in payloads:
            self._send_payload(payload)

    def _send_payload(self, payload: list[dict[str, Any]]) -> None:
        if not self.is_connected:
            return

        ws_app = self._ws_app
        if not ws_app:
            return

        ws_app.send(json.dumps(payload))
