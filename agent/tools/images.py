"""Photo / picture editing in code (Pillow) — faster and more reliable than clicking through GIMP / Paint.

image_edit: a chain of steps on one picture (light, colours, crop, size, text, frames, blur/pixelate a region, stickers,
format and quality). image_make: new pictures (blank canvas with text, collage, meme). The original file is never
overwritten: the result goes next to it as «<name>_edit.<ext>» unless `out` says otherwise.
"""
import re
from pathlib import Path

from . import S, tool

COLORS = {"красн": "#e53935", "red": "#e53935", "зел": "#43a047", "green": "#43a047", "син": "#1e88e5", "blue": "#1e88e5",
          "жёлт": "#fdd835", "желт": "#fdd835", "yellow": "#fdd835", "бел": "#ffffff", "white": "#ffffff",
          "чёрн": "#000000", "черн": "#000000", "black": "#000000", "оранж": "#fb8c00", "orange": "#fb8c00",
          "фиолет": "#8e24aa", "purple": "#8e24aa", "розов": "#ec407a", "pink": "#ec407a", "сер": "#9e9e9e", "gray": "#9e9e9e"}
POS = {"top": "top", "верх": "top", "сверху": "top", "bottom": "bottom", "низ": "bottom", "снизу": "bottom",
       "center": "center", "центр": "center", "по центру": "center"}


def _color(s: str, default="#ffffff") -> str:
    s = (s or "").strip().lower()
    if re.fullmatch(r"#?[0-9a-f]{6}", s):
        return s if s.startswith("#") else "#" + s
    return next((v for k, v in COLORS.items() if s.startswith(k)), default)


def _font(size: int, bold=True):
    from PIL import ImageFont
    for f in (("arialbd.ttf" if bold else "arial.ttf"), "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _nums(arg: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", arg or "")]


