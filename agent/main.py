"""Entry point: python -m agent.main  ->  http://127.0.0.1:8790"""
import asyncio
from pathlib import Path
import time
import re
import json
import uuid

from . import logs
from .logs import quiet
logs.setup("server")


def _preimport():
    """aiogram + mcp (pydantic models) take ~6 s to IMPORT. Imported lazily inside the running server they froze it at
    every start: the window got no answer and showed «загружаю…». Imported here, before the port opens, the window
    just sees «переподключаюсь» for those seconds and then everything answers at once."""
    t0 = time.time()
    for mod in ("aiogram", "aiogram.client.session.aiohttp", "aiogram.filters", "aiogram.types", "mcp", "mcp.client.stdio"):
        try:
            __import__(mod)
        except Exception:
            quiet()
    logs.log.info(f"heavy libraries imported before start: {time.time() - t0:.1f}s")


_preimport()

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import SETTINGS, WEB_DIR
from .core import Agent
from .memory_pass import run_memory_pass
from .monitor import Monitor
from .telegram_bot import TelegramBridge
from .wake import WakeWord
from . import wake as wake_mod
from . import voice
from .tools.pc import gpu_stats

VOICE_OK = voice.available()
EXTRA_STATUS: dict = {}
IDLE_MEMORY_PASS_SEC = SETTINGS.get("agent", {}).get("memory_pass_idle_sec", 120)

app = FastAPI(title="Renard")


CONFLICTS: list = []
UI_SEEN = {"t": 0.0}
INFLIGHT: dict = {}
_CSP: dict = {}


def csp_for(html_path: Path) -> str:
    """Only our own scripts may run in the window. Programs like AdBlock360 rewrite every page that Chromium/WebView2
    loads and add their own scripts (200 KB per page, they can read the chat). Inline scripts of our pages are
    allowed by hash, so nothing else inline runs either."""
    import base64
    import hashlib
    try:
        mt = html_path.stat().st_mtime
    except OSError:
        return ""
    if _CSP.get(html_path, (0, ""))[0] != mt:
        src = html_path.read_text(encoding="utf-8")
        hashes = [f"'sha256-{base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()}'"
                  for m in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S)]
        _CSP[html_path] = (mt, "; ".join([
            "default-src 'self'",
            "script-src 'self' 'wasm-unsafe-eval' " + " ".join(hashes),
            "style-src 'self' 'unsafe-inline'",
            "font-src 'self' data:",
            "img-src 'self' data: blob: https:",
            "media-src 'self' data: blob: https:",
            f"connect-src 'self' ws://127.0.0.1:{PORT} ws://localhost:{PORT} blob: data:",
            "worker-src 'self' blob:",
            "frame-src 'self' https:",
            "object-src 'none'", "base-uri 'self'"]))
    return _CSP[html_path][1]


@app.middleware("http")
async def no_stale_ui(request: Request, call_next):
    """Without Cache-Control the window cached app modules heuristically for hours, so after an update it ran a mix of
    old and new JS. The UI (index, /app, /api) is always revalidated (cheap: ETag -> 304); vendor libs and assets stay cached.
    Also: CSP for our pages, window heartbeat, slow / failing requests -> renard.log."""
    t0 = time.perf_counter()
    path = request.url.path
    key = object()
    INFLIGHT[key] = f"{request.method} {path}"
    try:
        resp = await call_next(request)
    except Exception:
        logs.log.exception(f"request crashed: {request.method} {path}")
        raise
    finally:
        INFLIGHT.pop(key, None)
    dt = time.perf_counter() - t0
    if path == "/api/status" and request.headers.get("x-renard-ui"):
        UI_SEEN["t"] = time.time()
    if resp.status_code >= 500:
        logs.log.error(f"HTTP {resp.status_code} {request.method} {path} {dt:.2f}s")
    elif dt > 5 and path not in ("/api/chat", "/api/voice/tts", "/api/stt"):
        logs.log.warning(f"slow request {dt:.1f}s {request.method} {path}")
    if path == "/" or path.startswith(("/app/", "/api/")) or path.endswith(".html"):
        resp.headers["Cache-Control"] = "no-cache"
    if path == "/" or path.endswith(".html"):
        page = WEB_DIR / "index.html" if path == "/" else WEB_DIR / path.lstrip("/")
        pol = csp_for(page)
        if pol:
            resp.headers["Content-Security-Policy"] = pol
    return resp


