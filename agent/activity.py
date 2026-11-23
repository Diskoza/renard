"""Activity log: which app is in front and for how long (local SQLite, nothing leaves the PC).

- «сколько я сегодня играл в War Thunder», «что я делал вчера», «статистика за неделю»
- habits: «как обычно» opens the apps you usually start around this time
- also remembers the window you work in (not Renard itself) -> «это окно» for the window / app tools
Cost: one Win32 call every 3 s.
"""
import ctypes
import sqlite3
import threading
import time
from collections import defaultdict
from ctypes import wintypes

import psutil

from .config import DATA_DIR
from .logs import quiet

DB = DATA_DIR / "activity.sqlite3"
u32 = ctypes.windll.user32
u32.GetForegroundWindow.restype = wintypes.HWND
IDLE_SEC = 300
NICE = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox", "telegram": "Telegram",
        "discord": "Discord", "steam": "Steam", "steamwebhelper": "Steam", "spotify": "Spotify", "code": "VS Code",
        "explorer": "Проводник", "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "notepad": "Блокнот",
        "aces": "War Thunder", "javaw": "Minecraft", "obs64": "OBS", "claude": "Claude", "windowsterminal": "Терминал",
        "pycharm64": "PyCharm", "taskmgr": "Диспетчер задач", "applicationframehost": ""}


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(li)
    u32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000


def _fullscreen(h) -> bool:
    r = wintypes.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
    sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
    return r.left <= 0 and r.top <= 0 and r.right >= sw and r.bottom >= sh


