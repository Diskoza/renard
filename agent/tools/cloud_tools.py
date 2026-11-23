"""ask_cloud: the local model hands a task it cannot do well to the strong cloud model he chose (agent/cloud.py)."""
from .. import cloud
from . import S, tool


def _context(ctx: dict | None) -> str:
    said = ((ctx or {}).get("user_text") or "").strip()
    return f"Пользователь сказал дословно: «{said[:2000]}»" if said else ""


@tool("ask_cloud",
      "Передать ТРУДНУЮ задачу сильной облачной модели (Claude и т.п.), если сам не справишься: большой/сложный код, "
      "архитектура, длинный разбор, сложная математика, важный текст. task — задача целиком, со всеми деталями и "
      "данными (облако не видит этот разговор). Простое делай сам. Ответ облака передай пользователю как есть.",
      {"task": S}, ["task"])
async def ask_cloud(task: str, ctx: dict | None = None) -> str:
    st = cloud.status()
    if st["permission"] == "off":
        return "Облачные модели выключены в настройках (ИИ → Облачные модели). Сделай задачу сам, как сможешь."
    if not st["provider"] or not st["model"]:
        return "Облачная модель не выбрана (ИИ → Облачные модели). Сделай задачу сам."
    if not st["has_key"]:
        return f"Нет ключа для {st['provider']} (ИИ → Облачные модели). Сделай задачу сам."
    if st["permission"] == "ask":
        tok = cloud.new_pending(task, _context(ctx))
        return (f"Нужно разрешение. Коротко спроси пользователя: «Это сложно — спросить у {st['model']}? Задача уйдёт в "
                f"интернет.» Если он скажет «да» — вызови ask_cloud_confirm(token=\"{tok}\"). Если «нет» — сделай сам.")
    try:
        return await cloud.ask(task, _context(ctx))
    except Exception as e:
        return f"Облако не ответило: {e}. Сделай задачу сам, как сможешь."


@tool("ask_cloud_confirm", "Отправить задачу в облако после «да» пользователя (token из ask_cloud)", {"token": S}, ["token"])
async def ask_cloud_confirm(token: str) -> str:
    p = cloud.PENDING.pop((token or "").strip().strip('"'), None)
    if not p:
        return "Нет такой ожидающей задачи (или уже отправлена). Вызови ask_cloud заново."
    try:
        return await cloud.ask(p["task"], p["context"])
    except Exception as e:
        return f"Облако не ответило: {e}. Сделай задачу сам, как сможешь."
