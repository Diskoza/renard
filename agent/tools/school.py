"""School: substitutions and the class timetable from the school's public Optivum pages (no login), and the e-diary
(grades, tests, homework, attendance) through the local API of the «Mój plan» app (eduVULCAN), if installed.
Configure in config/settings.json: school.substitutions_url, school.timetable_url; prefs: school.class, school.group,
school.mojplan_repo."""
import datetime as dt
import html
import re
import time

import httpx

from . import S, tool

from ..config import SETTINGS

ZAST = SETTINGS.get("school", {}).get("substitutions_url", "")
PLAN = SETTINGS.get("school", {}).get("timetable_url", "")
UA = {"User-Agent": "Renard-local-assistant/1.0 (personal desktop assistant)"}
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
DAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_cache: dict[str, tuple[float, str]] = {}


def _cfg() -> tuple[str, str]:
    from ..prefs import get
    return (get("school.class", "") or "").upper().replace(" ", ""), str(get("school.group", "") or "")


async def _get(url: str, enc: str = "", ttl: int = 600) -> str:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    async with httpx.AsyncClient(headers=UA, timeout=15, follow_redirects=True) as c:
        r = await c.get(url)
    r.raise_for_status()
    text = r.content.decode(enc, "replace") if enc else r.text
    _cache[url] = (time.time(), text)
    return text


def _cells(row: str) -> list[str]:
    out = []
    for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row):
        c = re.sub(r"(?i)<br\s*/?>", "\n", c)
        c = html.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\xa0", " ")
        out.append("\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in c.split("\n")).strip())
    return out


def parse_substitutions(page: str) -> list[dict]:
    """[{date, weekday, notice, items: [{lesson, desc, sub, note, absent}]}] — by table structure, not CSS names
    (Optivum renumbers its classes on every export)."""
    days, cur, absent = [], None, ""
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page):
        cells = _cells(row)
        if not cells:
            continue
        if len(cells) == 1:
            m = re.search(r"Zastępstwa w dniu\s+(\d{2}\.\d{2}\.\d{4})\s*(\w+)?", cells[0])
            if m:
                lines = [l for l in cells[0].split("\n") if l.strip()][1:]
                notice = "\n".join(l for l in lines if not re.match(r"(?i)(publikacja|opublikowan|aktualizacja)", l))
                cur = {"date": m.group(1), "weekday": m.group(2) or "", "notice": notice, "items": []}
                days.append(cur)
            elif cells[0].strip():
                absent = cells[0].strip()
            continue
        if cur is None or len(cells) < 3 or [c.lower() for c in cells[:2]] == ["lekcja", "opis"]:
            continue
        if not re.match(r"^\d+$", cells[0].strip()):
            continue
        cur["items"].append({"lesson": int(cells[0]), "desc": cells[1], "sub": cells[2] if len(cells) > 2 else "",
                             "note": cells[3] if len(cells) > 3 else "", "absent": absent})
    return days


def _for_class(desc: str, klass: str) -> bool:
    """«3 B(2) - matematyka», «3B - …», «3 AB - wf» (joined classes) -> belongs to 3B?"""
    m = re.match(r"^\s*(\d)\s*([A-Z]+)", desc)
    return bool(m) and m.group(1) == klass[0] and klass[1:] in m.group(2)


async def substitutions(day: str = "") -> str:
    klass, group = _cfg()
    try:
        days = parse_substitutions(await _get(ZAST, "iso-8859-2", ttl=300))
    except Exception as e:
        return f"Не удалось открыть страницу замен ({type(e).__name__}): {ZAST}"
    if not days:
        return f"На странице замен сейчас ничего не опубликовано ({ZAST})."
    want = _day_date(day)
    out = []
    for d in days:
        if want and d["date"] != want.strftime("%d.%m.%Y"):
            continue
        mine = [i for i in d["items"] if _for_class(i["desc"], klass)]
        if group:
            mine = [i for i in mine if not re.search(r"\(\d\)", i["desc"]) or f"({group[0]})" in i["desc"]]
        head = f"Замены на {d['date']} ({d['weekday']}) для {klass}:"
        if mine:
            lines = [f"- урок {i['lesson']}: {i['desc']}" + (f" → {i['sub']}" if i["sub"] else "") +
                     (f" ({i['note']})" if i["note"] else "") + f" [нет: {i['absent']}]" for i in sorted(mine, key=lambda x: x["lesson"])]
            out.append(head + "\n" + "\n".join(lines))
        else:
            out.append(f"{head} нет (всего замен в школе: {len(d['items'])}).")
        if d["notice"]:
            out.append("Информация школы: " + d["notice"])
    if not out:
        dates = ", ".join(d["date"] for d in days)
        return f"На {want:%d.%m.%Y} замены ещё не опубликованы (есть на: {dates}). Обычно их выкладывают накануне после обеда."
    return "\n\n".join(out) + f"\n(источник: {ZAST})"


