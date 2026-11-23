"""Shared helper for clients (TUI, desktop window): make sure the agent server is running."""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .config import ROOT, SETTINGS

HOST, PORT = SETTINGS.get("host", "127.0.0.1"), SETTINGS.get("port", 8790)
BASE = f"http://{HOST}:{PORT}"
WS_URL = f"ws://{HOST}:{PORT}/ws"


def server_alive() -> bool:
    try:
        return httpx.get(BASE + "/api/ping", timeout=3).status_code == 200
    except Exception:
        return False


def port_busy() -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def ensure_server(timeout: float = 120) -> bool:
    """Start `python -m agent` in the background (no console window) if it is not running."""
    if server_alive():
        return True
    if port_busy():
        t0 = time.time()
        while time.time() - t0 < timeout:
            if server_alive():
                return True
            time.sleep(0.5)
        return False
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else py)
    log = open(ROOT / "data" / "server.log", "ab")
    flags = 0
    if os.name == "nt":
        flags = 0x00000200 | 0x08000000
    subprocess.Popen([exe, "-m", "agent"], cwd=str(ROOT), stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, creationflags=flags)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if server_alive():
            return True
        time.sleep(0.4)
    return False
