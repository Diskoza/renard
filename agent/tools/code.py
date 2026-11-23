"""Stage 4: running code. Whitelisted programs only, inside allowed folders, with timeouts. No shell."""
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import I, S, tool
from .files import WORKSPACE, safe
from ..logs import quiet

ALLOWED = {"python", "py", "pip", "pytest", "node", "npm", "npx", "git", "php", "java", "javac", "dotnet", "go",
           "cargo", "rustc", "gcc", "g++", "tsc", "deno", "bun"}
BLOCKED_ARGS = [("git", "push"), ("git", "reset"), ("git", "clean"), ("git", "rebase"), ("git", "checkout"),
                ("npm", "publish"), ("pip", "uninstall"), ("npm", "uninstall")]
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
VENV_PY = sys.executable


def _resolve(prog: str) -> str | None:
    if prog in ("python", "py"):
        return VENV_PY
    if prog == "pip":
        return None
    return shutil.which(prog) or shutil.which(prog + ".cmd") or shutil.which(prog + ".exe")


def _tail(text: str, n: int = 6000) -> str:
    return text if len(text) <= n else "…(начало обрезано)…\n" + text[-n:]


@tool("run_command", "Запустить команду разработки (python, node, npm, npx, pytest, git, php, java…) БЕЗ shell, "
      "в папке cwd (по умолчанию рабочая папка). Пример: 'python main.py', 'node app.js', 'python -m pytest -q', "
      "'git status'. Возвращает код выхода, stdout, stderr. Используй, чтобы проверить код после записи. "
      "Приложение/сервер, который работает долго (npm start, npm run dev, electron ., python app.py с окном), — "
      "background=true: запустится, через ~15 с скажет, работает ли и есть ли ошибки, и останется открытым.",
      {"command": S, "cwd": S, "timeout": I, "background": {"type": "boolean"}}, ["command"], modes=("medium", "high"))
def run_command(command: str, cwd: str = "", timeout: int = 60, background: bool = False) -> str:
    try:
        args = shlex.split(command.replace("\\", "/"), posix=True)
    except ValueError as e:
        return f"Не разобрал команду: {e}"
    if not args:
        return "Пустая команда."
    prog = Path(args[0]).name.lower().removesuffix(".exe").removesuffix(".cmd")
    if prog in ("taskkill", "kill", "pkill", "stop-process"):
        return stop_started(cwd)
    if prog not in ALLOWED:
        return (f"Программа '{prog}' не в белом списке. Разрешены: {', '.join(sorted(ALLOWED))}. Остановить то, что ты "
                f"запустил, — stop_started; собрать .exe — npx electron-builder / python -m PyInstaller.")
    if any(prog == a and b in args[1:2] for a, b in BLOCKED_ARGS):
        return f"Команда '{prog} {args[1]}' заблокирована (может потерять данные). Попроси пользователя сделать это вручную."
    if prog == "pip":
        args = [VENV_PY, "-m", "pip"] + args[1:]
    elif prog == "pytest":
        args = [VENV_PY, "-m", "pytest"] + args[1:]
    else:
        exe = _resolve(prog)
        if not exe:
            return f"'{prog}' не установлен на этом ПК."
        args = [exe] + args[1:]
    workdir = safe(cwd) if cwd else WORKSPACE
    if workdir.is_file():
        workdir = workdir.parent
    workdir.mkdir(parents=True, exist_ok=True)
    timeout = max(5, min(int(timeout or 60), 300))
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    background = str(background).strip().lower() in ("true", "1", "yes", "да")
    long_run = background or bool(LONG_RUN.search(command))
    key = (str(workdir).lower(), command.strip().lower())
    old = _BG.pop(key, None)
    if old is not None and old.poll() is None:
        _kill_tree(old.pid)
    log_out = tempfile.NamedTemporaryFile("w+b", suffix=".out", delete=False)
    log_err = tempfile.NamedTemporaryFile("w+b", suffix=".err", delete=False)
    t0 = time.time()
    p = subprocess.Popen(args, cwd=str(workdir), stdout=log_out, stderr=log_err, stdin=subprocess.DEVNULL, env=env,
                         creationflags=NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    wait = min(timeout, 15) if long_run else timeout
    try:
        code = p.wait(timeout=wait)
        running = False
    except subprocess.TimeoutExpired:
        code, running = None, True
    dt = time.time() - t0
    out_txt, err_txt = _read(log_out), _read(log_err)
    if running and long_run:
        _BG[key] = p
        res = [f"$ {command}   (папка {workdir})",
               f"Процесс запущен и работает уже {dt:.0f} с (PID {p.pid}); сам не завершается — для приложения/сервера "
               f"это нормально. Ошибок в выводе: {'есть, см. stderr' if err_txt.strip() else 'нет'}.",
               _window_report(p.pid)]
    elif running:
        _kill_tree(p.pid)
        res = [f"$ {command}   (папка {workdir})",
               f"Таймаут {timeout} с — процесс и всё, что он запустил, остановлены (бесконечный цикл, ожидание ввода? "
               f"Если это приложение/сервер, который должен работать дальше, — запусти с background=true)."]
    else:
        res = [f"$ {command}   (папка {workdir}, {dt:.1f} с)", f"код выхода: {code}"]
    if out_txt.strip():
        res.append("stdout:\n" + _tail(out_txt.strip()))
    if err_txt.strip():
        res.append("stderr:\n" + _tail(err_txt.strip(), 4000))
    return "\n".join(res)


LONG_RUN = __import__("re").compile(r"(?i)\b(npm|pnpm|yarn|bun)\s+(run\s+)?(start|dev|serve|preview|electron)\b|"
                                    r"\belectron\b|\bvite\b(?!\s+build)|\bnext\s+dev\b|\bnodemon\b|"
                                    r"\buvicorn\b|\bflask\s+run\b|manage\.py\s+runserver|\bhttp\.server\b")
_BG: dict = {}


def _tree_pids(pid: int) -> set:
    try:
        import psutil
        pr = psutil.Process(pid)
        return {pid} | {c.pid for c in pr.children(recursive=True)}
    except Exception:
        return {pid}


def _window_report(pid: int) -> str:
    """What the started app actually SHOWS: its windows and whether they are blank (one colour) — «запустил,
    работает» was claimed while the Electron window was an empty dark rectangle."""
    try:
        import ctypes
        from ctypes import wintypes
        import psutil
        from PIL import ImageGrab, ImageStat
        pids = _tree_pids(pid)
        u = ctypes.windll.user32
        wins = []

        def cb(h, _):
            if u.IsWindowVisible(h):
                p = wintypes.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(p))
                if p.value in pids:
                    r = wintypes.RECT()
                    u.GetWindowRect(h, ctypes.byref(r))
                    if r.right - r.left > 150 and r.bottom - r.top > 100:
                        n = ctypes.create_unicode_buffer(256)
                        u.GetWindowTextW(h, n, 256)
                        wins.append((h, n.value, (r.left, r.top, r.right, r.bottom)))
            return True
        u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
        if not wins:
            if any(psutil.pid_exists(x) for x in pids):
                return ("ОКНА НЕТ: процесс жив, но видимого окна у него нет (сервер/фон — норм; если это должно быть "
                        "приложение с окном — оно не открылось, ищи ошибку в stderr/логах).")
            return "Процесс уже завершился — приложение НЕ работает, смотри stderr."
        out = []
        for h, title, (l, t, r, b) in wins[:3]:
            u.SetForegroundWindow(h)
            time.sleep(0.4)
            img = ImageGrab.grab(bbox=(l + 8, t + 40, r - 8, b - 8), all_screens=True).convert("L").resize((200, 120))
            sd = ImageStat.Stat(img).stddev[0]
            state = ("ПУСТОЕ — почти одноцветное, интерфейс НЕ отрисовался (ошибка в коде страницы/renderer: открой "
                     "DevTools-консоль или добавь вывод ошибок; не говори пользователю, что всё работает)") if sd < 4 \
                else "что-то нарисовано (проверь глазами look_at_window, то ли это, что нужно)"
            out.append(f"Окно «{title or '(без заголовка)'}» {r - l}x{b - t}: {state}.")
        return "\n".join(out)
    except Exception as e:
        return f"(окно проверить не удалось: {type(e).__name__})"


