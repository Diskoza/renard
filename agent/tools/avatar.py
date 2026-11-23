"""The companion's body: gestures, emotions, walking / sitting on the taskbar (desktop window) and in the app.
When the AI is idle the desktop companion turns into a little pixel Renard with its own activities."""
from . import S, tool

BUS = {"broadcast": None}

ACTIONS = {
    "wave": "помахать рукой", "jump": "подпрыгнуть", "dance": "потанцевать", "nod": "кивнуть", "shake": "покачать головой",
    "bow": "поклониться", "think": "задуматься", "shrug": "пожать плечами", "clap": "похлопать", "stretch": "потянуться",
    "point": "показать рукой", "celebrate": "обрадоваться",
    "sit": "сесть на панель задач", "stand": "встать", "sleep": "уснуть", "wake": "проснуться",
    "walk": "прогуляться", "walk_left": "пойти влево", "walk_right": "пойти вправо", "come": "подойти к курсору",
    "center": "выйти в центр", "stop": "остановиться",
    "climb": "запрыгнуть на активное окно", "jump_down": "спрыгнуть с окна",
    "catch": "поймать снежинку", "shiver": "поёжиться от холода", "brush": "стряхнуть снег с головы", "balance": "балансировать",
    "pixel": "стать маленьким пиксельным", "big": "стать большим", "shy": "смутиться",
    "puton": "надеть наушники (жест)", "earbuds": "вставить вкладыши (жест)", "neckoff": "снять наушники на шею (жест)",
}
DANCES = {"groove": "грув", "sway": "покачивание с руками вверх", "robot": "робот", "hype": "прыжки", "wave": "волна руками"}
WEAR = {"beanie": "шапку", "santa": "новогоднюю шапку", "cap": "кепку", "headphones": "наушники", "glasses": "очки",
        "sunglasses": "тёмные очки", "crown": "корону", "cat_ears": "кошачьи ушки", "flower": "цветок", "scarf": "шарф"}
SLOT = {"beanie": "top", "santa": "top", "cap": "top", "crown": "top", "cat_ears": "top", "glasses": "eyes", "sunglasses": "eyes"}


def dress(wear: str = "", take_off: str = "") -> tuple[list, str]:
    """Put on / take off accessories (one hat, one pair of glasses at a time). -> (new list, what changed in words)."""
    from ..prefs import get, update
    cur = [a for a in (get("companion.accessories", []) or []) if a in WEAR]
    said = []
    for t in [x.strip() for x in (take_off or "").lower().split(",") if x.strip()]:
        if t in ("all", "everything", "всё", "все"):
            cur, said = [], ["снял всё"]
            break
        if t in cur:
            cur.remove(t); said.append("снял " + WEAR[t])
    for w in [x.strip() for x in (wear or "").lower().split(",") if x.strip()]:
        if w in WEAR and w not in cur:
            cur = [a for a in cur if SLOT.get(a, a) != SLOT.get(w, w)] + [w]
            said.append("надел " + WEAR[w])
    update({"companion": {"accessories": cur}})
    return cur, ", ".join(said)
EMOTIONS = {"neutral": "спокойствие", "happy": "радость", "sad": "грусть", "angry": "злость", "surprised": "удивление",
            "relaxed": "умиротворение"}
ACTIVITIES = {"sit": "просто посидеть", "music": "слушать музыку", "handheld": "играть в портативку", "console": "играть в приставку",
              "tv": "смотреть мультики на диване", "campfire": "греться у костра", "sleep": "поспать"}
PLACES = {"corner": "в угол у часов", "window": "на рамку окна", "auto": "куда захочет"}
WEATHER = {"snow": "снег ❄", "rain": "дождь 🌧", "auto": "как за окном", "off": "выключена"}


