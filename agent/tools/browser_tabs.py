"""«Открой последнюю закрытую вкладку (ютуба)» and «открой папку загрузки» — without the model.

Before: «открой хром и последнюю закрытую вкладку ютуба» only opened Chrome; «открой папку загрузки» went to the model,
which apologised. Known folders come from the registry (they may be moved, e.g. Desktop into OneDrive).
"""
import asyncio
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from . import S, tool

SITES = {r"ютуб|youtube|ютьюб": "youtube.com", r"гитхаб|github": "github.com", r"твич|twitch": "twitch.tv",
         r"\bвк\b|вконтакте|vk\b": "vk.com", r"википеди|wikipedi": "wikipedia.org", r"реддит|reddit": "reddit.com",
         r"инстаграм|instagram|инста": "instagram.com", r"тикток|tiktok": "tiktok.com", r"дзиенник|dziennik|vulcan|вулкан": "vulcan",
         r"чатгпт|chatgpt|gpt": "chatgpt.com", r"гугл док|google doc": "docs.google.com", r"телеграм|telegram": "telegram.org",
         r"стим|steam": "steam", r"нетфликс|netflix": "netflix.com", r"спотиф|spotify": "spotify.com"}


def site_host(text: str) -> str:
    t = (text or "").lower()
    for rx, host in SITES.items():
        if re.search(rx, t):
            return host
    m = re.search(r"\b([a-z0-9-]+\.(?:com|pl|ru|org|net|io|tv|edu\.pl))\b", t)
    return m.group(1) if m else ""


def chrome_exe() -> str:
    import winreg
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                p = winreg.QueryValue(k, None)
                if p and os.path.exists(p):
                    return p
        except OSError:
            pass
    for p in (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
              r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"):
        p = os.path.expandvars(p)
        if os.path.exists(p):
            return p
    return shutil.which("chrome") or ""


def _history_db() -> Path | None:
    base = Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"))
    dbs = [p for p in base.glob("*/History") if p.is_file()]
    return max(dbs, key=lambda p: p.stat().st_mtime) if dbs else None


def last_visited(host: str, skip_titles: set[str] = frozenset()) -> tuple[str, str] | None:
    """The newest page of `host` in the Chrome history that is not open right now (= the tab that was closed)."""
    db = _history_db()
    if not db:
        return None
    tmp = Path(tempfile.gettempdir()) / "renard_chrome_history.sqlite"
    shutil.copy2(db, tmp)
    try:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        rows = con.execute("SELECT url, title FROM urls WHERE url LIKE ? ORDER BY last_visit_time DESC LIMIT 15",
                           (f"%{host}%",)).fetchall()
        con.close()
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    page = [r for r in rows if not re.search(r"/results\?|/search\?|accounts\.|/login", r[0])] or rows
    for url, title in page:
        if title and title.strip() in skip_titles:
            continue
        return url, title or url
    return None


def _chrome_wins() -> list[dict]:
    from .apps import list_wins
    return [w for w in list_wins() if w.get("stem") == "chrome"]


@tool("reopen_tab",
      "Вернуть закрытую вкладку браузера Chrome. site — если нужна последняя вкладка конкретного сайта "
      "(«последнюю вкладку ютуба» -> site=youtube): откроется последняя страница этого сайта из истории, которой сейчас нет",
      {"site": S}, [])
async def reopen_tab(site: str = "") -> str:
    exe = chrome_exe()
    if not exe:
        return "Не нашёл Chrome на этом ПК."
    host = site_host(site) or (site.strip().lower() if "." in (site or "") else "")
    if site and host:
        wins = _chrome_wins()
        open_titles = {re.sub(r"\s+-\s+Google Chrome$", "", w["title"]).removesuffix(" - YouTube").strip() for w in wins}
        err = ""
        try:
            hit = await asyncio.to_thread(last_visited, host, open_titles)
        except Exception as e:
            hit, err = None, f" ({type(e).__name__}: {e})"
        if hit:
            url, title = hit
            subprocess.Popen([exe, url])
            title = re.sub(r"\s+-\s+YouTube$", "", title)
            return f"Открыл в Chrome последнюю вкладку {site}: {title}"
        return f"В истории Chrome не нашёл страниц {site}.{err}"
    from .apps import activate
    from .. import winput
    wins = _chrome_wins()
    if not wins:
        subprocess.Popen([exe])
        for _ in range(30):
            await asyncio.sleep(0.25)
            wins = _chrome_wins()
            if wins:
                break
        if not wins:
            return "Запустил Chrome, но окно не появилось — нажми Ctrl+Shift+T сам."
        await asyncio.sleep(0.8)
    activate(wins[0]["hwnd"])
    await asyncio.sleep(0.35)
    winput.press("ctrl+shift+t")
    return "Вернул последнюю закрытую вкладку в Chrome (Ctrl+Shift+T)."


FOLDERS = {r"загрузк|скачанн|downloads?|pobran": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads", "Загрузки"),
           r"документ|documents?|dokument": ("Personal", "Documents", "Документы"),
           r"рабоч\w* стол|desktop|pulpit": ("Desktop", "Desktop", "Рабочий стол"),
           r"картинк|изображени|фотограф|pictures|obraz": ("My Pictures", "Pictures", "Изображения"),
           r"музык|music|muzyk": ("My Music", "Music", "Музыка"),
           r"видео|video|wideo|filmy": ("My Video", "Videos", "Видео")}


def known_folder(word: str) -> tuple[str, str] | None:
    import winreg
    w = (word or "").lower()
    for rx, (val, fallback, name) in FOLDERS.items():
        if re.search(rx, w):
            path = ""
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                    path = os.path.expandvars(winreg.QueryValueEx(k, val)[0])
            except OSError:
                pass
            if not path or not os.path.isdir(path):
                path = str(Path.home() / fallback)
            return path, name
    return None


@tool("open_folder", "Открыть стандартную папку пользователя в проводнике: загрузки, документы, рабочий стол, "
      "изображения, музыка, видео", {"name": S}, ["name"])
def open_folder(name: str) -> str:
    hit = known_folder(name)
    if not hit:
        return f"Не знаю стандартной папки «{name}». Назови путь, например C:\\Users\\…"
    path, disp = hit
    os.startfile(path)
    return f"Открыл папку «{disp}» ({path})."
