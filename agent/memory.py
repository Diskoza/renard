"""Memory: (1) chat history in SQLite + FTS5 search, (2) markdown notes with a short index.

Notes live in data/memory/*.md. First line after '# ' is used as the description in the index.
Only the index + explicitly read notes go into the prompt — never the whole memory.
"""
import re
import sqlite3
import time
from pathlib import Path

from .config import DATA_DIR, MEMORY_DIR
from .logs import quiet

DB_PATH = DATA_DIR / "agent.sqlite3"

_WD = {"понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресень": 6,
       "poniedział": 0, "wtor": 1, "środ": 2, "czwart": 3, "piąt": 4, "sobot": 5, "niedziel": 6}
_WD_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def resolve_dates(fact: str, now: float | None = None) -> str:
    """«справдзиан в пятницу» said on Wed 04.11 -> «… в пятницу (пт 06.11.2026)»: a remembered relative day must stay
    true next week too."""
    import datetime as dt
    today = dt.date.fromtimestamp(now or time.time())
    low = fact.lower()
    target = None
    if re.search(r"\bпослезавтра\b|\bpojutrze", low):
        target = today + dt.timedelta(days=2)
    elif re.search(r"\bзавтра\b|\bjutro\b", low):
        target = today + dt.timedelta(days=1)
    elif re.search(r"\bсегодня\b|\bdzisiaj\b|\bdziś\b", low):
        target = today
    else:
        m = re.search(r"\b(?:в|во|на|w|we)\s+(?:следующ\w+\s+|przysz\w+\s+)?(" + "|".join(_WD) + r")\w*", low)
        if m:
            wd = next(v for k, v in _WD.items() if m.group(1).startswith(k))
            ahead = (wd - today.weekday()) % 7 or 7
            if re.search(r"следующ|przysz", m.group(0)) and ahead < 7:
                ahead += 7
            target = today + dt.timedelta(days=ahead)
    if target and not re.search(r"\d{1,2}\.\d{1,2}", fact):
        fact += f" ({_WD_NAMES[target.weekday()]} {target:%d.%m.%Y})"
    return fact


DEFAULT_NOTES = {
    "profile.md": "# Кто пользователь\n",
    "preferences.md": "# Как пользователь хочет, чтобы агент работал\n",
    "notes.md": "# Разное, что попросили запомнить\n",
}


