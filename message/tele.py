import os

import telegram


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "Set it before starting the application."
        )
    return value


telgm_token = _get_required_env("TELEGRAM_BOT_TOKEN")
chat_id = _get_required_env("TELEGRAM_CHAT_ID")

bot = telegram.Bot(token=telgm_token)


def sendMessage(msg):
    bot.sendMessage(chat_id=chat_id, text=msg)
