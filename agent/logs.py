"""One hidden diagnostic log for every Renard process: data/logs/renard.log (rotated, 5 x 2 MB).

Every line: time, process (server/desktop/companion/...), level, source, message. It collects
  * Python logging of all modules + uncaught exceptions (main thread, threads, asyncio tasks);
  * stdout/stderr of windowless processes (pythonw has no console) - noisy library spam is counted, not repeated;
  * UI problems sent by the window (/api/clientlog): JS errors, failed/slow requests, stuck tabs, foreign scripts;
  * conflicts found on this PC (programs that inject into / proxy the window, port taken, duplicate servers).
Read it with:  python -m agent.logs [N]   (last N lines)  or  GET /api/logs?n=200
"""
import logging
import logging.handlers
import os
import re
import sys
import threading
import time

from .config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "renard.log"
_PROC = "?"
_ready = False
log = logging.getLogger("renard")

NOISE = [re.compile(p) for p in (r"^Missing phoneme from id map", r"^\s*$", r"Installed \d+ packages", r"Downloading |Downloaded ")]


def _hide(path):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
        except Exception:
            pass


class _Stream:
    """File-like object that replaces sys.stdout/stderr: whole lines go to the log, noise is only counted."""
    def __init__(self, level):
        self.level, self.buf, self.noise, self.noise_t = level, "", {}, time.time()
        self.lock = threading.Lock()

    def write(self, s):
        if not s:
            return 0
        with self.lock:
            self.buf += s
            *lines, self.buf = self.buf.split("\n")
        for line in lines:
            line = line.rstrip()
            pat = next((p.pattern for p in NOISE if p.search(line)), None)
            if pat:
                self.noise[pat] = self.noise.get(pat, 0) + 1
            else:
                logging.getLogger("stdout" if self.level == logging.INFO else "stderr").log(self.level, line)
        if self.noise and time.time() - self.noise_t > 60:
            n, self.noise, self.noise_t = self.noise, {}, time.time()
            log.debug("suppressed noise: " + "; ".join(f"{k[:30]}... x{v}" for k, v in n.items() if v))
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("no fileno")


