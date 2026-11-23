"""Wake word «Ренар»: always-on, CPU-only, ~60 MB RAM, ~0% CPU in silence.

Child process (spawn) owns the microphone:
  energy VAD (adaptive noise floor) -> only speech is fed to Vosk small-ru with grammar ["ренар","[unk]"] (cheap)
  -> candidate is VERIFIED by a free-vocabulary Vosk pass over the last ~2.5 s (kills "секс"/"некст"/"кексик")
  -> keeps recording until a pause -> sends the utterance (16 kHz PCM) to the parent.
Parent: Whisper STT (voice.stt) -> agent (voice style) -> the answer is spoken phrase by phrase WHILE the model is still
writing it. After the answer it keeps listening a few seconds for a follow-up without «Ренар». Saying «Ренар» while it
talks interrupts it (barge-in).
"""
import asyncio
import io
import json
import re
import threading
import time
import wave
from collections import deque

from .config import DATA_DIR, SETTINGS
from .logs import quiet

CFG = {"wake_enabled": True, "wake_word": "ренар", "wake_model": "vosk-model-small-ru-0.22",
       "wake_silence_ms": 1100, "wake_first_silence_ms": 1800, "wake_max_s": 15, **SETTINGS.get("voice", {})}
CFG["wake_silence_ms"] = max(CFG["wake_silence_ms"], 1600)
CFG["wake_first_silence_ms"] = max(CFG["wake_first_silence_ms"], 2200)
BARGE_STOP = {"стоп", "стой", "хватит", "подожди", "погоди", "замолчи", "тихо", "ренар", "перестань", "остановись", "всё", "ладно"}
CFG["wake_max_s"] = max(CFG["wake_max_s"], 30)
MODEL_DIR = DATA_DIR / "models" / CFG["wake_model"]
SR, BLOCK = 16000, 1600
VERIFY_DELAY = 6
CONFUSERS = ["нет", "не", "все", "со", "ремонт", "рената", "ренат", "нар", "радар", "регистр", "новый", "слушай", "эй", "сенат", "лемур"]
WAKE_RE = re.compile(r"^\W*(эй\W+|окей\W+|слушай\W+)?(ренар|ренард|ринар|renard|reynard)\w*\W*", re.I)
STOP_RE = re.compile(r"^\W*(спасибо|всё|все|хватит|ничего|не надо|нет,? спасибо|отбой|пока|стоп)\W*$", re.I)
SLEEP_RE = re.compile(r"(?i)^\W*(можешь\s+)?(засни|засыпай|спи|усни|поспи|отдыхай|отдохни|иди спать|спокойной ночи|"
                      r"хватит (меня )?слушать|перестань (меня )?слушать|не слушай( меня)?|не (надо )?слушать( меня)?|отключи (микрофон|уши)|отбой|до связи|"
                      r"режим ожидания|sleep|śpij|idź spać)\W*$")
HANGING = re.compile(r"(?i)(,|\b(и|а|но|что|чтобы|потому что|потому|ну|или|в|на|с|к|у|о|по|за|из|это|типо|короче|если|когда|"
                     r"который|которая|которое|как|где|то есть|например|ещё|еще|плюс|минус|а также))\W{0,2}$")


STATE_FILE = DATA_DIR / "wake.json"
INSTANCE = None


def wanted() -> bool:
    """Last on/off choice of the user (toggle in the UI), default from settings."""
    try:
        return bool(json.loads(STATE_FILE.read_text(encoding="utf-8"))["enabled"])
    except Exception:
        return bool(CFG["wake_enabled"])


def remember(on: bool):
    STATE_FILE.write_text(json.dumps({"enabled": on}), encoding="utf-8")


def available() -> bool:
    try:
        import sounddevice
        import vosk
        return MODEL_DIR.is_dir()
    except Exception:
        return False


def _pref(key, default):
    try:
        from .prefs import get as pget
        v = pget(f"voice.{key}", default)
        return default if v is None else v
    except Exception:
        return default


