"""Music: play a song / artist / genre, pause, resume, next, previous, «что играет».

Playback control goes through the Windows media session (works with Spotify, Яндекс Музыка, YouTube in a browser…).
«Включи <что-то>»: YouTube — first search result opened with autoplay (no API key); Spotify / Яндекс — opens the search.
"""
import asyncio
import random
import re
import urllib.parse
import webbrowser

import httpx

from . import S, tool
from ..logs import quiet

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept-Language": "ru,en;q=0.8"}


async def youtube_first(query: str) -> tuple[str, str] | None:
    async with httpx.AsyncClient(headers=UA, cookies={"SOCS": "CAI", "CONSENT": "YES+1"}, timeout=15,
                                 follow_redirects=True) as c:
        r = await c.get("https://www.youtube.com/results", params={"search_query": query})
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,600}?"title":\{"runs":\[\{"text":"([^"]+)"', r.text)
    return (m.group(1), m.group(2).encode().decode("unicode_escape", "ignore") if "\\u" in m.group(2) else m.group(2)) if m else None


async def youtube_search(query: str, n: int = 8) -> list[tuple[str, str]]:
    """Top n videos of a YouTube search (id, title), no API key."""
    try:
        async with httpx.AsyncClient(headers=UA, cookies={"SOCS": "CAI", "CONSENT": "YES+1"}, timeout=15,
                                     follow_redirects=True) as c:
            r = await c.get("https://www.youtube.com/results", params={"search_query": query})
    except Exception:
        return []
    out, seen = [], set()
    for m in re.finditer(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,600}?"title":\{"runs":\[\{"text":"([^"]+)"', r.text):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        t = m.group(2)
        out.append((m.group(1), t.encode().decode("unicode_escape", "ignore") if "\\u" in t else t))
        if len(out) >= n:
            break
    return out


POOL = ["lofi hip hop mix", "chill phonk mix", "rock hits playlist", "synthwave retrowave mix", "deep house mix",
        "drum and bass mix", "indie rock mix", "русский рэп хиты", "polskie hity", "rap hits playlist",
        "chillout lounge music", "alternative rock mix", "electronic music mix", "gaming music mix",
        "metal hits playlist", "russian rock классика", "pop hits playlist", "jazz hop mix"]
GENERIC_Q = re.compile(r"музык|песн|mix|микс|подборк|плейлист|playlist|сборник|хит|hits|lofi|лофи|phonk|фонк|для\s|"
                       r"настроени|жанр|chill|чил|рок\b|rock\b|рэп|rap\b|джаз|jazz|house|техно|techno|метал|metal|поп\b|pop\b|"
                       r"классик|релакс|relax|учёб|учеб|фон", re.I)


def _specific(query: str) -> bool:
    return not GENERIC_Q.search(query or "")


def _remember_query(q: str):
    if not q or URL.search(q) or MINE.match(q):
        return
    qs = [x for x in _music_prefs().get("queries", []) if x.lower() != q.lower()] + [q]
    _save_music(queries=qs[-30:])


def _varied_query() -> str:
    p = _music_prefs()
    recent = p.get("recent_pool", [])[-4:]
    own = [q for q in p.get("queries", []) if q not in recent]
    choices = [q for q in POOL if q not in recent]
    q = random.choice(own) if own and random.random() < 0.5 else random.choice(choices)
    _save_music(recent_pool=(recent + [q])[-6:])
    return q


def _last() -> dict:
    from ..media_now import _cache
    return _cache["data"] or {}


async def _new_title(before: str | None, limit: float) -> str:
    """Wait (at most `limit` s) until the media session shows another title."""
    from ..media_now import now_playing
    end = asyncio.get_event_loop().time() + limit
    while asyncio.get_event_loop().time() < end:
        await asyncio.sleep(0.6)
        try:
            m = await asyncio.wait_for(now_playing(), max(0.2, end - asyncio.get_event_loop().time()))
        except asyncio.TimeoutError:
            break
        if m.get("title") and m["title"] != before:
            return m["title"]
    return ""


def _yt_window():
    """The browser window whose active tab is YouTube (title «… - YouTube - Google Chrome»)."""
    try:
        from .apps import list_wins
        return next((w for w in list_wins() if re.search(r"\bYouTube\b", w["title"])
                     and w["stem"] in ("chrome", "msedge", "firefox", "opera", "brave", "vivaldi", "yandex")), None)
    except Exception:
        return None


async def _in_yt_tab(keys: str = "", url: str = "") -> bool:
    """Do something in the YouTube tab that is already open (no new tabs): open a URL in it or press its hotkeys
    (shift+n — next video, shift+p — previous, k — pause). Focus goes back to where the user was."""
    w = _yt_window()
    if not w:
        return False
    from .apps import activate, active_window
    from .. import winput
    prev = active_window()
    activate(w["hwnd"])
    await asyncio.sleep(0.35)
    if url:
        winput.press("ctrl+l"); await asyncio.sleep(0.15)
        winput.type_text(url); await asyncio.sleep(0.1)
        winput.press("enter")
    elif keys:
        winput.press("escape"); await asyncio.sleep(0.05)
        winput.press(keys)
    await asyncio.sleep(0.4 if url else 0.3)
    if w["state"] == "свёрнуто":
        import ctypes
        ctypes.windll.user32.ShowWindow(w["hwnd"], 6)
    if prev and prev["hwnd"] != w["hwnd"] and (not url or w["state"] == "свёрнуто"):
        activate(prev["hwnd"])
    return True


def _open(link: str) -> None:
    webbrowser.open(link)


def _service() -> str:
    from ..prefs import get
    return get("music.service", "youtube") or "youtube"


async def _session_action(action: str) -> bool:
    try:
        from ..media_now import control
        return await control(action)
    except Exception:
        return False


MINE = re.compile(r"^(мо[юяи]|мой|моё|мое)\s*(музык\w*|плейлист\w*|подборк\w*|песн\w*)?$|^(как обычно|любим\w*|my music)$", re.I)
URL = re.compile(r"https?://\S+|spotify:\S+")


def _music_prefs() -> dict:
    from ..prefs import get as pget
    return pget("music", {}) or {}


def _save_music(**kw):
    from ..prefs import update
    update({"music": kw})


@tool("music",
      "Музыка. action: play (включить; query — песня/исполнитель/жанр или ссылка YouTube/Spotify; «моя музыка» = любимый "
      "плейлист пользователя; пусто = продолжить), pause, resume, next, prev, now (что играет), save_favorite (запомнить "
      "ссылку из query или то, что сейчас открыто, как «мою музыку»). service: youtube | spotify | yandex",
      {"action": S, "query": S, "service": S}, ["action"])
async def music(action: str = "play", query: str = "", service: str = "") -> str:
    from ..media_now import now_playing
    action = (action or "play").lower()
    query = (query or "").strip()
    if action in ("save_favorite", "favorite", "save"):
        url = (URL.search(query) or [None])[0] if URL.search(query) else _music_prefs().get("last_url")
        if not url:
            m = await now_playing()
            if not m.get("title"):
                return "Пришли ссылку на плейлист или видео — запомню её как «твою музыку»."
            url = f"{m['title']} {m.get('artist', '')}".strip()
        _save_music(favorite=url)
        return f"Запомнил как твою музыку: {url}. Скажи «включи мою музыку» — включу."
    if action == "play" and query and MINE.match(query):
        fav = _music_prefs().get("favorite") or _music_prefs().get("last_url")
        if not fav:
            return "Я ещё не знаю твою музыку: пришли ссылку на плейлист или видео на YouTube и скажи «запомни как мою музыку»."
        query = fav
    u = URL.search(query)
    if action == "play" and u:
        try:
            from .system import stop_radio
            stop_radio()
        except Exception:
            quiet()
        link = u.group(0)
        if "youtube.com/watch" in link and "autoplay" not in link:
            link += "&autoplay=1"
        if not ("youtu" in link and await _in_yt_tab(url=link)):
            _open(link)
        _save_music(last_url=u.group(0))
        return "Включил по ссылке." + ("" if _music_prefs().get("favorite") else " Если это твоя музыка — скажи «запомни как мою музыку».")
    if action in ("now", "what", "status"):
        m = await now_playing()
        if not m.get("title"):
            return "Сейчас ничего не играет."
        return f"{'Играет' if m.get('playing') else 'На паузе'}: {m['title']}" + (f" — {m['artist']}" if m.get("artist") else "")
    if action in ("pause", "stop"):
        if await _session_action("pause"):
            return "Поставил на паузу."
        m = _last()
        return "Ничего не играет." if not m.get("title") else "Уже на паузе."
    if action in ("next", "prev"):
        before = _last().get("title")
        if await _in_yt_tab(keys="shift+n" if action == "next" else "shift+p"):
            title = await _new_title(before, 2.5)
            if title:
                return ("Следующее видео" if action == "next" else "Предыдущее видео") + f": {title}"
            if action == "prev":
                return "На YouTube «назад» работает только в плейлисте — скажи название, и я включу то видео."
            return "Переключил на следующее видео."
        ok = await _session_action(action)
        if not ok:
            from .media import media_control
            media_control(action)
        title = await _new_title(before, 2.0)
        return ("Следующий трек" if action == "next" else "Предыдущий трек") + (f": {title}" if title else ".")
    if action == "resume" or (not query and action == "play"):
        m = await now_playing()
        if m.get("title") and not m.get("playing") or action == "resume":
            if await _session_action("play"):
                m = _last()
                return "Продолжаю" + (f": {m['title']}" if m.get("title") else ".") + (f" — {m['artist']}" if m.get("artist") else "")
            if _yt_window() and await _in_yt_tab(keys="k"):
                return "Продолжаю на YouTube."
            if action == "resume":
                return "Не нашёл, что продолжить: ничего не стоит на паузе. Скажи, что включить."
    if not query:
        query = _varied_query()
    else:
        _remember_query(query)
    try:
        from .system import stop_radio
        stop_radio()
    except Exception:
        quiet()
    svc = (service or _service()).lower()
    if "spot" in svc:
        webbrowser.open("spotify:search:" + urllib.parse.quote(query))
        return f"Открыл поиск «{query}» в Spotify (включи нужный трек, дальше могу управлять: пауза, следующий)."
    if "yand" in svc or "янд" in svc:
        webbrowser.open("https://music.yandex.ru/search?text=" + urllib.parse.quote(query))
        return f"Открыл поиск «{query}» в Яндекс Музыке."
    hits = await youtube_search(query, 8)
    if not hits:
        webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
        return f"Не нашёл точного видео, открыл поиск «{query}» на YouTube."
    recent = set(_music_prefs().get("played", [])[-40:])
    fresh = [h for h in hits if h[0] not in recent] or hits
    vid, title = fresh[0] if _specific(query) else random.choice(fresh[:5])
    link = f"https://www.youtube.com/watch?v={vid}&autoplay=1"
    same_tab = await _in_yt_tab(url=link)
    if not same_tab:
        _open(link)
    _save_music(last_url=link, last_title=title, played=(_music_prefs().get("played", []) + [vid])[-60:])
    return f"Включил на YouTube: {title}" + (" (в той же вкладке)" if same_tab else "") + \
        ("" if _specific(query) else f"\n(подборка: {query}; не то — скажи «другую песню» или назови жанр/исполнителя)")
