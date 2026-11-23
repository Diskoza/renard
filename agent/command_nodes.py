"""The node blocks added on 11.11 (Astra's editor has them): repeat, conditions by time / window / text, clipboard,
selected text, AI text processing, paste, open a path, screenshot, power timer, «не беспокоить», close hung windows,
open the next meeting, HTTP / webhook. Each: async fn(runner, data, ctx, log, sub) -> output names."""
import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from .logs import quiet

OUT = ["output_1"]


def _clip_get() -> str:
    import win32clipboard as wc
    for _ in range(5):
        try:
            wc.OpenClipboard()
            try:
                return wc.GetClipboardData(wc.CF_UNICODETEXT) if wc.IsClipboardFormatAvailable(wc.CF_UNICODETEXT) else ""
            finally:
                wc.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return ""


def _clip_set(text: str):
    import win32clipboard as wc
    for _ in range(5):
        try:
            wc.OpenClipboard()
            try:
                wc.EmptyClipboard(); wc.SetClipboardText(text, wc.CF_UNICODETEXT)
                return
            finally:
                wc.CloseClipboard()
        except Exception:
            time.sleep(0.05)


async def _mods_up(limit: float = 2.0):
    """A hotkey command starts while Ctrl/Alt/Shift/Win are still held: Ctrl+C would become Ctrl+Alt+C."""
    import ctypes
    k = ctypes.windll.user32.GetAsyncKeyState
    t = time.time()
    while time.time() - t < limit and any(k(v) & 0x8000 for v in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
        await asyncio.sleep(0.03)
    await asyncio.sleep(0.05)


async def repeat(r, d, ctx, log, sub):
    n = max(1, int(float(d.get("times") or 1)))
    k = ctx.setdefault("repeats", {}).get(ctx["nid"], 1)
    if k < n:
        ctx["repeats"][ctx["nid"]] = k + 1
        log.append(f"повтор {k + 1} из {n}")
        return ["__restart__"]
    return OUT


async def if_time(r, d, ctx, log, sub):
    now = datetime.now().strftime("%H:%M")
    a, b = (d.get("from") or "00:00").strip(), (d.get("to") or "23:59").strip()
    yes = a <= now <= b if a <= b else (now >= a or now <= b)
    log.append(f"{now}: {'в' if yes else 'вне'} {a}–{b}")
    return ["output_1" if yes else "output_2"]


async def if_window(r, d, ctx, log, sub):
    from .tools.apps import list_wins
    q = sub(d.get("title")).lower().strip()
    yes = bool(q) and any(q in (w.get("title") or "").lower() for w in list_wins())
    log.append(f"окно «{q}»: {'есть' if yes else 'нет'}")
    return ["output_1" if yes else "output_2"]


async def if_text(r, d, ctx, log, sub):
    q = sub(d.get("text")).lower().strip()
    yes = bool(q) and q in (ctx.get("last") or "").lower()
    return ["output_1" if yes else "output_2"]


async def clipboard_get(r, d, ctx, log, sub):
    ctx["last"] = await asyncio.to_thread(_clip_get)
    log.append(f"буфер: {ctx['last'][:60]}")
    return OUT


async def selected_text(r, d, ctx, log, sub):
    """Ctrl+C in the active window, read, put the old clipboard back."""
    from . import winput
    old = await asyncio.to_thread(_clip_get)
    await asyncio.to_thread(_clip_set, "")
    await _mods_up()
    await asyncio.to_thread(winput.press, "ctrl+c")
    txt = ""
    for _ in range(10):
        await asyncio.sleep(0.08)
        txt = await asyncio.to_thread(_clip_get)
        if txt:
            break
    await asyncio.to_thread(_clip_set, old)
    ctx["last"] = txt
    log.append(f"выделено: {txt[:60]}" if txt else "ничего не выделено")
    return OUT


async def clipboard_set(r, d, ctx, log, sub):
    await asyncio.to_thread(_clip_set, sub(d.get("text")))
    log.append("положил в буфер")
    return OUT


async def paste_text(r, d, ctx, log, sub):
    from . import winput
    text = sub(d.get("text"))
    if not text.strip():
        log.append("нечего вставлять"); return OUT
    old = await asyncio.to_thread(_clip_get)
    await asyncio.to_thread(_clip_set, text)
    await _mods_up()
    await asyncio.to_thread(winput.press, "ctrl+v")
    await asyncio.sleep(0.25)
    await asyncio.to_thread(_clip_set, old)
    log.append("вставил текст")
    return OUT


async def ai_text(r, d, ctx, log, sub):
    """A light model call (no tools, no chat history): translate / rewrite / shorten the text."""
    text, task = sub(d.get("text")), sub(d.get("task")) or "Перепиши грамотно"
    if not text.strip():
        log.append("нет текста для ИИ")
        return OUT
    msg = [{"role": "system", "content": "Ты обрабатываешь текст по инструкции. Верни ТОЛЬКО результат — без кавычек, "
                                         "пояснений и вступлений. Сохраняй переносы строк и смысл."},
           {"role": "user", "content": f"Инструкция: {task}\n\nТекст:\n{text}"}]
    from . import feedback
    llm = getattr(r.agent, "llm", None) or feedback.LLM
    if llm is None:
        log.append("модель ещё не готова"); return OUT
    res = await llm.chat("low", msg)
    ctx["last"] = ((res.get("message") or {}).get("content") or "").strip()
    log.append("ИИ: " + ctx["last"][:120])
    return OUT


async def open_path(r, d, ctx, log, sub):
    p = os.path.expandvars(sub(d.get("path")).strip().strip('"'))
    if os.path.exists(p):
        os.startfile(p)
        log.append(f"открыл {p}")
    else:
        log.append(f"нет такого пути: {p}")
    return OUT


async def screenshot(r, d, ctx, log, sub):
    from PIL import ImageGrab
    from pathlib import Path
    out = Path(os.path.expandvars(r"%USERPROFILE%\Pictures\Renard"))
    out.mkdir(parents=True, exist_ok=True)
    f = out / time.strftime("screen_%Y%m%d_%H%M%S.png")
    await asyncio.to_thread(lambda: ImageGrab.grab(all_screens=True).save(f))
    ctx["last"] = str(f)
    log.append(f"скриншот: {f}")
    return OUT


async def power(r, d, ctx, log, sub):
    import subprocess
    a = (d.get("action") or "shutdown").lower().strip()
    mins = max(0, int(float(d.get("minutes") or 0)))
    if a == "cancel":
        subprocess.run(["shutdown", "/a"], capture_output=True)
        log.append("выключение отменено")
    elif a in ("shutdown", "restart"):
        subprocess.run(["shutdown", "/s" if a == "shutdown" else "/r", "/t", str(mins * 60)], capture_output=True)
        log.append(f"{'выключение' if a == 'shutdown' else 'перезагрузка'} через {mins} мин (отмена — «отмени выключение»)")
    elif a == "lock":
        import ctypes
        ctypes.windll.user32.LockWorkStation(); log.append("экран заблокирован")
    elif a == "sleep":
        if mins:
            await asyncio.sleep(mins * 60)
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], capture_output=True)
        log.append("сон")
    return OUT


