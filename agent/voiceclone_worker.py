"""Voice cloning worker: runs in its OWN venv (data/voiceclone/venv: torch + OmniVoice, k2-fsa, Apache-2.0), so the
agent's venv stays light. One JSON line in -> one JSON line out (stdin / stdout):
  {"op": "synth", "text": "...", "ref": "data/voices/clone/<name>/ref.wav", "ref_text": "...", "out": "x.wav",
   "lang": "ru", "speed": 1.0, "steps": 16}
  {"op": "ping"} / {"op": "quit"}
The model loads on the first synth: on the GPU when ~2.5 GB are free (a game or the LLM may hold the rest), else on the CPU.
Killing this process frees all its memory — the agent stops it after a few idle minutes.
"""
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TORCH_DISTRIBUTED_DEBUG", "OFF")
MODEL = os.environ.get("NX_CLONE_MODEL", "k2-fsa/OmniVoice")
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
out = sys.stdout
sys.stdout = sys.stderr

model, device, prompts = None, "", {}


def load(prefer: str = "auto"):
    global model, device
    import torch
    from omnivoice import OmniVoice
    dev = "cpu"
    if prefer != "cpu" and torch.cuda.is_available():
        free, _ = torch.cuda.mem_get_info()
        if free > 2.5e9 or prefer == "cuda":
            dev = "cuda:0"
    t0 = time.time()
    model = OmniVoice.from_pretrained(MODEL, device_map=dev, dtype=torch.float16 if dev != "cpu" else torch.float32)
    device = dev
    return round(time.time() - t0, 1)


def synth(job: dict) -> dict:
    import numpy as np
    import soundfile as sf
    from omnivoice import OmniVoiceGenerationConfig
    info = {}
    if model is None:
        info["load_s"] = load(job.get("device", "auto"))
    key = (job["ref"], os.path.getmtime(job["ref"]))
    if key not in prompts:
        prompts.clear()
        prompts[key] = model.create_voice_clone_prompt(ref_audio=job["ref"], ref_text=job.get("ref_text") or None)
    t0 = time.time()
    cfg = OmniVoiceGenerationConfig(num_step=int(job.get("steps", 16)))
    audio = model.generate(text=job["text"], language=job.get("lang") or None, voice_clone_prompt=prompts[key],
                           speed=float(job.get("speed") or 1.0), generation_config=cfg)
    a = np.asarray(audio[0], dtype=np.float32).reshape(-1)
    sf.write(job["out"], a, 24000, subtype="PCM_16")
    return {"ok": True, "out": job["out"], "sec": round(len(a) / 24000, 2), "gen_s": round(time.time() - t0, 2),
            "device": device, **info}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            op = job.get("op")
            if op == "quit":
                break
            res = {"ok": True, "device": device} if op == "ping" else synth(job) if op == "synth" else {"ok": False, "error": f"op {op}?"}
        except Exception as e:
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        out.write(json.dumps(res, ensure_ascii=False) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
