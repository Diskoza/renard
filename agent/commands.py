"""Node commands («Команды»): a Drawflow graph = triggers -> actions. Stored in data/commands.json.

Triggers: phrase (said or typed, works without LLM), hotkey (global, registered by the desktop app), manual.
Actions run in order along the connections; «если процесс запущен» has two outputs (да / нет).
Text fields may use {last} — the previous result (e.g. the answer of «Спросить ИИ»).
"""
import asyncio
import json
import re
import time
import uuid
import webbrowser

from .command_nodes import NEW_NODES
from .config import DATA_DIR

PATH = DATA_DIR / "commands.json"

NODES = {
    "trigger_phrase": {"title": "Фраза", "group": "trigger", "icon": "💬", "in": 0, "out": 1,
                       "fields": [["phrases", "фразы через запятую", "громче, сделай громче"]]},
    "trigger_hotkey": {"title": "Горячая клавиша", "group": "trigger", "icon": "⌨", "in": 0, "out": 1,
                       "fields": [["combo", "сочетание", "ctrl+alt+y"]]},
    "trigger_manual": {"title": "Вручную", "group": "trigger", "icon": "▶", "in": 0, "out": 1, "fields": []},
    "open_url": {"title": "Открыть URL", "group": "action", "icon": "🌐", "in": 1, "out": 1,
                 "fields": [["url", "адрес", "https://youtube.com"]]},
    "open_app": {"title": "Запустить программу", "group": "action", "icon": "🚀", "in": 1, "out": 1,
                 "fields": [["name", "программа", "spotify"]]},
    "close_app": {"title": "Закрыть программу", "group": "action", "icon": "✖", "in": 1, "out": 1,
                  "fields": [["name", "программа", "chrome"]]},
    "type_text": {"title": "Ввести текст", "group": "action", "icon": "⌨", "in": 1, "out": 1,
                  "fields": [["text", "текст", "lofi hip hop"]]},
    "keys": {"title": "Нажать клавиши", "group": "action", "icon": "⌘", "in": 1, "out": 1,
             "fields": [["combo", "клавиши", "enter"]]},
    "media": {"title": "Медиа", "group": "action", "icon": "⏯", "in": 1, "out": 1,
              "fields": [["action", "play_pause / next / prev / mute", "play_pause"]]},
    "volume": {"title": "Громкость", "group": "action", "icon": "🔊", "in": 1, "out": 1,
               "fields": [["mode", "add или set", "add"], ["value", "значение", "10"]]},
    "notify": {"title": "Уведомление", "group": "action", "icon": "🔔", "in": 1, "out": 1,
               "fields": [["text", "текст", "Готово"]]},
    "say": {"title": "Произнести", "group": "action", "icon": "🗣", "in": 1, "out": 1,
            "fields": [["text", "что сказать", "{last}"]]},
    "ask_ai": {"title": "Спросить ИИ", "group": "action", "icon": "✻", "in": 1, "out": 1,
               "fields": [["prompt", "запрос", "Какая погода на сегодня? Ответь коротко."]]},
    "radio": {"title": "Радио", "group": "action", "icon": "📻", "in": 1, "out": 1,
              "fields": [["station", "станция", "record"]]},
    "telegram": {"title": "В Telegram", "group": "action", "icon": "✈", "in": 1, "out": 1,
                 "fields": [["text", "текст", "{last}"]]},
    "minimize": {"title": "Свернуть все окна", "group": "action", "icon": "🗕", "in": 1, "out": 1, "fields": []},
    "wait": {"title": "Пауза", "group": "logic", "icon": "⏱", "in": 1, "out": 1,
             "fields": [["seconds", "секунд", "2"]]},
    "if_process": {"title": "Программа запущена?", "group": "logic", "icon": "⑂", "in": 1, "out": 2,
                   "fields": [["name", "процесс", "spotify"]], "outs": ["да", "нет"]},
    "trigger_schedule": {"title": "По расписанию", "group": "trigger", "icon": "🕒", "in": 0, "out": 1,
                         "fields": [["when", "daily 08:30 / weekdays 09:00 / every 60m / weekly sat 10:00", "daily 08:30"]]},
    "repeat": {"title": "Повторить с начала", "group": "logic", "icon": "🔁", "in": 1, "out": 1,
               "fields": [["times", "Сколько раз всего", "4"]]},
    "if_time": {"title": "Если время", "group": "logic", "icon": "⏰", "in": 1, "out": 2,
                "fields": [["from", "С (ЧЧ:ММ)", "09:00"], ["to", "До (ЧЧ:ММ)", "18:00"]], "outs": ["Да", "Нет"]},
    "if_window": {"title": "Если открыто окно", "group": "logic", "icon": "🪟", "in": 1, "out": 2,
                  "fields": [["title", "Часть заголовка окна", "YouTube"]], "outs": ["Да", "Нет"]},
    "if_text": {"title": "Если в результате есть", "group": "logic", "icon": "🔎", "in": 1, "out": 2,
                "fields": [["text", "Слово / фраза (ищется в {last})", "ошибка"]], "outs": ["Да", "Нет"]},
    "clipboard_get": {"title": "Взять буфер обмена", "group": "action", "icon": "📋", "in": 1, "out": 1, "fields": []},
    "selected_text": {"title": "Взять выделенный текст", "group": "action", "icon": "🖱", "in": 1, "out": 1, "fields": []},
    "clipboard_set": {"title": "Положить в буфер", "group": "action", "icon": "📋", "in": 1, "out": 1,
                      "fields": [["text", "Текст", "{last}"]]},
    "paste_text": {"title": "Вставить текст", "group": "action", "icon": "⎘", "in": 1, "out": 1,
                   "fields": [["text", "Текст (через буфер — любые символы)", "{last}"]]},
    "ai_text": {"title": "ИИ: обработать текст", "group": "action", "icon": "✨", "in": 1, "out": 1,
                "fields": [["task", "Что сделать с текстом", "Переведи на русский"], ["text", "Текст", "{last}"]]},
    "open_path": {"title": "Открыть файл / папку", "group": "action", "icon": "📂", "in": 1, "out": 1,
                  "fields": [["path", "Путь", "%USERPROFILE%\\Downloads"]]},
    "screenshot": {"title": "Скриншот", "group": "action", "icon": "📸", "in": 1, "out": 1, "fields": []},
    "power": {"title": "Выключение / сон", "group": "action", "icon": "⏻", "in": 1, "out": 1,
              "fields": [["action", "shutdown / restart / sleep / lock / cancel", "shutdown"], ["minutes", "Через минут", "60"]]},
    "focus": {"title": "Не беспокоить", "group": "action", "icon": "🌙", "in": 1, "out": 1,
              "fields": [["mode", "on / off", "on"]]},
    "close_hung": {"title": "Закрыть зависшие окна", "group": "action", "icon": "🧊", "in": 1, "out": 1, "fields": []},
    "next_meeting": {"title": "Открыть ближайшую встречу", "group": "action", "icon": "📅", "in": 1, "out": 1,
                     "fields": [["minutes", "Встреча в ближайшие N минут", "30"]]},
    "http": {"title": "HTTP-запрос / вебхук", "group": "action", "icon": "🌐", "in": 1, "out": 1,
             "fields": [["method", "GET / POST", "POST"], ["url", "Адрес", "https://"], ["body", "Тело (JSON, для POST)", '{"text": "{last}"}']]},
    "renard_tool": {"title": "Действие Renard", "group": "action", "icon": "✻", "in": 1, "out": 1,
                   "fields": [["tool", "инструмент", "music"], ["args", "параметры (JSON)", '{"action": "play", "query": "lofi"}']]},
}

