"""PC state + apps. No LLM needed for these."""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from ..config import APPS
from . import S, tool
from ..logs import quiet

try:
    import pynvml
    pynvml.nvmlInit()
    _GPU = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:
    pynvml, _GPU = None, None

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
psutil.cpu_percent(interval=None)


def gpu_stats() -> dict:
    if not _GPU:
        return {}
    mem = pynvml.nvmlDeviceGetMemoryInfo(_GPU)
    util = pynvml.nvmlDeviceGetUtilizationRates(_GPU)
    try:
        temp = pynvml.nvmlDeviceGetTemperature(_GPU, pynvml.NVML_TEMPERATURE_GPU)
    except Exception:
        temp = None
    name = pynvml.nvmlDeviceGetName(_GPU)
    return {"name": name if isinstance(name, str) else name.decode(), "load_%": util.gpu,
            "vram_used_gb": round(mem.used / 1e9, 1), "vram_total_gb": round(mem.total / 1e9, 1), "temp_c": temp}


def volume_mount_points() -> list[str]:
    """All mounted volumes incl. disks mounted into folders (e.g. C:\\Data), not only drive letters."""
    paths = []
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.FindFirstVolumeW.restype = wintypes.HANDLE
        k32.FindFirstVolumeW.argtypes = [wintypes.LPWSTR, wintypes.DWORD]
        k32.FindNextVolumeW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD]
        k32.FindNextVolumeW.restype = wintypes.BOOL
        k32.FindVolumeClose.argtypes = [wintypes.HANDLE]
        k32.GetVolumePathNamesForVolumeNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                                         ctypes.POINTER(wintypes.DWORD)]
        buf = ctypes.create_unicode_buffer(1024)
        h = k32.FindFirstVolumeW(buf, 1024)
        if h and h != wintypes.HANDLE(-1).value:
            try:
                while True:
                    names = ctypes.create_unicode_buffer(4096)
                    ln = wintypes.DWORD()
                    if k32.GetVolumePathNamesForVolumeNameW(buf.value, names, 4096, ctypes.byref(ln)):
                        paths += [p for p in names[:ln.value].split("\0") if p]
                    if not k32.FindNextVolumeW(h, buf, 1024):
                        break
            finally:
                k32.FindVolumeClose(h)
    if not paths:
        paths = [p.mountpoint for p in psutil.disk_partitions(all=False)]
    return sorted(set(paths), key=len)


