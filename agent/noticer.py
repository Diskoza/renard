"""The companion notices what you do and sometimes says something — like someone sitting next to you, not a nag.

Every 5 s: the app in front (activity.TRACKER), the time since your last input, the clock. Rules (each with its own
cooldown, plus at most one remark per 15 min, bubble only — never spoken):
  back    you return after 10+ min away            «С возвращением!» / «Доброе утро!» (first time in the morning)
  game    a game comes to the front                «О, War Thunder! Удачи 🎮»   (each game: once per 2 h)
  long    2 h at the PC without a 5-min break       «…может, потянемся?» + he stretches
  late    active after 01:00                        once a night, gently
Off: «Модель → Окно → Замечания». Nothing leaves the PC.
"""
import asyncio
import random
import time

from .activity import TRACKER, idle_seconds
from .logs import quiet

GAP = 15 * 60
GAME_HINTS = ("steamapps\\common", "epic games", "riot games", "battle.net", "ubisoft game launcher", "gog galaxy\\games",
              "\\games\\", "minecraft", "warthunder", "war thunder")
NOT_GAMES = ("steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "battle.net.exe", "explorer.exe")


def _today_short() -> str:
    """« Сегодня: созвон в 11:00, 2 дела.» after the morning hello (planner), '' on a free day."""
    try:
        from .planner import today_short
        s = today_short()
        return " " + s if s else ""
    except Exception:
        return ""


def _is_game(proc_stem: str) -> str:
    """Display name if the foreground process looks like a game (by its install folder), else ''."""
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info["name"] or "").lower().removesuffix(".exe") == proc_stem:
                exe = (p.info["exe"] or "").lower()
                if p.info["name"].lower() in NOT_GAMES:
                    return ""
                if any(h in exe for h in GAME_HINTS):
                    return (TRACKER.cur or [""])[0] or proc_stem
                return ""
    except Exception:
        quiet()
    return ""


class Noticer:
    def __init__(self):
        self.last_any = 0.0
        self.last = {}
        self.games = {}
        self.away_since = None
        self.active_since = time.time()
        self.prev_app = ""
        self.late_day = ""

    def enabled(self) -> bool:
        from .prefs import get
        return bool(get("companion.enabled", False) and get("companion.desktop", False) and get("companion.remarks", True) is not False)

    def due(self, rule: str, cooldown: float, now: float) -> bool:
        return now - self.last.get(rule, 0) > cooldown and now - self.last_any > GAP

    def fire(self, rule, now, **ev):
        self.last[rule], self.last_any = now, now
        return {"type": "notice", "kind": rule, **ev}

    def step(self, now: float, idle: float, app: str, proc: str, hour: int):
        """One check -> an event dict or None. Pure enough to test (eval.notice_check)."""
        ev = None
        if now - getattr(self, "prev_t", now) > 60:
            self.active_since = now
        self.prev_t = now
        if idle > 600:
            if self.away_since is None:
                self.away_since = now - idle
            self.active_since = now
            return None
        if idle > 300:
            self.active_since = now
        if self.away_since is not None:
            away = now - self.away_since
            self.away_since = None
            if self.due("back", 20 * 60, now):
                morning = 5 <= hour < 12 and away > 3 * 3600
                ev = self.fire("back", now, action="wave", emotion="happy",
                               text=("Доброе утро! ☀️" + _today_short()) if morning else random.choice(["С возвращением! 👋", "О, ты вернулся 🙂", "Привет снова!"]))
                return ev
        if app and app != self.prev_app:
            self.prev_app = app
            game = _is_game(proc) if proc else ""
            if game and now - self.games.get(game, 0) > 2 * 3600 and now - self.last_any > 60:
                self.games[game] = now
                return self.fire("game", now, action="celebrate", emotion="happy",
                                 text=random.choice([f"О, {game}! Удачи 🎮", f"{game}? Погнали! 🎮", f"Играем в {game} 😎"]))
        if now - self.active_since > 2 * 3600 and self.due("long", 2 * 3600, now):
            self.active_since = now
            return self.fire("long", now, action="stretch", emotion="relaxed",
                             text=random.choice(["Ты уже пару часов за компом — может, потянемся? 🙆", "Два часа без перерыва. Глаза отдохнуть не хотят? 👀"]))
        day = time.strftime("%Y-%m-%d", time.localtime(now - 6 * 3600))
        if 1 <= hour < 5 and self.late_day != day and now - self.last_any > GAP:
            self.late_day = day
            return self.fire("late", now, action="stretch", emotion="relaxed",
                             text=f"Уже {time.strftime('%H:%M', time.localtime(now))}… не забудь поспать 🙂")
        return ev

    async def run(self, broadcast):
        while True:
            await asyncio.sleep(5)
            try:
                if not self.enabled():
                    continue
                cur = TRACKER.cur or ["", "", "", 0, 0]
                ev = self.step(time.time(), idle_seconds(), cur[0] if cur[0] != "Renard" else self.prev_app, cur[1], time.localtime().tm_hour)
                if ev:
                    await broadcast(ev)
            except Exception as e:
                print("noticer:", e)


NOTICER = Noticer()
