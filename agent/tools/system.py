"""Stage 3: installed apps index (Start Menu), processes, radio player, notifications, temperatures, temp cleanup."""
import difflib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import httpx
import psutil

from ..config import DATA_DIR, RADIO
from . import I, S, tool
from ..logs import quiet

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
APPS_INDEX = DATA_DIR / "apps_index.json"
START_DIRS = [Path(os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs")),
              Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"))]
SKIP_APP = re.compile(r"(uninstall|удал|readme|help|справк|documentation|website|license|release notes)", re.I)
PROTECTED = {"system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
             "svchost.exe", "explorer.exe", "dwm.exe", "ollama.exe", "llama-server.exe", "python.exe", "pythonw.exe",
             "msmpeng.exe", "fontdrvhost.exe", "registry", "memcompression"}


def _desktop_dirs() -> list[Path]:
    out = []
    try:
        from win32com.shell import shell, shellcon
        for csidl in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_COMMON_DESKTOPDIRECTORY):
            out.append(Path(shell.SHGetFolderPath(0, csidl, None, 0)))
    except Exception:
        out.append(Path(os.path.expandvars(r"%USERPROFILE%\Desktop")))
    return [p for p in out if p.is_dir()]


def _steam_games() -> list[dict]:
    """Installed Steam games -> steam://rungameid/<id> (no shortcut needed)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except Exception:
        return []
    libs = {steam}
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        libs |= {Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore"))}
    games = []
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            t = acf.read_text(encoding="utf-8", errors="ignore")
            name, appid = re.search(r'"name"\s+"([^"]+)"', t), re.search(r'"appid"\s+"(\d+)"', t)
            if name and appid and not re.search(r"(redistributable|proton|steamworks|steam linux runtime|soundtrack)", name.group(1), re.I):
                games.append({"name": name.group(1), "link": f"steam://rungameid/{appid.group(1)}", "target": "", "process": "",
                              "source": "steam"})
    return games


def _epic_games() -> list[dict]:
    games = []
    d = Path(os.path.expandvars(r"%ProgramData%\Epic\EpicGamesLauncher\Data\Manifests"))
    for f in d.glob("*.item") if d.is_dir() else []:
        try:
            j = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            exe = Path(j.get("LaunchExecutable", "")).stem
            games.append({"name": j["DisplayName"], "link": f"com.epicgames.launcher://apps/{j['AppName']}?action=launch&silent=true",
                          "target": "", "process": exe, "source": "epic"})
        except Exception:
            continue
    return games


_NOT_MAIN_EXE = re.compile(r"(?i)unins|uninstall|crash|redist|setup|install|vc_?redist|dxsetup|directx|dotnet|"
                           r"unitycrashhandler|cefsharp|helper|updater|update|report|easyanticheat|eac|be_?service|"
                           r"battleye|ue4prereq|prereq|notification|7z|unrar|vcredist|launcherpatcher|config(urator)?$")
_TAIL_JUNK = re.compile(r"(?i)[\s._-]*(?:-?\s*steam\w*\.(?:net|com)|steamrip\.com|\bbuild[\s._]?\d+|\bv?\d+(?:\.\d+){2,}|"
                        r"\bthe\s+(?:pirate|real)\b.*|\[[^\]]*\]|\([^)]*\))$")


def _clean_game_name(folder: str) -> str:
    """«Probably Stolen - SteamGG.NET» → «Probably Stolen», «Runehaven.Build.23529669» → «Runehaven»."""
    n = folder
    for _ in range(4):
        m = _TAIL_JUNK.sub("", n).strip(" ._-")
        if m == n:
            break
        n = m
    if " " not in n:
        n = re.sub(r"[._-]+", " ", n)
    return n.strip() or folder


def _main_exe(folder: Path) -> Path | None:
    """The game's own .exe inside its folder: named like the folder, else the biggest one (depth ≤ 3)."""
    exes = []
    try:
        for p in folder.rglob("*.exe"):
            rel = p.relative_to(folder)
            if len(rel.parts) > 6 or _NOT_MAIN_EXE.search(p.stem) or any(
                    re.search(r"(?i)redist|prereq|directx|support|tools?$|editor|crashreport|engine\\extras", x)
                    for x in rel.parts[:-1]):
                continue
            try:
                exes.append((p, p.stat().st_size))
            except OSError:
                continue
            if len(exes) > 60:
                break
    except OSError:
        return None
    if not exes:
        return None
    key = re.sub(r"[^a-zа-я0-9]", "", _clean_game_name(folder.name).lower())
    named = [e for e in exes if key and (re.sub(r"[^a-zа-я0-9]", "", e[0].stem.lower()) in key
                                         or key in re.sub(r"[^a-zа-я0-9]", "", e[0].stem.lower()))]
    pick = max(named or exes, key=lambda e: (-len(e[0].relative_to(folder).parts), e[1]))
    return pick[0]


def _game_roots() -> list[Path]:
    """Folders where he keeps games outside launchers: «Games», «Игры», «Gry» at the top of every drive / mount."""
    roots, bases = [], []
    try:
        import psutil
        bases = [Path(p.mountpoint) for p in psutil.disk_partitions(all=False) if "fixed" in (p.opts or "") or p.fstype]
    except Exception:
        bases = [Path("C:\\")]
    for extra in ():
        if extra.is_dir() and extra not in bases:
            bases.append(extra)
    for b in bases:
        try:
            for d in b.iterdir():
                if d.is_dir() and re.fullmatch(r"(?i)(my\s*)?(games?|игры|gry|spiele|jeux)(\s*\w*)?", d.name):
                    roots.append(d)
        except OSError:
            continue
    return roots


def _hydra_games() -> list[Path]:
    """Hydra launcher keeps every game's .exe path in its LevelDB — read the paths straight out of the files."""
    d = Path(os.path.expandvars(r"%APPDATA%\hydralauncher\hydra-db"))
    out = set()
    if not d.is_dir():
        return []
    for f in d.iterdir():
        if f.suffix.lower() not in (".log", ".ldb") or f.stat().st_size > 30_000_000:
            continue
        try:
            raw = f.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        for m in re.finditer(r'[A-Za-z]:(?:\\\\|\\)[^"\x00-\x1f]{3,240}?\.exe', raw):
            p = Path(m.group(0).replace("\\\\", "\\"))
            if p.exists() and not _NOT_MAIN_EXE.search(p.stem):
                out.add(p)
    return sorted(out)


_SUBDIR = re.compile(r"(?i)bin|binaries|win64|win32|x64|x86|pc|game|ru|en|shipping|win64steam|win64shipping|retail|"
                     r"release|build|windows|windowsnoeditor|app|data|launcher")


def game_name_of(exe: Path) -> str:
    """The game's name from its .exe path: the folder above «Binaries\\Win64», «bin», «pc»… (not «Win64Steam»)."""
    top = exe.parent
    while _SUBDIR.fullmatch(top.name) and top.parent != top:
        top = top.parent
    if re.fullmatch(r"(?i)common|games?|игры|gry|steamapps", top.name):
        return _clean_game_name(exe.stem)
    return _clean_game_name(top.name)


def _folder_games() -> list[dict]:
    games, seen = [], set()
    hydra = _hydra_games()
    for root in _game_roots():
        try:
            subs = [d for d in root.iterdir() if d.is_dir()]
        except OSError:
            continue
        for d in subs:
            known = [h for h in hydra if str(h).lower().startswith(str(d).lower() + "\\")]
            exe = known[0] if known else _main_exe(d)
            if exe:
                seen.add(str(exe).lower())
                games.append({"name": _clean_game_name(d.name), "link": str(exe), "target": str(exe),
                              "process": exe.stem, "source": "folder"})
    roots = [str(r).lower() for r in _game_roots()]
    for exe in hydra:
        low = str(exe).lower()
        if low in seen or "\\steamapps\\" in low or any(low.startswith(r) for r in roots):
            continue
        games.append({"name": game_name_of(exe), "link": str(exe), "target": str(exe),
                      "process": exe.stem, "source": "hydra"})
    return games


def build_apps_index() -> list[dict]:
    links = []
    for d in START_DIRS + _desktop_dirs():
        if d.is_dir():
            links += [p for p in d.rglob("*") if p.suffix.lower() in (".lnk", ".url") and not SKIP_APP.search(p.stem)]
    targets: dict[str, str] = {}
    lnks = [str(p) for p in links if p.suffix.lower() == ".lnk"]
    if lnks and os.name == "nt":
        ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $sh=New-Object -ComObject WScript.Shell; $r=@{}; foreach($l in (Get-Content -LiteralPath $args[0] -Encoding UTF8))"
              "{ try { $r[$l]=$sh.CreateShortcut($l).TargetPath } catch {} }; $r | ConvertTo-Json -Compress")
        lst = DATA_DIR / "lnk_list.txt"
        lst.write_text("\n".join(lnks), encoding="utf-8")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", f"& {{{ps}}} '{lst}'"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW).stdout
            targets = json.loads(out or "{}")
        except Exception:
            targets = {}
    apps, seen = [], set()
    for p in links:
        key = p.stem.lower()
        if key in seen:
            continue
        seen.add(key)
        tgt = targets.get(str(p), "") or ""
        apps.append({"name": p.stem, "link": str(p), "target": tgt,
                     "process": Path(tgt).stem if tgt.lower().endswith(".exe") else ""})
    if os.name == "nt":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                 creationflags=NO_WINDOW).stdout
            for it in json.loads(out or "[]"):
                name, appid = it.get("Name", ""), it.get("AppID", "")
                if not name or not appid or name.lower() in seen or SKIP_APP.search(name):
                    continue
                if "!" not in appid:
                    continue
                seen.add(name.lower())
                apps.append({"name": name, "link": "shell:AppsFolder\\" + appid, "target": "", "process": ""})
        except Exception:
            quiet()
    try:
        folder_games = _folder_games()
    except Exception:
        folder_games = []
    for g in _steam_games() + _epic_games() + folder_games:
        if g["name"].lower() not in seen:
            seen.add(g["name"].lower()); apps.append(g)
    flat = lambda s: re.sub(r"[^a-z0-9а-я]", "", s.lower())
    by_name = {flat(g["name"]): g for g in folder_games}
    for a in apps:
        if (a.get("process") or "").lower() == "hydra" and a["name"].lower() != "hydra":
            g = by_name.get(flat(a["name"]))
            if g:
                a["process"], a["game_exe"], a["source"] = g["process"], g["target"], "hydra"
    APPS_INDEX.write_text(json.dumps({"built": time.time(), "apps": apps}, ensure_ascii=False, indent=0), encoding="utf-8")
    return apps


