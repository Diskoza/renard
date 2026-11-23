"""Long tasks with a working journal — how a small model can work for half an hour without its context overflowing.

The trick: the prompt is NOT a growing chat. Every step it is rebuilt from scratch:
    rules + tools  +  JOURNAL (goal, facts, attempts → result, conclusions, next step)  +  the last 3 results.
So it always fits (~6–9k tokens of a 12–16k context), however long the work goes.

Who writes the journal:
- the SYSTEM logs every attempt itself («probe_app OP Auto Clicker → 36 элементов…») — the model can't forget;
- the MODEL adds facts / conclusions in the "note" field of its step;
- every CHECKPOINT_EVERY steps, or when the journal grows too big, a checkpoint: the model rewrites facts / conclusions /
  next step compactly and old attempts fold into one line («шаги 1–12: …»). That is the «прочистился, перечитал, сделал выводы».
Stops on: done / fail, time or step budget, a step that needs the user's «да», or being stuck twice.
The journal is a normal .md in data/worknotes — the user can open it; «продолжи» resumes from it.
"""
import json
import os
import re
import time
from pathlib import Path
from .logs import quiet

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "data" / "worknotes"
CHECKPOINT_EVERY = 6
JOURNAL_BUDGET = 6000
RESULT_CHARS = 1400
KEEP_RESULTS = 3
MAX_STEPS = 80
SECTIONS = ("Факты", "Данные", "Попытки", "Выводы", "Дальше")
DATA_KEEP = 6
ASK_FIRST = {"app_do"}


