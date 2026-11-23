"""👍/👎 under answers → lessons the agent applies by itself next time.

👎 + «что не так» → the light model turns it into ONE rule «когда …, делай …, не делай …» with trigger words →
data/lessons.json. Before every answer lessons_block(request) adds the 1–3 lessons that match (same picker as skills).
👍 → the exchange is kept as a good example (data/feedback_good.jsonl); with tool steps the UI offers «сохранить как команду».
Every 👎 is also a regression case (data/feedback_cases.jsonl) for eval/feedback_replay.py.
No fine-tuning: the model's weights don't change, its instructions do — instant and reversible (lessons can be deleted).
"""
import json
import re
import time
import uuid
from pathlib import Path
from .logs import quiet

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOG = DATA / "feedback.jsonl"
GOOD = DATA / "feedback_good.jsonl"
CASES = DATA / "feedback_cases.jsonl"
LESSONS = DATA / "lessons.json"
LLM = None
MAX_LESSONS = 200

LESSON_PROMPT = """Пользователь поставил 👎 ответу ассистента Renard и объяснил почему. Сформулируй ОДИН урок на будущее.
Ответь ОДНИМ JSON:
{"when":"тип задачи, к которой относится урок — НЕ шире, чем этот случай (например «настройка параметров в
программе через app_do», «отправка сообщения в Telegram»). Без слова «когда» в начале",
 "do":"что делать правильно — по его словам","dont":"что было не так (что сделал Renard)",
 "triggers":"5-10 ОТДЕЛЬНЫХ слов через запятую (каждое — одно слово) из таких запросов"}
Правила:
- Урок — про ТО, ЧТО ОН НАПИСАЛ. Если он дал указание («отвечай короче», «не переспрашивай») — это и есть do.
- Если он только описал, что не получилось («не смог открыть X», «не поменял цвет»), то do = довести такую задачу до
  результата САМОМУ: другой путь, разведка программы, поиск в интернете — и честно сказать, что сделано.
- НИКОГДА не пиши в do «спросить/уточнить у пользователя», «попросить пользователя сделать самому», если он сам
  этого не просил. Он хочет, чтобы Renard справлялся сам.
- Не обобщай до «любая просьба» / «любая проблема». Не выдумывай того, чего нет в объяснении."""


def _append(path: Path, rec: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_lessons() -> list[dict]:
    try:
        return json.loads(LESSONS.read_text("utf-8"))
    except Exception:
        return []


def _save_lessons(ls: list[dict]):
    DATA.mkdir(parents=True, exist_ok=True)
    LESSONS.write_text(json.dumps(ls[-MAX_LESSONS:], ensure_ascii=False, indent=1), "utf-8")


async def record(rating: int, user_text: str, answer: str, reason: str = "", session: str = "", msg_id: str = "",
                 tools: list | None = None) -> dict:
    """rating: +1 / -1. Returns {"ok", "lesson"?: {...}, "offer_command"?: bool} for the UI."""
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "rating": 1 if rating > 0 else -1, "reason": reason.strip(),
           "user": user_text[:2000], "answer": answer[:4000], "tools": tools or [], "session": session, "msg": msg_id}
    _append(LOG, rec)
    if rec["rating"] > 0:
        _append(GOOD, rec)
        for l in load_lessons():
            if l["id"] in (tools or []):
                l["confirmed"] = l.get("confirmed", 0) + 1
        return {"ok": True, "offer_command": bool(tools)}
    _append(CASES, {"input": user_text, "bad_answer": answer[:2000], "reason": reason, "ts": rec["ts"]})
    if not reason.strip():
        return {"ok": True, "ask_reason": True}
    return {"ok": True, "draft": await make_lesson(user_text, answer, reason)}


def save_draft(lesson: dict) -> dict:
    """«Сохранить» under a draft: a new lesson, or the same complaint again → the old one gets stronger."""
    lesson = {k: str(v)[:400] for k, v in lesson.items() if k in ("id", "created", "source", "when", "do", "dont", "triggers")}
    lesson.setdefault("id", "L" + uuid.uuid4().hex[:6])
    lesson.setdefault("created", time.strftime("%Y-%m-%d"))
    lesson["when"] = re.sub(r"(?i)^когда\s+", "", lesson.get("when", "")).strip()
    lesson["count"] = 1
    ls = load_lessons()
    dup = next((l for l in ls if _similar(l, lesson)), None)
    if dup:
        dup["count"] = dup.get("count", 1) + 1
        dup.update({k: lesson[k] for k in ("when", "do", "dont", "triggers") if lesson.get(k)})
        lesson = dup
    else:
        ls.append(lesson)
    _save_lessons(ls)
    return lesson


