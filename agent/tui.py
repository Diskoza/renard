"""Terminal UI (like Claude Code): python -m agent.tui   (or pc.cmd)

Thin client over the agent server WebSocket. Starts the server in the background if needed.
"""
import asyncio
import io
import json
import threading
import time
import uuid
import wave

import httpx
import websockets
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Markdown, Static

from textual.theme import Theme

from .config import DATA_DIR
from .launcher import BASE, WS_URL, ensure_server
from .router import MODE_NAMES, norm_mode
from .logs import quiet

HELP = """**Команды**
- `/mode авто|низкий|средний|высокий` (или `low|medium|high`) — режим (сейчас: {mode})
- `/high текст`, `/medium текст`, `/low текст` — один запрос в нужном режиме
- `/unload` — выгрузить модели из видеопамяти
- `/mem` — показать память · `/status` — состояние ПК · `/clear` — очистить экран
- `/new` — новый разговор · `/exit` — выход (сервер остаётся работать в фоне)
- **Ctrl+R** — голос: начать запись, ещё раз Ctrl+R — отправить (ответ будет озвучен)
- `/voice on|off` — озвучивать все ответы
- ↑/↓ — история ввода · Ctrl+L — очистить · Ctrl+C — выход"""

HINT = "Enter — отправить · Ctrl+R — голос · /help — команды · Ctrl+C — выход"

RENARD_THEME = Theme(
    name="renard", primary="#D97757", secondary="#C15F3C", accent="#D97757",
    foreground="#E8E6E3", background="#1F1E1D", surface="#262624", panel="#2B2A28",
    success="#7FB069", warning="#E0A458", error="#E26D5A", dark=True,
    variables={"text-muted": "#8C8A85", "border": "#3A3836", "input-cursor-background": "#D97757",
               "footer-key-foreground": "#D97757", "scrollbar": "#3A3836", "scrollbar-hover": "#D97757"},
)

BANNER = """[#D97757]✻[/] [b]Renard[/b] [#8C8A85]— личный локальный ассистент[/]
[#8C8A85]  /help — команды · /mode высокий — сложный код · всё работает офлайн на твоём ПК[/]"""

CSS = """
Screen { background: #1F1E1D; }
#top { height: 1; padding: 0 1; background: #262624; color: #8C8A85; }
#log { padding: 0 2; scrollbar-size-vertical: 1; }
#banner { border: round #D97757; padding: 0 1; margin: 1 0 0 0; height: auto; }
.user { margin: 1 0 0 0; color: #E8E6E3; background: #2B2A28; padding: 0 1; }
.meta { color: #8C8A85; margin: 1 0 0 0; }
.route { color: #7FB069; margin: 1 0 0 0; }
.tool { color: #E0A458; padding: 0 0 0 2; }
.err { color: #E26D5A; }
.mem { color: #8C8A85; text-style: italic; }
Markdown { margin: 0; padding: 0; background: transparent; }
#prompt { dock: bottom; border: round #D97757; background: #1F1E1D; }
#prompt:focus { border: round #D97757; }
#hint { dock: bottom; height: 1; padding: 0 2; color: #8C8A85; }
"""


def session_id() -> str:
    p = DATA_DIR / "tui_session"
    if p.exists():
        return p.read_text().strip()
    s = "tui-" + uuid.uuid4().hex[:6]
    p.write_text(s)
    return s


class HistoryInput(Input):
    BINDINGS = [Binding("up", "hist(-1)", show=False), Binding("down", "hist(1)", show=False)]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.history: list[str] = []
        self.pos = 0

    def push(self, text: str):
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.pos = len(self.history)

    def action_hist(self, d: int):
        if not self.history:
            return
        self.pos = max(0, min(len(self.history), self.pos + d))
        self.value = self.history[self.pos] if self.pos < len(self.history) else ""
        self.cursor_position = len(self.value)


