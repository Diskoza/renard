"""File tools. Work only inside allowed_roots. Delete = Recycle Bin, never permanent."""
import fnmatch
import os
import re
import subprocess
import time
from pathlib import Path

from ..config import SETTINGS
from . import I, S, tool
from ..logs import quiet

FS = SETTINGS.get("files", {})
ROOTS = [Path(os.path.expandvars(os.path.expanduser(r))).resolve() for r in FS.get("allowed_roots", [])]
WORKSPACE = Path(SETTINGS.get("workspace", "workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
ROOTS.append(WORKSPACE)
EXTRA_ROOTS_FILE = Path(__file__).resolve().parents[2] / "data" / "extra_roots.json"


def _known_folders() -> list[Path]:
    """Real Desktop / Documents / Downloads (OneDrive may move them: C:\\Users\\x\\OneDrive\\Desktop)."""
    out = []
    try:
        from win32com.shell import shell, shellcon
        for csidl in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_PERSONAL, shellcon.CSIDL_MYPICTURES):
            out.append(Path(shell.SHGetFolderPath(0, csidl, None, 0)))
    except Exception:
        quiet()
    out.append(Path.home() / "Downloads")
    return out


def _extra_roots() -> list[Path]:
    import json
    try:
        return [Path(x) for x in json.loads(EXTRA_ROOTS_FILE.read_text(encoding="utf-8"))]
    except Exception:
        return []


for _r in _known_folders() + _extra_roots():
    if _r.exists() and _r.resolve() not in ROOTS:
        ROOTS.append(_r.resolve())


def add_root(path: str) -> Path:
    """Allow one more folder (persisted in data/extra_roots.json). Called only after the user confirmed."""
    import json
    p = Path(os.path.expandvars(path.strip().strip('"'))).expanduser().resolve()
    if p == Path(p.anchor) or str(p).lower().startswith(("c:\\windows", "c:\\program files", "c:\\programdata")):
        raise PermissionError(f"Целый диск и системные папки не открываю: {p}")
    p.mkdir(parents=True, exist_ok=True)
    if p not in ROOTS:
        ROOTS.append(p)
        extra = [str(x) for x in _extra_roots()]
        if str(p) not in extra:
            EXTRA_ROOTS_FILE.write_text(json.dumps(extra + [str(p)], ensure_ascii=False, indent=1), encoding="utf-8")
    return p
READ_LIMIT = FS.get("read_limit_chars", 20000)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages", ".next", "dist", "build",
             "$RECYCLE.BIN", "System Volume Information", "models", ".cache"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sql", ".php", ".json", ".md", ".txt", ".yml",
            ".yaml", ".toml", ".ini", ".cfg", ".ps1", ".cmd", ".bat", ".java", ".c", ".cpp", ".h",
            ".cs", ".go", ".rs", ".xml", ".csv", ".log", ".sh"}


def safe(path: str) -> Path:
    p = Path(os.path.expandvars(path.strip().strip('"'))).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    if not any(p == r or r in p.parents for r in ROOTS):
        raise PermissionError(f"Папка {p} пока не разрешена агенту (это настройка безопасности Renard, а не права Windows). "
                              f"Вызови allow_folder с этой папкой — система спросит у пользователя подтверждение. "
                              f"Сейчас разрешены: {', '.join(map(str, ROOTS))}")
    return p


def human(n: float) -> str:
    for u in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "Б" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} ПБ"


@tool("list_dir", "Показать содержимое папки (файлы и подпапки с размерами)", {"path": S}, ["path"])
def list_dir(path: str) -> str:
    p = safe(path)
    if not p.is_dir():
        return f"{p} — не папка."
    out = []
    for e in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:200]:
        try:
            out.append(f"{'[D]' if e.is_dir() else '   '} {e.name}" + ("" if e.is_dir() else f"  {human(e.stat().st_size)}"))
        except OSError:
            pass
    return f"{p}:\n" + "\n".join(out)


@tool("project_tree", "Структура проекта: дерево папок (без мусора вроде node_modules), количество и размер файлов",
      {"path": S, "depth": I}, ["path"])
def project_tree(path: str, depth: int = 3) -> str:
    root = safe(path)
    lines, total, size = [], 0, 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        rel = Path(dirpath).relative_to(root)
        lvl = len(rel.parts)
        for f in files:
            try:
                size += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
        total += len(files)
        if lvl <= depth:
            ind = "  " * lvl
            lines.append(f"{ind}{rel.name or root.name}/  ({len(files)} файлов)")
            if lvl < depth:
                for f in sorted(files)[:25]:
                    lines.append(f"{ind}  {f}")
        if len(lines) > 300:
            lines.append("... (обрезано)")
            break
    return f"Всего файлов: {total}, размер: {human(size)}\n" + "\n".join(lines)


