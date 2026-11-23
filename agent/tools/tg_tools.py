"""Send files to the user's Telegram (works from any interface once the bot is paired)."""
from . import S, tool
from .files import safe


@tool("send_file", "Отправить файл с ПК пользователю в Telegram («пришли мне файл …»). До 50 МБ", {"path": S, "caption": S}, ["path"])
async def send_file(path: str, caption: str = "") -> str:
    from .. import telegram_bot
    if not telegram_bot.BRIDGE:
        return "Telegram-бот не настроен. Открой окно Renard → плашка «TG» → вставь токен от @BotFather."
    return await telegram_bot.BRIDGE.send_file(str(safe(path)), caption)
