"""Archive of the user's conversations with other AIs (ChatGPT, Claude): imported from their data exports, searchable
by the agent («что мне раньше советовали про samba», «как я настраивал tailscale», «с учётом того, о чём мы
говорили…»). Lives only on this PC: data/archive.sqlite3 (gitignored with the rest of data/).

Formats (read straight from the .zip, nothing is unpacked):
  ChatGPT — conversations.json / conversations-NNN.json: [{title, mapping{id: {message, parent}}, current_node}]
  Claude  — conversations.json: [{name, chat_messages[{sender, text, content, created_at}]}]
Only the branch you actually saw is taken (ChatGPT keeps regenerated answers as side branches). The AI's answers are
kept shortened (start + end) — enough to recall what was advised; the user's own messages are kept whole and also go
to data/train/user_msgs.jsonl (persona, test scenarios).
"""
import datetime
import hashlib
import json
import re
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

from .config import DATA_DIR
from .logs import quiet

DB_PATH = DATA_DIR / "archive.sqlite3"
TRAIN = DATA_DIR / "train" / "user_msgs.jsonl"
ANSWER_KEEP = 4000
STOP = set("""что как где когда это эта этот мне меня мой моя мои ты тебя твой про для или если чтобы так там тут
еще ещё уже было были будет есть нет даже очень можно нужно надо какой какая какие раньше говорили обсуждали
спрашивал спрашивала советовал советовали чатгпт chatgpt gpt claude клод чате чатах чат нам нас мы вы они его
the and for with you your what how jak czy jest nie się dla oraz mnie mój привет подскажи помоги скажи напиши можешь
пожалуйста слушай вот типо тоесть cześć siema napisz pomóż proszę powiedz""".split())

_lock = threading.Lock()
_db = None


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.executescript("""
            CREATE TABLE IF NOT EXISTS conv(id TEXT PRIMARY KEY, source TEXT, account TEXT, title TEXT, date TEXT, n INTEGER);
            CREATE TABLE IF NOT EXISTS msg(id INTEGER PRIMARY KEY, conv TEXT, pos INTEGER, role TEXT, date TEXT, text TEXT,
                                           UNIQUE(conv, pos));
            CREATE VIRTUAL TABLE IF NOT EXISTS msg_fts USING fts5(text, title, content='', tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE IF NOT EXISTS imports(file TEXT PRIMARY KEY, source TEXT, account TEXT, convs INTEGER, msgs INTEGER, ts REAL);
        """)
    return _db


def _date(t) -> str:
    try:
        if isinstance(t, (int, float)):
            t = t / 1000 if t > 1e11 else t
            return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        return str(t or "")[:10]
    except Exception:
        return ""


SECRETS = [
    re.compile(r"\b(sk|pk|rk)[-_](live|test|proj)?[-_]?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{8,}"),
    re.compile(r"\b\d{8,10}:AA[\w-]{30,}"),
    re.compile(r"\bAIza[\w-]{30,}"),
    re.compile(r"\bxox[abprs]-[\w-]{10,}"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}(?=\s|$)"),
]
LABELLED = re.compile(r"(?i)\b(password|passwd|пароль|hasło|haslo|secret|client[ _]secret|api[ _-]?key|token|токен|klucz api)"
                      r"(\s*[:=]\s*|\s+)((?=\S*[\d!@#$%^&*])[A-Za-z0-9_\-!@#$%^&*.+/]{6,})")


def redact(text: str) -> str:
    """Keys, tokens and passwords from the exports never reach the archive (and so never an answer or Telegram).
    Also ChatGPT's web-citation markers («citeturn667853search26» in private-use characters) are dropped."""
    text = re.sub(r"[-]*cite(?:[-]*turn\d+[a-z]+\d+)+[-]*", "", text)
    text = re.sub(r"[-]", "", text)
    for rx in SECRETS:
        text = rx.sub("[скрыто]", text)
    return LABELLED.sub(lambda m: m.group(1) + m.group(2) + "[скрыто]", text)


def _short(text: str) -> str:
    text = text.strip()
    if len(text) <= ANSWER_KEEP:
        return text
    return text[:ANSWER_KEEP - 600].rstrip() + " … " + text[-580:].lstrip()


