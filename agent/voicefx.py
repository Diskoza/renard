"""A voice's own sound after synthesis (numpy only, ~1 ms per second of speech).

robot — the steady metallic tone of a TV-robot voice. Measured on sample recordings: the cepstrum of every voiced
frame has a peak at the same 0.63 ms whatever the pitch — a short comb (a voice mixed with itself 0.63 ms later). The
baked voice and the clone carry it only now and then, so it is added here, always.
    {"delay_ms": 0.63, "gain": 0.6, "feedback": 0.3, "wobble": 0.0}

pace — Piper rushes through a long sentence: it is said in parts (cut after commas), each part a little slower than the
one before, with a short breath between them — people start a phrase quicker and slow down to its end.
    {"ramp": 0.12, "comma_pause": 0.12}

Both live in the voice's settings: «renard» → «fx» / «pace» in <voice>.onnx.json, «fx» in clone/<name>/meta.json."""
import re

import numpy as np


def robot(a: np.ndarray, sr: int, fx: dict | None) -> np.ndarray:
    """float32 −1..1 → the same with the comb; level kept the same (RMS), no clipping"""
    if not fx or not len(a):
        return a
    d = float(fx.get("delay_ms", 0.63)) * sr / 1000.0
    g, fb, wob = float(fx.get("gain", 0.6)), float(fx.get("feedback", 0.3)), float(fx.get("wobble", 0.0))
    n = np.arange(len(a), dtype=np.float32)
    delay = d * (1 + 0.15 * np.sin(2 * np.pi * wob * n / sr)) if wob else np.full(len(a), d, np.float32)
    idx = n - delay
    lo = np.floor(idx).astype(np.int64)
    fr = (idx - lo).astype(np.float32)
    ok = lo >= 0
    lo1 = np.clip(lo + 1, 0, len(a) - 1)
    lo = np.clip(lo, 0, len(a) - 1)
    dl = np.where(ok, a[lo] * (1 - fr) + a[lo1] * fr, 0).astype(np.float32)
    y = a + g * dl
    if fb:
        y = y + fb * g * np.where(ok, np.concatenate([np.zeros(int(round(d)), np.float32), dl])[:len(a)], 0)
    r0, r1 = float(np.sqrt(np.mean(a ** 2)) + 1e-9), float(np.sqrt(np.mean(y ** 2)) + 1e-9)
    y = y * (r0 / r1)
    peak = float(np.abs(y).max())
    return (y / peak * 0.97 if peak > 0.97 else y).astype(np.float32)


def robot_pcm(pcm: bytes, sr: int, fx: dict | None) -> bytes:
    if not fx or not pcm:
        return pcm
    a = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    return (robot(a, sr, fx) * 32767).astype(np.int16).tobytes()


_CUT = re.compile(r"(?<=[,;:—–])\s+")


def parts(sentence: str, min_words: int = 3) -> list[str]:
    """a sentence → its parts after commas / dashes; a part of 1–2 words sticks to the next one («Да, конечно»)"""
    out, cur = [], ""
    for p in _CUT.split(sentence.strip()):
        cur = f"{cur} {p}".strip() if cur else p
        if len(cur.split()) >= min_words:
            out.append(cur)
            cur = ""
    if cur:
        if out and len(cur.split()) < min_words:
            out[-1] = f"{out[-1]} {cur}"
        else:
            out.append(cur)
    return out or [sentence]


def ramp(i: int, n: int, k: float) -> float:
    """length_scale factor of part i of n: 1.0 for the first, 1+k for the last"""
    return 1.0 + (k * i / (n - 1) if n > 1 else 0.0)