def _menu_changed() -> float:
    """Newest change in the Start menu folders: a freshly installed program adds a folder or shortcut there
    (the desktop is left out — files land there all the time)."""
    m = 0.0
    try:
        game_dirs = _game_roots()
    except Exception:
        game_dirs = []
    for d in START_DIRS + game_dirs:
        try:
            m = max(m, d.stat().st_mtime, *(p.stat().st_mtime for p in d.iterdir() if p.is_dir()))
        except (OSError, ValueError):
            continue
    return m


def apps_index() -> list[dict]:
    if APPS_INDEX.exists():
        data = json.loads(APPS_INDEX.read_text(encoding="utf-8"))
        built = data.get("built", 0)
        if time.time() - built < 24 * 3600 and _menu_changed() <= built:
            return data["apps"]
    return build_apps_index()


TRANSLIT = {"хром": "chrome", "дискорд": "discord", "телеграм": "telegram", "стим": "steam", "спотифай": "spotify",
            "блокнот": "notepad", "ворд": "word", "эксель": "excel", "фотошоп": "photoshop", "обс": "obs",
            "вскод": "visual studio code", "вс код": "visual studio code", "майнкрафт": "minecraft",
            "армори": "armoury crate", "армуари": "armoury crate", "армори крейт": "armoury crate", "эпик": "epic games",
            "опера": "opera", "фаерфокс": "firefox", "яндекс": "yandex", "вайбер": "viber", "зум": "zoom",
            "тимс": "teams", "нвидиа": "nvidia", "разер": "razer", "юнити": "unity", "блендер": "blender",
            "вар тандер": "war thunder", "вартандер": "war thunder", "ренар": "renard", "летал компани": "lethal company",
            "летал": "lethal company", "кловерпит": "cloverpit", "мафия": "mafia ii: definitive edition", "мафия 2": "mafia ii: definitive edition",
            "танки": "world of tanks", "ворлд оф танкс": "world of tanks", "дедлок": "deadlock", "цива": "sid meier's civilization vi",
            "цивилизация": "sid meier's civilization vi", "римворлд": "rimworld", "фростпанк": "frostpunk", "стардью": "stardew valley",
            "стардью валли": "stardew valley", "айзек": "the binding of isaac: rebirth", "шейпз": "shapez", "вотч догс": "watch_dogs 2",
            "дельта форс": "delta force", "бонго кэт": "bongo cat", "валпейпер": "wallpaper engine", "обои": "wallpaper engine",
            "дота": "dota 2", "кс": "counter-strike 2", "контра": "counter-strike 2", "фортнайт": "fortnite", "гта": "grand theft auto v"}


