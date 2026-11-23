"""Learning from corrections said in the chat itself — not only from 👎.

«включи что-нибудь спокойное» -> Renard searched the web; «нет, я имел в виду музыку» -> it played music. The second
turn is a correction: the tools it used are what the FIRST request needed. Recorded in data/corrections.jsonl
(a regression case for eval) and learned in data/learned_tools.json: toolpick then offers that tool for similar
requests right away. Nothing about the model changes; one line per learned pair, removable.
"""
import json
import re
import time

from .config import DATA_DIR
from .logs import quiet

CASES = DATA_DIR / "corrections.jsonl"
LEARNED = DATA_DIR / "learned_tools.json"
MAX_LEARNED = 300
WINDOW_S = 600
CORRECTION = re.compile(
    r"(?i)^\W*(?:нет[,.!\s]+|не то\b|не так\b|неправильно|ты не (?:так |правильно )?понял|я (?:же |ведь )?(?:просил|имел в виду|"
    r"говорил|хотел)|не это\b|не надо было|это не то|nie to\b|źle\b|nie o to|no,? i meant|not that)")
NOT_LEARNED = {"tool_search", "search_history", "remember", "memory_read", "use_skill", "look_at_screen", "web_search",
               "ask_cloud", "ask_cloud_confirm"}
LAST: dict[str, dict] = {}


def _stems(text: str) -> list[str]:
    from .archive import _stems as st
    return st(text)


def load() -> list[dict]:
    try:
        return json.loads(LEARNED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list[dict]):
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    LEARNED.write_text(json.dumps(items[-MAX_LEARNED:], ensure_ascii=False, indent=1), encoding="utf-8")


def learn(phrase: str, tool: str) -> bool:
    words = _stems(phrase)
    if len(words) < 2:
        return False
    items = load()
    for it in items:
        if it["tool"] == tool and set(it["words"]) == set(words):
            it["n"] = it.get("n", 1) + 1
            it["ts"] = time.strftime("%Y-%m-%d %H:%M")
            _save(items)
            return True
    items.append({"phrase": phrase[:200], "words": words, "tool": tool, "n": 1, "ts": time.strftime("%Y-%m-%d %H:%M")})
    _save(items)
    return True


def suggest(text: str) -> list[str]:
    """Tools learned for requests like this one: most of a learned phrase's words are in it (and at least two)."""
    words = set(_stems(text))
    if len(words) < 2:
        return []
    out = []
    for it in load():
        common = words & set(it["words"])
        if len(common) >= 2 and len(common) / max(len(it["words"]), 1) >= 0.6 and it["tool"] not in out:
            out.append(it["tool"])
    return out[:3]


def note_turn(session: str, text: str, did: list[str]) -> dict | None:
    """Called after every answer with the tools it used. Returns the recorded correction, if this turn was one."""
    rec = None
    if re.match(r"(eval|replay|wscheck|bootcheck)", session or ""):
        return None
    prev = LAST.get(session)
    try:
        if (prev and time.time() - prev["ts"] < WINDOW_S and CORRECTION.search(text) and did
                and set(did) != set(prev["did"])):
            from . import tools
            new = [t for t in dict.fromkeys(did) if t not in prev["did"] and t not in NOT_LEARNED and t in tools.REGISTRY]
            rec = {"orig": prev["text"][:300], "orig_did": prev["did"], "correction": text[:300], "fixed_did": did,
                   "learned": [t for t in new if learn(prev["text"], t)], "ts": time.strftime("%Y-%m-%d %H:%M")}
            CASES.parent.mkdir(parents=True, exist_ok=True)
            with CASES.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec["learned"]:
                from .logs import log
                log.info(f"learned from a correction: «{prev['text'][:60]}» -> {rec['learned']}")
    except Exception:
        quiet()
    LAST[session] = {"text": text, "did": list(dict.fromkeys(did)), "ts": time.time(),
                     "corr": bool(CORRECTION.search(text)) and bool(prev) and time.time() - prev["ts"] < WINDOW_S}
    return rec


def second_correction(session: str, text: str) -> bool:
    """He corrects it AGAIN (the previous turn was already a correction): the local model is not getting it."""
    prev = LAST.get(session)
    return bool(CORRECTION.search(text) and prev and prev.get("corr") and time.time() - prev["ts"] < WINDOW_S)


def forget(tool: str = "", phrase: str = "") -> int:
    items = load()
    keep = [it for it in items if not ((not tool or it["tool"] == tool) and (not phrase or phrase.lower() in it["phrase"].lower()))]
    _save(keep)
    return len(items) - len(keep)