def _day_date(day: str) -> dt.date | None:
    t = (day or "").lower().strip()
    today = dt.date.today()
    if not t:
        return None
    if re.search(r"послезавтра|pojutrze", t):
        return today + dt.timedelta(days=2)
    if re.search(r"завтра|jutro|tomorrow", t):
        return today + dt.timedelta(days=1)
    if re.search(r"сегодня|dzi[sś]|today", t):
        return today
    for i, (ru, pl) in enumerate(zip(["понед", "вторн", "сред", "четв", "пятн", "субб", "воскр"],
                                     ["poniedz", "wtor", "środ", "czwart", "piąt", "sobot", "niedz"])):
        if ru in t or pl in t:
            return today + dt.timedelta(days=(i - today.weekday()) % 7 or 7)
    m = re.search(r"(\d{1,2})\.(\d{1,2})", t)
    if m:
        try:
            return dt.date(today.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


async def timetable(day: str = "") -> str:
    klass, group = _cfg()
    try:
        lista = await _get(PLAN + "lista.html", ttl=86400)
        m = re.search(r'href="(plany/o\d+\.html)"[^>]*>\s*' + re.escape(klass) + r"\b", lista)
        if not m:
            return f"Не нашёл класс {klass} в списке планов ({PLAN}lista.html)."
        page = await _get(PLAN + m.group(1), ttl=3600)
    except Exception as e:
        return f"Не удалось открыть план уроков ({type(e).__name__}): {PLAN}"
    when = _day_date(day) or dt.date.today()
    if when.weekday() > 4:
        return f"{when:%d.%m} — {DAYS_RU[when.weekday()]}, уроков нет."
    rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page.split('class="tabela"', 1)[-1])
    lessons = []
    for row in rows:
        cells = _cells(row)
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        cell = cells[2 + when.weekday()].strip()
        if not cell:
            continue
        parts = [p.strip() for p in cell.split("\n") if p.strip()]
        if group:
            keep = [p for p in parts if not re.search(r"-\d/\d", p) or f"-{group[0]}/" in p]
            parts = keep or parts
        lessons.append(f"- {cells[0]}. {cells[1].replace(' ', '')}: " + " | ".join(parts))
    if not lessons:
        return f"{klass}, {DAYS_RU[when.weekday()]} {when:%d.%m}: по плану уроков нет."
    return (f"План {klass} на {DAYS_RU[when.weekday()]} {when:%d.%m} (обычный план, без замен):\n" + "\n".join(lessons) +
            ("" if group else "\n(группа не указана: «-1/2» и «-2/2» — уроки разных групп; скажи свою группу — буду показывать только её)"))


MP_PORTS = (47173, 47174)
_mp = {"proc": None}


def _mp_paths() -> tuple[str, str, str]:
    import os
    import shutil
    from ..prefs import get
    repo = get("school.mojplan_repo", "") or ""
    data = os.path.expandvars(get("school.mojplan_data", r"%APPDATA%\moj-plan") or r"%APPDATA%\moj-plan")
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    return repo, data, node


async def _mp_alive(port: int) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"http://127.0.0.1:{port}/api/vulcan/status")
        return r.status_code == 200 and r.json().get("connected")
    except Exception:
        return False


