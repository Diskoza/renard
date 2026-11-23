"""The browser by its own keys, like a person does it: refresh, go to tab N, next / previous tab, back, a new tab,
open a link from the last answer, any shortcut («нажми ctrl+l в браузере»). And bring the Renard window to the front.

Before: «обнови страницу» re-opened the last YouTube page from the history (reopen_tab), «переключись на первую вкладку»
and «нажми ctrl+1» had no tool at all, «открой первую ссылку» called open_file with a URL (error), «переключись на
приложение Renard» was answered with «не могу». Works with any Chromium / Firefox browser that is open.
"""
import asyncio
import os
import re
import subprocess

from . import S, tool

BROWSERS = ("chrome", "msedge", "firefox", "opera", "brave", "vivaldi", "yandex", "browser")
ACTIONS = {
    "refresh": "f5", "hard_refresh": "ctrl+f5", "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab", "close_tab": "ctrl+w",
    "new_tab": "ctrl+t", "reopen_closed": "ctrl+shift+t", "back": "alt+left", "forward": "alt+right",
    "home": "alt+home", "fullscreen": "f11", "find": "ctrl+f", "address": "ctrl+l", "zoom_in": "ctrl+plus",
    "zoom_out": "ctrl+minus", "zoom_reset": "ctrl+0", "scroll_down": "pagedown", "scroll_up": "pageup",
}
RU = {"refresh": "Обновил страницу", "hard_refresh": "Обновил страницу без кэша", "next_tab": "Переключил на следующую вкладку",
      "prev_tab": "Переключил на предыдущую вкладку", "close_tab": "Закрыл вкладку", "new_tab": "Открыл новую вкладку",
      "reopen_closed": "Вернул закрытую вкладку", "back": "Вернулся назад", "forward": "Перешёл вперёд",
      "fullscreen": "Переключил полноэкранный режим", "zoom_in": "Увеличил масштаб", "zoom_out": "Уменьшил масштаб",
      "zoom_reset": "Сбросил масштаб", "scroll_down": "Пролистал вниз", "scroll_up": "Пролистал вверх"}


def browser_windows() -> list[dict]:
    from .apps import list_wins
    return [w for w in list_wins() if (w.get("stem") or "").lower() in BROWSERS]


async def _front_browser() -> dict | None:
    from .apps import activate
    wins = browser_windows()
    if not wins:
        return None
    w = wins[0]
    activate(w["hwnd"])
    await asyncio.sleep(0.3)
    return w


def open_url(url: str) -> str:
    """In his browser (the default one): a new tab of the open window."""
    from .browser_tabs import chrome_exe
    wins = browser_windows()
    stem = (wins[0].get("stem") or "").lower() if wins else ""
    exe = chrome_exe() if stem in ("", "chrome") else ""
    if exe:
        subprocess.Popen([exe, url])
    else:
        os.startfile(url)
    return f"Открыл ссылку: {url}"


@tool("browser",
      "Управление открытым браузером его клавишами: action = refresh (обновить страницу, F5) | tab (перейти на вкладку "
      "номер n; n=-1 — последняя) | next_tab | prev_tab | close_tab | new_tab | reopen_closed | back | forward | "
      "fullscreen | zoom_in | zoom_out | zoom_reset | scroll_down | scroll_up | open (url — открыть ссылку) | "
      "keys (keys — любое сочетание, например ctrl+l). Не путать с reopen_tab (вернуть вкладку сайта из истории)",
      {"action": S, "n": {"type": "integer"}, "url": S, "keys": S}, ["action"])
async def browser(action: str, n: int = 0, url: str = "", keys: str = "") -> str:
    from .. import winput
    a = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    if a in ("open", "open_url", "url", "link"):
        if not re.match(r"https?://", url or ""):
            return "Нужна ссылка вида https://…"
        return open_url(url)
    if a in ("open_browser", "start", "launch"):
        w = await _front_browser()
        if w:
            return f"Переключился на браузер: {w['title'][:80]}"
        from .browser_tabs import chrome_exe
        exe = chrome_exe()
        if exe:
            subprocess.Popen([exe])
        else:
            os.startfile("https://www.google.com")
        return "Открыл браузер."
    if a in ("find_tab", "tab_with", "switch_to"):
        return await find_tab(keys or url)
    combo = ""
    if a in ("tab", "goto_tab", "switch_tab"):
        n = int(n or 1)
        combo = "ctrl+9" if n < 0 or n > 8 else f"ctrl+{n}"
    elif a == "keys":
        combo = (keys or "").strip().lower().replace(" ", "")
        if not combo:
            return "Какие клавиши нажать?"
    else:
        combo = ACTIONS.get(a, "")
    if not combo:
        return f"Не знаю действие браузера «{action}». Есть: {', '.join(list(ACTIONS) + ['tab', 'open', 'keys'])}."
    w = await _front_browser()
    if not w:
        return "Браузер не открыт — скажи «открой браузер»."
    winput.press(combo)
    await asyncio.sleep(0.4)
    if a in ("tab", "goto_tab", "switch_tab"):
        title = (browser_windows() or [w])[0]["title"]
        return f"Переключил на {'последнюю' if n < 0 or n > 8 else f'{n}-ю'} вкладку: {title[:90]}"
    if a == "keys":
        return f"Нажал {combo} в браузере."
    return RU.get(a, f"Нажал {combo}") + "."


