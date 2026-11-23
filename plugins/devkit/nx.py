"""nx — helper library for Renard scripts (pc_script / saved skills). `from nx import *` is done for you.

Read (always allowed):
  windows()                      -> open windows: [{title, proc, pid, hwnd}]
  fields(win)                    -> {label: value} of a program's window (UI Automation or Win32 controls)
  controls(win)                  -> [{id, type, name, value}] all elements
  app_dirs(name)                 -> folders with this program's settings (AppData, ProgramData, Documents)
  find_files(root, pattern, n)   -> paths matching a glob under root
  read_config(path)              -> dict from .json / .ini / .xml / .vdf / .yaml / .toml / plain text
  reg_read(path)                 -> values of a registry key «HKCU\\Software\\X»
  sql_read(db, query)            -> rows from a SQLite file (read-only copy: works while the app holds it)
  http_get(url, params)          -> JSON (or text) from a web API
  ps_read(cmd)                   -> output of a read-only PowerShell command (Get-*, Test-*, ipconfig …)
  disk(), top_procs(n)           -> free space per drive; heaviest processes
  read_text(path)                -> file text (in the sandbox: the changed copy if there is one)

Sandbox (no «да» needed): write_file / write_config / to_recycle change only a COPY in workspace/sandbox; the user
sees a diff and applies it to the PC with apply_sandbox (that asks «да»). Clicks, keys, PowerShell changes — always «да».

Change (only after the user's «да» — the runner sets NX_WRITE=1):
  set_field(win, label, value)   click(win, name)   press(keys)   type_text(text)
  write_file(path, text)         to_recycle(path)   ps(cmd)       write_config(path, data)
"""
import configparser
import fnmatch
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
WRITE_OK = os.environ.get("NX_WRITE") == "1"
SANDBOX = Path(os.environ["NX_SANDBOX"]) if os.environ.get("NX_SANDBOX") and not WRITE_OK else None


def _mirror(path) -> Path:
    p = Path(path).resolve()
    return SANDBOX / "files" / (p.drive.rstrip(":") or "root") / p.relative_to(p.anchor)


def _manifest() -> dict:
    f = SANDBOX / "manifest.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else {"files": {}, "delete": []}


def _save_manifest(m: dict):
    SANDBOX.mkdir(parents=True, exist_ok=True)
    (SANDBOX / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")


def _readable(path) -> Path:
    """In the sandbox a file already changed there is read from the copy, so several steps build on each other."""
    if SANDBOX:
        m = _mirror(path)
        if m.exists():
            return m
    return Path(path)


def read_text(path) -> str:
    return _readable(path).read_text("utf-8", "replace")
NO_WINDOW = 0x08000000
READ_PS = re.compile(r"^\s*(get-|test-|select-|measure-|format-|where-|sort-|resolve-|ipconfig|ping|tracert|nslookup|"
                     r"netstat|whoami|systeminfo|hostname|tasklist|driverquery|wmic\s+\w+\s+get|\$|\()", re.I)
WRITE_PS = re.compile(r"\b(set-|remove-|new-|stop-|start-|restart-|disable-|enable-|clear-|install-|uninstall-|rename-|"
                      r"move-|copy-|invoke-webrequest\s.*-method\s+(post|put|delete)|reg\s+(add|delete)|del\s|rd\s|format\s)", re.I)

__all__ = ["windows", "fields", "controls", "app_dirs", "find_files", "read_config", "reg_read", "sql_read", "http_get",
           "ps_read", "disk", "top_procs", "read_text", "set_field", "click", "press", "type_text", "write_file", "to_recycle", "ps",
           "write_config", "WRITE_OK", "ROOT"]


def _need_write(what: str):
    if not WRITE_OK:
        raise PermissionError(f"{what}: это изменение — нужен «да» пользователя (pc_script_write)")


def windows() -> list[dict]:
    from agent.tools.apps import list_wins
    return [{k: w.get(k) for k in ("title", "proc", "pid", "hwnd")} for w in list_wins() if (w.get("title") or "").strip()]


def _win(win):
    from agent.tools.apps import find_window
    if isinstance(win, int):
        return win
    w = find_window(str(win))
    if not w:
        raise LookupError(f"окно «{win}» не найдено — открой программу (open_app) или проверь windows()")
    return w["hwnd"]


def _snapshot(win) -> list[dict]:
    import uiautomation as auto
    from agent.app_operator import snapshot
    with auto.UIAutomationInitializerInThread():
        els = snapshot(auto.ControlFromHandle(_win(win)))
        return [{k: e.get(k) for k in ("id", "type", "name", "value", "hwnd")} for e in els]


def controls(win) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "hwnd"} for e in _snapshot(win)]