def undo(rec: dict) -> dict:
    """A second click on the same 👍/👎 takes it back (logged as rating 0; a lesson saved from it is removed)."""
    _append(LOG, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "rating": 0, "undo": True, "user": str(rec.get("user", ""))[:300],
                  "session": rec.get("session", "")})
    if rec.get("lesson_id"):
        delete_lesson(rec["lesson_id"])
    return {"ok": True}


async def make_lesson(user_text: str, answer: str, reason: str) -> dict:
    base = {"id": "L" + uuid.uuid4().hex[:6], "created": time.strftime("%Y-%m-%d"), "count": 1, "source": user_text[:200]}
    if LLM is not None:
        try:
            mode = "operator" if "operator" in getattr(LLM, "modes", {}) else "low"
            r = await LLM.chat(mode, [{"role": "system", "content": LESSON_PROMPT},
                                       {"role": "user", "content": f"Запрос: {user_text[:800]}\nОтвет Renard: {answer[:1500]}\n"
                                                                   f"Что не так (слова пользователя): {reason[:600]}"}])
            m = re.search(r"\{.*\}", (r.get("message") or {}).get("content", ""), re.S)
            d = json.loads(m.group(0)) if m else {}
            if d.get("do") or d.get("dont"):
                return {**base, **{k: str(d.get(k, ""))[:300] for k in ("when", "do", "dont", "triggers")}}
        except Exception:
            quiet()
    return {**base, "when": f"запрос похож на «{user_text[:120]}»", "do": reason[:300], "dont": "",
            "triggers": ", ".join(list(dict.fromkeys(re.findall(r"[а-яёa-z]{5,}", user_text.lower())))[:6])}


def _similar(a: dict, b: dict) -> bool:
    from .skills_auto import stems
    x, y = stems(a.get("when", "") + " " + a.get("dont", "")), stems(b.get("when", "") + " " + b.get("dont", ""))
    return bool(x and y) and len(x & y) / max(1, min(len(x), len(y))) >= 0.6


def lessons_block(text: str, k: int = 3) -> tuple[str, list[str]]:
    """Lessons for this request (added to the system prompt) + their ids."""
    from .skills_auto import rank
    items = [{"name": l["id"], "description": l.get("when", "") + " " + l.get("source", ""),
              "body": l.get("do", "") + " " + l.get("dont", ""),
              "triggers": ", ".join(w for t in l.get("triggers", "").split(",") for w in t.split() if len(w) >= 4),
              "_l": l} for l in load_lessons()]
    chosen = rank(items, text, k, min_score=2.5)
    if not chosen:
        return "", []
    lines = []
    for c in chosen:
        l = c["_l"]
        when = re.sub(r"(?i)^когда\s+", "", l.get("when", "")).rstrip(".")
        lines.append(f"- Когда {when}: {l.get('do', '').rstrip('.')}"
                     + (f". НЕ {l['dont'].rstrip('.')}" if l.get("dont") else "") + (f" (он просил уже {l['count']} раза)" if l.get("count", 1) > 1 else ""))
    return "\n\nУРОКИ ОТ ПОЛЬЗОВАТЕЛЯ (он поправлял такие ответы — соблюдай):\n" + "\n".join(lines), [c["name"] for c in chosen]


def delete_lesson(lesson_id: str) -> bool:
    ls = load_lessons()
    keep = [l for l in ls if l["id"] != lesson_id]
    _save_lessons(keep)
    return len(keep) < len(ls)


def update_lesson(lesson_id: str, fields: dict) -> dict | None:
    ls = load_lessons()
    for l in ls:
        if l["id"] == lesson_id:
            l.update({k: str(v)[:300] for k, v in fields.items() if k in ("when", "do", "dont", "triggers")})
            _save_lessons(ls)
            return l
    return None
