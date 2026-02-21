from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    def send(self, message: str) -> None:
        ...
