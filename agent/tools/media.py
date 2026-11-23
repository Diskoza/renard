"""Media: Windows media keys, volume, internet radio (opens stream in default player)."""
import ctypes
import os

from . import tool

VK = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD}


def press(key: str, times: int = 1):
    if os.name != "nt":
        return
    for _ in range(times):
        ctypes.windll.user32.keybd_event(VK[key], 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK[key], 0, 2, 0)


@tool("media_control", "Управление музыкой/видео: play_pause, next, prev, stop, vol_up, vol_down, mute",
      {"action": {"type": "string", "enum": list(VK)}}, ["action"])
def media_control(action: str) -> str:
    if action not in VK:
        return f"Неизвестное действие. Доступно: {', '.join(VK)}"
    press(action, 5 if action.startswith("vol_") else 1)
    return f"Готово: {action}"
