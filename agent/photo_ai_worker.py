"""AI repaint of one area of a photo (Stable Diffusion XL inpainting on the GPU). Runs in its own venv
(%USERPROFILE%\\photo-ai\\venv: torch + diffusers), started by agent/tools/photo.py — never imports the agent.

  python photo_ai_worker.py job.json

job: {"image", "mask" (white = repaint) | "box" [x0,y0,x1,y1], "mode": fix|remove|replace|detail, "prompt", "neg",
      "strength", "n", "steps", "out_dir", "name", "status"}
Only a square around the mask is repainted (1024 px for the model) and pasted back with a soft edge, so the rest of
the photo keeps its full resolution and is untouched. Progress -> job["status"] (json)."""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

NEG = ("blurry, motion blur, ghosting, double exposure, transparent, extra fingers, fused fingers, deformed hand, "
       "missing fingers, deformed face, lowres, cartoon, painting, illustration, text, watermark")
MODES = {
    "fix": (0.85, 35, "photo, natural, realistic, sharp focus"),
    "replace": (0.99, 35, "photo, realistic, sharp focus"),
    "remove": (0.80, 35, "empty background, seamless continuation of the surroundings, nothing there, photo"),
    "detail": (0.35, 30, "photo, sharp focus, fine natural detail"),
}


def imread(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)


def imwrite(p, img, q=95):
    ok, buf = cv2.imencode(Path(p).suffix or ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    buf.tofile(str(p))


def main(job_path):
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    st_path = Path(job["status"])

    def status(**kw):
        cur = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}
        cur.update(kw, t=time.time())
        st_path.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")

    status(state="loading")
    img = imread(job["image"])
    H, W = img.shape[:2]
    if job.get("mask"):
        mask = cv2.imdecode(np.fromfile(job["mask"], np.uint8), cv2.IMREAD_UNCHANGED)
        if mask.ndim == 3:
            mask = mask[..., 3] if mask.shape[2] == 4 else cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)
        mask = np.where(mask > 20, 255, 0).astype(np.uint8)
    else:
        x0, y0, x1, y1 = [int(v) for v in job["box"]]
        mask = np.zeros((H, W), np.uint8)
        cv2.ellipse(mask, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 255, -1)
    if not mask.any():
        status(state="error", error="маска пустая")
        return
    mode = job.get("mode", "fix")
    strength, steps, prefix = MODES.get(mode, MODES["fix"])
    strength = float(job.get("strength") or strength)
    d = max(9, int(min(H, W) * .012)) | 1
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d)))
    ys, xs = np.where(mask > 0)
    bw, bh = xs.max() - xs.min(), ys.max() - ys.min()
    S = int(min(min(H, W), max(768, max(bw, bh) * 1.7)))
    cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
    x0 = int(np.clip(cx - S // 2, 0, W - S)); y0 = int(np.clip(cy - S // 2, 0, H - S))
    ci = img[y0:y0 + S, x0:x0 + S].copy()
    cm = mask[y0:y0 + S, x0:x0 + S]
    src = ci
    if mode == "remove":
        src = cv2.inpaint(ci, cm, 9, cv2.INPAINT_TELEA)
    from PIL import Image
    dry = bool(job.get("dry"))
    if dry:
        free, pipe = 0.0, None
    else:
        import torch
        from diffusers import AutoPipelineForInpainting
        free = torch.cuda.mem_get_info()[0] / 2 ** 30 if torch.cuda.is_available() else 0
        pipe = AutoPipelineForInpainting.from_pretrained("diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
                                                         torch_dtype=torch.float16, variant="fp16")
        if free >= 8.5:
            pipe = pipe.to("cuda")
        else:
            pipe.enable_model_cpu_offload()
        pipe.enable_attention_slicing()
        try:
            pipe.vae.enable_tiling()
        except Exception:
            pass
    pi = Image.fromarray(cv2.cvtColor(cv2.resize(src, (1024, 1024), interpolation=cv2.INTER_AREA if S > 1024 else cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB))
    pm = Image.fromarray(cv2.resize(cm, (1024, 1024), interpolation=cv2.INTER_NEAREST))
    a = cv2.GaussianBlur(cm, (0, 0), max(3, S / 160)).astype(np.float32)[..., None] / 255
    prompt = ", ".join(x for x in (job.get("prompt", "").strip(), prefix) if x)
    neg = ", ".join(x for x in (job.get("neg", "").strip(), NEG) if x)
    n = int(job.get("n", 3))
    out_dir = Path(job["out_dir"]); out_dir.mkdir(parents=True, exist_ok=True)
    outs, crops = [], []
    for k in range(n):
        status(state="running", done=k, n=n, vram_free=round(free, 1))
        if dry:
            r = pi
        else:
            g = torch.Generator("cpu").manual_seed(int(job.get("seed", 1000)) + k)
            r = pipe(prompt=prompt, negative_prompt=neg, image=pi, mask_image=pm, strength=strength, guidance_scale=7.0,
                     num_inference_steps=int(job.get("steps") or steps), generator=g).images[0]
        r = cv2.resize(cv2.cvtColor(np.array(r), cv2.COLOR_RGB2BGR), (S, S), interpolation=cv2.INTER_LANCZOS4)
        blend = (r * a + ci * (1 - a)).astype(np.uint8)
        out = img.copy(); out[y0:y0 + S, x0:x0 + S] = blend
        p = out_dir / f'{job["name"]}_ai{k + 1}.jpg'
        imwrite(p, out)
        outs.append(str(p))
        crops.append(cv2.resize(blend, (420, 420)))
    sheet = np.concatenate([cv2.resize(ci, (420, 420))] + crops, 1)
    imwrite(out_dir / f'{job["name"]}_ai_variants.jpg', sheet, 90)
    status(state="done", done=n, n=n, outputs=outs, sheet=str(out_dir / f'{job["name"]}_ai_variants.jpg'))


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as e:
        job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        Path(job["status"]).write_text(json.dumps({"state": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), encoding="utf-8")
        raise
