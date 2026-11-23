"""Big picture -> crisp pixel art (used by the 3D-model chibi bake and by uploads of your own chibi).

Not a blurry shrink: the big image is reduced to one shared palette first (a bit more colourful and contrasty), then every
small pixel takes the most common colour of its block (dark colours weigh more, so eyes / lines survive), small specks
are cleaned up and a 1-px outline is added in a darkened colour of the pixel next to it (selective outline)."""
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

SUB = 6


def enhance(im: Image.Image, color=1.3, contrast=1.12, bright=1.06) -> Image.Image:
    """+colour/contrast; also heals see-through hair strands (alpha holes) and smooths render noise"""
    a = im.getchannel("A").point(lambda v: 255 if v > 30 else 0)
    a = a.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    rgb = Image.new("RGB", im.size)
    rgb.paste(im.convert("RGB"), mask=im.getchannel("A").point(lambda v: 255 if v > 30 else 0))
    filled = rgb.filter(ImageFilter.MaxFilter(5))
    rgb = Image.composite(rgb, filled, im.getchannel("A").point(lambda v: 255 if v > 30 else 0))
    rgb = rgb.filter(ImageFilter.MedianFilter(5))
    rgb = ImageEnhance.Color(rgb).enhance(color)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Brightness(rgb).enhance(bright)
    out = rgb.convert("RGBA"); out.putalpha(a)
    return out


def make_palette(images, colors=28) -> Image.Image:
    """one palette for a whole sheet (from the opaque pixels of all frames)"""
    pix = []
    for im in images:
        a = np.asarray(im.getchannel("A")) > 128
        rgb = np.asarray(im.convert("RGB"))[a]
        if len(rgb):
            pix.append(rgb[:: max(1, len(rgb) // 40000)])
    allpix = np.concatenate(pix) if pix else np.zeros((1, 3), np.uint8)
    strip = Image.fromarray(allpix.reshape(1, -1, 3).astype(np.uint8), "RGB")
    return strip.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, kmeans=2)


def _pal_rgb(pal: Image.Image) -> np.ndarray:
    p = np.array(pal.getpalette()[: 256 * 3], dtype=np.int32).reshape(-1, 3)
    return p


def pixelize(im: Image.Image, size: tuple, pal: Image.Image, cover=.45, outline=True) -> Image.Image:
    """im: RGBA crop already framed; size: (w, h) of the result."""
    w, h = size
    big = im.resize((w * SUB, h * SUB), Image.LANCZOS)
    alpha = np.asarray(big.getchannel("A")).astype(np.float32) / 255
    q = big.convert("RGB").quantize(palette=pal, dither=Image.Dither.NONE)
    idx = np.asarray(q).astype(np.int32)
    prgb = _pal_rgb(pal)
    ncol = int(idx.max()) + 1
    lum = prgb[:ncol] @ np.array([.3, .59, .11])
    weight = 1 + .8 * (lum < np.percentile(lum, 25))
    blk_i = idx.reshape(h, SUB, w, SUB).transpose(0, 2, 1, 3).reshape(h, w, SUB * SUB)
    blk_a = alpha.reshape(h, SUB, w, SUB).transpose(0, 2, 1, 3).reshape(h, w, SUB * SUB)
    opaque = blk_a > .5
    counts = np.zeros((ncol, h, w), np.float32)
    for k in range(ncol):
        counts[k] = ((blk_i == k) & opaque).sum(-1) * weight[k]
    best = counts.argmax(0)
    cov = opaque.mean(-1)
    solid = cov >= cover
    nb = np.zeros_like(cov)
    padded = np.pad(solid, 1)
    for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
        nb += padded[dy:dy + h, dx:dx + w]
    solid = (solid & (nb > 0)) | (~solid & (nb >= 3) & (cov > .2))
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = prgb[best].clip(0, 255)
    out[..., 3] = np.where(solid, 255, 0)
    if outline:
        sol = solid.copy()
        pad_s = np.pad(sol, 1)
        pad_c = np.pad(out[..., :3].astype(np.int32), ((1, 1), (1, 1), (0, 0)))
        for y in range(h):
            for x in range(w):
                if sol[y, x]:
                    continue
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if pad_s[y + 1 + dy, x + 1 + dx]:
                        c = pad_c[y + 1 + dy, x + 1 + dx]
                        out[y, x, :3] = (c * .38 + np.array([10, 8, 22]) * .62).astype(np.uint8)
                        out[y, x, 3] = 255
                        break
    return Image.fromarray(out, "RGBA")


def single(im: Image.Image, height=46, colors=28) -> Image.Image:
    """your own picture (any size) -> one pixel chibi frame, `height` px tall (pixel art already small enough stays as is)"""
    im = im.convert("RGBA")
    bb = im.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox() or (0, 0, *im.size)
    im = im.crop(bb)
    if im.height <= 96:
        return im
    w = max(4, round(im.width * height / im.height))
    e = enhance(im)
    return pixelize(e, (w, height), make_palette([e], colors))