def fields(win) -> dict:
    out = {}
    for e in _snapshot(win):
        if e["type"] in ("Edit", "ComboBox", "CheckBox", "RadioButton", "Slider", "Spinner") and e["name"]:
            key = re.sub(r"^поле «(.*)»$", r"\1", e["name"])
            while key in out:
                key += "'"
            out[key] = e["value"]
    return out


def _find_el(win, name: str, kinds=None):
    import uiautomation as auto
    from agent.app_operator import snapshot
    low = name.lower().strip()
    auto_init = auto.UIAutomationInitializerInThread()
    auto_init.__enter__()
    els = snapshot(auto.ControlFromHandle(_win(win)))
    cands = [e for e in els if (not kinds or e["type"] in kinds)]
    for test in (lambda n: n == low, lambda n: n == f"поле «{low}»", lambda n: low in n):
        hit = [e for e in cands if test(e["name"].lower())]
        if hit:
            return hit[0], auto_init
    auto_init.__exit__(None, None, None)
    raise LookupError(f"нет элемента «{name}». Есть: " + ", ".join(sorted({e['name'] for e in cands if e['name']}))[:400])


def set_field(win, label: str, value) -> str:
    """Put a value into a field by its label («secs», «Mouse button»); returns what the field shows after."""
    _need_write("set_field")
    from agent.app_operator import _w32_type
    from agent.tools.apps import activate
    from agent import winput
    e, init = _find_el(win, label, ("Edit", "ComboBox", "Document"))
    try:
        activate(_win(win)); time.sleep(.15)
        if e.get("c") is None:
            return _w32_type(e, str(value))
        try:
            e["c"].GetValuePattern().SetValue(str(value))
        except Exception:
            e["c"].Click(simulateMove=False); winput.press("ctrl+a"); winput.type_text(str(value))
        time.sleep(.2)
        return str(value)
    finally:
        init.__exit__(None, None, None)


def click(win, name: str) -> str:
    _need_write("click")
    from agent.app_operator import _w32_press
    from agent.tools.apps import _press_control, activate
    e, init = _find_el(win, name)
    try:
        activate(_win(win)); time.sleep(.15)
        return _w32_press(e) if e.get("c") is None else _press_control(e["c"])
    finally:
        init.__exit__(None, None, None)


def press(keys: str):
    _need_write("press")
    from agent import winput
    for k in [x.strip() for x in re.split(r"[;,]", keys) if x.strip()]:
        winput.press(k); time.sleep(.12)


def type_text(text: str):
    _need_write("type_text")
    from agent import winput
    winput.type_text(text)


def _env(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def app_dirs(name: str) -> list[str]:
    """Folders that look like this program's (by words of its name / exe), one level deep in the usual places."""
    key = re.sub(r"[^a-zа-я0-9]+", "", name.lower())
    if len(key) < 4:
        return []
    roots = [p for p in (_env("APPDATA"), _env("LOCALAPPDATA"), _env("PROGRAMDATA"),
                         _env("USERPROFILE") and _env("USERPROFILE") / "Documents",
                         _env("LOCALAPPDATA") and _env("LOCALAPPDATA") / "Programs",
                         Path("C:/Program Files"), Path("C:/Program Files (x86)")) if p and p.is_dir()]
    out = []
    for r in roots:
        try:
            for d in r.iterdir():
                low = re.sub(r"[^a-zа-я0-9]+", "", d.name.lower())
                if d.is_dir() and len(low) >= 4 and (key in low or (low in key and len(low) >= 6)):
                    out.append(str(d))
        except OSError:
            continue
    return out[:20]


def find_files(root, pattern: str = "*", n: int = 50) -> list[str]:
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".git", "node_modules", "__pycache__"))
                       and "cache" not in d.lower() and d.lower() not in ("logs", "temp", "tmp", "crashpad", "gpucache")]
        for f in files:
            if fnmatch.fnmatch(f.lower(), pattern.lower()):
                out.append(os.path.join(dirpath, f))
                if len(out) >= n:
                    return out
    return out


