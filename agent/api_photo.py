"""Routes of the photo brush window (web/app/photo_mask.html): show a photo, save the painted mask next to it."""
import base64
import io
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response


def routes(r: APIRouter) -> None:
    @r.get("/photo/file")
    def photo_file(path: str):
        """the photo for the brush window: rotated like the phone shot it, at most 2400 px (the mask is scaled back)"""
        from .photo import EXT, load
        from .tools.files import safe
        from PIL import Image
        p = safe(path)
        if p.suffix.lower() not in EXT or not p.exists():
            return JSONResponse({"error": "не фото"}, 404)
        rgb, _ = load(p)
        im = Image.fromarray(rgb)
        im.thumbnail((2400, 2400))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        return Response(buf.getvalue(), media_type="image/jpeg",
                        headers={"X-Width": str(rgb.shape[1]), "X-Height": str(rgb.shape[0])})

    @r.post("/photo/mask")
    async def photo_mask_save(req: Request):
        from PIL import Image
        from .tools.files import safe
        from .tools.photo import mask_path
        b = await req.json()
        src = safe(b.get("path", ""))
        data = str(b.get("png", "")).split(",", 1)[-1]
        im = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")
        from .photo import load
        rgb, _ = load(src)
        a = im.getchannel("A").point(lambda v: 255 if v > 20 else 0)
        a = a.resize((rgb.shape[1], rgb.shape[0]), Image.NEAREST)
        if not a.getbbox():
            return JSONResponse({"error": "ничего не закрашено"}, 400)
        dst = mask_path(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        a.save(dst)
        return {"ok": True, "mask": str(dst)}
