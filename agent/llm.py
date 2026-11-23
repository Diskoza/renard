"""Ollama client + model manager.

Rule #1: only ONE LLM in VRAM at a time. Switching mode unloads the previous model first.
"""
import asyncio
import json
import re
import time
from typing import AsyncIterator

import httpx

from .config import SETTINGS
from .logs import quiet

RUNNERS = ("llama-server", "ollama", "ollama_llama_server")
GAME_MODEL = SETTINGS.get("agent", {}).get("game_model", "gemma4:e4b")
_GAME_CACHE = [0.0, False]


_VRAM: dict = {}


def proc_vram_mb(pid: int) -> float | None:
    """dedicated video memory of a process, MB (Windows «GPU Process Memory» counter via typeperf, ~1.3 s)"""
    import subprocess
    try:
        r = subprocess.run(["typeperf", rf"\GPU Process Memory(pid_{pid}_*)\Dedicated Usage", "-sc", "1"],
                           capture_output=True, text=True, timeout=8, creationflags=0x08000000)
        rows = [l for l in r.stdout.splitlines() if l.startswith('"') and "PDH-CSV" not in l]
        if not rows:
            return None
        return sum(float(x.strip('"')) for x in rows[0].split(",")[1:] if x.strip('"').replace(".", "").isdigit()) / 2 ** 20
    except Exception:
        return None


def _heavy(pid: int) -> bool:
    """takes ≥ game_min_vram_mb of video memory? Unknown yet -> measured in the background, counted as a game
    meanwhile (the game comes first); unmeasurable -> a game, as before."""
    from .config import SETTINGS
    need = float((SETTINGS.get("agent") or {}).get("game_min_vram_mb", 2000))
    ts, mb = _VRAM.get(pid, (0.0, None))
    if time.time() - ts > 120:
        _VRAM[pid] = (time.time(), mb)

        def measure():
            _VRAM[pid] = (time.time(), proc_vram_mb(pid))
        import threading
        threading.Thread(target=measure, daemon=True).start()
    return mb is None or mb >= need


def gaming() -> bool:
    """Is he playing right now? The foreground window belongs to a game (Steam / Hydra / the Games folder / Riot /
    Epic…) or covers the whole screen without being a browser / player — AND it takes ≥ 2 GB of video memory.
    Not Discord / Roblox, not the lock screen, not when nobody touched the PC for 5 min. Cached 5 s."""
    if time.time() - _GAME_CACHE[0] < 5:
        return _GAME_CACHE[1]
    res = False
    try:
        import ctypes
        from ctypes import wintypes
        import psutil
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        exe = (psutil.Process(pid.value).exe() or "").lower()
        name = exe.rsplit("\\", 1)[-1]
        if name in ("lockapp.exe", "logonui.exe") or name.endswith(".scr") or idle_seconds() > 300:
            res = False
        elif not any(x in name for x in ("chrome", "msedge", "firefox", "opera", "explorer", "vlc", "mpc", "code", "python",
                                         "renard", "telegram", "discord", "obs", "spotify", "claude", "hydra.exe",
                                         "steam.exe", "steamwebhelper", "roblox")):
            import re
            if re.search(r"steamapps\\common|\\games?\\|\\gry\\|\\игры\\|riot games|epic games|hydra|minecraft|"
                         r"\\gog|ubisoft|battle\.net|\\ea games", exe):
                res = True
            else:
                r = wintypes.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
                res = r.left <= 0 and r.top <= 0 and r.right >= sw and r.bottom >= sh
            res = res and _heavy(pid.value)
    except Exception:
        res = False
    _GAME_CACHE[:] = [time.time(), res]
    return res


LEAK_HEAD = re.compile(r"^\s*thought\s*<\|?channel\|?>\s*|^\s*<\|?channel\|?>\s*")
LEAK_MARK = re.compile(r"<\|?channel\|?>")
_LEAK_FULL = ("thought<channel|>", "thought<|channel>", "<channel|>", "<|channel>")


def _maybe_leak(head: str) -> bool:
    """Could the text so far still be (the start of) the leaked markup? Then it is held back a little longer."""
    s = re.sub(r"\s+", "", head)
    return len(s) <= 20 and any(f.startswith(s) or s == f for f in _LEAK_FULL)