async def mojplan_base() -> str:
    """URL of a running Mój plan API with a connected eduVULCAN account; starts the hidden copy if needed. '' = none."""
    import asyncio
    import os
    import subprocess
    for port in MP_PORTS:
        if await _mp_alive(port):
            return f"http://127.0.0.1:{port}"
    repo, data, node = _mp_paths()
    if not (os.path.isfile(os.path.join(repo, "server.js")) and os.path.isfile(os.path.join(data, "vulcan-session.json"))
            and os.path.isfile(node)):
        return ""
    env = {**os.environ, "PORT": str(MP_PORTS[1]), "MOJ_PLAN_DATA_DIR": data}
    _mp["proc"] = subprocess.Popen([node, "server.js"], cwd=repo, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=0x08000000)
    for _ in range(20):
        await asyncio.sleep(0.4)
        if await _mp_alive(MP_PORTS[1]):
            return f"http://127.0.0.1:{MP_PORTS[1]}"
    return ""


async def diary(kind: str, frm: dt.date | None = None, to: dt.date | None = None) -> tuple[list | None, str]:
    base = await mojplan_base()
    if not base:
        return None, ("Дневник недоступен: приложение «Mój plan» не подключено к eduVULCAN на этом ПК "
                      "(открой его и войди в eduVULCAN — дальше Renard берёт данные сам).")
    params = {}
    if frm:
        params = {"from": frm.isoformat(), "to": (to or frm).isoformat()}
    key = f"mp:{kind}:{params}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1], ""
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.get(f"{base}/api/vulcan/data/{kind}", params=params)
        d = r.json()
    except Exception as e:
        return None, f"Дневник не ответил ({type(e).__name__})."
    if r.status_code != 200:
        return None, f"Дневник: {d.get('error') or r.status_code}"
    _cache[key] = (time.time(), d.get("data") or [])
    return d.get("data") or [], ""


def _n(o, *path, default=""):
    for p in path:
        o = o.get(p) if isinstance(o, dict) else None
    return o if o not in (None, "") else default


def _d(s: str) -> str:
    try:
        x = dt.date.fromisoformat(str(s)[:10])
        return f"{DAYS_RU[x.weekday()][:2]} {x:%d.%m}"
    except ValueError:
        return str(s)[:10]


