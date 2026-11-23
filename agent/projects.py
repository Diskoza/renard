"""Projects like Claude Projects: name + instructions + knowledge files + linked folders + own memory + own chats.

data/projects.json                       — list of projects
data/projects/<id>/knowledge/            — files uploaded into the project (any text, PDF, Word, Excel, code…)
data/projects/<id>/index.json            — text chunks of knowledge files AND of the linked folders
data/projects/<id>/memory.md             — what the agent learned inside this project (project_remember)

Every request in a project chat gets: instructions, project memory, and the knowledge relevant to the question
(small knowledge — whole; big — the best matching chunks, keyword search with crude Russian/Polish stemming)."""
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

from .config import DATA_DIR
from .logs import quiet

PATH = DATA_DIR / "projects.json"
PDIR = DATA_DIR / "projects"
CHUNK = 1400
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages", "dist", "build", ".next", ".cache",
        "bin", "obj", "target", ".idea", ".vscode"}


def _load() -> list[dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict]):
    PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def all_projects() -> list[dict]:
    return _load()


def get(pid: str) -> dict | None:
    return next((p for p in _load() if p["id"] == pid), None)


def pdir(pid: str) -> Path:
    d = PDIR / re.sub(r"[^\w-]", "", pid)
    (d / "knowledge").mkdir(parents=True, exist_ok=True)
    return d


def upsert(data: dict) -> dict:
    items = _load()
    pid = data.get("id") or uuid.uuid4().hex[:8]
    cur = next((p for p in items if p["id"] == pid), None)
    if cur is None:
        cur = {"id": pid, "name": "Новый проект", "instructions": "", "folders": [], "files": [], "pinned": True,
               "created": time.time()}
        items.append(cur)
    old_folders = list(cur.get("folders", []))
    for k in ("name", "instructions", "folders", "files", "pinned", "color"):
        if k in data:
            cur[k] = data[k]
    from .tools.files import add_root
    for f in cur["folders"]:
        try:
            if Path(f).exists():
                add_root(f)
        except Exception:
            quiet()
    _save(items)
    if cur["folders"] != old_folders or cur.get("files"):
        try:
            reindex(pid)
        except Exception as e:
            print("project reindex:", e)
    return cur


def delete(pid: str) -> bool:
    items = _load()
    new = [p for p in items if p["id"] != pid]
    _save(new)
    d = PDIR / re.sub(r"[^\w-]", "", pid)
    if d.exists():
        try:
            from .tools.files import delete_to_recycle_bin
            delete_to_recycle_bin(str(d))
        except Exception:
            quiet()
    return len(new) != len(items)


def _text_of(p: Path) -> str:
    from .tools.files import DOC_EXT, IMAGE_EXT, TEXT_EXT, extract_document
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        return ""
    if ext in DOC_EXT:
        return extract_document(p)
    if ext in TEXT_EXT or ext in (".lua", ".kt", ".vue", ".svelte", ".env.example", ".gradle") or p.stat().st_size < 200_000:
        raw = p.read_bytes()[:1_000_000]
        if b"\x00" in raw[:4000]:
            return ""
        return raw.decode("utf-8", "replace")
    return ""


def _chunks(text: str) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text)
    out, cur = [], ""
    for para in re.split(r"(?<=\n)\n", text):
        while len(para) > CHUNK:
            out.append((cur + para[:CHUNK]).strip()); cur = ""; para = para[CHUNK:]
        if len(cur) + len(para) > CHUNK:
            out.append(cur.strip()); cur = ""
        cur += para + "\n"
    if cur.strip():
        out.append(cur.strip())
    return [c for c in out if c]


def knowledge(pid: str) -> list[dict]:
    d = pdir(pid) / "knowledge"
    return [{"name": f.name, "size": f.stat().st_size, "time": f.stat().st_mtime} for f in sorted(d.iterdir()) if f.is_file()]


def add_file(pid: str, name: str, data: bytes) -> dict:
    name = re.sub(r'[\\/:*?"<>|]+', "_", Path(name).name)[:120] or "file"
    dest = pdir(pid) / "knowledge" / name
    dest.write_bytes(data)
    reindex(pid)
    return {"name": name, "size": len(data)}


def remove_file(pid: str, name: str) -> bool:
    f = pdir(pid) / "knowledge" / Path(name).name
    if not f.exists():
        return False
    from .tools.files import delete_to_recycle_bin
    delete_to_recycle_bin(str(f))
    reindex(pid)
    return True