ANIM_RU = {
    r"попей|пьёт|пей|чай|кофе|выпей": "Drinking", r"гитар": "Guitar Playing", r"пианино|фортепиано": "Piano Playing",
    r"спой|пой|поёт|микрофон": "Singing", r"поиграй в (игр|приставк|геймпад)|геймпад|играй в игр": "Gaming",
    r"телефон|позвони": "Talking On Phone", r"переписк|напиши сообщение|текст|смс": "Texting", r"печата|клавиатур": "Typing",
    r"планшет": "Standing Using Touchscreen Tablet", r"погладь|котик|собачк": "Petting Animal",
    r"посмейся|смейся|смех": "Laughing", r"похлопай|хлопай|аплодир": "Clapping", r"плач|поплачь": "Crying", r"испуг|бойся|страшно": "Terrified",
    r"злись|разозлись": "Angry", r"радуйся|ура|победа": "Victory", r"поздоровайся": "Standing Greeting",
    r"воздушный поцелуй|поцелуй": "Blow A Kiss", r"отдай честь|салют": "Salute", r"помолись": "Praying",
    r"зарядк|разминк|упражнен": "Warming Up", r"прыжки на месте|джампинг": "Jumping Jacks", r"зевни|зевает": "Yawn",
    r"ляг|приляг|полежи": "Lying Down", r"рэп|читай рэп": "Rapping", r"посчитай на пальцах": "Counting",
    r"гангнам": "Gangnam Style", r"макарен": "Macarena Dance", r"брейк": "Breakdance Uprock", r"робот": "Robot Hip Hop Dance",
    r"сальс": "Salsa Dancing", r"самб": "Samba Dancing", r"хип.?хоп": "Hip Hop Dancing", r"триллер": "Thriller Part 1",
    r"ymca|имка": "Ymca Dance", r"танец живота": "Belly Dance", r"цыпл|куриный": "Chicken Dance",
    r"румб": "Rumba Dancing", r"свинг": "Swing Dancing", r"джаз": "Jazz Dancing", r"шаффл": "Shuffling",
    r"танц|пляш": "dance", r"жест": "gesture", r"эмоци": "emotion",
}