SAVEABLE = {"music", "volume", "app_volume", "open_app", "close_app", "open_file", "windows", "media_control", "presentation",
            "play_radio", "stop_radio", "avatar", "notify", "news", "weather", "pc_stats", "show_in_explorer", "routine",
            "lock_pc", "clipboard", "run_user_command", "app_ui",
            "diagnose_pc", "top_processes", "load_history", "activity_report", "list_tasks", "recent_files",
            "day_plan", "currency", "browser", "show_renard"}
PREFETCH = {"diagnose_pc", "top_processes", "load_history", "activity_report", "list_tasks", "recent_files", "news",
            "weather", "pc_stats", "day_plan", "currency"}


def step_label(tool: str, a: dict) -> str:
    """Human-readable step for the «Сохранить как команду» card."""
    a = a or {}
    act, q = a.get("action", ""), a.get("query") or a.get("name") or a.get("target") or a.get("app") or a.get("path") or ""
    if tool == "music":
        return {"play": f"YouTube: {q}", "next": "Следующее видео", "prev": "Предыдущее видео", "pause": "Пауза"}.get(act, f"Музыка: {act} {q}").strip()
    if tool == "volume":
        amt = a.get("amount")
        return {"set": f"Громкость {amt}%", "up": f"Громче на {amt or 10}", "down": f"Тише на {amt or 10}",
                "mute": "Без звука", "unmute": "Включить звук"}.get(act, "Громкость")
    if tool == "app_volume":
        return f"Громкость {a.get('app', '')}: {act} {a.get('level') or ''}".strip()
    if tool == "open_app":
        return f"Запустить {q}"
    if tool == "close_app":
        return f"Закрыть {q}"
    if tool == "open_file":
        return f"Открыть {str(q).split(chr(92))[-1]}"
    if tool == "windows":
        return f"Окна: {act} {q}".strip()
    if tool == "play_radio":
        return f"Радио {a.get('station', '')}"
    if tool == "avatar":
        return f"Аватар: {act}"
    simple = {"diagnose_pc": "Проверка ПК", "pc_stats": "Состояние ПК", "top_processes": "Что грузит ПК",
              "load_history": "Нагрузка за час", "activity_report": "Отчёт активности", "list_tasks": "Мои задачи",
              "lock_pc": "Заблокировать экран", "stop_radio": "Выключить радио", "routine": "Как обычно"}
    if tool in simple:
        return simple[tool]
    if tool == "weather":
        return "Погода" + (f": {a['city']}" if a.get("city") else "")
    if tool == "news":
        return {"digest": "Новости: сводка", "youtube": "Новые видео подписок", "twitch": "Кто стримит",
                "world": "Главное в мире"}.get(act, f"Новости: {act}")
    if tool == "media_control":
        return {"play_pause": "Пауза / продолжить", "next": "Следующий трек", "prev": "Предыдущий трек"}.get(act, f"Медиа: {act}")
    if tool == "presentation":
        return {"start": "Показ презентации", "next": "Следующий слайд", "prev": "Предыдущий слайд", "end": "Закончить показ"}.get(act, act)
    if tool == "recent_files":
        return f"Недавние файлы: {a.get('kind', '')}".strip(": ")
    return f"{tool} {json.dumps(a, ensure_ascii=False)[:60]}"