async def focus(r, d, ctx, log, sub):
    """«Не беспокоить»: Windows notifications off + Renard stays quiet (no remarks, no spoken notices)."""
    import winreg
    on = (d.get("mode") or "on").lower().strip() in ("on", "1", "вкл", "да", "true")
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\PushNotifications") as k:
            winreg.SetValueEx(k, "ToastEnabled", 0, winreg.REG_DWORD, 0 if on else 1)
    except OSError as e:
        log.append(f"уведомления Windows: {e}")
    from .prefs import update
    update({"focus_mode": on})
    await r.broadcast({"type": "prefs"})
    log.append("не беспокоить: " + ("включено" if on else "выключено"))
    return OUT


async def close_hung(r, d, ctx, log, sub):
    import ctypes
    import psutil
    import win32gui
    import win32process
    u = ctypes.windll.user32
    hung = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) and u.IsHungAppWindow(h):
            hung.append((h, win32gui.GetWindowText(h)))
        return True
    win32gui.EnumWindows(cb, None)
    done = []
    for h, title in hung:
        try:
            _, pid = win32process.GetWindowThreadProcessId(h)
            psutil.Process(pid).kill(); done.append(title[:40])
        except Exception:
            quiet()
    log.append("закрыл зависшие: " + ", ".join(done) if done else "зависших окон нет")
    return OUT


async def next_meeting(r, d, ctx, log, sub):
    import webbrowser
    from . import planner
    within = int(float(d.get("minutes") or 30))
    now = datetime.now()
    for e in planner.upcoming(2):
        st = datetime.fromisoformat(e["start"])
        if now - timedelta(minutes=15) <= st <= now + timedelta(minutes=within):
            m = re.search(r"https?://\S+", f"{e.get('place', '')} {e.get('title', '')}")
            if m:
                webbrowser.open(m.group(0)); log.append(f"открыл встречу «{e['title']}»")
            else:
                log.append(f"«{e['title']}» в {st:%H:%M} — ссылки на встречу нет (впиши её в место события)")
            return OUT
    log.append("ближайших встреч нет")
    return OUT


async def http(r, d, ctx, log, sub):
    import httpx
    url, method = sub(d.get("url")).strip(), (d.get("method") or "GET").upper()
    if not re.match(r"https?://", url):
        log.append("нет адреса"); return OUT
    async with httpx.AsyncClient(timeout=20) as c:
        if method == "POST":
            body = sub(d.get("body"))
            try:
                resp = await c.post(url, json=json.loads(body) if body.strip().startswith(("{", "[")) else None,
                                    content=None if body.strip().startswith(("{", "[")) else body.encode())
            except json.JSONDecodeError:
                resp = await c.post(url, content=body.encode())
        else:
            resp = await c.get(url)
    ctx["last"] = resp.text[:4000]
    log.append(f"{method} {url} → {resp.status_code}")
    return OUT


NEW_NODES = {f.__name__: f for f in (repeat, if_time, if_window, if_text, clipboard_get, selected_text, clipboard_set,
                                     paste_text, ai_text, open_path, screenshot, power, focus, close_hung, next_meeting, http)}