@tool("pc_stats", "Состояние ПК: загрузка CPU/GPU/RAM, VRAM, температура GPU, ВСЕ диски (включая подключённые как папки), топ процессов по памяти")
def pc_stats() -> dict:
    vm = psutil.virtual_memory()
    disks = {}
    for mp in volume_mount_points():
        try:
            u = psutil.disk_usage(mp)
            disks[mp] = f"свободно {u.free / 1e9:.0f} из {u.total / 1e9:.0f} ГБ ({100 - u.percent:.0f}%)"
        except Exception:
            quiet()
    procs = []
    for pr in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((pr.info["memory_info"].rss, pr.info["name"]))
        except Exception:
            quiet()
    agg: dict[str, int] = {}
    for rss, n in procs:
        agg[n] = agg.get(n, 0) + rss
    top = sorted(agg.items(), key=lambda x: -x[1])[:6]
    return {
        "cpu_%": psutil.cpu_percent(interval=None),
        "ram": f"{vm.used / 1e9:.1f} из {vm.total / 1e9:.0f} ГБ ({vm.percent:.0f}%)",
        "gpu": gpu_stats(),
        "disks": disks,
        "top_ram": {n: f"{b / 1e9:.1f} ГБ" for n, b in top},
        "temps": _temps(),
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


def _temps() -> dict:
    from .system import lhm_temps
    return lhm_temps()


def _learned_app(name: str):
    """«запомни, что майнкрафт я запускаю через X Minecraft Launcher» -> «запусти майн» opens X Minecraft Launcher."""
    import re
    from ..config import MEMORY_DIR
    q = name.lower().strip()
    stem = re.sub(r"[^\wа-яё]", "", q)[:4]
    if len(stem) < 3:
        return None
    for p in MEMORY_DIR.glob("*.md"):
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            low = line.lower()
            if stem not in low:
                continue
            m = re.search(r"(?:через|в программе|в приложении|using|with|przez|=|—|->)\s+([^\n(.,;]+)", line, re.I)
            if not m:
                continue
            head = low[:m.start()]
            if re.search(r"(?:\bне|\bnie|\bnot)\s+(?:\w+\s+)?$", head):
                continue
            words = [w[:4] for w in re.findall(r"[\wа-яё]+", q) if len(w) >= 3]
            if not words or not all(re.search(r"\b" + re.escape(w), head) for w in words):
                continue
            target = m.group(1).strip()
            if stem in target.lower()[:len(stem) + 2] and target.lower().startswith(q):
                continue
            from .system import find_indexed_app
            a = find_indexed_app(target)
            if a:
                return a["name"], {"start": a["link"], "process": a.get("process", ""), "indexed": True,
                                   "target": a.get("game_exe") or a.get("target", "")}
    return None


def find_app(name: str) -> tuple[str, dict] | None:
    """Learned preference (memory) first, then the whitelist (config/apps.json), then the Start Menu index."""
    if PLAYED.search(name or ""):
        g = played_game(name)
        if g:
            return g["name"], {"start": g["link"], "process": g.get("process", ""), "indexed": True,
                               "target": g.get("game_exe") or g.get("target", "")}
    p = (name or "").strip().strip('"')
    if re.match(r"(?i)^[a-z]:\\.+\.(exe|lnk|url|bat)$", p) and os.path.exists(p):
        return Path(p).stem, {"start": p, "process": Path(p).stem if p.lower().endswith(".exe") else "", "indexed": True}
    try:
        learned = _learned_app(name)
        if learned:
            return learned
    except Exception:
        quiet()
    from .system import exact_indexed_app, find_indexed_app
    q = (name or "").lower().strip()
    if q not in APPS:
        a = exact_indexed_app(name)
        if a:
            return a["name"], {"start": a["link"], "process": a.get("process", ""), "indexed": True,
                                   "target": a.get("game_exe") or a.get("target", "")}
    found = _find_whitelisted(name)
    if found:
        return found
    a = find_indexed_app(name)
    if a:
        return a["name"], {"start": a["link"], "process": a.get("process", ""), "indexed": True,
                                   "target": a.get("game_exe") or a.get("target", "")}
    return None


PLAYED = re.compile(r"(?i)(игр\w*|game|gr[ęe])\W.*\b(играл|играю|запускал|сидел|grałem|played)|"
                    r"(в которую|в что|во что|что) (я )?(играл|запускал)|последн\w+ игр|last game")


def played_game(text: str) -> dict | None:
    """The game he played (yesterday / today / last time) — from the activity journal, matched to installed games."""
    import sqlite3
    import time as _t
    from .system import apps_index
    day = 1 if re.search(r"(?i)вчера|wczoraj|yesterday", text) else 0
    if re.search(r"(?i)позавчера|przedwczoraj", text):
        day = 2
    games = {}
    for a in apps_index():
        proc = (a.get("process") or "").lower()
        tgt = (a.get("target") or a.get("link") or "").lower()
        if proc and (a.get("source") in ("steam", "epic", "folder", "hydra") or re.search(
                r"steamapps|\\games\\|epic games|riot|gog|roblox", tgt)):
            games[proc] = a
    try:
        from ..config import DATA_DIR
        db = sqlite3.connect(str(DATA_DIR / "activity.sqlite3"))
    except Exception:
        return None
    lt = _t.localtime()
    midnight = _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    a0, a1 = (midnight - day * 86400, midnight - (day - 1) * 86400) if day else (midnight - 86400 * 7, _t.time())
    rows = db.execute("select proc, sum(end-start) from seg where start >= ? and start < ? group by proc "
                      "order by 2 desc", (a0, a1)).fetchall()
    for proc, sec in rows:
        p = (proc or "").lower()
        hit = games.get(p) or next((g for k, g in games.items() if k and (k in p or p in k)), None)
        if hit and sec > 60:
            return hit
    return None


def _find_whitelisted(name: str) -> tuple[str, dict] | None:
    q = name.lower().strip()
    for key, app in APPS.items():
        if q == key or q in [a.lower() for a in app.get("aliases", [])]:
            return key, app
    for key, app in APPS.items():
        if any(a.lower() in q or q in a.lower() for a in app.get("aliases", []) + [key]):
            return key, app
    return None


def _launch(cmd: str, app: dict):
    """Start an app the way Explorer does (.lnk / UWP via explorer.exe -> normal user token, no UAC-cancel errors)."""
    if cmd.startswith("shell:AppsFolder") or cmd.lower().endswith(".lnk") or cmd.lower().endswith(".url"):
        subprocess.Popen(["explorer.exe", cmd])
    elif cmd.endswith(":") or "://" in cmd:
        os.startfile(cmd)
    else:
        head = cmd.split(" --")[0]
        exe = head.strip().strip('"')
        exe = exe if os.path.exists(exe) else (shutil.which(exe) or "")
        if not exe:
            raise FileNotFoundError(head)
        rest = cmd[len(head):]
        console = os.path.basename(exe).lower() in ("cmd.exe", "powershell.exe", "pwsh.exe", "wsl.exe", "python.exe", "bash.exe")
        subprocess.Popen(f'"{exe}"{rest}' if rest else [exe], cwd=os.path.dirname(exe),
                         creationflags=0x00000010 if console else NO_WINDOW)


def ctypes_post(hwnd):
    import ctypes
    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)