def find_indexed_app(query: str) -> dict | None:
    q = query.lower().strip()
    q = TRANSLIT.get(q, q)
    apps = apps_index()
    names = {a["name"].lower(): a for a in apps}
    if q in names:
        return names[q]
    starts = [a for n, a in names.items() if n.startswith(q)]
    if starts:
        return min(starts, key=lambda a: len(a["name"]))
    subs = [a for n, a in names.items() if q in n]
    if subs:
        return min(subs, key=lambda a: len(a["name"]))
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.75)
    if close:
        return names[close[0]]
    if re.search("[а-яё]", q):
        lat = _cyr2lat(q)
        flat = {re.sub(r"[^a-z0-9 ]", "", n): n for n in names}
        close = difflib.get_close_matches(lat, list(flat), n=1, cutoff=0.7)
        if not close:
            close = [f for f in flat if f.startswith(lat[:max(5, len(lat) - 2)])][:1]
        if close:
            return names[flat[close[0]]]
    return None


_CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                 "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _cyr2lat(s: str) -> str:
    out = "".join(_CYR.get(c, c) for c in s.lower())
    return re.sub(r"\s+", " ", out).strip()


def exact_indexed_app(query: str) -> dict | None:
    """Only an exact (case/punctuation-insensitive) name match — beats fuzzy rules and the whitelist."""
    norm = lambda s: re.sub(r"[^\wа-яё]+", " ", s.lower()).strip()
    q = norm(TRANSLIT.get(query.lower().strip(), query))
    for a in apps_index():
        if norm(a["name"]) == q:
            return a
    return None