@tool("search_files", "Рекурсивно найти файлы И папки по маске имени (name='*.md', 'project') и/или по тексту внутри "
                      "(text=...). folder можно не указывать — тогда ищет во всех разрешённых папках (рабочий стол, документы, "
                      "загрузки…). Для поиска используй его, а не list_dir", {"folder": S, "name": S, "text": S}, [])
def search_files(folder: str = "", name: str = "", text: str = "", _deadline: float = 0) -> str:
    if not (folder or "").strip() or folder.strip() in ("*", "/", "\\", "все", "везде", "all"):
        roots = [r for r in ROOTS if r.exists() and not any(o != r and o in r.parents for o in ROOTS)]
        deadline, outs = time.time() + 30, []
        for r in sorted(roots, key=lambda p: len(str(p)), reverse=True):
            if time.time() > deadline:
                break
            outs.append(search_files(str(r), name, text, _deadline=deadline))
        hits = sorted({l for o in outs for l in o.splitlines()[1:] if l.strip()}, key=lambda h: (h.count("\\"), h.lower()))
        total = sum(int(m.group(1)) for o in outs for m in [re.match(r"Найдено (\d+)", o)] if m)
        return (f"Найдено {total} (во всех разрешённых папках)" + (", показаны первые 50" if total > 50 else "")
                + ("\n" + "\n".join(hits[:50]) if hits else ""))
    root = safe(folder)
    pat = name or "*"
    if pat and "*" not in pat and "?" not in pat:
        pat = f"*{pat}*"
    needle = text.lower()
    hits, t0 = [], time.time()
    limit_t = (_deadline - t0) if _deadline else 20
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if not needle and name:
            hits += [str(Path(dirpath) / d) + "\\" for d in dirs if fnmatch.fnmatch(d.lower(), pat.lower())]
        for f in files:
            if not fnmatch.fnmatch(f.lower(), pat.lower()):
                continue
            fp = Path(dirpath) / f
            if needle:
                if fp.suffix.lower() not in TEXT_EXT:
                    continue
                try:
                    if fp.stat().st_size > 2_000_000:
                        continue
                    content = fp.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                idx = content.lower().find(needle)
                if idx < 0:
                    continue
                line_no = content.count("\n", 0, idx) + 1
                snippet = content[max(0, idx - 60): idx + 80].replace("\n", " ")
                hits.append(f"{fp}:{line_no}: …{snippet}…")
            else:
                hits.append(str(fp))
            if len(hits) >= 2000:
                break
        if len(hits) >= 2000 or time.time() - t0 > limit_t:
            break
    hits.sort(key=lambda h: (h.count("\\") + 3 * bool(re.search(r"\\[._](cache|pytest|mypy|ruff|git|venv)", h)), h.lower()))
    n = len(hits)
    head = (f"Найдено {n}" + (" и больше (поиск остановлен)" if n >= 2000 else "") +
            (f", показаны первые 50 — всего {n}" if n > 50 else "") + f", {time.time() - t0:.1f} с")
    return head + ("\n" + "\n".join(hits[:50]) if hits else "")


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".doc", ".xls", ".ppt"}


def extract_document(p: Path) -> str:
    """Text of PDF / Word / Excel / PowerPoint files (school tasks, invoices, tables people send)."""
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(p))
        pages = [f"--- страница {i + 1} ---\n{(pg.extract_text() or '').strip()}" for i, pg in enumerate(r.pages[:60])]
        text = "\n".join(pages)
        if len(text.replace("-", "").strip()) < 40 * max(1, len(pages)):
            text += "\n\n[в PDF почти нет текста — похоже, это скан. Можно посмотреть страницы как картинку: look_at_image]"
        return text
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        out = [para.text for para in d.paragraphs if para.text.strip()]
        for ti, t in enumerate(d.tables[:20]):
            out.append(f"--- таблица {ti + 1} ---")
            out += [" | ".join(c.text.strip() for c in row.cells) for row in t.rows[:200]]
        return "\n".join(out)
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:10]:
            out.append(f"--- лист «{ws.title}» ---")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 300:
                    out.append("… (дальше строки не показаны)")
                    break
                if any(v is not None for v in row):
                    out.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(out)
    if ext == ".pptx":
        from pptx import Presentation
        out = []
        for i, s in enumerate(Presentation(str(p)).slides, 1):
            texts = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            out.append(f"--- слайд {i} ---\n" + "\n".join(texts))
        return "\n".join(out)
    if ext in (".odt", ".ods", ".odp"):
        return _odf_text(p)
    if ext in (".doc", ".rtf", ".xls", ".ppt"):
        try:
            from .office import _convert
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                return _convert(p, "txt", Path(tmp)).read_text(encoding="utf-8", errors="replace")
        except Exception:
            quiet()
    return p.read_text(encoding="utf-8", errors="replace")


