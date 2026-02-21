import os

import telegram

from message.notifier import Notifier


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "Set it before starting the application."
        )
    return value


class TelegramNotifier(Notifier):
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or _get_required_env("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or _get_required_env("TELEGRAM_CHAT_ID")
        self.bot = telegram.Bot(token=self.token)

    def send(self, message: str) -> None:
        self.bot.sendMessage(chat_id=self.chat_id, text=message)
