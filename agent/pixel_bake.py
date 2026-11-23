"""The pixel chibi of ANY 3D model: the current VRM is rendered in a hidden browser (big head = chibi proportions), each
pose is shot with a transparent background and turned into crisp pixel art (agent/pixelize.py: shared palette, «most
common colour» per pixel instead of a blurry shrink, selective outline) — a sprite sheet for the pixel companion
(idle / wave / walk / sit / sleep), saved next to the uploaded ones (avatars/pixel/<name>.png).
The raw shots are kept in avatars/pixel/_raw/<name>/ so the sheet can be remade without rendering again.
  python -m agent.pixel_bake [model.vrm]     bake the current (or that) model
  python -m agent.pixel_bake --again <name>  remake <name> from its raw shots
"""
import asyncio
import io
import json
import re
import sys
from pathlib import Path

from .config import DATA_DIR

BASE = "http://127.0.0.1:8790"
VIEW_W, VIEW_H = 420, 560
PIX = DATA_DIR / "avatars" / "pixel"
POSES = [
    ("idle", "nx.setMode('stand'); nx.clips && nx.clips.stop(.1); nx.gesture = null; nx.idle = null; nx.idleNext = 1e12", [3200, 700]),
    ("wave", "nx.setMode('stand'); nx.act('wave', {user: true})", [500, 350, 350, 350]),
    ("walk", "nx.face(1); nx.walkSpeed = 90; nx.setMode('walk')", [1200, 140, 140, 140, 140, 140]),
    ("sit", "nx.setMode('sit')", [2200, 900]),
    ("sleep", "nx.setMode('sleep')", [2600, 1200]),
]


async def _shots(model: str = "") -> dict:
    from playwright.async_api import async_playwright
    out = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chrome", headless=True, args=["--use-gl=angle"])
        p = await b.new_page(viewport={"width": VIEW_W, "height": VIEW_H})
        from urllib.parse import quote
        await p.goto(BASE + "/app/companion.html" + (f"?bake={quote(model)}" if model.endswith(".vrm") else ""))
        await p.wait_for_timeout(500)
        await p.evaluate("window.nxNoAuto = true; nx && (nx.idleNext = 1e12)")
        await p.wait_for_timeout(6000)
        await p.add_style_tag(content="html,body{background:transparent !important} .bubble,.menu{display:none !important}")
        ok = await p.evaluate("!!(window.nx && nx.vrm)")
        if not ok:
            await b.close()
            raise RuntimeError("3D-модель не загрузилась (выбрана 2D-картинка?)")
        await p.evaluate("""(() => {
          const h = nx.vrm.humanoid.getRawBoneNode('head'); if (h) h.scale.setScalar(1.85);
          nx.cam.fov = 12; nx.cam.position.set(0, 1.0, 10.5); nx.cam.lookAt(0, .95, 0); nx.cam.updateProjectionMatrix();
          window.nxBakeHips = () => { const v = nx.vrm.humanoid.getNormalizedBoneNode('hips').getWorldPosition(nx.cam.position.clone());
            v.project(nx.cam); return [(v.x + 1) / 2 * innerWidth, (1 - v.y) / 2 * innerHeight]; };
        })()""")
        for name, js, delays in POSES:
            await p.evaluate(js)
            frames, hips = [], None
            for d in delays:
                await p.wait_for_timeout(d)
                await p.evaluate("nx.cam.position.set(0, 1.0, 10.5); nx.cam.lookAt(0, .95, 0)")
                frames.append(await p.screenshot(omit_background=True))
                hips = await p.evaluate("nxBakeHips()")
            out[name] = {"frames": frames, "hips": hips}
            await p.evaluate("nx.setMode('stand')")
            await p.wait_for_timeout(500)
        await b.close()
    return out


def _save_raw(stem: str, shots: dict):
    d = PIX / "_raw" / stem
    d.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, v in shots.items():
        for i, f in enumerate(v["frames"]):
            (d / f"{name}_{i}.png").write_bytes(f)
        meta[name] = {"n": len(v["frames"]), "hips": v["hips"]}
    (d / "shots.json").write_text(json.dumps(meta), encoding="utf-8")