def _odf_text(p: Path) -> str:
    """OpenDocument (odt/ods/odp) → text: paragraphs on their own lines, tab stops as « | », table cells « | »
    (the raw zip used to come back as binary garbage — the model then invented the document)."""
    import html
    import zipfile
    x = zipfile.ZipFile(p).read("content.xml").decode("utf-8", "replace")
    x = re.sub(r"<text:tab/>", " | ", x)
    x = re.sub(r'<text:s(?: text:c="(\d+)")?/>', lambda m: " " * int(m.group(1) or 1), x)
    x = re.sub(r"<text:line-break/>", "\n", x)
    x = re.sub(r"</table:table-cell>", " | ", x)
    x = re.sub(r"</(text:p|text:h|table:table-row)>", "\n", x)
    x = html.unescape(re.sub(r"<[^>]+>", "", x))
    lines = [re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"[ \t]+", " ", ln)).strip(" |") for ln in x.splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())


@tool("read_file", "Прочитать файл: текст, код, PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx). Картинки — look_at_image",
      {"path": S}, ["path"])
def read_file(path: str) -> str:
    p = safe(path)
    if not p.is_file():
        return f"Файла {p} нет."
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        return (f"{p.name} — это картинка, текста в ней не прочитать read_file. Посмотри её инструментом look_at_image "
                f"(path={p}).")
    if ext in DOC_EXT:
        try:
            data = extract_document(p)
        except Exception as e:
            return f"Не смог прочитать {p.name}: {type(e).__name__}: {e}"
    else:
        raw = p.read_bytes()[:400_000]
        if b"\x00" in raw[:4000]:
            return f"{p.name} — двоичный файл ({human(p.stat().st_size)}), текстом его не прочитать."
        data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) > READ_LIMIT:
        return data[:READ_LIMIT] + f"\n\n[обрезано: показано {READ_LIMIT} из {len(data)} символов]"
    return data


@tool("write_file", "Создать или перезаписать текстовый файл (старая версия сохраняется в .bak)", {"path": S, "content": S},
      ["path", "content"])
def write_file(path: str, content: str) -> str:
    p = safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.with_suffix(p.suffix + ".bak")
        bak.write_bytes(p.read_bytes())
    p.write_text(content, encoding="utf-8")
    return f"Записал {p} ({len(content)} символов)."


@tool("delete_to_recycle_bin", "Удалить файл или папку В КОРЗИНУ (можно восстановить)", {"path": S}, ["path"], confirm=True)
def delete_to_recycle_bin(path: str) -> str:
    p = safe(path)
    if not p.exists():
        return f"{p} не существует."
    method = "DeleteDirectory" if p.is_dir() else "DeleteFile"
    ps = (f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          f"Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::{method}("
          f"'{str(p).replace(chr(39), chr(39) * 2)}', 'OnlyErrorDialogs', 'SendToRecycleBin')")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    return f"Отправил в корзину: {p}" if not p.exists() else f"Не удалось: {r.stderr[:300]}"


@tool("junk_report", "Отчёт о мусоре: временные файлы, кэши. Ничего не удаляет.", modes=("low", "medium"))
def junk_report() -> str:
    cands = [os.environ.get("TEMP", ""), r"C:\Windows\Temp",
             os.path.expandvars(r"%LOCALAPPDATA%\pip\cache"), os.path.expandvars(r"%LOCALAPPDATA%\npm-cache"),
             os.path.expandvars(r"%APPDATA%\npm-cache"), os.path.expandvars(r"%LOCALAPPDATA%\CrashDumps")]
    out, deadline = [], time.time() + 4
    for c in dict.fromkeys(cands):
        if not (c and os.path.isdir(c)):
            continue
        total, cut, stack = 0, False, [c]
        while stack:
            if time.time() > deadline:
                cut = True
                break
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
            except OSError:
                pass
        out.append(f"{c}: {'≥ ' if cut else ''}{human(total)}")
    return "Кандидаты на очистку (удаление только после твоего «да», в корзину):\n" + "\n".join(out)


