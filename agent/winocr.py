"""Windows OCR (Windows.Media.Ocr, offline, ru / pl / en) for numpy images: lines with their boxes."""
import asyncio

import numpy as np

_ENG = {}


def _engine(lang: str):
    if lang not in _ENG:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        _ENG[lang] = OcrEngine.try_create_from_language(Language(lang))
    return _ENG[lang]


def _bitmap(rgb: np.ndarray):
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import Buffer
    h, w = rgb.shape[:2]
    bgra = np.empty((h, w, 4), np.uint8)
    bgra[..., 0], bgra[..., 1], bgra[..., 2], bgra[..., 3] = rgb[..., 2], rgb[..., 1], rgb[..., 0], 255
    data = bgra.tobytes()
    buf = Buffer(len(data))
    buf.length = len(data)
    mv = memoryview(buf)
    if mv.format != "B" or mv.ndim != 1:
        mv = mv.cast("B")
    mv[:] = data
    return SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)


async def _recognize(rgb: np.ndarray, lang: str) -> list[dict]:
    res = await _engine(lang).recognize_async(_bitmap(rgb))
    out = []
    for ln in res.lines:
        ws = list(ln.words)
        if not ws:
            continue
        x0 = min(w.bounding_rect.x for w in ws); y0 = min(w.bounding_rect.y for w in ws)
        x1 = max(w.bounding_rect.x + w.bounding_rect.width for w in ws)
        y1 = max(w.bounding_rect.y + w.bounding_rect.height for w in ws)
        out.append({"text": ln.text, "box": (x0, y0, x1, y1)})
    return out


def ocr(rgb: np.ndarray, lang: str = "ru") -> list[dict]:
    """rgb: HxWx3 uint8 → [{"text", "box": (x0, y0, x1, y1)}] top to bottom."""
    return asyncio.run(_recognize(np.ascontiguousarray(rgb), lang))
