"""Auto-use of skills: for each request the 1–2 most relevant SKILL.md are put into the prompt by themselves.

The model never has to «remember to open a skill» (a 12b model forgets): the system picks by meaning-ish word overlap
(Russian/Polish stems + the skill's name/description weighted higher), optionally re-ranked by Ollama embeddings.
Also used for lessons (feedback.py): any list of {"name","description","body"} can be ranked with rank().
"""
import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIRS = [ROOT / "skills", ROOT / "data" / "skills"]
STOP = set("это как что где когда мне меня мой моя мои его она они там тут для или если чтобы надо можно сделай "
           "сделать пожалуйста просто ещё уже вот так все всё нет да the and for with jak czy nie się jest".split())
_cache: dict = {"t": 0.0, "items": [], "emb": {}}
MAX_BODY = 2400


def stems(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яёąćęłńóśźż0-9_+#]{3,}", (text or "").lower())
    return {w[:6] if len(w) > 6 else w for w in words if w not in STOP}


def _parse(p: Path) -> dict | None:
    t = p.read_text("utf-8", "replace")
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?(.*)$", t, re.S)
    if not m:
        return None
    meta = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    if not meta.get("name"):
        return None
    return {"name": meta["name"].strip(), "description": meta.get("description", "").strip(),
            "triggers": meta.get("triggers", ""),
            "body": m.group(2).strip(), "path": str(p), "enabled": meta.get("enabled", "true").lower() != "false"}


def index(force: bool = False) -> list[dict]:
    if not force and time.time() - _cache["t"] < 30:
        return _cache["items"]
    items, seen = [], set()
    try:
        from .skills import installed
        found = [{"name": s["name"], "description": s["description"], "body": s["body"], "path": str(s["dir"]),
                  "triggers": str((s.get("meta") or {}).get("triggers") or ""), "enabled": True} for s in installed()]
    except Exception:
        found = [s for d in SKILL_DIRS + list((ROOT / "plugins").glob("*/skills")) if d.is_dir()
                 for s in (_parse(p) for p in sorted(d.glob("*/SKILL.md"))) if s]
    for s in found:
        if True:
            if s and s["enabled"] and s["name"] not in seen:
                seen.add(s["name"])
                s["_trig"] = [stems(x) for x in s.get("triggers", "").split(",") if x.strip()]
                s["_head"] = stems(s["name"].replace("-", " ") + " " + s["description"])
                s["_body"] = stems(s["body"])
                items.append(s)
    _cache.update(t=time.time(), items=items)
    return items


def rank(items: list[dict], text: str, k: int = 2, min_score: float = 2.0) -> list[dict]:
    q = stems(text)
    if not q:
        return []
    scored = []
    for s in items:
        head = s.get("_head") or stems(s.get("name", "") + " " + s.get("description", ""))
        body = s.get("_body") or stems(s.get("body", ""))
        trig = s.get("_trig") or [stems(x) for x in s.get("triggers", "").split(",") if x.strip()]
        hits = sum(1 for t in trig if t and t <= q)
        sc = 3.0 * hits + 1.0 * len(q & head) + 0.3 * len(q & body)
        if sc >= min_score:
            scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    scored = [x for x in scored if x[0] >= 0.6 * scored[0][0]] if scored else []
    top = [s for _, s in scored[: k * 3]]
    if len(top) > k and os.environ.get("RENARD_SKILL_EMBED", "1") == "1":
        top = _rerank(top, text) or top
    return top[:k]


def _embed(text: str) -> list[float] | None:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/embed", method="POST",
                                     data=json.dumps({"model": "nomic-embed-text", "input": text[:2000]}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read())["embeddings"][0]
    except Exception:
        return None


def _rerank(cands: list[dict], text: str) -> list[dict] | None:
    qv = _embed(text)
    if not qv:
        return None
    def cos(a, b):
        return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)
    out = []
    for s in cands:
        key = s["name"] + s["description"]
        v = _cache["emb"].get(key) or _embed(s["name"] + ": " + s["description"])
        if not v:
            return None
        _cache["emb"][key] = v
        out.append((cos(qv, v), s))
    return [s for _, s in sorted(out, key=lambda x: -x[0])]


def prompt_block(text: str, k: int = 2) -> tuple[str, list[str]]:
    """Text to append to the system prompt for this request + names of the chosen skills (for the UI chip)."""
    chosen = rank(index(), text, k)
    if not chosen:
        return "", []
    parts = [f"### Навык «{s['name']}» (подобран к запросу — следуй ему)\n{s['body'][:MAX_BODY]}" for s in chosen]
    return "\n\nНАВЫКИ ДЛЯ ЭТОГО ЗАПРОСА:\n" + "\n\n".join(parts), [s["name"] for s in chosen]


def catalog() -> str:
    """One line per skill — for a «какие навыки у тебя есть» answer or the skills tab."""
    return "\n".join(f"- {s['name']}: {s['description'][:120]}" for s in index())
