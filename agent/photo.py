"""Photos like a careful retoucher, all on this PC (OpenCV + numpy, no internet, no GPU):

  enhance()  soft «make it pretty» grade: colour noise away, local contrast, shadows a bit up, highlights kept, deeper
             blacks, a touch warmer, light sharpening, soft vignette; too bright photos are darkened a little
  analyze()  sharpness (on faces when there are any), exposure, clipped highlights, faces -> one score
  pick()     the best shots of a folder: near-duplicates grouped, the sharpest / best exposed of each group wins
  crop()     Instagram / any ratio crop that keeps the faces in (4:5 feed, 9:16 stories, 1:1)
  compare()  before | after picture

Originals are never touched: results go to <folder>/edited (or /best, /crop) next to them."""
import math
import shutil
from pathlib import Path

import numpy as np

from .config import DATA_DIR

EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
FACE_MODEL = DATA_DIR / "models" / "photo" / "face_yunet.onnx"

STYLES = {
    "natural": dict(warm=1.5, tint=.3, sat=1.06, lift=.10, clahe=.45, black=.012, vig=.10, sharp=.45),
    "warm":    dict(warm=4.0, tint=1.0, sat=1.08, lift=.10, clahe=.45, black=.018, vig=.14, sharp=.45),
    "night":   dict(warm=3.0, tint=.8, sat=1.05, lift=.07, clahe=.40, black=.030, vig=.18, sharp=.40),
    "cold":    dict(warm=-3.0, tint=-.3, sat=1.04, lift=.10, clahe=.45, black=.015, vig=.10, sharp=.45),
    "vivid":   dict(warm=1.5, tint=.5, sat=1.18, lift=.12, clahe=.65, black=.020, vig=.10, sharp=.55),
    "soft":    dict(warm=2.0, tint=.6, sat=.98, lift=.16, clahe=.25, black=.005, vig=.06, sharp=.25),
    "bw":      dict(warm=0, tint=0, sat=0, lift=.10, clahe=.60, black=.025, vig=.16, sharp=.50),
}
STYLE_RU = {"естественно": "natural", "натурально": "natural", "тепло": "warm", "теплее": "warm", "ночь": "night",
            "вечер": "night", "холодно": "cold", "холоднее": "cold", "ярко": "vivid", "сочно": "vivid", "мягко": "soft",
            "нежно": "soft", "чб": "bw", "чёрно-белое": "bw", "черно-белое": "bw"}


def load(path) -> tuple:
    """-> (RGB uint8 array, exif bytes). Phone rotation applied, HEIC works."""
    from PIL import Image, ImageOps
    p = Path(path)
    if p.suffix.lower() in (".heic", ".heif"):
        import pillow_heif
        pillow_heif.register_heif_opener()
    im = Image.open(p)
    exif = b""
    try:
        ex = im.getexif()
        ex[0x0112] = 1
        exif = ex.tobytes()
    except Exception:
        pass
    im = ImageOps.exif_transpose(im).convert("RGB")
    return np.asarray(im), exif


def save(rgb: np.ndarray, dst, exif: bytes = b"", quality=95) -> Path:
    from PIL import Image
    dst = Path(dst)
    if dst.suffix.lower() in (".heic", ".heif", ".bmp", ".tif", ".tiff"):
        dst = dst.with_suffix(".jpg")
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    kw = {"quality": quality, "subsampling": 0} if dst.suffix.lower() in (".jpg", ".jpeg", ".webp") else {}
    if exif and dst.suffix.lower() in (".jpg", ".jpeg", ".webp"):
        kw["exif"] = exif
    im.save(dst, **kw)
    return dst


def images_in(folder) -> list:
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.suffix.lower() in EXT and not p.name.startswith("_"))


def out_path(src: Path, sub: str, suffix: str = "") -> Path:
    """<folder>/<sub>/<name><suffix>.jpg, never the original, never an existing result (… (2).jpg)"""
    ext = src.suffix.lower() if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
    d = src.parent / sub
    p = d / f"{src.stem}{suffix}{ext}"
    k = 2
    while p.exists():
        p = d / f"{src.stem}{suffix} ({k}){ext}"
        k += 1
    return p


def faces(rgb: np.ndarray) -> list:
    """[(x, y, w, h, score)] in image pixels; [] when the face model is missing"""
    import cv2
    if not FACE_MODEL.exists():
        return []
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    H, W = rgb.shape[:2]
    k = min(1.0, 1280 / max(H, W))
    small = cv2.resize(rgb, (max(1, int(W * k)), max(1, int(H * k))), interpolation=cv2.INTER_AREA)
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (small.shape[1], small.shape[0]), 0.72, 0.3, 50)
    _, res = det.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
    out = []
    for r in (res if res is not None else []):
        x, y, w, h = (r[:4] / k).tolist()
        if w * h > (W * H) * 0.0004:
            out.append((int(x), int(y), int(w), int(h), float(r[-1])))
    return out