def _parse_vdf(text: str) -> dict:
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack, cur, key = [], {}, None
    for s, br in tokens:
        if br == "{":
            new = {}
            cur[key] = new
            stack.append(cur); cur, key = new, None
        elif br == "}":
            cur = stack.pop() if stack else cur
        elif key is None:
            key = s
        else:
            cur[key] = s; key = None
    return cur


def read_config(path) -> dict | str:
    p = Path(path)
    text = _readable(p).read_text("utf-8", "replace")
    ext = p.suffix.lower()
    if ext == ".json" or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except ValueError:
            pass
    if ext in (".ini", ".cfg", ".conf") or re.search(r"^\s*\[[^\]]+\]\s*$", text, re.M):
        cp = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            cp.read_string(text)
            return {s: dict(cp[s]) for s in cp.sections()}
        except configparser.Error:
            pass
    if ext in (".vdf", ".acf"):
        return _parse_vdf(text)
    if ext == ".xml":
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        return {"tag": root.tag, "attrib": root.attrib,
                "children": [{"tag": c.tag, "attrib": c.attrib, "text": (c.text or "").strip()} for c in list(root)[:200]]}
    if ext == ".toml":
        import tomllib
        return tomllib.loads(text)
    if ext in (".yaml", ".yml"):
        try:
            import yaml
            return yaml.safe_load(text)
        except ImportError:
            pass
    return text


def reg_read(path: str) -> dict:
    import winreg
    hive, _, sub = path.replace("/", "\\").partition("\\")
    h = {"HKCU": winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
         "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE}[hive.upper()]
    out = {"values": {}, "subkeys": []}
    with winreg.OpenKey(h, sub) as k:
        i = 0
        while True:
            try:
                n, v, _ = winreg.EnumValue(k, i); out["values"][n] = v; i += 1
            except OSError:
                break
        i = 0
        while True:
            try:
                out["subkeys"].append(winreg.EnumKey(k, i)); i += 1
            except OSError:
                break
    return out


def sql_read(db, query: str, n: int = 50) -> list[tuple]:
    if not re.match(r"^\s*(select|with|pragma)\b", query, re.I):
        raise PermissionError("sql_read: только SELECT / WITH / PRAGMA")
    tmp = Path(tempfile.mkdtemp()) / Path(db).name
    shutil.copy2(db, tmp)
    con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        return con.execute(query).fetchmany(n)
    finally:
        con.close()
        shutil.rmtree(tmp.parent, ignore_errors=True)


def http_get(url: str, params: dict | None = None, timeout: int = 15):
    import httpx
    r = httpx.get(url, params=params, timeout=timeout, follow_redirects=True,
                  headers={"User-Agent": "Renard-local-assistant/1.0"})
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return r.text[:20000]


def _run_ps(cmd: str, timeout: int = 60) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=NO_WINDOW if os.name == "nt" else 0)
    return (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()[:20000]


def ps_read(cmd: str, timeout: int = 60) -> str:
    parts = [p for p in re.split(r"[;|]", cmd) if p.strip()]
    if not parts or not READ_PS.match(parts[0]) or WRITE_PS.search(cmd):
        raise PermissionError("ps_read: только команды чтения (Get-*, Test-*, ipconfig …); изменения — ps() с «да»")
    return _run_ps(cmd, timeout)


def ps(cmd: str, timeout: int = 120) -> str:
    _need_write("ps")
    return _run_ps(cmd, timeout)


def disk() -> dict:
    """Free space per drive, including drives mounted as folders (e.g. C:\\Data)."""
    import psutil
    out = {}
    for part in psutil.disk_partitions(all=False):
        try:
            u = shutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        out[part.mountpoint] = {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1),
                                "free_pct": round(100 * u.free / u.total)}
    for extra in (ROOT.anchor, str(ROOT.parents[len(ROOT.parents) - 2])):
        try:
            u = shutil.disk_usage(extra)
            if not any(abs(v["total_gb"] - round(u.total / 2**30, 1)) < 0.2 and abs(v["free_gb"] - round(u.free / 2**30, 1)) < 0.2
                       for v in out.values()):
                out[extra] = {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1),
                              "free_pct": round(100 * u.free / u.total)}
        except OSError:
            continue
    return out


