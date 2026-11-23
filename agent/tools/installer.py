"""Tools: install_app (install / update programs through winget) and download_file (a file from a link into Downloads).

Permission: his own message saying «скачай / установи / обнови X» IS the «да» — then it just does it. Asked by the
model on its own (or mentioned in passing) — it stops and waits for the usual «да» (agent.pending), with a one-time
token so the model cannot fake the confirmation."""
import os
import re
import secrets
import subprocess
from pathlib import Path

from . import S, tool
from ..logs import quiet

ASKED = re.compile(r"(?i)\b(установи|поставь|скачай|загрузи|обнови|переустанови|install|download|update|upgrade|"
                   r"zainstaluj|pobierz|ściągnij|zaktualizuj)\w*")
_TOKENS: set[str] = set()
SAME = {"java": ["jdk", "jre", "temurin", "corretto", "openjdk", "zulu"], "джава": ["java", "jdk", "jre", "temurin"],
        "питон": ["python"], "python": ["python"], "node": ["nodejs"], "дискорд": ["discord"], "стим": ["steam"],
        "хром": ["chrome"], "обс": ["obs"]}
WINGET_FLAGS = ["--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


def _allowed(ctx: dict | None, what: str) -> bool:
    """His last message asks for it in words (and is about this program, not something else)."""
    said = str((ctx or {}).get("user_text") or "")
    if not ASKED.search(said):
        return False
    words = [w for w in re.findall(r"[^\W\d_]{3,}", what.lower()) if w not in ("http", "https", "www", "com", "download")]
    low = said.lower()
    lat = low.translate(_LAT).replace("dzh", "j").replace("zh", "j")
    def norm(s):
        return s.replace("th", "t").replace("ph", "f").replace("y", "i").replace("w", "v").replace("c", "k").replace("j", "dj")
    toks = norm(lat).split()
    return not words or any(w[:4] in low or any(t.startswith(norm(w)[:3]) for t in toks) for w in words)


_LAT = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
                      "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
                      "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sh", "ы": "y", "э": "e",
                      "ю": "yu", "я": "ya", "ь": "", "ъ": ""})


def _ask(ctx: dict | None, name: str, args: dict, what: str) -> str:
    agent = (ctx or {}).get("agent")
    tok = secrets.token_hex(4)
    _TOKENS.add(tok)
    if agent is not None:
        agent.pending = {"name": name, "args": {**args, "_ok": tok}}
    return f"Нужно подтверждение: {what}. Ответь «да» — сделаю."


def _confirmed(args_ok: str) -> bool:
    if args_ok and args_ok in _TOKENS:
        _TOKENS.discard(args_ok)
        return True
    return False