import ast as _ast
import hashlib as _hashlib
import json as _json
import re as _re

from ..config import DATA_DIR as _DATA_DIR

MAP_DIR = _DATA_DIR / "project_maps"
MAP_DIR.mkdir(parents=True, exist_ok=True)
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".php", ".java", ".cs", ".go", ".rs", ".sql", ".html", ".css"}
ENTRY_NAMES = {"main.py", "__main__.py", "app.py", "server.py", "manage.py", "index.js", "index.ts", "server.js",
               "main.js", "index.html", "package.json", "pyproject.toml", "requirements.txt", "dockerfile",
               "docker-compose.yml", "readme.md", "makefile"}
JS_DEF = _re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+(\w+)|class\s+(\w+)|"
                     r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)", _re.M)
PHP_DEF = _re.compile(r"^\s*(?:public|private|protected|static|\s)*(?:function\s+(\w+)|class\s+(\w+))", _re.M)
SQL_DEF = _re.compile(r"create\s+(?:or\s+replace\s+)?(table|view|function|procedure|index)\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)", _re.I)


def _symbols(fp: Path) -> list[str]:
    try:
        if fp.stat().st_size > 400_000:
            return []
        src = fp.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    ext = fp.suffix.lower()
    out: list[str] = []
    if ext == ".py":
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            return ["(синтаксическая ошибка)"]
        for n in tree.body:
            if isinstance(n, _ast.ClassDef):
                meths = [m.name for m in n.body if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
                out.append(f"class {n.name}" + (f"({', '.join(meths[:8])}{'…' if len(meths) > 8 else ''})" if meths else ""))
            elif isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                out.append(f"def {n.name}")
    elif ext in (".js", ".ts", ".tsx", ".jsx"):
        for m in JS_DEF.finditer(src):
            name = next(g for g in m.groups() if g)
            out.append(name)
    elif ext == ".php":
        for m in PHP_DEF.finditer(src):
            out.append(next(g for g in m.groups() if g))
    elif ext == ".sql":
        out = [f"{k.lower()} {n}" for k, n in SQL_DEF.findall(src)]
    return out[:25]


def _fingerprint(root: Path) -> tuple[str, list[Path]]:
    files, h = [], _hashlib.sha1()
    own_data = _DATA_DIR.resolve()
    for dirpath, dirs, fs in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and (Path(dirpath) / d).resolve() != own_data)
        for f in sorted(fs):
            if f.endswith(".bak"):
                continue
            fp = Path(dirpath) / f
            try:
                st = fp.stat()
            except OSError:
                continue
            files.append(fp)
            h.update(f"{fp}|{st.st_mtime_ns}|{st.st_size}".encode())
        if len(files) > 3000:
            break
    return h.hexdigest(), files


@tool("project_map", "Карта проекта: точки входа, README, структура папок и функции/классы в каждом файле кода. "
      "Кешируется и обновляется только при изменениях. Используй, чтобы понять архитектуру проекта.",
      {"path": S}, ["path"], modes=("medium", "high"))
def project_map(path: str) -> str:
    root = safe(path)
    if not root.is_dir():
        return f"{root} — не папка."
    fp_hash, files = _fingerprint(root)
    cache = MAP_DIR / (_hashlib.sha1(str(root).lower().encode()).hexdigest()[:16] + ".json")
    if cache.exists():
        data = _json.loads(cache.read_text(encoding="utf-8"))
        if data.get("fingerprint") == fp_hash:
            return data["text"] + "\n(из кеша)"
    lines = [f"Проект: {root}", f"Файлов: {len(files)}"]
    entries = [f for f in files if f.name.lower() in ENTRY_NAMES]
    if entries:
        lines.append("Точки входа / конфиги: " + ", ".join(str(f.relative_to(root)) for f in entries[:15]))
    readme = next((f for f in entries if f.name.lower() == "readme.md"), None)
    if readme:
        head = [l.strip("# ").strip() for l in readme.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()][:3]
        lines.append("README: " + " / ".join(head)[:300])
    by_dir: dict[str, list[Path]] = {}
    for f in files:
        by_dir.setdefault(str(f.parent.relative_to(root)), []).append(f)
    for d in sorted(by_dir):
        fs = by_dir[d]
        code = [f for f in fs if f.suffix.lower() in CODE_EXT]
        other = len(fs) - len(code)
        lines.append(f"\n[{d if d != '.' else root.name}/] {len(code)} код, {other} прочих")
        for f in code[:40]:
            syms = _symbols(f)
            try:
                n_lines = sum(1 for _ in f.open("rb")) if f.stat().st_size < 2_000_000 else -1
            except OSError:
                n_lines = -1
            lines.append(f"  {f.name} ({n_lines} строк)" + (": " + ", ".join(syms) if syms else ""))
    text = "\n".join(lines)
    if len(text) > 9000:
        text = text[:9000] + "\n… (обрезано: спроси про конкретную папку)"
    cache.write_text(_json.dumps({"fingerprint": fp_hash, "text": text}, ensure_ascii=False), encoding="utf-8")
    return text


