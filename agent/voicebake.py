"""«Запечь голос»: a long recording of his voice → a normal Piper voice (fast, stable, like the 4 built-in ones).

  1. prepare  — the audio is cut into phrases (Whisper with timestamps), each phrase gets its text; junk is dropped.
  2. augment  — the AI adds what the recording lacks: the clone (OmniVoice) speaks extra sentences — the phrases Renard
                really says (numbers, dates, «готово», «открываю…») and phonetically rich ones; every generated phrase is
                checked by Whisper and thrown away if it came out crooked.
  3. train    — Piper (VITS) is fine-tuned from the Russian voice «ruslan» on the GPU (data/voiceclone/venv);
                when a game starts it pauses and continues later from the last checkpoint.
  4. export   — ONNX into data/voices: from now on the voice is chosen like any other, no clone running.
State: data/voicebake/<name>/state.json, progress in the UI («Голос» → «Свои голоса»)."""
import asyncio
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path

from .config import DATA_DIR
from .logs import quiet

ROOT = DATA_DIR / "voicebake"
BASE = ROOT / "base" / "ruslan"
BASES = {"ruslan": "мужской, большой корпус", "irina": "женский"}


def _base(name: str) -> Path:
    b = ROOT / "base" / (state(name).get("base") or "ruslan")
    return b if (b / "base_weights.pt").exists() else BASE
VENV_PY = DATA_DIR / "voiceclone" / "venv" / "Scripts" / "python.exe"
TRAIN = Path(__file__).with_name("voicebake_train.py")
SR = 22050
TARGET_STEPS = 2500
JOB: dict | None = None

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
                     "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))

SENTENCES = """Готово. Открываю браузер. Сейчас посмотрю. Не получилось, попробую ещё раз. Записал в дела. Напомню через десять минут.
Сегодня двенадцатое ноября, среда. Сейчас двадцать один час сорок пять минут. Температура плюс три градуса, без осадков.
Громкость шестьдесят процентов. Включаю музыку на YouTube. Следующий трек. Ставлю на паузу. Выключу компьютер через час.
Загрузка процессора двенадцать процентов, видеокарта свободна. На диске C осталось сорок два гигабайта.
Курс доллара — четыре злотых и две десятых. У тебя три задачи на сегодня и одна встреча в пятнадцать тридцать.
Привет! Чем помочь? Слушаю тебя. Хорошо, сделаю. Да, конечно. Нет, такого файла я не нашёл. Скажи «да», и я продолжу.
Съешь же ещё этих мягких французских булок, да выпей чаю. Широкая электрификация южных губерний даст мощный толчок подъёму сельского хозяйства.
В чащах юга жил бы цитрус? Да, но фальшивый экземпляр! Шла Саша по шоссе и сосала сушку. Щуку щиплет щётка в щели.
Жужжит жужелица, жужжит, да не кружится. Цапля чахла, цапля сохла, цапля чуть не сдохла. Четыре чёрненьких чумазеньких чертёнка.
Ёжик в тумане искал лошадку. Юла кружилась быстро-быстро. Эхо отвечало издалека. Мягкий свет падал на тёплый пол.
Вечером мы пойдём гулять в парк, если не будет дождя. Утром я проверил почту и ответил на два письма.
Какая сегодня погода в Варшаве? Открой папку загрузки и найди последний скачанный файл.
Пожалуйста, подожди немного: я ищу информацию в интернете. Нашёл пять результатов, самый подходящий — первый.
Один, два, три, четыре, пять, шесть, семь, восемь, девять, десять, сто, тысяча, миллион.
Понедельник, вторник, среда, четверг, пятница, суббота, воскресенье. Январь, февраль, март, апрель, май, июнь.
Июль, август, сентябрь, октябрь, ноябрь, декабрь. Весна, лето, осень, зима.
Это очень интересный вопрос, давай разберёмся по шагам. Во-первых, проверим настройки. Во-вторых, перезапустим программу.
Ошибка исправлена, всё работает. Обновление установлено. Файл сохранён в папке документы.
Кажется, ты давно сидишь за компьютером — может, сделаешь перерыв? Отличная работа, так держать!
Включаю режим «не беспокоить». Уведомления выключены на час. Хочешь, я соберу из этого команду?
Счастье — это когда тебя понимают. Чтобы что-то изменить, нужно начать с себя.
Объявление: съезд гостей в шесть часов. Подъезд, объём, вьюга, листья, семья, ружьё, пьеса, вьюн.
Хоккей, йогурт, район, майонез, лейка, чайник, стройка, война. Щавель, щенок, борщ, плащ, ящик, овощи.
""".replace("\n", " ")


def slug(name: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:24] or time.strftime("my%m%d")


def _dir(name: str) -> Path:
    return ROOT / slug(name)


def state(name: str) -> dict:
    try:
        return json.loads((_dir(name) / "state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _set(d: Path, **kw):
    try:
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    except Exception:
        st = {}
    st.update(kw, updated=time.time())
    tmp = d / "state.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(st, ensure_ascii=False, indent=1))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, d / "state.json")
    if JOB is not None and JOB.get("dir") == str(d):
        JOB["state"] = st
    return st


def all_jobs() -> list[dict]:
    out = []
    if ROOT.is_dir():
        for d in sorted(ROOT.iterdir()):
            if d.is_dir() and (d / "state.json").exists():
                out.append(json.loads((d / "state.json").read_text(encoding="utf-8")))
    return out


def ready() -> dict:
    return {"venv": VENV_PY.exists(), "base": (BASE / "base_weights.pt").exists() and (BASE / "config.json").exists(),
            "ffmpeg": bool(shutil.which("ffmpeg"))}


def _decode(path: Path) -> "np.ndarray":
    import numpy as np
    r = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "s16le", "-"], capture_output=True, timeout=1800, creationflags=0x08000000)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("не удалось прочитать " + path.name + ": " + r.stderr.decode("utf-8", "replace")[:200])
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768


