"""Make and convert office documents for real (the files exist afterwards and their paths go into the answer,
so the chat shows them as attachments):
- convert_document: any office format -> pdf / docx / odt / xlsx / pptx … through LibreOffice (headless, own profile);
- make_document: a document from simple markdown (headings, lists, tables, a column split with a divider line),
  laid out on a page (A4 / A5 / card, portrait / landscape, centred, font size) -> docx (+ pdf, odt).
  fit=true picks the largest font at which everything still fits on ONE page (cards, posters for the kitchen…)."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import I, S, tool
from ..logs import quiet

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
B = {"type": "boolean"}


def soffice() -> str:
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if os.path.exists(p):
            return p
    return shutil.which("soffice") or ""


def _profile() -> str:
    from ..config import DATA_DIR
    d = DATA_DIR / "lo_profile"
    d.mkdir(parents=True, exist_ok=True)
    return "file:///" + str(d).replace("\\", "/")


def _tree(pid: int) -> list:
    import psutil
    try:
        p = psutil.Process(pid)
        return [p] + p.children(recursive=True)
    except psutil.Error:
        return []


def _hide_windows(pids: set[int]):
    """Headless LibreOffice still pops «Ожидание подключения принтера…» when his default printer (Wi-Fi) is off —
    that box must not sit on his screen: hide every window of our converter."""
    import ctypes
    u = ctypes.windll.user32
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(h):
            found.append(h)
        return True
    u.EnumWindows(WNDENUMPROC(cb), 0)
    for h in found:
        u.ShowWindow(h, 0)
    return len(found)


def _kill_leftovers():
    """soffice.bin of OUR profile left from a killed run keeps the profile locked and its dialog on screen."""
    import psutil
    mark = _profile().replace("file:///", "").replace("/", "\\").lower()
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower().startswith("soffice") and \
                    mark in " ".join(p.info["cmdline"] or []).replace("/", "\\").lower():
                p.kill()
        except psutil.Error:
            pass


def _run_soffice(args: list, timeout: int) -> tuple[int, str]:
    import time as _t
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                         encoding="utf-8", errors="replace")
    t0, hidden = _t.time(), 0
    while p.poll() is None:
        if _t.time() - t0 > timeout:
            for q in reversed(_tree(p.pid)):
                try:
                    q.kill()
                except Exception:
                    quiet()
            raise RuntimeError(f"LibreOffice завис дольше {timeout} с" + (" (ждал принтер по умолчанию — он, похоже, "
                               "выключен)" if hidden else "") + " — остановил его")
        hidden += _hide_windows({q.pid for q in _tree(p.pid)})
        _t.sleep(0.25)
    return p.returncode, (p.stdout.read() if p.stdout else "")


def _convert(src: Path, fmt: str, outdir: Path, timeout: int = 90) -> Path:
    exe = soffice()
    if not exe:
        raise RuntimeError("LibreOffice не установлен (нужен для конвертации). Установи: install_app(name='LibreOffice')")
    outdir.mkdir(parents=True, exist_ok=True)
    target = fmt
    if fmt == "pdf" and src.suffix.lower() in (".odp", ".pptx", ".ppt"):
        target = "pdf:impress_pdf_Export"
    elif fmt == "pdf" and src.suffix.lower() in (".ods", ".xlsx", ".xls", ".csv"):
        target = "pdf:calc_pdf_Export"
    with tempfile.TemporaryDirectory() as tmp:
        _kill_leftovers()
        code, out = _run_soffice([exe, f"-env:UserInstallation={_profile()}", "--headless", "--norestore",
                                  "--convert-to", target, "--outdir", tmp, str(src)], timeout)
        made = list(Path(tmp).glob(f"*.{fmt}"))
        if not made:
            raise RuntimeError(f"LibreOffice не создал .{fmt}: {out.strip()[:300]}")
        dst = _free(outdir / (src.stem + "." + fmt))
        shutil.move(str(made[0]), dst)
    return dst


def _convert_many(srcs: list[Path], fmt: str, outdir: Path, timeout: int = 150) -> dict:
    """Several files in ONE LibreOffice launch: every launch costs ~20 s here (it probes the default printer),
    the files themselves take a second each. {src: result path} for the ones that converted."""
    exe = soffice()
    if not exe or not srcs:
        return {}
    outdir.mkdir(parents=True, exist_ok=True)
    _kill_leftovers()
    _run_soffice([exe, f"-env:UserInstallation={_profile()}", "--headless", "--norestore", "--convert-to", fmt,
                  "--outdir", str(outdir), *map(str, srcs)], timeout)
    return {p: outdir / f"{p.stem}.{fmt}" for p in srcs if (outdir / f"{p.stem}.{fmt}").exists()}


def _free(p: Path) -> Path:
    """Never overwrite: «X.pdf» -> «X (2).pdf» if it exists and is in use; overwrite our own earlier result otherwise."""
    if not p.exists():
        return p
    try:
        with open(p, "ab"):
            pass
        p.unlink()
        return p
    except OSError:
        i = 2
        while (q := p.with_name(f"{p.stem} ({i}){p.suffix}")).exists():
            i += 1
        return q


def _outdir(src: Path | None) -> Path:
    """Next to the source — but files the user sent into the chat (workspace/uploads) go to Documents\\Renard."""
    if src is not None and "uploads" not in [x.lower() for x in src.parts] and os.access(src.parent, os.W_OK):
        return src.parent
    home = Path.home()
    for d in (home / "OneDrive" / "Documents", home / "Documents"):
        if d.exists():
            return d / "Renard"
    return home / "Documents" / "Renard"


@tool("convert_document", "Сконвертировать документ/таблицу/презентацию в другой формат через LibreOffice: "
                          "to = pdf | docx | odt | doc | rtf | txt | html | xlsx | ods | csv | pptx | odp (можно несколько через запятую). "
                          "Файл реально создаётся; в ответе дай его полный путь — чат покажет его как вложение.",
      {"path": S, "to": S}, ["path", "to"])
def convert_document(path: str, to: str = "pdf") -> str:
    from .files import safe
    src = safe(path)
    if not src.is_file():
        return f"Файла {src} нет."
    out = []
    for fmt in [f.strip().lower().lstrip(".") for f in re.split(r"[,;\s]+", to or "pdf") if f.strip()]:
        fmt = {"word": "docx", "ворд": "docx", "excel": "xlsx", "powerpoint": "pptx"}.get(fmt, fmt)
        try:
            out.append(str(_convert(src, fmt, _outdir(src))))
        except Exception as e:
            out.append(f"{fmt}: ошибка — {e}")
    ok = [o for o in out if re.match(r"^[A-Za-z]:\\", o)]
    return ("Готово, файлы созданы:\n" + "\n".join(ok) if ok else "Не получилось.") + \
        ("\n" + "\n".join(o for o in out if o not in ok) if len(ok) < len(out) else "")


PAGES = {"a4": (21.0, 29.7), "a5": (14.8, 21.0), "a6": (10.5, 14.8), "letter": (21.59, 27.94), "card": (14.8, 21.0)}


def _runs(par, text: str, size: float | None, bold: bool = False):
    from docx.shared import Pt
    for i, part in enumerate(re.split(r"\*\*", text)):
        if not part:
            continue
        r = par.add_run(part)
        r.bold = bold or i % 2 == 1
        if size:
            r.font.size = Pt(size)


def _hr(par):
    """A horizontal divider line under the paragraph."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ppr = par._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "12"), ("space", "1"), ("color", "444444")):
        b.set(qn("w:" + k), v)
    bdr.append(b)
    ppr.append(bdr)


