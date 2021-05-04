import telegram

telgm_token = '1783738726:AAGY3JoTBqkVxon9XK15drNJfDgJpS4a3P4'
chat_id = '-1001190314566'

bot = telegram.Bot(token=telgm_token)


def sendMessage(msg):
    bot.sendMessage(chat_id=chat_id, text=msg)

