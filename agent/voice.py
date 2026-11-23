"""Stage 5: voice. STT = faster-whisper (GPU, child process, unloaded when idle). TTS = Piper (CPU).

VRAM rule still holds: whisper-turbo ~1.5 GB sits next to the small LLM only while you talk, then it is freed.

Hearing: audio is level-normalized before Whisper (quiet headset mics), beam search 5, softer VAD so quiet words at
the edges are not cut, a short hint with names it must know («Ренар», apps), language picked among ru/uk/pl/en only
when Whisper is sure, and typical Whisper hallucinations on noise («Субтитры сделал…») are dropped.
Speaking: text goes through speech_text (numbers/units/Latin -> spoken Russian, no emoji/markup) and is synthesized
phrase by phrase, so playback can start after the first phrase.
"""
import io
import json
import os
import re
import sys
import threading
import time
import wave
from pathlib import Path

from .config import DATA_DIR, SETTINGS
from .speech_text import for_speech, phrases, speech_segments
from .logs import quiet

CFG = {"stt_model": "large-v3-turbo", "stt_device": "cuda", "stt_compute": "int8_float16", "stt_idle_unload_sec": 300,
       "language": "ru", "stt_languages": ["ru", "uk", "pl", "en"], "stt_beam": 5,
       "stt_hotwords": "Ренар, Renard, Discord, Chrome, YouTube, Telegram, Steam, Spotify",
       "tts_voice": "ru_RU-ruslan-medium", "tts_enabled": True, "tts_rate": 1.0,
       "tts_voices": {"pl": "pl_PL-darkman-medium", "en": "en_US-ryan-medium", "uk": "uk_UA-ukrainian_tts-medium"},
       "tts_speakers": {"uk_UA-ukrainian_tts-medium": 1},
       "debug_keep": 20, **SETTINGS.get("voice", {})}
MODELS_DIR = DATA_DIR / "models"
VOICES_DIR = DATA_DIR / "voices"
DEBUG_DIR = DATA_DIR / "voice_debug"


def apply_prefs():
    """Choices made in the UI (voice, speed, …) live in prefs.json and must survive a restart."""
    try:
        from .prefs import get as pget
        v = pget("voice", {}) or {}
        for k in ("tts_voice", "tts_piper", "tts_rate", "stt_auto_lang", "debug_keep"):
            if v.get(k) is not None:
                CFG[k] = v[k]
    except Exception as e:
        print("voice prefs:", e)


apply_prefs()


def _add_cuda_dlls():
    """pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 ship DLLs that ctranslate2 needs on Windows."""
    if os.name != "nt":
        return
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
        d = base / sub / "bin"
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def available() -> bool:
    try:
        import faster_whisper
        import piper
        return True
    except Exception:
        return False


HALLU = re.compile(r"субтитр|продолжение следует|спасибо за (просмотр|внимание)|подпис\w* на (канал|мой)|dimatorzok|"
                   r"редактор\w* субтитров|корректор|amara\.org|ставьте лайк|добро пожаловать на канал|thanks for watching|"
                   r"дякую за перегляд|napisy (stworzone|wykonane)|www\.\w+", re.I)


FILLER = re.compile(r"(?i)\W*((m+|mm-hmm|mhm|hmm+|uh+|um+|ah+|oh+|м+|мм+|хм+|э+|а+|ну|так)[\W]*)+")


def _prep(raw: bytes):
    """Decode anything (wav/webm/ogg) to 16 kHz float32 and bring a quiet recording up to a normal level."""
    import numpy as np
    from faster_whisper.audio import decode_audio
    a = decode_audio(io.BytesIO(raw), sampling_rate=16000)
    info = {"dur": round(len(a) / 16000, 2)}
    if a.size < 1600:
        return a, info
    a = a - float(a.mean())
    peak = float(np.percentile(np.abs(a), 99.9))
    info["peak"] = round(peak, 4)
    if peak < 0.002:
        info["silent"] = True
        return a, info
    gain = min(12.0, 0.5 / peak)
    if gain > 1.15:
        a = np.clip(a * gain, -1.0, 1.0).astype("float32")
        info["gain"] = round(gain, 1)
    return a, info