def _chatgpt(convs: list) -> list[dict]:
    out = []
    for c in convs:
        m, node, path = c.get("mapping") or {}, c.get("current_node"), []
        while node and node in m:
            path.append(m[node]); node = m[node].get("parent")
        msgs = []
        for n in reversed(path):
            msg = n.get("message") or {}
            role = (msg.get("author") or {}).get("role")
            md = msg.get("metadata") or {}
            if role not in ("user", "assistant") or md.get("is_visually_hidden_from_conversation"):
                continue
            ct = msg.get("content") or {}
            if ct.get("content_type") not in ("text", "multimodal_text", None):
                continue
            text = "\n".join(p for p in (ct.get("parts") or []) if isinstance(p, str)).strip()
            pics = sum(1 for p in (ct.get("parts") or []) if isinstance(p, dict))
            if pics and role == "user":
                text = (f"[{pics} картинк(и)] " + text).strip()
            if text:
                msgs.append({"role": role, "date": _date(msg.get("create_time") or c.get("create_time")), "text": text})
        if msgs:
            out.append({"id": "chatgpt:" + str(c.get("conversation_id") or c.get("id")), "title": c.get("title") or "",
                        "date": _date(c.get("create_time")), "msgs": msgs})
    return out


def _claude(convs: list) -> list[dict]:
    out = []
    for c in convs:
        msgs = []
        for m in c.get("chat_messages") or []:
            role = {"human": "user", "assistant": "assistant"}.get(m.get("sender"))
            text = (m.get("text") or "").strip()
            if not text and isinstance(m.get("content"), list):
                text = "\n".join(x.get("text", "") for x in m["content"] if isinstance(x, dict) and x.get("type") == "text").strip()
            files = len(m.get("files") or []) + len(m.get("attachments") or [])
            if files and role == "user":
                text = (f"[{files} файл(а)] " + text).strip()
            if role and text:
                msgs.append({"role": role, "date": _date(m.get("created_at")), "text": text})
        if msgs:
            out.append({"id": "claude:" + str(c.get("uuid")), "title": c.get("name") or "", "date": _date(c.get("created_at")),
                        "msgs": msgs})
    return out


def read_export(path: Path) -> tuple[str, list[dict]]:
    """-> (source, conversations). Raises ValueError if this is not a ChatGPT / Claude export."""
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.search(r"(^|/)conversations(-\d+)?\.json$", n)]
        if not names:
            raise ValueError("в архиве нет conversations.json — это не экспорт ChatGPT или Claude")
        convs = []
        for n in sorted(names):
            with z.open(n) as f:
                convs += json.load(f)
    if not convs:
        return "unknown", []
    if "mapping" in convs[0]:
        return "chatgpt", _chatgpt(convs)
    if "chat_messages" in convs[0]:
        return "claude", _claude(convs)
    raise ValueError("непонятный формат conversations.json")


def import_export(path, progress=None) -> dict:
    path = Path(path)
    source, convs = read_export(path)
    account = hashlib.sha1(path.name.encode()).hexdigest()[:6]
    d = db()
    new_c = new_m = 0
    seen_user = set()
    TRAIN.parent.mkdir(parents=True, exist_ok=True)
    if TRAIN.exists():
        for line in TRAIN.open(encoding="utf-8", errors="replace"):
            try:
                x = json.loads(line); seen_user.add((x.get("date", ""), x.get("text", "")[:200]))
            except Exception:
                quiet()
    with _lock, TRAIN.open("a", encoding="utf-8") as train:
        for i, c in enumerate(convs):
            if progress and i % 50 == 0:
                progress(i, len(convs))
            if d.execute("SELECT 1 FROM conv WHERE id=?", (c["id"],)).fetchone():
                continue
            d.execute("INSERT INTO conv VALUES (?,?,?,?,?,?)", (c["id"], source, account, c["title"], c["date"], len(c["msgs"])))
            new_c += 1
            for pos, m in enumerate(c["msgs"]):
                m["text"] = redact(m["text"])
                text = m["text"] if m["role"] == "user" else _short(m["text"])
                cur = d.execute("INSERT OR IGNORE INTO msg(conv, pos, role, date, text) VALUES (?,?,?,?,?)",
                                (c["id"], pos, m["role"], m["date"], text))
                if cur.rowcount:
                    d.execute("INSERT INTO msg_fts(rowid, text, title) VALUES (?,?,?)", (cur.lastrowid, text, c["title"]))
                    new_m += 1
                if m["role"] == "user":
                    key = (m["date"], m["text"][:200])
                    if key not in seen_user:
                        seen_user.add(key)
                        train.write(json.dumps({"src": f"{source}-{account}", "conv": c["title"], "date": m["date"],
                                                "text": m["text"], "files": []}, ensure_ascii=False) + "\n")
        d.execute("INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?,?)", (path.name, source, account, new_c, new_m, time.time()))
        d.commit()
    return {"file": path.name, "source": source, "conversations": len(convs), "new_conversations": new_c, "new_messages": new_m}


