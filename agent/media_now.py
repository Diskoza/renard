"""«Сейчас играет» for the home widget: Windows media session (Spotify, Яндекс Музыка, YouTube in a browser…).

All WinRT media calls run in ONE dedicated thread with its own event loop. They used to run on the server's event
loop, and some of them are synchronous and hang while a player / browser tab is stuck — `request_async()` itself
blocks before it returns (seen: the server frozen 8+ s, the whole window and voice lagging, «event loop blocked»
in renard.log). Now a stuck call holds only that thread: the widget shows the last known state and the server goes on.
The session manager is requested once and reused (it was requested every 1.5 s).
"""
import asyncio
import base64
import concurrent.futures
import time

from .logs import quiet

_cache = {"t": 0.0, "data": None, "thumb_key": "", "thumb": ""}
_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-winrt")
_W = {"loop": None, "mgr": None, "busy_since": 0.0, "logged": 0.0, "gen": 0, "reset": 0.0}
STUCK_RESET_S = 120


def _job(fn, gen: int):
    """Runs in the media thread: the coroutine fn() on that thread's own loop."""
    _W["busy_since"] = time.time()
    try:
        if _W["loop"] is None:
            _W["loop"] = asyncio.new_event_loop()
        return _W["loop"].run_until_complete(fn())
    finally:
        if gen == _W["gen"]:
            _W["busy_since"] = 0.0


def _maybe_reset():
    """The WinRT call never came back (it can hang forever): leave that thread behind, start clean."""
    global _EXEC
    if time.time() - _W["busy_since"] < STUCK_RESET_S or time.time() - _W["reset"] < (300 if _W["gen"] < 5 else 1800):
        return
    import logging
    logging.getLogger("renard").warning(f"media thread stuck {time.time() - _W['busy_since']:.0f} s — starting a new one")
    _W.update(gen=_W["gen"] + 1, reset=time.time(), busy_since=0.0, loop=None, mgr=None)
    _EXEC.shutdown(wait=False)
    _EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-winrt")


async def _in_media_thread(fn, timeout: float):
    """fn() in the media thread; TimeoutError when it takes longer — or at once while an earlier call is still stuck
    there (nothing queues behind a hung WinRT call)."""
    if _W["busy_since"]:
        _maybe_reset()
    if _W["busy_since"]:
        raise TimeoutError(f"media thread busy for {time.time() - _W['busy_since']:.0f} s")
    fut = asyncio.get_running_loop().run_in_executor(_EXEC, _job, fn, _W["gen"])
    return await asyncio.wait_for(asyncio.shield(fut), timeout)


async def _manager():
    """Only inside the media thread."""
    if _W["mgr"] is None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
        _W["mgr"] = await M.request_async()
    return _W["mgr"]


def _stuck_note():
    if time.time() - _W["logged"] > 300:
        import logging
        _W["logged"] = time.time()
        logging.getLogger("renard").warning("media session query > 3 s (stuck player?) — showing the last known state")


async def now_playing() -> dict:
    """Polled by the home widget every few seconds: a fresh answer (≤ 1.5 s old) or the last known one if WinRT hangs."""
    if time.time() - _cache["t"] < 1.5 and _cache["data"] is not None:
        return _cache["data"]
    try:
        return await _in_media_thread(_query, 3)
    except (TimeoutError, asyncio.TimeoutError):
        _stuck_note()
        return _cache["data"] or {"playing": False, "title": ""}


async def _query() -> dict:
    try:
        mgr = await _manager()
        s = mgr.get_current_session()
        if s is None:
            data = {"playing": False, "title": ""}
        else:
            props = await s.try_get_media_properties_async()
            info = s.get_playback_info()
            tl = s.get_timeline_properties()
            key = f"{props.title}|{props.artist}"
            if key != _cache["thumb_key"]:
                _cache["thumb_key"], _cache["thumb"] = key, ""
                try:
                    from winrt.windows.storage.streams import Buffer, InputStreamOptions
                    if props.thumbnail:
                        stream = await props.thumbnail.open_read_async()
                        buf = Buffer(stream.size)
                        await stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
                        _cache["thumb"] = "data:image/png;base64," + base64.b64encode(bytes(buf)).decode()
                except Exception:
                    quiet()
            data = {"playing": int(info.playback_status) == 4, "title": props.title or "", "artist": props.artist or "",
                    "app": s.source_app_user_model_id or "", "thumb": _cache["thumb"],
                    "position": tl.position.total_seconds() if hasattr(tl.position, "total_seconds") else 0,
                    "duration": tl.end_time.total_seconds() if hasattr(tl.end_time, "total_seconds") else 0}
    except Exception as e:
        _W["mgr"] = None
        data = {"playing": False, "title": "", "error": f"{type(e).__name__}: {e}"}
    _cache["t"], _cache["data"] = time.time(), data
    return data


OWN = ("python", "renard", "msedgewebview")


def _status(s) -> int:
    try:
        return int(s.get_playback_info().playback_status)
    except Exception:
        return 0


async def control(action: str) -> bool:
    """play / pause / play_pause / next / prev on the RIGHT session. «Сними паузу» used to toggle the «current»
    session — often not the paused YouTube tab (another player or our own voice), so «Готово» and nothing happened."""
    try:
        return await _in_media_thread(lambda: _control(action), 8)
    except (TimeoutError, asyncio.TimeoutError):
        _stuck_note()
        return False


async def _control(action: str) -> bool:
    try:
        mgr = await _manager()
        sess, cur = list(mgr.get_sessions()), mgr.get_current_session()
        sess = [s for s in sess if not any(o in (s.source_app_user_model_id or "").lower() for o in OWN)]
        if not sess:
            return False
        playing = [s for s in sess if _status(s) == 4]
        paused = [s for s in sess if _status(s) == 5]
        last_app = ((_cache["data"] or {}).get("app") or "").lower()

        def best(lst):
            if not lst:
                return []
            pref = [s for s in lst if cur is not None and s.source_app_user_model_id == cur.source_app_user_model_id] or \
                   [s for s in lst if last_app and (s.source_app_user_model_id or "").lower() == last_app] or \
                   [s for s in lst if "chrome" in (s.source_app_user_model_id or "").lower()]
            return pref[:1] or lst[:1]
        if action == "pause":
            targets, meth = playing, "try_pause_async"
        elif action == "play":
            targets, meth = best(paused), "try_play_async"
            if playing and not paused:
                return True
        elif action == "play_pause":
            targets, meth = (playing or best(paused)), ("try_pause_async" if playing else "try_play_async")
        else:
            targets = best(playing) or best(paused) or best(sess)
            meth = "try_skip_next_async" if action == "next" else "try_skip_previous_async" if action == "prev" else ""
        if not targets or not meth:
            return False
        _cache["t"] = 0
        res = [await asyncio.wait_for(getattr(s, meth)(), 4) for s in targets]
        return any(bool(r) for r in res)
    except Exception:
        _W["mgr"] = None
        return False