def _stt_worker(conn, cfg: dict, models_dir: str):
    """Runs in a child process: owns CUDA/whisper. Killing the process frees ALL its RAM and VRAM."""
    _add_cuda_dlls()
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(cfg["stt_model"], device=cfg["stt_device"], compute_type=cfg["stt_compute"],
                             download_root=models_dir)
        device = cfg["stt_device"]
    except Exception as e:
        print("STT: GPU failed, using CPU:", e)
        model = WhisperModel(cfg["stt_model"], device="cpu", compute_type="int8", cpu_threads=8, download_root=models_dir)
        device = "cpu"
    conn.send({"ready": True, "device": device})
    while True:
        job = conn.recv()
        if job is None:
            break
        audio, opts = (job, {}) if isinstance(job, (bytes, bytearray)) else job
        try:
            a, info = _prep(bytes(audio))
            if info.get("silent") or a.size < 4800:
                conn.send({"text": "", "error": "тишина — микрофон выключен или слишком тихо" if info.get("silent") else "слишком коротко",
                           "device": device, **info})
                continue
            lang = opts.get("language") or cfg["language"]
            langs = cfg.get("stt_languages") or [lang]
            if not opts.get("language") and cfg.get("stt_auto_lang", True) and len(langs) > 1 and info["dur"] >= 1.0:
                try:
                    _, _, probs = model.detect_language(a)
                    allowed = {l: p for l, p in probs if l in langs}
                    tot = sum(allowed.values()) or 1.0
                    best = max(allowed, key=allowed.get)
                    info["lang_p"] = round(allowed[best] / tot, 2)
                    need = 0.75 if info["dur"] >= 4 else 0.98 if best == "uk" else 0.93
                    if best != lang and allowed[best] / tot >= need:
                        lang = best
                except Exception as e:
                    info["lang_err"] = str(e)
            def run(lang):
                segs, _ = model.transcribe(
                    a, language=lang, beam_size=cfg.get("stt_beam", 5), vad_filter=True, without_timestamps=not opts.get("timestamps"),
                    vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 700, "speech_pad_ms": 400},
                    condition_on_previous_text=False, hotwords=cfg.get("stt_hotwords") or None,
                    temperature=[0.0, 0.2, 0.4], no_speech_threshold=0.6, log_prob_threshold=-1.0)
                keep, dropped, stamped = [], [], []
                for s in segs:
                    t = s.text.strip()
                    if not t or HALLU.search(t) or (s.no_speech_prob > 0.7 and s.avg_logprob < -0.8):
                        dropped.append(t)
                        continue
                    keep.append(t)
                    stamped.append([round(s.start, 2), t, round(s.end, 2)])
                return " ".join(keep).strip(), dropped, stamped
            text, dropped, stamped = run(lang)
            base = cfg["language"]
            if lang == "uk" and base == "ru" and text and not re.search(r"[іїєґІЇЄҐ]", text):
                text, dropped, stamped = run(base)
                info["lang_fix"] = "uk->ru"
                lang = base
            if FILLER.fullmatch(text) and info["dur"] < 4 and not opts.get("timestamps"):
                dropped.append(text)
                text = ""
            conn.send({"text": text, "audio_s": info["dur"], "device": device, "lang": lang,
                       "dropped": dropped, **({"segments": stamped} if opts.get("timestamps") else {}), **info})
        except Exception as e:
            conn.send({"text": "", "error": f"{type(e).__name__}: {e}"})