def top_procs(n: int = 8) -> list[dict]:
    import psutil
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append({"name": p.info["name"], "pid": p.pid, "ram_mb": round(p.info["memory_info"].rss / 2**20),
                          "cpu": p.cpu_percent(None)})
        except Exception:
            continue
    time.sleep(1.0)
    for x in procs:
        try:
            x["cpu"] = psutil.Process(x["pid"]).cpu_percent(None)
        except Exception:
            x["cpu"] = 0
    return sorted(procs, key=lambda x: (x["cpu"], x["ram_mb"]), reverse=True)[:n]


WORKSPACE = ROOT / "workspace"


def _in_workspace(path) -> bool:
    try:
        Path(path).resolve().relative_to(WORKSPACE.resolve())
        return True
    except ValueError:
        return False


def write_file(path, text: str):
    if _in_workspace(path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return str(p)
    if SANDBOX:
        m = _manifest()
        dst = _mirror(path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        m["files"][str(Path(path).resolve())] = str(dst)
        _save_manifest(m)
        return f"(песочница) {path}"
    _need_write("write_file")
    p = Path(path)
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + f".bak_{time.strftime('%Y%m%d_%H%M%S')}"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return str(p)


def write_config(path, data):
    p = Path(path)
    if p.suffix.lower() == ".json":
        return write_file(p, json.dumps(data, ensure_ascii=False, indent=2))
    if p.suffix.lower() in (".ini", ".cfg"):
        return write_file(p, _ini_update(read_text(p) if _readable(p).exists() else "", data))
    raise ValueError("write_config: умею .json и .ini; для остального write_file")


def _ini_update(text: str, data: dict) -> str:
    """Change only the values that differ, keeping the file's own formatting, comments and key order."""
    lines, sec, seen = text.splitlines(), None, set()
    out, ends = [], {}
    for line in lines:
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            sec = m.group(1)
        else:
            kv = re.match(r"^(\s*)([^=;#\s][^=]*?)(\s*=\s*)(.*)$", line)
            if kv and sec in data and kv.group(2).strip() in data[sec]:
                val = str(data[sec][kv.group(2).strip()])
                line = f"{kv.group(1)}{kv.group(2)}{kv.group(3)}{val}"
                seen.add((sec, kv.group(2).strip()))
        out.append(line)
        if sec is not None and line.strip():
            ends[sec] = len(out)
    for s, kvs in data.items():
        new = [f"{k}={v}" for k, v in kvs.items() if (s, k) not in seen]
        if not new:
            continue
        if s in ends:
            out[ends[s]:ends[s]] = new
            ends = {k: (i + len(new) if i > ends[s] else i) for k, i in ends.items()}
        else:
            out += ["", f"[{s}]"] + new
    return "\n".join(out) + "\n"


def to_recycle(path) -> str:
    """Delete = move to the Recycle Bin (never permanently)."""
    if SANDBOX:
        m = _manifest()
        p = str(Path(path).resolve())
        if p not in m["delete"]:
            m["delete"].append(p)
        _save_manifest(m)
        return f"(песочница) будет в Корзину: {p}"
    _need_write("to_recycle")
    import ctypes
    from ctypes import wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR), ("pTo", wt.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wt.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wt.LPCWSTR)]
    p = str(Path(path).resolve())
    op = SHFILEOPSTRUCTW(None, 3, p + "\0\0", None, 0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
        raise OSError(f"не удалось переместить в Корзину: {p}")
    return p