@tool("find_installed_apps", "Найти установленные программы (по меню Пуск). query пустой — показать все",
      {"query": S}, [])
def find_installed_apps(query: str = "") -> str:
    apps = apps_index()
    q = TRANSLIT.get(query.lower().strip(), query.lower().strip())
    hits = [a["name"] for a in apps if q in a["name"].lower()] if q else [a["name"] for a in apps]
    return f"Найдено {len(hits)}: " + ", ".join(sorted(hits)[:80])


_SNAP: dict = {"t": 0.0, "cpu": {}}
_SNAP_LOCK = threading.Lock()


def _pass() -> tuple[float, dict, dict]:
    """One pass over all processes (~2 ms each on Windows): cpu seconds and memory, read together."""
    cpu, info = {}, {}
    for p in psutil.process_iter(["name"]):
        try:
            with p.oneshot():
                ct = p.cpu_times()
                cpu[p.pid] = ct.user + ct.system
                info[p.pid] = (p.info["name"] or "?", p.memory_info().rss)
        except Exception:
            continue
    return time.time(), cpu, info


def _sample_procs() -> dict[str, list[float]]:
    """CPU% (over the time since the previous pass, 0.5–60 s) and RAM of all processes, by name:
    {name: [cpu%, ram_gb, count]}. One pass (~0.8 s) when a recent snapshot exists, else two passes 0.5 s apart."""
    with _SNAP_LOCK:
        prev_t, prev = _SNAP["t"], _SNAP["cpu"]
        t, cpu, info = _pass()
        if not (0.4 <= t - prev_t <= 60):
            prev_t, prev = t, cpu
            time.sleep(0.5)
            t, cpu, info = _pass()
        _SNAP.update(t=t, cpu=cpu)
    dt = max(t - prev_t, 0.1)
    ncpu = psutil.cpu_count() or 1
    agg: dict[str, list[float]] = {}
    for pid, (n, rss) in info.items():
        if n in ("System Idle Process", "Idle"):
            continue
        c = max(0.0, cpu.get(pid, 0) - prev.get(pid, cpu.get(pid, 0))) / dt / ncpu * 100
        a = agg.setdefault(n, [0.0, 0.0, 0])
        a[0] += c
        a[1] += rss / 1e9
        a[2] += 1
    return agg