def find_exports(folder: Path | None = None) -> list[dict]:
    """Export zips lying in Downloads (ChatGPT: <hash>-<date>.zip, Claude: conversations-NNN.zip / data-*.zip)."""
    folder = folder or Path.home() / "Downloads"
    done = {r[0] for r in db().execute("SELECT file FROM imports")}
    out = []
    for p in sorted(folder.glob("*.zip"), key=lambda p: -p.stat().st_mtime)[:200]:
        if p.stat().st_size < 20_000:
            continue
        try:
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
            if not any(re.search(r"(^|/)conversations(-\d+)?\.json$", n) for n in names):
                continue
            kind = "chatgpt" if any("chat.html" in n or re.search(r"conversations-\d+\.json$", n) for n in names) else "claude"
        except Exception:
            continue
        out.append({"path": str(p), "name": p.name, "size_mb": round(p.stat().st_size / 1e6, 1), "kind": kind,
                    "imported": p.name in done, "date": time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))})
    return out


def stats() -> dict:
    d = db()
    src = [{"source": s, "account": a, "conversations": c, "first": f, "last": l} for s, a, c, f, l in d.execute(
        "SELECT source, account, COUNT(*), MIN(date), MAX(date) FROM conv GROUP BY source, account ORDER BY MIN(date)")]
    n = d.execute("SELECT COUNT(*) FROM msg").fetchone()[0]
    return {"sources": src, "messages": n, "imports": [dict(zip(("file", "source", "account", "convs", "msgs", "ts"), r))
                                                      for r in d.execute("SELECT * FROM imports ORDER BY ts")]}


def forget(source: str = "", account: str = "") -> int:
    """Delete an imported account (or everything)."""
    d = db()
    q, a = "SELECT id FROM conv WHERE 1=1", []
    if source:
        q += " AND source=?"; a.append(source)
    if account:
        q += " AND account=?"; a.append(account)
    ids = [r[0] for r in d.execute(q, a)]
    with _lock:
        for cid in ids:
            for rid, text, title in d.execute("SELECT m.id, m.text, c.title FROM msg m JOIN conv c ON c.id=m.conv WHERE m.conv=?", (cid,)).fetchall():
                d.execute("INSERT INTO msg_fts(msg_fts, rowid, text, title) VALUES('delete', ?, ?, ?)", (rid, text, title))
            d.execute("DELETE FROM msg WHERE conv=?", (cid,))
            d.execute("DELETE FROM conv WHERE id=?", (cid,))
        if not source and not account:
            d.execute("DELETE FROM imports")
        else:
            d.execute("DELETE FROM imports WHERE (?='' OR source=?) AND (?='' OR account=?)", (source, source, account, account))
        d.commit()
    return len(ids)


ENDINGS = sorted("ами ями ого его ому ему ыми ими ах ях ам ям ом ем ой ей ую юю ая яя ые ие ов ев ы и а я у ю е о ь".split(),
                 key=len, reverse=True)


def _stems(query: str) -> list[str]:
    out = []
    for w in re.findall(r"[\wąćęłńóśźż.+#-]+", query.lower().replace("ё", "е")):
        w = w.strip(".-")
        if len(w) < 3 or w in STOP:
            continue
        if re.fullmatch(r"[а-я]+", w):
            if len(w) > 6:
                w = w[:max(4, round(len(w) * .7))]
            else:
                for e in ENDINGS:
                    if w.endswith(e) and len(w) - len(e) >= 3:
                        w = w[:-len(e)]
                        break
        out.append(w)
    return list(dict.fromkeys(out))[:12]