def _box(arg: str, img) -> tuple[int, int, int, int]:
    """«x1,y1,x2,y2» in pixels, or «10%,20%,60%,80%», or a word: top/bottom/left/right/center (half / middle third)."""
    W, H = img.size
    a = (arg or "").lower()
    if "%" in a:
        p = _nums(a)[:4]
        return int(W * p[0] / 100), int(H * p[1] / 100), int(W * p[2] / 100), int(H * p[3] / 100)
    n = _nums(a)
    if len(n) >= 4:
        return tuple(int(x) for x in n[:4])
    for k, b in {"верх": (0, 0, W, H // 2), "top": (0, 0, W, H // 2), "низ": (0, H // 2, W, H), "bottom": (0, H // 2, W, H),
                 "лев": (0, 0, W // 2, H), "left": (0, 0, W // 2, H), "прав": (W // 2, 0, W, H), "right": (W // 2, 0, W, H),
                 "центр": (W // 3, H // 3, 2 * W // 3, 2 * H // 3), "center": (W // 3, H // 3, 2 * W // 3, 2 * H // 3)}.items():
        if k in a:
            return b
    return 0, 0, W, H


def _caption(img, text: str, where: str = "bottom", color: str = "#ffffff", size: float = 0.08):
    """Meme-style text with an outline, wrapped to the width."""
    from PIL import ImageDraw
    img = img.convert("RGBA")
    d = ImageDraw.Draw(img)
    fs = max(14, int(img.height * size))
    font = _font(fs)
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) > img.width * 0.92 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    lh = int(fs * 1.15)
    y0 = int(img.height * 0.03) if where == "top" else (img.height - lh * len(lines)) // 2 if where == "center" \
        else img.height - lh * len(lines) - int(img.height * 0.03)
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=font)
        d.text(((img.width - tw) / 2, y0 + i * lh), line, font=font, fill=color, stroke_width=max(2, fs // 14),
               stroke_fill="#000000" if color.lower() != "#000000" else "#ffffff")
    return img


MODELS = Path(__file__).resolve().parents[2] / "data" / "models"
_seg = {}


def remove_bg(img):
    """Real background removal: IS-Net (the rembg «isnet-general-use» model) on onnxruntime, CPU. Returns RGBA."""
    from PIL import Image
    import numpy as np
    import onnxruntime as ort
    f = MODELS / "isnet-general-use.onnx"
    if not f.exists():
        raise RuntimeError(f"нет модели {f.name} в data/models (скачать: github.com/danielgatis/rembg/releases)")
    if "s" not in _seg:
        _seg["s"] = ort.InferenceSession(str(f), providers=["CPUExecutionProvider"])
    s = _seg["s"]
    rgb = img.convert("RGB")
    x = np.asarray(rgb.resize((1024, 1024), Image.LANCZOS)).astype(np.float32)
    x = x / max(float(x.max()), 1e-6) - 0.5
    x = x.transpose(2, 0, 1)[None]
    pred = s.run(None, {s.get_inputs()[0].name: x})[0][:, 0, :, :]
    mi, ma = float(pred.min()), float(pred.max())
    m = ((pred - mi) / max(ma - mi, 1e-6))[0]
    mask = Image.fromarray((m * 255).clip(0, 255).astype("uint8")).resize(rgb.size, Image.LANCZOS)
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    return out


def upscale(img, k: int = 2):
    """×2 / ×4 with the FSRCNN super-resolution net (OpenCV dnn_superres), then a light sharpen; Lanczos if no model."""
    from PIL import Image, ImageEnhance
    import numpy as np
    k = 4 if k >= 3 else 2
    alpha = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
    rgb = img.convert("RGB")
    if rgb.width * rgb.height * k * k > 40_000_000:
        k = 2
    try:
        import cv2
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(str(MODELS / f"FSRCNN_x{k}.pb"))
        sr.setModel("fsrcnn", k)
        big = Image.fromarray(sr.upsample(np.asarray(rgb)[:, :, ::-1].copy())[:, :, ::-1].copy())
    except Exception:
        big = rgb.resize((rgb.width * k, rgb.height * k), Image.LANCZOS)
    big = ImageEnhance.Sharpness(big).enhance(1.25)
    if alpha is not None:
        big = big.convert("RGBA"); big.putalpha(alpha.resize(big.size, Image.LANCZOS))
    return big


def apply(img, op: str, src_dir: Path):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    import numpy as np
    name, _, arg = op.strip().partition(" ")
    name, arg = name.lower(), arg.strip()
    n = _nums(arg)
    if name in ("remove_bg", "removebg", "nobg", "убрать_фон", "cutout"):
        im = remove_bg(img)
        if arg:
            bg = Image.new("RGBA", im.size, _color(arg)); bg.alpha_composite(im); return bg.convert("RGB")
        return im
    if name in ("upscale", "upscale2", "upscale4", "увеличить", "superres"):
        return upscale(img, int(n[0]) if n else (4 if name.endswith("4") else 2))
    if name in ("grayscale", "gray", "bw", "чб", "серый"):
        return ImageOps.grayscale(img) if img.mode != "RGBA" else ImageOps.grayscale(img).convert("LA")
    if name == "resize":
        return img.resize((int(n[0]), int(n[1])), Image.LANCZOS)
    if name == "width":
        return img.resize((int(n[0]), round(img.height * n[0] / img.width)), Image.LANCZOS)
    if name == "height":
        return img.resize((round(img.width * n[0] / img.height), int(n[0])), Image.LANCZOS)
    if name in ("scale", "zoom"):
        k = n[0] / 100 if n and n[0] > 5 else (n[0] if n else 0.5)
        return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
    if name == "fit":
        im = img.copy(); im.thumbnail((int(n[0]), int(n[1])), Image.LANCZOS); return im
    if name == "crop":
        return img.crop(_box(arg, img))
    if name == "square":
        s = min(img.size); l, t = (img.width - s) // 2, (img.height - s) // 2
        return img.crop((l, t, l + s, t + s))
    if name == "aspect":
        a, b = n[0], n[1]; W, H = img.size
        if W / H > a / b:
            nw = int(H * a / b); return img.crop(((W - nw) // 2, 0, (W - nw) // 2 + nw, H))
        nh = int(W * b / a); return img.crop((0, (H - nh) // 2, W, (H - nh) // 2 + nh))
    if name == "rotate":
        return img.rotate(-(n[0] if n else 90), expand=True, fillcolor=(255, 255, 255, 0) if img.mode == "RGBA" else None)
    if name in ("flip", "mirror"):
        return ImageOps.mirror(img)
    if name in ("flip_v", "vflip"):
        return ImageOps.flip(img)
    if name in ("brightness", "яркость"):
        return ImageEnhance.Brightness(img.convert("RGB") if img.mode == "P" else img).enhance(1 + (n[0] if n else 20) / 100)
    if name in ("contrast", "контраст"):
        return ImageEnhance.Contrast(img.convert("RGB") if img.mode == "P" else img).enhance(1 + (n[0] if n else 20) / 100)
    if name in ("saturation", "насыщенность", "color"):
        return ImageEnhance.Color(img.convert("RGB") if img.mode == "P" else img).enhance(1 + (n[0] if n else 30) / 100)
    if name in ("sharpen", "резкость"):
        return ImageEnhance.Sharpness(img.convert("RGB") if img.mode == "P" else img).enhance(1 + (n[0] if n else 100) / 100)
    if name in ("blur", "размыть"):
        first, _, rest = arg.partition(" ")
        r = float(first) if re.fullmatch(r"\d+(\.\d+)?", first) else 6
        rest = rest if re.fullmatch(r"\d+(\.\d+)?", first) else arg
        if rest.strip():
            box = _box(rest, img)
            region = img.crop(box).filter(ImageFilter.GaussianBlur(r)); im = img.copy(); im.paste(region, box[:2]); return im
        return img.filter(ImageFilter.GaussianBlur(r))
    if name in ("pixelate", "censor", "пикселизация"):
        box = _box(arg, img); region = img.crop(box)
        k = max(6, min(region.size) // 12)
        region = region.resize((max(1, region.width // k), max(1, region.height // k)), Image.NEAREST).resize(region.size, Image.NEAREST)
        im = img.copy(); im.paste(region, box[:2]); return im
    if name in ("autocontrast", "auto", "улучшить", "enhance"):
        rgb = img.convert("RGB")
        rgb = ImageOps.autocontrast(rgb, cutoff=1)
        return ImageEnhance.Sharpness(ImageEnhance.Color(rgb).enhance(1.15)).enhance(1.3)
    if name in ("denoise", "шум"):
        return img.filter(ImageFilter.MedianFilter(3))
    if name in ("invert", "негатив"):
        return ImageOps.invert(img.convert("RGB"))
    if name in ("sepia", "сепия"):
        g = np.array(ImageOps.grayscale(img)).astype(float)
        rgb = np.stack([g * 1.07, g * 0.74, g * 0.43], -1).clip(0, 255).astype("uint8")
        return Image.fromarray(rgb)
    if name in ("vignette", "виньетка"):
        rgb = np.array(img.convert("RGB")).astype(float)
        H, W = rgb.shape[:2]; y, x = np.ogrid[:H, :W]
        d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
        k = (1 - 0.55 * np.clip(d - 0.4, 0, 1)) [..., None]
        return Image.fromarray((rgb * k).clip(0, 255).astype("uint8"))
    if name in ("border", "рамка"):
        w = int(n[0]) if n else 20
        return ImageOps.expand(img.convert("RGB"), border=w, fill=_color(re.sub(r"[\d\s]+", "", arg), "#ffffff"))
    if name in ("round", "rounded", "скруглить"):
        r = int(n[0]) if n else min(img.size) // 10
        im = img.convert("RGBA"); mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width, im.height), r, fill=255); im.putalpha(mask); return im
    if name in ("circle", "круг"):
        s = min(img.size); im = apply(img, "square", src_dir).convert("RGBA"); mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, s, s), fill=255); im.putalpha(mask); return im
    if name == "transparent_white":
        a = np.array(img.convert("RGBA")); m = (a[..., :3] > 235).all(-1); a[m, 3] = 0; return Image.fromarray(a)
    if name == "keep_color":
        a = np.array(img.convert("RGBA")).astype(int); r, g, b = a[..., 0], a[..., 1], a[..., 2]
        m = {"red": (r > 120) & (r > g * 1.6) & (r > b * 1.6), "green": (g > 100) & (g > r * 1.3) & (g > b * 1.3),
             "blue": (b > 100) & (b > r * 1.3) & (b > g * 1.1), "yellow": (r > 150) & (g > 150) & (b < r * 0.6)}.get(arg.lower() or "red")
        if m is None:
            raise ValueError("keep_color: red / green / blue / yellow")
        a[~m, 3] = 0; im = Image.fromarray(a.astype("uint8")); box = im.getbbox(); return im.crop(box) if box else im
    if name in ("text", "caption", "надпись", "meme"):
        parts = [p.strip() for p in arg.split("|")]
        opts = {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in parts[1:]) if v}
        where = POS.get(opts.get("where", "bottom").lower(), "bottom")
        size = float(opts.get("size", 8)) / 100
        return _caption(img, parts[0], where, _color(opts.get("color", "white")), size)
    if name in ("watermark", "подпись"):
        im = img.convert("RGBA"); d = ImageDraw.Draw(im); fs = max(12, im.height // 28); f = _font(fs, bold=False)
        tw = d.textlength(arg, font=f)
        d.text((im.width - tw - fs, im.height - fs * 1.6), arg, font=f, fill=(255, 255, 255, 170), stroke_width=1, stroke_fill=(0, 0, 0, 120))
        return im
    if name in ("sticker", "overlay", "наложить"):
        parts = [p.strip() for p in arg.split("|")]
        p = Path(parts[0]) if Path(parts[0]).is_absolute() else src_dir / parts[0]
        opts = {k.strip(): v.strip() for k, _, v in (q.partition("=") for q in parts[1:]) if v}
        st = Image.open(p).convert("RGBA"); k = float(opts.get("size", 20)) / 100
        st.thumbnail((int(img.width * k), int(img.height * k)), Image.LANCZOS)
        where = opts.get("where", "bottom-right"); m = int(min(img.size) * 0.03)
        x = m if "left" in where or "лев" in where else (img.width - st.width) // 2 if "center" in where or "центр" in where else img.width - st.width - m
        y = m if "top" in where or "верх" in where else (img.height - st.height) // 2 if where in ("center", "центр") else img.height - st.height - m
        im = img.convert("RGBA"); im.alpha_composite(st, (int(x), int(y))); return im
    raise ValueError(f"неизвестный шаг «{op}»")


STEPS = ("remove_bg (НАСТОЯЩЕЕ удаление фона нейросетью → прозрачный PNG; remove_bg white — на белом фоне) | "
         "upscale 2 / upscale 4 (увеличить разрешение и качество нейросетью) | grayscale | resize 800x600 | width 1080 | height 720 | scale 50% | fit 1080x1080 | crop x1,y1,x2,y2 (или 10%,10%,90%,90% "
         "или top/bottom/left/right/center) | square | aspect 16:9 | rotate 90 | flip | flip_v | brightness 20 (−/+ %) | "
         "contrast 20 | saturation 30 | sharpen 100 | blur 4 [область] | pixelate <область> (замазать лицо/номер) | "
         "autocontrast (улучшить фото) | denoise | invert | sepia | vignette | border 20 white | round 40 | circle | "
         "transparent_white (только чисто белый фон → прозрачный; для «убери фон» — remove_bg) | keep_color red | text Надпись | where=top|bottom|center | color=yellow | size=8 | "
         "watermark @nick | sticker путь.png | where=bottom-right | size=20")


@tool("image_edit",
      "Редактировать фото/картинку кодом (без GIMP/Paint — быстрее и точнее). path — файл, ops — шаги через «;»: " + STEPS +
      ". out — куда сохранить (расширение = формат: .jpg/.png/.webp; quality через format_quality), по умолчанию рядом с "
      "оригиналом «_edit». Оригинал не трогается.", {"path": S, "ops": S, "out": S}, ["path", "ops"])
def image_edit(path: str, ops: str, out: str = "") -> str:
    from PIL import Image, ImageOps
    from .files import safe
    src = safe(path)
    img = ImageOps.exif_transpose(Image.open(src))
    log = []
    for op in [o.strip() for o in re.split(r";\s*|\n", ops) if o.strip()]:
        try:
            img = apply(img, op, src.parent)
        except Exception as e:
            return f"Шаг «{op}» не получился: {e}. Доступно: {STEPS}"
        log.append(op)
    dst = safe(out) if out else src.with_name(src.stem + "_edit" + (".png" if img.mode in ("RGBA", "LA") else src.suffix))
    if dst.suffix.lower() in (".jpg", ".jpeg") and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    kw = {"quality": 90} if dst.suffix.lower() in (".jpg", ".jpeg", ".webp") else {}
    img.save(dst, **kw)
    return f"Сохранил {dst} ({img.width}x{img.height}). Шаги: {'; '.join(log)}"


@tool("image_make",
      "Создать новую картинку: kind=collage (paths — файлы через «;», в сетку), kind=meme (paths — одно фото, "
      "top/bottom — текст сверху/снизу), kind=card (пустой холст: size 1080x1080, color фон, text крупно по центру). "
      "out — куда сохранить (по умолчанию workspace/images)",
      {"kind": S, "paths": S, "top": S, "bottom": S, "text": S, "size": S, "color": S, "out": S}, ["kind"])
def image_make(kind: str, paths: str = "", top: str = "", bottom: str = "", text: str = "", size: str = "1080x1080",
               color: str = "", out: str = "") -> str:
    import math
    import time
    from PIL import Image, ImageOps
    from ..config import SETTINGS
    from .files import safe
    k = (kind or "").lower()
    files = [safe(p.strip()) for p in re.split(r";|\n", paths or "") if p.strip()]
    if k.startswith("coll"):
        if len(files) < 2:
            return "Для коллажа нужно минимум 2 файла."
        n = len(files); cols = math.ceil(math.sqrt(n)); rows = math.ceil(n / cols); cell = 600
        canvas = Image.new("RGB", (cols * cell, rows * cell), _color(color, "#ffffff"))
        for i, f in enumerate(files):
            im = ImageOps.fit(ImageOps.exif_transpose(Image.open(f)).convert("RGB"), (cell - 12, cell - 12), Image.LANCZOS)
            canvas.paste(im, ((i % cols) * cell + 6, (i // cols) * cell + 6))
        img = canvas
    elif k.startswith("meme"):
        if not files:
            return "Нужно фото (paths)."
        img = ImageOps.exif_transpose(Image.open(files[0])).convert("RGB")
        if top:
            img = _caption(img, top.upper(), "top")
        if bottom:
            img = _caption(img, bottom.upper(), "bottom")
    else:
        w, h = (int(x) for x in (re.findall(r"\d+", size or "1080x1080") + ["1080", "1080"])[:2])
        img = Image.new("RGB", (w, h), _color(color, "#1e1e2e"))
        if text:
            img = _caption(img, text, "center", "#ffffff", 0.09)
    dst = safe(out) if out else Path(SETTINGS.get("workspace", "workspace")).resolve() / "images" / time.strftime(f"{k[:6] or 'image'}_%Y%m%d_%H%M%S.png")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        img = img.convert("RGB")
    img.save(dst)
    return f"Сохранил {dst} ({img.width}x{img.height})."