def from_steps(name: str, phrases: str, steps: list[dict], say: str = "", group: str = "Выученные") -> dict:
    """phrase -> step1 -> step2 … (-> say): the command Renard learned from what the AI just did."""
    chain = [("trigger_phrase", {"phrases": phrases})]
    for s in steps:
        if s.get("tool") in SAVEABLE:
            chain.append(("renard_tool", {"tool": s["tool"], "args": json.dumps(s.get("args") or {}, ensure_ascii=False)}))
    if say:
        chain.append(("say", {"text": say}))
    if len(chain) < 2:
        raise ValueError("нечего сохранять: в ответе не было действий, которые можно повторить")
    return upsert({"name": name.strip()[:60] or phrases.split(",")[0][:60], "group": group, "enabled": True,
                   "learned": True, "graph": _chain(*chain)})


BLOCK_ALIASES = {"url": "open_url", "app": "open_app", "open": "open_app", "type": "type_text", "text": "type_text",
                 "key": "keys", "hotkey": "keys", "pause": "wait", "sleep": "wait", "speak": "say", "message": "notify",
                 "ai": "ai_text", "web": "http", "webhook": "http"}


def to_block(s) -> tuple[str, dict] | None:
    """A step from the AI or the session log → (node, data). Accepts {"tool": name, "args": {…}} (a Renard tool),
    {"block": "open_url", "url": …} or {"open_url": "https://…"} (an editor block)."""
    if isinstance(s, str):
        s = s.strip()
        if re.match(r"https?://", s):
            return ("open_url", {"url": s})
        return ("say", {"text": s}) if s else None
    if not isinstance(s, dict):
        return None
    if s.get("tool"):
        tool = s["tool"]
        if tool in SAVEABLE:
            return ("renard_tool", {"tool": tool, "args": json.dumps(s.get("args") or {}, ensure_ascii=False)})
        if tool in NODES and NODES[tool]["group"] != "trigger":
            return (tool, {k: str(v) for k, v in (s.get("args") or {}).items()})
        return None
    name = s.get("block") or s.get("type") or s.get("node")
    if not name and len(s) == 1:
        (name, val), = s.items()
        name = BLOCK_ALIASES.get(name, name)
        if name in NODES and NODES[name]["fields"]:
            return (name, {NODES[name]["fields"][0][0]: str(val)})
    name = BLOCK_ALIASES.get(name or "", name)
    if name not in NODES or NODES[name]["group"] == "trigger":
        return None
    data = {k: str(v) for k, v in s.items() if k not in ("block", "type", "node")}
    for k, _, ph in NODES[name]["fields"]:
        data.setdefault(k, ph if name in ("power", "focus", "repeat") else "")
    return (name, data)