def reindex(pid: str) -> dict:
    """Knowledge files + project files + linked folders (text, code, docs; up to ~600 files / 4 MB of text)."""
    p = get(pid) or {}
    sources: list[Path] = [f for f in (pdir(pid) / "knowledge").iterdir() if f.is_file()]
    sources += [Path(f) for f in p.get("files", []) if Path(f).is_file()]
    for folder in p.get("folders", []):
        root = Path(folder)
        if not root.is_dir():
            continue
        n = 0
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
            for fn in files:
                fp = Path(dirpath) / fn
                try:
                    if fp.stat().st_size > 1_500_000:
                        continue
                except OSError:
                    continue
                sources.append(fp); n += 1
            if n > 600:
                break
    chunks, total, files = [], 0, 0
    for f in sources:
        try:
            t = _text_of(f)
        except Exception:
            continue
        if not t.strip():
            continue
        files += 1
        for i, ch in enumerate(_chunks(t)):
            chunks.append({"file": str(f), "i": i, "text": ch})
            total += len(ch)
        if total > 4_000_000:
            break
    (pdir(pid) / "index.json").write_text(json.dumps({"time": time.time(), "chunks": chunks}, ensure_ascii=False),
                                          encoding="utf-8")
    return {"files": files, "chunks": len(chunks), "chars": total}


def _index(pid: str) -> list[dict]:
    try:
        return json.loads((pdir(pid) / "index.json").read_text(encoding="utf-8"))["chunks"]
    except Exception:
        return []


def _terms(s: str) -> list[str]:
    return [w[:6] for w in re.findall(r"[a-zа-яёąćęłńóśźżіїєґ0-9_]{3,}", s.lower())
            if w not in {"что", "как", "это", "для", "the", "and", "или", "где", "мне", "мой", "моя", "его", "она"}]


def search(pid: str, query: str, k: int = 6) -> list[dict]:
    chunks = _index(pid)
    q = set(_terms(query))
    if not chunks or not q:
        return []
    df = {}
    toks = []
    for c in chunks:
        t = _terms(c["text"] + " " + Path(c["file"]).name)
        toks.append(t)
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    n = len(chunks)
    scored = []
    for c, t in zip(chunks, toks):
        tf = {}
        for w in t:
            if w in q:
                tf[w] = tf.get(w, 0) + 1
        if tf:
            s = sum((1 + math.log(v)) * math.log(1 + n / df[w]) for w, v in tf.items()) / (1 + len(t) / 400)
            scored.append((s, c))
    return [c for _, c in sorted(scored, key=lambda x: -x[0])[:k]]


def memory(pid: str) -> str:
    f = pdir(pid) / "memory.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def remember(pid: str, fact: str) -> str:
    f = pdir(pid) / "memory.md"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(f"- {fact.strip()} ({time.strftime('%Y-%m-%d')})\n")
    return f"Запомнил в памяти проекта: {fact.strip()}"


def prompt_block(pid: str | None, query: str = "") -> str:
    p = get(pid) if pid else None
    if not p:
        return ""
    lines = [f"ПРОЕКТ «{p['name']}». Ты работаешь внутри этого проекта: его инструкции, знания и память важнее общих."]
    if p.get("instructions"):
        lines.append("Инструкции проекта: " + p["instructions"].strip())
    if p.get("folders"):
        lines.append("Папки проекта: " + "; ".join(p["folders"]) + " (структура — project_map; файлы — read_file/edit_file).")
    mem = memory(pid).strip()
    if mem:
        lines.append("Память проекта (запомнено раньше в этом проекте):\n" + mem[-3000:])
    chunks = _index(pid)
    total = sum(len(c["text"]) for c in chunks)
    if chunks and total <= 9000:
        lines.append("Знания проекта (все файлы):\n" + "\n\n".join(f"### {Path(c['file']).name}\n{c['text']}" for c in chunks))
    elif chunks:
        hits = search(pid, query or p["name"], 6)
        if hits:
            lines.append(f"Знания проекта ({len({c['file'] for c in chunks})} файлов; ниже самое подходящее к вопросу, "
                         f"остальное — инструмент project_search):\n" +
                         "\n\n".join(f"### {c['file']} (часть {c['i'] + 1})\n{c['text']}" for c in hits))
    lines.append("Узнал о проекте что-то важное (решение, стек, правило) — project_remember.")
    return "\n".join(lines)
