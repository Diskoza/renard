"""Tools over agent/app_manuals.py: what an app is for and how to drive it; which apps he has; learn an app's window."""
import asyncio

from . import S, tool


@tool("app_guide",
      "Инструкция по программе пользователя ПЕРЕД работой в ней: для чего она, горячие клавиши, как сделать типичные "
      "задачи твоими инструментами, какие кнопки есть в её окне (запомнено) и что уже получалось раньше. "
      "app — название (хром, телеграм, gimp, packet tracer, ведьмак…)", {"app": S}, ["app"])
def app_guide(app: str) -> str:
    from .. import app_manuals
    return app_manuals.guide(app)


@tool("apps_overview", "Какие программы и игры установлены у пользователя, по типам (браузер, мессенджер, игра, IDE, офис…). "
      "category — только один тип (игра, офис, терминал…), пусто = все", {"category": S}, [])
def apps_overview(category: str = "") -> str:
    from .. import app_manuals
    return app_manuals.overview(category)


@tool("app_do",
      "СДЕЛАТЬ ЗАДАЧУ В ЛЮБОЙ ПРОГРАММЕ самому, шаг за шагом (смотрит на окно, нажимает, вводит, читает, проверяет). "
      "app — программа (steam, gimp, hydra, discord, проводник…), goal — что сделать или узнать, подробно и дословно "
      "(«найди в библиотеке Stardew Valley и открой страницу игры», «прочитай последние сообщения в канале general»). "
      "Рискованный последний шаг (отправить, удалить, купить, установить) он не делает сам — попросит «да». "
      "Удачные задачи запоминает и в следующий раз делает быстрее.", {"app": S, "goal": S}, ["app", "goal"])
async def app_do(app: str, goal: str, ctx: dict | None = None) -> str:
    from .. import app_operator
    return await app_operator.app_do(app, goal, ctx or {})


@tool("app_do_confirm", "Выполнить рискованный шаг, на котором остановился app_do (после «да» пользователя)",
      {"token": S}, ["token"])
async def app_do_confirm(token: str) -> str:
    from .. import app_manuals, app_operator
    p = dict(app_operator.PENDING.get(token) or {})
    res = await asyncio.to_thread(app_operator.finish, token)
    if p and res.startswith("Готово"):
        a = p.get("action", {})
        app_manuals.add_recipe_lines(p.get("key") or p.get("app"), p.get("goal", ""),
                                     list(p.get("steps", [])) + [f"{a.get('action')} {a.get('keys') or a.get('text') or ''} (после «да»)"])
    return res


@tool("app_learn",
      "Изучить окно программы: открыть её (если закрыта), прочитать кнопки/меню/поля и запомнить (потом app_guide их "
      "показывает). Открытую ради изучения программу закрывает обратно. Игры не изучает.", {"app": S}, ["app"])
async def app_learn(app: str) -> str:
    from .. import app_manuals
    from .apps import _app_ui, find_window, u32
    from .pc import open_app
    disp, entry = app_manuals.find(app)
    if app_manuals.category(entry, disp) == "игра":
        return f"{disp} — игра: внутри игр кнопок для UI Automation нет, изучать нечего. Запуск — open_app."
    from .apps import list_wins
    opened = False
    w = find_window(app) or find_window(disp)
    if not w:
        before = {x["hwnd"] for x in list_wins()}
        res = await open_app(disp)
        if res.startswith("Не "):
            return res
        opened = True
        for _ in range(30):
            await asyncio.sleep(0.5)
            new = [x for x in list_wins() if x["hwnd"] not in before and x["title"].strip()]
            w = find_window(app) or find_window(disp) or (new[0] if new else None)
            if w:
                break
        if not w:
            return f"{res} Но окно не появилось за 15 с — изучу, когда откроешь её сам («изучи {app}»)."
        if u32.IsIconic(w["hwnd"]):
            u32.ShowWindow(w["hwnd"], 9)
        await asyncio.sleep(2.0)
    res = await _app_ui(w["title"], "read", "", "", False, False)
    if opened:
        u32.PostMessageW(w["hwnd"], 0x0010, 0, 0)
    n = res.count("\n")
    return (f"Изучил окно «{disp}» ({n} элементов), запомнил кнопки и меню." + (" Окно закрыл обратно." if opened else "") +
            "\n" + "\n".join(res.splitlines()[:40]))
