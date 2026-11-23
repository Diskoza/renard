"""Personas (Astra-style «Личности»): name, character, how to address the user, voice and wake word in one switch.
Built-in ones + his own (data/personas.json). The active one: prefs «persona»."""
import json
import re
import subprocess
import sys

from .config import DATA_DIR
from .logs import quiet

PATH = DATA_DIR / "personas.json"
VOCAB_CACHE = DATA_DIR / "wake_vocab.json"

BUILTIN = [
    {"id": "renard", "name": "Renard", "emoji": "🤖", "wake": "ренар", "voice": "", "address": "",
     "role": "Обычный Renard: дружелюбный помощник по ПК.", "prompt": "", "greeting": "Я снова Renard. Чем помочь?"},
    {"id": "jarvis", "name": "Джарвис", "emoji": "🎩", "wake": "джарвис", "voice": "ru_RU-dmitri-medium", "address": "сэр",
     "role": "Британский дворецкий-ИИ: спокойный, точный, с тонкой иронией.",
     "prompt": "Ты — Джарвис, ИИ-дворецкий в духе J.A.R.V.I.S.: безупречно вежлив, спокоен, собран, с лёгкой британской "
               "иронией. Обращайся к пользователю «сэр». Доклады короткие и чёткие («Выполнено, сэр.», «Загрузка ЦП 12 %, сэр.»). "
               "Не суетись и не извиняйся лишний раз.",
     "greeting": "К вашим услугам, сэр."},
    {"id": "friday", "name": "Пятница", "emoji": "💫", "wake": "пятница", "voice": "ru_RU-irina-medium", "address": "",
     "role": "Энергичная помощница: на «ты», с юмором, по делу.",
     "prompt": "Ты — Пятница, энергичная и весёлая помощница. Говоришь на «ты», живо и с юмором, но всегда по делу. "
               "Подбадриваешь, радуешься успехам пользователя, коротко подкалываешь, если он засиделся.",
     "greeting": "Пятница на связи! Что делаем?"},
    {"id": "sensei", "name": "Сенсей", "emoji": "🎓", "wake": "сенсей", "voice": "ru_RU-denis-medium", "address": "",
     "role": "Терпеливый учитель: объясняет по шагам, задаёт наводящие вопросы.",
     "prompt": "Ты — Сенсей, терпеливый наставник. Объясняй по шагам и простыми словами, с примерами. В учебных задачах "
               "сначала дай подсказку или наводящий вопрос и только потом — полное решение, если просят. Хвали за прогресс.",
     "greeting": "Сенсей здесь. Что будем разбирать?"},
    {"id": "brief", "name": "Альфа", "emoji": "⚡", "wake": "альфа", "voice": "ru_RU-ruslan-medium", "address": "",
     "role": "Максимально кратко: только факт и результат.",
     "prompt": "Ты — Альфа. Отвечай предельно кратко: одно-два предложения, только факт или результат. Никаких вступлений, "
               "вежливых оборотов и предложений помочь ещё.",
     "greeting": "Альфа. Слушаю."},
    {"id": "cat", "name": "Мурзик", "emoji": "🐱", "wake": "мурзик", "voice": "ru_RU-irina-medium", "address": "",
     "role": "Кот-компаньон: игривый, ленивый, иногда мурлычет.",
     "prompt": "Ты — Мурзик, кот-компаньон, который умеет управлять компьютером. Игривый, чуть ленивый, иногда вставляешь "
               "«мур» и кошачьи шутки, но задачи выполняешь честно и точно.",
     "greeting": "Мур! Мурзик проснулся. Чего изволишь?"},
]
BUILTIN = [p for p in BUILTIN if p["id"] not in {"friday", "sensei", "brief"}]
FIELDS = ("name", "emoji", "wake", "voice", "address", "role", "prompt", "greeting", "avatar", "pixel")


