"""Power: shut down / restart / sleep / lock / sign out — the PC owner asked for it, so Renard can do it.
Shutdown, restart, sleep and sign-out always ask «да/нет» first (and a timer can be cancelled)."""
import ctypes
import subprocess

from . import I, S, tool

NAMES = {"shutdown": "выключу компьютер", "restart": "перезагружу компьютер", "sleep": "отправлю компьютер в сон",
         "hibernate": "отправлю компьютер в гибернацию", "signout": "выйду из учётной записи"}


def _when(delay_min: int) -> str:
    return "сейчас" if delay_min <= 0 else f"через {delay_min} мин"


@tool("power", "Питание ПК: shutdown (выключить), restart (перезагрузить), sleep (сон), hibernate, signout (выйти из "
               "учётки). delay_min — через сколько минут (выключение/перезагрузка по таймеру). Спрашивает подтверждение.",
      {"action": S, "delay_min": I}, ["action"], confirm=True)
def power(action: str, delay_min: int = 0) -> str:
    a = (action or "").lower().strip()
    a = {"выключи": "shutdown", "off": "shutdown", "reboot": "restart", "suspend": "sleep", "logout": "signout",
         "logoff": "signout"}.get(a, a)
    d = max(0, int(delay_min or 0))
    if a in ("shutdown", "restart"):
        flag = "/s" if a == "shutdown" else "/r"
        sec = max(d * 60, 15)
        subprocess.run(["shutdown", flag, "/t", str(sec), "/c", "Renard: " + NAMES[a]], capture_output=True, timeout=20)
        return (f"Готово: {NAMES[a]} {_when(d) if d else 'через 15 секунд'}. Передумаешь — скажи «отмени выключение».")
    if a in ("sleep", "hibernate"):
        ctypes.windll.powrprof.SetSuspendState(a == "hibernate", False, False)
        return "Ушёл в сон." if a == "sleep" else "Ушёл в гибернацию."
    if a == "signout":
        subprocess.run(["shutdown", "/l"], capture_output=True, timeout=20)
        return "Выхожу из учётной записи."
    return f"Не знаю действие «{action}». Есть: shutdown, restart, sleep, hibernate, signout."


@tool("power_cancel", "Отменить запланированное выключение/перезагрузку ПК")
def power_cancel() -> str:
    r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True, timeout=20)
    return "Выключение отменено." if r.returncode == 0 else "Отменять нечего — выключение не запланировано."


@tool("lock_pc", "Заблокировать экран (Win+L)")
def lock_pc() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Заблокировал экран."