def _wav(a, sr: int = SR) -> bytes:
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def _norm(a):
    """Same loudness for every phrase (RMS of the speech ≈ −20 dBFS, peaks kept under 0.95): peak normalization made
    a phrase with one loud click much quieter than its neighbours."""
    import numpy as np
    a = a - float(np.mean(a))
    hop = SR // 50
    e = np.array([float(np.sqrt(np.mean(a[i:i + hop] ** 2))) for i in range(0, max(1, len(a) - hop), hop)] or [0.0])
    speech = float(np.sqrt(np.mean(np.square(e[e >= np.median(e)])))) or 1e-4
    g = min(0.1 / speech, 0.95 / (float(np.max(np.abs(a))) or 1.0))
    return (a * g).astype(np.float32)


def clip_quality(a) -> dict:
    """edge: speech energy at the very first / last 20-ms frame vs the loud half of the phrase (a word cut in half).
    (Noise is NOT judged from quiet frames: in fast continuous speech the quietest frames are speech too — that
    measure called clean phrases noisy. Music / noise is measured by the separation: bg_db.)"""
    import numpy as np
    hop = SR // 50
    e = np.array([float(np.sqrt(np.mean(a[i:i + hop] ** 2) + 1e-12)) for i in range(0, max(1, len(a) - hop), hop)])
    if len(e) < 10:
        return {"edge": 1.0}
    hi = float(np.median(e[e >= np.median(e)]))
    return {"edge": round(max(float(e[0]), float(e[-1])) / hi, 2)}


def bg_db(orig, voice) -> float:
    """voice vs what the separation removed (music, effects, noise), dB: Raya's show phrases 20–44 (median 34),
    clean speech 40+; under ~20 the music is as audible as the voice."""
    import numpy as np
    n = min(len(orig), len(voice))
    rest = orig[:n] - voice[:n]
    return round(10 * float(np.log10(float(np.sum(voice[:n] ** 2)) / (float(np.sum(rest ** 2)) + 1e-9) + 1e-12)), 1)


MIN_BG_DB, MAX_EDGE, RATE = 20.0, 0.35, (7.0, 19.0)


def train_text(t: str) -> str:
    """The text the voice is trained on must be what it will be given later: numbers and Latin as words (speech_text),
    ё and stress marked (ru_stress / ruaccent) — «3 часа» in training and «три часа» at runtime are different phonemes,
    and espeak's own stress (пОтом, стоИт) would not match how the phrase is really said in the recording."""
    from .ru_stress import for_piper
    from .speech_text import for_speech
    return for_piper(for_speech(t, "ru", 2000)[0], wait=True)


def quality_rows(d: Path, rows: list[str]) -> tuple[list[str], dict]:
    """Before training: drop phrases under music/noise, with a word cut at the edge, or whose text cannot be what is
    said (impossible letters per second); the rest get the runtime-normalized text. Rejects -> rejected.csv."""
    keep, rej, why = [], [], {"шум/музыка": 0, "обрез слова": 0, "текст не совпадает": 0}
    try:
        bg = json.loads((d / "bg_db.json").read_text(encoding="utf-8"))
    except Exception:
        bg = {}
    for r in rows:
        uid, text = r.split("|", 1)
        try:
            import numpy as np
            with wave.open(str(d / "wavs" / f"{uid}.wav"), "rb") as w:
                a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        except Exception:
            continue
        q = clip_quality(a)
        rate = sum(c.isalpha() for c in text) / max(0.1, len(a) / SR)
        bad = ("шум/музыка" if bg.get(uid, 99) < MIN_BG_DB else "обрез слова" if q["edge"] > MAX_EDGE
               else "текст не совпадает" if not (RATE[0] <= rate <= RATE[1]) else "")
        if bad and uid.startswith("s_") and bad != "текст не совпадает":
            bad = ""
        if bad:
            why[bad] += 1
            rej.append(f"{uid}|{bad}|фон {bg.get(uid, '?')} дБ|edge {q['edge']}|{rate:.1f}/s|{text}")
            continue
        t = train_text(text)
        if t:
            keep.append(f"{uid}|{t}")
    (d / "rejected.csv").write_text("\n".join(rej) + "\n", encoding="utf-8")
    return keep, {"kept": len(keep), "rejected": why}


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("|", " ")).strip()


def _sim(a: str, b: str) -> float:
    n = lambda s: re.sub(r"[^\wё ]+", "", s.lower().replace("ё", "е")).split()
    return difflib.SequenceMatcher(None, n(a), n(b)).ratio()


