"""Activity log tools: time spent in apps, «что я делал», habits («как обычно»)."""
from . import S, tool


@tool("activity_report", "Сколько времени пользователь провёл в программах/играх. period: today | yesterday | week; "
                         "app — конкретная программа (пусто = общий список)", {"period": S, "app": S}, [])
def activity_report(period: str = "today", app: str = "") -> str:
    from ..activity import report
    return report(period, app)


@tool("routine", "Привычки пользователя: какие программы он обычно открывает в это время. action: suggest (показать) "
                 "или open (открыть «как обычно»)", {"action": S}, [])
async def routine(action: str = "suggest", ctx: dict | None = None) -> str:
    from ..activity import usual_apps
    from .apps import list_wins
    apps = usual_apps()
    if not apps:
        return ("Пока не знаю твоих привычек на это время: журнал активности копит данные, нужно несколько дней "
                "(программа считается привычкой, если открывалась в это время хотя бы 3 дня из 14).")
    running = {w["stem"] for w in list_wins()}
    todo = [a for a in apps if a["proc"] not in running and a["app"] not in ("Renard", "Проводник")]
    if action != "open":
        return "Обычно в это время ты открываешь: " + ", ".join(f"{a['app']} ({a['days']} дн.)" for a in apps) + (
            "" if todo else ". Всё уже открыто.")
    if not todo:
        return "Всё как обычно уже открыто: " + ", ".join(a["app"] for a in apps) + "."
    from .pc import open_app
    res = [await open_app(a["app"]) for a in todo[:5]]
    return "Открываю как обычно: " + " ".join(res)