class Journal:
    def __init__(self, goal: str, path: Path | None = None):
        self.goal = " ".join(goal.split())
        self.data = {s: [] for s in SECTIONS}
        self.folded = []
        self.step = 0
        self.started = time.time()
        NOTES.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\wа-яё]+", "-", goal.lower())[:40].strip("-")
        self.path = path or NOTES / f"{time.strftime('%Y%m%d_%H%M')}_{slug}.md"

    def add(self, section: str, text: str):
        text = re.sub(r"\s+", " ", str(text)).strip()
        if not text:
            return
        sec = next((s for s in SECTIONS if section.lower().startswith(s.lower()[:4])), "Факты")
        if sec == "Дальше":
            self.data[sec] = [text]
        elif text not in self.data[sec]:
            self.data[sec].append(text[:400])
        self.save()

    def attempt(self, action: str, result: str, ok: bool):
        self.data["Попытки"].append(f"{self.step}. {'✓' if ok else '✗'} {action[:140]} → {_short(result, 220)}")
        if ok and len(result.strip()) > 20 and not result.startswith("ждёт"):
            self.data["Данные"].append(f"шаг {self.step} ({action.split(' ')[0]}): {_short(result, 420)}")
            self.data["Данные"] = self.data["Данные"][-DATA_KEEP:]
        self.save()

    def render(self) -> str:
        out = [f"# Задача: {self.goal}", f"Шаг {self.step}, работаю {int((time.time() - self.started) / 60)} мин."]
        for s in SECTIONS:
            lines = (self.folded if s == "Попытки" else []) + self.data[s]
            if lines:
                out.append(f"## {s}\n" + "\n".join(f"- {x}" for x in lines))
        return "\n".join(out)

    def size(self) -> int:
        return len(self.render())

    def save(self):
        self.path.write_text(self.render() + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Journal":
        t = path.read_text("utf-8")
        goal = re.search(r"^# Задача: (.+)$", t, re.M).group(1)
        j = cls(goal, path)
        cur = None
        for line in t.splitlines():
            m = re.match(r"^## (.+)$", line)
            if m:
                cur = m.group(1).strip() if m.group(1).strip() in SECTIONS else None
            elif cur and line.startswith("- "):
                (j.folded if cur == "Попытки" and line.startswith("- шаги") else j.data[cur]).append(line[2:])
        m = re.search(r"^Шаг (\d+)", t, re.M)
        j.step = int(m.group(1)) if m else 0
        return j

    def compact(self, summary: dict):
        first = self.data["Попытки"][0].split(".")[0] if self.data["Попытки"] else "?"
        what = summary.get("attempts_summary") or "; ".join(a.split("→")[0][3:60] for a in self.data["Попытки"][-4:])
        if self.data["Попытки"]:
            self.folded.append(f"шаги {first}–{self.step}: {_short(what, 300)}")
            self.folded = self.folded[-6:]
        self.data["Попытки"] = []
        for key, sec in (("facts", "Факты"), ("conclusions", "Выводы")):
            if isinstance(summary.get(key), list) and summary[key]:
                self.data[sec] = [_short(x, 300) for x in summary[key]][:12]
        if summary.get("next"):
            self.data["Дальше"] = [_short(summary["next"], 300)]
        self.save()


def _short(s, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse(text: str) -> dict | None:
    text = text or ""
    block = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    head = text[:block.start()] + text[block.end():] if block else text
    m = re.search(r"\{.*\}", head, re.S)
    d = None
    if m:
        raw = m.group(0)
        for cand in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                d = json.loads(cand, strict=False)
                break
            except ValueError:
                continue
        if d is None:
            t = re.search(r'"tool"\s*:\s*"(\w+)"', raw)
            c = re.search(r'"code"\s*:\s*"(.*?)"\s*}\s*(?:,|}|$)', raw, re.S)
            if t:
                code = re.sub(r'\\(["\\/nt])', lambda x: {"n": "\n", "t": "\t"}.get(x.group(1), x.group(1)), c.group(1)) if c else ""
                d = {"tool": t.group(1), "args": {"code": code} if code else {}}
                n = re.search(r'"note"\s*:\s*"([^"]*)"', raw)
                if n:
                    d["note"] = n.group(1)
    if d is not None and block and isinstance(d.get("args"), dict) and not d["args"].get("code"):
        d["args"]["code"] = block.group(1)
    if d is None and block:
        d = {"tool": "pc_script", "args": {"code": block.group(1)}}
    return d


STEP_PROMPT = """Ты Renard и сам долго работаешь над задачей пользователя на его ПК. У тебя маленькая память, поэтому всё
важное хранится в ЖУРНАЛЕ ниже: доверяй ему, а не догадкам. Каждый ход — ОДИН JSON без другого текста:
{{"think":"что известно и какой шаг сейчас (коротко)","tool":"имя","args":{{...}},"note":"новый факт/вывод для журнала или пусто"}}
Закончил: {{"done":true,"answer":"итог для пользователя по-русски: что выяснил/сделал, что не вышло"}}
Не получается вообще: {{"fail":true,"answer":"почему и что нужно от пользователя"}}

Правила:
- Сначала разберись (читать/смотреть можно без спроса), потом действуй. Изменения на ПК система подтвердит у пользователя.
- Не повторяй попытку, которая в журнале уже ✗ — придумай другой путь.
- В note пиши только проверенное («в config.json поле interval = 100»), не планы.
- Раздел «Данные» — то, что шаги уже РЕАЛЬНО нашли. Если там уже есть ответ на задачу — сразу done с этими данными,
  не пересчитывай заново и не «улучшай» формат.
- Цель достигнута и проверена — сразу done.
- Код для pc_script удобнее писать ОТДЕЛЬНЫМ блоком ```python … ``` сразу после JSON (в JSON тогда "args":{{}}).
  В скрипте уже есть готовые функции — пользуйся ими, а не os.walk: app_dirs('Имя') — папки программы,
  find_files(папка, '*.json') — файлы, read_config(путь), reg_read(r'HKCU\\Software\\Имя'), fields('Окно').
  Путь — r'C:\\Папка\\Файл' без «\\» в конце строки.

ИНСТРУМЕНТЫ:
{tools}
{skills}"""

FINAL_PROMPT = """Время работы над задачей вышло. Задача: {goal}
По журналу ниже напиши пользователю итог по-русски, коротко и КОНКРЕТНО:
1) что нашёл — с цифрами и путями из разделов «Факты» и «Данные» (самое крупное сначала);
2) план: 3–6 конкретных шагов, каждый с ожидаемым результатом (сколько ГБ / что изменится);
3) что требует его решения или «да».
Только то, что есть в журнале, — ничего не придумывай. Без вступлений.
Смотри на путь каждого объекта: если задача про конкретный диск/папку, в план бери только то, что лежит ТАМ
(C:\\Users\\…\\AppData — это диск C:\\, а не другой диск). Не обещай удалять сам — только «могу после твоего да»."""

CHECK_PROMPT = """Пора сжать журнал, чтобы освободить память. Раздел «Данные» система сохранит сама — не теряй
из фактов то, что там уже найдено. Перечитай журнал и ответь ОДНИМ JSON:
{"facts":["проверенные факты, самое важное, до 10"],"conclusions":["выводы: что работает, что нет и почему, до 6"],
 "attempts_summary":"одна строка: что пробовал на этих шагах и чем кончилось",
 "next":"следующий конкретный шаг (если застрял — ДРУГОЙ подход, чем раньше)","stuck":false}
stuck=true, если за последние шаги нет продвижения."""


async def long_task(agent, goal: str, ctx: dict, tool_specs: list[tuple[str, str]], call_tool,
                    minutes: float = 30, mode: str = "study", resume: str = "") -> str:
    """agent.llm.chat(mode, msgs) → {"message":{"content"}}; call_tool(name, args) → str (async);
    tool_specs — [(name, one-line description)] the model may use."""
    j = Journal.load(Path(resume)) if resume else Journal(goal)
    send = ctx.get("send")
    cancelled = ctx.get("cancelled") or (lambda: False)
    tools_txt = "\n".join(f"- {n}: {d[:160]}" for n, d in tool_specs)
    names = {n for n, _ in tool_specs}
    skills = ""
    try:
        from . import skills_auto
        skills, _ = skills_auto.prompt_block(goal, k=1)
    except Exception:
        quiet()
    system = STEP_PROMPT.format(tools=tools_txt, skills=skills) + "\n" + drives_line()
    recent: list[str] = []
    deadline = time.time() + minutes * 60
    stuck_count, errors_row = 0, 0

    async def note(text):
        if send:
            await send({"type": "note", "text": text[:140]})

    async def ask(msgs):
        r = await agent.llm.chat(mode, msgs)
        return (r.get("message") or {}).get("content", "")

    async def checkpoint():
        nonlocal stuck_count
        reply = await ask([{"role": "system", "content": CHECK_PROMPT},
                           {"role": "user", "content": j.render() + "\n\nПоследние результаты:\n" + "\n".join(recent)}])
        s = _parse(reply) or {}
        j.compact(s)
        recent.clear()
        if s.get("stuck"):
            stuck_count += 1
        await note(f"📝 сжал журнал: {_short(s.get('next', ''), 90)}")

    await note(f"🧭 долгая задача: {_short(goal, 80)} (до {int(minutes)} мин), журнал {j.path.name}")
    while True:
        if cancelled():
            return f"Остановлено по просьбе. Журнал: {j.path}\n" + _short(" ".join(j.data["Выводы"]), 600)
        if time.time() > deadline or j.step >= MAX_STEPS:
            await checkpoint()
            final = await ask([{"role": "system", "content": FINAL_PROMPT.format(goal=j.goal)},
                               {"role": "user", "content": j.render()}])
            final = re.sub(r"^```\w*|```$", "", (final or "").strip()).strip()
            if len(final) < 40:
                final = "Что выяснил:\n" + "\n".join(f"- {x}" for x in (j.data["Факты"] + j.data["Выводы"])[:10])
            j.add("Выводы", "промежуточный итог (время вышло): " + _short(final, 300))
            return (f"ВРЕМЯ ВЫШЛО ({int(minutes)} мин, {j.step} шагов) — промежуточный итог:\n{final}\n"
                    f"(журнал: {j.path}; «продолжи» — продолжу с этого места)\n"
                    "[Перескажи пользователю этот итог как есть, с цифрами; ничего не добавляй от себя.]")
        if stuck_count >= 2:
            j.add("Выводы", "промежуточный итог: застрял, нет продвижения")
            return ("Застрял: два раза подряд нет продвижения. Что выяснил:\n" +
                    "\n".join(f"- {x}" for x in (j.data["Выводы"] + j.data["Факты"])[:8]) + f"\nЖурнал: {j.path}")
        j.step += 1
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": j.render() + ("\n\nПОСЛЕДНИЕ РЕЗУЛЬТАТЫ:\n" + "\n".join(recent) if recent else "")
                 + "\n\nТвой следующий ход (один JSON):"}]
        a = _parse(await ask(msgs))
        if not a:
            j.attempt("(ответ не JSON)", "повтори одним JSON", False)
            errors_row += 1
            if errors_row >= 4:
                await checkpoint(); errors_row = 0
            continue
        if a.get("note"):
            j.add("Выводы" if re.search(r"вывод|значит|причина|работает|не работает", str(a["note"]), re.I) else "Факты", a["note"])
        if a.get("done") or a.get("fail"):
            j.add("Выводы", ("ИТОГ: " if a.get("done") else "НЕ ВЫШЛО: ") + str(a.get("answer", "")))
            head = "ЗАДАЧА ВЫПОЛНЕНА. " if a.get("done") else "НЕ ВЫШЛО. "
            return (head + str(a.get("answer") or "Готово.") + f"\n(журнал: {j.path})\n"
                    "[Перескажи пользователю этот итог как есть, своими словами не добавляй «не могу» — работа уже сделана.]")
        name, args = str(a.get("tool", "")), a.get("args") or {}
        action = f"{name} {json.dumps(args, ensure_ascii=False)}"
        if name in ASK_FIRST and hasattr(agent, "pending"):
            agent.pending = {"name": name, "args": args}
            j.attempt(action, "ждёт «да» пользователя", True)
            j.add("Дальше", f"после «да» на {action[:120]} — проверить результат; «продолжи»")
            await note(f"⏸ нужно «да»: {_short(action, 90)}")
            return (f"Дошёл до шага, который меняет программу: {name} {json.dumps(args, ensure_ascii=False)[:200]}. "
                    f"Сделать? Ответь «да» — выполню, потом скажи «продолжи».\n(журнал: {j.path})")
        if name.lower() in ("", "none", "null", "done", "answer"):
            res, ok = 'инструмент не нужен? Если ответ уже есть в журнале — ответь {"done":true,"answer":"…"}', False
        elif name not in names:
            res, ok = f"нет инструмента «{name}». Есть: {', '.join(sorted(names))[:300]}", False
        elif any(action == x.split(". ", 1)[-1][2:].split(" → ")[0] for x in j.data["Попытки"]):
            res, ok = "эта попытка уже была — смотри журнал и выбери другой путь", False
        else:
            await note(f"шаг {j.step}: {_short(action, 100)}")
            try:
                res = str(await call_tool(name, args))
                ok = not re.match(r"(ошибка|error|не нашёл|не найден|не получилось|нет элемента|traceback|скрипт не уложился|"
                                  r"нужно подтверждение)", res.strip(), re.I) and "ОШИБКА:" not in res
            except Exception as e:
                res, ok = f"ошибка: {type(e).__name__}: {e}", False
        errors_row = 0 if ok else errors_row + 1
        j.attempt(action, res, ok)
        recent.append(f"[шаг {j.step}] {action[:120]} →\n{_short(res, RESULT_CHARS)}")
        recent[:] = recent[-KEEP_RESULTS:]
        if getattr(agent, "pending", None):
            j.add("Дальше", f"ждёт подтверждения пользователя: {action[:150]}; после «да» — «продолжи»")
            return f"{_short(res, 600)}\n\nОстановился: нужно твоё «да». Потом скажи «продолжи» — вернусь к задаче.\n(журнал: {j.path})"
        if j.step % CHECKPOINT_EVERY == 0 or j.size() > JOURNAL_BUDGET or errors_row >= 3:
            await checkpoint()
            errors_row = 0