def _curve(L, lift, black, protect=.92):
    """L 0..1: shadows up, a deeper black point, highlights rolled off instead of clipped"""
    y = L + lift * L * (1 - L) ** 2 * 2.6
    y = np.clip((y - black) / (1 - black), 0, None)
    over = y > protect
    y[over] = protect + (1 - protect) * np.tanh((y[over] - protect) / (1 - protect))
    return np.clip(y, 0, 1)


def enhance(rgb: np.ndarray, style: str = "natural", strength: float = 1.0, darken: str = "auto",
            denoise: bool = True) -> tuple:
    """-> (new RGB, list of what was done). strength 0.3 (barely) … 1.5 (strong)."""
    import cv2
    st = dict(STYLES.get(STYLE_RU.get(style, style), STYLES["natural"]))
    s = max(0.0, min(2.0, float(strength)))
    did = []
    img = rgb.copy()
    H, W = img.shape[:2]
    if denoise:
        lab8 = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        L8, a8, b8 = cv2.split(lab8)
        k = max(3, int(round(min(H, W) / 700)) | 1)
        a8 = cv2.bilateralFilter(a8, k * 2 + 1, 12, k * 2)
        b8 = cv2.bilateralFilter(b8, k * 2 + 1, 12, k * 2)
        noise = float(np.median(np.abs(L8.astype(np.int16) - cv2.medianBlur(L8, 3).astype(np.int16))))
        if noise >= 2:
            L8 = cv2.fastNlMeansDenoising(L8, None, h=min(6, 1.5 + noise * .8), templateWindowSize=7, searchWindowSize=15)
        img = cv2.cvtColor(cv2.merge([L8, a8, b8]), cv2.COLOR_LAB2RGB)
        did.append("шум убран" + (" (и зерно)" if noise >= 2 else " (цветной)"))
    lab = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    L, A, B = cv2.split(lab)
    L1 = L / 100
    med, hi = float(np.median(L1)), float((L1 > .97).mean())
    dk = 0.0
    if darken in ("auto", "yes", "да", True) or darken == "1":
        dk = max(0.0, (med - .5) * 1.6)
        if darken in ("yes", "да", True, "1"):
            dk = max(dk, .18)
        dk = min(.45, dk)
        if dk > .03:
            L1 = L1 ** (1 + dk)
            did.append(f"затемнил светлое ({int(dk * 100)}%)")
    sm = max(1, int(min(H, W) / 600))
    small = cv2.resize(L1, (W // sm, H // sm), interpolation=cv2.INTER_AREA) if sm > 1 else L1
    kk = max(15, int(min(small.shape) / 25)) | 1
    lmin = cv2.erode(small.astype(np.float32), cv2.getStructuringElement(cv2.MORPH_RECT, (kk, kk)))
    lmin = cv2.GaussianBlur(lmin, (0, 0), kk)
    veil = np.clip(lmin - .25, 0, .4)
    if float((veil > .05).mean()) > .03:
        veil = cv2.resize(veil, (W, H), interpolation=cv2.INTER_LINEAR) if sm > 1 else veil
        k2 = .5 * min(1.0, s)
        L1 = np.clip((L1 - k2 * veil) / (1 - k2 * veil), 0, 1)
        did.append("убрал дымку / засветку от света")
    fs = faces(rgb) if st["sat"] >= 0 else []
    for x, y, w, h, _ in fs[:4]:
        fl = float(np.median(L1[max(0, y):y + h, max(0, x):x + w]))
        if fl < .55:
            m = np.zeros((H, W), np.float32)
            cv2.ellipse(m, (x + w // 2, y + h // 2), (int(w * .75), int(h * .85)), 0, 0, 360, 1, -1)
            m = cv2.GaussianBlur(m, (0, 0), max(w, h) * .25)
            g = min(.35, (.58 - fl) * 1.6) * s
            L1 = L1 + m * g * L1 * (1 - L1) * 2
            did.append("лицо чуть светлее")
    hi = float((L1 > .96).mean())
    protect = .92 - min(.14, hi * 5)
    if st["clahe"] * s > 0:
        tiles = max(4, min(12, int(round(max(H, W) / 400))))
        c = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(tiles, tiles)).apply((L1 * 255).astype(np.uint8)).astype(np.float32) / 255
        L1 = L1 + (c - L1) * min(1, st["clahe"] * s)
        did.append("локальный контраст")
    L1 = _curve(L1, st["lift"] * s, st["black"] * s, protect)
    did.append("тени приподнял, чёрный глубже, светлое не выбито")
    mid = (L1 > .2) & (L1 < .8)
    if mid.mean() > .05 and st["sat"] > 0:
        ca, cb = float(A[mid].mean()), float(B[mid].mean())
        fa = ca if abs(ca) > 5 else 0.0
        fb = cb if cb < -5 else 0.0
        if fa or fb:
            A, B = A - fa * .35, B - fb * .35
            did.append("баланс белого")
    A = A + st["tint"] * s
    B = B + st["warm"] * s
    if st["warm"]:
        did.append("теплее" if st["warm"] > 0 else "холоднее")
    chroma = np.sqrt(A ** 2 + B ** 2)
    boost = 1 + (st["sat"] - 1) * s * np.clip(1 - chroma / 60, 0, 1) * 1.6 if st["sat"] > 0 else 0
    A, B = A * boost, B * boost
    if st["sharp"] * s > 0:
        sig = max(.8, min(H, W) / 1400)
        blur = cv2.GaussianBlur(L1, (0, 0), sig)
        det = L1 - blur
        det = np.where(np.abs(det) < .004, 0, det)
        L1 = np.clip(L1 + det * st["sharp"] * s * 1.4, 0, 1)
        did.append("резкость")
    if st["vig"] * s > 0:
        yy, xx = np.ogrid[:H, :W]
        d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        L1 = L1 * (1 - st["vig"] * s * np.clip((d - .45) / .55, 0, 1) ** 2)
        did.append("мягкая виньетка")
    out = cv2.cvtColor(cv2.merge([np.asarray(c, np.float32) for c in (L1 * 100, A, B)]), cv2.COLOR_LAB2RGB)
    out = (np.clip(out, 0, 1) * 255 + .5).astype(np.uint8)
    if st["sat"] == 0:
        g = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)
        out = np.stack([g] * 3, -1)
        did.append("чёрно-белое")
    return out, did


def floor_fade(rgb: np.ndarray, amount=.35, height=.3) -> np.ndarray:
    """a bright floor / sky that pulls the eye: a soft dark gradient at the bottom (height = part of the frame)"""
    H = rgb.shape[0]
    y = np.linspace(0, 1, H)[:, None, None]
    k = 1 - amount * np.clip((y - (1 - height)) / height, 0, 1) ** 1.5
    return (rgb.astype(np.float32) * k).clip(0, 255).astype(np.uint8)


def analyze(rgb: np.ndarray) -> dict:
    import cv2
    H, W = rgb.shape[:2]
    k = 1200 / max(H, W)
    sm = cv2.resize(rgb, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(sm, cv2.COLOR_RGB2GRAY)
    fs = faces(rgb)
    lap = cv2.Laplacian(g, cv2.CV_32F)
    sharp_all = float(lap.var())
    sharp_face = None
    if fs:
        vals = []
        for x, y, w, h, _ in fs:
            x0, y0, x1, y1 = int(x * k), int(y * k), int((x + w) * k), int((y + h) * k)
            if x1 - x0 > 6 and y1 - y0 > 6:
                vals.append(float(lap[max(0, y0):y1, max(0, x0):x1].var()))
        sharp_face = max(vals) if vals else None
    mean = float(g.mean()) / 255
    clip_hi = float((g > 250).mean())
    clip_lo = float((g < 5).mean())
    sharp = sharp_face if sharp_face is not None else sharp_all
    sc = min(1.0, math.log10(1 + sharp) / 3.0) * 60
    sc += (1 - min(1, abs(mean - .45) / .4)) * 20
    sc -= min(15, clip_hi * 300) + min(8, clip_lo * 80)
    sc += 15 if fs else 0
    return {"w": W, "h": H, "sharp": round(sharp, 1), "sharp_face": sharp_face and round(sharp_face, 1),
            "bright": round(mean, 2), "clipped": round(clip_hi * 100, 1), "faces": len(fs), "score": round(sc, 1)}


def dhash(rgb: np.ndarray) -> int:
    import cv2
    g = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def pick(folder, n: int = 0, copy: bool = True) -> dict:
    """groups near-identical shots (series), keeps the best of each; n>0 -> only the n best overall"""
    files = images_in(folder)
    rows = []
    for p in files:
        try:
            rgb, _ = load(p)
        except Exception:
            continue
        a = analyze(rgb)
        a.update(path=p, hash=dhash(rgb))
        rows.append(a)
    groups = []
    for r in rows:
        for gr in groups:
            if bin(gr[0]["hash"] ^ r["hash"]).count("1") <= 12:
                gr.append(r)
                break
        else:
            groups.append([r])
    best = [max(gr, key=lambda r: r["score"]) for gr in groups]
    best.sort(key=lambda r: -r["score"])
    if n:
        best = best[:n]
    dst = Path(folder) / "best"
    if copy and best:
        dst.mkdir(exist_ok=True)
        for r in best:
            shutil.copy2(r["path"], dst / r["path"].name)
        contact_sheet([r["path"] for r in best], dst / "_preview.jpg", [f'{r["score"]:.0f}' for r in best])
    return {"total": len(rows), "groups": len(groups), "best": best, "dir": dst, "all": rows}


def _font(size):
    try:
        from .tools.images import _font as f
        return f(size, bold=False)
    except Exception:
        from PIL import ImageFont
        return ImageFont.load_default()


def contact_sheet(paths, dst, labels=None, cell=360) -> Path:
    from PIL import Image, ImageDraw
    cols = min(4, max(1, len(paths)))
    rows = math.ceil(len(paths) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(paths):
        try:
            rgb, _ = load(p)
        except Exception:
            continue
        im = Image.fromarray(rgb)
        im.thumbnail((cell - 8, cell - 26))
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(im, (x + (cell - im.width) // 2, y + 4))
        d.text((x + 6, y + cell - 20), f"{Path(p).stem}" + (f"  ★{labels[i]}" if labels else ""), fill=(230, 230, 235), font=_font(14))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst, quality=88)
    return dst


def ratio_name(r: str) -> str:
    """«сторис» / «insta» / 4x5 -> «9:16» / «4:5»"""
    r = str(r or "4:5").replace("x", ":").replace("х", ":").replace("/", ":").strip()
    names = {"insta": "4:5", "instagram": "4:5", "инста": "4:5", "инстаграм": "4:5", "feed": "4:5", "лента": "4:5",
             "story": "9:16", "stories": "9:16", "сторис": "9:16", "reels": "9:16", "рилс": "9:16", "tiktok": "9:16",
             "тикток": "9:16", "square": "1:1", "квадрат": "1:1"}
    return names.get(r.lower(), r)


def _ratio(r: str) -> float:
    a, _, b = ratio_name(r).partition(":")
    return float(a) / float(b or 1)


def crop(rgb: np.ndarray, ratio: str = "4:5") -> tuple:
    """-> (cropped, box). The biggest crop of that ratio; faces stay inside with some room above the head."""
    import cv2
    H, W = rgb.shape[:2]
    rt = _ratio(ratio)
    if W / H > rt:
        cw, ch = int(round(H * rt)), H
    else:
        cw, ch = W, int(round(W / rt))
    fs = faces(rgb)
    if fs:
        x0 = min(f[0] for f in fs); x1 = max(f[0] + f[2] for f in fs)
        y0 = min(f[1] for f in fs); y1 = max(f[1] + f[3] for f in fs)
        cx = (x0 + x1) / 2
        fh = y1 - y0
        cy = y0 + fh / 2 + ch * (.30 if fh < ch * .12 else .17)
        cy = min(cy, y0 - fh * .6 + ch / 2) if ch > fh * 3 else cy
    else:
        sm = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (W // 8 or 1, H // 8 or 1))
        e = cv2.GaussianBlur(np.abs(cv2.Laplacian(sm.astype(np.float32), cv2.CV_32F)), (0, 0), 6)
        ys, xs = np.mgrid[:e.shape[0], :e.shape[1]]
        tot = e.sum() or 1
        cx, cy = float((e * xs).sum() / tot * 8), float((e * ys).sum() / tot * 8)
        cx, cy = (cx + W / 2) / 2, (cy + H / 2) / 2
    l = int(np.clip(cx - cw / 2, 0, W - cw))
    t = int(np.clip(cy - ch / 2, 0, H - ch))
    return rgb[t:t + ch, l:l + cw].copy(), (l, t, l + cw, t + ch)


def compare(before: np.ndarray, after: np.ndarray, dst, height=900) -> Path:
    from PIL import Image, ImageDraw
    ims = []
    for a in (before, after):
        im = Image.fromarray(a)
        im = im.resize((max(1, int(im.width * height / im.height)), height), Image.LANCZOS)
        ims.append(im)
    sheet = Image.new("RGB", (ims[0].width + ims[1].width + 12, height + 30), (18, 18, 22))
    sheet.paste(ims[0], (0, 30)); sheet.paste(ims[1], (ims[0].width + 12, 30))
    d = ImageDraw.Draw(sheet)
    f = _font(18)
    d.text((8, 5), "до", fill=(220, 220, 225), font=f); d.text((ims[0].width + 20, 5), "после", fill=(220, 220, 225), font=f)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst, quality=88)
    return dst
