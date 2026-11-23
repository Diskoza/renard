"""Separate process for ruaccent (stress + ё for Russian): it needs ~2.4 GB of RAM, so it lives only while Renard
speaks (ru_stress starts it and stops it after a few idle minutes). Protocol: one JSON line in {"text": …} -> one JSON
line out {"text": «з+амок …»} or {"error": …}. First line out: {"ready": true}."""
import json
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    from ruaccent import RUAccent
    m = RUAccent()
    m.load(omograph_model_size="turbo3.1", use_dictionary=True)
    am = m.accent_model
    real_run = am.session.run
    need = {i.name for i in am.session.get_inputs()}

    def run(out, feed, *a, **kw):
        if "token_type_ids" in need and "token_type_ids" not in feed and "input_ids" in feed:
            import numpy as np
            feed = {**feed, "token_type_ids": np.zeros_like(feed["input_ids"])}
        return real_run(out, feed, *a, **kw)
    am.session.run = run
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            text = json.loads(line)["text"]
            print(json.dumps({"text": m.process_all(text)}, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"error": f"{type(e).__name__}: {e}"}), flush=True)


if __name__ == "__main__":
    main()