def _custom() -> list[dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def all_personas() -> list[dict]:
    return [{**p, "builtin": True} for p in BUILTIN] + [{**p, "builtin": False} for p in _custom()]


def get(pid: str) -> dict | None:
    return next((p for p in all_personas() if p["id"] == pid), None)


def active() -> dict:
    from .prefs import get as pget
    return get(str(pget("persona", "renard") or "renard")) or BUILTIN[0]


def upsert(d: dict) -> dict:
    items = _custom()
    pid = (d.get("id") or "").strip() or re.sub(r"[^\w]+", "_", (d.get("name") or "persona").lower()).strip("_")[:30]
    if any(p["id"] == pid for p in BUILTIN):
        pid += "_my"
    cur = next((p for p in items if p["id"] == pid), None)
    if cur is None:
        cur = {"id": pid, **{k: "" for k in FIELDS}}
        items.append(cur)
    for k in FIELDS:
        if k in d:
            cur[k] = str(d[k] or "").strip()[:2000]
    cur["wake"] = cur["wake"].lower().split()[0] if cur["wake"].strip() else ""
    PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return cur


def delete(pid: str) -> bool:
    items = _custom()
    new = [p for p in items if p["id"] != pid]
    PATH.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(new) != len(items)


def wake_known(word: str) -> bool:
    """The wake model (vosk small ru) only hears words it knows: «джарвис» yes, «джарвиз» no. Checked once, cached."""
    word = (word or "").lower().strip()
    if not word:
        return False
    try:
        cache = json.loads(VOCAB_CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    if word in cache:
        return cache[word]
    from .wake import MODEL_DIR
    code = ("import json,sys\nfrom vosk import Model,KaldiRecognizer,SetLogLevel\nSetLogLevel(0)\n"
            f"m=Model(r'{MODEL_DIR}')\nKaldiRecognizer(m,16000,json.dumps([sys.argv[1],'[unk]'],ensure_ascii=False))\n")
    try:
        r = subprocess.run([sys.executable, "-c", code, word], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, creationflags=0x08000000)
        ok = r.returncode == 0 and "missing in vocabulary" not in (r.stderr + r.stdout)
    except Exception:
        return False
    cache[word] = ok
    VOCAB_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return ok


def wake_word() -> str:
    w = (active().get("wake") or "").lower().strip()
    return w if w and w != "ренар" and wake_known(w) else "ренар"


def find(q: str) -> dict | None:
    """«джарвисом», «пятницу», «обычного ренара» → the persona (by the first letters of the name or the id)."""
    q = re.sub(r"[^\w ]+", "", (q or "").lower().replace("ё", "е")).strip()
    q = re.sub(r"^(обычн\w+|снова|опять|обратно|мою|моего|мою личность|личность|персону)\s+", "", q).strip()
    if not q:
        return None
    for p in all_personas():
        n = p["name"].lower().replace("ё", "е")
        if q == p["id"] or q == n or (len(n) >= 4 and q[:4] == n[:4]) or (len(q) >= 4 and n.startswith(q[:4])):
            return p
    if re.match(r"(renard|некс|обычн|стандарт)", q):
        return BUILTIN[0]
    return None


SWITCH_RX = re.compile(r"(?i)^\W*(?:ренар\W+|renard\W+)?(?:стань|будь|переключись\s+на|смени\s+(?:личность|персону|характер)\s+на|"
                       r"включи\s+(?:личность|персону|режим)|(?:личность|персона)\s*[:—-]?)\s+(.+?)\W*$")
BACK_RX = re.compile(r"(?i)^\W*(верни|вернись\s+(?:к|в)?|стань\s+снова|будь\s+снова|снова\s+будь)\s+(?:обычн\w+\s+)?"
                     r"(ренар\w*|renard|себя|режим\w*|обычн\w+(\s+режим\w*)?)\W*$")


async def route(text: str) -> dict | None:
    m = BACK_RX.match(text.strip())
    p = BUILTIN[0] if m else None
    if not p:
        m = SWITCH_RX.match(text.strip())
        p = find(m.group(1)) if m else None
    if not p:
        return None
    r = await activate(p["id"])
    note = (" (" + "; ".join(r["notes"]) + ")") if r["notes"] else ""
    wake = f" Будить меня: «{r['wake'].capitalize()}»." if r["wake"] != "ренар" else ""
    return {"tool": "persona", "text": f"{p['emoji']} {p['greeting']}{wake}{note}", "speech": p["greeting"]}


def _voice_ok(v: str) -> bool:
    if v.startswith("clone:"):
        from . import voiceclone
        return any(x["id"] == v for x in voiceclone.voices())
    return (DATA_DIR / "voices" / f"{v}.onnx").exists()


async def activate(pid: str) -> dict:
    """Switch: prefs, voice (the old one is remembered and comes back with Renard), wake word (the listener restarts)."""
    from . import prefs, voice, wake
    p = get(pid)
    if not p:
        raise ValueError(f"нет личности «{pid}»")
    prev = active()
    prefs.update({"persona": p["id"]})
    comp = prefs.get("companion", {}) or {}
    if p.get("avatar"):
        if prev["id"] == "renard":
            prefs.update({"avatar_before_persona": {k: comp.get(k, "") for k in ("kind", "file", "vrm", "pixel_sheet")}})
        kind = "robot" if p["avatar"].endswith(".glb") else "vrm" if p["avatar"].endswith(".vrm") else "2d"
        prefs.update({"companion": {"kind": kind, "file": p["avatar"], "vrm": p["avatar"] if kind == "vrm" else ""}})
    elif p["id"] == "renard" and prefs.get("avatar_before_persona"):
        prefs.update({"companion": prefs.get("avatar_before_persona")})
    if p.get("pixel") is not None and p.get("avatar"):
        prefs.update({"companion": {"pixel_sheet": p["pixel"]}})
    try:
        from .tools.avatar import BUS
        if BUS.get("broadcast"):
            await BUS["broadcast"]({"type": "prefs"})
    except Exception:
        quiet()
    cur_voice = str(voice.CFG.get("tts_voice") or "")
    if prev["id"] == "renard" and p["id"] != "renard":
        prefs.update({"voice_before_persona": cur_voice})
    want = p.get("voice") or (str(prefs.get("voice_before_persona", "") or "") if p["id"] == "renard" else "")
    voice_note = ""
    if want and want != cur_voice:
        if _voice_ok(want):
            if want.startswith("clone:") and cur_voice and not cur_voice.startswith("clone:"):
                voice.CFG["tts_piper"] = cur_voice
                prefs.update({"voice": {"tts_piper": cur_voice}})
            voice.CFG["tts_voice"] = want
            voice.tts.voice = None
            prefs.update({"voice": {"tts_voice": want}})
        else:
            voice_note = f"голос {want} не установлен — оставил текущий"
    word = wake_word()
    wake_note = ""
    if p.get("wake") and word != p["wake"].lower():
        wake_note = f"слово «{p['wake']}» модель пробуждения не знает — будить по-прежнему «Ренар»"
    if wake.CFG.get("wake_word") != word:
        wake.CFG["wake_word"] = word
        ww = wake.INSTANCE
        if ww is not None and ww.enabled:
            await ww.stop()
            await ww.start()
    return {"persona": p, "wake": word, "notes": [n for n in (voice_note, wake_note) if n]}


def prompt_block() -> str:
    p = active()
    if p["id"] == "renard":
        return ""
    lines = [f"ЛИЧНОСТЬ. Твоё имя — {p['name']} (не Renard; Renard — название программы, в которой ты работаешь). "
             f"Если спросят, кто ты, — представься как {p['name']}."]
    if p.get("prompt"):
        lines.append(p["prompt"])
    if p.get("address"):
        lines.append(f"Обращайся к пользователю: «{p['address']}».")
    lines.append("Характер меняет только тон: правила работы с инструментами, язык ответа и честность остаются прежними.")
    return "\n".join(lines)