def _running(proc: str) -> set:
    proc = proc.lower().removesuffix(".exe")
    out = set()
    for pr in psutil.process_iter(["name", "pid"]):
        n = (pr.info["name"] or "").lower().removesuffix(".exe")
        if proc and n == proc:
            out.add(pr.info["pid"])
    return out


def _display(key: str, app: dict, said: str) -> str:
    """How to name the app in the answer: the word the user said if it is an alias, else a Russian alias, else the key
    («Запустил калькулятор», not «Запустил calc»)."""
    al = [a for a in app.get("aliases", []) if a]
    if said.lower().strip() in [a.lower() for a in al]:
        return said.strip()
    return next((a for a in al if re.search("[а-яё]", a, re.I)), key)


@tool("open_app", "Запустить программу или игру по названию (любая установленная из меню Пуск)", {"name": S}, ["name"])
async def open_app(name: str) -> str:
    found = find_app(name)
    if not found:
        return f"Не нашёл программу '{name}' ни в списке, ни в меню Пуск. Попробуй find_installed_apps."
    key, app = found
    disp = _display(key, app, name)
    cmd = os.path.expandvars(app["start"])
    proc = app.get("process") or ""
    before = _running(proc)
    try:
        _launch(cmd, app)
    except FileNotFoundError:
        from .system import find_indexed_app
        a = find_indexed_app(key) or find_indexed_app(name)
        if not a:
            return f"Не удалось запустить {key}: файл {cmd} не найден и в меню Пуск ярлыка нет."
        _launch(a["link"], {})
    except OSError as e:
        if getattr(e, "winerror", None) == 1223 and app.get("indexed"):
            subprocess.Popen(["explorer.exe", cmd])
        else:
            return f"Не удалось запустить {key}: {e}"
    if not proc:
        return f"Запустил {disp}."
    game = bool(re.search(r"(?i)\\games?\\|steamapps|hydra|\\gry\\|\\игры\\|\.url$", cmd + " " + app.get("start", "") + " " + app.get("target", "")))
    wait_s = 25 if game else 6
    for _ in range(wait_s * 5):
        await __import__("asyncio").sleep(0.2)
        if _running(proc) - before or (before and _running(proc)):
            return f"Запустил {disp}." if not before else f"{disp[:1].upper() + disp[1:]} уже был запущен — вывел запуск ещё раз."
    return (f"Команду запуска «{disp}» отправил ({cmd}), но процесс {proc} не появился за {wait_s} с. "
            f"Возможно, игра/программа ещё грузится или спросила права администратора — проверь windows через минуту.")