app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")
app.mount("/app", StaticFiles(directory=str(WEB_DIR / "app")), name="app")
app.mount("/vendor", StaticFiles(directory=str(WEB_DIR / "vendor")), name="vendor")
from .config import DATA_DIR as _DD
(_DD / "avatars").mkdir(exist_ok=True)
app.mount("/avatars", StaticFiles(directory=str(_DD / "avatars")), name="avatars")
(_DD / "animations" / "library").mkdir(parents=True, exist_ok=True)
app.mount("/anims", StaticFiles(directory=str(_DD / "animations" / "library")), name="anims")
agent = Agent()
HOST, PORT = SETTINGS.get("host", "127.0.0.1"), SETTINGS.get("port", 8790)
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}


CLIENTS: set = set()


async def broadcast(ev: dict):
    for s in list(CLIENTS):
        try:
            await s(ev)
        except Exception:
            CLIENTS.discard(s)
    if ev.get("type") == "alert" and ev.get("source") != "telegram" and telegram.connected:
        asyncio.create_task(telegram.notify("⚠ " + ev.get("text", "")))


telegram = TelegramBridge(agent, broadcast)
from .tools.avatar import BUS as _AVATAR_BUS
_AVATAR_BUS["broadcast"] = broadcast
monitor = Monitor(broadcast)
wake = WakeWord(agent, broadcast, EXTRA_STATUS)

from types import SimpleNamespace
from .api_extra import build as build_api
from .commands import Runner
from .mcp_client import HUB
from .scheduler import Scheduler
from . import plugins as plugins_mod, prefs as prefs_mod

runner = Runner(agent, broadcast)
agent.command_runner = runner


async def _tg_notify(text: str):
    if telegram.connected:
        await telegram.notify(text)

sched = Scheduler(agent, broadcast, _tg_notify, lambda cid: runner.run(cid))
app.include_router(build_api(SimpleNamespace(agent=agent, broadcast=broadcast, telegram=telegram, wake=wake,
                                             sched=sched, runner=runner, status=EXTRA_STATUS)))
from .api_feedback import router as feedback_router
app.include_router(feedback_router)
for _m, _o in (prefs_mod.get("ai", {}) or {}).items():
    if _m in agent.llm.modes:
        agent.llm.modes[_m].update(_o)
plugins_mod.load_all()
agent.monitor = monitor