def drives_line() -> str:
    """The PC disks as they really are, including disks mounted as folders."""
    try:
        import psutil
        import shutil
        parts = []
        for p in psutil.disk_partitions(all=False):
            u = shutil.disk_usage(p.mountpoint)
            kind = "отдельный диск, подключён как ПАПКА" if len(p.mountpoint.rstrip("\\")) > 2 else "диск"
            parts.append(f"{p.mountpoint} — {kind}, {u.total / 2**30:.0f} ГБ, свободно {u.free / 2**30:.0f} ГБ "
                         f"({100 * u.free / u.total:.0f}%)")
        for extra in ():
            if os.path.isdir(extra) and not any(extra in x for x in parts):
                u = shutil.disk_usage(extra)
                parts.append(f"{extra} — отдельный SSD, подключён как ПАПКА, {u.total / 2**30:.0f} ГБ, "
                             f"свободно {u.free / 2**30:.0f} ГБ ({100 * u.free / u.total:.0f}%)")
        return "ДИСКИ ПК: " + "; ".join(parts) + "."
    except Exception:
        return ""


def unfinished(text: str, hours: float = 3) -> Path | None:
    """The latest journal that has no final result yet (stopped / ran out of time), if the request continues it:
    «продолжи…», or most of the words of its goal are in the request."""
    from .skills_auto import stems
    for p in latest(3):
        if time.time() - p.stat().st_mtime > hours * 3600:
            break
        t = p.read_text("utf-8", "replace")
        if re.search(r"^- (ИТОГ|НЕ ВЫШЛО):", t, re.M):
            continue
        goal = (re.search(r"^# Задача: (.+)$", t, re.M) or [None, ""])[1]
        g, q = stems(goal), stems(text)
        if re.search(r"(?i)продолж|дальше|доделай|закончи", text) or (g and len(g & q) / len(g) >= 0.5):
            return p
    return None


def latest(n: int = 5) -> list[Path]:
    return sorted(NOTES.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:n] if NOTES.is_dir() else []
