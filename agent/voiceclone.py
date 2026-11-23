"""Own voices for Renard (the idea of VoiceStudio, github.com/debpalash/VoiceStudio): a voice is cloned from 3–10 s of
speech — recorded with the mic, an audio file, or the sound track of a video. Engine: OmniVoice (k2-fsa, Apache-2.0,
0.6B, Russian / Polish / Ukrainian / English) in a separate venv (data/voiceclone/venv) and a separate process
(voiceclone_worker.py): it loads on first use and is stopped after a few idle minutes, like Whisper.

A voice = data/voices/clone/<name>/ref.wav (24 kHz mono, trimmed) + ref.txt (what is said in it) + meta.json.
Selected as the TTS voice «clone:<name>»; when the clone cannot speak (no venv, a game holds the GPU and the CPU is too
slow, an error) the Piper voice speaks instead — the answer is never silent.
"""
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .config import DATA_DIR
from .logs import quiet

ROOT = DATA_DIR / "voices" / "clone"
VENV_PY = DATA_DIR / "voiceclone" / "venv" / "Scripts" / "python.exe"
WORKER = Path(__file__).with_name("voiceclone_worker.py")
IDLE_SEC = 300
MIN_S, MAX_S = 3.0, 12.0


def installed() -> bool:
    return VENV_PY.exists()


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


def safe_name(name: str) -> str:
    n = re.sub(r"[^\w\- ]+", "", (name or "").strip())[:40].strip()
    return n or time.strftime("voice_%Y%m%d_%H%M%S")


def voices() -> list[dict]:
    out = []
    if ROOT.is_dir():
        for d in sorted(ROOT.iterdir()):
            if (d / "ref.wav").exists():
                meta = {}
                try:
                    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                except Exception:
                    quiet()
                out.append({"id": f"clone:{d.name}", "name": d.name, "text": (d / "ref.txt").read_text(encoding="utf-8")
                            if (d / "ref.txt").exists() else "", **{k: meta.get(k) for k in ("source", "created", "seconds")}})
    return out


def _decode(raw: bytes, start: float = 0.0, dur: float | None = None) -> tuple["np.ndarray", float]:
    """Any audio / video file -> 24 kHz mono float32 (ffmpeg), optionally a part of it."""
    import numpy as np
    ff = _ffmpeg()
    if not ff:
        raise RuntimeError("нужен ffmpeg (winget install ffmpeg)")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.bin"
        src.write_bytes(raw)
        cmd = [ff, "-v", "error", "-y"] + (["-ss", str(start)] if start else []) + ["-i", str(src)]
        cmd += (["-t", str(dur)] if dur else []) + ["-vn", "-ac", "1", "-ar", "24000", "-f", "s16le", "-"]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("не удалось прочитать звук: " + r.stderr.decode("utf-8", "replace")[:200])
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    return a, len(a) / 24000


def best_part(a, sr: int = 24000, want: float = 8.0):
    """The densest speech window of `want` seconds (a song intro / silence is skipped), cut at quiet points."""
    import numpy as np
    if len(a) <= want * sr:
        return a
    hop = sr // 10
    e = np.array([float(np.sqrt(np.mean(a[i:i + hop] ** 2) + 1e-9)) for i in range(0, len(a) - hop, hop)])
    thr = max(1e-3, np.percentile(e, 60) * 0.35)
    voiced = (e > thr).astype(np.float32)
    win = int(want * 10)
    score = np.convolve(voiced, np.ones(win), "valid")
    i0 = int(np.argmax(score))
    s = i0
    while s > max(0, i0 - 8) and voiced[s]:
        s -= 1
    end = min(len(e) - 1, s + win)
    while end < min(len(e) - 1, s + win + 8) and voiced[end]:
        end += 1
    return a[s * hop:end * hop]


def _wav16(a, sr: int = 24000) -> bytes:
    import io
    import wave
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def _norm(a):
    import numpy as np
    a = a - float(np.mean(a))
    peak = float(np.max(np.abs(a))) or 1.0
    return (a / peak * 0.9).astype(np.float32)