def setup(proc: str, level=logging.INFO, capture_std: bool | None = None) -> logging.Logger:
    """Call once at the start of each process. capture_std: None = only when there is no console (pythonw)."""
    global _PROC, _ready
    if _ready:
        return log
    _PROC = proc
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _hide(LOG_DIR)
    logging.raiseExceptions = False
    path = LOG_FILE if proc == "server" else LOG_DIR / f"{proc}.log"
    h = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8", delay=True)
    h.setFormatter(logging.Formatter(f"%(asctime)s.%(msecs)03d {proc:<9} %(levelname)-5s %(name)s: %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "PIL", "matplotlib", "aiogram.event", "websockets",
                  "multipart", "numba", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if capture_std is None:
        capture_std = sys.stdout is None or sys.stderr is None or "pythonw" in os.path.basename(sys.executable).lower()
    if capture_std:
        sys.stdout = _Stream(logging.INFO)
        sys.stderr = _Stream(logging.WARNING)

    def _exc(t, v, tb):
        if issubclass(t, KeyboardInterrupt):
            return sys.__excepthook__(t, v, tb)
        log.critical("UNCAUGHT", exc_info=(t, v, tb))
    sys.excepthook = _exc
    threading.excepthook = lambda a: log.error(f"thread {a.thread.name if a.thread else '?'} crashed",
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    _ready = True
    try:
        import faulthandler
        global _crash_file
        _crash_file = open(LOG_DIR / f"crash_{proc}.log", "a", encoding="utf-8")
        _crash_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start pid={os.getpid()}\n")
        _crash_file.flush()
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        pass
    log.info(f"=== start pid={os.getpid()} exe={sys.executable} argv={' '.join(sys.argv[1:])}")
    return log


_quiet_seen: dict[tuple, list] = {}
_QUIET_EVERY = 600


def quiet() -> None:
    """Call in an `except` block whose error is deliberately ignored: the program goes on as before, but the error is
    written to the log once (file:line, type, message) and then at most every 10 min per place with a repeat count —
    so a polling loop does not flood it. Cancellation / Ctrl+C / exit are not errors and are skipped."""
    t, v, _ = sys.exc_info()
    if t is None or t.__name__ in ("CancelledError", "KeyboardInterrupt", "SystemExit", "GeneratorExit"):
        return
    try:
        f = sys._getframe(1)
        site = (f.f_code.co_filename, f.f_lineno)
        now = time.time()
        rec = _quiet_seen.setdefault(site, [0.0, 0])
        rec[1] += 1
        if now - rec[0] < _QUIET_EVERY:
            return
        n, rec[0], rec[1] = rec[1], now, 0
        logging.getLogger("quiet").info(f"{os.path.basename(site[0])}:{site[1]} {f.f_code.co_name}: {t.__name__}: "
                                        f"{str(v)[:200]}" + (f"  (×{n} за 10 мин)" if n > 1 else ""))
    except Exception:
        pass


def asyncio_handler(loop, ctx):
    """loop.set_exception_handler(asyncio_handler): errors of fire-and-forget tasks land in the log."""
    exc = ctx.get("exception")
    msg = ctx.get("message", "")
    if exc and type(exc).__name__ in ("CancelledError", "ConnectionResetError") or "Task was destroyed" in msg:
        return
    log.error(f"asyncio: {msg}", exc_info=exc)


def client(entries: list) -> None:
    """Entries from the UI window: [{level, kind, msg, page, ...}]."""
    lg = logging.getLogger("ui")
    for e in entries[:50]:
        if not isinstance(e, dict):
            continue
        lvl = {"error": logging.ERROR, "warn": logging.WARNING}.get(e.get("level"), logging.INFO)
        extra = " ".join(f"{k}={str(v)[:300]}" for k, v in e.items() if k not in ("level", "kind", "msg") and v not in (None, ""))
        lg.log(lvl, f"[{e.get('kind', '?')}] {str(e.get('msg', ''))[:1500]} {extra}".rstrip())


def tail(n: int = 200, grep: str = "") -> list[str]:
    """Last n lines of all Renard logs (server, desktop, companion, ...) merged by time."""
    lines: list[str] = []
    for base in sorted(LOG_DIR.glob("*.log")):
        for f in (base, base.with_name(base.name + ".1")):
            if f.exists():
                lines += [l for l in f.read_text(encoding="utf-8", errors="replace").splitlines()[-max(n * 2, 400):]]
    rows, last = [], ""
    for l in lines:
        if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", l):
            last = l[:23]
            rows.append((last, len(rows), l))
        else:
            rows.append((last, len(rows), l))
    rows.sort(key=lambda r: (r[0], r[1]))
    out = [r[2] for r in rows]
    if grep:
        out = [l for l in out if grep.lower() in l.lower()]
    return out[-n:]


INJECTORS = {"adblock360": "AdBlock360", "adblock360svc": "AdBlock360", "webcompanion": "Web Companion",
             "searchprotect": "Search Protect", "wajam": "Wajam", "browsersafeguard": "Browser Safeguard",
             "pcappstore": "PC App Store", "onelaunch": "OneLaunch", "shieldapps": "Shield Apps"}


def detect_conflicts() -> list[dict]:
    out = []
    try:
        import psutil
        seen = set()
        for p in psutil.process_iter(["name", "exe"]):
            n = (p.info.get("name") or "").lower().rsplit(".", 1)[0]
            if n in INJECTORS and INJECTORS[n] not in seen:
                seen.add(INJECTORS[n])
                out.append({"kind": "injector", "name": INJECTORS[n], "exe": p.info.get("exe") or "",
                            "text": f"{INJECTORS[n]} встраивает свои скрипты в окно Renard и пропускает через себя его "
                                    "трафик: вкладки грузятся медленно или зависают. Добавь 127.0.0.1 в исключения "
                                    "этой программы или удали её (Параметры → Приложения)."})
        servers = [p for p in psutil.process_iter(["cmdline"])
                   if (p.info.get("cmdline") or [])[-2:] == ["-m", "agent"]]
        pids = {s.pid for s in servers}
        roots = [s for s in servers if s.ppid() not in pids]
        if len(roots) > 1:
            out.append({"kind": "duplicate", "name": "Renard",
                        "text": f"Запущено {len(roots)} сервера Renard одновременно — второй не может занять порт и мешает первому."})
    except Exception as e:
        log.warning(f"conflict scan failed: {e}")
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 120
    g = next((a for a in sys.argv[1:] if not a.isdigit()), "")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(tail(n, g)))