@app.on_event("startup")
async def warmup():
    asyncio.get_running_loop().set_exception_handler(logs.asyncio_handler)

    def _scan():
        CONFLICTS[:] = logs.detect_conflicts()
        for c in CONFLICTS:
            logs.log.warning(f"CONFLICT {c['kind']}: {c['name']} {c.get('exe', '')}")
    asyncio.get_running_loop().run_in_executor(None, _scan)

    async def _lag_watch():
        """If something blocks the event loop, EVERYTHING lags (chat stream, UI, voice, Telegram). Log who did it."""
        while True:
            t = time.perf_counter()
            await asyncio.sleep(0.5)
            lag = time.perf_counter() - t - 0.5
            if lag > 0.8:
                logs.log.warning(f"event loop blocked {lag:.1f}s (requests in progress: {', '.join(INFLIGHT.values()) or '-'})")
    asyncio.create_task(_lag_watch())

    import sys as _sys
    import threading as _th
    import traceback as _tb
    _beat = {"t": time.perf_counter()}
    _loop_tid = _th.get_ident()

    import faulthandler as _fh
    _stuck_log = logs.LOG_DIR / "loop_stuck.log"
    try:
        if _stuck_log.exists() and _stuck_log.stat().st_size > 2_000_000:
            _stuck_log.replace(_stuck_log.with_suffix(".1.log"))
        _stuck_fh = open(_stuck_log, "a", encoding="utf-8")
    except OSError:
        _stuck_fh = None

    async def _heartbeat():
        last = time.perf_counter()
        while True:
            now = time.perf_counter()
            if _stuck_fh and now - last > 2.2:
                _stuck_fh.write(f"^^^ {time.strftime('%Y-%m-%d %H:%M:%S')}: event loop was stuck {now - last:.1f}s\n\n")
                _stuck_fh.flush()
            last = _beat["t"] = now
            if _stuck_fh:
                _fh.dump_traceback_later(2.0, repeat=False, file=_stuck_fh)
            await asyncio.sleep(0.25)
    asyncio.create_task(_heartbeat())

    def _stack_watch():
        seen = 0.0
        while True:
            time.sleep(0.4)
            stuck = time.perf_counter() - _beat["t"]
            if stuck < 1.2 or _beat["t"] == seen:
                continue
            seen = _beat["t"]
            f = _sys._current_frames().get(_loop_tid)
            if not f:
                continue
            frames = [x for x in _tb.extract_stack(f) if "pc-agent" in x.filename and "main.py" not in x.filename[-8:]]
            where = " <- ".join(f"{x.filename.rsplit(chr(92), 1)[-1]}:{x.lineno} {x.name}" for x in reversed(frames[-4:]))
            logs.log.warning(f"event loop stuck {stuck:.1f}s in: {where or 'library code (' + _tb.extract_stack(f)[-1].filename.rsplit(chr(92), 1)[-1] + ')'}")
    _th.Thread(target=_stack_watch, name="loop-stack-watch", daemon=True).start()

    async def _boot_llm():
        if await agent.llm.ensure_ollama(90) and SETTINGS.get("agent", {}).get("preload_light", True):
            if not await agent.llm.fits(agent.llm.mode_cfg("low")["model"], idle_load=True):
                logs.log.info("preload skipped: the GPU is busy (a game?) — the model loads on the first question")
                return
            await agent.warmup("low")
    asyncio.create_task(_boot_llm())
    asyncio.create_task(agent.llm.keep_warm(busy=agent.lock.locked))
    from . import health
    asyncio.create_task(health.startup_check(SimpleNamespace(agent=agent, telegram=telegram, wake=wake)))
    from .activity import TRACKER
    TRACKER.start()
    asyncio.create_task(monitor.run())
    asyncio.create_task(voice_idle_loop())
    asyncio.create_task(sched.loop())

    asyncio.create_task(telegram.start())
    asyncio.create_task(HUB.start_all())
    from .beat import TRACKER as BEAT
    asyncio.create_task(BEAT.run(broadcast))
    from .noticer import NOTICER
    asyncio.create_task(NOTICER.run(broadcast))
    if VOICE_OK and wake_mod.wanted():
        asyncio.create_task(wake.start())
    if VOICE_OK and voice.CFG.get("tts_enabled", True):
        asyncio.get_running_loop().run_in_executor(None, preload_tts)


def preload_tts():
    try:
        voice.tts.synth("готово")
        from .wake import ACKS
        for text in [p for ps in ACKS.values() for p in ps] + ["Слушаю.", "Готово.", "Секунду, просыпаюсь."]:
            for p, l in voice.tts.prepare(text)[0]:
                voice.tts.phrase_pcm(p, l)
    except Exception as e:
        print("TTS preload failed:", e)


async def voice_idle_loop():
    while True:
        await asyncio.sleep(60)
        if await asyncio.to_thread(voice.stt.unload_if_idle):
            print("STT unloaded (idle)")


@app.post("/api/voice/stt")
async def voice_stt(request: Request):
    audio = await request.body()
    if len(audio) < 1000:
        return JSONResponse({"text": "", "error": "слишком короткая запись"})
    try:
        r = await asyncio.to_thread(voice.stt.transcribe, audio, None, "mic")
    except Exception as e:
        return JSONResponse({"text": "", "error": f"{type(e).__name__}: {e}"})
    return JSONResponse(r)


@app.post("/api/voice/warmup")
async def voice_warmup():
    """Called when the user starts recording: load whisper while they are still speaking."""
    asyncio.get_running_loop().run_in_executor(None, voice.stt.warmup)
    return {"ok": True}


@app.post("/api/voice/tts")
async def voice_tts(request: Request):
    data = await request.json()
    try:
        wav = await asyncio.to_thread(voice.tts.synth, data.get("text", ""), data.get("lang") or None,
                                      int(data.get("limit") or 700))
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    return Response(content=wav, media_type="audio/wav")


@app.post("/api/wake/toggle")
async def wake_toggle():
    on = await wake.toggle()
    wake_mod.remember(on)
    return {"wake": on, "device": wake.device}


@app.get("/api/telegram")
def telegram_status():
    return telegram.status()