class Detector:
    """Pure audio logic (no mic): push 100 ms int16 blocks, get events. Time = number of blocks, so it is testable."""

    def __init__(self, model, word: str, silence_ms: int = 1100, max_s: float = 15, first_silence_ms: int = 1800):
        from vosk import KaldiRecognizer
        self.KR, self.model, self.word = KaldiRecognizer, model, word
        self.rec = KaldiRecognizer(model, SR, json.dumps([word, "[unk]"], ensure_ascii=False))
        self.silence_blocks, self.max_blocks, self.wait_blocks = silence_ms // 100, int(max_s * 10), 50
        self.first_silence_blocks = max(first_silence_ms // 100, self.silence_blocks)
        self.ring = deque(maxlen=25)
        self.floor, self.quiet_run = 200.0, 99
        self.state, self.utt, self.utt_quiet, self.heard = "idle", [], 0, False
        self.kind, self.loud_after = "wake", 0
        self.candidates = self.rejected = 0
        self.pending = 0
        self.confusers = [w for w in CONFUSERS if word.startswith("ренар")]
        self.free = self.forced = None
        self.speak_words: set | None = None
        self.barge_rec = None
        self.vlog: list = []
        self.sensitivity = lambda: str(_pref("wake_sensitivity", "high"))
        self.strict = lambda: self.sensitivity() != "low"

    def reset(self):
        self.state, self.utt = "idle", []
        self.ring.clear(); self.rec.Reset(); self.quiet_run = 99; self.pending = 0

    def listen(self, kind: str = "listen", wait_s: float = 5.0):
        """Record a command right now (after «Слушаю.» or as a follow-up after an answer)."""
        self.state, self.utt, self.utt_quiet, self.heard = "record", [], 0, False
        self.kind, self.loud_after, self.wait_blocks = kind, 0, int(wait_s * 10)
        self.waited, self.loud_run = 0, 0

    def verify(self, audio: bytes) -> bool:
        """Second opinion on a candidate. 1) free recognition heard «нексу…» — yes. 2) otherwise a forced choice between
        the wake word and the words it is usually confused with («нет со…», «не все», «некст», «лексус»…): only if the
        wake word wins. The free model alone mishears a real «Ренар» as «нет сос»/«немцев» in ~10% of calls."""
        if self.free is None:
            self.free = self.KR(self.model, SR)
            self.forced = self.KR(self.model, SR, json.dumps([self.word] + self.confusers + ["[unk]"], ensure_ascii=False)) \
                if self.confusers else None
        r = self.free
        r.Reset()
        r.AcceptWaveform(audio)
        text = json.loads(r.FinalResult()).get("text", "")
        ok, how = self.word[:5] in text, "free"
        if not ok and self.forced is not None and self.sensitivity() == "high":
            g = self.forced
            g.Reset()
            g.AcceptWaveform(audio)
            forced = json.loads(g.FinalResult()).get("text", "")
            ok, how = self.word in forced.split(), f"forced:{forced}"
        self.vlog.append((ok, f"{text} | {how}"))
        del self.vlog[:-50]
        return ok

    @staticmethod
    def _echo(w: str, said: set) -> bool:
        import difflib
        return any(w[:4] == x[:4] or difflib.SequenceMatcher(None, w, x).ratio() >= .6 for x in said)

    def barge_check(self, blk: bytes, loud: bool) -> list:
        """While he speaks: is the person talking over him? A stop word, or 3+ words that are not in his own phrase."""
        if self.barge_rec is None:
            self.barge_rec = self.KR(self.model, SR)
        if not loud and self.quiet_run >= 6:
            return []
        r = self.barge_rec
        final = r.AcceptWaveform(blk)
        text = json.loads(r.Result()).get("text", "") if final else json.loads(r.PartialResult()).get("partial", "")
        words = [w for w in text.lower().split() if len(w) >= 3 or w in BARGE_STOP]
        if final:
            r.Reset()
        if not words:
            return []
        said = self.speak_words or set()
        foreign = [w for w in words if not self._echo(w, said)]
        stop = any(w in BARGE_STOP and w not in said for w in words)
        if stop or len(foreign) >= 3:
            r.Reset()
            self.speak_words = None
            self.state, self.utt, self.utt_quiet, self.heard = "record", list(self.ring), 0, True
            self.kind, self.loud_after, self.wait_blocks, self.waited, self.loud_run = "barge", 6, 50, 0, 0
            self.ring.clear()
            return [{"event": "barge", "heard": text, "stop": stop}]
        return []

    def push(self, blk: bytes) -> list:
        import numpy as np
        a = np.frombuffer(blk, np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(a * a)) + 1e-6)
        loud = rms > max(self.floor * 3.0, 300.0)
        if not loud:
            self.floor = self.floor * 0.98 + rms * 0.02
        out = []
        if self.state == "idle" and self.speak_words is not None:
            self.ring.append(blk)
            self.quiet_run = 0 if loud else self.quiet_run + 1
            return self.barge_check(blk, loud)
        if self.state == "record" and not self.heard:
            self.waited = getattr(self, "waited", 0) + 1
            self.utt = (self.utt + [blk])[-8:]
            self.loud_run = getattr(self, "loud_run", 0) + 1 if loud else 0
            out.append({"event": "level", "v": round(min(1.0, rms / 4000), 3)})
            if self.loud_run >= 2:
                self.heard, self.utt_quiet, self.loud_after = True, 0, 2
            elif self.waited > self.wait_blocks:
                out.append({"event": "utterance", "pcm": b"", "kind": self.kind})
                self.reset()
            return out
        if self.state == "record":
            self.utt.append(blk)
            self.loud_after += 1 if loud else 0
            self.utt_quiet = 0 if loud else self.utt_quiet + 1
            out.append({"event": "level", "v": round(min(1.0, rms / 4000), 3)})
            n = len(self.utt)
            need = self.first_silence_blocks if (self.kind == "wake" and self.loud_after < 6) else self.silence_blocks
            if (self.heard and self.utt_quiet >= need) or n > self.max_blocks or (not self.heard and n > self.wait_blocks):
                out.append({"event": "utterance", "pcm": b"".join(self.utt) if self.heard else b"", "kind": self.kind})
                self.reset()
            return out
        self.ring.append(blk)
        self.quiet_run = 0 if loud else self.quiet_run + 1
        if self.pending:
            self.pending -= 1
            if self.pending == 0:
                ok = self.verify(b"".join(self.ring))
                if not ok and not self.strict():
                    ok = True
                out.append({"event": "candidate", "ok": ok, "heard": self.vlog[-1][1] if self.vlog else ""})
                if ok:
                    out.append({"event": "wake"})
                    self.state, self.utt, self.utt_quiet, self.heard = "record", list(self.ring), 0, True
                    self.kind, self.loud_after, self.wait_blocks = "wake", 0, 50
                    self.waited, self.loud_run = 0, 0
                    self.ring.clear()
                else:
                    self.rejected += 1
            return out
        if self.quiet_run < 6:
            if self.rec.AcceptWaveform(blk):
                hit = self.word in json.loads(self.rec.Result()).get("text", "")
            else:
                hit = self.word in json.loads(self.rec.PartialResult()).get("partial", "")
            if hit:
                self.rec.Reset()
                self.candidates += 1
                self.pending = VERIFY_DELAY
        elif self.quiet_run == 6:
            self.rec.Reset()
        return out