async def find_tab(what: str) -> str:
    """Go through the open tabs (Ctrl+Tab, as a person would) until the title names the site / words he said."""
    import win32gui
    from .. import winput
    from .browser_tabs import site_host
    host = site_host(what)
    words = [host.split(".")[0]] if host else [w for w in re.findall(r"\w{3,}", (what or "").lower())
                                              if w not in ("вкладку", "вкладка", "браузере", "сайтом", "сайт")]
    if not words:
        return "На какую вкладку переключить?"
    w = await _front_browser()
    if not w:
        return "Браузер не открыт."
    title = lambda: win32gui.GetWindowText(w["hwnd"]).lower()
    first = title()
    for i in range(25):
        if any(x in title() for x in words):
            return f"Переключил на вкладку: {win32gui.GetWindowText(w['hwnd'])[:90]}" if i else \
                f"Уже открыта эта вкладка: {win32gui.GetWindowText(w['hwnd'])[:90]}"
        winput.press("ctrl+tab")
        await asyncio.sleep(0.25)
        if i and title() == first:
            break
    return f"Среди открытых вкладок нет «{what}». Открыть этот сайт?"


LOGIN_SITES = {
    "yummy": "https://yummyanime.tv/", "юмми": "https://yummyanime.tv/", "аниме": "https://yummyanime.tv/",
    "curseforge": "https://www.curseforge.com/", "курсфордж": "https://www.curseforge.com/",
    "vulcan": "https://eduvulcan.pl/", "вулкан": "https://eduvulcan.pl/", "дзиенник": "https://eduvulcan.pl/", "dziennik": "https://eduvulcan.pl/",
    "statususlugi": "https://statususlugi.pl/", "статус": "https://statususlugi.pl/",
    "tiktok": "https://www.tiktok.com/login", "тикток": "https://www.tiktok.com/login",
    "roblox": "https://www.roblox.com/login", "роблокс": "https://www.roblox.com/login",
    "twitch": "https://www.twitch.tv/login", "твич": "https://www.twitch.tv/login",
    "youtube": "https://accounts.google.com/ServiceLogin?service=youtube", "ютуб": "https://accounts.google.com/ServiceLogin?service=youtube",
    "seobility": "https://www.seobility.net/en/seocheck/", "github": "https://github.com/login", "гитхаб": "https://github.com/login",
}


@tool("site_login", "Открыть сайт в браузере Renard (отдельный профиль Chrome), чтобы пользователь САМ вошёл в аккаунт. После "
      "входа агент может читать этот сайт через коннектор browser. site — название (moodle, vulcan, yummyanime, tiktok, roblox, "
      "twitch, curseforge, youtube…) или адрес", {"site": S}, ["site"])
async def site_login(site: str, ctx: dict | None = None) -> str:
    from ..mcp_client import HUB
    s = (site or "").strip()
    url = s if s.startswith("http") else next((u for k, u in LOGIN_SITES.items() if k in s.lower()), "")
    if not url:
        url = "https://" + s if "." in s else ""
    if not url:
        return f"Какой сайт открыть для входа? Знаю: {', '.join(sorted({k for k in LOGIN_SITES if k.isascii()}))}."
    srv = HUB.servers.get("browser")
    if not srv or srv.status != "ready":
        return "Браузер Renard (коннектор browser) не запущен — включи его в «Плагины → Коннекторы»."
    await srv.call("browser_navigate", {"url": url})
    return (f"Открыл {url} в браузере Renard. Войди в аккаунт сам — пароль я не вижу и не храню. Когда войдёшь, окно можно "
            f"закрыть: вход запомнится в профиле Renard, и я смогу читать этот сайт.")


def show_renard() -> bool:
    """Bring the Renard main window up (the desktop app listens for this event)."""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.OpenEventW.restype = ctypes.c_void_p
    h = k32.OpenEventW(0x0002, False, "Local\\RENARD_desktop_show")
    if not h:
        return False
    k32.SetEvent(ctypes.c_void_p(h))
    k32.CloseHandle(ctypes.c_void_p(h))
    return True


@tool("show_renard", "Показать главное окно Renard (это приложение): чат, где видны ответы, ссылки, таблицы", {}, [])
def show_renard_tool() -> str:
    return "Открыл окно Renard — ответ и ссылки там, в чате." if show_renard() else \
        "Окно Renard не запущено как приложение — открой его ярлыком на рабочем столе."