def build(name: str, triggers: list[tuple[str, dict]], actions: list[tuple[str, dict]], group: str = "Выученные",
          enabled: bool = True) -> dict:
    """Several triggers (phrase + hotkey + schedule) → one chain of actions."""
    if not triggers or not actions:
        raise ValueError("нужен хотя бы один триггер и одно действие")
    data, i = {}, 0
    for k, (n, d) in enumerate(triggers):
        i += 1
        data[str(i)] = _node(i, n, d, 60, 80 + k * 170)
    first = i + 1
    for k, (n, d) in enumerate(actions):
        i += 1
        data[str(i)] = _node(i, n, d, 380 + k * 290, 100 + (40 if k % 2 else 0))
        if k:
            data[str(i - 1)]["outputs"]["output_1"]["connections"].append({"node": str(i), "output": "input_1"})
            data[str(i)]["inputs"]["input_1"]["connections"].append({"node": str(i - 1), "input": "output_1"})
    for t in range(1, first):
        data[str(t)]["outputs"]["output_1"]["connections"].append({"node": str(first), "output": "input_1"})
        data[str(first)]["inputs"]["input_1"]["connections"].append({"node": str(t), "input": "output_1"})
    return upsert({"name": name.strip()[:60], "group": group, "enabled": enabled, "learned": True,
                   "graph": {"drawflow": {"Home": {"data": data}}}})


STATS = DATA_DIR / "action_stats.json"


def same_steps_command(steps: list[dict]) -> dict | None:
    want = [(s["tool"], json.dumps(s.get("args") or {}, ensure_ascii=False, sort_keys=True)) for s in steps]
    for c in _load():
        try:
            have = [(n["data"].get("tool"), json.dumps(json.loads(n["data"].get("args") or "{}"), ensure_ascii=False, sort_keys=True))
                    for n in _nodes(c).values() if n["name"] == "renard_tool" and n.get("data")]
        except (json.JSONDecodeError, TypeError):
            continue
        if have == want:
            return c
    return None


