"""Node CLI tools re-cut for Renard's small local model: few tools, short Russian schemas, compact answers.

- site_api       — api-anything (https://github.com/goodnight000/api-anything): ~110 sites (YouTube, hh.ru, Habr, GitHub,
                   Steam, Wikipedia, Reddit, IMDb, Google Flights …) as plain read operations, ~1 s a call, no browser.
                   Always local-only: nothing goes to its shared catalog. Writes are not exposed at all.
- site_learn     — teach api-anything a new site from a search-page URL (needs a Chromium browser, ~30-60 s).
- inspect_program— what an .exe/.dll can do: imports grouped into capabilities (network, keyboard hooks, injection …)
                   via rea-agents (https://github.com/morluto/rea), hardening flags, and the real Authenticode
                   signature from Windows (rea cannot see catalog signatures).
- connector_add  — add any npm MCP server as a Renard connector (data/mcp.json), with his «да» first.

Packages are installed once, pinned, into data/node_tools (not the global npm), on first use. The CLI is run as
`node <cli.js>` directly: no npx resolve on every call and no cmd.exe quoting (args go as JSON on stdin).
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..config import DATA_DIR
from . import S, tool

NODE_DIR = DATA_DIR / "node_tools"
PKGS = {
    "api-anything": ("0.4.0", "dist/cli.js"),
    "rea-agents": ("6.9.0", "scripts/rea.mjs"),
}
MAX_OUT = 2500
SEARCH_ENGINES = {"google", "duckduckgo", "ddg", "bing", "yandex", "яндекс", "гугл", "search", "web"}


def _node() -> str:
    n = shutil.which("node")
    if not n:
        raise RuntimeError("Node.js не установлен (нужен Node 22.13+): https://nodejs.org")
    return n


def _ensure(pkg: str) -> Path:
    """Path to the package's CLI; installs the pinned version into data/node_tools the first time."""
    ver, entry = PKGS[pkg]
    cli = NODE_DIR / "node_modules" / pkg / entry
    if cli.exists():
        return cli
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm не найден (ставится вместе с Node.js)")
    NODE_DIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--save-exact", f"{pkg}@{ver}"], cwd=NODE_DIR,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if not cli.exists():
        raise RuntimeError(f"не удалось установить {pkg}: {(r.stderr or r.stdout)[-400:]}")
    return cli


