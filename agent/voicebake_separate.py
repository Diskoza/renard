"""Runs INSIDE data/voiceclone/venv (torch + demucs): the voice out of music, effects and noise (Demucs htdemucs,
the «vocals» stem), for the phrases of a voice bake recorded from a show or a game.
    python voicebake_separate.py <pairs.json: [[src.wav, dst.wav], …]> <progress.json>
The model is loaded once for all phrases; GPU when there is one. dst = mono 44.1 kHz float wav."""
import json
import sys
import time


def main():
    pairs = json.load(open(sys.argv[1], encoding="utf-8"))
    progress = sys.argv[2]
    import soundfile as sf
    import torch
    import torchaudio.functional as AF
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = get_model("htdemucs")
    model.to(dev).eval()
    sr, voc = model.samplerate, model.sources.index("vocals")
    for k, (src, dst) in enumerate(pairs):
        a, r = sf.read(src, dtype="float32", always_2d=True)
        x = torch.from_numpy(a.T.copy())
        if r != sr:
            x = AF.resample(x, r, sr)
        if x.shape[0] == 1:
            x = x.repeat(2, 1)
        ref = x.mean(0)
        mean, std = float(ref.mean()), float(ref.std()) + 1e-8
        with torch.no_grad():
            out = apply_model(model, ((x - mean) / std)[None].to(dev), shifts=1, split=True, overlap=0.25,
                              progress=False)[0]
        v = (out[voc] * std + mean).mean(0).cpu().numpy()
        sf.write(dst, v, sr, subtype="FLOAT")
        if k % 10 == 0 or k == len(pairs) - 1:
            with open(progress, "w", encoding="utf-8") as f:
                json.dump({"stage": "separate", "done": k + 1, "total": len(pairs), "ts": time.time()}, f)


if __name__ == "__main__":
    main()
