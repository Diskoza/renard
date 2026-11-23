"""Tools over agent/planner.py: tasks, notes, calendar, exchange rates, the plan of the day."""
from datetime import date, datetime, timedelta

from . import I, S, tool
from .. import planner as P
from ..logs import quiet


def _task_line(i: int, t: dict) -> str:
    due = ""
    if t.get("due"):
        dt = datetime.fromisoformat(t["due"])
        due = " — " + ("просрочено, " if dt.date() < date.today() and not t.get("done") else "") + P.human(dt, t.get("due_time"))
    return f"{i}. {'✓ ' if t.get('done') else ''}{t['text']}{due}"


@tool("tasks", "Список дел пользователя. action: add (text — что сделать; when — срок словами: «завтра в 18:00», «в пятницу»; "
      "в срок придёт напоминание) | list (scope: open — все открытые, today — на сегодня и просроченные, week, all) | "
      "done / undone (text — номер из списка или слова из задачи) | delete",
      {"action": S, "text": S, "when": S, "scope": S}, ["action"])
def tasks(action: str, text: str = "", when: str = "", scope: str = "open") -> str:
    a = (action or "").lower()
    if a in ("add", "create", "new"):
        if not text.strip():
            return "Что записать в дела?"
        t = P.add_task(text, when)
        due = P.human(datetime.fromisoformat(t["due"]), t["due_time"]) if t.get("due") else ""
        return f"Записал в дела: «{t['text']}»" + (f" — {due}" + (", напомню" if t.get("reminder") else "") if due else "") + "."
    if a in ("done", "complete", "check"):
        t = P.set_done(text, True)
        return f"Отметил: «{t['text']}» — сделано." if t else f"Не нашёл в делах «{text}»."
    if a in ("undone", "reopen"):
        t = P.set_done(text, False)
        return f"Вернул в дела: «{t['text']}»." if t else f"Не нашёл «{text}»."
    if a in ("delete", "remove"):
        t = P.delete("tasks", text)
        return f"Удалил из дел: «{t['text']}»." if t else f"Не нашёл «{text}»."
    items = P.tasks(scope or "open")
    if not items:
        return {"today": "На сегодня дел нет.", "week": "На неделю дел нет."}.get(scope, "Список дел пуст.")
    head = {"today": "Дела на сегодня", "week": "Дела на неделю", "all": "Все дела"}.get(scope, "Дела")
    return head + ":\n" + "\n".join(_task_line(i, t) for i, t in enumerate(items, 1))


@tool("notes", "Заметки пользователя (не путать с memory — это его записи: идеи, коды, списки). action: add (text, title) | "
      "list | search (text — что искать) | read (text — название/слова) | delete",
      {"action": S, "text": S, "title": S}, ["action"])
def notes(action: str, text: str = "", title: str = "") -> str:
    a = (action or "").lower()
    if a in ("add", "create", "new"):
        if not text.strip():
            return "Что записать?"
        n = P.add_note(text, title)
        return f"Записал заметку «{n['title']}»."
    if a in ("delete", "remove"):
        n = P.delete("notes", text)
        return f"Удалил заметку «{n['title']}»." if n else f"Не нашёл заметку «{text}»."
    found = P.notes(text if a in ("search", "read", "find") else "")
    if not found:
        return f"Заметок про «{text}» нет." if text else "Заметок пока нет."
    if a == "read" or (a == "search" and len(found) == 1):
        n = found[0]
        return n["text"] if n["text"].startswith(n["title"]) else f"{n['title']}\n\n{n['text']}"
    return "Заметки:\n" + "\n".join(f"{i}. {n['title']}" for i, n in enumerate(found[:20], 1))


@tool("calendar", "Календарь событий пользователя (встречи, созвоны, дни рождения). action: add (title; when — «завтра в 11:00»; "
      "minutes — длительность; place; remind_min — за сколько минут напомнить, по умолчанию 15) | list (days: 1 — сегодня, "
      "7 — неделя; start: today | tomorrow) | delete (title — слова из события)",
      {"action": S, "title": S, "when": S, "minutes": I, "place": S, "remind_min": I, "days": I, "start": S}, ["action"])
def calendar(action: str, title: str = "", when: str = "", minutes: int = 60, place: str = "", remind_min: int = 15,
             days: int = 7, start: str = "today") -> str:
    a = (action or "").lower()
    if a in ("add", "create", "new"):
        try:
            e = P.add_event(title, when, minutes, place, remind_min)
        except ValueError as ex:
            return str(ex)
        dt = datetime.fromisoformat(e["start"])
        return (f"Добавил в календарь: «{e['title']}» — {P.human(dt, not e['all_day'])}"
                + (f", {e['place']}" if e.get("place") else "")
                + (f". Напомню за {e['remind_min']} мин." if e.get("reminder") else "."))
    if a in ("delete", "remove", "cancel"):
        e = P.delete("events", title)
        return f"Убрал из календаря «{e['title']}»." if e else f"Не нашёл событие «{title}»."
    d0 = date.today() + timedelta(days=1 if (start or "").startswith(("tom", "завт")) else 0)
    evs = P.events(d0, max(1, int(days or 7)))
    if not evs:
        return "В календаре пусто." if days > 1 else "На этот день событий нет."
    return "Календарь:\n" + "\n".join(
        f"• {P.human(datetime.fromisoformat(e['start']), not e['all_day'])} — {e['title']}" + (f" ({e['place']})" if e.get("place") else "")
        for e in evs)


@tool("currency", "Курс валют и пересчёт (курсы Нацбанка Польши, обновляются каждый рабочий день). amount, from_cur, to_cur — "
      "коды или слова: USD, EUR, PLN, UAH, GBP… («доллар», «злотый»)", {"amount": {"type": "number"}, "from_cur": S, "to_cur": S},
      ["from_cur"])
def currency(from_cur: str, to_cur: str = "PLN", amount: float = 1) -> str:
    a, b = P.cur_code(from_cur), P.cur_code(to_cur or "PLN")
    if not a or not b:
        return f"Не знаю валюту «{from_cur if not a else to_cur}»."
    try:
        v, day = P.convert(float(amount or 1), a, b)
    except Exception as e:
        return f"Курс не получил: {e}"
    amt = float(amount or 1)
    return f"{amt:g} {a} = {v:,.2f} {b}".replace(",", " ") + f" (курс НБП на {day})"


@tool("day_plan", "План дня пользователя одним ответом: погода, события календаря, дела со сроком, напоминания. "
      "day: today | tomorrow. Для «какие планы», «что у меня сегодня», «доброе утро»", {"day": S}, [])
async def day_plan(day: str = "today", ctx: dict | None = None) -> str:
    from . import call
    d = date.today() + timedelta(days=1 if (day or "").startswith(("tom", "завт")) else 0)
    w = ""
    try:
        full = await call("weather", {"days": 2}, ctx or {})
        lines = full.split("\n")
        w = lines[0] if d == date.today() else next((x.lstrip("- ") for x in lines[1:] if "завтра" in x.lower()), lines[-1].lstrip("- "))
        w = "Погода: " + w
    except Exception:
        quiet()
    head = "Сегодня" if d == date.today() else "Завтра"
    return f"{head}, {P.RU_WD[d.weekday()]}, {d.day} {P.RU_MON[d.month - 1]}.\n\n" + P.day_text(d, w)