class Memory:
    def __init__(self, db_path: Path = DB_PATH, notes_dir: Path = MEMORY_DIR):
        self.notes_dir = notes_dir
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        for name, head in DEFAULT_NOTES.items():
            p = self.notes_dir / name
            if not p.exists():
                p.write_text(head, encoding="utf-8")
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY, ts REAL, session TEXT, role TEXT, content TEXT, mode TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content='messages', content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TABLE IF NOT EXISTS mem_sources(note TEXT, line TEXT, session TEXT, ts REAL);
            """
        )
        self.db.commit()

    def add(self, session: str, role: str, content: str, mode: str = ""):
        self.db.execute("INSERT INTO messages(ts, session, role, content, mode) VALUES (?,?,?,?,?)",
                        (time.time(), session, role, content, mode))
        self.db.commit()

    def recent(self, session: str, n: int = 10) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content FROM messages WHERE session=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT ?",
            (session, n)).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def search_history(self, query: str, limit: int = 8, exclude_session: str = "") -> list[dict]:
        """Past Renard chats. A hit must contain the query's rarest word (the topic: «samba», not «настраивал»),
        and the chat we are in right now is skipped (it would just find the question itself)."""
        from .archive import _stems
        words = _stems(query)
        if not words:
            return []

        def count(w):
            try:
                return self.db.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?", (f'"{w}"*',)).fetchone()[0]
            except sqlite3.OperationalError:
                return 0
        key = min(words, key=count)
        if not count(key):
            return []
        try:
            rows = self.db.execute(
                "SELECT m.ts, m.role, m.content FROM messages_fts f JOIN messages m ON m.id=f.rowid "
                "WHERE messages_fts MATCH ? AND m.session != ? AND m.session NOT LIKE 'eval-%' AND m.session NOT LIKE 'arc1%' "
                "AND m.session NOT IN ('wscheck', 'bootcheck') ORDER BY rank LIMIT ?",
                (" OR ".join(f'"{w}"*' for w in words), exclude_session or "", limit * 4)).fetchall()
        except sqlite3.OperationalError:
            return []
        out, seen = [], set()
        for t, r, c in rows:
            low = c.lower().replace("ё", "е")
            i = low.find(key)
            if i < 0:
                continue
            s = max(0, i - 150)
            sig = re.sub(r"\W+", " ", low[s:s + 400]).strip()
            if sig in seen:
                continue
            seen.add(sig)
            out.append({"date": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)), "role": r,
                        "text": ("…" if s else "") + c[s:s + 400]})
            if len(out) >= limit:
                break
        return out

    def _safe_note(self, name: str) -> Path:
        name = Path(name).name
        if not name.endswith(".md"):
            name += ".md"
        return self.notes_dir / name

    def index(self) -> str:
        lines = []
        for p in sorted(self.notes_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8").strip().splitlines()
            desc = text[0].lstrip("# ").strip() if text else ""
            facts = sum(1 for l in text if l.startswith("- "))
            lines.append(f"- {p.name}: {desc} ({facts} фактов)")
        return "\n".join(lines)

    def read_note(self, name: str) -> str:
        p = self._safe_note(name)
        return p.read_text(encoding="utf-8") if p.exists() else f"Заметки {p.name} нет."

    def remember(self, fact: str, note: str = "notes.md", session: str = "") -> str:
        fact = " ".join(fact.split())
        if not fact:
            return "Пустой факт — нечего запоминать."
        fact = resolve_dates(fact)
        p = self._safe_note(note)
        if not p.exists():
            p.write_text(f"# {p.stem}\n", encoding="utf-8")
        existing = p.read_text(encoding="utf-8")
        if fact.lower() in existing.lower():
            return f"Уже помню это ({p.name})."
        line = f"- {fact} ({time.strftime('%Y-%m-%d')})"
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if session:
            try:
                self.db.execute("INSERT INTO mem_sources(note, line, session, ts) VALUES(?,?,?,?)", (p.name, line, session, time.time()))
                self.db.commit()
            except Exception:
                quiet()
        return f"Запомнил в {p.name}: {fact}"

    def _tokens(self, s: str) -> set[str]:
        return {w for w in re.findall(r"\w{4,}", s.lower()) if not w.isdigit()}

    def learned_from(self, session: str) -> list[dict]:
        """Memory lines that came from this chat: recorded at save time, or (older facts, saved before that was
        recorded) a line whose words mostly appear in what the user wrote in this chat."""
        out, seen = [], set()
        try:
            for note, line in self.db.execute("SELECT note, line FROM mem_sources WHERE session=?", (session,)):
                seen.add((note, line))
        except Exception:
            quiet()
        user_text = [self._tokens(c) for (c,) in self.db.execute(
            "SELECT content FROM messages WHERE session=? AND role='user'", (session,))]
        for p in sorted(self.notes_dir.glob("*.md")):
            for l in p.read_text(encoding="utf-8").splitlines():
                if not l.startswith("- "):
                    continue
                if (p.name, l) in seen:
                    out.append({"note": p.name, "line": l, "how": "saved"})
                    continue
                fact = self._tokens(re.sub(r"\(\d{4}-\d{2}-\d{2}\)\s*$", "", l))
                if len(fact) >= 3 and user_text and max(len(fact & u) / len(fact) for u in user_text) >= 0.7:
                    out.append({"note": p.name, "line": l, "how": "match"})
        return out

    def forget_lines(self, items: list[dict]) -> int:
        n = 0
        by_note: dict[str, set] = {}
        for it in items:
            by_note.setdefault(it["note"], set()).add(it["line"])
        for note, lines in by_note.items():
            p = self._safe_note(note)
            if not p.exists():
                continue
            src = p.read_text(encoding="utf-8").splitlines(keepends=True)
            keep = [l for l in src if l.rstrip("\r\n") not in lines]
            n += len(src) - len(keep)
            p.write_text("".join(keep), encoding="utf-8")
        try:
            for it in items:
                self.db.execute("DELETE FROM mem_sources WHERE note=? AND line=?", (it["note"], it["line"]))
            self.db.commit()
        except Exception:
            quiet()
        return n

    def forget(self, text: str) -> str:
        text = text.strip().lower()
        removed = []
        for p in self.notes_dir.glob("*.md"):
            lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
            keep = [l for l in lines if not (l.startswith("- ") and text in l.lower())]
            if len(keep) != len(lines):
                p.write_text("".join(keep), encoding="utf-8")
                removed.append(f"{p.name}: {len(lines) - len(keep)}")
        return "Удалил: " + ", ".join(removed) if removed else "Не нашёл такого в памяти."

    def always_on_context(self, budget_chars: int = 6000) -> str:
        """Index + profile + preferences (small) — goes into every system prompt."""
        parts = ["Оглавление памяти (заметку читай через memory_read, если нужна; «что мы раньше обсуждали / о чём говорили» "
                 "ищи в прошлых чатах через search_history):", self.index()]
        for name in ("profile.md", "preferences.md"):
            body = self.read_note(name).strip()
            if body.count("\n") >= 1:
                parts.append(body)
        notes = [l for l in self.read_note("notes.md").splitlines() if l.startswith("- ")]
        if notes:
            parts.append(f"Пользователь просил запомнить (сегодня {time.strftime('%Y-%m-%d, %A')}; в скобках в конце — дата, когда "
                         f"записано; отвечая, называй и ЧТО, и КОГДА, полным предложением):\n" + "\n".join(notes[-25:]))
        text = "\n\n".join(parts)
        return text[:budget_chars]