def warm_procs():
    """Keep a fresh snapshot so «что грузит пк» answers in one pass (called by the monitor every ~30 s)."""
    try:
        _sample_procs()
    except Exception:
        quiet()


def _fmt_procs(agg: dict, sort: str, top: int) -> str:
    key = 1 if sort.lower().startswith(("ram", "mem", "пам", "опер")) else 0
    rows = sorted(agg.items(), key=lambda x: -x[1][key])[:top]
    return "\n".join(f"{n:<28} CPU {v[0]:5.1f}%  RAM {v[1]:5.2f} ГБ" + (f"  ({v[2]} проц.)" if v[2] > 1 else "") for n, v in rows)


@tool("top_processes", "Процессы, которые больше всего нагружают ПК. sort: cpu или ram", {"sort": S, "top": I}, [])
def top_processes(sort: str = "cpu", top: int = 8) -> str:
    return _fmt_procs(_sample_procs(), sort, top)


@tool("kill_process", "Завершить процесс по имени (например chrome.exe). Системные процессы защищены",
      {"name": S}, ["name"], confirm=True)
def kill_process(name: str) -> str:
    target = name.lower().strip()
    if not target.endswith(".exe"):
        target += ".exe"
    if target in PROTECTED:
        return f"{target} — системный/служебный процесс, его завершать нельзя."
    n, denied = 0, 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == target:
                p.terminate()
                n += 1
        except psutil.AccessDenied:
            denied += 1
        except Exception:
            quiet()
    if denied:
        return (f"{target}: {denied} процесс(ов) запущены с правами администратора — без этих прав Renard их не "
                f"завершит, закрой сам." + (f" Остальные {n} завершил." if n else ""))
    return f"Завершил {n} процесс(ов) {target}." if n else f"Процесс {target} не найден."


_radio: dict = {"proc": None, "station": None}


def _find_station(name: str):
    q = name.lower()
    for key, st in RADIO.items():
        if q == key or any(a in q or q in a for a in st.get("aliases", [])):
            return key, st
    return None