class AgentTUI(App):
    CSS = CSS
    TITLE = "Renard"
    BINDINGS = [Binding("ctrl+c", "quit", "Выход", priority=True), Binding("ctrl+l", "clear", "Очистить"),
                Binding("ctrl+r", "voice", "Голос", priority=True)]

    def __init__(self):
        super().__init__()
        self.mode = ""
        self.session = session_id()
        self.ws = None
        self.busy = False
        self.cur_md = None
        self.cur_text = ""
        self.cur_meta: Static | None = None
        self.meta_text = ""
        self.cur_route = False
        self.md_stream = None
        self.last_render = 0.0
        self.rec_stream = None
        self.rec_frames: list = []
        self.speak_next = False
        self.speak_all = False
        self.spoken = ""

    def compose(self) -> ComposeResult:
        yield Static("Renard · подключаюсь…", id="top")
        yield VerticalScroll(id="log")
        yield Static(HINT, id="hint")
        yield HistoryInput(placeholder="Напиши… (/help — команды)", id="prompt")

    async def on_mount(self):
        self.register_theme(RENARD_THEME)
        self.theme = "renard"
        await self.add(Static(BANNER, id="banner"))
        self.query_one("#prompt").focus()
        self.connect()
        self.set_interval(5, self.refresh_status)

    @work(exclusive=True, group="ws")
    async def connect(self):
        ok = await asyncio.to_thread(ensure_server)
        if not ok:
            await self.add(Static("Не удалось запустить сервер агента. Смотри data/server.log", classes="err"))
            return
        while True:
            try:
                async with websockets.connect(WS_URL, max_size=None) as ws:
                    self.ws = ws
                    await self.refresh_status()
                    async for raw in ws:
                        await self.handle_agent_event(json.loads(raw))
            except Exception as e:
                self.ws = None
                self.query_one("#top", Static).update(f"Renard · нет связи ({type(e).__name__}), переподключаюсь…")
                await asyncio.sleep(2)
                await asyncio.to_thread(ensure_server)

    async def refresh_status(self):
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                s = (await c.get(BASE + "/api/status")).json()
        except Exception:
            return
        g = s.get("gpu") or {}
        loaded = ", ".join(m["name"] for m in s.get("loaded", [])) or "VRAM свободна"
        self.query_one("#top", Static).update(
            f"✻ Renard · режим: {MODE_NAMES.get(self.mode, 'авто')} · модель: {loaded} · GPU {g.get('load_%', '?')}% · "
            f"VRAM {g.get('vram_used_gb', '?')}/{g.get('vram_total_gb', '?')} ГБ · RAM {s.get('ram_used_gb')} ГБ · "
            f"сервер {s.get('agent_ram_mb')} МБ")

    async def add(self, widget):
        log = self.query_one("#log", VerticalScroll)
        await log.mount(widget)
        log.scroll_end(animate=False)
        return widget

    async def ensure_answer(self):
        if self.cur_md is None:
            self.cur_text = ""
            self.md_stream = None
            widget = Static("", markup=False) if self.cur_route else Markdown("")
            self.cur_md = await self.add(widget)
            if isinstance(widget, Markdown):
                self.md_stream = Markdown.get_stream(widget)

    async def write_token(self, chunk: str):
        self.cur_text += chunk
        if self.md_stream is not None:
            await self.md_stream.write(chunk)
        else:
            self.cur_md.update(self.cur_text)

    async def set_answer(self, text: str):
        if self.md_stream is not None:
            await self.md_stream.stop()
            self.md_stream = None
            return
        r = self.cur_md.update(text)
        if r is not None and hasattr(r, "__await__"):
            await r

    async def add_meta(self, text: str, cls: str = "meta"):
        if self.cur_meta is None:
            self.meta_text = text
            self.cur_meta = Static(text, classes=cls, markup=False)
            await self.add(self.cur_meta)
        else:
            self.meta_text += " · " + text
            self.cur_meta.update(self.meta_text)

    async def flush_answer(self):
        if self.cur_md is not None:
            await self.set_answer(self.cur_text)
            self.cur_md = None
            self.query_one("#log", VerticalScroll).scroll_end(animate=False)

    async def handle_agent_event(self, ev: dict):
        t = ev.get("type")
        if t == "token":
            await self.ensure_answer()
            await self.write_token(ev["text"])
            self.spoken += ev["text"]
            now = time.time()
            if now - self.last_render > 0.15:
                self.last_render = now
                self.query_one("#log", VerticalScroll).scroll_end(animate=False)
        elif t == "route":
            self.cur_route = True
            await self.add_meta(f"⚡ без LLM · {ev['tool']} · {ev['ms']} мс", "route")
        elif t == "mode":
            await self.add_meta(f"✻ {MODE_NAMES.get(ev['mode'], ev['mode'])} · {ev['model']}")
        elif t == "tool":
            await self.flush_answer()
            res = (ev.get("result") or "").strip().splitlines()
            preview = "\n".join("  │ " + l for l in res[:4]) + ("\n  │ …" if len(res) > 4 else "")
            args = json.dumps(ev.get("args", {}), ensure_ascii=False)
            if len(args) > 90:
                args = args[:90] + "…"
            await self.add(Static(f"● {ev['name']}({args})\n{preview}", classes="tool", markup=False))
        elif t == "stats":
            if (ev.get("tokens") or 0) >= 5:
                await self.add_meta(f"{ev.get('tps')} ток/с · {ev.get('wall_s')} с")
        elif t == "confirm":
            await self.flush_answer()
            self.query_one("#hint", Static).update("⚠ Нужно подтверждение: напиши «да» или «нет»")
        elif t == "error":
            await self.add(Static("Ошибка: " + ev.get("text", ""), classes="err", markup=False))
        elif t == "alert":
            await self.add(Static("⚠ " + ev.get("text", ""), classes="err", markup=False))
        elif t == "memory":
            await self.add(Static("🧠 " + "\n🧠 ".join(ev.get("saved", [])), classes="mem", markup=False))
        elif t == "done":
            await self.flush_answer()
            if (self.speak_next or self.speak_all) and self.spoken.strip():
                self.speak(self.spoken)
            self.speak_next, self.spoken = False, ""
            self.cur_md, self.cur_meta, self.busy, self.cur_route = None, None, False, False
            if not str(self.query_one("#hint", Static).render()).startswith("⚠"):
                self.query_one("#hint", Static).update(HINT)
            await self.refresh_status()

    @on(Input.Submitted, "#prompt")
    async def submitted(self, event: Input.Submitted):
        text = event.value.strip()
        inp = self.query_one("#prompt", HistoryInput)
        inp.value = ""
        if not text:
            return
        inp.push(text)
        if text.startswith("/") and await self.command(text):
            return
        if not self.ws:
            await self.add(Static("Нет связи с сервером, подожди пару секунд.", classes="err"))
            return
        await self.add(Static("> " + text, classes="user", markup=False))
        self.busy = True
        self.query_one("#hint", Static).update("… думаю (следующее сообщение встанет в очередь)")
        await self.ws.send(json.dumps({"text": text, "session": self.session, "mode": self.mode}))

    async def command(self, text: str) -> bool:
        parts = text.split(maxsplit=1)
        cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        if norm_mode(cmd[1:]) and arg:
            return False
        if cmd == "/help":
            await self.add(Markdown(HELP.format(mode=MODE_NAMES.get(self.mode, "авто"))))
        elif cmd == "/mode":
            if arg in ("", "auto", "авто"):
                self.mode = ""
            elif norm_mode(arg):
                self.mode = norm_mode(arg)
            else:
                await self.add(Static("Режимы: авто, низкий, средний, высокий", classes="err"))
                return True
            await self.add(Static(f"Режим: {MODE_NAMES.get(self.mode, 'авто')}", classes="meta"))
            await self.refresh_status()
        elif cmd == "/unload":
            async with httpx.AsyncClient(timeout=30) as c:
                await c.post(BASE + "/api/unload")
            await self.add(Static("Видеопамять освобождена.", classes="meta"))
            await self.refresh_status()
        elif cmd in ("/mem", "/memory"):
            async with httpx.AsyncClient(timeout=5) as c:
                m = (await c.get(BASE + "/api/memory")).json()
            body = "\n\n".join(m["notes"].values())
            await self.add(Markdown("**Память**\n\n" + m["index"] + "\n\n---\n\n" + body))
        elif cmd == "/status":
            if self.ws:
                self.busy = True
                await self.ws.send(json.dumps({"text": "состояние пк", "session": self.session}))
        elif cmd == "/voice":
            self.speak_all = arg.lower() in ("on", "вкл", "да", "1")
            await self.add(Static(f"Озвучивать все ответы: {'да' if self.speak_all else 'нет'}", classes="meta"))
        elif cmd == "/clear":
            await self.action_clear()
        elif cmd == "/new":
            self.session = "tui-" + uuid.uuid4().hex[:6]
            (DATA_DIR / "tui_session").write_text(self.session)
            await self.action_clear()
            await self.add(Static("Новый разговор.", classes="meta"))
        elif cmd in ("/exit", "/quit", "/q"):
            self.exit()
        else:
            await self.add(Static(f"Неизвестная команда {cmd}. /help — список.", classes="err"))
        return True

    async def action_voice(self):
        hint = self.query_one("#hint", Static)
        if self.rec_stream is None:
            try:
                import sounddevice as sd
            except Exception as e:
                await self.add(Static(f"Нет sounddevice: {e}", classes="err"))
                return
            self.rec_frames = []
            threading.Thread(target=lambda: httpx.post(BASE + "/api/voice/warmup", timeout=5), daemon=True).start()
            self.rec_stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                             callback=lambda data, *_: self.rec_frames.append(bytes(data)))
            self.rec_stream.start()
            hint.update("● ЗАПИСЬ… говори, затем Ctrl+R — отправить")
            return
        self.rec_stream.stop()
        self.rec_stream.close()
        self.rec_stream = None
        hint.update("… распознаю речь")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"".join(self.rec_frames))
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = (await c.post(BASE + "/api/voice/stt", content=buf.getvalue())).json()
        except Exception as e:
            r = {"text": "", "error": str(e)}
        text = (r.get("text") or "").strip()
        hint.update(HINT)
        if not text:
            await self.add(Static("Не расслышал: " + (r.get("error") or "тишина"), classes="err"))
            return
        await self.add(Static(f"🎤 {r.get('ms')} мс", classes="meta"))
        self.speak_next = True
        inp = self.query_one("#prompt", HistoryInput)
        inp.value = text
        await inp.action_submit()

    def speak(self, text: str):
        def run():
            try:
                wav = httpx.post(BASE + "/api/voice/tts", json={"text": text}, timeout=60).content
                if wav[:4] == b"RIFF":
                    import winsound
                    winsound.PlaySound(wav, winsound.SND_MEMORY)
            except Exception:
                quiet()
        threading.Thread(target=run, daemon=True).start()

    async def action_clear(self):
        await self.query_one("#log", VerticalScroll).remove_children()


def main():
    AgentTUI().run()


if __name__ == "__main__":
    main()