def _elevated(pid: int) -> bool:
    """Started «as administrator» (Renard runs without admin rights: it cannot close / kill such a program)."""
    try:
        psutil.Process(pid).exe()
        return False
    except psutil.AccessDenied:
        return True
    except Exception:
        return False


def _closed_check(hwnds: list[int], wait: float = 3.0) -> str:
    """After WM_CLOSE: did the windows really go? '' = yes, else an honest reason (asked to save / admin rights)."""
    import ctypes
    import time as _t
    u = ctypes.windll.user32
    t0 = _t.time()
    alive = list(hwnds)
    while _t.time() - t0 < wait:
        alive = [h for h in alive if u.IsWindow(h) and u.IsWindowVisible(h)]
        if not alive:
            return ""
        _t.sleep(0.3)
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(alive[0], ctypes.byref(pid))
    if _elevated(pid.value):
        return ("окно НЕ закрылось: программа запущена с правами администратора, а Renard работает без них — "
                "закрыть её может только сам пользователь (крестик или Alt+F4)")
    return ("окно ещё открыто — скорее всего программа спрашивает, сохранить ли изменения (ответ — в её окне), "
            "или закрывается медленно")


@tool("close_app", "Закрыть программу (как крестик у всех её окон; несохранённое программа спросит сама)", {"name": S}, ["name"])
def close_app(name: str) -> str:
    try:
        from .apps import find_window, list_wins, _name
        wins = list_wins()
        w = find_window(name, wins)
        if w and not w["title"].startswith("Renard"):
            same = [x for x in wins if x["stem"] == w["stem"]] if w["stem"] != "applicationframehost" else [w]
            for x in same:
                ctypes_post(x["hwnd"])
            left = _closed_check([x["hwnd"] for x in same])
            if left:
                return f"{_name(w)}: {left}."
            return f"Закрыл {_name(w)}" + (f" и ещё {len(same) - 1} окон" if len(same) > 1 else "") + "."
    except Exception as e:
        print("close_app windows:", e)
    found = find_app(name)
    if not found:
        return f"Приложения '{name}' нет в белом списке."
    key, app = found
    target = (app.get("process") or "").lower()
    if not target:
        return f"Не знаю имя процесса для {key}. Скажи «завершить процесс <имя>.exe»."
    n, denied = 0, 0
    for pr in psutil.process_iter(["name"]):
        try:
            if pr.info["name"] and pr.info["name"].lower().removesuffix(".exe") == target:
                pr.terminate()
                n += 1
        except psutil.AccessDenied:
            denied += 1
        except Exception:
            quiet()
    if denied:
        return (f"{key}: {denied} процесс(ов) запущены с правами администратора — Renard без этих прав их не закроет, "
                f"закрой сам." + (f" Остальные {n} закрыл." if n else ""))
    return f"Закрыл {key} ({n} процессов)." if n else f"{key} не запущен."


@tool("defender_status", "Статус Windows Defender и последние найденные угрозы", modes=("low", "medium"))
def defender_status() -> str:
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $s=Get-MpComputerStatus; "
          "'Защита в реальном времени: '+$s.RealTimeProtectionEnabled; "
          "'Базы обновлены: '+$s.AntivirusSignatureLastUpdated; "
          "'Последнее быстрое сканирование: '+$s.QuickScanEndTime; "
          "$t=Get-MpThreatDetection | Select -First 5; if($t){'Угрозы:'; $t | % { $_.InitialDetectionTime.ToString()+' '+$_.Resources[0] }} else {'Угроз не найдено'}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30, creationflags=NO_WINDOW)
        return (out.stdout or out.stderr).strip()[:2000]
    except Exception as e:
        return f"Не удалось получить статус Defender: {e}"


@tool("defender_scan", "Запустить быстрое сканирование Windows Defender в фоне", modes=("low", "medium"))
def defender_scan() -> str:
    subprocess.Popen(["powershell", "-NoProfile", "-Command", "Start-MpScan -ScanType QuickScan"],
                     creationflags=NO_WINDOW)
    return "Запустил быстрое сканирование Defender в фоне. Результат: спроси «статус защитника» через несколько минут."