def cut_phrases(a, lo: float = 2.0, hi: float = 11.0) -> list[tuple[int, int]]:
    """Cut speech at pauses: 20-ms frames, a pause = quiet ≥ 0.18 s; phrases are glued to 2–11 s, a longer piece is cut
    at its quietest frame. Returns (start, end) sample ranges with a little air around the words."""
    import numpy as np
    hop = SR // 50
    e = np.array([float(np.sqrt(np.mean(a[i:i + hop] ** 2) + 1e-12)) for i in range(0, len(a) - hop, hop)])
    if not len(e):
        return []
    thr = max(0.004, float(np.percentile(e, 20)) * 2.5, float(np.percentile(e, 90)) * 0.08)
    loud = e > thr
    runs, start, quiet = [], None, 0
    for i, v in enumerate(loud):
        if v:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet >= 9:
                runs.append([start, i - quiet + 1]); start, quiet = None, 0
    if start is not None:
        runs.append([start, len(loud)])
    out, cur = [], None
    for s, t in runs:
        if cur and (t - cur[0]) * hop / SR <= hi and (s - cur[1]) * hop / SR < 1.2 and (cur[1] - cur[0]) * hop / SR < lo:
            cur[1] = t
        else:
            if cur:
                out.append(cur)
            cur = [s, t]
    if cur:
        out.append(cur)
    res = []
    for s, t in out:
        while (t - s) * hop / SR > hi:
            lo_i, hi_i = s + int(SR * 3 / hop), s + int(SR * hi / hop)
            k = lo_i + int(np.argmin(e[lo_i:hi_i]))
            res.append((s, k)); s = k
        if (t - s) * hop / SR >= 1.0:
            res.append((s, t))
    return [(max(0, s * hop - SR // 12), min(len(a), t * hop + SR // 8)) for s, t in res]


def prepare(d: Path, lang: str = "ru") -> dict:
    """Every uploaded file → phrases cut at pauses (2–11 s), each phrase gets its own Whisper text."""
    import numpy as np
    from .voice import stt
    wavs = d / "wavs"
    wavs.mkdir(exist_ok=True)
    rows, n, real, dropped = [], 0, 0.0, 0
    files = sorted((d / "src").iterdir())
    for fi, f in enumerate(files):
        a = _decode(f)
        cuts = cut_phrases(a)
        for ci, (s0, s1) in enumerate(cuts):
            if ci % 5 == 0:
                _set(d, stage="prepare", pct=int(100 * (fi + ci / max(1, len(cuts))) / len(files)),
                     note=f"режу на фразы и распознаю текст: {f.name}, фраза {ci + 1} из {len(cuts)}")
            if JOB and JOB.get("cancel"):
                raise RuntimeError("отменено")
            part = a[s0:s1]
            dur = len(part) / SR
            r = stt.transcribe(_wav(part), lang or None, "media")
            text = _clean(r.get("text", ""))
            if not text or r.get("lang", lang) not in (lang, None) or not (4 <= len(text) / dur <= 26) \
                    or float(np.sqrt(np.mean(part ** 2))) < 0.004:
                dropped += 1
                continue
            n += 1
            uid = f"r_{n:05d}"
            (wavs / f"{uid}.wav").write_bytes(_wav(_norm(part)))
            rows.append(f"{uid}|{text}")
            real += dur
    (d / "real.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"phrases": n, "real_seconds": round(real, 1), "dropped": dropped}


def _sentences(d: Path, need: int) -> list[str]:
    """Built-in phrases + what Renard answered recently (his real vocabulary), split into sentences of 3–22 words."""
    pool = re.split(r"(?<=[.!?…])\s+", SENTENCES)
    try:
        import sqlite3
        from .memory import DB_PATH
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        for (t,) in con.execute("SELECT content FROM messages WHERE role='assistant' AND length(content) < 600 "
                                "ORDER BY ts DESC LIMIT 500"):
            pool += re.split(r"(?<=[.!?…])\s+", re.sub(r"[*_`#>\[\]()|]|https?://\S+", "", t or ""))
        con.close()
    except Exception:
        quiet()
    seen, out = set(), []
    for s in pool:
        s = _clean(s)
        k = s.lower()
        if 3 <= len(s.split()) <= 22 and re.search(r"[а-яё]", k) and not re.search(r"[a-z]{4,}|\d{4,}", k) and k not in seen:
            seen.add(k); out.append(s)
    return out[:need]


def augment(d: Path, name: str, minutes_target: float = 25.0) -> dict:
    """The clone speaks extra sentences; Whisper checks every one, crooked ones are dropped."""
    import numpy as np
    from . import voiceclone
    from .voice import stt
    st = state(name)
    real = float(st.get("real_seconds") or 0)
    need_s = max(0.0, minutes_target * 60 - real)
    if need_s < 60:
        return {"synthetic": 0, "synthetic_seconds": 0}
    ref_name = f"bake_{slug(name)}"
    if not any(v["name"] == ref_name for v in voiceclone.voices()):
        rows = [r.split("|", 1) for r in (d / "real.csv").read_text(encoding="utf-8").splitlines() if "|" in r]
        best = sorted(rows, key=lambda r: -len(r[1]))[:6]
        a = np.concatenate([_decode(d / "wavs" / f"{u}.wav") for u, _ in best])
        voiceclone.add_voice(ref_name, _wav(a), "bake", "", 0, None, consent=True)
    sents = _sentences(d, 900)
    rows, got, n, fails = [], 0.0, 0, 0
    for i, s in enumerate(sents):
        if got >= need_s:
            break
        from .llm import gaming
        while gaming():
            _set(d, stage="augment", note="пауза: идёт игра — продолжу после неё")
            time.sleep(30)
        if JOB and JOB.get("cancel"):
            raise RuntimeError("отменено")
        _set(d, stage="augment", pct=int(100 * got / need_s),
             note=f"ИИ досинтезирует фразы твоим голосом: {n} готово, {fails} отброшено")
        try:
            pcm, sr = voiceclone.engine.synth(s, ref_name)
        except Exception:
            fails += 1
            continue
        a = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
        if sr != SR:
            a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * SR / sr)), np.arange(len(a)), a).astype(np.float32)
        heard = stt.transcribe(_wav(a), "ru", "media").get("text", "")
        need = 0.6 if re.search(r"\d", heard) else 0.8
        if _sim(heard, s) < need or len(a) / SR > 14:
            fails += 1
            continue
        n += 1
        uid = f"s_{n:05d}"
        (d / "wavs" / f"{uid}.wav").write_bytes(_wav(_norm(a)))
        rows.append(f"{uid}|{s}")
        got += len(a) / SR
    (d / "synthetic.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    voiceclone.engine.stop()
    return {"synthetic": n, "synthetic_seconds": round(got, 1), "rejected": fails}


def _ckpts(d: Path) -> list[Path]:
    """last.ckpt files, oldest first, without the broken ones: a power cut while one was being saved leaves a file
    of the full size filled with zeros (it is a zip archive inside, so that is cheap to see)."""
    import zipfile
    out = []
    for p in sorted((d / "train").rglob("last.ckpt"), key=lambda p: p.stat().st_mtime):
        try:
            with zipfile.ZipFile(p) as z:
                z.namelist()
            out.append(p)
        except Exception:
            try:
                p.rename(p.with_name(f"broken_{int(time.time())}.ckpt.bad"))
            except OSError:
                pass
    return out


def _train_cmd(d: Path, name: str, rows: int, resume: bool) -> list[str]:
    batch = 12
    per_epoch = max(1, int(rows * 0.95) // batch)
    target = int(state(name).get("steps") or TARGET_STEPS)
    epochs = max(20, -(-target // per_epoch))
    cmd = [str(VENV_PY), "-u", str(TRAIN), str(d / "progress.json"), "fit",
           "--data.voice_name", slug(name), "--data.csv_path", str(d / "metadata.csv"), "--data.audio_dir", str(d / "wavs"),
           "--data.cache_dir", str(d / "cache"), "--data.config_path", str(d / "config.json"), "--data.espeak_voice", "ru",
           "--data.batch_size", str(batch), "--data.validation_split", "0.05", "--data.num_test_examples", "0",
           "--data.num_workers", "0", "--model.sample_rate", str(SR), "--model.mos_metric", "none",
           "--model.learning_rate", str(state(name).get("lr") or "1e-4"), "--trainer.max_epochs", str(epochs), "--trainer.accelerator", "gpu",
           "--trainer.devices", "1", "--trainer.precision", "32", "--trainer.default_root_dir", str(d / "train"),
           "--trainer.log_every_n_steps", "10", "--trainer.check_val_every_n_epoch", "25"]
    last = _ckpts(d)
    for old in last[:-1]:
        old.unlink(missing_ok=True)
    if resume and last:
        cmd += ["--ckpt_path", str(last[-1])]
    else:
        cmd += ["--model.warmstart_ckpt", str(_base(name) / "base_weights.pt")]
    return cmd


def _train(d: Path, name: str):
    from .llm import gaming
    rows = len([r for r in (d / "metadata.csv").read_text(encoding="utf-8").splitlines() if r.strip()])
    resume = bool(_ckpts(d)) if (d / "train").exists() else False
    log = open(d / "train.log", "ab")
    while True:
        while gaming():
            _set(d, stage="train", note="пауза: идёт игра — продолжу обучение после неё")
            time.sleep(30)
        p = subprocess.Popen(_train_cmd(d, name, rows, resume), stdout=log, stderr=subprocess.STDOUT, cwd=str(d),
                             env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, creationflags=0x08000000)
        JOB["pid"] = p.pid
        paused = False
        while p.poll() is None:
            time.sleep(5)
            try:
                pr = json.loads((d / "progress.json").read_text(encoding="utf-8"))
                pct = int(100 * pr.get("step", 0) / max(1, pr.get("total", 1)))
                _set(d, stage="train", pct=pct, note=f"обучение: шаг {pr.get('step', 0)} из {pr.get('total', '?')}"
                     + (f", потери {pr['loss_gen_all']:.1f}" if "loss_gen_all" in pr else ""))
            except Exception:
                quiet()
            if JOB.get("cancel"):
                p.kill(); raise RuntimeError("отменено")
            if gaming():
                p.kill(); paused = True
                break
        if paused:
            resume = True
            continue
        if p.returncode != 0:
            tail = (d / "train.log").read_bytes()[-1500:].decode("utf-8", "replace")
            raise RuntimeError("обучение упало: " + tail[-600:])
        return


def _export(d: Path, name: str, out: Path | None = None) -> str:
    ckpts = _ckpts(d)
    if not ckpts:
        raise RuntimeError("нет чекпойнта")
    voice_id = f"ru_RU-{slug(name)}-medium"
    if out is not None:
        r = subprocess.run([str(VENV_PY), str(TRAIN), str(d / "progress.json"), "export", str(ckpts[-1]), str(out)],
                           capture_output=True, timeout=1800, creationflags=0x08000000)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("экспорт не удался: " + r.stderr.decode("utf-8", "replace")[-300:])
        shutil.copy2(d / "config.json", str(out) + ".json")
        return str(out)
    out = DATA_DIR / "voices" / f"{voice_id}.onnx"
    r = subprocess.run([str(VENV_PY), str(TRAIN), str(d / "progress.json"), "export", str(ckpts[-1]), str(out)],
                       capture_output=True, timeout=1800, creationflags=0x08000000)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("экспорт не удался: " + r.stdout.decode("utf-8", "replace")[-300:] + r.stderr.decode("utf-8", "replace")[-300:])
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    cfg.setdefault("dataset", slug(name))
    try:
        cfg["renard"] = json.loads((DATA_DIR / "voices" / f"{voice_id}.onnx.json").read_text(encoding="utf-8"))["renard"]
    except Exception:
        quiet()
    (DATA_DIR / "voices" / f"{voice_id}.onnx.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return voice_id


SEPARATE = Path(__file__).with_name("voicebake_separate.py")
_CAN_SEP: dict = {}


def can_separate() -> bool:
    """demucs in the voice venv (pip install demucs there): the voice is taken out of music / effects before training"""
    if "ok" not in _CAN_SEP:
        try:
            r = subprocess.run([str(VENV_PY), "-c", "import demucs"], capture_output=True, timeout=120, creationflags=0x08000000)
            _CAN_SEP["ok"] = VENV_PY.exists() and r.returncode == 0
        except Exception:
            _CAN_SEP["ok"] = False
    return _CAN_SEP["ok"]


def separate_clips(d: Path) -> dict:
    """The real phrases (wavs/r_*.wav) from a show / game have music and effects under the voice — the voice learned
    them too and came out broken. Demucs keeps only the voice: originals -> wavs_orig/, the clean ones replace them.
    Done once per voice (state «separated»); a failure leaves the originals in place."""
    if state_of(d).get("separated") or not can_separate():
        return {}
    clips = sorted((d / "wavs").glob("r_*.wav"))
    if not clips:
        return {}
    orig, tmp = d / "wavs_orig", d / "sep"
    orig.mkdir(exist_ok=True)
    tmp.mkdir(exist_ok=True)
    for c in clips:
        if not (orig / c.name).exists():
            shutil.copy2(c, orig / c.name)
    pairs = [[str(orig / c.name), str(tmp / c.name)] for c in clips]
    (d / "sep_pairs.json").write_text(json.dumps(pairs), encoding="utf-8")
    p = subprocess.Popen([str(VENV_PY), "-u", str(SEPARATE), str(d / "sep_pairs.json"), str(d / "progress.json")],
                         stdout=open(d / "separate.log", "ab"), stderr=subprocess.STDOUT, cwd=str(d),
                         env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, creationflags=0x08000000)
    while p.poll() is None:
        time.sleep(3)
        try:
            pr = json.loads((d / "progress.json").read_text(encoding="utf-8"))
            if pr.get("stage") == "separate":
                _set(d, stage="separate", pct=int(100 * pr["done"] / max(1, pr["total"])),
                     note=f"отделяю голос от музыки и шума: {pr['done']} из {pr['total']}")
        except Exception:
            quiet()
        if JOB and JOB.get("cancel"):
            p.kill()
            raise RuntimeError("отменено")
    if p.returncode != 0:
        tail = (d / "separate.log").read_bytes()[-600:].decode("utf-8", "replace")
        print("voicebake separate failed:", tail)
        return {"separate_error": tail[-300:]}
    bg = {}
    for c in clips:
        out = tmp / c.name
        if out.exists():
            v = _decode(out)
            bg[c.stem] = bg_db(_decode(orig / c.name), v)
            c.write_bytes(_wav(_norm(v)))
    (d / "bg_db.json").write_text(json.dumps(bg), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    vals = sorted(bg.values())
    return {"separated": True, "bg_db_median": vals[len(vals) // 2] if vals else None}


def state_of(d: Path) -> dict:
    try:
        return json.loads((d / "state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _metadata(d: Path, min_rows: int = 100) -> list[str]:
    rows = [r for f in ("real.csv", "synthetic.csv") if (d / f).exists()
            for r in (d / f).read_text(encoding="utf-8").splitlines() if "|" in r]
    if can_separate() and not state_of(d).get("separated"):
        _set(d, stage="separate", pct=0, note="отделяю голос от музыки и шума (demucs)")
        _set(d, **separate_clips(d))
    _set(d, stage="train", pct=0, note="отбираю чистые фразы: без музыки, без обрезанных слов")
    rows, q = quality_rows(d, rows)
    _set(d, quality=q)
    if len(rows) < min_rows:
        raise RuntimeError(f"после отбора осталось {len(rows)} чистых фраз — мало для обучения (нужно хотя бы {min_rows}). "
                           f"Отброшено: {q['rejected']} — запись с музыкой или шумом, нужна чище")
    (d / "metadata.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return rows


CHECK = ["Готово, файл сохранён в папке документы.", "Сегодня плюс три градуса, к вечеру возможен дождь.",
         "Нашла пять результатов, самый подходящий — первый.", "Хочешь, я напомню об этом через десять минут?",
         "Съешь же ещё этих мягких французских булок, да выпей чаю.", "Сканирование системы завершено, угроз не обнаружено.",
         "Открываю браузер и ищу свежие новости о погоде.", "Загрузка процессора двенадцать процентов, видеокарта свободна.",
         "Привет! Я на связи и готова помочь.", "Не получилось подключиться к сети, попробую ещё раз через минуту.",
         "Включаю музыку на ютубе, громкость шестьдесят процентов.", "Чтобы что-то изменить, нужно начать с себя."]


def verify(voice_id: str, tuning: dict | None = None, takes: int = 2) -> dict:
    """The finished voice says test phrases it never trained on; Whisper writes down what it hears. A voice Whisper
    cannot understand is broken whatever the losses said. -> {"score": 0..100, "worst": "…"}
    Each phrase is said `takes` times (VITS speaks a little differently each time) with 0.4 s of silence around it:
    on a bare 2-s clip Whisper's voice filter sometimes ate the first word or returned nothing at all — the same
    voice scored 83, 75 and 70."""
    from piper import PiperVoice, SynthesisConfig
    from .voice import stt
    import numpy as np
    v = PiperVoice.load(voice_id if voice_id.endswith(".onnx") else str(DATA_DIR / "voices" / f"{voice_id}.onnx"))
    tu = tuning or {}
    cfg = SynthesisConfig(length_scale=tu.get("length_scale"), noise_scale=tu.get("noise_scale"), noise_w_scale=tu.get("noise_w"))
    scores, worst = [], (1.0, "")
    pad = np.zeros(int(v.config.sample_rate * 0.4), np.float32)
    for t in CHECK:
        said = train_text(t)
        for _ in range(takes):
            a = np.concatenate([pad] + [ch.audio_float_array for ch in v.synthesize(said, syn_config=cfg)] + [pad])
            heard = stt.transcribe(_wav(a * 0.8, v.config.sample_rate), "ru", "media").get("text", "")
            s = _sim(train_text(heard), said)
            scores.append(s)
            if s < worst[0]:
                worst = (s, f"«{t}» → услышано «{heard}»")
    return {"score": round(100 * sum(scores) / len(scores)), "worst": worst[1] if worst[0] < 0.9 else ""}


def rebake(name: str, steps: int = 7000) -> str:
    """Train the voice again from the same phrases with the quality filter: the old training goes to train_old_<time>
    (and the old ONNX stays until the new one replaces it), the phoneme cache is rebuilt for the normalized texts."""
    d = _dir(name)
    if not (d / "real.csv").exists():
        raise RuntimeError("нет фраз этого голоса — запеки его заново")
    if (d / "train").exists():
        (d / "train").rename(d / f"train_old_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.rmtree(d / "cache", ignore_errors=True)
    _set(d, stage="train", steps=steps, error="", check={})
    global JOB
    JOB = {"dir": str(d), "name": name}
    try:
        _metadata(d)
        _train(d, name)
        _set(d, stage="export", pct=99, note="собираю готовый голос")
        vid = _export(d, name)
        _set(d, stage="check", pct=99, note="проверяю готовый голос")
        _set(d, check=verify(vid))
        _set(d, stage="done", pct=100, note="готово — голос обновлён", voice=vid)
        return vid
    except Exception as e:
        _set(d, stage="error", error=str(e)[:800], note="ошибка")
        raise
    finally:
        JOB = None


TUNE = [{"length_scale": ls, "noise_scale": ns, "noise_w": nw}
        for ls in (1.0, 1.15, 1.3) for ns in (0.33, 0.5, 0.667) for nw in (0.4, 0.6, 0.8)]


def tune(voice: str, keep: dict | None = None) -> tuple[dict, dict]:
    """The synthesis settings the voice is understood best with (pace, smoothness): 27 combinations, each heard by
    Whisper; a tie goes to the calmer / slower one. -> (tuning, check)"""
    best = (keep or {}, verify(voice, keep) if keep else {"score": -1})
    for t in TUNE:
        c = verify(voice, t)
        if c["score"] > best[1]["score"]:
            best = (t, c)
    return best


def bake_best(name: str, base: str = "irina", target: int = 90, stage: int = 2500, max_steps: int = 20000,
              resume: bool = False, lr: str = "1e-4", source: str = "") -> dict:
    """«Переобучить чище» for real quality: separation + filter, then training in stages of `stage` steps; after each
    stage the voice is exported as a candidate and Whisper scores it on 12 new phrases. The best candidate is kept;
    training stops at max_steps, or when the target is reached and two stages in a row did not improve it. At the end
    the synthesis settings are tuned for the best one and it replaces the voice in the list."""
    global JOB
    d = _dir(name)
    if source and not (d / "real.csv").exists():
        src = _dir(source)
        d.mkdir(parents=True, exist_ok=True)
        for f in ("real.csv", "synthetic.csv", "bg_db.json", "sep_pairs.json", "config.json"):
            if (src / f).exists():
                shutil.copy2(src / f, d / f)
        for sub in ("wavs", "wavs_orig"):
            if (src / sub).exists():
                shutil.copytree(src / sub, d / sub, dirs_exist_ok=True)
        st = state(source)
        _set(d, **{k: st[k] for k in ("consent", "phrases", "real_seconds", "dropped", "synthetic", "synthetic_seconds",
                                       "separated", "bg_db_median") if k in st},
             name=name, slug=slug(name), created=time.time(), stage="train", source=source)
    if not (d / "real.csv").exists():
        raise RuntimeError("нет фраз этого голоса — запеки его заново")
    if JOB is not None and JOB.get("dir") != str(d):
        raise RuntimeError("уже идёт другое запекание")
    st0 = state(name)
    resume = resume and (d / "train").exists() and bool(st0.get("checks")) and (d / "metadata.csv").exists()
    cand = d / "cand"
    cand.mkdir(exist_ok=True)
    if not resume:
        if (d / "train").exists():
            (d / "train").rename(d / f"train_old_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.rmtree(d / "cache", ignore_errors=True)
        _set(d, stage="train", base=base, steps=stage, error="", check={}, checks=[], target=target, lr=lr, stage_steps=stage)
    JOB = {"dir": str(d), "name": name}
    try:
        if resume:
            done = [c["steps"] for c in st0["checks"]]
            steps = max(done) + stage
            best = None
            for c in st0["checks"]:
                if (cand / f"step{c['steps']}.onnx").exists() and (best is None or c["score"] > best["score"]):
                    best = {"steps": c["steps"], "score": c["score"], "onnx": str(cand / f"step{c['steps']}.onnx")}
            flat = len([c for c in st0["checks"] if best and c["steps"] > best["steps"]])
        else:
            _metadata(d)
            best, flat, steps = None, 0, stage
        while True:
            _set(d, stage="train", steps=steps, note=f"обучение до {steps} шагов (цель — понятность {target}/100)")
            _train(d, name)
            _set(d, stage="check", note=f"{steps} шагов: Whisper проверяет голос")
            onnx = cand / f"step{steps}.onnx"
            _export(d, name, onnx)
            c = verify(str(onnx), {"length_scale": 1.1, "noise_scale": 0.5, "noise_w": 0.6})
            checks = state(name).get("checks", []) + [{"steps": steps, **c}]
            _set(d, checks=checks, note=f"{steps} шагов: понятность {c['score']}/100")
            if best is None or c["score"] > best["score"]:
                best, flat = {"steps": steps, "score": c["score"], "onnx": str(onnx)}, 0
            else:
                flat += 1
            top = sorted([c for c in checks if (cand / f"step{c['steps']}.onnx").exists()], key=lambda c: -c["score"])[:3]
            keep = {f"step{c['steps']}.onnx" for c in top}
            for f in cand.glob("step*.onnx*"):
                if f.name.removesuffix(".json") not in keep:
                    f.unlink(missing_ok=True)
            if steps >= max_steps or (best["score"] >= target and flat >= 2) or flat >= 4:
                break
            steps += stage
        _set(d, stage="check", note="сравниваю лучшие варианты ещё раз, внимательнее")
        final = []
        for f in sorted(cand.glob("step*.onnx")):
            c = verify(str(f), {"length_scale": 1.15, "noise_scale": 0.5, "noise_w": 0.6}, takes=4)
            final.append((c["score"], f))
        _set(d, finalists=[{"onnx": f.name, "score": sc} for sc, f in final])
        sc, f = max(final)
        best = {"steps": int(f.stem[4:]), "score": sc, "onnx": str(f)}
        _set(d, stage="check", note=f"подбираю темп и плавность для лучшего варианта ({best['steps']} шагов)")
        tuning, c = tune(best["onnx"])
        vid = f"ru_RU-{slug(name)}-medium"
        live = DATA_DIR / "voices" / f"{vid}.onnx"
        if live.exists():
            shutil.copy2(live, d / f"previous_{time.strftime('%Y%m%d_%H%M%S')}.onnx")
        shutil.copy2(best["onnx"], live)
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        cfg.update(dataset=slug(name), renard=tuning)
        (DATA_DIR / "voices" / f"{vid}.onnx.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        _set(d, stage="done", pct=100, voice=vid, check=c, best_steps=best["steps"],
             note=f"готово — понятность {c['score']}/100 (лучший вариант: {best['steps']} шагов)")
        return {"voice": vid, "check": c, "tuning": tuning, "steps": best["steps"]}
    except Exception as e:
        _set(d, stage="error", error=str(e)[:800], note="ошибка")
        raise
    finally:
        JOB = None


def _run(name: str, lang: str, minutes_target: float):
    d = _dir(name)
    try:
        st = state(name)
        if st.get("stage") in (None, "new", "prepare", "error") and not (d / "real.csv").exists():
            _set(d, stage="prepare", pct=0, note="режу запись на фразы и распознаю текст", error="")
            _set(d, **prepare(d, lang))
        st = state(name)
        if float(st.get("real_seconds") or 0) < 60:
            raise RuntimeError(f"в записи всего {st.get('real_seconds', 0)} с чистой речи — нужна хотя бы 1 минута "
                               f"(лучше 5–20 минут)")
        if not (d / "synthetic.csv").exists():
            _set(d, stage="augment", pct=0, note="ИИ досинтезирует недостающие звуки и фразы")
            _set(d, **augment(d, name, minutes_target))
        rows = _metadata(d)
        _set(d, stage="train", pct=0, note="обучаю голос на видеокарте", rows=len(rows))
        _train(d, name)
        _set(d, stage="export", pct=99, note="собираю готовый голос")
        vid = _export(d, name)
        _set(d, stage="check", pct=99, note="проверяю готовый голос: Whisper слушает тестовые фразы")
        _set(d, check=verify(vid))
        _set(d, stage="done", pct=100, note="готово — голос появился в списке", voice=vid)
    except Exception as e:
        _set(d, stage="error", error=str(e)[:800], note="ошибка")
    finally:
        global JOB
        JOB = None


def _import_dataset(d: Path, src: Path) -> dict:
    """A ready dataset (src/final/<id>.wav + src/metadata.csv «id|text», e.g. a character's phrases found in a show):
    phrases up to 12 s keep their text, longer ones are cut at pauses (2–11 s) and each part gets its own Whisper text."""
    from .llm import gaming
    from .voice import stt
    wavs = d / "wavs"
    wavs.mkdir(exist_ok=True)
    meta = [l.split("|", 1) for l in (src / "metadata.csv").read_text(encoding="utf-8").splitlines() if "|" in l]
    rows, n, real, dropped = [], 0, 0.0, 0
    for k, (uid, text) in enumerate(meta):
        if k % 10 == 0:
            _set(d, stage="prepare", pct=int(100 * k / len(meta)), note=f"готовлю её фразы: {k} из {len(meta)}")
        a = _decode(src / "final" / f"{uid}.wav")
        if len(a) / SR <= 12:
            parts = [(a, _clean(text))]
        else:
            parts = []
            for s0, s1 in cut_phrases(a):
                while gaming():
                    _set(d, note="пауза: идёт игра"); time.sleep(30)
                p = a[s0:s1]
                t = _clean(stt.transcribe(_wav(p), "ru", "media").get("text", ""))
                if t and 4 <= len(t) / (len(p) / SR) <= 26:
                    parts.append((p, t))
                else:
                    dropped += 1
        for p, t in parts:
            if not t:
                continue
            n += 1
            nid = f"r_{n:05d}"
            (wavs / f"{nid}.wav").write_bytes(_wav(_norm(p)))
            rows.append(f"{nid}|{t}")
            real += len(p) / SR
    (d / "real.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"phrases": n, "real_seconds": round(real, 1), "dropped": dropped}


def run_dataset(name: str, src: Path, steps: int = 7000, extra_min: float = 15.0):
    """The whole bake from a ready dataset, in this process (python -m agent.voicebake --dataset <char dir> <name>)."""
    global JOB
    d = _dir(name)
    d.mkdir(parents=True, exist_ok=True)
    _set(d, name=name, slug=slug(name), created=time.time(), consent=True, steps=steps, error="")
    JOB = {"dir": str(d), "name": name}
    try:
        if not (d / "real.csv").exists():
            _set(d, **_import_dataset(d, src))
        if not (d / "synthetic.csv").exists() and extra_min > 0:
            _set(d, stage="augment", pct=0, note="ИИ досинтезирует недостающие фразы её голосом")
            _set(d, **augment(d, name, float(state(name).get("real_seconds") or 0) / 60 + extra_min))
        rows = _metadata(d)
        _set(d, stage="train", pct=0, note="обучаю голос на видеокарте", rows=len(rows))
        _train(d, name)
        _set(d, stage="export", pct=99, note="собираю готовый голос")
        vid = _export(d, name)
        _set(d, stage="check", pct=99, note="проверяю готовый голос: Whisper слушает тестовые фразы")
        _set(d, check=verify(vid))
        _set(d, stage="done", pct=100, note="готово — голос появился в списке", voice=vid)
        return vid
    except Exception as e:
        _set(d, stage="error", error=str(e)[:800], note="ошибка")
        raise
    finally:
        JOB = None


def add_file(name: str, fn: str, raw: bytes) -> dict:
    """One uploaded recording (any audio / video) → data/voicebake/<slug>/src. Several files are fine."""
    d = _dir(name)
    (d / "src").mkdir(parents=True, exist_ok=True)
    p = d / "src" / (re.sub(r"[^\w.\-]+", "_", fn or "rec.webm")[-80:] or "rec.webm")
    p.write_bytes(raw)
    files = sorted((d / "src").iterdir())
    _set(d, name=name, slug=slug(name), stage=state(name).get("stage") or "new", files=[f.name for f in files])
    return {"ok": True, "files": [f.name for f in files], "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1)}


def start(name: str, files: list[tuple[str, bytes]] | None, consent: bool, lang: str = "ru", minutes_target: float = 25.0) -> dict:
    global JOB
    if JOB is not None:
        return {"ok": False, "error": "уже запекается другой голос — дождись окончания"}
    if not consent:
        return {"ok": False, "error": "Отметь, что это твой голос или у тебя есть согласие его владельца."}
    r = ready()
    if not all(r.values()):
        return {"ok": False, "error": "не готово: " + ", ".join(k for k, v in r.items() if not v)}
    d = _dir(name)
    (d / "src").mkdir(parents=True, exist_ok=True)
    for fn, raw in files or []:
        (d / "src" / re.sub(r"[^\w.\-]+", "_", fn)[-80:]).write_bytes(raw)
    if not any((d / "src").iterdir()):
        return {"ok": False, "error": "нет аудио"}
    _set(d, name=name, slug=slug(name), stage=state(name).get("stage") or "new", created=time.time(), consent=True)
    JOB = {"dir": str(d), "name": name}
    import threading
    threading.Thread(target=_run, args=(name, lang, minutes_target), daemon=True).start()
    return {"ok": True, "slug": slug(name)}


def resume(name: str) -> dict:
    global JOB
    if JOB is not None:
        return {"ok": False, "error": "уже идёт"}
    d = _dir(name)
    if not d.exists():
        return {"ok": False, "error": "нет такого"}
    JOB = {"dir": str(d), "name": name}
    import threading
    threading.Thread(target=_run, args=(name, "ru", 25.0), daemon=True).start()
    return {"ok": True}


def start_rebake(name: str, steps: int | None = None) -> dict:
    """«Переобучить чище» in the UI: rebake() in the background (one job at a time)."""
    if JOB is not None:
        return {"ok": False, "error": "уже идёт запекание — дождись окончания"}
    if not (_dir(name) / "real.csv").exists():
        return {"ok": False, "error": "нет фраз этого голоса"}
    import threading

    def go():
        try:
            if steps:
                rebake(name, int(steps))
            else:
                base = "irina" if (ROOT / "base" / "irina" / "base_weights.pt").exists() and state(name).get("base") != "ruslan" else "ruslan"
                bake_best(name, base)
        except Exception:
            quiet()
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


def cancel() -> dict:
    if JOB is None:
        return {"ok": False}
    JOB["cancel"] = True
    return {"ok": True}


async def astart(*a, **kw):
    return await asyncio.to_thread(start, *a, **kw)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["--check"]:
        print(verify(sys.argv[2], {"length_scale": float(sys.argv[3])} if len(sys.argv) > 3 else None))
    elif sys.argv[1:2] == ["--filter"]:
        dd = _dir(sys.argv[2])
        rr = [r for f in ("real.csv", "synthetic.csv") if (dd / f).exists()
              for r in (dd / f).read_text(encoding="utf-8").splitlines() if "|" in r]
        kept, qq = quality_rows(dd, rr)
        print(len(rr), "->", qq, "| rejected.csv in", dd)
    elif sys.argv[1:2] == ["--best"]:
        kv = dict(a.split("=", 1) for a in sys.argv[5:] if "=" in a)
        st_ = state(sys.argv[2])
        res = bake_best(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "irina", int(sys.argv[4]) if len(sys.argv) > 4 else 90,
                        resume="resume" in sys.argv[5:], lr=kv.get("lr", st_.get("lr") or "1e-4"),
                        stage=int(kv.get("stage", st_.get("stage_steps") or 2500)), source=kv.get("from", ""))
        print(res)
        try:
            from .jobwatch import telegram
            telegram(f"Renard: голос «{sys.argv[2]}» переобучен: понятность {res['check']['score']}/100 "
                     f"({res['steps']} шагов). Можно слушать.")
        except Exception:
            quiet()
    elif sys.argv[1:2] == ["--rebake"]:
        vid = rebake(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 7000)
        print("voice", vid, state(sys.argv[2]).get("check"))
        try:
            from .jobwatch import telegram
            telegram(f"Renard: голос «{sys.argv[2]}» перезапечён ({vid}), проверка: {state(sys.argv[2]).get('check')}")
        except Exception:
            quiet()
    elif sys.argv[1:2] == ["--dataset"]:
        vid = run_dataset(sys.argv[3], Path(sys.argv[2]), int(sys.argv[4]) if len(sys.argv) > 4 else 7000)
        print("voice", vid)
        try:
            from .jobwatch import telegram
            telegram(f"Renard: голос «{sys.argv[3]}» запечён ({vid}). Можно включать в личности.")
        except Exception:
            quiet()