def _cell_border(cell, side: str, sz: int = 12):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcpr.append(borders)
    e = OxmlElement(f"w:{side}")
    for k, v in (("val", "single"), ("sz", str(sz)), ("space", "0"), ("color", "444444")):
        e.set(qn("w:" + k), v)
    borders.append(e)


def _table_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    if rows:
        n = max(len(r) for r in rows)
        keep = [ci for ci in range(n) if any(ci < len(r) and r[ci] for r in rows)]
        rows = [[r[ci] if ci < len(r) else "" for ci in keep] for r in rows]
    return rows


def _render_blocks(container, md: str, size: float, align, first: bool = True):
    """Markdown-lite into a docx container (document or table cell)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    lines = md.strip("\n").splitlines()
    i = 0
    used_first = False

    def para():
        nonlocal used_first
        if not first and not used_first and hasattr(container, "paragraphs") and container.paragraphs \
                and not container.paragraphs[0].text:
            used_first = True
            return container.paragraphs[0]
        return container.add_paragraph()

    while i < len(lines):
        ln = lines[i].rstrip()
        is_row = lambda s: "|" in s and not re.fullmatch(r"\s*\|{3}\s*", s)
        if is_row(ln) and (ln.strip().startswith("|") or (i + 1 < len(lines) and is_row(lines[i + 1]))):
            block = []
            while i < len(lines) and is_row(lines[i]):
                block.append(lines[i]); i += 1
            rows = _table_rows(block)
            header = any(re.fullmatch(r"\s*\|?\s*:?-{2,}.*", b) for b in block[1:2])
            if rows:
                ncol = max(len(r) for r in rows)
                t = container.add_table(rows=len(rows), cols=ncol)
                try:
                    t.style = "Table Grid"
                except Exception:
                    quiet()
                longest = [max(len(r[ci]) if ci < len(r) else 0 for r in rows) + 3 for ci in range(ncol)]
                total = getattr(container, "width", None) or (9000 * 635)
                t.autofit = False
                widths = [int(total * 0.96 * n / sum(longest)) for n in longest]
                for ci, wd in enumerate(widths):
                    t.columns[ci].width = wd
                for ri, r in enumerate(rows):
                    for ci in range(ncol):
                        c = t.cell(ri, ci)
                        c.width = widths[ci]
                        p = c.paragraphs[0]
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if ci else align
                        _runs(p, r[ci] if ci < len(r) else "", size, bold=header and ri == 0)
                container.add_paragraph().paragraph_format.space_after = Pt(0)
            continue
        p_text = ln.strip()
        if re.fullmatch(r"-{3,}|_{3,}|\*{3,}", p_text):
            p = para(); _hr(p); i += 1; continue
        m = re.match(r"^(#{1,3})\s+(.*)", p_text)
        p = para()
        p.paragraph_format.space_after = Pt(size * 0.3)
        if m:
            lvl = len(m.group(1))
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _runs(p, m.group(2), size * {1: 1.6, 2: 1.3, 3: 1.12}[lvl], bold=True)
        elif re.match(r"^[-*•]\s+", p_text):
            p.alignment = align
            _runs(p, "• " + re.sub(r"^[-*•]\s+", "", p_text), size)
        else:
            p.alignment = align
            if "\t" in ln or re.search(r" {3,}", ln):
                p_text = re.sub(r"\s{3,}|\t+", "  —  ", p_text)
            _runs(p, p_text, size)
        i += 1


def _broken_words(pdf: Path, content: str) -> int:
    """How many words of the text the PDF splits over two lines («Wątro|ba» in a narrow column at a big font)."""
    try:
        from pypdf import PdfReader
        text = " ".join(pg.extract_text() or "" for pg in PdfReader(str(pdf)).pages)
    except Exception:
        return 0
    flat = re.sub(r"\s+", " ", text)
    words = {w for w in re.findall(r"[^\W\d_]{5,}", content or "")}
    return sum(1 for w in words if w not in flat)


def _inline_columns(content: str) -> str:
    """The model put the column break INSIDE table rows («| 1 × | 0,190 | ||| | Gulasz |») instead of on its own line:
    split such a table into a left table, a «|||» line and a right table (the side-by-side layout it meant)."""
    lines = (content or "").split("\n")
    out, i = [], 0
    while i < len(lines):
        if not lines[i].strip().startswith("|"):
            out.append(lines[i]); i += 1; continue
        j = i
        while j < len(lines) and lines[j].strip().startswith("|"):
            j += 1
        block = lines[i:j]
        if not any(re.search(r"\S.*\|\|\|.*\S", ln) and ln.strip() != "|||" for ln in block):
            out.extend(block); i = j; continue
        head = next(ln for ln in block if "|||" in ln)
        n_left = len([c for c in head.strip().split("|||")[0].strip().strip("|").split("|")])
        left, right = [], []
        for ln in block:
            t = ln.strip()
            if "|||" in t:
                l_, r_ = t.split("|||", 1)
                lc = [c.strip() for c in l_.strip().strip("|").split("|")]
                rc = [c.strip() for c in r_.strip().strip("|").split("|")]
            else:
                cells = [c.strip() for c in t.strip("|").split("|")]
                lc, rc = cells[:n_left], cells[n_left:]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in lc + rc if c):
                lc, rc = ["---"] * n_left, ["---"] * max(1, len(head.split("|||", 1)[1].strip().strip("|").split("|")))
            if any(lc):
                left.append("| " + " | ".join(lc) + " |")
            if any(rc):
                right.append("| " + " | ".join(rc) + " |")
        out.extend(left + ["|||"] + right)
        i = j
    return "\n".join(out)


def _build_docx(dst: Path, title: str, content: str, page: str, landscape: bool, size: float, align_s: str,
                margins_cm: float):
    import docx
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(size)
    sec = d.sections[0]
    w, h = PAGES.get((page or "a4").lower(), PAGES["a4"])
    if landscape:
        w, h = h, w
        sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(w), Cm(h)
    for k in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, k, Cm(margins_cm))
    align = {"center": WD_ALIGN_PARAGRAPH.CENTER, "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT,
             "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}.get((align_s or "left").lower(), WD_ALIGN_PARAGRAPH.LEFT)
    if title:
        p = d.paragraphs[0] if d.paragraphs else d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _runs(p, title, size * 1.6, bold=True)
        p.paragraph_format.space_after = Pt(size * 0.6)
    if title:
        content = re.sub(r"\A\s*#{1,3}\s*" + re.escape(title.strip()) + r"\s*\n", "", content or "", flags=re.I)
    content = _inline_columns(content)
    parts = re.split(r"(?m)^\s*(?:\|\|\||={3,}\s*колонк\w*\s*={3,}|={3,}\s*columns?\s*={3,})\s*$", content or "")
    if len(parts) > 1:
        t = d.add_table(rows=1, cols=len(parts))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        for ci, part in enumerate(parts):
            t.columns[ci].width = Cm((w - 2 * margins_cm) / len(parts))
            c = t.cell(0, ci)
            c.width = Cm((w - 2 * margins_cm) / len(parts) - 0.4)
            if ci:
                _cell_border(c, "left", 16)
            _render_blocks(c, part, size, align, first=False)
    else:
        _render_blocks(d, content or "", size, align)
    d.core_properties.title = title or dst.stem
    d.save(str(dst))


def _pdf_pages(p: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(p)).pages)
    except Exception:
        return len(re.findall(rb"/Type\s*/Page(?!s)", p.read_bytes()))


@tool("make_document", "СОЗДАТЬ документ (Word docx + pdf/odt) из текста в простом markdown: # заголовок, - список, "
                       "таблицы | a | b |, --- горизонтальная линия, строка ||| делит страницу на колонки с вертикальной "
                       "разделительной линией. page = a4 | a5 | a6 | letter, landscape=true — альбомная, align = left | "
                       "center | justify, font_size (пт), fit=true — подобрать самый крупный шрифт, чтобы всё влезло на ОДНУ "
                       "страницу (карточки, памятки на кухню, плакаты). formats = 'docx,pdf' (ещё odt). "
                       "Чтобы «подровнять/переделать» чужой документ: прочитай его (read_file), сам перепиши содержимое "
                       "аккуратной структурой и вызови make_document. Файлы реально создаются — в ответе дай их пути. "
                       "Пример карточки в две колонки (каждая строка таблицы — с | по краям, отдельной строкой): "
                       "«## Порции\\n| Кол-во | Вес |\\n| --- | --- |\\n| 1 × | 0,190 |\\n| 2 × | 0,380 |\\n|||\\n## Блюда\\n"
                       "| Блюдо | Граммы |\\n| --- | --- |\\n| Gulasz | 50 / 50 |». Разные по смыслу данные (шкала и "
                       "список блюд) — в разные таблицы/колонки, не в одну.",
      {"name": S, "content": S, "title": S, "formats": S, "page": S, "landscape": B, "align": S, "font_size": I,
       "fit": B, "folder": S}, ["name", "content"])
def make_document(name: str, content: str, title: str = "", formats: str = "docx,pdf", page: str = "a4",
                  landscape: bool = False, align: str = "left", font_size: int = 0, fit: bool = False,
                  folder: str = "") -> str:
    from .files import safe
    try:
        import docx
    except ImportError:
        return "Нет python-docx. Установи в venv: pip install python-docx"
    landscape = str(landscape).lower() in ("true", "1", "yes", "да")
    fit = str(fit).lower() in ("true", "1", "yes", "да")
    outdir = safe(folder) if folder else _outdir(None)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[\\/:*?"<>|]+', " ", Path(name or "Документ").stem).strip() or "Документ"
    fmts = [f.strip().lower().lstrip(".") for f in re.split(r"[,;\s]+", formats or "docx,pdf") if f.strip()]
    fmts = [{"word": "docx", "ворд": "docx"}.get(f, f) for f in fmts] or ["docx", "pdf"]
    margins = 1.2 if (page or "a4").lower() in ("a5", "a6", "card") else 1.8
    size = float(font_size or (12 if not fit else 14))
    docx_path = _free(outdir / f"{stem}.docx")
    note = ""
    fit_pdf = None
    if fit and soffice():
        keep = Path(tempfile.mkdtemp(prefix="renard_fit_"))

        def batch(sizes, tag):
            probes = {}
            for sz in sizes:
                pth = keep / f"{tag}_{str(sz).replace('.', '_')}.docx"
                _build_docx(pth, title, content, page, landscape, sz, align, margins)
                probes[sz] = pth
            pdfs = _convert_many(list(probes.values()), "pdf", keep / "pdf")
            return {sz: (_pdf_pages(pdfs[p]) + (1 if _broken_words(pdfs[p], content) else 0), pdfs[p])
                    for sz, p in probes.items() if p in pdfs}
        try:
            r1 = batch([7, 9, 11.5, 14.5, 18, 23, 29, 36], "a")
            ok = sorted(sz for sz, (n, _) in r1.items() if n <= 1)
            lo = ok[-1] if ok else 7
            hi = min([sz for sz in r1 if sz > lo], default=40)
            r2 = batch([round(lo + (hi - lo) * k / 6, 1) for k in range(1, 6)], "b") if hi - lo > 0.6 else {}
            ok2 = sorted(sz for sz, (n, _) in r2.items() if n <= 1)
            size = ok2[-1] if ok2 else lo
            fit_pdf = (r2.get(size) or r1.get(size) or (None, None))[1]
            note = f" Шрифт подобран: {size:g} пт — всё на одной странице." if (ok or ok2) else \
                " Даже при 7 пт не влезает на одну страницу — сократи текст или выбери формат больше."
        except Exception as e:
            note = f" Подбор шрифта не удался ({e}) — оставил {size:g} пт."
    _build_docx(docx_path, title, content, page, landscape, size, align, margins)
    made = []
    if "docx" in fmts:
        made.append(docx_path)
    for f in fmts:
        if f == "docx":
            continue
        try:
            if f == "pdf" and fit_pdf and fit_pdf.exists():
                dst = _free(outdir / f"{stem}.pdf")
                shutil.copy2(fit_pdf, dst)
                made.append(dst)
            else:
                made.append(_convert(docx_path, f, outdir))
        except Exception as e:
            note += f" {f}: не получилось — {e}."
    if fit_pdf:
        shutil.rmtree(fit_pdf.parent.parent, ignore_errors=True)
    if "docx" not in fmts:
        docx_path.unlink(missing_ok=True)
    if not made:
        return "Документ не создан." + note
    pages = next((_pdf_pages(p) for p in made if p.suffix == ".pdf"), None)
    return ("Создал файлы (они существуют, дай пользователю эти пути — чат покажет их как вложения):\n"
            + "\n".join(str(p) for p in made) + (f"\nСтраниц в pdf: {pages}." if pages else "") + note)