def _run(pkg: str, args: list[str], stdin: str | None = None, timeout: int = 90, env: dict | None = None) -> str:
    cli = _ensure(pkg)
    r = subprocess.run([_node(), str(cli), *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=NODE_DIR, env={**os.environ, **(env or {})})
    return (r.stdout or "").strip() or (r.stderr or "").strip()


def _json(s: str):
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _short(o, n: int = MAX_OUT) -> str:
    s = o if isinstance(o, str) else json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return s if len(s) <= n else s[:n] + " …(обрезано)"


AA_ENV = {"API_ANYTHING_LOCAL_ONLY": "1"}


def _aa(args: list[str], stdin: str | None = None, timeout: int = 90):
    out = _run("api-anything", args, stdin, timeout, AA_ENV)
    return _json(out), out


RU_HINTS = {
    "ваканс": "job", "работ": "job", "видео": "video", "ютуб": "youtube", "погод": "weather", "новост": "news",
    "фильм": "movie", "сериал": "series", "книг": "book", "рецепт": "recipe", "билет": "flight", "авиа": "flight",
    "рейс": "flight", "отел": "stay", "жиль": "stay", "музык": "music", "игр": "steam", "курс": "course",
    "акци": "stock", "валют": "currency", "карт": "map", "статья": "article", "статьи": "article", "код": "github",
    "пакет": "package", "модел": "model", "перевод": "dictionary", "слов": "dictionary", "цитат": "quote",
}


def _ops_text(site: str) -> str:
    d, raw = _aa(["ops", site])
    if not isinstance(d, dict) or not d.get("operations"):
        return f"Сайта «{site}» нет. " + _sites_text(site)
    lines = [f"{site}: операции (вызов: site_api(site=\"{site}\", op=..., args={{...}}))"]
    for o in d["operations"]:
        if not o.get("readOnly", True):
            continue
        ps = ", ".join(p.split(" (")[0] for p in o.get("params", []))
        lines.append(f"- {o['name']}({ps}): {o.get('description', '')[:110]}")
    if d.get("notes"):
        lines.append("Заметки: " + d["notes"].replace("\n", " ")[:400])
    return "\n".join(lines)


def _sites_text(query: str = "") -> str:
    d, raw = _aa(["sites"])
    if not isinstance(d, list):
        return "api-anything не ответил: " + _short(raw, 300)
    words = [w for w in re.findall(r"\w{3,}", (query or "").lower())]
    words += [en for ru, en in RU_HINTS.items() for w in words if w.startswith(ru)]
    if words:
        hit = [s for s in d if any(w in (s["name"] + " " + s.get("description", "")).lower() for w in words)]
        if hit:
            return "Подходящие сайты:\n" + "\n".join(f"- {s['name']}: {s.get('description', '')[:120]}" for s in hit[:12])
    return ("Сайты (site_api(site=имя) — его операции): " + ", ".join(s["name"] for s in d) +
            ". Новый сайт можно выучить: site_learn.")


@tool("site_api",
      "Данные с сайтов без браузера (~1 с): YouTube, hh.ru вакансии, Хабр, GitHub, Steam, Википедия, Reddit, IMDb, "
      "Google Flights, Spotify, PyPI, arXiv и ещё ~100. Без site — список сайтов (query сужает). С site без op — "
      "его операции и параметры. С site+op — вызов, args — объект параметров. Только чтение.",
      {"site": S, "op": S, "args": {"type": "object"}, "query": S})
def site_api(site: str = "", op: str = "", args: dict | str | None = None, query: str = "") -> str:
    site, op = (site or "").strip().lower(), (op or "").strip()
    if isinstance(args, str):
        args = _json(args) if args.strip().startswith("{") else {}
    if re.sub(r"^www\.|\.(com|ru|pl|net)$", "", site) in SEARCH_ENGINES:
        q = query or next((str(v) for v in (args or {}).values() if v), "")
        if q:
            import asyncio
            from .web import web_search
            return asyncio.run(web_search(q))
    if not site:
        return _sites_text(query)
    if not op:
        return _ops_text(site)
    if not args and query and "search" in op.lower():
        args = {"q": query}
    d, raw = _aa(["call", site, op, "--json", "-", "--max-chars", "6000"], json.dumps(args or {}, ensure_ascii=False))
    if not isinstance(d, dict):
        return "Ошибка api-anything: " + _short(raw, 400)
    if not d.get("ok"):
        why = d.get("reason") or d.get("class") or "ошибка"
        if d.get("class") == "input":
            return f"Ошибка: {why}. Исправь и вызови снова.\n" + _ops_text(site)
        retry = {"after_wait": "попробуй позже", "no": "повтор не поможет"}.get(d.get("retry"), "")
        return f"Сайт не ответил: {why}" + (f" ({retry})" if retry else "")
    data = d.get("data")
    more = " Есть ещё результаты (следующая страница: " + json.dumps(d["nextPage"], ensure_ascii=False) + ")." \
        if d.get("hasMore") and d.get("nextPage") else ""
    return _short(data) + more


@tool("site_learn",
      "Научиться читать новый сайт (страница поиска/карточки) для site_api. url — адрес с {q} на месте запроса, "
      "examples — три РАЗНЫХ значения для {q}. Открывает браузер, ~1 мин.",
      {"url": S, "examples": {"type": "array", "items": S}}, ["url", "examples"], modes=("medium", "high"))
def site_learn(url: str, examples: list | str) -> str:
    slots = re.findall(r"\{(\w+)\}", url or "")
    if len(set(slots)) != 1:
        return "В url должен быть ровно один параметр в фигурных скобках, например https://site.com/search?q={q}"
    if isinstance(examples, str):
        examples = [x.strip() for x in re.split(r"[,;\n]", examples) if x.strip()]
    if len(examples) < 3 or len(set(examples)) < 3:
        return "Нужны три разных примера значения (например три разных поисковых запроса)."
    p = slots[0]
    d, raw = _aa(["learn", url, "--args", f"{p}={examples[0]}", "--args2", f"{p}={examples[1]}",
                  "--args3", f"{p}={examples[2]}"], timeout=300)
    if not isinstance(d, dict):
        return "Не выучил: " + _short(raw, 500)
    if d.get("ok") is False:
        return "Не выучил: " + str(d.get("reason") or d.get("class"))
    sig = d.get("signature") or {}
    name = f"{sig.get('site', '?')}.{sig.get('op', '?')}" if isinstance(sig, dict) else str(sig)[:80]
    return f"Выучил: {name}. Ответ для «{examples[0]}»: " + _short(d.get("data"), 1500)


CAPS = [
    ("сеть / интернет", r"^(ws2_32|wsock32|wininet|winhttp|urlmon)\.dll$|^(WSAStartup|InternetOpen|WinHttpOpen|URLDownloadToFile)"),
    ("перехват клавиатуры/мыши", r"^(SetWindowsHookEx|GetAsyncKeyState|RegisterRawInputDevices)"),
    ("внедрение в чужие процессы", r"^(WriteProcessMemory|CreateRemoteThread|VirtualAllocEx|QueueUserAPC|NtUnmapViewOfSection|SetThreadContext)"),
    ("управление чужими процессами", r"^(OpenProcess|TerminateProcess|DebugActiveProcess)$"),
    ("автозапуск / службы", r"^(CreateService|OpenSCManager|ChangeServiceConfig)"),
    ("запись в реестр", r"^(RegSetValue|RegCreateKey|RegDeleteKey)"),
    ("запуск других программ", r"^(CreateProcess|ShellExecute|WinExec)"),
    ("шифрование", r"^(CryptEncrypt|CryptDecrypt|BCryptEncrypt|BCryptDecrypt)$"),
    ("буфер обмена", r"^(GetClipboardData|SetClipboardData)$"),
    ("повышение привилегий", r"^(AdjustTokenPrivileges|ImpersonateLoggedOnUser)$"),
    ("проверяет, запущена ли под отладчиком (бывает и у обычных программ)", r"^(IsDebuggerPresent|CheckRemoteDebuggerPresent)$"),
    ("снимки экрана", r"^(PrintWindow|BitBlt)$"),
]
HARDEN = {"dynamic_base": "ASLR", "nx_compat": "DEP", "guard_cf": "Control Flow Guard", "high_entropy_va": "ASLR 64"}


def _signature(path: str) -> str:
    """Real Authenticode check (embedded and catalog signatures) — the path goes through env, never into the command."""
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath $env:NX_PATH; "
          "[pscustomobject]@{st=[string]$s.Status; who=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30, env={**os.environ, "NX_PATH": path})
        d = _json(r.stdout.strip()) or {}
    except (OSError, subprocess.TimeoutExpired):
        return "подпись: не проверена"
    st, who = d.get("st", ""), d.get("who") or ""
    cn = (re.search(r"CN=\"?([^,\"]+)", who) or [None, who])[1]
    return {"Valid": f"подпись: действительна — {cn}", "NotSigned": "подпись: НЕТ (не подписан)",
            "HashMismatch": "подпись: НЕ СОВПАДАЕТ — файл изменён после подписи!",
            "NotTrusted": f"подпись: есть, но издатель не доверенный ({cn})"}.get(st, f"подпись: {st or 'неизвестно'}")


@tool("inspect_program",
      "Проверить программу/файл .exe .dll: кем подписана, что умеет (сеть, перехват клавиатуры, внедрение в процессы, "
      "автозапуск…), защита. Сам файл НЕ запускается. Для «безопасна ли программа», «что делает этот exe».",
      {"path": S}, ["path"])
def inspect_program(path: str) -> str:
    p = Path(os.path.expandvars((path or "").strip().strip('"'))).expanduser()
    if not p.is_file():
        return f"Файла нет: {p}"
    with open(p, "rb") as f:
        if f.read(2) != b"MZ":
            return f"{p.name} — не программа Windows (.exe/.dll). Проверяю только их."
    out = [f"{p.name} ({p.stat().st_size // 1024} КБ)", _signature(str(p))]
    imp = _json(_run("rea-agents", ["inspect-pe-imports", str(p), "--format", "json"], timeout=120))
    res = (imp or {}).get("normalized_result") or {}
    dlls = res.get("imports", []) + res.get("delay_imports", [])
    if dlls:
        names = [d.get("name", "") for d in dlls]
        funcs = [fn.get("name") or "" for d in dlls for fn in d.get("functions", [])]
        out.append(f"архитектура: {res.get('architecture', '?')}; импортирует {len(funcs)} функций из {len(names)} DLL")
        found = []
        for label, rx in CAPS:
            hits = sorted({x for x in names + funcs if re.search(rx, x, re.I)})
            if hits:
                found.append(f"- {label}: {', '.join(hits[:4])}")
        out.append("умеет (по импортам):\n" + "\n".join(found) if found else "особых возможностей в импортах нет")
        if len(funcs) < 15 and any(re.match(r"(LoadLibrary|GetProcAddress)", f) for f in funcs):
            out.append("⚠ очень мало импортов + динамическая загрузка: похоже на упакованную/сжатую программу — "
                       "настоящие возможности скрыты")
    else:
        out.append("импорты не прочитаны" + (": " + _short((imp or {}).get("message", ""), 150) if imp else ""))
    hd = _json(_run("rea-agents", ["inspect-binary-hardening", str(p), "--format", "json"], timeout=120))
    rows = ((((hd or {}).get("normalized_result") or {}).get("images") or [{}])[0]).get("rows", [])
    if rows:
        st = {r["property"]: r["state"] for r in rows}
        on = [v for k, v in HARDEN.items() if st.get(k) == "enabled"]
        off = [v for k, v in HARDEN.items() if st.get(k) == "disabled"]
        out.append("защита: " + (", ".join(on) or "нет") + (f"; выключено: {', '.join(off)}" if off else ""))
    out.append("(импорты — то, что программа МОЖЕТ вызвать; это не приговор: браузеру сеть нужна, вирусу — тоже)")
    return "\n".join(out)


NPM_NAME = re.compile(r"^(@[a-z0-9][\w.~-]*/)?[a-z0-9][\w.~-]*(@[\w.^~-]+)?$")


@tool("connector_add",
      "Подключить MCP-сервер из npm как коннектор Renard (например «подключи коннектор @modelcontextprotocol/server-memory»). "
      "package — имя npm-пакета, args — доп. аргументы запуска. Система спросит подтверждение.",
      {"package": S, "name": S, "args": {"type": "array", "items": S}}, ["package"], confirm=True)
async def connector_add(package: str, name: str = "", args: list | str | None = None) -> str:
    import asyncio
    from ..mcp_client import HUB, load_cfg, save_cfg
    package = (package or "").strip()
    if package.startswith("npx "):
        parts = [x for x in package.split()[1:] if x != "-y"]
        package, args = parts[0], parts[1:] + (args if isinstance(args, list) else [])
    if not NPM_NAME.match(package):
        return f"«{package}» не похоже на имя npm-пакета."
    if isinstance(args, str):
        args = args.split()
    if not shutil.which("npx"):
        return "npx не найден: установи Node.js (https://nodejs.org)."
    name = re.sub(r"[^a-z0-9_-]+", "-", (name or package.split("/")[-1].split("@")[0]).lower()).strip("-")
    cfg = load_cfg()
    cfg.setdefault("servers", {})[name] = {"command": "npx", "args": ["-y", package, *(args or [])], "env": {},
                                           "enabled": True}
    save_cfg(cfg)
    await HUB.restart(name)
    s = HUB.servers.get(name)
    for _ in range(180):
        if not s or s.status in ("ready", "error"):
            break
        await asyncio.sleep(0.5)
    if s and s.status == "ready":
        return (f"Коннектор «{name}» подключён: {len(s.tools)} инструментов ({', '.join(t['name'] for t in s.tools[:10])}"
                f"{'…' if len(s.tools) > 10 else ''}). Вызывать через mcp_call(server=\"{name}\", …).")
    err = s.error if s else "не запустился"
    return (f"Коннектор «{name}» записан, но пока не готов ({s.status if s else '?'}: {err[:300]}). "
            f"Лог: data\\mcp_{name}.log. Если серверу нужна подкоманда (например «mcp»), добавь её в args.")
