"""Low-level Windows input for commands: type text, press key combos, system volume."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x0002, 0x0004
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inputs: list):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key(vk=0, scan=0, flags=0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_U(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)))


def type_text(text: str, delay: float = 0.01):
    """Unicode keystrokes. The small gap matters: Win11 Notepad / WinUI fields drop a burst of synthetic keys after
    ~25 chars and repeat the last one («4711» came out «1111»)."""
    for ch in text:
        if ch == "\n":
            press("enter"); continue
        code = ord(ch)
        units = [code] if code < 0x10000 else [0xD800 + ((code - 0x10000) >> 10), 0xDC00 + ((code - 0x10000) & 0x3FF)]
        for u in units:
            _send([_key(scan=u, flags=KEYEVENTF_UNICODE), _key(scan=u, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)])
        if delay:
            time.sleep(delay)


VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "enter": 0x0D, "esc": 0x1B, "tab": 0x09,
      "space": 0x20, "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
      "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C,
      "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD, "play_pause": 0xB3, "next": 0xB0, "prev": 0xB1}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
VK.update({"escape": 0x1B, "return": 0x0D, "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "pgup": 0x21, "pgdn": 0x22,
           "capslock": 0x14, "menu": 0x5D, "windows": 0x5B, "cmd": 0x5B, "plus": 0xBB, "minus": 0xBD,
           "энтер": 0x0D, "ввод": 0x0D, "пробел": 0x20, "таб": 0x09, "эскейп": 0x1B, "ктрл": 0x11, "шифт": 0x10, "альт": 0x12})


def _vk(name: str) -> int:
    name = name.strip().lower()
    if name in VK:
        return VK[name]
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    if len(name) == 1:
        return user32.VkKeyScanW(ord(name)) & 0xFF
    raise ValueError(f"неизвестная клавиша: {name}")


def press(combo: str):
    """'ctrl+shift+esc', 'win+d', 'enter'"""
    keys = [_vk(k) for k in combo.replace(" ", "").split("+") if k]
    _send([_key(vk=k) for k in keys] + [_key(vk=k, flags=KEYEVENTF_KEYUP) for k in reversed(keys)])


def _endpoint():
    from comtypes import CLSCTX_ALL, CoInitialize
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    CoInitialize()
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):
        return dev.EndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return iface.QueryInterface(IAudioEndpointVolume)


def get_volume() -> int:
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(value: int | None = None, delta: int | None = None) -> int:
    ep = _endpoint()
    cur = ep.GetMasterVolumeLevelScalar() * 100
    new = max(0, min(100, (cur + delta) if delta is not None else (value if value is not None else cur)))
    ep.SetMasterVolumeLevelScalar(new / 100, None)
    if new > 0:
        ep.SetMute(0, None)
    return round(new)