def _db():
    c = sqlite3.connect(DB, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS seg(app TEXT, proc TEXT, title TEXT, start REAL, end REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS opens(app TEXT, proc TEXT, ts REAL, day TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS seg_start ON seg(start)")
    return c


def app_name(proc: str, title: str) -> str:
    stem = proc.lower().removesuffix(".exe")
    if stem in NICE and NICE[stem]:
        return NICE[stem]
    if stem == "applicationframehost":
        return title.split(" - ")[-1][:40] or "Приложение"
    try:
        from .tools.system import apps_index
        for a in apps_index():
            if a.get("process", "").lower() == stem:
                return a["name"]
    except Exception:
        quiet()
    return proc.removesuffix(".exe") or "?"


class Tracker:
    def __init__(self):
        self.last_user_hwnd = None
        self.cur = None
        self.seen_today: set = set()
        self.day = ""
        self.started = False

    def start(self):
        if not self.started:
            self.started = True
            threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        db = _db()
        while True:
            try:
                self.tick(db)
            except Exception as e:
                print("activity:", e)
            time.sleep(3)

    def tick(self, db):
        now = time.time()
        day = time.strftime("%Y-%m-%d")
        if day != self.day:
            self.day = day
            self.seen_today = {r[0] for r in db.execute("SELECT DISTINCT app FROM opens WHERE day=?", (day,))}
        h = u32.GetForegroundWindow()
        if not h:
            return
        pid = wintypes.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value).name()
        except Exception:
            return
        n = u32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1); u32.GetWindowTextW(h, buf, n + 1)
        title = buf.value
        stem = proc.lower().removesuffix(".exe")
        cls = ctypes.create_unicode_buffer(64); u32.GetClassNameW(h, cls, 64)
        renard = stem in ("python", "pythonw") and title.startswith("Renard")
        if cls.value in ("RenardCompanionHost", "Shell_TrayWnd", "Progman", "WorkerW") or not title:
            renard = renard or cls.value == "RenardCompanionHost"
            if cls.value in ("Shell_TrayWnd", "Progman", "WorkerW"):
                self._close(db, now)
                return
        if not renard:
            self.last_user_hwnd = h
        idle = idle_seconds() > IDLE_SEC and not _fullscreen(h)
        if idle:
            self._close(db, now)
            return
        app = "Renard" if renard else app_name(proc, title)
        if self.cur and self.cur[0] == app and now - self.cur[4] < 12:
            self.cur[4] = now; self.cur[2] = title[:150]
            db.execute("UPDATE seg SET end=?, title=? WHERE rowid=?", (now, title[:150], self.cur[5])); db.commit()
            return
        self._close(db, now)
        cur = db.execute("INSERT INTO seg VALUES(?,?,?,?,?)", (app, stem, title[:150], now, now))
        self.cur = [app, stem, title[:150], now, now, cur.lastrowid]
        if app not in self.seen_today and app != "Renard":
            self.seen_today.add(app)
            db.execute("INSERT INTO opens VALUES(?,?,?,?)", (app, stem, now, day))
        db.commit()

    def _close(self, db, now):
        self.cur = None


TRACKER = Tracker()


def _fmt(sec: float) -> str:
    m = int(sec // 60)
    return f"{m // 60} ч {m % 60:02d} мин" if m >= 60 else f"{m} мин" if m else f"{int(sec)} с"


def period_bounds(period: str) -> tuple[float, float, str]:
    t = time.localtime()
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    p = (period or "today").lower()
    if p in ("yesterday", "вчера"):
        return midnight - 86400, midnight, "вчера"
    if p in ("week", "неделя", "7d"):
        return midnight - 6 * 86400, time.time(), "за 7 дней"
    return midnight, time.time(), "сегодня"


def report(period: str = "today", app: str = "") -> str:
    a, b, label = period_bounds(period)
    db = _db()
    rows = db.execute("SELECT app, proc, title, MAX(start, ?), MIN(end, ?) FROM seg WHERE end > ? AND start < ?", (a, b, a, b)).fetchall()
    if not rows:
        return f"{label.capitalize()} записей активности нет (журнал ведётся, пока Renard запущен)."
    tot = defaultdict(float)
    for r in rows:
        tot[r[0]] += max(0.0, r[4] - r[3])
    if app:
        from .tools.apps import ALIAS, _variants
        keys = set()
        for v in _variants(app):
            keys.add(v); keys.update(ALIAS.get(v, "").split("|") if v in ALIAS else [])
        keys.discard("")
        hit = [r for r in rows if any(k in r[0].lower() or k == r[1] or (len(k) > 3 and k in r[1]) for k in keys)]
        if not hit:
            return f"{label.capitalize()} «{app}» не было на экране."
        s = sum(max(0.0, r[4] - r[3]) for r in hit)
        first, last = min(r[3] for r in hit), max(r[4] for r in hit)
        return (f"{hit[0][0]} {label}: {_fmt(s)} (с {time.strftime('%H:%M', time.localtime(first))} "
                f"до {time.strftime('%H:%M', time.localtime(last))}).")
    total = sum(v for k, v in tot.items() if k != "Renard")
    top = sorted(((k, v) for k, v in tot.items() if v >= 60), key=lambda x: -x[1])[:12]
    lines = [f"Активность {label}: всего за компьютером {_fmt(total)}"]
    lines += [f"- {k}: {_fmt(v)}" for k, v in top]
    return "\n".join(lines)


def today_top(n: int = 6) -> list[dict]:
    a, b, _ = period_bounds("today")
    db = _db()
    tot = defaultdict(float)
    for app, s, e in db.execute("SELECT app, MAX(start, ?), MIN(end, ?) FROM seg WHERE end > ?", (a, b, a)):
        tot[app] += max(0.0, e - s)
    return [{"app": k, "sec": round(v)} for k, v in sorted(tot.items(), key=lambda x: -x[1])[:n] if v >= 30]


def usual_apps(window_min: int = 75, days: int = 14, min_days: int = 3) -> list[dict]:
    """Apps you usually open around this time of day (first open of the day within ±window)."""
    db = _db()
    now = time.localtime()
    minute = now.tm_hour * 60 + now.tm_min
    since = time.time() - days * 86400
    by_app = defaultdict(set)
    procs = {}
    for app, proc, ts, day in db.execute("SELECT app, proc, ts, day FROM opens WHERE ts > ?", (since,)):
        t = time.localtime(ts)
        if abs(t.tm_hour * 60 + t.tm_min - minute) <= window_min and day != time.strftime("%Y-%m-%d"):
            by_app[app].add(day); procs[app] = proc
    out = [{"app": a, "proc": procs[a], "days": len(d)} for a, d in by_app.items() if len(d) >= min_days]
    return sorted(out, key=lambda x: -x["days"])