def idle_seconds() -> float:
    """Seconds since his last keyboard / mouse input (Windows GetLastInputInfo). 0 if unknown."""
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return 0.0
        return max(0.0, (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000)
    except Exception:
        return 0.0


def _runner_vram_gb() -> float | None:
    """Dedicated VRAM held by Ollama's model runners (Windows «GPU Process Memory» counters, ~0.3 s). None if unknown."""
    try:
        import psutil
        import win32pdh
        q = win32pdh.OpenQuery()
        try:
            cs = [(p, win32pdh.AddCounter(q, p)) for p in win32pdh.ExpandCounterPath(r"\GPU Process Memory(*)\Dedicated Usage")
                  if "pid_" in p]
            win32pdh.CollectQueryData(q)
            total, names = 0, {}
            for p, c in cs:
                pid = int(p.split("pid_")[1].split("_")[0])
                if pid not in names:
                    try:
                        names[pid] = psutil.Process(pid).name().lower().removesuffix(".exe")
                    except Exception:
                        names[pid] = ""
                if names[pid] in RUNNERS:
                    try:
                        total += win32pdh.GetFormattedCounterValue(c, win32pdh.PDH_FMT_LARGE)[1]
                    except Exception:
                        quiet()
            return total / 1e9
        finally:
            win32pdh.CloseQuery(q)
    except Exception:
        return None


class ModelManager:
    def __init__(self):
        self.url = SETTINGS.get("ollama_url", "http://127.0.0.1:11434")
        self.modes = SETTINGS["modes"]
        self.num_ctx = SETTINGS.get("num_ctx", 8192)
        self.current_model: str | None = None
        self._lock = asyncio.Lock()
        self._caps: dict[str, list[str]] = {}
        self.client = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(600, connect=5))

    def mode_cfg(self, mode: str) -> dict:
        return self.modes.get(mode) or self.modes["low"]

    _down_until = 0.0

    async def alive(self) -> bool:
        try:
            r = await self.client.get("/api/version", timeout=httpx.Timeout(3, connect=1.5))
            return r.status_code == 200
        except Exception:
            return False

    async def ensure_ollama(self, wait: float = 40) -> bool:
        """Ollama is not always running (closed tray app, slow boot). Start `ollama serve` hidden if needed."""
        if await self.alive():
            return True
        import os
        import shutil
        import subprocess
        exe = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
        if not os.path.exists(exe):
            return False
        import socket
        with socket.socket() as s:
            s.settimeout(0.5)
            busy = s.connect_ex(("127.0.0.1", 11434)) == 0
        if not busy:
            from .logs import log
            log.warning("Ollama is not running -> starting `ollama serve`")
            subprocess.Popen([exe, "serve"], creationflags=0x00000200 | 0x08000000,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < wait:
            await asyncio.sleep(0.7)
            if await self.alive():
                self._down_until = 0.0
                return True
        return False

    _sizes: dict = {}

    async def model_size_gb(self, model: str) -> float:
        if not self._sizes:
            try:
                r = await self.client.get("/api/tags", timeout=5)
                self._sizes = {m["name"]: m.get("size", 0) / 1e9 for m in r.json().get("models", [])}
            except Exception:
                return 0.0
        return self._sizes.get(model, 0.0)

    async def gpu_room_gb(self) -> float | None:
        """VRAM free for OUR models = total - what other programs (a game!) hold. None if unknown."""
        try:
            from .tools.pc import gpu_stats
            g = gpu_stats()
            if not g:
                return None
            ours = sum(m.get("size_vram", 0) for m in await self.loaded_models()) / 1e9
            runners = await asyncio.to_thread(_runner_vram_gb)
            if runners is not None:
                ours = max(ours, runners)
            return g["vram_total_gb"] - (g["vram_used_gb"] - ours)
        except Exception:
            return None

    async def fits(self, model: str, idle_load: bool = False) -> bool:
        """Does the model fit next to what else holds the GPU? idle_load=True (a preload nobody asked for): never under
        his game. A request he made runs even while he plays — the agent does not touch his mouse/keys, only the
        free video memory decides (a game holding it -> the light model)."""
        if idle_load and model != GAME_MODEL and gaming():
            return False
        return await self._fits(model)

    async def _fits(self, model: str) -> bool:
        """A game holding the GPU: a 8-22 GB model would spill into RAM — slow for us AND stutter in the game."""
        room, need = await self.gpu_room_gb(), await self.model_size_gb(model)
        if room is None or not need or need + 1.8 <= room:
            return True
        try:
            from .tools.pc import gpu_stats
            total = (gpu_stats() or {}).get("vram_total_gb") or 0
        except Exception:
            total = 0
        return bool(total) and need > total and room >= 0.8 * total

    async def loaded_models(self) -> list[dict]:
        """Polled by every status refresh (UI each 3 s): never make it wait. While Ollama is busy loading a model,
        /api/ps can take seconds -> answer with the last known list and refresh it in the background."""
        if time.time() < self._down_until:
            return []
        cache = getattr(self, "_ps_cache", None)
        if cache and time.time() - cache[0] < 2:
            return cache[1]
        task = getattr(self, "_ps_task", None)
        if task is None or task.done():
            self._ps_task = task = asyncio.ensure_future(self._fetch_ps())
        try:
            return await asyncio.wait_for(asyncio.shield(task), 1.0)
        except asyncio.TimeoutError:
            return cache[1] if cache else []

    async def _fetch_ps(self) -> list[dict]:
        try:
            r = await self.client.get("/api/ps", timeout=httpx.Timeout(8, connect=1.5))
            models = r.json().get("models", [])
            self._ps_cache = (time.time(), models)
            return models
        except Exception:
            self._down_until = time.time() + 15
            return []

    async def unload(self, model: str):
        try:
            await self.client.post("/api/generate", json={"model": model, "keep_alive": 0, "prompt": ""})
        except Exception:
            quiet()

    async def capabilities(self, model: str) -> list[str]:
        if model not in self._caps:
            try:
                r = await self.client.post("/api/show", json={"model": model})
                self._caps[model] = r.json().get("capabilities", [])
            except Exception:
                return []
        return self._caps[model]

    async def ensure(self, mode: str) -> str:
        """Make sure only the model for `mode` is (or will be) in VRAM."""
        model = self.mode_cfg(mode)["model"]
        if model.startswith("@"):
            self.current_model = model
            return model
        if time.time() < self._down_until or not await self.alive():
            await self.ensure_ollama()
        await self.capabilities(model)
        async with self._lock:
            for m in await self.loaded_models():
                if m.get("name") != model and m.get("model") != model:
                    await self.unload(m["name"])
            self.current_model = model
        return model

    async def preload(self, mode: str = "low"):
        """Load the model into VRAM without generating (so the first reply is instant)."""
        model = await self.ensure(mode)
        if model.startswith("@"):
            return
        try:
            await self.client.post("/api/generate", json={"model": model, "prompt": "",
                                                          "keep_alive": self.mode_cfg(mode).get("keep_alive", "5m")})
        except Exception:
            quiet()

    async def keep_warm(self, busy=lambda: False, every: float = 60):
        """A cold start of the light model took 20–35 s of a 35 s answer (timing.jsonl, «cold»). While he is at the PC
        (input in the last `keep_warm_idle_min` minutes) and not playing, keep it in VRAM: refresh its keep_alive, load it
        again if it fell out. A game in front -> free the VRAM at once. Away -> it expires by itself 10 min later."""
        from .logs import log
        cfg = SETTINGS.get("agent", {})
        if not cfg.get("keep_warm", True):
            return
        idle_max = cfg.get("keep_warm_idle_min", 20) * 60
        while True:
            await asyncio.sleep(every)
            try:
                light = self.mode_cfg("low")["model"]
                if light.startswith("@") or time.time() < self._down_until or busy():
                    continue
                loaded = {m.get("name") for m in await self.loaded_models()}
                if gaming():
                    if light in loaded and light != GAME_MODEL:
                        log.info(f"keep_warm: a game is in front -> unloading {light} (VRAM for the game)")
                        await self.unload(light)
                    continue
                if await asyncio.to_thread(idle_seconds) > idle_max:
                    continue
                if light in loaded:
                    await self.client.post("/api/generate", json={"model": light, "prompt": "", "keep_alive": "10m"})
                elif not loaded and await self.fits(light, idle_load=True):
                    log.info(f"keep_warm: he is at the PC, {light} not loaded -> preloading")
                    await self.ensure("low")
                    await self.client.post("/api/generate", json={"model": light, "prompt": "", "keep_alive": "10m"})
            except Exception:
                quiet()

    async def unload_all(self):
        for m in await self.loaded_models():
            await self.unload(m["name"])
        self.current_model = None

    def _payload(self, mode: str, messages: list, tools: list | None, stream: bool) -> dict:
        cfg = self.mode_cfg(mode)
        p = {
            "model": cfg["model"],
            "messages": messages,
            "stream": stream,
            "keep_alive": cfg.get("keep_alive", "3m"),
            "options": {
                "num_ctx": cfg.get("num_ctx", self.num_ctx),
                "temperature": cfg.get("temperature", 0.3),
                "num_predict": cfg.get("num_predict", 1000),
            },
        }
        if "thinking" in self._caps.get(cfg["model"], []):
            p["think"] = bool(cfg.get("think", False))
        if tools:
            p["tools"] = tools
        return p

    async def chat(self, mode: str, messages: list, tools: list | None = None) -> dict:
        from . import providers
        ext = providers.parse(self.mode_cfg(mode)["model"])
        if ext:
            try:
                return await providers.chat(*ext, messages, tools, self.mode_cfg(mode))
            except Exception as e:
                from .logs import log
                log.warning(f"provider {ext[0]} failed ({e}) -> Ollama {GAME_MODEL}")
                self.modes["_fallback"] = {**self.mode_cfg(mode), "model": self.mode_cfg(mode).get("fallback") or GAME_MODEL}
                mode = "_fallback"
        await self.ensure(mode)
        t0 = time.time()
        r = await self.client.post("/api/chat", json=self._payload(mode, messages, tools, False))
        r.raise_for_status()
        data = r.json()
        data["_wall"] = time.time() - t0
        return data

    async def stream(self, mode: str, messages: list, tools: list | None = None) -> AsyncIterator[tuple[str, object]]:
        """Yields ('token', str) while generating, then ('done', {'content', 'tool_calls', 'stats'})."""
        from . import providers
        ext = providers.parse(self.mode_cfg(mode)["model"])
        if ext:
            started = False
            try:
                async for ev in providers.stream(*ext, messages, tools, self.mode_cfg(mode)):
                    started = True
                    yield ev
                return
            except Exception as e:
                if started:
                    raise
                from .logs import log
                log.warning(f"provider {ext[0]} failed ({e}) -> Ollama {GAME_MODEL}")
                self.modes["_fallback"] = {**self.mode_cfg(mode), "model": self.mode_cfg(mode).get("fallback") or GAME_MODEL}
                yield "think", f"[{ext[0]} недоступен — отвечаю локальной моделью]"
                mode = "_fallback"
        await self.ensure(mode)
        content, calls, stats = [], [], {}
        t0 = time.time()
        empty = 0
        head, started = "", False
        async with self.client.stream("POST", "/api/chat", json=self._payload(mode, messages, tools, True)) as r:
            if r.status_code != 200:
                body = await r.aread()
                raise RuntimeError(f"Ollama {r.status_code}: {body[:300]!r}")
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message", {})
                if not (msg.get("content") or msg.get("thinking") or msg.get("tool_calls") or chunk.get("done")):
                    empty += 1
                if msg.get("thinking"):
                    yield "think", msg["thinking"]
                piece = msg.get("content", "")
                if piece and not started:
                    head += piece
                    if _maybe_leak(head):
                        piece = ""
                    else:
                        started, piece, head = True, LEAK_HEAD.sub("", head), ""
                if piece:
                    piece = LEAK_MARK.sub("", piece)
                if piece:
                    content.append(piece)
                    yield "token", piece
                if msg.get("tool_calls"):
                    calls.extend(msg["tool_calls"])
                if chunk.get("done"):
                    ec, ed = chunk.get("eval_count", 0), chunk.get("eval_duration", 0)
                    stats = {"model": chunk.get("model"), "tokens": ec,
                             "tps": round(ec / (ed / 1e9), 1) if ed else None,
                             "load_s": round(chunk.get("load_duration", 0) / 1e9, 2),
                             "wall_s": round(time.time() - t0, 2), "done_reason": chunk.get("done_reason"),
                             "empty_chunks": empty}
                    break
        rest = LEAK_HEAD.sub("", head) if head and not started else ""
        if rest.strip():
            content.append(rest)
            yield "token", rest
        yield "done", {"content": "".join(content), "tool_calls": calls, "stats": stats}
