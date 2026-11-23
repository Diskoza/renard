"""Master volume of Windows (the speaker icon in the tray), not of one app.
One «деление» = 2% — the same step as the volume keys."""
import asyncio

from . import I, S, tool


def _endpoint():
    from ctypes import POINTER, cast
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator, EDataFlow, ERole
    from pycaw.constants import CLSID_MMDeviceEnumerator
    enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
    dev = enum.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
    return cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))


def _job(action: str, amount: int | None, unit: str) -> str:
    import comtypes
    comtypes.CoInitialize()
    try:
        v = _endpoint()
        cur = round(v.GetMasterVolumeLevelScalar() * 100)
        muted = bool(v.GetMute())
        if action in ("get", "status", "now"):
            return f"Общая громкость: {cur}%" + (" (звук выключен)" if muted else "") + "."
        if action == "mute":
            v.SetMute(1, None)
            return f"Выключил звук (было {cur}%)."
        if action == "unmute":
            v.SetMute(0, None)
            return f"Включил звук: {cur}%."
        step = amount if amount is not None else 10
        if unit.startswith("дел") or unit in ("step", "steps", "tick"):
            step *= 2
        new = amount if action == "set" and amount is not None else cur + (step if action == "up" else -step if action == "down" else 0)
        new = max(0, min(100, int(new)))
        v.SetMasterVolumeLevelScalar(new / 100, None)
        if new > 0 and muted:
            v.SetMute(0, None)
        return f"Общая громкость: {cur}% → {new}%."
    finally:
        pass


@tool("volume", "ОБЩАЯ громкость Windows (всего компьютера). action: get, set (amount 0-100), up, down (amount — на сколько; "
                "unit: percent | деления (1 деление = 2%)), mute, unmute. Для одной программы — app_volume.",
      {"action": S, "amount": I, "unit": S}, ["action"])
async def volume(action: str = "get", amount: int | None = None, unit: str = "percent") -> str:
    return await asyncio.to_thread(_job, (action or "get").lower(), amount, (unit or "percent").lower())