@tool("largest_files", "Самые большие файлы в папке (для поиска мусора и того, что занимает место)",
      {"folder": S, "top": I}, ["folder"])
def largest_files(folder: str, top: int = 15) -> str:
    root = safe(folder)
    import heapq
    heap: list[tuple[int, str]] = []
    t0, n = time.time(), 0
    for dirpath, dirs, files in os.walk(root):
        for f in files:
            try:
                s = os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
            n += 1
            item = (s, os.path.join(dirpath, f))
            if len(heap) < top:
                heapq.heappush(heap, item)
            elif s > heap[0][0]:
                heapq.heapreplace(heap, item)
        if time.time() - t0 > 25:
            break
    res = sorted(heap, reverse=True)
    cut = " (просмотр остановлен по времени)" if time.time() - t0 > 25 else ""
    return f"Просмотрено {n} файлов за {time.time() - t0:.1f} с{cut}:\n" + "\n".join(f"{human(s):>10}  {p}" for s, p in res)


@tool("file_info", "Сведения о файле или папке: размер, даты, число строк", {"path": S}, ["path"])
def file_info(path: str) -> str:
    p = safe(path)
    if not p.exists():
        return f"{p} не существует."
    st = p.stat()
    info = [f"{p}", f"тип: {'папка' if p.is_dir() else 'файл'}", f"изменён: {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}"]
    if p.is_file():
        info.append(f"размер: {human(st.st_size)}")
        if p.suffix.lower() in TEXT_EXT and st.st_size < 5_000_000:
            info.append(f"строк: {sum(1 for _ in p.open('rb'))}")
    return "\n".join(info)


@tool("open_file", "Открыть файл или папку в программе по умолчанию (на экране пользователя)", {"path": S}, ["path"])
def open_file(path: str) -> str:
    if re.match(r"(?i)\s*(https?://|www\.)", path or ""):
        from .browser_ctl import open_url
        u = path.strip()
        return open_url(u if u.lower().startswith("http") else "https://" + u)
    p = safe(path)
    if not p.exists():
        return f"{p} не существует."
    os.startfile(str(p))
    return f"Открыл {p}"


@tool("show_in_explorer", "Показать файл в Проводнике (выделенным) — чтобы пользователь мог его забрать/отправить",
      {"path": S}, ["path"])
def show_in_explorer(path: str) -> str:
    p = safe(path)
    if not p.exists():
        return f"{p} не существует."
    subprocess.Popen(["explorer", "/select,", str(p)])
    return f"Показал в Проводнике: {p}"


@tool("edit_file", "Точечная правка текстового файла: заменить ТОЧНЫЙ фрагмент old на new (old должен встречаться "
      "ровно один раз; скопируй его из read_file дословно). Старая версия сохраняется в .bak",
      {"path": S, "old": S, "new": S}, ["path", "old", "new"], modes=("medium", "high"))
def edit_file(path: str, old: str, new: str) -> str:
    p = safe(path)
    if not p.is_file():
        return f"Файла {p} нет. Для нового файла используй write_file."
    src = p.read_text(encoding="utf-8", errors="replace")
    n = src.count(old)
    if n == 0:
        norm = lambda s: "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").split("\n"))
        if norm(old) and norm(src).count(norm(old)) == 1:
            src, old = norm(src), norm(old)
            n = 1
        else:
            return "Ошибка: фрагмент old не найден. Прочитай файл (read_file) и скопируй фрагмент дословно."
    if n > 1:
        return f"Ошибка: фрагмент old встречается {n} раз — добавь больше соседних строк, чтобы он был уникальным."
    p.with_suffix(p.suffix + ".bak").write_bytes(p.read_bytes())
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    line = src[: src.index(old)].count("\n") + 1
    return f"Изменил {p} (строка {line}: -{old.count(chr(10)) + 1} +{new.count(chr(10)) + 1} строк)."
