"""Background PC monitor: thresholds -> Windows toast + alert to every connected client.
Cheap: psutil + NVML every `interval_sec` (~1 ms of CPU), Defender check every 10 min.
"""
import asyncio
import subprocess
import time

import psutil

from .config import SETTINGS
from .tools.pc import gpu_stats, volume_mount_points
from .tools.system import NO_WINDOW, toast

CFG = {"enabled": True, "interval_sec": 30, "cpu_pct": 95, "ram_pct": 92, "gpu_temp_c": 85, "disk_free_pct": 3,
       "sustain_checks": 4, "cooldown_min": 30, **SETTINGS.get("monitor", {})}


class Monitor:
    def __init__(self, broadcast):
        self.broadcast = broadcast
        self.streak: dict[str, int] = {}
        self.last_alert: dict[str, float] = {}
        self.last_defender = 0.0
        self.defender_seen: int | None = None
        self.history: list[dict] = []

    async def run(self):
        if not CFG["enabled"]:
            return
        psutil.cpu_percent(None)
        while True:
            await asyncio.sleep(CFG["interval_sec"])
            try:
                await self.check()
            except Exception as e:
                print("monitor error:", e)

    def _sustained(self, key: str, cond: bool) -> bool:
        self.streak[key] = self.streak.get(key, 0) + 1 if cond else 0
        return self.streak[key] >= CFG["sustain_checks"]

    async def alert(self, key: str, text: str):
        now = time.time()
        if now - self.last_alert.get(key, 0) < CFG["cooldown_min"] * 60:
            return
        self.last_alert[key] = now
        toast("Renard", text)
        await self.broadcast({"type": "alert", "text": text})

    async def check(self):
        from .tools.system import warm_procs
        asyncio.create_task(asyncio.to_thread(warm_procs))
        cpu = psutil.cpu_percent(None)
        ram = psutil.virtual_memory().percent
        g = gpu_stats()
        self.history = (self.history + [{"t": time.time(), "cpu": cpu, "ram": ram, "gpu": g.get("load_%"),
                                         "gpu_temp": g.get("temp_c")}])[-120:]
        if self._sustained("cpu", cpu >= CFG["cpu_pct"]):
            await self.alert("cpu", f"Процессор загружен на {cpu:.0f}% уже ~{CFG['sustain_checks'] * CFG['interval_sec'] // 60 or 1} мин. "
                                    "Спроси «что грузит процессор».")
        if self._sustained("ram", ram >= CFG["ram_pct"]):
            await self.alert("ram", f"Оперативная память занята на {ram:.0f}%. Спроси «что жрёт память».")
        t = g.get("temp_c")
        if t is not None and self._sustained("gpu_temp", t >= CFG["gpu_temp_c"]):
            await self.alert("gpu_temp", f"Видеокарта греется: {t}°C.")
        for mp in volume_mount_points():
            try:
                u = psutil.disk_usage(mp)
            except Exception:
                continue
            if 100 - u.percent <= CFG["disk_free_pct"]:
                await self.alert(f"disk:{mp}", f"На диске {mp} осталось {u.free / 1e9:.0f} ГБ ({100 - u.percent:.0f}%).")
        if time.time() - self.last_defender > 600:
            self.last_defender = time.time()
            n = await asyncio.to_thread(self._defender_count)
            if n is not None:
                if self.defender_seen is not None and n > self.defender_seen:
                    await self.alert(f"defender:{n}", "Windows Defender обнаружил новую угрозу. Спроси «статус защитника».")
                self.defender_seen = n

    @staticmethod
    def _defender_count() -> int | None:
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-MpThreatDetection | Measure-Object).Count"],
                                 capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout.strip()
            return int(out) if out.isdigit() else None
        except Exception:
            return None

    def summary(self) -> str:
        if not self.history:
            return "Мониторинг ещё не собрал данные (первая проверка через ~30 с после запуска)."
        h = self.history
        mins = (h[-1]["t"] - h[0]["t"]) / 60
        avg = lambda k: sum(x[k] or 0 for x in h) / len(h)
        mx = lambda k: max((x[k] or 0) for x in h)
        return (f"За последние {mins:.0f} мин: CPU ср. {avg('cpu'):.0f}% (макс {mx('cpu'):.0f}%), "
                f"RAM ср. {avg('ram'):.0f}%, GPU ср. {avg('gpu'):.0f}% (макс {mx('gpu'):.0f}%), "
                f"темп. GPU макс {mx('gpu_temp'):.0f}°C. Предупреждений: {len(self.last_alert)}.")
