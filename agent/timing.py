"""Where an answer's time goes: route / study / vram check / prompt / tool pick / each model step / each tool.

One Trace per request (a contextvar, so tools.call and the model stream add to it without passing it around).
Written to data/logs/timing.jsonl (one line per answer) and sent to the window as {"type": "timing"}.
"""
import contextvars
import json
import time
from contextlib import contextmanager

from .config import DATA_DIR
from .logs import quiet

PATH = DATA_DIR / "logs" / "timing.jsonl"
MAX_BYTES = 5_000_000
CURRENT: contextvars.ContextVar = contextvars.ContextVar("renard_trace", default=None)


class Trace:
    def __init__(self, text: str, session: str):
        self.text, self.session = text[:120], session
        self.t0 = time.perf_counter()
        self.ts = time.time()
        self.spans: list[dict] = []
        self.info: dict = {}

    def add(self, name: str, seconds: float, **extra):
        self.spans.append({"name": name, "s": round(seconds, 3), **extra})

    @contextmanager
    def span(self, name: str, **extra):
        t = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, time.perf_counter() - t, **extra)

    def total(self) -> float:
        return time.perf_counter() - self.t0

    def summary(self) -> dict:
        by: dict[str, float] = {}
        for s in self.spans:
            key = s["name"].split(":")[0]
            by[key] = round(by.get(key, 0) + s["s"], 3)
        total = round(self.total(), 3)
        by["other"] = round(max(0.0, total - sum(v for k, v in by.items())), 3)
        return {"total": total, "by": by}

    def record(self) -> dict:
        return {"ts": round(self.ts), "session": self.session, "text": self.text, **self.info, **self.summary(),
                "spans": self.spans}


def current() -> "Trace | None":
    return CURRENT.get()


@contextmanager
def span(name: str, **extra):
    """No-op outside a request (tests, background jobs)."""
    tr = CURRENT.get()
    if tr is None:
        yield
        return
    with tr.span(name, **extra):
        yield


def save(tr: Trace):
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        if PATH.exists() and PATH.stat().st_size > MAX_BYTES:
            PATH.replace(PATH.with_suffix(".1.jsonl"))
        with PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(tr.record(), ensure_ascii=False) + "\n")
    except Exception:
        quiet()


def load(limit: int = 200) -> list[dict]:
    if not PATH.exists():
        return []
    out = []
    for line in PATH.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def report(rows: list[dict]) -> dict:
    """Averages over the last answers: which stage eats the time (the window's «Здоровье» page, eval reports)."""
    if not rows:
        return {"n": 0}
    stages: dict[str, list] = {}
    for r in rows:
        for k, v in (r.get("by") or {}).items():
            stages.setdefault(k, []).append(v)
    totals = sorted(r.get("total", 0) for r in rows)
    slow = sorted(rows, key=lambda r: -r.get("total", 0))[:5]
    return {"n": len(rows),
            "median": totals[len(totals) // 2],
            "p90": totals[min(len(totals) - 1, int(len(totals) * 0.9))],
            "avg_by": {k: round(sum(v) / len(rows), 2) for k, v in sorted(stages.items(), key=lambda kv: -sum(kv[1]))},
            "slowest": [{"text": r.get("text"), "total": r.get("total"), "by": r.get("by")} for r in slow]}
