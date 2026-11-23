"""Notifications for long background jobs: a Telegram message from the bot (token from data/telegram.json, never
printed) and a Windows toast."""
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def telegram(text: str) -> bool:
    try:
        cfg = json.loads((DATA / "telegram.json").read_text(encoding="utf-8"))
        ok = False
        for uid in cfg.get("allowed", []):
            body = urllib.parse.urlencode({"chat_id": uid, "text": text}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{cfg['token']}/sendMessage", data=body)
            with urllib.request.urlopen(req, timeout=20) as r:
                ok = ok or r.status == 200
        return ok
    except Exception as e:
        print("telegram: not sent (" + type(e).__name__ + ")", flush=True)
        return False


def toast(title: str, text: str):
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; "
          "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
          f"$n.ShowBalloonTip(15000, '{title}', '{text}', 'Info'); Start-Sleep 16; $n.Dispose()")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])