def _catalog() -> list:
    import json
    from ..config import DATA_DIR
    try:
        return json.loads((DATA_DIR / "animations" / "library" / "catalog.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def resolve_anim(what: str) -> tuple[str, str]:
    """A clip name / category / his Russian words -> (value for the companion, how to say it). ('', reason) if none."""
    import re
    cat = _catalog()
    if not cat:
        return "", "библиотека анимаций пуста"
    w = (what or "").strip()
    for rx, name in ANIM_RU.items():
        if re.search(rx, w.lower()):
            w = name
            break
    if re.search(r"сидя|сядь|присядь|посиди|сидит|sitting", (what or "").lower()):
        names = {c["name"].lower(): c["name"] for c in cat}
        alias = {"clapping": "sitting clap", "talking on phone": "sitting talking", "cheering": "cheering while sitting",
                 "pointing": "sitting and pointing", "idle": "sitting idle", "typing": "sit to type"}
        for cand in (f"sitting {w.lower()}", f"{w.lower()} while sitting", f"sitting {w.lower().split()[0]}",
                     alias.get(w.lower(), "")):
            if cand in names:
                w = names[cand]
                break
    cats = {c["cat"] for c in cat}
    if w.lower() in cats:
        return w.lower(), f"случайная анимация из «{w.lower()}»"
    low = w.lower()
    hit = next((c for c in cat if c["name"].lower() == low), None) or \
        next((c for c in cat if low and low in c["name"].lower()), None)
    return (hit["name"], hit["name"]) if hit else ("", f"нет анимации «{what}»")


ROBOT_FACES = {"neutral": "обычная", "calm": "покерфейс / анализ / сарказм / фейспалм / забыла что-то",
               "happy": "радость / юмор / игривость",
               "sly": "хитрая", "shocked": "удивление", "laugh": "смеётся", "love": "влюблена", "angry": "злится",
               "tender": "умиление", "big_eyes": "интерес («а что за план?»)",
               "wow": "кошачье лицо (милота, кокетство, невинность, лукавство)", "sad": "грусть",
               "question": "непонимание / вопрос", "alert": "предупреждение", "broken": "ошибка", "money": "выгода",
               "logo": "заставка", "hello": "привет", "suspicious": "подозрение", "shy": "смущение", "cry": "плачет",
               "sleep": "спит"}


@tool("avatar",
      "Твоё тело-аватар (компаньон на рабочем столе, живёт на панели задач). action: " + ", ".join(ACTIONS)
      + ". emotion: " + ", ".join(EMOTIONS) + ". activity (маленький пиксельный Renard занимается делом): "
      + ", ".join(ACTIVITIES) + ". place: corner | window | auto. style (для dance): " + ", ".join(DANCES)
      + ". wear / take_off (аксессуары 3D-модели, через запятую; take_off=all снять всё): " + ", ".join(WEAR)
      + ". weather — погода на рабочем столе: snow | rain | auto (как за окном) | off. say — короткая фраза в облачке. "
      "anim — настоящая mocap-анимация 3D-модели: категория (dance, idle, gesture, emotion, props, sit, walk, misc) или "
      "имя/описание (Drinking, Guitar Playing, Gaming, Singing, Texting, Gangnam Style, Salsa Dancing, Laughing, Crying, "
      "Salute, Warming Up, «попей чай», «поиграй на гитаре»…). "
      "face — лицо-экран робота (если аватар — робот): " + ", ".join(ROBOT_FACES) + "; red=true — "
      "красный (злой) режим. "
      "Вызывай, когда просят что-то сделать аватаром (помаши, сядь, потанцуй, подойди, поиграй в приставку, надень шапку, пусть пойдёт снег) или выразить эмоцию.",
      {"action": S, "emotion": S, "say": S, "activity": S, "place": S, "style": S, "wear": S, "take_off": S, "weather": S,
       "anim": S, "face": S, "red": {"type": "boolean"}}, [])
async def avatar(action: str = "", emotion: str = "", say: str = "", activity: str = "", place: str = "", style: str = "",
                 wear: str = "", take_off: str = "", weather: str = "", anim: str = "", face: str = "",
                 red: bool | None = None) -> str:
    face = (face or "").strip().lower()
    if face or red is not None:
        if face and face not in ROBOT_FACES:
            return f"Нет такого лица «{face}». Есть: {', '.join(ROBOT_FACES)}"
        if BUS["broadcast"]:
            ev = {"type": "avatar", "action": "", "face": face, "say": (say or "")[:200]}
            if red is not None:
                ev["red"] = bool(red)
            await BUS["broadcast"](ev)
        if not (action or emotion or activity or place or anim):
            return "Аватар: лицо — " + (ROBOT_FACES.get(face, "") if face else "") + (" (красный режим)" if red else "")
    if anim:
        val, how = resolve_anim(anim)
        if not val:
            return f"Аватар: {how}. Категории: dance, idle, gesture, emotion, props, sit, walk, misc."
        from ..prefs import get
        if not get("companion.enabled", False):
            return "Аватар выключен (вкладка «Модель» → включить компаньона)."
        if BUS["broadcast"]:
            await BUS["broadcast"]({"type": "avatar", "anim": val, "emotion": (emotion or "").strip().lower(),
                                    "say": (say or "")[:200], "action": ""})
        if not (action or activity or place):
            return f"Аватар: {how}" + (" (только у 3D-модели)" if get("companion.kind", "") != "vrm" else "")
    weather = (weather or "").strip().lower()
    if weather:
        if weather not in WEATHER:
            return f"Погода бывает: {', '.join(WEATHER)}"
        from ..prefs import get, update
        if not get("companion.desktop", False):
            return "Погода живёт вместе с компаньоном на рабочем столе — включи его во вкладке «Модель» → «Окно»."
        update({"companion": {"weather": weather}})
        if BUS["broadcast"]:
            await BUS["broadcast"]({"type": "prefs"})
        if not (action or emotion or say or activity or place or wear or take_off):
            return "Аватар: погода — " + WEATHER[weather]
    if wear or take_off:
        _, said = dress(wear, take_off)
        if BUS["broadcast"]:
            await BUS["broadcast"]({"type": "prefs"})
        if not (action or emotion or say or activity or place):
            return "Аватар: " + (said or "ничего не изменилось")
    action, emotion = (action or "").strip().lower(), (emotion or "").strip().lower()
    activity, place = (activity or "").strip().lower(), (place or "").strip().lower()
    style = (style or "").strip().lower()
    style = style if style in DANCES else ""
    if action and action not in ACTIONS:
        return f"Нет такого действия «{action}». Можно: {', '.join(ACTIONS)}"
    if activity and activity not in ACTIVITIES:
        return f"Нет такого занятия «{activity}». Можно: {', '.join(ACTIVITIES)}"
    if emotion and emotion not in EMOTIONS:
        emotion = ""
    if place not in PLACES:
        place = ""
    if not (action or emotion or say or activity or place):
        return "Укажи action, activity или emotion."
    from ..prefs import get
    if not get("companion.enabled", False):
        return "Аватар выключен (вкладка «Модель» → включить компаньона)."
    if BUS["broadcast"]:
        await BUS["broadcast"]({"type": "avatar", "action": action, "emotion": emotion, "say": (say or "")[:200],
                                "activity": activity, "place": place, "style": style})
    parts = [ACTIONS[action] + (f" ({DANCES[style]})" if style else "")] if action else []
    if activity:
        parts.append(ACTIVITIES[activity])
    if place:
        parts.append(PLACES[place])
    if emotion:
        parts.append(EMOTIONS[emotion])
    return "Аватар: " + (", ".join(parts) or "фраза") + (" (на рабочем столе)" if get("companion.desktop", False) else "")