def _worker(conn, model_dir: str, word: str, silence_ms: int, max_s: float, first_silence_ms: int = 1800):
    import sounddevice as sd
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)
    det = Detector(Model(model_dir), word, silence_ms, max_s, first_silence_ms)
    q: "deque[bytes]" = deque()
    ev = threading.Event()
    paused = False

    def cb(indata, frames, t, status):
        q.append(bytes(indata)); ev.set()

    stream = sd.RawInputStream(samplerate=SR, blocksize=BLOCK, channels=1, dtype="int16", callback=cb)
    stream.start()
    conn.send({"event": "ready", "device": sd.query_devices(kind="input")["name"]})
    while True:
        while conn.poll():
            cmd = conn.recv()
            if cmd == "stop":
                stream.stop(); stream.close(); return
            if cmd == "pause":
                paused = True; det.reset(); q.clear()
            elif cmd == "resume":
                paused = False; det.reset(); q.clear()
            elif isinstance(cmd, str) and cmd.startswith("speak:"):
                txt = cmd[6:].lower()
                det.speak_words = set(re.findall(r"\w{3,}", txt)) if txt else None
                if det.state == "idle":
                    det.barge_rec = None
            elif isinstance(cmd, str) and cmd.startswith("listen"):
                _, kind, wait = (cmd.split(":") + ["listen", "5"])[:3]
                paused = False; q.clear()
                det.listen(kind or "listen", float(wait or 5))
        if not ev.wait(0.2):
            continue
        ev.clear()
        lvl = None
        while q:
            blk = q.popleft()
            if paused:
                continue
            for e in det.push(blk):
                if e["event"] == "level":
                    lvl = e
                else:
                    conn.send(e)
        if lvl:
            conn.send(lvl)


def pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
    return buf.getvalue()


def play_wav(wav: bytes):
    """Blocking playback on the default output device."""
    import numpy as np
    import sounddevice as sd
    w = wave.open(io.BytesIO(wav))
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    sd.play(a, w.getframerate()); sd.wait()


def play_pcm(pcm: bytes, sr: int):
    import numpy as np
    import sounddevice as sd
    if pcm:
        sd.play(np.frombuffer(pcm, np.int16), sr); sd.wait()


def stop_playback():
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        quiet()


def chime(up: bool = True) -> bytes:
    import numpy as np
    t = np.linspace(0, 0.18, int(SR * 0.18), False)
    f1, f2 = (880, 1320) if up else (660, 440)
    tone = (np.sin(2 * np.pi * f1 * t) * np.exp(-t * 18) + 0.6 * np.sin(2 * np.pi * f2 * t) * np.exp(-t * 22))
    return pcm_to_wav((tone / 1.6 * 9000).astype(np.int16).tobytes())


ACKS = {
    ("web_search", "fetch_page", "news", "skill_search"): ["Сейчас поищу.", "Секунду, ищу.", "Гляну в интернете."],
    ("look_at_screen", "look_at_window", "look_at_image"): ["Смотрю.", "Сейчас гляну.", "Секунду, смотрю."],
    ("weather",): ["Сейчас узнаю.", "Секунду."],
    ("diagnose_pc", "top_processes", "largest_files", "junk_report", "defender_status", "search_files"): ["Сейчас проверю.", "Секунду, проверяю."],
    ("analyze_media", "read_file", "project_map"): ["Секунду, читаю.", "Сейчас разберусь."],
    ("run_python", "run_command"): ["Запускаю.", "Секунду, считаю."],
    ("ask_cloud", "ask_cloud_confirm"): ["Спрошу у сильной модели, это займёт немного времени.", "Передаю задачу в облако, секунду."],
    ("site_api", "site_learn"): ["Сейчас гляну.", "Секунду, смотрю на сайте."],
    ("inspect_program",): ["Сейчас проверю программу.", "Секунду, разбираю файл."],
}
_last_ack = {"text": ""}


def ack_for(tool: str, note: str) -> str:
    """The phrase to say while `tool` runs (a different one than last time), or ''."""
    import random
    if note.startswith("загружаю"):
        return "Секунду, просыпаюсь."
    for names, phrases in ACKS.items():
        if tool in names:
            pick = random.choice([p for p in phrases if p != _last_ack["text"]] or phrases)
            _last_ack["text"] = pick
            return pick
    return ""


