"""The beat of the music playing on the PC, for the companion's dances.

No audio capture: Windows' own output level meter (IAudioMeterInformation, the same as the volume mixer's bars) is read
~100 times a second -> onset strength -> tempo by autocorrelation -> beat phase -> {"type": "beat", "bpm", "conf"} events
on every predicted beat. Runs only while something is playing and the desktop companion is on.
"""
import asyncio
import math
import threading
import time
from collections import deque
from .logs import quiet

RATE = 100
WIN_S = 8.0


class Tempo:
    """Feed (t, peak) at ~RATE Hz; estimate() -> (bpm, confidence, last beat time)."""

    def __init__(self):
        self.on = deque(maxlen=int(WIN_S * RATE))
        self.ts = deque(maxlen=int(WIN_S * RATE))
        self.fast = self.slow = None

    def feed(self, t: float, peak: float):
        e = math.log(1e-4 + max(0.0, peak))
        if self.fast is None:
            self.fast = self.slow = e
        self.fast += (e - self.fast) * .5
        self.slow += (e - self.slow) * .04
        self.on.append(max(0.0, self.fast - self.slow))
        self.ts.append(t)

    def estimate(self):
        n = len(self.on)
        if n < RATE * 4:
            return 0.0, 0.0, 0.0
        x = list(self.on)
        m = sum(x) / n
        x = [v - m for v in x]
        a0 = sum(v * v for v in x) or 1e-9
        best, best_lag, raw = -1.0, 0, 0.0
        for lag in range(int(RATE * 60 / 180), int(RATE * 60 / 70) + 1):
            r = sum(x[i] * x[i - lag] for i in range(lag, n)) / a0
            bpm = 60 * RATE / lag
            w = math.exp(-.5 * (math.log2(bpm / 120) / .9) ** 2)
            if r * (.6 + .4 * w) > best:
                best, best_lag, raw = r * (.6 + .4 * w), lag, r
        if best_lag == 0 or raw <= 0:
            return 0.0, 0.0, 0.0
        span = min(n, RATE * 4)
        tail = list(self.on)[-span:]
        score = [sum(tail[j] for j in range(span - 1 - o, -1, -best_lag)) for o in range(best_lag)]
        o = max(range(best_lag), key=score.__getitem__)
        last = self.ts[-1] - o / RATE
        return 60 * RATE / best_lag, max(0.0, min(1.0, raw)), last


class BeatTracker:
    def __init__(self):
        self.running = False
        self.bpm = self.conf = 0.0

    def wanted(self) -> bool:
        from .prefs import get
        return bool(get("companion.enabled", False) and get("companion.desktop", False)
                    and get("companion.dance_music", True) is not False)

    async def run(self, broadcast):
        from .media_now import now_playing
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(3)
            try:
                want = self.wanted() and (await now_playing()).get("playing")
            except Exception:
                want = False
            if want and not self.running:
                self.running = True
                threading.Thread(target=self._loop, args=(loop, broadcast), daemon=True).start()
            elif not want:
                self.running = False

    def _loop(self, loop, broadcast):
        import comtypes
        comtypes.CoInitialize()
        try:
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
            dev = AudioUtilities.GetSpeakers()
            meter = getattr(dev, "_dev", dev).Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None) \
                .QueryInterface(IAudioMeterInformation)
        except Exception as e:
            print("beat: no level meter:", e)
            self.running = False
            return
        tempo, est_t, next_beat, last_ok = Tempo(), 0.0, 0.0, 0.0
        emit = lambda ev: asyncio.run_coroutine_threadsafe(broadcast(ev), loop)
        while self.running:
            t = time.perf_counter()
            try:
                tempo.feed(t, meter.GetPeakValue())
            except Exception:
                break
            if t - est_t > .5:
                est_t = t
                bpm, conf, last = tempo.estimate()
                if conf > .2 and bpm:
                    self.bpm, self.conf = bpm, conf
                    period = 60 / bpm
                    nb = last + period * math.ceil((t - last) / period + 1e-6)
                    next_beat = nb if not next_beat or abs(nb - next_beat) > period * .25 else next_beat
                    last_ok = t
                elif t - last_ok > 4:
                    if self.conf:
                        emit({"type": "beat", "bpm": 0, "conf": 0})
                    self.bpm = self.conf = 0.0
                    next_beat = 0.0
            if next_beat and t >= next_beat:
                emit({"type": "beat", "bpm": round(self.bpm, 1), "conf": round(self.conf, 2)})
                next_beat += 60 / self.bpm if self.bpm else 1e9
            time.sleep(1 / RATE)
        self.running = False
        try:
            emit({"type": "beat", "bpm": 0, "conf": 0})
        except Exception:
            quiet()


TRACKER = BeatTracker()
