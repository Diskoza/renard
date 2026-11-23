"""devkit — the methods a big model uses on this PC, given to Renard as tools.

probe_app   — one call shows everything about a program: window elements (UIA / Win32), exe, settings folders and
              files, registry, whether it runs as admin. The model picks the reliable path from there.
pc_script  — a short script with the nx helper library (see nx.py). Reading is free; anything that changes the PC
              (click, type, write, delete to Recycle Bin, PowerShell changes) needs the user's «да» → pc_script_write.
save_skill  — a solved task becomes a skill: SKILL.md (+ script.py) in this plugin's skills/ — the agent grows itself.
run_skill   — run a saved skill script with parameters.

The read-only check is a guard against accidents by a small model, not a sandbox against malicious code.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from agent.tools import S, tool

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SKILLS = HERE / "skills"
WORK = ROOT / "workspace" / "scripts"
PY = Path(sys.executable).with_name("python.exe") if os.name == "nt" else Path(sys.executable)
NO_WINDOW = 0x08000000
PENDING: dict[str, dict] = {}

CHANGES = re.compile(
    r"\b(set_field|click|press|type_text|write_file|write_config|to_recycle|ps)\s*\("
    r"|\.(write_text|write_bytes|unlink|rmdir|rename|mkdir|touch|chmod)\s*\("
    r"|\bopen\s*\([^)]*,\s*['\"][^'\"]*[wax+]"
    r"|\b(os\.(remove|unlink|rmdir|removedirs|rename|replace|system|popen|startfile|kill|makedirs|mkdir)"
    r"|shutil\.(rmtree|move|copy\w*)|subprocess\.|winreg\.(Set|Delete|Create)\w*|ctypes\."
    r"|httpx\.(post|put|patch|delete)|requests\.(post|put|patch|delete)|\.execute\s*\(\s*['\"]\s*(insert|update|delete|drop|alter|create))",
    re.I)
BANNED = re.compile(r"\b(format\s+[a-z]:|cipher\s+/w|vssadmin|bcdedit|reg\s+delete\s+hklm|Remove-Item\s+.*-Recurse\s+.*C:\\\\?Windows"
                    r"|Set-MpPreference|netsh\s+advfirewall\s+set|Disable-WindowsOptionalFeature|shutil\.rmtree\s*\(\s*['\"]C:)", re.I)
PRELUDE = "import sys, json, os, re, time\nsys.path.insert(0, {plugin!r})\nfrom nx import *\nfrom pathlib import Path\n"


SANDBOXABLE = {"write_file", "write_config", "to_recycle"}
SANDBOX_ROOT = ROOT / "workspace" / "sandbox"


def changes_in(code: str) -> list[str]:
    return sorted({m.group(0).strip(" (")[:30] for m in CHANGES.finditer(code)})


def _sandbox_dir(ctx: dict | None) -> Path:
    sid = re.sub(r"[^\w-]", "_", str((ctx or {}).get("session") or "default"))[:40]
    return SANDBOX_ROOT / sid


def _sandbox_report(box: Path) -> str:
    import difflib
    f = box / "manifest.json"
    if not f.exists():
        return "Песочница пуста."
    m = json.loads(f.read_text("utf-8"))
    out = []
    for real, copy in m["files"].items():
        old = Path(real).read_text("utf-8", "replace").splitlines() if Path(real).exists() else []
        new = Path(copy).read_text("utf-8", "replace").splitlines()
        diff = list(difflib.unified_diff(old, new, real, real + " (новый)", lineterm="", n=1))
        out.append(f"✎ {real}" + (" (новый файл)" if not old else "") + "\n" + "\n".join(diff[2:40]))
    out += [f"🗑 в Корзину: {p}" for p in m["delete"]]
    return "\n".join(out)[:4000] or "Песочница пуста."


def fix_code(code: str) -> str:
    """Typical slips of a small model that are never what it meant: r'C:\\folder\\' (a raw string can't end in \\),
    a leading «from nx import *» (already there), Windows paths in normal strings («C:\\Users» → \\U escape error)."""
    code = re.sub(r"(\br'[^'\n]*?)\\+'", r"\1'", code)
    code = re.sub(r'(\br"[^"\n]*?)\\+"', r'\1"', code)
    code = re.sub(r"(?<![rRbBfF\w])(['\"])([A-Za-z]:\\[^'\"\n]*)\1", lambda m: "r" + m.group(1) + m.group(2).rstrip("\\") + m.group(1), code)
    return code


def _run(code: str, write: bool, args: dict | None = None, timeout: int = 90, sandbox: Path | None = None) -> str:
    code = fix_code(code)
    WORK.mkdir(parents=True, exist_ok=True)
    f = WORK / f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.py"
    head = PRELUDE.format(plugin=str(HERE)) + f"ARGS = json.loads({json.dumps(json.dumps(args or {}, ensure_ascii=False))})\n"
    f.write_text(head + code, encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NX_WRITE": "1" if write else "0", "PYTHONPATH": str(ROOT),
           "NX_SANDBOX": str(sandbox) if sandbox else ""}
    try:
        r = subprocess.run([str(PY), str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(ROOT / "workspace"), env=env, timeout=timeout,
                           creationflags=NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return f"Скрипт не уложился в {timeout} с и остановлен."
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode:
        shift = head.count("\n")
        err = re.sub(r'File "[^"]*run_\w+\.py", line (\d+)',
                     lambda m: f"твой код, строка {max(1, int(m.group(1)) - shift)}", err)
        lines = err.splitlines() if err else []
        mine = [i for i, l in enumerate(lines) if "твой код" in l]
        last = (lines[mine[-1]:mine[-1] + 2] if mine else []) + [l for l in lines[-2:] if l.strip() and not l.startswith("  ")]
        last = last or lines[-4:]
        return (out[-3000:] + "\n" if out else "") + "ОШИБКА:\n" + "\n".join(last) + \
            "\n(исправь одну причину и запусти снова; не повторяй тот же код)"
    return (out[-6000:] or "(скрипт ничего не напечатал — выводи результат через print)")


def _ask(ctx: dict, code: str, args: dict | None, what: list[str], title: str) -> str:
    token = uuid.uuid4().hex[:8]
    PENDING[token] = {"code": code, "args": args or {}, "ts": time.time(), "title": title}
    agent = (ctx or {}).get("agent")
    if agent is not None:
        agent.pending = {"name": "pc_script_write", "args": {"token": token}}
    return (f"{title}: скрипт меняет ПК ({', '.join(what)}). Скажи пользователю коротко, ЧТО именно изменится, "
            f"и попроси ответить «да» (подтверждение уже ждёт). Без «да» ничего не делай.")


@tool("probe_app",
      "Разведка программы перед работой: элементы окна (UI Automation и Win32), путь к exe, запущена ли от админа, "
      "папки и файлы настроек (AppData/ProgramData/Документы), ключи реестра. Используй для новой/незнакомой программы "
      "или когда app_do не справился. app — имя программы или заголовок окна.",
      {"app": S}, ["app"])
async def probe_app(app: str, ctx: dict | None = None) -> str:
    return await asyncio.to_thread(_probe, app)


def _probe(app: str) -> str:
    sys.path.insert(0, str(HERE))
    import nx
    from agent.tools.apps import find_window
    lines = [f"Разведка «{app}»:"]
    w = find_window(app)
    exe = ""
    if w:
        lines.append(f"Окно: «{w['title']}» ({w['proc']}, pid {w['pid']})")
        try:
            import psutil
            exe = psutil.Process(w["pid"]).exe()
            lines.append(f"exe: {exe}")
        except Exception:
            pass
        if _elevated(w["pid"]):
            lines.append("⚠ программа запущена ОТ АДМИНИСТРАТОРА: окно может не отвечать на клики Renard — скажи пользователю.")
        try:
            els = nx.controls(w["hwnd"])
            lines.append(f"Элементов в окне: {len(els)}" + (" (почти пусто — рисованный интерфейс: клавиши/скриншот/файлы)"
                                                           if len(els) < 4 else ""))
            lines += [f"  #{e['id']} {e['type']}: {e['name'][:60]}" + (f" = «{e['value'][:40]}»" if e["value"] else "")
                      for e in els[:45]]
        except Exception as e:
            lines.append(f"Элементы не прочитались: {e}")
    else:
        lines.append("Окно не открыто (open_app, если нужно работать в окне).")
        try:
            from agent.tools.system import find_indexed_app
            a = find_indexed_app(app)
            if a:
                exe = a.get("target") or ""
                lines.append(f"Установлена: {a['name']}" + (f", exe: {exe}" if exe else ""))
        except Exception:
            pass
    names = [app] + ([Path(exe).stem] if exe else []) + ([Path(exe).parent.name] if exe else [])
    dirs = []
    for n in names:
        dirs += [d for d in nx.app_dirs(n) if d not in dirs]
    if exe and str(Path(exe).parent) not in dirs:
        dirs.append(str(Path(exe).parent))
    CFG = ("*.json", "*.ini", "*.cfg", "*.config", "*.xml", "*.vdf", "*.yaml", "*.yml", "*.toml", "*.conf", "*.db", "*.sqlite")
    for d in dirs[:8]:
        files = []
        for pat in CFG:
            files += nx.find_files(d, pat, 15)
        files = sorted(set(files), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)[:10]
        lines.append(f"Папка: {d}" + ("" if files else " (файлов настроек нет)"))
        for p in files:
            try:
                st = os.stat(p)
                lines.append(f"  {p}  ({st.st_size // 1024} КБ, {time.strftime('%d.%m %H:%M', time.localtime(st.st_mtime))})")
            except OSError:
                continue
    try:
        sw = nx.reg_read(r"HKCU\Software")["subkeys"]
        words = [x for x in re.split(r"[\s_\-.]+", " ".join(names).lower()) if len(x) >= 3]
        hits = [k for k in sw if any(x in k.lower().replace(" ", "") for x in words)]
        if hits:
            lines.append("Реестр: " + ", ".join(f"HKCU\\Software\\{k}" for k in hits[:5]))
    except Exception:
        pass
    lines.append("Дальше: готовый инструмент → файл настроек/API через pc_script → app_do по элементам → клавиши. "
                 "После изменения прочитай значение обратно.")
    return "\n".join(lines)


def _elevated(pid: int) -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes as wt
    k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return True
    tok = wt.HANDLE()
    try:
        if not adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):
            return False
        e, n = wt.DWORD(), wt.DWORD()
        adv.GetTokenInformation(tok, 20, ctypes.byref(e), 4, ctypes.byref(n))
        return bool(e.value)
    finally:
        k32.CloseHandle(h)


@tool("pc_script",
      "Выполнить короткий Python-скрипт на ПК (как делает опытный разработчик). Уже импортировано: from nx import * — "
      "windows(), fields(окно), controls(окно), app_dirs(имя), find_files(папка, '*.json'), read_config(путь), reg_read(ключ), "
      "sql_read(база, 'SELECT…'), http_get(url), ps_read('Get-…'), disk(), top_procs(); изменения: set_field(окно, подпись, "
      "значение), click(окно, имя), press('ctrl+s'), type_text(), write_file(), write_config(), to_recycle(путь), ps(). "
      "Результат печатай через print. Чтение выполняется сразу; если скрипт что-то меняет — система спросит «да». "
      "Ошибка → исправь одну причину и запусти снова.",
      {"code": S}, ["code"])
async def pc_script(code: str, ctx: dict | None = None) -> str:
    if BANNED.search(code):
        return "Такое не запускаю (форматирование, системные/защитные настройки, удаление системных папок). Дай пользователю инструкцию."
    what = changes_in(code)
    if what and set(what) <= SANDBOXABLE:
        box = _sandbox_dir(ctx)
        out = await asyncio.to_thread(_run, code, False, None, 90, box)
        return (out + "\n\nПЕСОЧНИЦА (на ПК ещё ничего не изменено):\n" + _sandbox_report(box) +
                "\nПроверь результат; применить на ПК — apply_sandbox (спросит «да»), отменить — apply_sandbox action=clear.")
    if what:
        return _ask(ctx, code, None, what, "Нужно подтверждение")
    return await asyncio.to_thread(_run, code, False, None, 90, _sandbox_dir(ctx))


@tool("apply_sandbox",
      "Песочница правок файлов: action=show — что изменено в копиях (diff); action=apply — перенести изменения на ПК "
      "(старые файлы сохраняются как .bak, удаление — в Корзину; спросит «да»); action=clear — выбросить изменения.",
      {"action": S}, [], confirm=True)
async def apply_sandbox(action: str = "apply", ctx: dict | None = None) -> str:
    import shutil
    box = _sandbox_dir(ctx)
    f = box / "manifest.json"
    a = (action or "apply").lower()
    if a.startswith("show"):
        return _sandbox_report(box)
    if not f.exists():
        return "Песочница пуста — применять нечего."
    if a.startswith(("clear", "cancel", "отмен")):
        shutil.rmtree(box, ignore_errors=True)
        return "Изменения в песочнице выброшены, на ПК ничего не менялось."
    m = json.loads(f.read_text("utf-8"))
    code = ("import shutil, json\nm = json.loads(" + repr(json.dumps(m, ensure_ascii=False)) + ")\n"
            "for real, copy in m['files'].items():\n"
            "    write_file(real, Path(copy).read_text('utf-8'))\n    print('записал', real)\n"
            "for p in m['delete']:\n    to_recycle(p); print('в Корзину', p)\n")
    out = await asyncio.to_thread(_run, code, True)
    if "ОШИБКА" not in out:
        shutil.rmtree(box, ignore_errors=True)
    return out


@tool("pc_script_write",
      "Выполнить скрипт, который МЕНЯЕТ что-то на ПК (после «да» пользователя). Обычно вызывается системой сама после "
      "pc_script; token — из него. Удаление — только to_recycle (в Корзину).",
      {"token": S, "code": S}, [], confirm=True)
async def pc_script_write(token: str = "", code: str = "", ctx: dict | None = None) -> str:
    p = PENDING.pop(token, None) if token else None
    if token and not p:
        return "Подтверждение устарело — запусти задачу заново."
    code = p["code"] if p else code
    if not code.strip():
        return "Нечего выполнять."
    if BANNED.search(code):
        return "Такое не запускаю."
    return await asyncio.to_thread(_run, code, True, p["args"] if p else None)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:48] or f"skill-{uuid.uuid4().hex[:6]}"


@tool("save_skill",
      "Сохранить решённую и ПРОВЕРЕННУЮ задачу как навык, чтобы в следующий раз сделать сразу. name — коротко латиницей; "
      "description — что делает и когда использовать (словами пользователя); notes — как устроено, где настройки, что опасно; "
      "code — скрипт (nx), конкретные значения замени на ARGS['имя'] (например ARGS['secs']); params — какие ARGS нужны.",
      {"name": S, "description": S, "notes": S, "code": S, "params": S}, ["name", "description"])
async def save_skill(name: str, description: str, notes: str = "", code: str = "", params: str = "",
                     ctx: dict | None = None) -> str:
    slug = _slug(name)
    d = SKILLS / slug
    d.mkdir(parents=True, exist_ok=True)
    changes = bool(code and changes_in(code))
    body = [f"---\nname: {slug}\ndescription: {description.strip().replace(chr(10), ' ')}\n---",
            f"# {name}", "", notes.strip() or ""]
    if code:
        (d / "script.py").write_text(code.strip() + "\n", encoding="utf-8")
        example = "{" + params + "}" if params else "{}"
        body += ["", "## Как выполнить",
                 f"Вызови ИНСТРУМЕНТ run_skill с аргументами: name = \"{slug}\", args = '{example}' "
                 f"(подставь нужные значения). Не пиши это как код и не вызывай pc_script.",
                 "Меняет ПК — система сама спросит «да»." if changes else "Только читает — выполняется сразу."]
    body += ["", f"_Сохранён {time.strftime('%d.%m.%Y')} Renard после успешной задачи._"]
    (d / "SKILL.md").write_text("\n".join(body).strip() + "\n", encoding="utf-8")
    try:
        from agent import plugins
        getattr(plugins, "reload_skills", lambda: None)()
    except Exception:
        pass
    return f"Сохранил навык «{slug}» ({'со скриптом' if code else 'описание'}). Скажи пользователю одной строкой."


@tool("run_skill",
      "Запустить сохранённый навык со скриптом (из save_skill). name — имя навыка, args — JSON с параметрами, "
      "например {\"secs\": 1}. Если навык меняет ПК — система спросит «да».",
      {"name": S, "args": S}, ["name"])
async def run_skill(name: str = "", args: str = "", code: str = "", ctx: dict | None = None) -> str:
    if not name and code:
        m = re.search(r"name\s*[=:]\s*[\"']?([\w-]+)", code)
        a = re.search(r"args\s*[=:]\s*'?(\{.*?\})", code, re.S)
        name, args = (m.group(1) if m else ""), (a.group(1) if a else args)
    if isinstance(args, dict):
        args = json.dumps(args, ensure_ascii=False)
    if not name:
        return "Укажи name навыка (run_skill name=…)."
    d = SKILLS / _slug(name)
    f = d / "script.py"
    if not f.exists():
        have = ", ".join(sorted(p.parent.name for p in SKILLS.glob("*/script.py"))) or "нет"
        return f"Нет навыка-скрипта «{name}». Есть: {have}."
    try:
        a = json.loads(args) if args and args.strip() else {}
    except ValueError:
        return "args должен быть JSON, например {\"secs\": 1}."
    code = f.read_text("utf-8")
    what = changes_in(code)
    if what:
        token = uuid.uuid4().hex[:8]
        PENDING[token] = {"code": code, "args": a, "ts": time.time(), "title": name}
        agent = (ctx or {}).get("agent")
        if agent is not None:
            agent.pending = {"name": "pc_script_write", "args": {"token": token}}
        return (f"Навык «{name}» с {a} меняет ПК ({', '.join(what)}). Скажи пользователю, что будет сделано, "
                f"и попроси «да» (подтверждение уже ждёт).")
    return await asyncio.to_thread(_run, code, False, a, 90, _sandbox_dir(ctx))