@tool("play_radio", "Включить интернет-радио по названию станции (играет в фоне, без окон)", {"station": S}, ["station"])
def play_radio(station: str) -> str:
    found = _find_station(station)
    if not found:
        return f"Станции '{station}' нет в config/radio.json. Есть: {', '.join(RADIO)}"
    key, st = found
    stop_radio()
    try:
        _radio["proc"] = subprocess.Popen(["ffplay", "-nodisp", "-loglevel", "quiet", "-volume", "70", st["url"]],
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        _radio["station"] = key
    except FileNotFoundError:
        os.startfile(st["url"])
        return f"ffplay не найден — открыл {key} в плеере по умолчанию."
    return f"Включаю радио {key}. «Стоп радио» — выключить."


@tool("stop_radio", "Выключить радио")
def stop_radio() -> str:
    p = _radio.get("proc")
    if p and p.poll() is None:
        p.terminate()
        st = _radio.get("station")
        _radio.update(proc=None, station=None)
        return f"Радио {st} выключено."
    return "Радио и так не играет."


def toast(title: str, text: str) -> bool:
    """Windows toast notification (no extra modules)."""
    if os.name != "nt":
        return False
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        f"$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml('<toast><visual><binding template=\"ToastGeneric\">"
        f"<text>{esc(title)}</text><text>{esc(text)}</text></binding></visual></toast>');"
        "$t = [Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($t)"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


@tool("notify", "Показать уведомление Windows", {"title": S, "text": S}, ["text"])
def notify(text: str, title: str = "Renard") -> str:
    return "Уведомление показано." if toast(title, text) else "Не удалось показать уведомление."


_lhm_down_until = 0.0


def lhm_temps() -> dict:
    """If LibreHardwareMonitor runs with 'Remote Web Server' on :8085 — read CPU/GPU/disk temperatures.
    When it is not running, don't retry for 60 s (keeps pc_stats fast)."""
    global _lhm_down_until
    if time.time() < _lhm_down_until:
        return {}
    try:
        data = httpx.get("http://127.0.0.1:8085/data.json", timeout=0.4).json()
    except Exception:
        _lhm_down_until = time.time() + 60
        return {}
    out: dict[str, str] = {}

    def walk(node, path):
        txt = node.get("Text", "")
        if node.get("Type") == "Temperature" or (txt and path.endswith("Temperatures")):
            val = node.get("Value", "")
            if val and any(k in txt for k in ("Package", "Core (Tctl", "Tdie", "GPU Core", "Temperature", "Composite")):
                out[f"{path.split('/')[1] if '/' in path else ''} {txt}".strip()] = val
        for ch in node.get("Children", []):
            walk(ch, f"{path}/{txt}")
    walk(data, "")
    return dict(list(out.items())[:6])


@tool("clean_temp", "Очистить временные файлы (%TEMP%) старше N дней — В КОРЗИНУ", {"days": I}, [], confirm=True)
def clean_temp(days: int = 2) -> str:
    tmp = Path(os.environ.get("TEMP", ""))
    if not tmp.is_dir():
        return "Папка TEMP не найдена."
    cutoff = time.time() - days * 86400
    items = []
    for e in tmp.iterdir():
        try:
            if e.stat().st_mtime < cutoff:
                items.append(str(e))
        except OSError:
            pass
    if not items:
        return "Нечего чистить: нет файлов старше указанного срока."
    lst = DATA_DIR / "clean_list.txt"
    lst.write_text("\n".join(items), encoding="utf-8")
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; $ok=0; foreach($p in (Get-Content -LiteralPath $args[0] -Encoding UTF8))"
          "{ try { if (Test-Path -LiteralPath $p -PathType Container) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p,'OnlyErrorDialogs','SendToRecycleBin') }"
          " else { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin') }; $ok++ } catch {} }; $ok")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"& {{{ps}}} '{lst}'"], capture_output=True, text=True,
                       timeout=600, creationflags=NO_WINDOW)
    return f"Отправил в корзину {r.stdout.strip() or 0} из {len(items)} элементов TEMP (занятые программами пропущены)."


@tool("load_history", "Как был нагружен ПК за последний час (средняя/максимальная загрузка CPU, RAM, GPU, температура)")
def load_history(ctx: dict) -> str:
    agent = ctx.get("agent")
    mon = getattr(agent, "monitor", None)
    return mon.summary() if mon else "Мониторинг не запущен."


@tool("diagnose_pc", "Диагностика ПК одним вызовом: загрузка, топ процессов по CPU и RAM, история нагрузки, диски. "
      "ИСПОЛЬЗУЙ, когда пользователь жалуется: тормозит, лагает, медленно, греется, шумит, вылетает")
def diagnose_pc(ctx: dict) -> str:
    from .pc import pc_stats
    s = pc_stats()
    g = s.get("gpu") or {}
    parts = [f"CPU {s['cpu_%']}% · RAM {s['ram']} · GPU {g.get('load_%', '?')}% VRAM {g.get('vram_used_gb')}/{g.get('vram_total_gb')} ГБ "
             f"{g.get('temp_c', '?')}°C · аптайм {s['uptime_h']} ч",
             "Диски: " + "; ".join(f"{k} {v}" for k, v in s["disks"].items()),
             "Топ по CPU:\n" + _fmt_procs(agg := _sample_procs(), "cpu", 5),
             "Топ по RAM:\n" + _fmt_procs(agg, "ram", 5)]
    mon = getattr(ctx.get("agent"), "monitor", None)
    if mon:
        parts.append(mon.summary())
    if s.get("temps"):
        parts.append("Температуры: " + ", ".join(f"{k} {v}" for k, v in s["temps"].items()))
    return "\n".join(parts)