class Speaker:
    """Speaks an answer while it is being written: complete sentences are synthesized (next one while the current one
    plays) and played in order. say() replaces the stream with a ready spoken text (tool/router results)."""
    LIMIT = 650

    def __init__(self, ww: "WakeWord"):
        self.ww, self.buf, self.override = ww, "", None
        self.lang, self.total, self.cut = None, 0, False
        self.stopped = False
        self.text_q: asyncio.Queue = asyncio.Queue()
        self.audio_q: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.started = asyncio.Event()
        self.tasks = [asyncio.create_task(self._synth()), asyncio.create_task(self._play())]

    def _push(self, chunk: str, final: bool = False):
        from . import voice
        if self.cut or not chunk.strip():
            return
        parts, lang = voice.tts.prepare(chunk, limit=10_000, lang=self.lang if self.lang not in (None, "ru") else None)
        self.lang = self.lang or lang
        for p, l in parts:
            if self.total + len(p) > self.LIMIT and self.total > 0:
                self.text_q.put_nowait(("Остальное на экране.", "ru"))
                self.cut = True
                return
            self.total += len(p)
            self.text_q.put_nowait((p, l))

    def feed(self, token: str):
        if self.override is not None or self.stopped:
            return
        self.buf += token
        if self.buf.count("```") % 2:
            return
        ends = [m.end() for m in re.finditer(r"[.!?…](?=\s)|\n", self.buf)]
        ends = [e for e in ends if e >= (25 if self.total - getattr(self, "ack_chars", 0) <= 0 else 60)]
        if ends:
            chunk, self.buf = self.buf[:ends[-1]], self.buf[ends[-1]:]
            self._push(chunk)

    def say(self, text: str):
        self.override, self.buf = text, ""
        self._push(text)

    def ack(self, text: str):
        """A short «Сейчас поищу» while a slow tool runs — only if nothing has been said yet, once per answer."""
        if self.total == 0 and self.override is None and not self.stopped and not getattr(self, "acked", False):
            self.acked = True
            self._push(text)
            self.ack_chars = self.total

    async def finish(self):
        if self.override is None and not self.stopped:
            self._push(self.buf)
        self.buf = ""
        await self.text_q.put(None)
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def stop(self):
        self.stopped = True
        stop_playback()

    async def _synth(self):
        from . import voice
        while True:
            item = await self.text_q.get()
            if item is None:
                await self.audio_q.put(None)
                return
            if self.stopped:
                continue
            try:
                p, l = item
                pcm, sr = await asyncio.to_thread(voice.tts.phrase_pcm, p, l)
            except Exception as e:
                print("TTS:", e)
                continue
            await self.audio_q.put((p, pcm + b"\x00\x00" * int(sr * 0.14), sr))

    async def _play(self):
        while True:
            item = await self.audio_q.get()
            if item is None:
                return
            if self.stopped:
                continue
            p, pcm, sr = item
            self.started.set()
            own_name = "ренар" in p.lower() or CFG["wake_word"][:5] in p.lower()
            if own_name or not self.ww.barge:
                self.ww.send("pause")
            else:
                self.ww.send("speak:" + p)
            self.ww.said.append((time.time(), p))
            lips = asyncio.create_task(self._lips(pcm, sr))
            try:
                await asyncio.to_thread(play_pcm, pcm, sr)
            finally:
                lips.cancel()
                if own_name or not self.ww.barge:
                    self.ww.send("resume")
                else:
                    self.ww.send("speak:")

    async def _lips(self, pcm: bytes, sr: int):
        """The mouth of the avatar follows the voice: loudness every 60 ms, sent in time with the playback."""
        import numpy as np
        a = np.frombuffer(pcm, np.int16).astype(np.float32)
        hop = int(sr * .06)
        env = [float(np.sqrt(np.mean(a[i:i + hop] ** 2)) / 6000) for i in range(0, len(a), hop)]
        t0 = time.perf_counter()
        for i, v in enumerate(env):
            if self.stopped:
                break
            await self.ww.broadcast({"type": "activity", "source": "wake", "state": "speaking", "level": round(min(1.0, v), 3)})
            await asyncio.sleep(max(0.0, t0 + (i + 1) * .06 - time.perf_counter()))