def add_voice(name: str, raw: bytes, source: str = "file", text: str = "", start: float = 0.0, dur: float | None = None,
              consent: bool = False) -> dict:
    """Store a new voice. `consent`: the owner of the voice agreed (his own voice, or a person who allowed it)."""
    import numpy as np
    if not consent:
        return {"ok": False, "error": "Отметь, что это твой голос или у тебя есть согласие его владельца."}
    a, total = _decode(raw, start, dur)
    if total < MIN_S:
        return {"ok": False, "error": f"Слишком коротко ({total:.1f} с) — нужно хотя бы {MIN_S:.0f} секунды речи."}
    part = _norm(best_part(a, want=min(MAX_S - 2, max(MIN_S, total))))
    if float(np.sqrt(np.mean(part ** 2))) < 0.01:
        return {"ok": False, "error": "В записи почти тишина — запиши громче / ближе к микрофону."}
    name = safe_name(name)
    d = ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "ref.wav").write_bytes(_wav16(part))
    if not text.strip():
        try:
            from .voice import stt
            buf = (d / "ref.wav").read_bytes()
            text = stt.transcribe(buf, None, "media").get("text", "")
        except Exception:
            text = ""
    (d / "ref.txt").write_text(text.strip(), encoding="utf-8")
    meta = {"source": source, "created": time.strftime("%Y-%m-%d %H:%M"), "seconds": round(len(part) / 24000, 1),
            "consent": True}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "id": f"clone:{name}", "name": name, "text": text.strip(), **meta}


def delete_voice(name: str) -> dict:
    d = ROOT / safe_name(name)
    if not d.is_dir():
        return {"ok": False, "error": "нет такого голоса"}
    from .tools.files import delete_to_recycle_bin
    msg = delete_to_recycle_bin(str(d))
    return {"ok": not d.exists(), "text": msg}


class Engine:
    """The worker process: started on demand, stopped after IDLE_SEC without speech."""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.last = 0.0
        self.info = {}
        threading.Thread(target=self._idle_loop, daemon=True).start()

    def _start(self):
        flags = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0
        log = open(DATA_DIR / "logs" / "voiceclone.log", "ab")
        import os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        self.proc = subprocess.Popen([str(VENV_PY), "-u", str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=log, cwd=str(DATA_DIR.parent), creationflags=flags, env=env)

    def _ask(self, job: dict, timeout: float = 300) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            self._start()
        self.proc.stdin.write((json.dumps(job, ensure_ascii=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        box = {}
        t = threading.Thread(target=lambda: box.setdefault("line", self.proc.stdout.readline()), daemon=True)
        t.start()
        t.join(timeout)
        if "line" not in box or not box["line"]:
            self.stop()
            return {"ok": False, "error": "движок клонирования не ответил"}
        return json.loads(box["line"].decode("utf-8"))

    def synth(self, text: str, name: str, lang: str = "ru", speed: float = 1.0) -> tuple[bytes, int]:
        """-> (pcm16 bytes, 24000). Raises on any failure (the caller falls back to Piper)."""
        d = ROOT / safe_name(name)
        if not installed():
            raise RuntimeError("движок своих голосов не установлен")
        if not (d / "ref.wav").exists():
            raise FileNotFoundError(f"нет голоса {name}")
        try:
            from .llm import gaming
            device = "cpu" if gaming() else "auto"
        except Exception:
            device = "auto"
        with self.lock:
            fd, out = tempfile.mkstemp(suffix=".wav")
            import os
            os.close(fd)
            try:
                r = self._ask({"op": "synth", "text": text, "ref": str(d / "ref.wav"), "lang": lang, "speed": speed,
                               "ref_text": (d / "ref.txt").read_text(encoding="utf-8") if (d / "ref.txt").exists() else "",
                               "out": out, "device": device, "steps": 16})
                self.last = time.time()
                if not r.get("ok"):
                    raise RuntimeError(r.get("error") or "ошибка синтеза")
                self.info = r
                import wave
                with wave.open(out, "rb") as w:
                    return w.readframes(w.getnframes()), w.getframerate()
            finally:
                Path(out).unlink(missing_ok=True)

    def stop(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.stdin.write(b'{"op": "quit"}\n')
                p.stdin.flush()
                p.wait(5)
            except Exception:
                quiet()
            if p.poll() is None:
                p.kill()

    def _idle_loop(self):
        while True:
            time.sleep(20)
            if self.proc is not None and time.time() - self.last > IDLE_SEC and not self.lock.locked():
                self.stop()


engine = Engine()