def _winget(args: list[str], timeout: int = 900) -> str:
    try:
        r = subprocess.run(["winget", *args], capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return "ОШИБКА: winget не найден (нужен «Установщик приложений» из Microsoft Store)"
    except subprocess.TimeoutExpired:
        return "ОШИБКА: winget не уложился в время (установка может ещё идти в фоне)"
    out = r.stdout or b""
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            text = out.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = out.decode("utf-8", "replace")
    text = "\n".join(seg.split("\r")[-1] for seg in text.splitlines())
    text = re.sub(r"[█▒░]{3,}.*", "", text)
    text = re.sub(r"(?m)^\s*[-\\|/]\s*$", "", text)
    return f"(код {r.returncode})\n" + text.strip()


def _table(text: str) -> list[dict]:
    """winget list/search/upgrade table → rows {name, id, version, available} by the header's column positions."""
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if re.fullmatch(r"-{10,}", lines[i].strip()):
            head = lines[i - 1]
            cols = [m.start() for m in re.finditer(r"\S+", head)]
            names = [h.lower() for h in head.split()]
            rows = []
            for ln in lines[i + 1:]:
                if not ln.strip() or re.match(r"^\d+ (пакет|package|upgrade)", ln.strip()):
                    continue
                cells = [ln[a:b].strip() for a, b in zip(cols, cols[1:] + [None])]
                if len(cells) >= 3:
                    rows.append({"name": cells[0], "id": cells[1], "version": cells[2],
                                 "available": cells[3] if len(cells) > 3 and names[3:4] and names[3] not in ("source", "источник")
                                 else ""})
            return rows
    return []


@tool("install_app",
      "Установить или ОБНОВИТЬ программу на этом ПК через winget (сам скачивает и ставит: Java, Python, Discord, "
      "OBS, 7-Zip, драйверы-утилиты и т.д.). name — программа своими словами. action: auto (обновить, если уже "
      "стоит, иначе установить), search (только показать варианты и версии), install, upgrade. Если пользователь сам "
      "написал «установи/скачай/обнови» — это и есть разрешение.",
      {"name": S, "action": S, "id": S}, ["name"])
def install_app(name: str, action: str = "auto", id: str = "", ctx: dict | None = None, _ok: str = "") -> str:
    action = (action or "auto").lower()
    q = id or name
    qw = [w for w in re.findall(r"\w{3,}", q.lower())]
    qw += [s for w in qw for s in SAME.get(w, [])]
    listed = _table(_winget(["list", q, *WINGET_FLAGS[1:]], 120))
    installed = [r for r in listed
                 if id or not qw or any(w in (r["name"] + " " + r["id"]).lower() for w in qw)]
    maybe = [r for r in listed if r not in installed]
    also = ("\n(По тегам winget нашлось ещё — возможно, тоже оно: "
            + "; ".join(f"{r['name']} [{r['id']}] {r['version']}" + (f" → {r['available']}" if r["available"] else "")
                        for r in maybe[:6]) + ". Если это то же самое — вызови install_app с id.)") if maybe else ""
    found = _table(_winget(["search", q, *WINGET_FLAGS[1:]], 120)) if not id else []
    if action == "search":
        lines = [f"- {r['name']} [{r['id']}] {r['version']}" + (f" → есть {r['available']}" if r['available'] else "")
                 for r in installed] or ["(не установлено)"]
        return ("Установлено:\n" + "\n".join(lines) + "\n\nМожно поставить (winget):\n"
                + "\n".join(f"- {r['name']} [{r['id']}] {r['version']}" for r in found[:10]) + also)
    todo: list[tuple[str, str, str]] = []
    if action in ("auto", "upgrade"):
        for r in installed:
            if r["available"] and (not id or r["id"] == id):
                todo.append(("upgrade", r["id"], f"{r['name']} {r['version']} → {r['available']}"))
    if not todo and action in ("auto", "install"):
        if installed and action == "auto" and not id:
            return ("Уже стоит последняя версия: " + "; ".join(f"{r['name']} {r['version']}" for r in installed)
                    + "\n(Новее в winget нет. Нужна другая линейка — например JDK 25 — скажи, поставлю её отдельно.)")
        pick = id or (found[0]["id"] if found else "")
        if not pick:
            return f"В winget не нашёл «{name}». Могу найти официальный сайт и скачать установщик (download_file)."
        todo.append(("install", pick, next((f"{r['name']} {r['version']}" for r in found if r["id"] == pick), pick)))
    if not todo:
        return "Нечего делать: " + ("; ".join(f"{r['name']} {r['version']}" for r in installed) or "ничего не найдено")
    what = "; ".join(f"{'обновить' if v == 'upgrade' else 'установить'} {lbl}" for v, _, lbl in todo)
    if ctx is not None and _allowed(ctx, name):
        ctx["_install_ok"] = True
    if not ((ctx or {}).get("_install_ok") or _confirmed(_ok)):
        return _ask(ctx, "install_app", {"name": name, "action": action, "id": id}, what) + also
    out = []
    for verb, pid, label in todo:
        args = [verb, "--id", pid, "--exact", "--silent", *WINGET_FLAGS]
        res = _winget(args)
        if not _succeeded(res) and re.search(r"1603|0x8a150030|0x8a15000f|elevat|administrator|администратор|отказано|denied", res, re.I):
            res = _winget_admin(args) + "\n(повтор с правами администратора)"
        ok = _succeeded(res)
        out.append(f"{'✅' if ok else '⚠ НЕ ВЫШЛО'} {verb} {label}\n{res[-600:]}")
    after = _table(_winget(["list", q, *WINGET_FLAGS[1:]], 120))
    now = {r["id"]: r for r in after}
    check = []
    for verb, pid, label in todo:
        r = now.get(pid)
        if r and r["available"]:
            check.append(f"⚠ {r['name']}: всё ещё {r['version']} (есть {r['available']}) — НЕ обновилось")
        elif r:
            check.append(f"✅ {r['name']}: теперь {r['version']}")
    return ("\n\n".join(out) + "\n\nПРОВЕРКА после установки:\n" + "\n".join(check or ["?"])
            + "\n(Говори пользователю только то, что в ПРОВЕРКЕ.)" + also)


def _succeeded(res: str) -> bool:
    return "(код 0)" in res or bool(re.search(r"(?i)успешно установ|successfully installed|успешно обнов", res))


def _winget_admin(args: list[str], timeout: int = 900) -> str:
    """winget in an elevated PowerShell (UAC prompt), output through a temp file."""
    import tempfile
    import time
    log = Path(tempfile.gettempdir()) / f"renard_winget_{int(time.time())}.txt"
    inner = "winget " + " ".join(f"'{a}'" for a in args) + f" *> '{log}'; exit $LASTEXITCODE"
    ps = ["powershell", "-NoProfile", "-Command",
          f"$p = Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
          f"-ArgumentList '-NoProfile','-Command',\"{inner}\"; exit $p.ExitCode"]
    try:
        r = subprocess.run(ps, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        code = r.returncode
    except subprocess.TimeoutExpired:
        return "ОШИБКА: установка с правами администратора не уложилась во время"
    text = ""
    try:
        raw = log.read_bytes()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
        log.unlink()
    except Exception:
        quiet()
    if code != 0 and not text:
        return f"(код {code}) окно «Разрешить изменения» отклонено или закрыто"
    return f"(код {code})\n" + re.sub(r"[█▒░]{3,}.*", "", text).strip()[-1500:]


@tool("download_file",
      "Скачать файл по прямой ссылке в папку Загрузки (установщик, архив, документ). Если пользователь сам "
      "написал «скачай» — это разрешение. Возвращает путь к файлу. Запускать скачанное — отдельно, с его «да».",
      {"url": S, "name": S}, ["url"])
def download_file(url: str, name: str = "", ctx: dict | None = None, _ok: str = "") -> str:
    import httpx
    if not re.match(r"https?://", url or ""):
        return "Нужна прямая ссылка http(s)://"
    if not (_allowed(ctx, url + " " + name) or _confirmed(_ok)):
        return _ask(ctx, "download_file", {"url": url, "name": name}, f"скачать {url}")
    dest_dir = Path(os.path.expanduser("~")) / "Downloads"
    fname = re.sub(r"[\\/:*?\"<>|]", "_", name or url.split("?")[0].rstrip("/").split("/")[-1] or "download")
    dest = dest_dir / fname
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            cd = r.headers.get("content-disposition", "")
            m = re.search(r'filename="?([^";]+)', cd)
            if m and not name:
                dest = dest_dir / re.sub(r"[\\/:*?\"<>|]", "_", m.group(1))
            if "text/html" in r.headers.get("content-type", "") and dest.suffix.lower() not in (".html", ".htm"):
                return "По ссылке веб-страница, а не файл. Нужна прямая ссылка на скачивание (fetch_page поможет её найти)."
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
                    size += len(chunk)
    except Exception as e:
        return f"Не скачалось: {type(e).__name__}: {e}"
    return f"Скачал: {dest} ({size / 1048576:.1f} МБ)"