class WakeWord:
    def __init__(self, agent, broadcast, status: dict):
        self.agent, self.broadcast, self.status = agent, broadcast, status
        self.proc = self.conn = None
        self.loop = None
        self.enabled = False
        self.device = ""
        self.speaker: Speaker | None = None
        self.busy = False
        self.said: deque = deque(maxlen=40)
        global INSTANCE
        INSTANCE = self
        try:
            from .personas import wake_word
            CFG["wake_word"] = wake_word()
        except Exception:
            quiet()
        status["wake_available"] = available()
        status["wake"] = False

    @property
    def speaking(self) -> bool:
        return self.speaker is not None

    @property
    def barge(self) -> bool:
        return bool(_pref("barge_in", True))

    async def start(self):
        if not available():
            return False
        if self.proc and self.proc.is_alive():
            return True
        import multiprocessing as mp
        self.loop = asyncio.get_running_loop()
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self.proc = ctx.Process(target=_worker, args=(child, str(MODEL_DIR), CFG["wake_word"], CFG["wake_silence_ms"],
                                                      CFG["wake_max_s"], CFG["wake_first_silence_ms"]), daemon=True)
        self.proc.start()
        self.conn = parent
        ok = await asyncio.to_thread(self._wait_ready)
        if not ok:
            self.stop_sync()
            return False
        self.enabled = self.status["wake"] = True
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def _wait_ready(self) -> bool:
        if not self.conn.poll(30):
            return False
        msg = self.conn.recv()
        self.device = msg.get("device", "")
        return msg.get("event") == "ready"

    def stop_sync(self):
        self.enabled = self.status["wake"] = False
        if self.proc is not None:
            try:
                self.conn.send("stop"); self.proc.join(2)
            except Exception:
                quiet()
            if self.proc.is_alive():
                self.proc.terminate()
        self.proc = self.conn = None

    async def stop(self):
        await asyncio.to_thread(self.stop_sync)

    async def toggle(self) -> bool:
        if self.enabled:
            await self.stop()
        else:
            await self.start()
        return self.enabled

    def send(self, cmd: str):
        try:
            if self.conn:
                self.conn.send(cmd)
        except Exception:
            quiet()

    def _reader(self):
        conn = self.conn
        while self.enabled and conn is self.conn:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            asyncio.run_coroutine_threadsafe(self._on(msg), self.loop)

    async def _on(self, msg: dict):
        e = msg.get("event")
        if e == "wake":
            if self.speaker:
                self.speaker.stop()
            await self.broadcast({"type": "activity", "source": "wake", "state": "listening"})
            if _pref("wake_beep", True):
                asyncio.get_running_loop().run_in_executor(None, play_wav, chime())
            from . import voice
            asyncio.get_running_loop().run_in_executor(None, voice.stt.warmup)
        elif e == "barge":
            if self.speaker:
                self.speaker.stop()
            await self.broadcast({"type": "activity", "source": "wake", "state": "listening"})
        elif e == "level":
            await self.broadcast({"type": "activity", "source": "wake", "level": msg["v"]})
        elif e == "candidate":
            log = self.status.setdefault("wake_log", [])
            log.append({"t": time.strftime("%H:%M:%S"), "ok": msg.get("ok"), "heard": msg.get("heard", "")})
            del log[:-30]
        elif e == "utterance":
            await self._handle_utterance(msg.get("pcm") or b"", msg.get("kind", "wake"))

    async def _idle(self):
        await self.broadcast({"type": "activity", "source": "wake", "state": "idle"})

    async def _say(self, text: str):
        from . import voice
        self.send("pause")
        try:
            await asyncio.to_thread(play_wav, await asyncio.to_thread(voice.tts.synth, text))
        finally:
            self.send("resume")

    def _conversation_wait(self) -> float:
        """How long to keep listening after an answer. In conversation mode: until «Ренар, засни» or this much silence."""
        if _pref("conversation", True):
            return float(_pref("conversation_idle_s", 120))
        return float(_pref("followup_s", 6)) if _pref("followup", True) else 0.0

    async def _keep_listening(self, kind: str = "followup"):
        wait = self._conversation_wait()
        if wait > 0:
            self.send(f"listen:{kind}:{wait:g}")
            await self.broadcast({"type": "activity", "source": "wake", "state": "listening", "followup": True})
        else:
            await self._idle()

    async def _handle_utterance(self, pcm: bytes, kind: str = "wake"):
        from . import voice
        followup = kind in ("followup", "cont")
        partial = getattr(self, "partial", "")
        if len(pcm) < SR * 2 * 0.3:
            if kind == "cont" and partial:
                self.partial = ""
                return await self._answer(partial)
            self.partial = ""
            if followup and _pref("wake_beep", True):
                asyncio.get_running_loop().run_in_executor(None, play_wav, chime(False))
            await self._idle()
            return
        for _ in range(600):
            if not self.busy:
                break
            await asyncio.sleep(0.1)
        r = await asyncio.to_thread(voice.stt.transcribe, pcm_to_wav(pcm), None, "wake")
        text = WAKE_RE.sub("", r.get("text", "")).strip(" .!?")
        if CFG["wake_word"] != "ренар":
            text = re.sub(rf"(?i)^\W*(эй\W+|окей\W+|слушай\W+)?{re.escape(CFG['wake_word'][:5])}\w*\W*", "", text).strip(" .!?")
        if text and self._is_echo(text):
            print("wake: own echo ignored:", text)
            return await self._keep_listening(kind="followup")
        if kind == "cont" and partial:
            text = (partial + " " + text).strip()
            self.partial = ""
        if not text.strip(" ,"):
            if followup:
                return await self._keep_listening(kind="followup")
            if r.get("silent"):
                await self._idle()
                return
            await self._say("Слушаю.")
            self.send("listen:listen:8")
            await self.broadcast({"type": "activity", "source": "wake", "state": "listening"})
            return
        if SLEEP_RE.match(text) or (followup and STOP_RE.match(text)):
            self.partial = ""
            await self.broadcast({"type": "activity", "source": "wake", "role": "user", "text": text, "state": "idle"})
            if SLEEP_RE.match(text):
                await self._say("Хорошо, сплю. Позови «Ренар», когда понадоблюсь.")
            elif _pref("wake_beep", True):
                await asyncio.to_thread(play_wav, chime(False))
            await self._idle()
            return
        if HANGING.search(text) and kind != "cont" and len(text) < 400:
            self.partial = text
            self.send("listen:cont:2.5")
            return
        await self._answer(text.strip(" ,"))

    def _is_echo(self, text: str) -> bool:
        """Most words of the utterance were just spoken by him (last 20 s) -> the mic heard the speakers, not the user."""
        words = re.findall(r"\w{3,}", text.lower())
        if len(words) < 2:
            return False
        recent = " ".join(p for t, p in self.said if time.time() - t < 20).lower()
        if not recent:
            return False
        said = set(re.findall(r"\w{3,}", recent))
        own = sum(1 for w in words if Detector._echo(w, said))
        return own / len(words) >= .75

    async def _answer(self, text: str):
        await self.broadcast({"type": "activity", "source": "wake", "role": "user", "text": text, "state": "thinking"})
        self.busy = True
        answer = []
        sp = self.speaker = Speaker(self)

        async def send(ev: dict):
            t = ev.get("type")
            if t == "token":
                answer.append(ev["text"])
                sp.feed(ev["text"])
            elif t == "speech":
                sp.say(ev["text"])
            elif t == "note" and _pref("voice_acks", True):
                a = ack_for(ev.get("tool") or "", ev.get("text") or "")
                if a:
                    sp.ack(a)
            elif t == "tool":
                await self.broadcast({"type": "activity", "source": "wake", "state": "tool"})

        try:
            async with self.agent.lock:
                await self.agent.handle(text, "wake", send, voice=True)
            final = "".join(answer).strip() or "Готово."
            if not answer:
                sp.say(final)
            await self.broadcast({"type": "activity", "source": "wake", "role": "assistant", "text": final, "state": "speaking"})
            await sp.finish()
        finally:
            interrupted = sp.stopped
            self.speaker, self.busy = None, False
        if interrupted:
            return
        await self._keep_listening()