@tool("stop_started", "Остановить программы/серверы, которые ТЫ запустил через run_command (npm start, electron, dev-сервер…) "
      "— например, чтобы пересобрать или запустить заново. cwd — папка проекта (пусто = все запущенные тобой). "
      "Чужие программы пользователя этим не закрыть.", {"cwd": S}, [], modes=("medium", "high"))
def stop_started(cwd: str = "") -> str:
    import psutil
    want = str(safe(cwd)).lower() if cwd else ""
    stopped = []
    for key, p in list(_BG.items()):
        if want and not key[0].startswith(want):
            continue
        if p.poll() is None:
            _kill_tree(p.pid)
            stopped.append(f"{key[1]} (PID {p.pid})")
        _BG.pop(key, None)
    if want:
        for pr in psutil.process_iter(["pid", "name", "exe", "cwd"]):
            try:
                loc = ((pr.info.get("exe") or "") + "|" + (pr.info.get("cwd") or "")).lower()
                if (pr.info["name"] or "").lower() in ("code.exe", "explorer.exe", "cmd.exe", "powershell.exe",
                                                       "pwsh.exe", "windowsterminal.exe", "conhost.exe"):
                    continue
                if want in loc and pr.pid != os.getpid():
                    _kill_tree(pr.pid)
                    stopped.append(f"{pr.info['name']} (PID {pr.pid})")
            except Exception:
                continue
    return ("Остановил: " + ", ".join(stopped)) if stopped else "Запущенных мной процессов там нет."


def _kill_tree(pid: int):
    """Stop a process AND its children (npm → node → electron): killing only npm left electron and the pipes alive."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15,
                       creationflags=NO_WINDOW)
    except Exception:
        quiet()


def _read(f) -> str:
    try:
        f.flush()
        f.close()
        data = Path(f.name).read_bytes()
    except Exception:
        return ""
    try:
        Path(f.name).unlink(missing_ok=True)
    except Exception:
        quiet()
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


@tool("run_python", "Быстро выполнить фрагмент Python-кода (расчёты, проверка идеи, парсинг). Таймаут 30 с. "
      "Печатай результат через print", {"code": S}, ["code"], modes=("medium", "high"))
def run_python(code: str) -> str:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=WORKSPACE, delete=False, encoding="utf-8") as f:
        f.write(code)
        path = f.name
    try:
        return run_command(f'python "{Path(path).name}"', str(WORKSPACE), 30)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