def note_repeat(phrase: str, steps: list[dict]) -> int:
    """How many times this exact set of actions was asked for (data/action_stats.json). 3 → Renard offers a command."""
    sig = " | ".join(f"{s['tool']}:{json.dumps(s.get('args') or {}, ensure_ascii=False, sort_keys=True)}" for s in steps)
    try:
        st = json.loads(STATS.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    e = st.setdefault(sig, {"n": 0, "phrases": []})
    e["n"] += 1; e["last"] = time.time()
    if phrase and phrase not in e["phrases"]:
        e["phrases"] = (e["phrases"] + [phrase])[-5:]
    if len(st) > 400:
        st = dict(sorted(st.items(), key=lambda kv: kv[1].get("last", 0))[-300:])
    STATS.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return e["n"]


def _load() -> list[dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return _defaults()


def _save(items):
    PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def _node(nid, name, data, x, y, to=None):
    meta = NODES[name]
    outs = {f"output_{i + 1}": {"connections": []} for i in range(meta["out"])}
    ins = {f"input_{i + 1}": {"connections": []} for i in range(meta["in"])}
    return {"id": nid, "name": name, "data": data, "class": name, "html": name, "typenode": False,
            "inputs": ins, "outputs": outs, "pos_x": x, "pos_y": y}


def _chain(*nodes) -> dict:
    data = {}
    for i, (name, d) in enumerate(nodes, 1):
        data[str(i)] = _node(i, name, d, 60 + (i - 1) * 290, 120 + (40 if i % 2 == 0 else 0))
    for i in range(1, len(nodes)):
        data[str(i)]["outputs"]["output_1"]["connections"].append({"node": str(i + 1), "output": "input_1"})
        data[str(i + 1)]["inputs"]["input_1"]["connections"].append({"node": str(i), "input": "output_1"})
    return {"drawflow": {"Home": {"data": data}}}


def _defaults() -> list[dict]:
    items = [
        {"name": "Громче", "group": "Звук", "graph": _chain(("trigger_phrase", {"phrases": "громче, сделай громче, прибавь звук"}),
                                                          ("volume", {"mode": "add", "value": "10"}))},
        {"name": "Тише", "group": "Звук", "graph": _chain(("trigger_phrase", {"phrases": "тише, сделай тише, убавь звук"}),
                                                        ("volume", {"mode": "add", "value": "-10"}))},
        {"name": "Открыть YouTube", "group": "Продуктивность",
         "graph": _chain(("trigger_phrase", {"phrases": "открой ютуб, включи ютуб"}), ("open_url", {"url": "https://youtube.com"}))},
        {"name": "Доброе утро", "group": "Продуктивность",
         "graph": _chain(("trigger_phrase", {"phrases": "доброе утро"}),
                         ("ask_ai", {"prompt": "Доброе утро! Коротко: погода на сегодня (инструмент weather) и одна мотивирующая фраза."}),
                         ("say", {"text": "{last}"}))},
        {"name": "Режим фокуса 25 мин", "group": "Фокус", "enabled": False,
         "graph": _chain(("trigger_phrase", {"phrases": "режим фокуса"}), ("minimize", {}),
                         ("notify", {"text": "Фокус 25 минут. Поехали!"}), ("wait", {"seconds": "1500"}),
                         ("notify", {"text": "Перерыв 5 минут"}), ("say", {"text": "Время перерыва"}))},
    ]
    out = []
    for c in items:
        out.append({"id": uuid.uuid4().hex[:8], "enabled": c.get("enabled", True), **c})
    _save(out)
    return out


def all_commands() -> list[dict]:
    return _load()


def get(cid: str) -> dict | None:
    return next((c for c in _load() if c["id"] == cid), None)


def upsert(data: dict) -> dict:
    items = _load()
    cid = data.get("id") or uuid.uuid4().hex[:8]
    cur = next((c for c in items if c["id"] == cid), None)
    if cur is None:
        cur = {"id": cid, "name": "Новая команда", "group": "Без группы", "enabled": True,
               "graph": {"drawflow": {"Home": {"data": {}}}}}
        items.append(cur)
    for k in ("name", "group", "enabled", "graph", "learned", "template"):
        if k in data:
            cur[k] = data[k]
    _save(items)
    cur["schedule_errors"] = _sync_schedule(cur)
    return cur


def _sync_schedule(c: dict) -> list[str]:
    """«По расписанию» blocks live in the scheduler as tasks cmd_<command>_<node> (kind command)."""
    from . import scheduler
    pre, errs, keep = f"cmd_{c['id']}_", [], set()
    for nid, n in _nodes(c).items():
        if n["name"] != "trigger_schedule" or not (n.get("data", {}).get("when") or "").strip():
            continue
        tid = pre + str(nid)
        try:
            scheduler.upsert({"id": tid, "name": f"Команда «{c['name']}»", "kind": "command", "command": c["id"],
                              "when": n["data"]["when"], "enabled": bool(c.get("enabled", True)), "telegram": False})
            keep.add(tid)
        except ValueError as e:
            errs.append(str(e))
    for t in scheduler.all_tasks():
        if t["id"].startswith(pre) and t["id"] not in keep:
            scheduler.delete(t["id"])
    return errs


def delete(cid: str) -> bool:
    items = _load()
    new = [c for c in items if c["id"] != cid]
    _save(new)
    _sync_schedule({"id": cid, "name": "", "graph": {}})
    return len(new) != len(items)


def _nodes(c: dict) -> dict:
    return c.get("graph", {}).get("drawflow", {}).get("Home", {}).get("data", {})


def _norm(s: str) -> str:
    return re.sub(r"[^\w ]+", "", s.lower().replace("ё", "е")).strip()


def _stems(s: str) -> list[str]:
    """Russian/Polish word endings change with the case: compare by the first 4 letters of longer words."""
    return [w[:4] if len(w) >= 5 else w for w in s.split()]


FILLER = re.compile(r"^(ренар|renard|некс|слушай|ну|давай|а|ой|эй|пожалуйста|плиз)\s+|\s+(пожалуйста|плиз|please)$")


def match_phrase(text: str) -> tuple[dict, str] | None:
    """Exact phrase, phrase + a short tail, or the same phrase said a little differently (typos, word endings,
    «ренар», «пожалуйста»): similarity ≥ 0.86 on phrases of 2+ words."""
    import difflib
    t = _norm(text)
    for _ in range(3):
        t = FILLER.sub("", t).strip()
    best, best_r = None, 0.0
    for c in _load():
        if not c.get("enabled", True):
            continue
        for nid, n in _nodes(c).items():
            if n["name"] == "trigger_phrase":
                for ph in (n.get("data", {}).get("phrases") or "").split(","):
                    ph = _norm(ph)
                    if not ph:
                        continue
                    if t == ph or t.startswith(ph + " ") and len(t) - len(ph) < 25:
                        return c, nid
                    if len(ph.split()) >= 2 and _stems(t) == _stems(ph):
                        return c, nid
                    if len(ph.split()) >= 2 and abs(len(t) - len(ph)) <= max(4, len(ph) // 4):
                        r = difflib.SequenceMatcher(None, t, ph).ratio()
                        if r > best_r:
                            best, best_r = (c, nid), r
    return best if best_r >= 0.86 else None


def hotkeys() -> list[dict]:
    out = []
    for c in _load():
        if c.get("enabled", True):
            for nid, n in _nodes(c).items():
                if n["name"] == "trigger_hotkey" and n.get("data", {}).get("combo"):
                    out.append({"command": c["id"], "node": nid, "combo": n["data"]["combo"].lower().replace(" ", "")})
    return out


class Runner:
    def __init__(self, agent, broadcast):
        self.agent, self.broadcast = agent, broadcast

    async def run(self, cid: str, start: str | None = None) -> list[str]:
        c = get(cid)
        if not c:
            return [f"нет команды {cid}"]
        nodes = _nodes(c)
        starts = [start] if start else [k for k, n in nodes.items() if NODES.get(n["name"], {}).get("group") == "trigger"] or \
            [k for k, n in nodes.items() if not any(v["connections"] for v in n.get("inputs", {}).values())]
        log, ctx = [], {"last": "", "pre": {}}
        await self.broadcast({"type": "activity", "source": "command", "note": f"команда «{c['name']}»…"})
        from . import tools as _tools
        for nid, n in nodes.items():
            d = n.get("data", {})
            if n["name"] == "renard_tool" and d.get("tool") in PREFETCH and "{last}" not in (d.get("args") or ""):
                try:
                    args = json.loads(d.get("args") or "{}")
                except json.JSONDecodeError:
                    continue
                ctx["pre"][nid] = asyncio.create_task(_tools.call(d["tool"], args, self.agent.ctx() if self.agent else {}))
        queue, seen = list(starts), set()
        try:
            while queue:
                nid = queue.pop(0)
                if nid in seen or nid not in nodes:
                    continue
                seen.add(nid)
                n = nodes[nid]
                ctx["nid"] = nid
                await self.broadcast({"type": "command_step", "command": cid, "node": nid, "status": "run"})
                n_log = len(log)
                try:
                    outs = await self._exec(n["name"], n.get("data", {}), ctx, log)
                except Exception as e:
                    await self.broadcast({"type": "command_step", "command": cid, "node": nid, "status": "error",
                                          "result": f"{type(e).__name__}: {e}"[:200]})
                    raise
                await self.broadcast({"type": "command_step", "command": cid, "node": nid, "status": "ok",
                                      "result": " ".join(log[n_log:])[:200]})
                if outs == ["__restart__"]:
                    seen.clear(); queue = list(starts)
                    continue
                for o in outs:
                    for conn in n.get("outputs", {}).get(o, {}).get("connections", []):
                        queue.append(str(conn["node"]))
        except Exception as e:
            log.append(f"ошибка: {type(e).__name__}: {e}")
        finally:
            for t in ctx["pre"].values():
                t.cancel()
            await self.broadcast({"type": "activity", "source": "command", "note": ""})
        return log

    async def _exec(self, name: str, d: dict, ctx: dict, log: list) -> list[str]:
        from . import tools, winput
        sub = lambda s: str(s or "").replace("{last}", ctx["last"])
        if NODES.get(name, {}).get("group") == "trigger":
            return ["output_1"]
        if name == "open_url":
            url = sub(d.get("url"))
            url = url if re.match(r"^[a-z]+:", url) else "https://" + url
            webbrowser.open(url); log.append(f"открыл {url}")
        elif name in ("open_app", "close_app"):
            log.append(await tools.call(name, {"name": sub(d.get("name"))}, {}))
        elif name == "type_text":
            await asyncio.sleep(0.3)
            for part in re.split(r"(\{(?:tab|enter|esc|wait)\})", sub(d.get("text")), flags=re.I):
                key = part.lower().strip("{}") if re.fullmatch(r"\{\w+\}", part) else ""
                if key == "wait":
                    await asyncio.sleep(1)
                elif key:
                    await asyncio.to_thread(winput.press, key); await asyncio.sleep(0.12)
                elif part:
                    await asyncio.to_thread(winput.type_text, part)
            log.append("ввёл текст")
        elif name == "keys":
            await asyncio.to_thread(winput.press, sub(d.get("combo"))); log.append(f"нажал {d.get('combo')}")
        elif name == "media":
            log.append(await tools.call("media_control", {"action": d.get("action") or "play_pause"}, {}))
        elif name == "volume":
            v = int(float(d.get("value") or 10))
            new = await asyncio.to_thread(winput.set_volume, None if d.get("mode") == "add" else v,
                                          v if d.get("mode") == "add" else None)
            log.append(f"громкость {new}%")
        elif name == "notify":
            from .tools.system import toast
            toast("Renard", sub(d.get("text"))); log.append("уведомление")
            await self.broadcast({"type": "task", "name": "Команда", "kind": "reminder", "text": sub(d.get("text"))})
        elif name == "say":
            from . import voice
            from .wake import play_wav
            wav = await asyncio.to_thread(voice.tts.synth, sub(d.get("text")))
            if wav:
                await asyncio.to_thread(play_wav, wav)
            log.append("сказал")
        elif name == "ask_ai":
            answer = []

            async def send(ev):
                if ev.get("type") == "token":
                    answer.append(ev["text"])
            async with self.agent.lock:
                await self.agent.handle(sub(d.get("prompt")), "commands", send, None, perm="auto")
            ctx["last"] = "".join(answer).strip()
            log.append("ИИ: " + ctx["last"][:200])
        elif name == "radio":
            log.append(await tools.call("play_radio", {"station": d.get("station") or "record"}, {}))
        elif name == "telegram":
            from .telegram_bot import BRIDGE
            if BRIDGE and BRIDGE.connected:
                await BRIDGE.notify(sub(d.get("text"))); log.append("отправил в Telegram")
            else:
                log.append("Telegram не подключён")
        elif name == "minimize":
            log.append(await tools.call("windows", {"action": "minimize_all"}, {}))
        elif name == "renard_tool":
            tool = (d.get("tool") or "").strip()
            try:
                args = json.loads(sub(d.get("args")) or "{}")
            except json.JSONDecodeError:
                args = {}
            if tool not in SAVEABLE:
                log.append(f"{tool}: этот инструмент нельзя запускать из команды")
            else:
                pre = ctx.get("pre", {}).pop(ctx.get("nid"), None)
                res = await pre if pre else await tools.call(tool, args, self.agent.ctx() if self.agent else {})
                ctx["last"] = res
                log.append(res)
        elif name == "wait":
            await asyncio.sleep(min(float(d.get("seconds") or 1), 4 * 3600))
        elif name == "if_process":
            import psutil
            target = (d.get("name") or "").lower().removesuffix(".exe")
            running = any((p.info["name"] or "").lower().removesuffix(".exe") == target for p in psutil.process_iter(["name"]))
            log.append(f"{target}: {'запущен' if running else 'не запущен'}")
            return ["output_1" if running else "output_2"]
        elif name in NEW_NODES:
            return await NEW_NODES[name](self, d, ctx, log, sub)
        else:
            log.append(f"неизвестный узел {name}")
        return ["output_1"]