@app.post("/api/telegram/token")
async def telegram_token(request: Request):
    data = await request.json()
    return await telegram.set_token(data.get("token", ""))


@app.post("/api/telegram/paircode")
def telegram_paircode():
    return {"pair_code": telegram.new_pair_code()}


@app.get("/api/monitor")
def monitor_summary():
    return {"summary": monitor.summary(), "samples": monitor.history[-60:]}


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" fill="#D97757"/>'
           '<circle cx="32" cy="32" r="14" fill="#1F1E1D"/><circle cx="32" cy="32" r="5" fill="#D97757"/></svg>')


@app.get("/favicon.ico")
def favicon():
    return FileResponse(WEB_DIR / "assets" / "renard.ico")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/ping")
def ping():
    return {"ok": True, "name": "Renard", "ui_age": round(time.time() - UI_SEEN["t"], 1) if UI_SEEN["t"] else None}


@app.get("/api/build")
def build():
    """Newest change time of the web UI: an open window reloads itself after an update (on reconnect)."""
    files = [p for p in (WEB_DIR / "app").rglob("*") if p.suffix in (".js", ".css", ".html")]
    return {"web": int(max((p.stat().st_mtime for p in files), default=0))}


@app.get("/api/status")
async def status():
    import psutil
    loaded = await agent.llm.loaded_models()
    return {
        "loaded": [{"name": m["name"], "vram_gb": round(m.get("size_vram", 0) / 1e9, 1), "until": m.get("expires_at")} for m in loaded],
        "gpu": gpu_stats(),
        "ram_used_gb": round(psutil.virtual_memory().used / 1e9, 1),
        "ram_pct": psutil.virtual_memory().percent,
        "cpu_pct": psutil.cpu_percent(None),
        "wake": EXTRA_STATUS.get("wake", False),
        "wake_available": EXTRA_STATUS.get("wake_available", False),
        "telegram": telegram.status(),
        "agent_ram_mb": round(psutil.Process().memory_info().rss / 1e6),
        "modes": {k: v["model"] for k, v in agent.llm.modes.items()},
        "voice": VOICE_OK,
        "stt_loaded": voice.stt.model is not None,
        "conflicts": CONFLICTS,
    }


@app.post("/api/clientlog")
async def clientlog(request: Request):
    """Problems seen by the UI window (JS errors, failed/slow requests, stuck tabs, foreign scripts) -> renard.log."""
    try:
        data = await request.json()
        logs.client(data if isinstance(data, list) else [data])
    except Exception as e:
        logs.log.warning(f"bad clientlog: {e}")
    return {"ok": True}


@app.get("/api/logs")
def get_logs(n: int = 200, grep: str = ""):
    return {"file": str(logs.LOG_FILE), "lines": logs.tail(min(n, 2000), grep)}


@app.post("/api/conflicts/rescan")
def rescan_conflicts():
    CONFLICTS[:] = logs.detect_conflicts()
    return {"conflicts": CONFLICTS}


@app.post("/api/unload")
async def unload():
    await agent.llm.unload_all()
    return {"ok": True}


@app.get("/api/sessions")
def sessions():
    """Chat list for the «Чаты» panel: newest first, title = first user message."""
    rows = agent.memory.db.execute(
        "SELECT session, MIN(ts), MAX(ts), COUNT(*), "
        "(SELECT content FROM messages m2 WHERE m2.session=m.session AND m2.role='user' ORDER BY id LIMIT 1) "
        "FROM messages m WHERE role IN ('user','assistant') GROUP BY session ORDER BY MAX(ts) DESC LIMIT 60").fetchall()
    out = []
    for sid, t0, t1, n, first in rows:
        src = "Telegram" if sid.startswith("tg-") else "голос" if sid == "wake" else "окно"
        out.append({"id": sid, "title": (first or "(без текста)")[:70], "n": n, "src": src,
                    "when": time.strftime("%d.%m %H:%M", time.localtime(t1))})
    return {"sessions": out}


@app.get("/api/session/{sid}")
def session_messages(sid: str):
    rows = agent.memory.db.execute(
        "SELECT ts, role, content, mode FROM (SELECT * FROM messages WHERE session=? AND role IN ('user','assistant') "
        "ORDER BY id DESC LIMIT 200) ORDER BY id", (sid,)).fetchall()
    return {"messages": [{"time": time.strftime("%d.%m %H:%M", time.localtime(t)), "role": r, "content": c, "mode": m}
                         for t, r, c, m in rows]}


