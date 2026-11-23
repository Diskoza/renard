"""Understand audio and video files: speech -> text with timecodes (Whisper), video -> a few key frames looked at
by the vision model, then one combined description the agent can retell / answer questions about."""
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

from . import S, tool

AUDIO = {".mp3", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".flac", ".wma", ".amr"}
VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".3gp", ".gif"}


def probe(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                        "-of", "json", str(p)], capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout or "{}")
    kinds = {s.get("codec_type") for s in d.get("streams", [])}
    return {"dur": float(d.get("format", {}).get("duration") or 0), "audio": "audio" in kinds,
            "video": "video" in kinds and p.suffix.lower() not in AUDIO}


def _audio_wav(p: Path, out: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vn", "-ac", "1", "-ar", "16000", str(out)],
                   check=True, timeout=600)


def _frame(p: Path, t: float, out: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1",
                    "-vf", "scale='min(1280,iw)':-2", str(out)], check=True, timeout=60)


def tc(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


async def analyze_file(path: str, question: str = "", ctx: dict | None = None, frames: int = 0) -> str:
    from .. import voice
    from .extra import _ask_vision, _img_b64
    p = Path(path)
    info = await asyncio.to_thread(probe, p)
    parts = [f"Файл {p.name}: длительность {tc(info['dur'])}" + (", видео" if info["video"] else ", аудио")]
    with tempfile.TemporaryDirectory() as d:
        if info["audio"]:
            wav = Path(d) / "a.wav"
            await asyncio.to_thread(_audio_wav, p, wav)
            r = await asyncio.to_thread(voice.stt.transcribe, wav.read_bytes(), None, "media", True)
            segs = r.get("segments") or []
            if segs:
                lines = [f"[{tc(s)}] {t}" for s, t, *_ in segs]
                text = "\n".join(lines)
                if len(text) > 12000:
                    text = text[:8000] + "\n…\n" + text[-3500:]
                parts.append(f"Речь (язык {r.get('lang')}, расшифровка с таймкодами):\n{text}")
            else:
                parts.append("Речи не слышно" + (f" ({r.get('error')})" if r.get("error") else "") + ".")
        if info["video"] and ctx and ctx.get("agent"):
            n = frames or (3 if info["dur"] < 20 else 5 if info["dur"] < 180 else 7)
            times = [info["dur"] * (i + 0.5) / n for i in range(n)] if info["dur"] > 0 else [0]
            seen = []
            from PIL import Image
            for i, t in enumerate(times):
                f = Path(d) / f"f{i}.jpg"
                try:
                    await asyncio.to_thread(_frame, p, t, f)
                    desc = await _ask_vision(ctx, _img_b64(Image.open(f), 1024),
                                             "Кадр из видео. Коротко (1-2 предложения): что происходит, кто/что в кадре, "
                                             "текст на экране дословно, если есть." + (f" Вопрос пользователя: {question}" if question else ""))
                    seen.append(f"[{tc(t)}] {desc}")
                except Exception as e:
                    seen.append(f"[{tc(t)}] (кадр не получен: {e})")
            parts.append("Что видно на кадрах:\n" + "\n".join(seen))
    return "\n\n".join(parts)


@tool("analyze_media", "Разобрать аудио или видео файл: расшифровка речи с таймкодами (Whisper) и, для видео, что видно на "
                       "ключевых кадрах. Потом перескажи / ответь на вопрос пользователя. path — файл (mp3, ogg, m4a, wav, mp4, "
                       "mkv, mov, webm…), question — что нужно узнать.", {"path": S, "question": S}, ["path"])
async def analyze_media(path: str, question: str = "", ctx: dict | None = None) -> str:
    from .files import safe
    p = safe(path)
    if not p.is_file():
        return f"Файла {p} нет."
    try:
        return await analyze_file(str(p), question, ctx)
    except Exception as e:
        return f"Не смог разобрать {p.name}: {type(e).__name__}: {e}"
