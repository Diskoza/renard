"""Documents the user works with: find the recent presentation / document / table, replace text in it
(docx, pptx, xlsx, odt/odp/ods — with a .bak copy), run a slideshow in PowerPoint / LibreOffice Impress."""
import asyncio
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from . import I, S, tool

KINDS = {
    "presentation": {".pptx", ".ppt", ".odp", ".key"},
    "document": {".docx", ".doc", ".odt", ".rtf", ".pdf", ".txt", ".md"},
    "table": {".xlsx", ".xls", ".ods", ".csv"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus"},
    "archive": {".zip", ".7z", ".rar"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".php", ".sql", ".java", ".lua", ".cs", ".cpp"},
}
KIND_WORDS = {"презентац": "presentation", "слайд": "presentation", "prezentac": "presentation", "документ": "document",
              "реферат": "document", "доклад": "document", "ворд": "document", "текст": "document", "pdf": "document",
              "таблиц": "table", "эксель": "table", "excel": "table", "фот": "image", "картинк": "image",
              "скрин": "image", "видео": "video", "аудио": "audio", "запис": "audio", "музык": "audio", "архив": "archive",
              "код": "code", "скрипт": "code"}
SKIP = {"node_modules", ".git", "__pycache__", ".venv", "venv", "site-packages", "AppData", "$RECYCLE.BIN", ".cache"}


def kind_of(word: str) -> str:
    w = (word or "").lower()
    if w in KINDS:
        return w
    for k, v in KIND_WORDS.items():
        if k in w:
            return v
    return ""


def _places() -> list[Path]:
    home = Path.home()
    cand = [home / "OneDrive" / "Desktop", home / "Desktop", home / "OneDrive" / "Документи", home / "OneDrive" / "Documents",
            home / "Documents", home / "Downloads", home / "OneDrive" / "Зображення", home / "Pictures", home / "Videos"]
    return [p for p in dict.fromkeys(cand) if p.exists()]


def _scan(exts: set, query: str, days: int, budget: float = 8.0) -> list[tuple[float, Path]]:
    t0, since, out = time.time(), time.time() - days * 86400, []
    q = (query or "").lower()
    for root in _places():
        depth0 = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            if len(Path(dirpath).parts) - depth0 >= 5:
                dirs[:] = []
            for f in files:
                if exts and Path(f).suffix.lower() not in exts:
                    continue
                if q and q not in f.lower():
                    continue
                p = Path(dirpath) / f
                try:
                    mt = p.stat().st_mtime
                except OSError:
                    continue
                if mt >= since:
                    out.append((mt, p))
            if time.time() - t0 > budget:
                break
    return sorted(set(out), reverse=True)


@tool("recent_files", "Найти НЕДАВНИЕ файлы пользователя по виду: kind = presentation | document | table | image | video | audio | "
                      "archive | code (или пусто — любые), query — часть имени, days — за сколько дней (по умолчанию 60). "
                      "Ищет на рабочем столе, в документах, загрузках и OneDrive. «Найди мою презентацию» — это он.",
      {"kind": S, "query": S, "days": I}, [])
async def recent_files(kind: str = "", query: str = "", days: int = 60) -> str:
    k = kind_of(kind)
    exts = KINDS.get(k, set())
    hits = await asyncio.to_thread(_scan, exts, query, int(days or 60))
    if not hits:
        return f"Не нашёл {('файлов вида ' + k) if k else 'файлов'}{(' с «' + query + '» в имени') if query else ''} за {days} дн."
    lines = [f"{time.strftime('%d.%m %H:%M', time.localtime(mt))}  {p}" for mt, p in hits[:15]]
    return f"Найдено {len(hits)}, самые свежие первыми:\n" + "\n".join(lines)


def _replace_runs(paragraphs, old: str, new: str) -> int:
    n = 0
    for para in paragraphs:
        if old not in para.text:
            continue
        hit = False
        for r in para.runs:
            if old in r.text:
                r.text = r.text.replace(old, new)
                n += 1
                hit = True
        if not hit and para.runs:
            full = para.text.replace(old, new)
            para.runs[0].text = full
            for r in para.runs[1:]:
                r.text = ""
            n += 1
    return n


def _do_replace(p: Path, old: str, new: str) -> int:
    ext = p.suffix.lower()
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        n = _replace_runs(d.paragraphs, old, new)
        for t in d.tables:
            for row in t.rows:
                for c in row.cells:
                    n += _replace_runs(c.paragraphs, old, new)
        d.save(str(p))
        return n
    if ext == ".pptx":
        from pptx import Presentation
        pr = Presentation(str(p))
        n = 0
        for s in pr.slides:
            for sh in s.shapes:
                if sh.has_text_frame:
                    n += _replace_runs(sh.text_frame.paragraphs, old, new)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for row in sh.table.rows:
                        for c in row.cells:
                            n += _replace_runs(c.text_frame.paragraphs, old, new)
        pr.save(str(p))
        return n
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(str(p))
        n = 0
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and old in c.value:
                        c.value = c.value.replace(old, new); n += 1
        wb.save(str(p))
        return n
    if ext in (".odt", ".odp", ".ods"):
        from xml.sax.saxutils import escape
        tmp = p.with_suffix(p.suffix + ".tmp")
        n = 0
        with zipfile.ZipFile(p) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename in ("content.xml", "styles.xml"):
                    s = data.decode("utf-8")
                    n += s.count(escape(old))
                    data = s.replace(escape(old), escape(new)).encode("utf-8")
                zout.writestr(item, data, compress_type=zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED)
        tmp.replace(p)
        return n
    raise ValueError(f"не умею менять текст в {ext} (умею: docx, pptx, xlsx, odt, odp, ods)")


def _open_window(p: Path):
    try:
        from .apps import list_wins
        stem = p.stem.lower()
        return next((w for w in list_wins() if stem in w["title"].lower()), None)
    except Exception:
        return None


@tool("doc_replace", "Заменить текст в документе/презентации/таблице (docx, pptx, xlsx, odt, odp, ods) или текстовом файле: "
                     "old → new во всём файле. "
                     "Старая версия сохраняется в .bak. path — полный путь (найди через recent_files/search_files).",
      {"path": S, "old": S, "new": S}, ["path", "old", "new"])
def doc_replace(path: str, old: str, new: str) -> str:
    from .files import safe
    p = safe(path)
    if not p.is_file():
        return f"Файла {p} нет."
    if not old:
        return "Не указано, что заменить."
    bak, i = p.with_name(p.name + ".bak"), 1
    while bak.exists():
        bak, i = p.with_name(f"{p.name}.{i}.bak"), i + 1
    shutil.copy2(p, bak)
    try:
        if p.suffix.lower() in (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods"):
            n = _do_replace(p, old, new)
        else:
            raw = p.read_bytes()
            enc = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
            s = raw.decode(enc)
            n = s.count(old)
            if n:
                p.write_text(s.replace(old, new), encoding=enc, newline="")
    except PermissionError:
        bak.unlink(missing_ok=True)
        return f"Файл {p.name} занят программой, в которой он открыт. Закрой его (или сохрани) и скажи ещё раз."
    except UnicodeDecodeError:
        bak.unlink(missing_ok=True)
        return f"{p.name} — не текстовый файл и не документ Office, заменить в нём текст не могу."
    except Exception as e:
        return f"Не смог изменить {p.name}: {type(e).__name__}: {e}. Копия до изменения: {bak.name}."
    if not n:
        bak.unlink(missing_ok=True)
        return f"В {p.name} нет текста «{old}» (регистр важен). Посмотри точное написание через read_file."
    w = _open_window(p)
    tail = (f" Файл открыт в «{w['title'][:50]}» — там ещё старая версия: закрой окно без сохранения и открой файл заново "
            f"(или скажи «переоткрой»).") if w else ""
    return f"Заменил «{old}» → «{new}» в {p.name} ({n} мест). Копия старой версии: {bak.name}.{tail}"


SHOW_KEYS = {"start": "f5", "from_current": "shift+f5", "next": "right", "prev": "left", "end": "escape",
             "first": "home", "last": "end"}


@tool("presentation", "Показ презентации в открытом PowerPoint / LibreOffice Impress: action start (запустить показ с начала), "
                      "from_current, next, prev, first, last, end. path — файл, если презентация ещё не открыта.",
      {"action": S, "path": S}, ["action"])
async def presentation(action: str = "start", path: str = "") -> str:
    from .apps import activate, list_wins
    from .. import winput
    key = SHOW_KEYS.get((action or "start").lower())
    if not key:
        return f"Не знаю действие «{action}». Есть: {', '.join(SHOW_KEYS)}."
    wins = list_wins()
    w = next((x for x in wins if x["stem"] in ("powerpnt", "soffice.bin", "soffice")
              or re.search(r"\.(pptx?|odp)\b|impress|powerpoint", x["title"], re.I)), None)
    if not w and path:
        from .files import safe
        os.startfile(str(safe(path)))
        for _ in range(30):
            await asyncio.sleep(0.5)
            w = next((x for x in list_wins() if Path(path).stem.lower() in x["title"].lower()), None)
            if w:
                break
        await asyncio.sleep(1.5)
    if not w:
        return "Не вижу открытой презентации. Скажи, какой файл открыть (или найду через recent_files)."
    activate(w["hwnd"])
    await asyncio.sleep(0.4)
    winput.press(key)
    names = {"start": "Запустил показ", "from_current": "Запустил показ с текущего слайда", "next": "Следующий слайд",
             "prev": "Предыдущий слайд", "end": "Закрыл показ", "first": "Первый слайд", "last": "Последний слайд"}
    return f"{names[action.lower()]}: {w['title'][:60]}."
