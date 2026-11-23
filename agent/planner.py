"""Planner: tasks (to-do with a due date), notes and calendar events, all local (data/planner.json), plus exchange rates
and the «day» brief (weather + events + tasks + reminders). Due tasks / events become scheduler reminders, so they reach
him like any reminder (window, voice, Telegram).

Dates come in as he says them: «завтра в 11», «в пятницу в 18:00», «через 2 часа», «10 ноября», «15.11 в 9:30», ISO.
"""
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta

from .config import DATA_DIR
from .logs import quiet

PATH = DATA_DIR / "planner.json"
WD = {"понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресень": 6,
      "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
MONTHS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]
RU_WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
RU_MON = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _load() -> dict:
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    for k in ("tasks", "notes", "events"):
        d.setdefault(k, [])
    return d


def _save(d: dict):
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_when(s: str, now: datetime | None = None) -> tuple[datetime | None, bool]:
    """-> (datetime, has_time). None when nothing date-like is in the text."""
    now = now or datetime.now()
    t = (s or "").lower().replace("ё", "е").strip()
    if not t:
        return None, False
    try:
        dt = datetime.fromisoformat(t.replace("z", ""))
        return dt, bool(re.search(r"\d[t ]\d", t))
    except ValueError:
        pass
    m = re.search(r"через\s+(\d+|полчаса|час)\s*(минут\w*|мин|час\w*|ч|дн\w*|день|недел\w*)?", t)
    if m:
        n = 30 if m.group(1) == "полчаса" else 1 if m.group(1) == "час" else int(m.group(1))
        unit = m.group(2) or ("мин" if m.group(1) == "полчаса" else "час")
        delta = timedelta(minutes=n) if unit.startswith("мин") else timedelta(hours=n) if unit.startswith(("час", "ч")) \
            else timedelta(weeks=n) if unit.startswith("недел") else timedelta(days=n)
        if m.group(1) == "полчаса":
            delta = timedelta(minutes=30)
        return now + delta, not unit.startswith(("дн", "день", "недел"))
    day = None
    if "послезавтра" in t:
        day = now.date() + timedelta(days=2)
    elif "завтра" in t:
        day = now.date() + timedelta(days=1)
    elif "сегодня" in t or "вечером" in t or "утром" in t:
        day = now.date()
    if day is None:
        for k, wd in WD.items():
            if re.search(rf"\b{k}", t):
                ahead = (wd - now.weekday()) % 7 or 7
                if "следующ" in t and ahead < 7:
                    ahead += 7 if ahead <= 0 else 0
                day = now.date() + timedelta(days=ahead)
                break
    if day is None:
        m = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\w*", t)
        if m:
            mon = next(i for i, x in enumerate(MONTHS) if m.group(2).startswith(x)) + 1
            day = date(now.year, mon, int(m.group(1)))
            if day < now.date() - timedelta(days=1):
                day = day.replace(year=now.year + 1)
    dspan = (0, 0)
    if day is None:
        m = re.search(r"(?<!в )(?<!к )\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", t)
        if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
            y = int(m.group(3)) if m.group(3) else now.year
            y = y + 2000 if y < 100 else y
            try:
                day = date(y, int(m.group(2)), int(m.group(1)))
                dspan = m.span()
                if not m.group(3) and day < now.date() - timedelta(days=1):
                    day = day.replace(year=now.year + 1)
            except ValueError:
                day = None
    hh = mm = None
    m = next((x for x in re.finditer(r"\b(\d{1,2})[:.](\d{2})\b", t)
              if not (dspan[0] <= x.start() < dspan[1]) and int(x.group(1)) < 24 and int(x.group(2)) < 60), None)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if ("вечер" in t or "дня" in t) and hh < 12:
            hh += 12
    else:
        m = re.search(r"\b(?:в|к|на|до)\s+(\d{1,2})\s*(час\w*|утра|дня|вечера|ночи)?\b", t)
        if m:
            hh, mm = int(m.group(1)), 0
            if (m.group(2) in ("дня", "вечера") or "вечер" in t) and hh < 12:
                hh += 12
    if hh is None:
        if "утром" in t:
            hh, mm = 9, 0
        elif "вечером" in t:
            hh, mm = 19, 0
        elif "днем" in t or "днём" in t:
            hh, mm = 14, 0
    if day is None and hh is None:
        return None, False
    if day is None:
        day = now.date()
        if hh is not None and datetime.combine(day, datetime.min.time()).replace(hour=hh % 24, minute=mm or 0) < now:
            day += timedelta(days=1)
    if hh is None:
        return datetime.combine(day, datetime.min.time()), False
    return datetime.combine(day, datetime.min.time()).replace(hour=hh % 24, minute=mm or 0), True