def _my_notes(rx: str) -> list[str]:
    """What he asked Renard to remember about tests etc. (notes.md) — the diary may not have it yet."""
    try:
        from ..config import MEMORY_DIR
        lines = (MEMORY_DIR / "notes.md").read_text(encoding="utf-8").splitlines()
        return [re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", l[2:]) for l in lines if l.startswith("- ") and re.search(rx, l, re.I)]
    except Exception:
        return []


async def exams(days: int = 30) -> str:
    today = dt.date.today()
    data, err = await diary("exams", today, today + dt.timedelta(days=days))
    notes = _my_notes(r"справдз|контрольн|kartk|sprawdz|тест|экзамен|egzamin")
    if data is None:
        return err + ("\n\nИз того, что ты просил запомнить:\n" + "\n".join(f"- {x}" for x in notes) if notes else "")
    rows = sorted(data, key=lambda e: str(e.get("DeadlineAt")))
    out = [f"- {_d(e.get('DeadlineAt'))}: {_n(e, 'Type')} — {_n(e, 'Subject', 'Name')}: {_n(e, 'Content')}"
           f" ({_n(e, 'Creator', 'DisplayName')})" for e in rows]
    text = (f"Контрольные/справдзианы/kartkówki на {days} дней (дневник):\n" + "\n".join(out)) if out else \
        f"В дневнике на ближайшие {days} дней контрольных нет."
    if notes:
        text += "\n\nТвои заметки:\n" + "\n".join(f"- {x}" for x in notes)
    return text


async def homework(days: int = 14) -> str:
    today = dt.date.today()
    data, err = await diary("homework", today - dt.timedelta(days=1), today + dt.timedelta(days=days))
    if data is None:
        return err
    rows = sorted(data, key=lambda e: str(e.get("DeadlineAt")))
    out = [f"- до {_d(e.get('DeadlineAt'))}: {_n(e, 'Subject', 'Name')} — {_n(e, 'Content', default='(без описания)')}" for e in rows]
    return ("Домашние задания (дневник):\n" + "\n".join(out)) if out else f"Домашних заданий в дневнике на {days} дней нет."


SUBJ_RU = {"матем": "matematyka", "алгебр": "matematyka", "геометр": "matematyka", "физик": "fizyka", "истори": "historia",
           "польск": "polski", "немец": "niemiecki", "англ": "angielski", "информат": "informatyka", "географ": "geografia",
           "баз": "baz", "физкульт": "wychowanie fizyczne", "физ-ра": "wychowanie fizyczne", "физр": "wychowanie fizyczne",
           "религ": "religia", "хим": "chemia", "биолог": "biologia", "сайт": "witryny", "программир": "program",
           "веб": "aplikacji internetowych", "сет": "sieci"}


def _subj_match(asked: str, subj: str) -> bool:
    a = asked.lower().strip()
    for ru, pl in SUBJ_RU.items():
        if a.startswith(ru) or f" {ru}" in f" {a}":
            a = pl
            break
    s = subj.lower()
    return a[:5] in s or any(w[:5] in s for w in a.split() if len(w) >= 4)


async def grades(subject: str = "") -> str:
    data, err = await diary("grades")
    if data is None:
        return err
    by: dict[str, list] = {}
    for g in data:
        subj = _n(g, "Column", "Subject", "Name", default="?")
        if subject and not _subj_match(subject, subj):
            continue
        by.setdefault(subj, []).append(g)
    if not by:
        return f"Оценок{' по ' + subject if subject else ''} в этом семестре пока нет."
    out = []
    for subj, gs in sorted(by.items()):
        gs.sort(key=lambda g: str(g.get("CreatedAt")))
        vals = [(g.get("Value"), _n(g, "Column", "Weight", default=1)) for g in gs
                if isinstance(g.get("Value"), (int, float)) and 1 <= g.get("Value") <= 6]
        avg = sum(v * w for v, w in vals) / sum(w for _, w in vals) if vals and sum(w for _, w in vals) else None
        marks = ", ".join(f"{_n(g, 'Content')} ({_n(g, 'Column', 'Name', default=_n(g, 'Column', 'Category', 'Name'))[:28]}, "
                          f"{str(g.get('CreatedAt'))[8:10]}.{str(g.get('CreatedAt'))[5:7]})" for g in gs)
        out.append(f"- {subj}: {marks}" + (f" — средняя {avg:.2f}" if avg else ""))
    recent = sorted(data, key=lambda g: str(g.get("CreatedAt")), reverse=True)[:3]
    last = "; ".join(f"{_n(g, 'Content')} из {_n(g, 'Column', 'Subject', 'Name')} {str(g.get('CreatedAt'))[8:10]}.{str(g.get('CreatedAt'))[5:7]}"
                     for g in recent)
    return "Оценки за семестр (дневник):\n" + "\n".join(out) + (f"\nПоследние: {last}" if not subject else "")


async def my_day(day: str = "") -> str:
    """His own timetable from the diary: his groups only, substitutions and cancellations already applied."""
    when = _day_date(day) or dt.date.today()
    data, err = await diary("schedule", when, when)
    if data is None:
        return ""
    if not data:
        return f"{DAYS_RU[when.weekday()].capitalize()} {when:%d.%m}: уроков нет (дневник)."
    rows = []
    for l in sorted(data, key=lambda x: _n(x, "TimeSlot", "Position", default=0)):
        subj, teacher, room = _n(l, "Subject", "Name"), _n(l, "TeacherPrimary", "DisplayName"), _n(l, "Room", "Code")
        mark = ""
        sub, ch = l.get("Substitution"), l.get("Change")
        if isinstance(sub, dict):
            subj = _n(sub, "Subject", "Name", default=subj)
            teacher = _n(sub, "TeacherPrimary", "DisplayName", default=teacher)
            room = _n(sub, "Room", "Code", default=room)
            mark = " — ЗАМЕНА" + (f" ({_n(sub, 'Reason')})" if _n(sub, "Reason") else "")
        if isinstance(ch, dict):
            mark += " — ИЗМЕНЕНИЕ" + (f": {_n(ch, 'Reason') or _n(ch, 'Note') or _n(ch, 'Type')}" if (_n(ch, 'Reason') or _n(ch, 'Note') or _n(ch, 'Type')) else "")
        if l.get("Event"):
            mark += f" — {l['Event']}"
        rows.append(f"- {_n(l, 'TimeSlot', 'Position')}. {_n(l, 'TimeSlot', 'Display')}: {subj}, {teacher}, каб. {room}{mark}")
    return f"Твои уроки, {DAYS_RU[when.weekday()]} {when:%d.%m} (дневник, только твоя группа):\n" + "\n".join(rows)


async def my_week(next_week: bool = False) -> str:
    """Mon–Fri of this (or, at the weekend / when asked, the next) school week — one diary request."""
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    if next_week or today.weekday() >= 5:
        monday += dt.timedelta(days=7)
    out = []
    for i in range(5):
        d = await my_day((monday + dt.timedelta(days=i)).strftime("%d.%m.%Y"))
        if not d:
            return await timetable("")
        out.append(d.replace("Твои уроки, ", "").replace(" (дневник, только твоя группа)", ""))
    return f"Твоё расписание на неделю {monday:%d.%m}–{monday + dt.timedelta(days=4):%d.%m} (дневник, только твоя группа):\n\n" + "\n\n".join(out)


async def attendance(days: int = 30) -> str:
    today = dt.date.today()
    data, err = await diary("attendance", today - dt.timedelta(days=days), today)
    if data is None:
        return err
    absent = [a for a in data if _n(a, "PresenceType", "Absence") is True]
    late = [a for a in data if _n(a, "PresenceType", "Late") is True]
    unjust = [a for a in absent if not _n(a, "PresenceType", "AbsenceJustified") and not _n(a, "PresenceType", "LegalAbsence")]
    total = len([a for a in data if a.get("CalculatePresence")])
    pct = 100 * (total - len(absent)) / total if total else 0
    lines = [f"Посещаемость за {days} дней: {pct:.0f}% (уроков {total}, пропусков {len(absent)}, неоправданных {len(unjust)}, опозданий {len(late)})."]
    for a in unjust[:10]:
        lines.append(f"- {_d(a.get('DayAt'))} урок {a.get('LessonNumber') or _n(a, 'TimeSlot', 'Position')}: {_n(a, 'Subject', 'Name')} — {_n(a, 'PresenceType', 'Name')}")
    return "\n".join(lines)


@tool("school",
      "Школа пользователя — через приложение-дневник «Mój plan» (eduVULCAN, если установлено) и сайт школы (Optivum). "
      "action: substitutions (замены на день: его уроки из дневника + страница замен школы), timetable (его уроки на день), "
      "week (все уроки на неделю Пн–Пт; day=«следующая» — на следующую неделю), "
      "exams (контрольные, справдзианы, kartkówki на 30 дней + что он просил запомнить), homework (домашки), "
      "grades (оценки и средние; subject — предмет, если спросили про один), attendance (пропуски, опоздания). "
      "day: сегодня/завтра/день недели/дата. Сообщения дневника недоступны (нужен eduVULCAN premium).",
      {"action": S, "day": S, "subject": S}, [])
async def school(action: str = "substitutions", day: str = "", subject: str = "") -> str:
    a = (action or "substitutions").lower()
    if not (ZAST or PLAN) and a.startswith(("sub", "zast", "зам", "time", "plan", "week", "нед", "рас")):
        return ("Школа не настроена: укажи в config/settings.json school.substitutions_url и school.timetable_url "
                "(страницы Optivum своей школы) и в настройках school.class.")
    if a.startswith(("exam", "test", "spraw", "kartk")):
        return await exams()
    if a.startswith(("home", "zad", "дом")):
        return await homework()
    if a.startswith(("grade", "ocen", "оцен")):
        return await grades(subject)
    if a.startswith(("att", "frek", "проп")):
        return await attendance()
    if a.startswith("week") or re.search(r"(?i)недел|week|tydz|tydzień", day or ""):
        return await my_week("следующ" in (day or "").lower() or "next" in (day or "").lower())
    if a.startswith("time") or a in ("plan", "lessons"):
        mine = await my_day(day or "сегодня")
        return mine or await timetable(day)
    if a == "both":
        a, day = "substitutions", day or "завтра"
    mine = await my_day(day or "завтра")
    site = await substitutions(day)
    return (mine + "\n\n" + site) if mine else site