def _load_raw(stem: str) -> dict:
    d = PIX / "_raw" / stem
    meta = json.loads((d / "shots.json").read_text(encoding="utf-8"))
    return {name: {"frames": [(d / f"{name}_{i}.png").read_bytes() for i in range(m["n"])], "hips": m["hips"]}
            for name, m in meta.items()}


def _process(shots: dict, height: int = 46) -> tuple:
    from PIL import Image
    from .pixelize import enhance, make_palette, pixelize
    imgs = {k: [Image.open(io.BytesIO(f)).convert("RGBA") for f in v["frames"]] for k, v in shots.items()}
    bb = imgs["idle"][0].getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
    if not bb:
        raise RuntimeError("пустой кадр")
    k = height / (bb[3] - bb[1])
    allbb = None
    for fl in imgs.values():
        for im in fl:
            b2 = im.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
            if b2:
                allbb = b2 if not allbb else (min(allbb[0], b2[0]), min(allbb[1], b2[1]), max(allbb[2], b2[2]), max(allbb[3], b2[3]))
    cx = (bb[0] + bb[2]) / 2
    pad = 1 / k
    half = max(cx - allbb[0], allbb[2] - cx) + 2 + pad
    top, bot = allbb[1] - 2 - pad, bb[3] + pad
    fw = int(round(2 * half * k))
    fh = int(round((bot - top) * k))
    crops = {name: [enhance(im.crop((int(cx - half), int(top), int(cx + half), int(bot)))) for im in fl]
             for name, fl in imgs.items()}
    pal = make_palette([c for fl in crops.values() for c in fl], 28)
    cols = max(len(v) for v in crops.values())
    sheet = Image.new("RGBA", (fw * cols, fh * len(crops)))
    anims = {}
    for r, (name, fl) in enumerate(crops.items()):
        for i, c in enumerate(fl):
            sheet.paste(pixelize(c, (fw, fh), pal), (i * fw, r * fh))
        a_meta = {"row": r, "frames": len(fl)}
        if name in ("sit", "sleep") and shots[name].get("hips"):
            a_meta["seat"] = int(round((shots[name]["hips"][1] - top) * k))
        if name == "walk":
            a_meta["fps"] = 8
        anims[name] = a_meta
    meta = {"frame_w": fw, "frame_h": fh, "fps": 4, "seat": fh - 1, "anims": anims, "baked_from": ""}
    return sheet, meta


def _title(model: str) -> str:
    try:
        return json.loads((DATA_DIR / "avatars" / "thumbs" / (Path(model).stem + ".json")).read_text(encoding="utf-8")).get("title", "")
    except Exception:
        return ""


def _write(stem: str, sheet, meta: dict, model: str) -> dict:
    meta["baked_from"] = str(model)
    meta["title"] = _title(model)
    PIX.mkdir(parents=True, exist_ok=True)
    sheet.save(PIX / f"{stem}.png")
    (PIX / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"name": stem, **meta}


def bake(name: str = "", height: int = 46, model: str = "") -> dict:
    from .prefs import get as pget
    c = pget("companion", {}) or {}
    model = model or c.get("vrm") or c.get("file") or "model"
    stem = re.sub(r"[^\w\-]+", "_", "px_" + Path(str(name or model)).stem)[:40]
    shots = asyncio.run(_shots(model))
    _save_raw(stem, shots)
    sheet, meta = _process(shots, height)
    return _write(stem, sheet, meta, model)


def again(stem: str, height: int = 46) -> dict:
    old = json.loads((PIX / f"{stem}.json").read_text(encoding="utf-8")) if (PIX / f"{stem}.json").exists() else {}
    sheet, meta = _process(_load_raw(stem), height)
    return _write(stem, sheet, meta, old.get("baked_from", ""))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["--again"]:
        print(again(sys.argv[2]))
    else:
        print(bake(model=sys.argv[1] if len(sys.argv) > 1 else ""))