def _debug_save(audio: bytes, r: dict):
    """Keep the last few recordings + what was heard (data/voice_debug, local only) to tune hearing on real speech."""
    keep = int(CFG.get("debug_keep", 20) or 0)
    if keep <= 0:
        return
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ext = "wav" if audio[:4] == b"RIFF" else "webm" if audio[:4] == b"\x1aE\xdf\xa3" else "ogg" if audio[:4] == b"OggS" else "bin"
        stem = time.strftime("%Y%m%d_%H%M%S")
        (DEBUG_DIR / f"{stem}.{ext}").write_bytes(audio)
        (DEBUG_DIR / f"{stem}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        files = sorted(DEBUG_DIR.glob("*.json"))
        for old in files[:-keep]:
            for p in DEBUG_DIR.glob(old.stem + ".*"):
                p.unlink(missing_ok=True)
    except Exception as e:
        print("voice debug save:", e)


RU_FIX = {"музику": "музыку", "музика": "музыка", "музики": "музыки", "музикой": "музыкой", "ютюб": "ютуб", "ютюбе": "ютубе"}
RU_FIX_RE = re.compile(r"(?<!\w)(" + "|".join(RU_FIX) + r")(?!\w)", re.I)


def _ru_fix(m):
    w = m.group(0)
    f = RU_FIX[w.lower()]
    return f.capitalize() if w[0].isupper() else f


class STT:
    """Speech-to-text in a separate process: started on demand (mic pressed), terminated after idle."""

    def __init__(self):
        self.proc = None
        self.conn = None
        self.device = None
        self.last_used = 0.0
        self.lock = threading.Lock()

    @property
    def model(self):
        return self.proc if (self.proc and self.proc.is_alive()) else None

    def _start(self):
        import multiprocessing as mp
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self.proc = ctx.Process(target=_stt_worker, args=(child, dict(CFG), str(MODELS_DIR)), daemon=True)
        self.proc.start()
        child.close()
        self.conn = parent
        if not self.conn.poll(600):
            self._kill()
            raise RuntimeError("распознавание речи не запустилось за 10 минут")
        msg = self.conn.recv()
        self.device = msg.get("device")

    def _kill(self):
        try:
            if self.proc is not None and self.proc.is_alive():
                self.proc.kill()
        except Exception:
            quiet()
        self.proc = self.conn = None

    def _ask(self, audio: bytes, opts: dict) -> dict:
        """one job; a worker that died (CUDA crash, killed) is started again once — a dead worker made the voice bake
        wait forever on the first phrase"""
        for attempt in (1, 2):
            if self.model is None:
                self._start()
            try:
                self.conn.send((bytes(audio), opts))
                while not self.conn.poll(2):
                    if not self.proc.is_alive():
                        raise EOFError(f"процесс распознавания завершился (код {self.proc.exitcode})")
                return self.conn.recv()
            except (EOFError, OSError, BrokenPipeError) as e:
                print("STT worker died:", e)
                self._kill()
                if attempt == 2:
                    return {"text": "", "error": f"распознавание упало: {e}"}
        return {"text": ""}

    def warmup(self):
        with self.lock:
            if self.model is None:
                self._start()
            self.last_used = time.time()

    def transcribe(self, audio: bytes, language: str | None = None, source: str = "", timestamps: bool = False) -> dict:
        with self.lock:
            t0 = time.time()
            if self.model is None:
                self._start()
            load_s = time.time() - t0
            opts = {"language": language} if language else {}
            if timestamps:
                opts["timestamps"] = True
            r = self._ask(audio, opts)
            text = (r.get("text") or "").replace("«", "").replace("»", "").replace('"', "").strip()
            if r.get("lang") == "ru":
                text = RU_FIX_RE.sub(lambda m: _ru_fix(m), text)
            self.last_used = time.time()
            r = {**r, "text": text, "ms": int((time.time() - t0) * 1000), "load_ms": int(load_s * 1000), "source": source}
        if source not in ("media", "eval"):
            _debug_save(audio, r)
        return r

    def stop(self):
        with self.lock:
            if self.proc is not None:
                try:
                    self.conn.send(None)
                    self.proc.join(3)
                except Exception:
                    quiet()
                if self.proc.is_alive():
                    self.proc.terminate()
                self.proc, self.conn = None, None

    def unload_if_idle(self):
        if self.model is not None and time.time() - self.last_used > CFG["stt_idle_unload_sec"]:
            self.stop()
            return True
        return False


def _wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
    return buf.getvalue()


class TTS:
    """Piper voices on CPU: one per language (ru main + pl/en/uk when such an answer comes), loaded on first use."""
    GAP_S = 0.16
    SENT_PAUSE = {".": 0.3, "?": 0.35, "!": 0.3, "…": 0.4}

    def __init__(self):
        self.voices: dict = {}
        self.lock = threading.Lock()

    @property
    def voice(self):
        return self.voices or None

    @voice.setter
    def voice(self, v):
        if v is None:
            self.voices = {}
            self.__dict__.pop("_cache", None)

    def _voice_for(self, lang: str):
        from piper import PiperVoice
        main = CFG["tts_voice"] if not str(CFG["tts_voice"]).startswith("clone:") else CFG.get("tts_piper", "ru_RU-ruslan-medium")
        name = main if lang == "ru" else (CFG.get("tts_voices") or {}).get(lang)
        if not name or not (VOICES_DIR / f"{name}.onnx").exists():
            if lang != "ru":
                return self._voice_for("ru")
            raise FileNotFoundError(f"Голос {name} не найден: python -m piper.download_voices --data-dir data/voices {name}")
        if name not in self.voices:
            self.voices[name] = PiperVoice.load(str(VOICES_DIR / f"{name}.onnx"))
        return self.voices[name], name

    def _cfg(self, name: str, scale: float = 1.0):
        from piper import SynthesisConfig
        rate = float(CFG.get("tts_rate", 1.0) or 1.0)
        own = self._own_tuning(name)
        return SynthesisConfig(speaker_id=(CFG.get("tts_speakers") or {}).get(name),
                               length_scale=scale * own.get("length_scale", 1.0) / max(0.6, min(1.6, rate)),
                               noise_scale=float(own.get("noise_scale", CFG.get("tts_noise", 0.5))),
                               noise_w_scale=float(own.get("noise_w", CFG.get("tts_noise_w", 0.5))))

    def _own_tuning(self, name: str) -> dict:
        """«renard» block of <voice>.onnx.json: {"length_scale": 2.0, "noise_scale": .45, "noise_w": .55}"""
        cache = self.__dict__.setdefault("_tune", {})
        if name not in cache:
            try:
                p = Path(__file__).resolve().parent.parent / "data" / "voices" / f"{name}.onnx.json"
                cache[name] = (json.loads(p.read_text(encoding="utf-8")).get("renard") or {}) if p.exists() else {}
            except Exception:
                cache[name] = {}
        return cache[name]

    @staticmethod
    def clean(text: str, limit: int = 700) -> str:
        return for_speech(text, limit=limit)[0]

    def prepare(self, text: str, limit: int = 700, lang: str | None = None) -> tuple[list[tuple[str, str]], str]:
        """-> ([(phrase, lang), …], main lang). English runs inside a Russian answer get the English voice."""
        if lang:
            spoken, lang = for_speech(text, lang, limit)
            return [(p, lang) for p in phrases(spoken)], lang
        try:
            from .prefs import get as pget
            eng = pget("voice.english_voice", True) is not False
        except Exception:
            eng = True
        segs, main = speech_segments(text, limit, english=eng and bool((CFG.get("tts_voices") or {}).get("en")))
        return [(p, l) for s, l in segs for p in phrases(s)], main

    CACHE_MAX = 64

    def phrase_pcm(self, phrase: str, lang: str = "ru", sr_out: int = 22050) -> tuple[bytes, int]:
        key = (phrase, lang, sr_out, CFG.get("tts_voice"), CFG.get("tts_rate"), str(CFG.get("tts_voices")))
        cache = self.__dict__.setdefault("_cache", {})
        if len(phrase) <= 40 and key in cache:
            cache[key] = cache.pop(key)
            return cache[key]
        out = self._phrase_pcm(phrase, lang, sr_out)
        if len(phrase) <= 40 and out[0]:
            cache[key] = out
            while len(cache) > self.CACHE_MAX:
                cache.pop(next(iter(cache)))
        return out

    def warm_cache(self, phrases_: list[str]):
        for p in phrases_:
            try:
                self.phrase_pcm(p)
            except Exception:
                return

    def _phrase_pcm(self, phrase: str, lang: str = "ru", sr_out: int = 22050) -> tuple[bytes, int]:
        pcm, sr = b"", sr_out
        sel = str(CFG.get("tts_voice") or "")
        if sel.startswith("clone:"):
            try:
                from .voiceclone import engine
                own, meta = 1.0, {}
                try:
                    meta = json.loads((DATA_DIR / "voices" / "clone" / sel[6:] / "meta.json").read_text(encoding="utf-8"))
                    own = float(meta.get("speed", 1.0))
                except Exception:
                    quiet()
                if lang == "ru":
                    from .ru_stress import restore_yo
                    phrase = restore_yo(phrase)
                pcm, sr = engine.synth(phrase, sel[6:], lang=lang, speed=float(CFG.get("tts_rate", 1.0) or 1.0) * own)
                if meta.get("fx"):
                    from .voicefx import robot_pcm
                    pcm = robot_pcm(pcm, sr, meta["fx"])
            except Exception as e:
                pcm = b""
                if time.time() - getattr(self, "_clone_err_t", 0) > 60:
                    self._clone_err_t = time.time()
                    print("voice clone -> piper:", e)
        if not pcm:
            with self.lock:
                v, name = self._voice_for(lang)
                pcm, sr = b"", v.config.sample_rate
                if lang == "ru" and v.config.espeak_voice.startswith("ru"):
                    from .ru_stress import for_piper
                    phrase = for_piper(phrase)
                own = self._own_tuning(name)
                slow = max(0.6, min(1.6, float(CFG.get("tts_rate", 1.0) or 1.0)))
                if own.get("pace"):
                    from .voicefx import parts, ramp
                    pace = own["pace"]
                    sents = [x for x in re.split(r"(?<=[.!?…])\s+", phrase.strip()) if x]
                    for si, sent in enumerate(sents):
                        ps = parts(sent)
                        for pi, part in enumerate(ps):
                            cfg = self._cfg(name, ramp(pi, len(ps), float(pace.get("ramp", 0.12))))
                            for ch in v.synthesize(part, syn_config=cfg):
                                pcm += ch.audio_int16_bytes
                                sr = ch.sample_rate
                            if pi < len(ps) - 1:
                                pcm += b"\x00\x00" * int(sr * float(pace.get("comma_pause", 0.12)) / slow)
                        if si < len(sents) - 1:
                            pcm += b"\x00\x00" * int(sr * self.SENT_PAUSE.get(sent.rstrip()[-1:], 0.3) / slow)
                else:
                    chunks = list(v.synthesize(phrase, syn_config=self._cfg(name)))
                    for i, ch in enumerate(chunks):
                        pcm += ch.audio_int16_bytes
                        sr = ch.sample_rate
                        if i < len(chunks) - 1:
                            end = "".join(ch.phonemes[-2:])
                            pause = self.SENT_PAUSE.get(next((c for c in reversed(end) if c in "?!.…"), "."), 0.3)
                            pcm += b"\x00\x00" * int(sr * pause / slow)
                if own.get("fx"):
                    from .voicefx import robot_pcm
                    pcm = robot_pcm(pcm, sr, own["fx"])
        if sr != sr_out and pcm:
            import numpy as np
            a = np.frombuffer(pcm, np.int16).astype(np.float32)
            x = np.linspace(0, len(a) - 1, int(len(a) * sr_out / sr))
            pcm, sr = np.interp(x, np.arange(len(a)), a).astype(np.int16).tobytes(), sr_out
        return pcm, sr

    def synth_phrase(self, phrase: str, lang: str = "ru") -> bytes:
        pcm, sr = self.phrase_pcm(phrase, lang)
        return _wav(pcm, sr) if pcm else b""

    def synth(self, text: str, lang: str | None = None, limit: int = 700) -> bytes:
        """Whole answer -> one wav (Telegram, scheduler, short UI lines)."""
        parts, detected = self.prepare(text, limit, lang)
        out, sr = b"", 22050
        for p, l in parts:
            pcm, sr = self.phrase_pcm(p, l)
            out += pcm + b"\x00\x00" * int(sr * self.GAP_S)
        return _wav(out, sr) if out else b""


stt = STT()
tts = TTS()
