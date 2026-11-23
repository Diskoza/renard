"""Companion avatars: 3D .vrm and 2D images (png/gif/webp/jpg/svg) in data/avatars.
Thumbnails: VRM files carry one inside (meta.thumbnailImage / meta.texture) — extracted on demand; if a model has
none, the UI renders a snapshot and uploads it."""
import json
import struct
from pathlib import Path

from .config import DATA_DIR
from .logs import quiet

DIR = DATA_DIR / "avatars"
THUMBS = DIR / "thumbs"
DIR.mkdir(exist_ok=True)
THUMBS.mkdir(exist_ok=True)
IMG2D = {".png", ".gif", ".webp", ".jpg", ".jpeg", ".svg"}


def vrm_thumbnail(path: Path) -> bytes | None:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        return None
    off, js, binc = 12, None, None
    while off < len(data):
        ln, typ = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + ln]
        if typ == 0x4E4F534A:
            js = json.loads(chunk)
        elif typ == 0x004E4942:
            binc = chunk
        off += 8 + ln
    if not js or binc is None:
        return None
    ext = js.get("extensions", {})
    img = None
    if "VRMC_vrm" in ext:
        img = ext["VRMC_vrm"].get("meta", {}).get("thumbnailImage")
    elif "VRM" in ext:
        tex = ext["VRM"].get("meta", {}).get("texture")
        if tex is not None and tex >= 0:
            img = js["textures"][tex].get("source")
    if img is None:
        return None
    bv = js["bufferViews"][js["images"][img]["bufferView"]]
    o = bv.get("byteOffset", 0)
    return binc[o: o + bv["byteLength"]]


def vrm_title(path: Path) -> str:
    """Model name from VRM meta (VRM0: meta.title, VRM1: meta.name), cached next to the thumbnail."""
    cache = THUMBS / (path.stem + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")).get("title", "")
    title = ""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
            ln = struct.unpack_from("<I", head, 12)[0]
            js = json.loads(f.read(ln))
        ext = js.get("extensions", {})
        meta = ext.get("VRMC_vrm", {}).get("meta") or ext.get("VRM", {}).get("meta") or {}
        title = (meta.get("name") or meta.get("title") or "").strip()
    except Exception:
        quiet()
    cache.write_text(json.dumps({"title": title}, ensure_ascii=False), encoding="utf-8")
    return title


def thumb_path(name: str) -> Path:
    return THUMBS / (Path(name).stem + ".png")


def listing() -> list[dict]:
    out = []
    for p in sorted(DIR.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext == ".vrm":
            t = thumb_path(p.name)
            if not t.exists():
                try:
                    b = vrm_thumbnail(p)
                    if b:
                        import io
                        from PIL import Image
                        im = Image.open(io.BytesIO(b)).convert("RGBA")
                        im.thumbnail((320, 320))
                        im.save(t, "PNG")
                except Exception:
                    quiet()
            out.append({"name": p.name, "kind": "vrm", "title": vrm_title(p) or p.stem,
                        "thumb": f"/avatars/thumbs/{t.name}" if t.exists() else None})
        elif ext in IMG2D:
            out.append({"name": p.name, "kind": "2d", "title": p.stem, "thumb": f"/avatars/{p.name}"})
        elif ext == ".glb":
            t = thumb_path(p.name)
            out.append({"name": p.name, "kind": "robot", "title": p.stem.replace("_", " "),
                        "thumb": f"/avatars/thumbs/{t.name}" if t.exists() else None})
    return out