def recall(text: str) -> str:
    """He asks the same things again (INF.02 questions, Minecraft commands, SQL…). If a past question is almost
    the same, the answer he got then goes to the model as a hint — it is told it may be inaccurate."""
    words = _stems(text)
    if len(words) < 3 or len(text) > 1500:
        return ""
    try:
        hits = search(text, limit=3)
    except Exception:
        return ""
    for h in hits:
        theirs = h["question"].lower().replace("ё", "е")
        same = sum(1 for w in words if w in theirs)
        other = len(set(_stems(h["question"])) - set(words))
        if same / len(words) >= .75 and other <= len(words) and h["answer"]:
            name = {"chatgpt": "ChatGPT", "claude": "Claude"}.get(h["source"], h["source"])
            return (f"\n\n[Справка Renard: почти такой же вопрос пользователь задавал {h['date']} в {name} (чат «{h['title']}»). "
                    f"Ответ тогда — может быть неточным, проверь и ответь сам:\n{h['answer'][:1500]}]")
    return ""


def search(query: str, limit: int = 5) -> list[dict]:
    """Best matching conversations: title, date, source, the matching user message and the answer after it."""
    words = _stems(query)
    if not words:
        return []
    d = db()
    fts = " OR ".join('"' + w.replace('"', "") + '"*' for w in words)
    try:
        rows = d.execute("SELECT m.id, m.conv, m.pos, m.role, m.date, m.text, c.title, c.source, bm25(msg_fts, 1.0, 3.0) AS r "
                         "FROM msg_fts JOIN msg m ON m.id = msg_fts.rowid JOIN conv c ON c.id = m.conv "
                         "WHERE msg_fts MATCH ? ORDER BY r LIMIT 200", (fts,)).fetchall()
    except sqlite3.OperationalError:
        return []
    best: dict[str, tuple] = {}
    for row in rows:
        mid, conv, pos, role, date, text, title, source, r = row
        hay = (text + " " + title).lower()
        cover = sum(1 for w in words if w in hay)
        key = (-cover, r)
        if conv not in best or key < best[conv][0]:
            best[conv] = (key, row)
    out, seen_q = [], set()
    for key, row in sorted(best.values(), key=lambda x: x[0]):
        mid, conv, pos, role, date, text, title, source, r = row
        q = d.execute("SELECT pos, text FROM msg WHERE conv=? AND pos<=? AND role='user' ORDER BY pos DESC LIMIT 1",
                      (conv, pos)).fetchone()
        qpos, qtext = q if q else (-1, "")
        nxt = d.execute("SELECT MIN(pos) FROM msg WHERE conv=? AND pos>? AND role='user'", (conv, qpos)).fetchone()[0]
        parts = [r[0] for r in d.execute(
            "SELECT text FROM msg WHERE conv=? AND pos>? AND pos<? AND role='assistant' ORDER BY pos",
            (conv, qpos, nxt if nxt is not None else 10 ** 9))]
        a = ("\n".join(parts),) if parts else None
        sig = re.sub(r"\W+", "", qtext.lower())[:120]
        if sig and sig in seen_q:
            continue
        seen_q.add(sig)
        ans = a[0] if a else ""
        low = ans.lower().replace("ё", "е")
        hit = min([i for i in (low.find(w) for w in words) if i >= 0] or [0])
        s = 0 if hit < 500 else hit - 250
        size = 2000 if not out else 700
        out.append({"title": re.sub(r"^(Ветка · )+", "", title), "date": date, "source": source,
                    "question": qtext[:500], "answer": ("…" if s else "") + ans[s:s + size], "match": -key[0]})
        if len(out) >= limit:
            break
    return out


def format_hits(hits: list[dict]) -> str:
    name = {"chatgpt": "ChatGPT", "claude": "Claude"}
    parts = []
    for h in hits:
        parts.append(f"[{h['date']}] {name.get(h['source'], h['source'])}, чат «{h['title']}»\n"
                     f"  ты: {h['question']}\n  ответ: {h['answer']}")
    return "\n".join(parts)