@app.post("/api/upload")
async def upload(request: Request, name: str = "file"):
    """Files dropped into the window -> workspace/uploads (the agent gets the path)."""
    data = await request.body()
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", Path(name).name)[:120] or "file"
    d = Path(SETTINGS.get("workspace", "workspace")) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    p.write_bytes(data)
    return {"path": str(p), "size": len(data)}


@app.get("/api/settings")
def get_settings():
    from .shortcuts import autostart_enabled
    from .tools.files import ROOTS
    return {"wake": EXTRA_STATUS.get("wake", False), "wake_available": EXTRA_STATUS.get("wake_available", False),
            "telegram": telegram.status(), "folders": [str(r) for r in ROOTS], "autostart": autostart_enabled(),
            "home_city": SETTINGS.get("home_city", ""), "tts_voice": voice.CFG.get("tts_voice", "")}


@app.post("/api/settings")
async def set_settings(request: Request):
    data = await request.json()
    res = {}
    if "autostart" in data:
        from .shortcuts import set_autostart
        res["autostart"] = await asyncio.to_thread(set_autostart, bool(data["autostart"]))
    if data.get("folder"):
        from .tools.files import add_root
        try:
            res["folder"] = str(add_root(data["folder"]))
        except Exception as e:
            res["error"] = str(e)
    if data.get("home_city"):
        SETTINGS["home_city"] = data["home_city"].strip()
        cfg_path = WEB_DIR.parent / "config" / "settings.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["home_city"] = SETTINGS["home_city"]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        res["home_city"] = SETTINGS["home_city"]
    return res


@app.get("/api/memory")
def memory():
    m = agent.memory
    return {"index": m.index(), "notes": {p.name: p.read_text(encoding="utf-8") for p in m.notes_dir.glob("*.md")}}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session = uuid.uuid4().hex[:8]
    lock = agent.lock

    async def send(ev: dict):
        await websocket.send_text(json.dumps(ev, ensure_ascii=False))

    CLIENTS.add(send)

    idle_task: asyncio.Task | None = None
    last_seen = {"id": 0}

    async def idle_memory_pass(sess: str):
        await asyncio.sleep(IDLE_MEMORY_PASS_SEC)
        async with lock:
            await broadcast({"type": "activity", "source": "memory", "note": "фоновая память: разбираю разговор…"})
            try:
                saved, last_seen["id"] = await run_memory_pass(agent, sess, last_seen["id"])
                if saved:
                    await send({"type": "memory", "saved": saved})
            except Exception as e:
                print("memory pass failed:", e)
            await broadcast({"type": "activity", "source": "memory", "note": ""})

    current: dict = {"task": None}

    async def run(data: dict, sess: str):
        """One answer. Runs as a task, so the socket keeps listening — {"type": "stop"} cancels it (the Ollama stream is
        closed, generation stops at once)."""
        nonlocal idle_task
        async with lock:
            try:
                await agent.handle(data.get("text", ""), sess, send, data.get("mode") or None,
                                   perm=data.get("perm") or None, project=data.get("project") or None,
                                   voice=bool(data.get("voice")), speak=bool(data.get("speak")))
            except asyncio.CancelledError:
                logs.log.info("answer stopped by the user")
                try:
                    await send({"type": "token", "text": "\n\n_(остановлено)_"})
                    await send({"type": "done"})
                except Exception:
                    quiet()
                return
            except Exception as e:
                logs.log.exception("agent.handle failed")
                await send({"type": "error", "text": f"{type(e).__name__}: {e}"})
                await send({"type": "done"})
        if IDLE_MEMORY_PASS_SEC > 0:
            idle_task = asyncio.create_task(idle_memory_pass(sess))

    try:
        while True:
            data = json.loads(await websocket.receive_text())
            if data.get("type") == "stop":
                t = current["task"]
                if t and not t.done():
                    t.cancel()
                continue
            if idle_task:
                idle_task.cancel()
            if data.get("session"):
                session = data["session"]
            if current["task"] and not current["task"].done():
                await current["task"]
            current["task"] = asyncio.create_task(run(data, session))
    except WebSocketDisconnect:
        if idle_task:
            idle_task.cancel()
    finally:
        CLIENTS.discard(send)


def main():
    print(f"Renard: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