def human(dt: datetime, has_time: bool = True) -> str:
    today = date.today()
    d = dt.date()
    dd = "сегодня" if d == today else "завтра" if d == today + timedelta(days=1) else \
        "вчера" if d == today - timedelta(days=1) else \
        (RU_WD[d.weekday()] if 0 < (d - today).days < 7 else f"{d.day} {RU_MON[d.month - 1]}")
    return f"{dd} в {dt:%H:%M}" if has_time else dd


def strip_when(text: str) -> str:
    """«купить хлеб завтра в 18:00» -> «купить хлеб»."""
    t = re.sub(r"(?i)\s*(\bв\s+)?(следующ\w+\s+)?\b(послезавтра|завтра|сегодня|утром|вечером|днем|днём|"
               r"понедельник|вторник|сред[уа]|четверг|пятниц[уа]|суббот[уа]|воскресенье)\b", " ", text)
    t = re.sub(r"(?i)\s*\bчерез\s+(\d+|полчаса|час)\s*(минут\w*|мин|час\w*|ч|дн\w*|день|недел\w*)?", " ", t)
    t = re.sub(r"(?i)\s*\b(в|к|на|до)?\s*\d{1,2}[:.]\d{2}\b", " ", t)
    t = re.sub(r"(?i)\s*\b(в|к|до)\s+\d{1,2}\s*(час\w*|утра|дня|вечера|ночи)?\b", " ", t)
    t = re.sub(r"(?i)\s*\b\d{1,2}\s+(" + "|".join(MONTHS) + r")\w*", " ", t)
    t = re.sub(r"(?i)\s*\b\d{1,2}\.\d{1,2}(\.\d{2,4})?\b", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,.-—")


def _remind(item: dict, at: datetime, text: str):
    from . import scheduler
    _unremind(item)
    if at <= datetime.now():
        return
    try:
        r = scheduler.upsert({"name": text[:40], "kind": "reminder", "prompt": text, "speak": True,
                              "when": f"once {at:%Y-%m-%d %H:%M}"})
        item["reminder"] = r["id"]
    except Exception:
        quiet()


def _unremind(item: dict):
    if item.get("reminder"):
        from . import scheduler
        try:
            scheduler.delete(item["reminder"])
        except Exception:
            quiet()
        item.pop("reminder", None)


def _find(items: list, key: str) -> dict | None:
    key = (key or "").strip().lower()
    if not key:
        return None
    hit = next((x for x in items if x["id"] == key), None)
    if hit:
        return hit
    if key.isdigit():
        n = int(key)
        live = [x for x in items if not x.get("done")]
        return live[n - 1] if 0 < n <= len(live) else None
    words = set(re.findall(r"\w{3,}", key))
    best, score = None, 0
    for x in items:
        w = set(re.findall(r"\w{3,}", (x.get("text") or x.get("title") or "").lower()))
        s = len(words & w) + (2 if key in (x.get("text") or x.get("title") or "").lower() else 0)
        if s > score:
            best, score = x, s
    return best


def add_task(text: str, when: str = "", remind: bool = True) -> dict:
    d = _load()
    dt, has_t = parse_when(when or text)
    title = strip_when(text) if not when else text.strip()
    item = {"id": uuid.uuid4().hex[:6], "text": title or text.strip(), "done": False, "created": time.time(),
            "due": dt.isoformat(timespec="minutes") if dt else None, "due_time": has_t}
    if dt and has_t and remind:
        _remind(item, dt - timedelta(minutes=0), f"Задача: {item['text']}")
    d["tasks"].append(item)
    _save(d)
    return item


def tasks(scope: str = "open") -> list[dict]:
    d = _load()
    out = [t for t in d["tasks"] if scope == "all" or not t.get("done")]
    today = date.today()
    if scope in ("today", "overdue"):
        out = [t for t in out if t.get("due") and datetime.fromisoformat(t["due"]).date() <= today]
    elif scope == "week":
        out = [t for t in out if not t.get("due") or datetime.fromisoformat(t["due"]).date() <= today + timedelta(days=7)]
    return sorted(out, key=lambda t: (t.get("due") or "9999", t["created"]))


def set_done(key: str, done: bool = True) -> dict | None:
    d = _load()
    t = _find([x for x in d["tasks"] if not x.get("done")] if done else d["tasks"], key)
    if t:
        t["done"] = done
        t["done_at"] = time.time() if done else None
        if done:
            _unremind(t)
        _save(d)
    return t


def delete(kind: str, key: str) -> dict | None:
    d = _load()
    x = _find(d[kind], key)
    if x:
        _unremind(x)
        d[kind].remove(x)
        _save(d)
    return x


def add_note(text: str, title: str = "") -> dict:
    d = _load()
    text = text.strip()
    title = title.strip() or (text.split("\n", 1)[0][:60])
    n = {"id": uuid.uuid4().hex[:6], "title": title, "text": text, "created": time.time(), "updated": time.time()}
    d["notes"].append(n)
    _save(d)
    return n


def notes(query: str = "") -> list[dict]:
    d = _load()
    q = (query or "").lower().strip()
    out = d["notes"]
    if q:
        words = set(re.findall(r"\w{3,}", q))
        out = [n for n in out if q in (n["title"] + " " + n["text"]).lower()
               or words & set(re.findall(r"\w{3,}", (n["title"] + " " + n["text"]).lower()))]
    return sorted(out, key=lambda n: -n["updated"])


def add_event(title: str, when: str = "", minutes: int = 60, place: str = "", remind_min: int = 15) -> dict:
    d = _load()
    dt, has_t = parse_when(when or title)
    if not dt:
        raise ValueError("не понял, когда — скажи день и время (например, «завтра в 11:00»)")
    name = title.strip() if when else strip_when(title)
    ev = {"id": uuid.uuid4().hex[:6], "title": name or title.strip(), "start": dt.isoformat(timespec="minutes"),
          "all_day": not has_t, "minutes": int(minutes or 60), "place": place.strip(), "remind_min": int(remind_min or 0),
          "created": time.time()}
    if has_t and ev["remind_min"] >= 0:
        rm = ev["remind_min"]
        soon = "сейчас" if not rm else f"через {rm} мин"
        _remind(ev, dt - timedelta(minutes=rm), f"{ev['title']} — {soon} ({dt:%H:%M})")
    d["events"].append(ev)
    _save(d)
    return ev


def events(day_from: date | None = None, days: int = 1) -> list[dict]:
    d = _load()
    a = day_from or date.today()
    b = a + timedelta(days=days)
    out = [e for e in d["events"] if a <= datetime.fromisoformat(e["start"]).date() < b]
    return sorted(out, key=lambda e: e["start"])


def upcoming(days: int = 7) -> list[dict]:
    return events(date.today(), days)


_RATES = {"t": 0, "rates": {}, "date": ""}
CUR = {"доллар": "USD", "бакс": "USD", "usd": "USD", "$": "USD", "евро": "EUR", "eur": "EUR", "€": "EUR",
       "злот": "PLN", "pln": "PLN", "zł": "PLN", "гривн": "UAH", "гривен": "UAH", "uah": "UAH", "фунт": "GBP", "gbp": "GBP",
       "франк": "CHF", "chf": "CHF", "рубл": "RUB", "rub": "RUB", "крон": "CZK", "czk": "CZK", "иен": "JPY", "йен": "JPY",
       "jpy": "JPY", "юан": "CNY", "cny": "CNY", "лир": "TRY", "try": "TRY"}


def cur_code(word: str) -> str:
    w = (word or "").lower().strip()
    if re.fullmatch(r"[a-z]{3}", w):
        return w.upper()
    return next((v for k, v in CUR.items() if w.startswith(k) or k == w), "")


def rates() -> dict:
    """PLN per 1 unit of each currency (NBP tables A + B), cached for 3 hours."""
    if time.time() - _RATES["t"] < 3 * 3600 and _RATES["rates"]:
        return _RATES
    import httpx
    out, day = {"PLN": 1.0}, ""
    for table in ("a", "b"):
        try:
            r = httpx.get(f"https://api.nbp.pl/api/exchangerates/tables/{table}/?format=json", timeout=10)
            j = r.json()[0]
            day = day or j.get("effectiveDate", "")
            for x in j["rates"]:
                out.setdefault(x["code"], float(x["mid"]))
        except Exception:
            continue
    if len(out) > 1:
        _RATES.update(t=time.time(), rates=out, date=day)
    return _RATES


def convert(amount: float, a: str, b: str) -> tuple[float, str]:
    r = rates()
    ra, rb = r["rates"].get(a), r["rates"].get(b)
    if not ra or not rb:
        raise ValueError(f"нет курса {a if not ra else b}")
    return amount * ra / rb, r["date"]


def today_short() -> str:
    """One line for the morning greeting: «Сегодня: созвон с Аней в 11:00, 2 дела.» ('' when the day is free)."""
    evs = events(date.today(), 1)
    tk = [t for t in tasks("open") if t.get("due") and datetime.fromisoformat(t["due"]).date() <= date.today()]
    parts = [f"{e['title']}" + ("" if e["all_day"] else f" в {datetime.fromisoformat(e['start']):%H:%M}") for e in evs[:2]]
    if len(evs) > 2:
        parts.append(f"ещё {len(evs) - 2} событ.")
    if tk:
        n = len(tk)
        parts.append(f"{n} {'дело' if n % 10 == 1 and n % 100 != 11 else 'дела' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'дел'}")
    return ("Сегодня: " + ", ".join(parts) + ".") if parts else ""


def day_text(day: date | None = None, weather: str = "") -> str:
    """«Погода и планы»: the morning / «что у меня сегодня» answer."""
    day = day or date.today()
    from . import scheduler
    lines = []
    if weather:
        lines.append(weather)
    evs = events(day, 1)
    if evs:
        lines.append("События:\n" + "\n".join(
            f"• {'весь день' if e['all_day'] else datetime.fromisoformat(e['start']).strftime('%H:%M')} — {e['title']}"
            + (f" ({e['place']})" if e.get("place") else "") for e in evs))
    tk = [t for t in tasks("open") if t.get("due") and datetime.fromisoformat(t["due"]).date() <= day]
    if tk:
        lines.append("Задачи:\n" + "\n".join(
            f"• {t['text']}" + (f" — до {datetime.fromisoformat(t['due']):%H:%M}" if t.get("due_time") and
                                 datetime.fromisoformat(t['due']).date() == day else
                                 " (просрочено)" if datetime.fromisoformat(t['due']).date() < day else "") for t in tk))
    nodue = [t for t in tasks("open") if not t.get("due")]
    if nodue:
        lines.append(f"Без срока: {len(nodue)} — " + "; ".join(t["text"] for t in nodue[:4]) + ("…" if len(nodue) > 4 else ""))
    start = datetime.combine(day, datetime.min.time()).timestamp()
    rem = [t for t in scheduler.all_tasks() if t.get("enabled") and t.get("next_run") and start <= t["next_run"] < start + 86400
           and t.get("kind") == "reminder" and not any(t["id"] == x.get("reminder") for x in evs + tk)]
    if rem:
        lines.append("Напоминания:\n" + "\n".join(
            f"• {datetime.fromtimestamp(t['next_run']):%H:%M} — {t.get('prompt') or t['name']}" for t in sorted(rem, key=lambda x: x['next_run'])))
    if len(lines) <= (1 if weather else 0):
        lines.append("Планов нет — свободный день.")
    return "\n\n".join(lines)
