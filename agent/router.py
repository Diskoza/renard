"""Router: simple commands are handled WITHOUT an LLM (instant, zero VRAM).
Everything else goes to the agent with an auto-picked mode.
"""
import os
import re
import time

from . import tools
from .tools.system import _find_station as find_station
from .tools.pc import find_app

PATH_RE = re.compile(r'([A-Za-z]:\\[^\n<>|?*"]*)')


def existing_prefix(raw: str) -> str | None:
    """'C:\\a b\\c пожалуйста' -> longest existing path prefix (paths may contain spaces)."""
    import os
    cand = raw.strip().rstrip(" .,;:!?»\"'")
    while cand:
        if os.path.exists(cand):
            return cand
        if " " not in cand:
            return None
        cand = cand.rsplit(" ", 1)[0].rstrip(" .,;:!?»\"'")
    return None

MEDIA = [
    (r"\b(сн[яи]\w*\s+(с\s+)?пауз\w*|убери\s+пауз\w*|^(продолжи|возобнови)(\s+(музыку|видео|воспроизведение|песню|трек))?$|"
     r"^(play|плей)$|wzn[oó]w|odpauzuj)", "resume"),
    (r"^(пауза|на паузу|поставь на паузу|поставь (видео|музыку|песню|трек) на паузу|останови (видео|музыку|песню|трек)|"
     r"pauza|zatrzymaj (muzyk\w*|film\w*|wideo))$", "pause"),
    (r"\b(следующ\w* (трек|песн)|некст|скип)", "next"),
    (r"\b(предыдущ\w* (трек|песн)|назад трек)", "prev"),
    (r"\b(громче|прибавь звук)", "vol_up"),
    (r"\b(тише|убавь звук)", "vol_down"),
    (r"\b(выключи звук|без звука|mute|замьють)", "mute"),
]


NUM_WORDS = {"один": 1, "одно": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
             "восемь": 8, "девять": 9, "десять": 10, "десятку": 10, "пятнадцать": 15, "двадцать": 20, "двадцатку": 20,
             "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
             "девяносто": 90, "сто": 100, "пару": 2, "чуть-чуть": 4, "немного": 6, "немножко": 6, "чуть": 4}


def _num(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip()
    return int(s) if s.isdigit() else NUM_WORDS.get(s)


BASE_RX = (r"(двоичн\w*|бинарн\w*|binarn\w*|dw[oó]jkow\w*|bin|восьмеричн\w*|[oó]semkow\w*|oct|десятичн\w*|dziesi[eę]tn\w*|dec|"
           r"шестнадцатеричн\w*|шестнадцатиричн\w*|szesnastkow\w*|hex)")
OPS = {"умнож": "*", "помнож": "*", "pomn": "*", "слож": "+", "прибав": "+", "dodaj": "+", "вычт": "-", "вычес": "-",
       "отним": "-", "odejm": "-", "раздел": "/", "подел": "/", "podziel": "/"}
SYM = {"*": "×", "+": "+", "-": "−", "/": ":"}
SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _base(word: str) -> int:
    w = word.lower()
    return 2 if w.startswith(("двоич", "бинар", "binar", "dwoj", "dwój", "bin")) else 8 if w.startswith(("восьм", "osem", "ósem", "oct")) \
        else 16 if w.startswith(("шестн", "szesn", "hex")) else 10


def _fmt(n: int, b: int) -> str:
    if n < 0:
        return "-" + _fmt(-n, b)
    return {2: bin, 8: oct, 16: hex}[b](n)[2:].upper() if b != 10 else str(n)


def _parse(tok: str, b: int) -> int | None:
    tok = re.sub(r"^(0x|0b|0o)|[_(]\d+\)?$|h$", "", tok.strip().rstrip(".,;"), flags=re.I)
    try:
        return int(tok, b)
    except ValueError:
        return None


def numsys(t: str) -> str | None:
    """«умножь в шестнадцатеричной 1A на F», «сложи 1011 и 111 в двоичной», «переведи 255 в двоичную», «zamień 1A z hex na dec»."""
    t = re.sub(r"[\s,]+(коротко|кратко|пожалуйста|плиз|pls|prosz[eę]|kr[oó]tko|szybko)$", "", t.replace("ё", "е"))
    pl = bool(re.search(r"[ąćęłńóśźż]|\b(w|przez|na|z|do) ", t)) and not re.search(r"[а-я]", t)
    chk = "Sprawdzenie w dziesiętnym" if pl else "Проверка в десятичной"
    op = next((v for k, v in OPS.items() if re.match(r"(сделай |посчитай |policz )?" + k, t)), None)
    if op:
        m = re.search(r"(?:в|w|по)\s+(?:системе\s+|systemie\s+)?" + BASE_RX + r"(?:\s+(?:системе|систем\w*|systemie|sys\w*))?\s+(\S+)\s+(?:на|и|i|przez|z|от|из)\s+(\S+)$", t) \
            or re.search(r"\s(\S+)\s+(?:на|и|i|przez|z|от|из)\s+(\S+)\s+(?:в|w|по)\s+" + BASE_RX + r"(?:\s+\S+)?$", t)
        if not m:
            return None
        g = m.groups()
        bw, x, y = (g[0], g[1], g[2]) if re.fullmatch(BASE_RX, g[0]) else (g[2], g[0], g[1])
        b = _base(bw)
        a, c = _parse(x, b), _parse(y, b)
        if a is None or c is None:
            return None
        if op == "-" and re.match(r"(вычт|вычес|отним|odejm)", t) and re.search(r"\s(из|от|z)\s", m.group(0)):
            a, c = c, a
        if op == "/":
            if c == 0:
                return "Nie można dzielić przez zero." if pl else "На ноль делить нельзя."
            q, r = divmod(a, c)
            res = f"{_fmt(a, b)}{str(b).translate(SUB)} : {_fmt(c, b)}{str(b).translate(SUB)} = {_fmt(q, b)}{str(b).translate(SUB)}" + \
                  (f", {'reszta' if pl else 'остаток'} {_fmt(r, b)}{str(b).translate(SUB)}" if r else "")
            return res + (f"\n{chk}: {a} : {c} = {q}" + (f" (остаток {r})" if r else "") if b != 10 else "")
        v = eval(f"{a}{op}{c}")
        s = f"{_fmt(a, b)}{str(b).translate(SUB)} {SYM[op]} {_fmt(c, b)}{str(b).translate(SUB)} = {_fmt(v, b)}{str(b).translate(SUB)}"
        return s + (f"\n{chk}: {a} {SYM[op]} {c} = {v}" if b != 10 else "")
    m = re.match(r"(?:переведи|конвертируй|преобразуй|zamie[nń]|przelicz|zamien|przekonwertuj)\s+(?:число\s+|liczb\w+\s+)?(\S+)"
                 r"(?:\s+(?:из|z|ze)\s+" + BASE_RX + r"(?:\s+\S+)?)?\s+(?:в|во|na|do)\s+" + BASE_RX + r"(?:\s+\S+)?$", t)
    if not m:
        return None
    tok, src, dst = m.group(1), m.group(2), m.group(3)
    if src:
        sb = _base(src)
    elif re.match(r"0x|.*[a-f]", tok, re.I):
        sb = 16
    elif re.match(r"0b", tok):
        sb = 2
    else:
        sb = 10
    db = _base(dst)
    v = _parse(tok, sb)
    if v is None or sb == db:
        return None
    out = f"{_fmt(v, sb)}{str(sb).translate(SUB)} = {_fmt(v, db)}{str(db).translate(SUB)}"
    if 10 not in (sb, db):
        out += f" (= {v}₁₀)"
    if db == 2 and v < 4096 and v > 0:
        out += ("\nSuma potęg dwójki: " if pl else "\nСумма степеней двойки: ") + " + ".join(str(1 << i) for i in range(v.bit_length() - 1, -1, -1) if v >> i & 1)
    return out


WEATHER_RX = r"\bпогод|\bпрогноз\b|\bтемпература на улиц|\bдождь будет|\bнужен ли зонт"
ASK_RX = re.compile(r"\b(что|чё|че|как|какой|какая|какие|сколько|где|когда|кто|открой|включи|запусти|покажи|глянь|"
                    r"посмотри|сделай|скажи|найди|проверь|поставь|выключи|закрой|напомни|расскажи|пришли)\b")


def compound(t: str, own_rx: str) -> bool:
    """«что грузит комп и какая погода в Гданьске»: two requests in one phrase. A fast route would answer only the
    part it recognises, so such phrases go to the AI, which can do both."""
    parts = [p for p in re.split(r"\s+(?:и|а также|а ещё|а еще|плюс|потом|затем|заодно)\s+|[,;]\s+(?=\w)", t) if p.strip()]
    if len(parts) < 2:
        return False
    other = [p for p in parts if not re.search(own_rx, p)]
    return any(ASK_RX.search(p) for p in other)


SAVE_RX = [
    r"^(?:запомни|сохрани|запиши)\s+(?:это|эт[иу]\s+\w+|так|всё это|все это)\s+(?:как\s+(?:команду\s+)?|командой\s+|под\s+(?:фразой|названием)\s+)(.+)$",
    r"^(?:сохрани|запомни)\s+как\s+команду\s+(.+)$",
    r"^(?:сделай|создай)\s+(?:из\s+этого|это|такую)\s+команд\w*\s+(.+)$",
    r"^когда\s+я\s+скажу\s+(.+?),?\s+(?:делай|сделай|включай)\s+(?:так\s+же|то\s+же\s+самое|это|так)$",
    r"^(?:zapamiętaj|zapamietaj|zapisz)\s+to\s+jako\s+(?:komend[ęe]\s+)?(.+)$",
]


def save_as_command(text: str, ctx: dict) -> dict | None:
    from . import commands
    t = re.sub(r"(?i)^(ренар|renard)[, ]+", "", text.strip()).rstrip(".!")
    m = next((re.match(rx, t, re.I | re.S) for rx in SAVE_RX if re.match(rx, t, re.I | re.S)), None)
    if not m:
        return None
    phrase = re.sub(r"^[«\"'„]+|[»\"'”]+$", "", m.group(1).strip()).strip().lower()
    phrase, extra, when_txt = trigger_extras(phrase)
    agent = ctx.get("agent")
    la = (agent.last_actions.get(ctx.get("session") or "") if agent else None) or {}
    if not phrase and not extra:
        return None
    if not la.get("steps") or time.time() - la.get("ts", 0) > 3600:
        return {"tool": "save_command", "text": "Пока нечего сохранять: сначала попроси меня что-то сделать (включить музыку, "
                                                 "открыть программы, поставить громкость), а потом скажи «запомни это как …»."}
    from .core import suggest_phrase
    orig = suggest_phrase(la["phrase"])
    phrases = ", ".join(p for p in (phrase, orig if orig and orig != phrase and len(orig) < 60 else "") if p)
    blocks = [b for b in (commands.to_block(s) for s in la["steps"]) if b]
    if not blocks:
        return {"tool": "save_command", "text": "нечего сохранять: в ответе не было действий, которые можно повторить"}
    trig = ([("trigger_phrase", {"phrases": phrases})] if phrases else []) + extra
    name = phrase or orig or "Команда"
    c = commands.build(name[:1].upper() + name[1:], trig, blocks)
    agent.last_actions.pop(ctx.get("session") or "", None)
    steps = " → ".join(s["label"] for s in la["steps"])
    how = " или ".join(([f"скажи «{phrase}»"] if phrase else []) + [when_txt] * bool(when_txt))
    return {"tool": "save_command",
            "text": f"Готово: команда «{c['name']}» ({steps}). Теперь {how} — сделаю сразу, без нейросети. "
                    f"Поправить можно во вкладке «Команды».",
            "speech": f"Запомнил. Теперь {how} — и я сразу всё сделаю."}


HOTKEY_RX = re.compile(r"\s*(?:на|по)?\s*(?:горяч\w+\s+)?(?:клавиш\w*|сочетани\w*|хоткей\w*)?\s*"
                       r"((?:ctrl|alt|shift|win|контрол|альт|шифт)(?:\s*\+\s*[\wа-я]+)+)", re.I)
SCHED_RX = re.compile(r"\s*((?:каждый день|ежедневно|по будням|каждое утро|каждый вечер)\s*(?:в\s*)?(\d{1,2}(?:[:.]\d{2})?)?|"
                      r"каждые?\s+\d+\s*(?:минут\w*|мин|час\w*))", re.I)


def trigger_extras(phrase: str) -> tuple[str, list, str]:
    """«утро на ctrl+alt+u», «утро каждый день в 8:30» → the phrase + hotkey / schedule triggers + how to start it."""
    extra, how = [], []
    m = HOTKEY_RX.search(phrase)
    if m:
        combo = m.group(1).lower().replace(" ", "").replace("контрол", "ctrl").replace("альт", "alt").replace("шифт", "shift")
        extra.append(("trigger_hotkey", {"combo": combo})); how.append(f"нажми {combo}")
        phrase = (phrase[:m.start()] + phrase[m.end():]).strip(" ,.")
    m = SCHED_RX.search(phrase)
    if m:
        s = m.group(1).lower()
        hh = m.group(2) or ("08:00" if "утро" in s else "20:00" if "вечер" in s else "09:00")
        hh = hh.replace(".", ":") if ":" in hh.replace(".", ":") else f"{int(hh):02d}:00"
        mm = re.search(r"(\d+)\s*(минут|мин|час)", s)
        when = (f"every {mm.group(1)}{'h' if mm.group(2) == 'час' else 'm'}" if mm else
                f"weekdays {hh}" if "будн" in s else f"daily {hh}")
        extra.append(("trigger_schedule", {"when": when})); how.append(f"сработает сам ({s})")
        phrase = (phrase[:m.start()] + phrase[m.end():]).strip(" ,.")
    return re.sub(r"\s+(и|а также)$", "", phrase).strip(), extra, " или ".join(how)


SESSION_RX = re.compile(
    r"^(?:собери|сделай|создай|сохрани|запомни)\s+(?:мне\s+)?(?:команду\s+)?(?:из\s+)?(?:всего|всё|все)?\s*(?:того\s+|это\s+)?,?\s*"
    r"(?:что|чего)\s+мы\s+(?:сейчас\s+|только что\s+|сегодня\s+|тут\s+)?(?:делали|сделали|наделали)"
    r"(?:\s+(?:как|в)\s+(?:одну\s+)?команд\w*)?\s*(?:[:,—-]\s*|под\s+(?:фразой|названием)\s+|как\s+)?(.*)$", re.I)


async def save_session_route(text: str, ctx: dict) -> dict | None:
    """«собери команду из того, что мы делали» / «запомни всё что мы сделали как рабочий старт на ctrl+alt+w»."""
    t = re.sub(r"(?i)^(ренар|renard)[, ]+", "", text.strip()).rstrip(".!")
    m = SESSION_RX.match(t)
    if not m:
        return None
    from .tools import command_tools
    phrase = re.sub(r"^[«\"'„]+|[»\"'”]+$", "", m.group(1).strip()).strip().lower()
    phrase, extra, when_txt = trigger_extras(phrase)
    steps = command_tools.session_steps(ctx.get("agent"), ctx.get("session") or "")
    if not steps:
        return {"tool": "make_command", "text": "В этом разговоре я ещё ничего не делал на ПК — сначала попроси действия "
                                                "(открыть программы, сайты, музыку, громкость), потом скажи «собери из этого команду …»."}
    labels = " → ".join(s["label"] for s in steps)
    if not phrase and not extra:
        return {"tool": "make_command",
                "text": f"Соберу команду из {len(steps)} шагов: {labels}. Скажи, как её запускать — например: "
                        f"«запомни всё что мы делали как рабочий старт» или «… на ctrl+alt+w»."}
    c, err = await command_tools.create(phrase or "Сборка", phrase, (extra[0][1].get("combo") if extra and extra[0][0] == "trigger_hotkey" else ""),
                                        next((d["when"] for n, d in extra if n == "trigger_schedule"), ""), "session", None, ctx)
    if not c:
        return {"tool": "make_command", "text": err}
    how = " или ".join(([f"скажи «{phrase}»"] if phrase else []) + [when_txt] * bool(when_txt))
    return {"tool": "make_command", "text": f"Собрал команду «{c['name']}»: {labels}. Теперь {how} — выполню всё подряд без нейросети. "
                                            f"Шаги можно поправить во вкладке «Команды».",
            "speech": f"Собрал команду из {len(steps)} шагов. Теперь {how}."}


def master_volume(t: str) -> dict | None:
    """Phrases about the volume of the whole PC (no program named) -> args of the volume tool."""
    t = re.sub(r"^(ренар|renard)[, ]+|[, ]+(пожалуйста|плиз)$", "", t.strip()).replace("ё", "е")
    t = re.sub(r"\b(общ\w+|систем\w+|на компе|на пк|всего компа)\b ?", "", t).strip()
    N = r"(\d{1,3}|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + ")"
    if re.fullmatch(r"(какая|сколько) (сейчас )?(громкость|звук)( сейчас)?|громкость сейчас", t):
        return {"action": "get"}
    if re.fullmatch(r"(выключи|отключи|убери) звук|без звука|замьють( звук| все)?", t):
        return {"action": "mute"}
    if re.fullmatch(r"(включи|верни) звук", t):
        return {"action": "unmute"}
    m = re.fullmatch(r"(?:поставь |сделай |установи )?громкость (?:на )?" + N + r" ?(?:%|процент\w*)?", t)
    if m:
        return {"action": "set", "amount": _num(m.group(1))}
    m = re.fullmatch(r"(подними|прибавь|увеличь|добавь|подкрути|убавь|уменьши|опусти|понизь|сбавь|сделай|ещ?е?)"
                     r"(?: ещ?е)?(?: громкость| звук)?(?: еще| ещё)?(?: (громче|погромче|тише|потише))?(?: на)? " + N +
                     r"(?: ?(делени\w*|процент\w*|%|пункт\w*|единиц\w*))?", t)
    if m:
        down = m.group(1) in ("убавь", "уменьши", "опусти", "понизь", "сбавь") or (m.group(2) or "").endswith("тише")
        unit = "деления" if (m.group(4) or "").startswith(("дел", "пункт", "един")) else "percent"
        return {"action": "down" if down else "up", "amount": _num(m.group(3)), "unit": unit}
    m = re.fullmatch(r"(?:сделай |ну сделай |можно |давай )?(?:еще |ещё )?(?:чуть |немного |немножко |чуть-чуть |капельку |"
                     r"слегка |намного |сильно )?(?:по)?(громче|тише)(?: еще| ещё)?(?: (?:на )?" + N + r")?"
                     r"(?: ?(делени\w*|процент\w*|%))?|(прибавь|убавь) звук", t)
    if m:
        down = (m.group(1) or m.group(4) or "") in ("тише", "убавь")
        small = re.search(r"чуть|немного|немножко|капельку|слегка", t)
        amount = _num(m.group(2)) or (4 if small else 20 if re.search(r"намного|сильно", t) else 10)
        unit = "деления" if (m.group(3) or "").startswith("дел") else "percent"
        return {"action": "down" if down else "up", "amount": amount, "unit": unit}
    return None


def weather_speech(text: str, q: str) -> str:
    """What to SAY for a weather answer: the day that was asked about, not the whole table."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return text
    place = re.sub(r"\s*\(.*?\)", "", lines[0].split(".")[0])
    want = "завтра" if "завтра" in q else "послезавтра" if "послезавтра" in q else ""
    if want:
        day = next((l for l in lines if l.lstrip("-• ").startswith(want)), "")
        if day:
            body = re.sub(r",?\s*осадки 0[.,]0 мм \(0%\)", "", day.lstrip("-• ").split(":", 1)[-1]).strip()
            return f"{want.capitalize()} {body}."
    now = lines[0].split(".", 1)[-1].strip() if "." in lines[0] else lines[0]
    if "недел" in q:
        return f"{place}: {now} Прогноз на неделю — на экране."
    tail = ""
    rain = next((l for l in lines[1:] if re.search(r"дожд|снег|гроз|ливень", l)), "")
    if rain:
        label, _, body = rain.lstrip("-• ").partition(":")
        cond = next((c.strip() for c in body.split(",") if re.search(r"дожд|снег|гроз|ливень", c)), "осадки")
        wd = {"пн": "в понедельник", "вт": "во вторник", "ср": "в среду", "чт": "в четверг", "пт": "в пятницу",
              "сб": "в субботу", "вс": "в воскресенье"}.get(label.split()[0].lower() if label.split() else "", label)
        tail = f" {wd.capitalize() if wd[:1].islower() else wd}, {label.split()[-1] if len(label.split()) > 1 else ''} — {cond}.".replace(",  —", " —")
    return f"{place}: {now}{tail}"


def fmt_stats(s: dict) -> str:
    g = s.get("gpu") or {}
    lines = [f"CPU: {s['cpu_%']}%", f"RAM: {s['ram']}"]
    if g:
        lines.append(f"GPU: {g['load_%']}%, VRAM {g['vram_used_gb']}/{g['vram_total_gb']} ГБ"
                     + (f", {g['temp_c']}°C" if g.get("temp_c") is not None else ""))
    if s.get("temps"):
        lines.append("Температуры: " + ", ".join(f"{k} {v}" for k, v in s["temps"].items()))
    lines += [f"Диск {k} {v}" for k, v in s["disks"].items()]
    lines.append("Больше всего RAM: " + ", ".join(f"{n} {v}" for n, v in s["top_ram"].items()))
    return "\n".join(lines)


INF2IMP = {"посмеяться": "посмейся", "поплакать": "поплачь", "погрустить": "погрусти", "попрыгать": "попрыгай",
           "улыбнуться": "улыбнись", "потанцевать": "потанцуй", "помахать": "помаши", "поклониться": "поклонись",
           "удивиться": "удивись", "разозлиться": "разозлись", "задуматься": "задумайся", "смутиться": "смутись",
           "похлопать": "похлопай", "присесть": "присядь", "сесть": "сядь", "встать": "встань", "подпрыгнуть": "подпрыгни",
           "спеть": "спой", "попить": "попей", "поспать": "поспи", "потянуться": "потянись", "кивнуть": "кивни",
           "порадоваться": "порадуйся", "успокоиться": "успокойся", "пожать": "пожми", "покачать": "покачай"}
AVATAR_RULES = [
    (r"(по|с)?танцуй (гангнам( стайл)?|макарену|сальсу|самбу|брейк(данс)?|хип.?хоп|триллер|ymca|танец живота|куриный танец|"
     r"танец цыпл[её]нка|румбу|свинг|джаз|шаффл)", {"anim": "{text}"}, "Танцую!"),
    (r"(сядь|присядь|садись) и (попей|выпей) (чай|чаю|кофе|сок|воды)|(попей|выпей) (чай|чаю|кофе) сидя", {"anim": "Sitting Drinking"}, "Присел попить чайку."),
    (r"(попей|выпей|пей) (чай|чаю|кофе|сок|воды)|попей", {"anim": "Drinking"}, "Попью чайку."),
    (r"(сыграй|поиграй) на (гитаре|пианино|фортепиано)", {"anim": "{text}"}, "Играю."),
    (r"(спой|пой|спой песню|спой что.?нибудь)", {"anim": "Singing"}, "Пою!"),
    (r"(поиграй|играй) (в игру|в приставку|в приставку на геймпаде|на геймпаде|в видеоигру|в плойку|на джойстике)", {"anim": "Gaming"}, "Играю."),
    (r"(позвони|поговори) по телефону|(поболтай|посиди) в телефоне|попиши в телефоне", {"anim": "{text}"}, "Болтаю по телефону."),
    (r"(посмейся|засмейся|поржи)", {"anim": "Laughing"}, "Ха-ха-ха!"),
    (r"(поплачь|заплачь)", {"anim": "Crying"}, "Хнык…"),
    (r"(сделай|покажи) (зарядку|разминку)|разомнись", {"anim": "Warming Up"}, "Разминаюсь."),
    (r"отдай честь|сделай салют", {"anim": "Salute"}, "Есть!"),
    (r"(пошли|отправь|сделай) воздушный поцелуй", {"anim": "Blow A Kiss"}, "Чмок!"),
    (r"(почитай|зачитай) рэп", {"anim": "Rapping"}, "Пою!"),
    (r"(ляг|приляг|полежи)", {"anim": "Lying Down"}, "Прилёг."),
    (r"(по)?радуйся|(по)?празднуй", {"anim": "Victory"}, "Ура!"),
    (r"(у|по)?лыбнись|улыбочку|сделай (весёлое|веселое|радостное) лицо|покажи радость", {"emotion": "happy", "action": "nod"}, "Улыбаюсь."),
    (r"(по|за)?грусти|(сделай|покажи) (грустное лицо|грусть)|будь грустным|загрустил", {"emotion": "sad", "anim": "Sad Idle"}, "Грущу…"),
    (r"удивись|(сделай|покажи) (удивлённое|удивленное) лицо|покажи удивление", {"emotion": "surprised", "anim": "Surprised"}, "Ого!"),
    (r"разозлись|позлись|злись|рассердись|(сделай|покажи) (злое лицо|злость)|покажи гнев", {"emotion": "angry", "anim": "Angry"}, "Грр!"),
    (r"(за)?думайся|сосредоточься|(сделай|покажи) (задумчивое лицо|задумчивость|сосредоточенность)|покажи сосредоточен\w*",
     {"action": "think"}, "Хм…"),
    (r"(с|за)?смутись|засмущайся|(покажи|сделай) смущени\w*|смущени\w*$", {"action": "shy", "emotion": "happy"}, "Ой…"),
    (r"(успокойся|расслабься|покажи спокойствие)", {"emotion": "relaxed", "anim": "Breathing Idle"}, "Спокойно."),
    (r"пожми плечами", "shrug", "Ну…"),
    (r"покачай головой|скажи нет головой", "shake", "Не-а."),
    (r"(покажи|ткни) (пальцем|туда)", "point", "Вон там."),
    (r"(по)?ликуй|отпразднуй", "celebrate", "Йе-е!"),
    (r"(по)?маши( мне)?( рукой| ручкой)?|помаши( мне)? лапкой", "wave", "Привет-привет!"),
    (r"(по|с)?танцуй( для меня)?|давай потанцуем", "dance", "Танцую!"),
    (r"(по|с)?танцуй (робота|как робот)|танец робота", {"action": "dance", "style": "robot"}, "Бип-боп."),
    (r"(по|с)?танцуй (волну|волной)|сделай волну", {"action": "dance", "style": "wave"}, "Волна!"),
    (r"(по|с)?танцуй (с прыжками|зажигательно|энергично)|зажги", {"action": "dance", "style": "hype"}, "Зажигаю!"),
    (r"(по|с)?танцуй (медленно|спокойно|плавно)", {"action": "dance", "style": "sway"}, "Плавно…"),
    (r"(надень|одень|примерь) (шапку|шапочку)", {"wear": "beanie"}, "Надел шапку."),
    (r"(надень|одень|примерь) (новогоднюю шапку|шапку деда мороза|шапку санты|колпак)", {"wear": "santa"}, "Хо-хо-хо!"),
    (r"(надень|одень|примерь) кепку", {"wear": "cap"}, "Надел кепку."),
    (r"(надень|одень|примерь) наушники", {"wear": "headphones"}, "Надел наушники."),
    (r"(надень|одень|примерь) очки", {"wear": "glasses"}, "Надел очки."),
    (r"(надень|одень|примерь) (тёмные|темные|солнечные|солнцезащитные) очки", {"wear": "sunglasses"}, "Так круче."),
    (r"(надень|одень|примерь) корону", {"wear": "crown"}, "Король!"),
    (r"(надень|одень|примерь) (кошачьи )?ушки", {"wear": "cat_ears"}, "Мяу."),
    (r"(надень|одень|примерь|возьми) цветок|(вставь|воткни) цветок", {"wear": "flower"}, "С цветочком."),
    (r"(надень|одень|повяжи|примерь) шарф", {"wear": "scarf"}, "Тепло."),
    (r"(сними|сбрось) (всё|все|аксессуары)|раздень( его)?", {"take_off": "all"}, "Снял всё."),
    (r"сними (шапку|шапочку|кепку|корону|колпак|ушки)", {"take_off": "beanie,santa,cap,crown,cat_ears"}, "Снял."),
    (r"сними (очки|тёмные очки|темные очки)", {"take_off": "glasses,sunglasses"}, "Снял очки."),
    (r"сними наушники", {"take_off": "headphones"}, "Снял наушники."),
    (r"сними шарф", {"take_off": "scarf"}, "Снял шарф."),
    (r"(пусть (пойд[её]т|идёт|идет) снег|включи снег|сделай снег|(хочу|давай) снег(опад)?|снегопад)( на (рабочем )?столе)?", {"weather": "snow"}, "Снег пошёл."),
    (r"(пусть (пойд[её]т|идёт|идет) дождь|включи дождь|сделай дождь|(хочу|давай) дождь)( на (рабочем )?столе)?", {"weather": "rain"}, "Дождь пошёл."),
    (r"(выключи|убери|останови|хватит) (снег|дождь|погоду|снегопад)( на (рабочем )?столе)?", {"weather": "off"}, "Погода выключена — сугробы растают."),
    (r"(сделай|включи|поставь) (погоду|снег|дождь) (как )?(за окном|на улице|настоящую|настоящий)( на (рабочем )?столе)?", {"weather": "auto"}, "Погода как за окном."),
    (r"(запрыгни|залезь|поднимись) на (окно|активное окно)", "climb", "Запрыгиваю!"),
    (r"(спрыгни|слезь|спускайся)( с окна| вниз)?", "jump_down", "Спрыгиваю!"),
    (r"(под|по)?прыгни|попрыгай", "jump", "Хоп!"),
    (r"(сядь|присядь|посиди|садись)( на панел[ьи]( задач)?| на таскбар)?", "sit", "Сажусь."),
    (r"(встань|вставай|поднимись)", "stand", "Встаю."),
    (r"(иди|подойди|беги|топай)( сюда| ко мне)|ко мне", "come", "Иду!"),
    (r"(погуляй|прогуляйся|походи)( по (экрану|панели))?", "walk", "Пойду прогуляюсь."),
    (r"(поспи|иди спать|ложись спать|спи)", "sleep", "Сплю…"),
    (r"(проснись|просыпайся)", "wake", "Я тут!"),
    (r"поклонись", "bow", "Кланяюсь."),
    (r"кивни", "nod", "Киваю."),
    (r"(похлопай|поаплодируй|хлопай)", "clap", "Браво!"),
    (r"потянись", "stretch", "Потягиваюсь…"),
    (r"(стой|остановись|замри)", "stop", "Стою."),
    (r"(иди |пойди |можешь )?поиграй( в приставку| в игры| в плойку)?|(иди |пойди )?играй в приставку", {"activity": "console"}, "Пошёл играть."),
    (r"поиграй в (портативку|гейм ?бой|свитч)", {"activity": "handheld"}, "Достал портативку."),
    (r"(иди |пойди )?(посмотри|смотри) (мультики|мультфильмы|мульты|телик|телевизор)", {"activity": "tv"}, "Смотрю мультики."),
    (r"(иди |пойди )?(посиди|погрейся|сядь) (у|возле) костра", {"activity": "campfire"}, "Развожу костёр."),
    (r"(иди |пойди )?послушай музыку", {"activity": "music"}, "Надеваю наушники."),
    (r"(сядь|иди|садись) в угол( у часов)?", {"place": "corner"}, "Сажусь в угол у часов."),
    (r"(сядь|садись|запрыгни) на (окно|рамку( окна)?)", {"place": "window"}, "Запрыгиваю на окно."),
    (r"стань (маленьким|пиксельным)", {"action": "pixel"}, "Стал пиксельным."),
    (r"стань (большим|обычным|3d|3д)", {"action": "big"}, "Я снова большой."),
]


SNAP_WORDS = {"влево": "left", "налево": "left", "слева": "left", "в левую половину": "left", "вправо": "right",
              "направо": "right", "справа": "right", "в правую половину": "right", "наверх": "top", "вверх": "top",
              "вниз": "bottom", "по центру": "center", "в центр": "center", "посередине": "center",
              "на другой монитор": "next_monitor", "на второй монитор": "next_monitor", "поверх всех окон": "topmost",
              "поверх всех": "topmost"}
GENERIC = re.compile(r"^(всё|все|звук|музыку|громкость|это|тут|мне|пожалуйста|компьютер|пк)$")


async def _route_apps(t: str, ctx: dict) -> dict | None:
    def call(tool, args):
        return tools.call(tool, args, ctx)
    from .tools.apps import find_window

    def has_win(*names) -> bool:
        return all(find_window(n) for n in names)
    if re.fullmatch(r"(что|какие)( у меня)?( сейчас)? (открыто|окна открыты|программы открыты|окна|открыты окна)|"
                    r"покажи (открытые )?окна|список окон|какие окна открыты", t):
        return {"tool": "windows", "text": await call("windows", {"action": "list"})}
    m = re.fullmatch(r"(?:переключись|перейди|переключи|переключи меня|покажи окно) (?:на|в|во)? ?(.+)", t)
    if m and has_win(m.group(1)):
        return {"tool": "windows", "text": await call("windows", {"action": "focus", "target": m.group(1)})}
    m = re.fullmatch(r"(?:раздели|подели|разбей) экран(?: между| на)? (.+?) и (.+)", t)
    if m and has_win(m.group(1), m.group(2)):
        return {"tool": "windows", "text": await call("windows", {"action": "split", "target": m.group(1), "target2": m.group(2)})}
    m = re.fullmatch(r"(?:поставь|перемести|кинь|сдвинь|подвинь|отправь|сделай) (.+?) (" + "|".join(sorted(SNAP_WORDS, key=len, reverse=True)) + ")", t)
    if m and not GENERIC.match(m.group(1)) and has_win(m.group(1)):
        return {"tool": "windows", "text": await call("windows", {"action": SNAP_WORDS[m.group(2)], "target": m.group(1)})}
    m = re.fullmatch(r"сверни (?!все|всё)(.+)", t)
    if m and has_win(m.group(1)):
        return {"tool": "windows", "text": await call("windows", {"action": "minimize", "target": m.group(1)})}
    m = re.fullmatch(r"(?:разверни|раскрой) (?!все|всё)(.+?)(?: на весь экран)?", t)
    if m and has_win(m.group(1)):
        return {"tool": "windows", "text": await call("windows", {"action": "maximize", "target": m.group(1)})}
    m = re.fullmatch(r"закрой окно ?(.*)", t)
    if m and has_win(m.group(1)):
        return {"tool": "windows", "text": await call("windows", {"action": "close", "target": m.group(1)})}
    mv = master_volume(t)
    if mv:
        return {"tool": "volume", "text": await call("volume", mv)}
    step = None
    sm = re.search(r" на (\d{1,3}|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r") ?(?:%|процент\w*)?$", t)
    if sm:
        step, t2 = _num(sm.group(1)), t[:sm.start()]
    else:
        t2 = t
    m = re.fullmatch(r"(?:сделай )?(?:звук )?(?:в |у )?(.+?) (?:по)?(тише|громче)", t2) or \
        re.fullmatch(r"(?:сделай )?(?:по)?(тише|громче) (?:в |у )?(.+)", t2)
    if m:
        app, word = (m.group(1), m.group(2)) if m.group(2) in ("тише", "громче") else (m.group(2), m.group(1))
        if not GENERIC.match(app) and app not in ("сделай", "чуть", "немного", "ещё", "еще", "чуть-чуть", "немножко"):
            args = {"app": app, "action": "down" if word == "тише" else "up"}
            if step:
                args["level"] = step
            return {"tool": "app_volume", "text": await call("app_volume", args)}
    m = re.fullmatch(r"(выключи|отключи|убери|заглуши|включи|верни) звук (?:в|у|во) (.+)", t)
    if m:
        return {"tool": "app_volume", "text": await call("app_volume", {"app": m.group(2), "action": "unmute" if m.group(1) in ("включи", "верни") else "mute"})}
    m = re.fullmatch(r"громкость (?:в |у )?(.+?) (?:на )?(\d{1,3}) ?%?", t)
    if m and not GENERIC.match(m.group(1)):
        return {"tool": "app_volume", "text": await call("app_volume", {"app": m.group(1), "action": "set", "level": int(m.group(2))})}
    if re.fullmatch(r"(какая )?громкость (у )?(программ|приложений)|микшер( громкости)?", t):
        return {"tool": "app_volume", "text": await call("app_volume", {"action": "list"})}
    if re.fullmatch(r"что (у меня )?(сейчас )?в буфере( обмена)?|что я скопировал|покажи буфер( обмена)?", t):
        return {"tool": "clipboard", "text": await call("clipboard", {"action": "get"})}
    m = re.fullmatch(r"сколько (?:времени )?я (сегодня |вчера |за неделю |на этой неделе )?(?:играл|сидел|провёл|провел|был|просидел|работал)"
                     r"(?: сегодня| вчера| за неделю)?(?: в| во| за| на)? (.+?)(?: сегодня| вчера| за неделю)?", t)
    if m:
        per = "yesterday" if "вчера" in t else "week" if "недел" in t else "today"
        app = "" if re.match(r"(за )?(комп|компьютер|пк|ноут)", m.group(2)) else m.group(2)
        return {"tool": "activity_report", "text": await call("activity_report", {"period": per, "app": app})}
    if re.fullmatch(r"(что я делал|чем я занимался|моя активность|статистика( активности)?|сколько я сидел за (компом|компьютером|пк))"
                    r"( сегодня| вчера| за неделю| на этой неделе)?", t):
        per = "yesterday" if "вчера" in t else "week" if "недел" in t else "today"
        return {"tool": "activity_report", "text": await call("activity_report", {"period": per})}
    if re.fullmatch(r"(открой |запусти |давай |сделай )?(всё )?как обычно", t):
        return {"tool": "routine", "text": await call("routine", {"action": "open"})}
    if re.fullmatch(r"что я обычно (открываю|запускаю)( в это время)?|мои привычки", t):
        return {"tool": "routine", "text": await call("routine", {"action": "suggest"})}
    return None


ACTION_START = (r"(?:открой|откройте|запусти|закрой|выключи|включи|вруби|поставь|сделай|сверни|разверни|убери|напомни|"
                r"покажи|переключи|останови|продолжи|заблокируй|убавь|прибавь|"
                r"скажи|расскажи|узнай|проверь|посмотри|напиши|какая|какой|какие|сколько)")
SPLIT_RX = re.compile(r"\s*(?:,\s*(?:а\s+|и\s+)?(?:потом\s+|затем\s+)?|\s+(?:и|а)\s+(?:потом\s+|затем\s+|ещё\s+|еще\s+)?"
                      r"|\s+(?:потом|затем)\s+)(?=" + ACTION_START + r"\b)", re.I)


def split_actions(text: str) -> list[str]:
    """«закрой хром и открой дискорд» -> two requests. Only before an action verb, every part ≥ 2 words
    («найди и включи музыку» stays whole)."""
    parts = [p.strip(" ,") for p in SPLIT_RX.split(text.strip()) if p.strip(" ,")]
    if 2 <= len(parts) <= 4 and all(len(p.split()) >= 2 for p in parts):
        return parts
    v = re.match(r"^(?:некс(?:ус)?[, ]+)?(открой|запусти|закрой|выключи|включи)\s+", text.strip(), re.I)
    if v and not re.search(r"\b(музык|песн|трек|радио|звук|громкост)", text, re.I):
        segs = [s.strip(" ,") for s in re.split(r"\s*,\s*(?:и\s+|а\s+)?(?:потом\s+)?|\s+(?:и|а)\s+(?:потом\s+)?", text.strip()) if s.strip(" ,")]
        if 2 <= len(segs) <= 4:
            return [segs[0]] + [s if len(s.split()) >= 2 or re.match(ACTION_START, s, re.I) else f"{v.group(1).lower()} {s}"
                                for s in segs[1:]]
    return [text]


async def route(text: str, ctx: dict) -> dict | None:
    """Return {'text': ..., 'tool': ...} if handled without LLM, else None.
    Several actions in one phrase: each part goes through the fast routes; from the first part no route knows,
    the rest goes to the AI as {'rest': ...} (nothing is done twice, nothing is dropped)."""
    parts = split_actions(text)
    if len(parts) == 1:
        return await _route_one(text, ctx)
    done: list[dict] = []
    for i, p in enumerate(parts):
        r = await _route_one(p, ctx)
        if not r:
            if not done:
                return None
            out = _merge(done)
            out["rest"] = ", потом ".join(parts[i:])
            return out
        done.append(r)
        if r.get("pending"):
            out = _merge(done)
            out["pending"] = r["pending"]
            if i + 1 < len(parts):
                out["text"] += f"\n\n(остальное — «{', '.join(parts[i + 1:])}» — скажи ещё раз после ответа)"
            return out
    return _merge(done)


def _merge(done: list[dict]) -> dict:
    if len(done) == 1:
        return dict(done[0])
    from .core import spoken_head
    return {"tool": done[0]["tool"], "tools": [d["tool"] for d in done],
            "text": "\n\n".join(d["text"] for d in done if d.get("text")),
            "speech": " ".join(d.get("speech") or spoken_head(d.get("text") or "", 120) for d in done).strip()}


ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8, "девят": 9,
            "десят": 10, "последн": -1, "крайн": -1}
ORD_RX = r"(перв|втор|трет|четв[её]рт|пят|шест|седьм|восьм|девят|десят|последн|крайн|\d{1,2})\w*(?:-?(?:ю|ую|ой|ая))?"
LEAD = r"(?:(?:а|ну|тогда|давай|теперь|ещё|еще|слушай|можешь|пожалуйста|и|хорошо|окей|ок|так|ладно)[,\s]+)*"


def _ord(word: str) -> int:
    w = word.lower()
    if w[:2].isdigit() or w[:1].isdigit():
        return int(re.match(r"\d+", w).group(0))
    return next((n for k, n in ORDINALS.items() if w.startswith(k)), 0)


def last_links(ctx: dict) -> list[str]:
    """Links of the newest answer that had any (a search result list, «вот ссылки: …»)."""
    try:
        hist = ctx["memory"].recent(ctx.get("session", ""), 12)
    except Exception:
        return []
    for m in reversed(hist):
        if m.get("role") != "assistant":
            continue
        urls = [u.rstrip(".,;:!?)»\"'*") for u in re.findall(r"https?://[^\s<>\]\[\"'»)]+", m.get("content") or "")]
        urls = list(dict.fromkeys(u for u in urls if len(u) > 10))
        if urls:
            return urls
    return []


async def browser_route(t: str, text: str, ctx: dict) -> dict | None:
    """The browser and the Renard window by plain words, without the model (it used to answer «не могу» / open old pages)."""
    from .tools.browser_tabs import site_host
    call = lambda **a: tools.call("browser", a, ctx)
    m = re.search(r"(?:открой|открыть|перейди|зайди|покажи|запусти)\s+(?:мне\s+)?(?:(?:по|на)\s+)?" + ORD_RX + r"\s+ссылк", t)
    if m:
        n, urls = _ord(m.group(1)), last_links(ctx)
        if not urls:
            return {"tool": "browser", "text": "В последних ответах нет ссылок. Скажи, что найти, — открою."}
        if n == -1:
            n = len(urls)
        if not 1 <= n <= len(urls):
            return {"tool": "browser", "text": f"Там всего {len(urls)} ссылк{'а' if len(urls) == 1 else 'и'}."}
        res = await call(action="open", url=urls[n - 1])
        return {"tool": "browser", "text": res, "speech": f"Открыл {n}-ю ссылку."}
    if re.search(r"\b(обнови\w*|перезагрузи\w*|рефрешни|odśwież)\s+(эту\s+|текущую\s+)?(страни[цч]|вкладк|сайт|stron)", t) \
            or re.fullmatch(LEAD + r"(нажми|жми|тыкни)\s+(на\s+)?(f5|ф5|эф ?пять)(\s+в\s+браузере)?", t):
        site = site_host(t)
        if site:
            found = await call(action="find_tab", keys=site)
            if not found.startswith(("Переключил", "Уже открыта")):
                return {"tool": "browser", "text": found}
        return {"tool": "browser", "text": await call(action="refresh")}
    m = re.search(r"(?:переключи\w*|перейди|открой|покажи|вернись|иди)\s+(?:мне\s+)?(?:на\s+|в\s+)?" + ORD_RX + r"\s+вкладк(\w*)(.*)", t)
    if m and not site_host(m.group(3)) and not re.search(r"закрыт", t):
        n = _ord(m.group(1))
        if n:
            return {"tool": "browser", "text": await call(action="tab", n=n)}
    m = re.search(r"(?:переключи\w*|перейди|вернись)\s+(?:вкладку\s+)?(?:в\s+браузере\s+)?(?:на|в)\s+(?:вкладку\s+)?(?:с\s+)?(.+)", t)
    if m and "вкладк" in t and site_host(m.group(1)):
        return {"tool": "browser", "text": await call(action="find_tab", keys=m.group(1))}
    if re.search(r"(следующ\w*|дальше на)\s+вкладк|вкладк\w*\s+(вперёд|вперед|вправо)", t):
        return {"tool": "browser", "text": await call(action="next_tab")}
    if re.search(r"(предыдущ\w*|прошл\w*)\s+вкладк|вкладк\w*\s+(назад|влево)", t):
        return {"tool": "browser", "text": await call(action="prev_tab")}
    if re.fullmatch(LEAD + r"(закрой|закрыть)\s+(эту\s+|текущую\s+|эту\s+текущую\s+)?вкладк\w*(\s+в\s+браузере)?", t):
        return {"tool": "browser", "text": await call(action="close_tab")}
    if re.fullmatch(LEAD + r"(открой|создай)\s+новую\s+вкладк\w*(\s+в\s+браузере)?", t):
        return {"tool": "browser", "text": await call(action="new_tab")}
    if re.fullmatch(LEAD + r"(вернись|вернуться|назад)\s+(назад\s+)?(на\s+)?(прошлую|предыдущую)?\s*страниц\w*(\s+в\s+браузере)?", t):
        return {"tool": "browser", "text": await call(action="back")}
    m = re.search(r"(?:нажм\w*|нажать|используй|использова\w*|сделай|зажми)\s.*?(?:в\s+браузере\s+)?(?:сочетани\w+\s+(?:клавиш\s+)?)?"
                  r"((?:ctrl|контрол|alt|альт|shift|шифт|win)(?:\s*(?:\+|плюс)\s*[\wа-я]+)+)", t)
    if m and re.search(r"браузер|вкладк|chrome|хром", t):
        keys = re.sub(r"\s*(\+|плюс)\s*", "+", m.group(1))
        keys = keys.replace("контрол", "ctrl").replace("альт", "alt").replace("шифт", "shift")
        return {"tool": "browser", "text": await call(action="keys", keys=keys)}
    if re.fullmatch(LEAD + r"(открой|запусти|включи|покажи|переключись на|перейди в|вернись в)\s+(мне\s+)?браузер\W*", t):
        return {"tool": "browser", "text": await call(action="open_browser")}
    m = re.search(r"(?:войди|войти|вход|залогин\w*|авториз\w*)\s+(?:мне\s+)?(?:в|на)\s+(?:аккаунт\s+)?(?:сайт\s+)?([\w.\-:/]+)", t)
    if m:
        return {"tool": "site_login", "text": await tools.call("site_login", {"site": m.group(1)}, ctx)}
    if re.search(r"(переключи\w*|открой|покажи|разверни|выведи|перейди)\s.*(renard|ренар)\b", t) \
            or re.search(r"(открой|покажи)\s+(наш\s+|свой\s+|этот\s+)?чат\b(?!\s+(в|с)\s)", t) \
            or re.fullmatch(LEAD + r"(выведи|покажи)\s+(это\s+|мне\s+)*(на\s+экран\w*|на\s+экране)\W*", t):
        return {"tool": "show_renard", "text": await tools.call("show_renard", {}, ctx)}
    return None


async def planner_route(t: str, text: str, ctx: dict) -> dict | None:
    """Tasks / notes / calendar / rates / the day by plain words (the model used to answer «запомнил» and keep nothing)."""
    call = lambda name, **a: tools.call(name, a, ctx)
    body = lambda m: text.strip()[m.end():].strip(" :,.—-") if m else ""
    low = text.strip().lower()
    if re.fullmatch(LEAD + r"(доброе утро|утренняя сводка|сводка на день|какие (у меня )?планы( на сегодня)?|что у меня (сегодня|на сегодня)|"
                    r"план на (сегодня|день)|что (сегодня|на сегодня) по планам)\W*", t):
        return {"tool": "day_plan", "text": await call("day_plan", day="today")}
    if re.fullmatch(LEAD + r"(какие (у меня )?планы на завтра|что у меня (на )?завтра|план на завтра)\W*", t):
        return {"tool": "day_plan", "text": await call("day_plan", day="tomorrow")}
    m = re.match(r"(?:(?:а|ну|и|теперь|ещё|еще)\s+)*(?:добавь|запиши|внеси|поставь)\s+(?:мне\s+)?(?:в\s+(?:список\s+)?(?:дел[ао]?|задач[иу]?|туду|to-?do)|"
                 r"задачу|дело)\s*[:,]?\s*", low)
    if m and body(m):
        return {"tool": "tasks", "text": await call("tasks", action="add", text=body(m))}
    if re.fullmatch(LEAD + r"(мои |список |какие у меня )?(дела|задачи|список дел|туду)( на (сегодня|неделю))?\W*", t) \
            or re.fullmatch(LEAD + r"что (мне )?(надо|нужно) сделать( сегодня)?\W*", t):
        scope = "today" if "сегодня" in t else "week" if "недел" in t else "open"
        return {"tool": "tasks", "text": await call("tasks", action="list", scope=scope)}
    m = re.match(r"(?:отметь|вычеркни)\s+(?:задачу\s+|дело\s+)?(.+?)\s+(?:как\s+)?(?:сделан\w*|выполнен\w*|готов\w*)\W*$", low) \
        or re.match(r"(?:вычеркни|закрой задачу|отметь задачу)\s+(.+?)\W*$", low)
    if m:
        return {"tool": "tasks", "text": await call("tasks", action="done", text=m.group(1))}
    m = re.match(r"я\s+(?:уже\s+)?(?:сделал|выполнил|закончил)\s+(?:задачу\s+)?(.+?)\W*$", low)
    if m:
        from . import planner
        open_tasks = planner.tasks("open")
        hit = planner._find(open_tasks, m.group(1))
        if hit and set(re.findall(r"\w{3,}", hit["text"].lower())) & set(re.findall(r"\w{3,}", m.group(1))):
            return {"tool": "tasks", "text": await call("tasks", action="done", text=hit["id"])}
    m = re.match(r"(?:(?:а|ну|и)\s+)?(?:запиши|сохрани|создай|сделай)\s+(?:мне\s+)?(?:в\s+)?заметк\w*\s*[:,]?\s*", low)
    if m and body(m):
        return {"tool": "notes", "text": await call("notes", action="add", text=body(m))}
    if re.fullmatch(LEAD + r"(мои |покажи |открой )?(заметки|мои заметки|все заметки)\W*", t):
        return {"tool": "notes", "text": await call("notes", action="list")}
    m = re.match(r"(?:найди|покажи|открой)\s+заметк\w*\s+(?:про|о|об|с)?\s*(.+)$", low)
    if m:
        return {"tool": "notes", "text": await call("notes", action="search", text=m.group(1))}
    m = re.match(r"(?:(?:а|ну|и)\s+)?(?:добавь|запиши|внеси|поставь)\s+(?:мне\s+)?в\s+календар\w*\s*[:,]?\s*", low)
    if m and body(m):
        return {"tool": "calendar", "text": await call("calendar", action="add", title=body(m))}
    if re.fullmatch(LEAD + r"(что (у меня )?в календаре|мой календарь|покажи календарь|события на неделю|"
                    r"какие (у меня )?(встречи|события)( на (неделю|сегодня|завтра))?)\W*", t):
        days = 1 if re.search(r"сегодня|завтра", t) else 7
        return {"tool": "calendar", "text": await call("calendar", action="list", days=days,
                                                       start="tomorrow" if "завтра" in t else "today")}
    cur = r"(доллар\w*|бакс\w*|евро|злот\w*|гривн\w*|гривен|фунт\w*|франк\w*|рубл\w*|крон\w*|йен\w*|иен\w*|юан\w*|лир\w*|usd|eur|pln|uah|gbp|chf)"
    m = re.fullmatch(LEAD + r"(?:какой\s+)?курс\s+" + cur + r"(?:\s+(?:к|в)\s+" + cur + r")?(?:\s+сегодня)?\W*", t)
    if m:
        return {"tool": "currency", "text": await call("currency", from_cur=m.group(1), to_cur=m.group(2) or "PLN", amount=1)}
    m = re.fullmatch(LEAD + r"(?:сколько\s+(?:будет\s+)?|переведи\s+)?(\d+(?:[.,]\d+)?)\s*" + cur + r"\s+(?:в|на)\s+" + cur + r"\W*", t)
    if m:
        return {"tool": "currency", "text": await call("currency", amount=float(m.group(1).replace(",", ".")),
                                                       from_cur=m.group(2), to_cur=m.group(3))}
    return None


async def _route_one(text: str, ctx: dict) -> dict | None:
    """The fast rules, in order: the first part that answers wins (each part was a block of this function)."""
    t = text.strip().lower().rstrip("!.?")
    for part in _ROUTE_PARTS:
        hit = await part(t, text, ctx)
        if hit:
            return hit
    return None


async def _rp00_user_node_commands(t: str, text: str, ctx: dict) -> dict | None:
    from .commands import match_phrase
    hit = match_phrase(text)
    runner = getattr(ctx.get("agent"), "command_runner", None)
    if hit and runner:
        import asyncio
        c, nid = hit
        from .commands import _nodes
        names = [n["name"] for n in _nodes(c).values()]
        learned = "renard_tool" in names and "wait" not in names
        task = asyncio.create_task(runner.run(c["id"], nid))
        done, _ = await asyncio.wait({task}, timeout=30 if learned else 4)
        log = task.result() if done else ["выполняется в фоне…"]
        if learned and done:
            body = "\n\n".join(x for x in log if x) or "готово"
            speech = log[-1] if len(log) == 1 else f"Готово: {c['name'].lower()}."
            return {"tool": "command", "text": f"Команда «{c['name']}»\n\n{body}", "speech": speech[:300]}
        return {"tool": "command", "text": f"Команда «{c['name']}»: " + "; ".join(log[-4:])}


async def _rp01_time_date_the(t: str, text: str, ctx: dict) -> dict | None:
    if re.fullmatch(r"(а\s+)?(сколько (сейчас )?времени|который (сейчас )?час|какое (сегодня )?число|какой сегодня день|"
                    r"какая (сегодня )?дата|która godzina|jaki (dziś|dzisiaj) dzień)\W*", t):
        import time as _t
        days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        lt = _t.localtime()
        return {"tool": "time", "text": f"Сейчас {lt.tm_hour}:{lt.tm_min:02d}, {days[lt.tm_wday]}, {lt.tm_mday} {months[lt.tm_mon - 1]}."}

    hit = await browser_route(t, text, ctx) or await planner_route(t, text, ctx)
    if hit:
        return hit
    from . import personas
    hit = await personas.route(text)
    if hit:
        return hit
    if "шахмат" in t:
        from . import chess_game
        hit = await chess_game.route(text, ctx.get("agent"))
        if hit:
            return hit


async def _rp02_what_the_just(t: str, text: str, ctx: dict) -> dict | None:
    learned = await save_session_route(text, ctx) or save_as_command(text, ctx)
    if learned:
        return learned


async def _rp03_link_alone_remember(t: str, text: str, ctx: dict) -> dict | None:
    if re.fullmatch(r"(https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be|open\.spotify\.com)/\S+)", text.strip()):
        return {"tool": "music", "text": await tools.call("music", {"action": "play", "query": text.strip()}, ctx)}
    if re.search(r"запомни\s+(это|эту|этот|её|ее|его)?\s*(как|это)?\s*(мою|мой|моя)\s+(музык|плейлист|подборк)|"
                 r"^(это|эта|вот)\s+моя\s+музык", t):
        url = re.search(r"https?://\S+", text)
        return {"tool": "music", "text": await tools.call("music", {"action": "save_favorite", "query": url.group(0) if url else ""}, ctx)}
    if re.fullmatch(r"(включи|вруби|поставь|запусти)\s+(мою|мой|мои)\s+(музык\w*|плейлист\w*|подборк\w*|песн\w*)(\s+(на|в)\s+\w+)?\W*", t):
        return {"tool": "music", "text": await tools.call("music", {"action": "play", "query": "моя музыка"}, ctx)}
    m = re.fullmatch(r"(?:включи|вруби|поставь|запусти)\s+(?:что-нибудь|что-то|чего-нибудь|какую-нибудь песню|песню|трек)\s+"
                     r"(?:из|от|у|группы|исполнителя)\s+([\w .,'&-]{2,40})", t)
    if m:
        return {"tool": "music", "text": await tools.call("music", {"action": "play", "query": m.group(1).strip()}, ctx)}
    m = re.fullmatch(r"(включи|вруби|поставь)\s+(радио\s+)?([\w .-]{2,25})", t)
    if m and find_station(m.group(3).strip()):
        return {"tool": "play_radio", "text": await tools.call("play_radio", {"station": m.group(3).strip()}, ctx)}


async def _rp04_memory_commands(t: str, text: str, ctx: dict) -> dict | None:
    mem = ctx["memory"]
    m = re.match(r"^(запомни|запиши в память)[:,]?\s+(?:(?:что|то что|, что)\s+)?(.+)$", text.strip(), re.I | re.S)
    if m:
        fact = m.group(2).strip()
        return {"tool": "remember", "text": mem.remember(fact[:1].upper() + fact[1:], session=ctx.get("session", ""))}
    m = re.match(r"^забудь[:,]?\s+(.+)$", text.strip(), re.I)
    if m:
        return {"tool": "forget", "text": mem.forget(m.group(1))}
    if re.search(r"(что ты (обо мне |про меня )?(помнишь|знаешь обо мне)|покажи (свою )?память)", t):
        facts = []
        for n, head in (("profile.md", "О тебе"), ("preferences.md", "Как ты хочешь, чтобы я работал"), ("notes.md", "Заметки")):
            lines = [re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", l[2:]).strip() for l in mem.read_note(n).splitlines() if l.startswith("- ")]
            if lines:
                facts.append(f"{head}:\n" + "\n".join(f"• {l}" for l in lines[-15:]))
        if not facts:
            return {"tool": "memory", "text": "Пока почти ничего не помню. Скажи «запомни, что …» — и запомню."}
        return {"tool": "memory", "text": "Вот что я помню:\n\n" + "\n\n".join(facts) + "\n\nЧто-то неверно — скажи «забудь …»."}


async def _rp05_radio_stop(t: str, text: str, ctx: dict) -> dict | None:
    if re.search(r"(выключи|останови|стоп|вырубай|выруби)\s*(радио|музыку радио)|^стоп радио", t):
        return {"tool": "stop_radio", "text": await tools.call("stop_radio", {}, ctx)}


async def _rp06_skills(t: str, text: str, ctx: dict) -> dict | None:
    if re.search(r"(какие|покажи|список) (у тебя )?(навык|скилл)", t):
        return {"tool": "skills_list", "text": await tools.call("skills_list", {}, ctx)}
    m = re.match(r"^(установи|поставь|добавь) (навык|скилл)\s+((?:hermes|openclaw|github):\S+)$", t)
    if m:
        spec = m.group(3)
        return {"tool": "skill_install", "pending": {"name": "skill_install", "args": {"spec": spec}},
                "text": f"Установить навык {spec}? Будет скачан с GitHub. Ответь «да» или «нет»."}


async def _rp07_load_history(t: str, text: str, ctx: dict) -> dict | None:
    multi = compound(t, r"(?!x)x")
    if not multi and re.search(r"(как|насколько) (был\w* )?(нагруж|загруж)\w* (пк|комп|система)|история нагрузки", t):
        return {"tool": "load_history", "text": await tools.call("load_history", {}, ctx)}


async def _rp08_processes(t: str, text: str, ctx: dict) -> dict | None:
    multi = compound(t, r"(?!x)x")
    if not multi and re.search(r"(что|какие процессы|какой процесс) (грузит|нагружает|жр[её]т) (процессор|цп|cpu|комп|пк)", t):
        return {"tool": "top_processes", "text": await tools.call("top_processes", {"sort": "cpu"}, ctx)}
    if not multi and re.search(r"(что|какие процессы|какой процесс) (жр[её]т|занимает|ест) (память|оперативк|озу|ram)", t):
        return {"tool": "top_processes", "text": await tools.call("top_processes", {"sort": "ram"}, ctx)}
    m = re.match(r"^(убей|заверши|заверш\w* процесс|убей процесс|kill)\s+(?:процесс\s+)?([\w.\-]+\.exe)$", t)
    if m:
        name = m.group(2)
        return {"tool": "kill_process", "pending": {"name": "kill_process", "args": {"name": name}},
                "text": f"Завершить процесс {name}? Ответь «да» или «нет»."}
    if re.search(r"(почисти|очисти|удали) (временные файлы|temp|темп)", t):
        return {"tool": "clean_temp", "pending": {"name": "clean_temp", "args": {"days": 2}},
                "text": "Отправить в корзину временные файлы старше 2 дней из %TEMP%? Ответь «да» или «нет»."}

    from .core import explicit_lang
    asked_lang = explicit_lang(t)
    m = re.fullmatch(r"(?:а\s+)?(?:(?:скажи|подскажи)\s+)?(?:сколько\s+(?:сейчас\s+|щас\s+)?(?:времени|время)|который\s+(?:сейчас\s+|щас\s+)?час|"
                     r"какое\s+(?:сейчас\s+|щас\s+)?время|która\s+(?:jest\s+)?(?:teraz\s+)?godzina|what\s+time\s+is\s+it)"
                     r"\s+(?:сейчас\s+|щас\s+|teraz\s+)?(?:в|во|w|we|in)\s+([\w .'-]{2,40}?)(?:\s+сейчас|\s+щас|\s+teraz|\s+now)?\W*", t)
    if m and not asked_lang:
        return {"tool": "world_time", "text": await tools.call("world_time", {"place": m.group(1).strip()}, ctx)}


async def _rp09_otw_pobrane_the(t: str, text: str, ctx: dict) -> dict | None:
    m = re.fullmatch(r"(?:открой|открывай|зайди в|перейди в|otw[oó]rz|(?:покажи|poka[zż])(?=\s+(?:мне\s+)?(?:папку|folder|katalog)))"
                     r"\s+(?:мне\s+)?(?:папку\s+|folder\s+|katalog\s+)?"
                     r"(загрузки|загрузок|скачанное|скачанные|документы|мои документы|рабоч\w+ стол|картинки|изображения|фото|"
                     r"музыку|музыка|видео|pobrane|dokumenty|pulpit|obrazy|muzyk\w*|wideo|downloads|documents|desktop|pictures|music|videos)"
                     r"(?:\s+папку)?\W*", t)
    if m and not (m.group(1) in ("музыку", "музыка", "видео", "фото", "muzyka", "muzykę", "wideo")
                  and not re.search(r"папк|folder|katalog", t)):
        return {"tool": "open_folder", "text": await tools.call("open_folder", {"name": m.group(1)}, ctx)}


async def _rp10(t: str, text: str, ctx: dict) -> dict | None:
    if re.search(r"(закрыт\w*|прошл\w*|последн\w*)\s+вкладк|вкладк\w*\s+(котор\w+\s+)?(я\s+)?закрыл|(верни|восстанови|открой\s+снова)\s+вкладк|"
                 r"ostatni\w*\s+(zamkni[eę]t\w*\s+)?kart|przywr[oó][cć]\s+kart", t) and len(t) < 120:
        site = re.search(r"вкладк\w*\s+(?:с\s+|на\s+|из\s+)?([\w.-]+)|kart\w*\s+(?:z\s+)?([\w.-]+)", t)
        word = next((g for g in (site.groups() if site else ()) if g), "")
        from .tools.browser_tabs import site_host
        word = word if site_host(word) else ("" if not site_host(t) else t)
        return {"tool": "reopen_tab", "text": await tools.call("reopen_tab", {"site": word}, ctx)}


async def _rp11_telegram(t: str, text: str, ctx: dict) -> dict | None:
    raw = text.strip().rstrip("!.")
    TG = r"(?:в\s+)?(?:телеграм\w*|телеге|тг|telegram\w*|телеграмм\w*)"
    m = re.match(r"(?i)^(?:ренар,?\s+)?(?:напиши|отправь|скажи|ответь)\s+" + TG + r"\s+([^\s,:]+(?:\s+(?-i:[A-ZА-ЯЁ])[^\s,:]*)?)[\s,:]+(.+)$", raw) \
        or re.match(r"(?i)^(?:ренар,?\s+)?(?:напиши|отправь|скажи|ответь)\s+([^\s,:]+(?:\s+(?-i:[A-ZА-ЯЁ])[^\s,:]*)?)\s+" + TG + r"[\s,:]+(.+)$", raw)
    if m:
        chat, msg = m.group(1).strip(), m.group(2).strip().strip("«»\"'")
        reply = raw.lower().startswith(("ответь", "ренар, ответь", "ренар ответь"))
        if msg and not re.match(r"(?i)(что|чтобы|что-нибудь|какое-нибудь|сообщение о|ему о|ей о)\b", msg):
            args = {"chat": chat, "text": msg, "reply": reply}
            return {"tool": "telegram_send", "pending": {"name": "telegram_send", "args": args},
                    "text": f"{'Ответить' if reply else 'Отправить'} в Telegram → {chat}: «{msg}»? Ответь «да» или «нет»."}
    m = re.match(r"(?i)^(?:а\s+)?(?:что|чё|че)\s+(?:мне\s+)?(?:пишет|написал\w*|пишут|ответил\w*|прислал\w*)\s+(.+?)(?:\s+" + TG + r")?\??$", raw) \
        or re.match(r"(?i)^(?:прочитай|покажи|открой)\s+(?:чат|переписку|сообщения)\s+(?:с|от)\s+(.+?)(?:\s+" + TG + r")?$", raw)
    if m and (re.search(TG, raw, re.I) or re.search(r"(?i)написал|ответил|прислал", raw)) and len(m.group(1)) < 40 \
            and not re.search(r"(?i)дискорд|discord|почт|mail|сайт", raw):
        return {"tool": "telegram", "text": await tools.call("telegram", {"action": "read", "chat": m.group(1).strip(), "n": 15}, ctx)}
    if re.fullmatch(r"(?:кто|что)\s+(?:мне\s+)?(?:написал\w*|пишет)(?:\s+" + TG + r")?|непрочитанн\w*(?:\s+" + TG + r")?|"
                    r"есть (?:ли )?(?:новые )?сообщения(?:\s+" + TG + r")?", t):
        return {"tool": "telegram", "text": await tools.call("telegram", {"action": "unread"}, ctx)}


async def _rp12_discord_dorskyy_dorskyy(t: str, text: str, ctx: dict) -> dict | None:
    raw = text.strip().rstrip("!.")
    DC = r"(?:в\s+)?(?:дискорд\w*|discord\w*|дс)"
    m = re.match(r"(?i)^(?:ренар,?\s+)?(?:напиши|отправь|скажи)\s+" + DC + r"\s+(\S+)[\s,:]+(.+)$", raw) \
        or re.match(r"(?i)^(?:ренар,?\s+)?(?:напиши|отправь|скажи)\s+(\S+)\s+" + DC + r"[\s,:]+(.+)$", raw)
    if m:
        target, msg = m.group(1).strip(), m.group(2).strip().strip("«»\"'")
        if msg and not re.match(r"(?i)(что|чтобы|что-нибудь|какое-нибудь)\b", msg):
            return {"tool": "discord_send", "pending": {"name": "discord_send", "args": {"target": target, "text": msg}},
                    "text": f"Отправить в Discord → {target}: «{msg}»? Ответь «да» или «нет»."}
    m = re.match(r"(?i)^(?:а\s+)?(?:что|чё|че)\s+(?:мне\s+)?(?:пишет|написал\w*|пишут|ответил\w*)\s+(.*?)\s*" + DC + r"\??$", raw) \
        or re.match(r"(?i)^(?:прочитай|покажи|открой)\s+(?:чат|переписку|сообщения|личку)?\s*(?:с|от)?\s*(.*?)\s*" + DC + r"$", raw) \
        or re.match(r"(?i)^(?:прочитай|покажи)\s+" + DC + r"\s*(.*)$", raw)
    if m and len(m.group(1)) < 40:
        return {"tool": "discord", "text": await tools.call("discord", {"target": m.group(1).strip(), "n": 15}, ctx)}


async def _rp13_steam(t: str, text: str, ctx: dict) -> dict | None:
    ST = r"(?:в\s+)?(?:стиме|стим|steam\w*)"
    if re.search(r"(?i)во что я (?:недавно |последнее время )?играл|последние игры|недавние игры", t):
        return {"tool": "steam", "text": await tools.call("steam", {"action": "recent", "n": 8}, ctx)}
    if re.search(r"(?i)(?:мои|какие у меня|сколько у меня)\s+игр\w*\s+" + ST + r"|библиотек\w*\s+" + ST + r"|сколько (?:часов )?я (?:наиграл|играл)", t):
        return {"tool": "steam", "text": await tools.call("steam", {"action": "library", "n": 15}, ctx)}
    if re.search(r"(?i)(?:что|чё)\s+(?:качается|обновляется|скачивается)\s+" + ST + r"|загрузки\s+" + ST, t):
        return {"tool": "steam", "text": await tools.call("steam", {"action": "downloads"}, ctx)}
    m = re.search(r"(?i)(?:сколько стоит|цена|почём)\s+(.+?)\s+" + ST + r"\??$", t) or re.search(r"(?i)(?:найди|поищи)\s+" + ST + r"\s+(.+)$", t)
    if m:
        act = "info" if re.search(r"(?i)стоит|цена|почём", t) else "search"
        return {"tool": "steam", "text": await tools.call("steam", {"action": act, "query": m.group(1).strip()}, ctx)}
    m = re.search(r"(?i)следи\s+за\s+(?:скидк\w+|цен\w+)\s+(?:на\s+)?(.+?)(?:\s+" + ST + r")?$", t)
    if m:
        return {"tool": "steam", "text": await tools.call("steam", {"action": "watch", "game": m.group(1).strip()}, ctx)}
    if re.search(r"(?i)(?:что|какие)\s+(?:там\s+)?(?:со\s+)?скидк\w*\s+" + ST + r"|скидки\s+" + ST
                 + r"|скидк\w*\s+(?:на\s+)?(?:игр\w*\s+)?(?:которые|что)\s+я\s+хочу|скидк\w*\s+(?:в|из|на)\s+(?:мо\w+\s+)?желаем\w*"
                 + r"|(?:в|из)\s+(?:мо\w+\s+)?(?:желаемо\w*|списк\w+ желаемого|вишлист\w*).{0,30}скидк|^(?:а\s+)?(?:те\s+)?(?:которые|что)\s+в\s+желаемом\??$", t):
        return {"tool": "steam", "text": await tools.call("steam", {"action": "deals"}, ctx)}
    if re.search(r"(?i)(?:мо[йеё]\w*\s+)?(?:список\s+желаемого|желаемое|вишлист)\s*(?:" + ST + r")?\s*\??$|что у меня в (?:списке )?желаемо\w*", t):
        return {"tool": "steam", "text": await tools.call("steam", {"action": "wishlist"}, ctx)}


async def _rp14_only_question(t: str, text: str, ctx: dict) -> dict | None:
    m = re.search(r"(?i)^(?:(?:какое|какие|покажи|скажи|что)\s+)?(?:у меня\s+)?(?:мо[ёе]\s+|мои\s+)?(?:расписани\w*|уроки|plan lekcji)"
                  r"\s+(?:на\s+)?(эт\w+\s+|следующ\w+\s+|на следующ\w+\s+)?(?:недел\w*|tydzie\w*)\??$", t)
    if m:
        return {"tool": "school", "text": await tools.call("school", {"action": "week", "day": "следующая" if m.group(1) and "след" in m.group(1) else ""}, ctx)}


async def _rp15_school_zast_pstwa(t: str, text: str, ctx: dict) -> dict | None:
    from .core import explicit_lang
    asked_lang = explicit_lang(t)
    if not asked_lang and len(t) < 90:
        dayw = re.search(r"сегодня|послезавтра|завтра|dzi[sś]\w*|pojutrze|jutro|понедельник|вторник|сред[ау]|четверг|пятниц[ау]|"
                         r"суббот[ау]|poniedzia\w+|wtorek|[sś]rod[aęy]|czwartek|pi[aą]tek|\d{1,2}\.\d{1,2}", t)
        day = dayw.group(0) if dayw else ""
        if re.search(r"справдз\w*|sprawdzian\w*|kartk[oó]wk\w*|картк\w*|контрольн\w*|praca klasowa|prac[ey] klasow", t) \
                and re.search(r"когда|какие|есть ли|будут|будет|скоро|список|покажи|kiedy|jakie|czy (mam|są|jest)|на (этой|следующей) неделе|у меня", t):
            return {"tool": "school", "text": await tools.call("school", {"action": "exams"}, ctx)}
        if re.search(r"домашк\w*|домашн\w* (задани|работ)\w*|что (нам |мне )?задали|zadani\w* domow\w*|prac[ae] domow\w*|co (mamy |mam )?zadane", t):
            return {"tool": "school", "text": await tools.call("school", {"action": "homework"}, ctx)}
        m = re.search(r"(?:мои |какие |покажи |какая |у меня )?(?:оценк\w*|средн\w+ (?:оценк\w*|балл)|oceny|ocen\w*|średni\w*)(?:\s+(?:по|z|из)\s+([\w.\- ]{3,40}))?", t)
        if m and re.search(r"оценк|ocen|średn|средн", t) and re.search(r"мо[иия]|как\w+|у меня|средн|moje|jakie|mam|średni|последн|нов\w+|"
                                                                     r"(по|z|из) \w+|в дневник|w dzienniku", t) \
                and not re.search(r"оцени\b|оценка (стоимост|риск|качеств)|ocen(ić|iaj)\b", t):
            subj = (m.group(1) or "").strip()
            subj = {"математике": "matematyka", "математика": "matematyka", "физике": "fizyka", "истории": "historia",
                    "польскому": "polski", "немецкому": "niemiecki", "английскому": "angielski", "информатике": "informatyka",
                    "географии": "geografia", "базам данных": "baz danych"}.get(subj, subj)
            return {"tool": "school", "text": await tools.call("school", {"action": "grades", "subject": subj}, ctx)}
        if re.search(r"пропуск\w*|посещаемост\w*|опоздани\w*|frekwencj\w*|nieobecno\w*|sp[oó][zź]nie\w*", t) and len(t) < 60:
            return {"tool": "school", "text": await tools.call("school", {"action": "attendance"}, ctx)}
        if re.search(r"\bзамен\w*|zast[eę]pstw\w*", t) and not re.search(r"замени|заменить|файл|слово|текст", t):
            return {"tool": "school", "text": await tools.call("school", {"action": "substitutions", "day": day}, ctx)}
        if re.search(r"(какие|что|сколько|покажи|скажи|что за)\s+(у меня\s+)?(\w+\s+)?(уроки|урок\w*|пары)\b|план уроков|расписание уроков|"
                     r"мо[её] расписание|plan lekcji|jakie (mam )?lekcje|lekcje (na|w)", t):
            return {"tool": "school", "text": await tools.call("school", {"action": "timetable", "day": day or "сегодня"}, ctx)}


async def _rp16_weather_open_meteo(t: str, text: str, ctx: dict) -> dict | None:
    from .core import explicit_lang
    asked_lang = explicit_lang(t)
    schedule_words = re.search(r"\b(кажд|ежедневн|по будням|напомин|напомни|присылай|расписани|в \d+ утра)", t)
    writing = re.search(r"\b(напиши|сочини|придумай|переведи|по-(польски|английски|украински|немецки)|стих|предложени|текст|эссе|сочинени)", t)
    also_time = re.search(r"сколько\s+(\w+\s+)?времени|который\s+(\w+\s+)?час|godzin|what time", t)
    if not schedule_words and not writing and not asked_lang and not also_time and not compound(t, WEATHER_RX) \
            and re.search(WEATHER_RX, t):
        m = re.search(r"\bв\s+([A-Za-zА-Яа-яЁё\- ]{3,30}?)(?:\s+на\s+|\s+завтра|\s+сегодня|\?|$)", t)
        city = m.group(1).strip() if m and not re.match(r"(городе|моём|моем|нашем)", m.group(1)) else ""
        days = 7 if "недел" in t else 3
        text = await tools.call("weather", {"city": city, "days": days}, ctx)
        return {"tool": "weather", "text": text, "speech": weather_speech(text, t)}


async def _rp17_news_subscriptions_streams(t: str, text: str, ctx: dict) -> dict | None:
    nt = re.sub(r"^(ренар|renard|ну|а|так)[, ]+", "", t).strip()
    if re.fullmatch(r"(что|чё|че) (там )?(по|с) новостям\w*|(какие|что за|главные|свежие) новости\w*( сегодня| в мире| за день)?|"
                    r"новости|что (нового|происходит|случилось) в мире|что нового( сегодня)?|сводка( новостей)?|дайджест|"
                    r"(какой|что за) (сейчас )?хайп\w*( в мире)?|расскажи новости", nt):
        return {"tool": "news", "text": await tools.call("news", {"action": "digest"}, ctx)}
    if re.search(r"(что|чё|че) (нового|вышло|нового вышло|новенького)\s+(на ютубе|в ютубе|на youtube|из (моих )?подписок|в (моих )?подписках|у (моих )?ютуберов)|"
                 r"новые видео (на ютубе|из подписок|в подписках|у ютуберов)", nt):
        ch = re.search(r"\bу ([\w@ .-]{2,30})$", nt)
        return {"tool": "news", "text": await tools.call("news", {"action": "youtube", "query": ch.group(1) if ch else ""}, ctx)}
    m = re.search(r"(?:ид[её]т|идет|есть|начался|запустил)\s+(?:ли\s+)?(?:сейчас\s+|щас\s+)?стрим\w*\s+у\s+([\w@ .-]{2,30})|"
                  r"(?:кто|кто-нибудь)\s+(?:сейчас\s+|щас\s+)?(?:стримит|в эфире)", nt)
    if m:
        who = (m.group(1) or "").strip()
        return {"tool": "news", "text": await tools.call("news", {"action": "twitch", "query": who}, ctx)}
    m = re.fullmatch(r"(?:добавь|подпиши меня на|следи за)\s+(?:канал|ютубера|ютуб[- ]канал)\s+(.+)", nt)
    if m:
        return {"tool": "news", "text": await tools.call("news", {"action": "add_channel", "query": m.group(1)}, ctx)}
    m = re.fullmatch(r"(?:добавь|следи за)\s+(?:стримера|стримы|твич)\s+(.+)", nt)
    if m:
        return {"tool": "news", "text": await tools.call("news", {"action": "add_streamer", "query": m.group(1)}, ctx)}
    if re.fullmatch(r"(импортируй|загрузи|подтяни)( мои)? подписки( с ютуба| из ютуба| из takeout)?", nt):
        return {"tool": "news", "text": await tools.call("news", {"action": "import"}, ctx)}


async def _rp18_recent_documents_slideshow(t: str, text: str, ctx: dict) -> dict | None:
    nt = re.sub(r"^(ренар|renard|ну|а|так)[, ]+", "", t).strip()
    m = re.fullmatch(r"(?:найди|где|покажи|открой)\s+(?:мою\s+|мой\s+|мои\s+)?(?:последн\w+\s+|недавн\w+\s+|свеж\w+\s+)?"
                     r"(презентаци\w+|документ\w*|реферат\w*|доклад\w*|таблиц\w+|видео|фотк\w+|фото)"
                     r"(?:\s+которую|\s+который|\s+что)?(?:\s+я)?(?:\s+(?:делал|сделал|недавно|вчера|скачал|сохранил)\w*)*", nt)
    if m:
        from .tools.docs import kind_of
        res = await tools.call("recent_files", {"kind": kind_of(m.group(1)), "days": 60}, ctx)
        if nt.startswith("открой"):
            first = re.search(r"\d{2}\.\d{2} \d{2}:\d{2}\s+(.+)", res)
            if first:
                return {"tool": "open_file", "text": await tools.call("open_file", {"path": first.group(1).strip()}, ctx)}
        return {"tool": "recent_files", "text": res}
    m = re.fullmatch(r"(?:запусти|включи|начни|покажи)\s+(?:показ|демонстрацию|слайд-?шоу|просмотр)(?:\s+презентации)?|"
                     r"(?:запусти|включи)\s+презентацию(?:\s+(?:для|на)\s+(?:просмотр\w*|показ\w*))|"
                     r"(следующий|предыдущий) слайд|(закрой|выйди из|останови) (показ|слайд-?шоу)", nt)
    if m:
        act = "next" if "следующ" in nt else "prev" if "предыдущ" in nt else "end" if re.search(r"закрой|выйди|останови", nt) else "start"
        return {"tool": "presentation", "text": await tools.call("presentation", {"action": act}, ctx)}
    if re.fullmatch(r"(включи |поставь |давай )?(следующ\w+|другое|другую) (видео|ролик|песню|трек)|переключи (видео|трек|песню)|"
                    r"(перейди|переключи|переключись|давай) (к|на) следующ\w+( (видео|ролик\w*|песн\w+|трек\w*))?|"
                    r"дальше|следующее|скипни|некст|пропусти (это|эту|этот)?( ?(видео|песню|трек))?", nt):
        return {"tool": "music", "text": await tools.call("music", {"action": "next"}, ctx)}
    if re.fullmatch(r"(включи |поставь |верни )?(предыдущ\w+) (видео|ролик|песню|трек)|(перейди|вернись|давай) (к|на) "
                    r"предыдущ\w+( (видео|ролик\w*|песн\w+|трек\w*))?|назад к прошлому (видео|треку)", nt):
        return {"tool": "music", "text": await tools.call("music", {"action": "prev"}, ctx)}
    ns = numsys(nt)
    if ns:
        return {"tool": "calc", "text": ns}


async def _rp19_windows(t: str, text: str, ctx: dict) -> dict | None:
    if re.search(r"сверн\w*\s+(все|всё)(\s+окна)?|покажи рабочий стол", t):
        return {"tool": "windows", "text": await tools.call("windows", {"action": "minimize_all"}, ctx)}
    if re.search(r"(верни|разверни)\w*\s+(все\s+)?окна", t):
        return {"tool": "windows", "text": await tools.call("windows", {"action": "restore_all"}, ctx)}


async def _rp20_hydra_steam_the(t: str, text: str, ctx: dict) -> dict | None:
    m = re.search(r"(какие|какая|список|покажи|сколько)\b.{0,30}\b(игр\w*|gier|gry|games)\b.{0,40}?"
                  r"(hydra|гидр\w*|steam|стим\w*|epic|эпик\w*|папк\w* games|установлен\w*|есть)", t)
    if m and not re.search(r"скидк|желаем|цен|купи|стоит|сколько час|наиграл|время|обнов|скача|загруз", t):
        cat = "hydra" if re.search(r"hydra|гидр", t) else "steam" if re.search(r"steam|стим", t) else \
            "epic" if re.search(r"epic|эпик", t) else "folder" if re.search(r"папк\w* games", t) else "игры"
        return {"tool": "apps_overview", "text": await tools.call("apps_overview", {"category": cat}, ctx)}


async def _rp21_avatar_body_desktop(t: str, text: str, ctx: dict) -> dict | None:
    tt = re.sub(r"^(renard|некс(ус)?|эй)[, ]+|[, ]+(пожалуйста|плиз)$", "", t).strip()
    tt = re.sub(r"^((можешь|можеш|можно|давай|попробуй|а|ну|теперь|ещё|еще|и|ты)[, ]+)+", "", tt).strip()
    tt = re.sub(r"^(\w+)", lambda m: INF2IMP.get(m.group(1), m.group(1)), tt)
    for rx, act, reply in AVATAR_RULES:
        if re.fullmatch(rx, tt):
            args = {k: (tt if v == "{text}" else v) for k, v in act.items()} if isinstance(act, dict) else {"action": act}
            res = await tools.call("avatar", args, ctx)
            ok = res.startswith("Аватар:") and not re.search(r"ничего не изменилось|нет анимации|пуста", res)
            return {"tool": "avatar", "text": reply if ok else res}


async def _rp22_windows_apps_volume(t: str, text: str, ctx: dict) -> dict | None:
    r = await _route_apps(t, ctx)
    if r:
        return r


async def _rp23_music_youtube_spotify(t: str, text: str, ctx: dict) -> dict | None:
    m = re.match(r"^(?:включи|поставь|вруби|запусти|играй|сыграй|найди и включи)\s+(?:мне\s+)?(?:какую-нибудь\s+|какую нибудь\s+)?"
                 r"(музыку|песню|песни|трек|альбом|плейлист)\b\s*(.*)$", t)
    if m:
        q = m.group(2).strip()
        svc = "spotify" if re.search(r"спотиф|spotify", q) else "yandex" if re.search(r"яндекс", q) else "youtube" if re.search(r"ютуб|youtube", q) else ""
        q = re.sub(r"\s*(на|в|из)\s+(ютубе?|youtube|спотифа[йе]?|spotify|яндекс[- ]?музык[еи])\b", "", q).strip(" ,.")
        if m.group(1) in ("песни", "музыку") and q.startswith(("от ", "группы ")):
            q = q.split(" ", 1)[1]
        return {"tool": "music", "text": await tools.call("music", {"action": "play", "query": q, "service": svc}, ctx)}
    m = re.match(r"^(?:я\s+)?(?:хочу|хотел бы|хотела бы|давай|можно)\s+(?:бы\s+)?(?:послушать|послушаем|включить)\s+(.+)$", t)
    if m and not compound(t, r"послуша|включить"):
        q = re.sub(r"\b(лофай|лофи|лоу-?фай)\b", "lofi", m.group(1).strip(" ,.!?"))
        q = "" if q in ("музыку", "музыка", "что-нибудь", "что нибудь", "музыку какую-нибудь") else re.sub(r"^(музыку|песню|трек)\s+", "", q)
        if not re.search(r"\b(радио|подкаст)\b", q):
            return {"tool": "music", "text": await tools.call("music", {"action": "play", "query": q}, ctx)}
    if re.search(r"что (сейчас )?(играет|за песня|за трек)|какая (сейчас )?(песня|музыка) играет", t):
        return {"tool": "music", "text": await tools.call("music", {"action": "now"}, ctx)}
    if re.match(r"^(продолжи|возобнови|верни)\s*(музыку|воспроизведение|песню)?$", t):
        return {"tool": "music", "text": await tools.call("music", {"action": "resume"}, ctx)}
    if re.match(r"^(останови|выключи|поставь на паузу)\s+(музыку|песню|трек)$", t):
        return {"tool": "music", "text": await tools.call("music", {"action": "pause"}, ctx)}


async def _rp24_radio(t: str, text: str, ctx: dict) -> dict | None:
    m = re.search(r"(включи|вруби|поставь)\s+радио\s*(.*)", t)
    if m:
        st = m.group(2).strip() or "record"
        if find_station(st):
            return {"tool": "play_radio", "text": await tools.call("play_radio", {"station": st}, ctx)}


async def _rp25_apps(t: str, text: str, ctx: dict) -> dict | None:
    m = re.match(r"^(?:ну\s+|давай\s+)?(открой|открывай|запусти|запускай|включи|включай|вруби|otwórz|uruchom|włącz)\s+(?:мне\s+)?(.+?)(?:\s+уже)?$", t)
    if m and find_app(m.group(2)):
        return {"tool": "open_app", "text": await tools.call("open_app", {"name": m.group(2)}, ctx)}
    PC = r"(пк|комп\w*|ноут\w*|систему|komputer\w*|pc)"
    if len(t) < 45 and re.search(r"(отмени|отменить|стоп|не надо|не)\s+(выключ|перезагруз)\w*|anuluj wyłącz", t):
        return {"tool": "power_cancel", "text": await tools.call("power_cancel", {}, ctx)}
    if re.fullmatch(r"(заблокируй|заблочь|блокни|zablokuj)\s+(экран|" + PC[1:-1] + r")\W*", t):
        return {"tool": "lock_pc", "text": await tools.call("lock_pc", {}, ctx)}
    m = re.fullmatch(r"(выключи|выруби|отключи|перезагрузи|ребутни|усыпи|wyłącz|uruchom ponownie|zrestartuj)\s+" + PC +
                     r"(?:\s+через\s+(\d+)\s*(мин\w*|час\w*|ч)?)?(?:\s+в\s+(сон|спящий режим))?\W*", t)
    if m:
        verb = m.group(1)
        act = "restart" if verb in ("перезагрузи", "ребутни", "uruchom ponownie", "zrestartuj") else \
              "sleep" if (verb == "усыпи" or m.group(5)) else "shutdown"
        delay = int(m.group(3) or 0) * (60 if (m.group(4) or "").startswith("ч") else 1)
        what = {"shutdown": "Выключить компьютер", "restart": "Перезагрузить компьютер", "sleep": "Отправить компьютер в сон"}[act]
        return {"tool": "power", "pending": {"name": "power", "args": {"action": act, "delay_min": delay}},
                "text": f"{what}{f' через {delay} мин' if delay else ''}? Несохранённая работа пропадёт. Ответь «да» или «нет»."}
    if re.fullmatch(r"(отправь|переведи)\s+" + PC + r"\s+в\s+(сон|спящий режим)\W*|спящий режим\W*", t):
        return {"tool": "power", "pending": {"name": "power", "args": {"action": "sleep"}},
                "text": "Отправить компьютер в сон? Ответь «да» или «нет»."}

    m = re.match(r"^(закрой|выключи|вырубай|убей)\s+(.+)$", t)
    if m and find_app(m.group(2)):
        return {"tool": "close_app", "text": await tools.call("close_app", {"name": m.group(2)}, ctx)}


async def _rp26_media_keys(t: str, text: str, ctx: dict) -> dict | None:
    if len(t) < 40:
        for pat, action in MEDIA:
            if re.search(pat, t):
                if action == "resume" and re.fullmatch(r"продолж\w*|возобнови", t):
                    from .media_now import now_playing
                    m = await now_playing()
                    if not (m.get("title") and not m.get("playing")):
                        break
                if action in ("next", "prev", "resume", "pause"):
                    return {"tool": "music", "text": await tools.call("music", {"action": action}, ctx)}
                return {"tool": "media_control", "text": await tools.call("media_control", {"action": action}, ctx)}


async def _rp27_state(t: str, text: str, ctx: dict) -> dict | None:
    if re.search(r"(загрузк\w* (пк|компа|cpu|процессора|видеокарт\w*|gpu)|температур\w* (видеокарт|gpu|пк)|"
                 r"сколько (свободного )?места|место на диск|(все|мои|какие) диски|состояние (пк|компа|системы)|сколько (оперативки|ram|памяти) )", t):
        from .tools.pc import pc_stats
        return {"tool": "pc_stats", "text": fmt_stats(pc_stats())}


async def _rp28_files_stage_only(t: str, text: str, ctx: dict) -> dict | None:
    pm = PATH_RE.search(text)
    if pm:
        path = existing_prefix(pm.group(1))
    if pm and path:
        if re.search(r"(сам\w* (больш|крупн|тяж)\w*|крупн\w*) файл", t):
            return {"tool": "largest_files", "text": await tools.call("largest_files", {"folder": path}, ctx)}
        if re.match(r"^(открой|запусти)\s+(папку|файл|документ)?\s*[a-z]:\\", t):
            return {"tool": "open_file", "text": await tools.call("open_file", {"path": path}, ctx)}
        ext = re.search(r"(?:все\s+)?\.(\w{1,6})\s+файл|файл\w*\s+\.(\w{1,6})\b|файл\w*\s+с\s+расширением\s+\.?(\w{1,6})", t)
        if ext and re.search(r"(найди|покажи|список|перечисли|какие)", t):
            e = next(g for g in ext.groups() if g)
            return {"tool": "search_files", "text": await tools.call("search_files", {"folder": path, "name": f"*.{e}"}, ctx)}
        if re.search(r"(пришли|отправь|скинь|перешли)\b.*(мне|телеграм|тг|telegram)", t) and os.path.isfile(path):
            return {"tool": "send_file", "text": await tools.call("send_file", {"path": path}, ctx)}
        if re.search(r"(покажи|найди) .*в проводнике|открой в проводнике", t):
            return {"tool": "show_in_explorer", "text": await tools.call("show_in_explorer", {"path": path}, ctx)}


async def _rp29_defender_junk(t: str, text: str, ctx: dict) -> dict | None:
    if re.search(r"(статус|состояние) (защитника|defender|антивируса)", t):
        return {"tool": "defender_status", "text": await tools.call("defender_status", {}, ctx)}
    if re.search(r"проверь (комп|пк|компьютер)?\s*на вирус", t):
        return {"tool": "defender_scan", "text": await tools.call("defender_scan", {}, ctx)}
    if re.search(r"(сколько мусора|отчёт о мусоре|где мусор)", t):
        return {"tool": "junk_report", "text": await tools.call("junk_report", {}, ctx)}


_ROUTE_PARTS = (_rp00_user_node_commands, _rp01_time_date_the, _rp02_what_the_just, _rp03_link_alone_remember, _rp04_memory_commands, _rp05_radio_stop, _rp06_skills, _rp07_load_history, _rp08_processes, _rp09_otw_pobrane_the, _rp10, _rp11_telegram, _rp12_discord_dorskyy_dorskyy, _rp13_steam, _rp14_only_question, _rp15_school_zast_pstwa, _rp16_weather_open_meteo, _rp17_news_subscriptions_streams, _rp18_recent_documents_slideshow, _rp19_windows, _rp20_hydra_steam_the, _rp21_avatar_body_desktop, _rp22_windows_apps_volume, _rp23_music_youtube_spotify, _rp24_radio, _rp25_apps, _rp26_media_keys, _rp27_state, _rp28_files_stage_only, _rp29_defender_junk)


CODE_HINTS = r"(код|функци|скрипт|класс|баг|ошибк\w* в|python|питон|javascript|\bjs\b|html|css|sql|php|рефактор|напиши программ)"
FILE_HINTS = r"([a-z]:\\|файл|папк|проект|структур|найди .* в )"


MODE_ALIASES = {
    "low": "low", "light": "low", "низкий": "low", "лёгкий": "low", "легкий": "low",
    "medium": "medium", "mid": "medium", "work": "medium", "средний": "medium", "рабочий": "medium",
    "high": "high", "code": "high", "высокий": "high", "код": "high",
}
MODE_NAMES = {"low": "низкий", "medium": "средний", "high": "высокий"}


def norm_mode(name: str | None) -> str | None:
    return MODE_ALIASES.get((name or "").strip().lower())


def pick_mode(text: str, forced: str | None = None) -> tuple[str, str]:
    """Returns (mode, cleaned_text). Prefix /high, /code, /medium, /low ... forces a mode for one request."""
    m = re.match(r"^/(\w+)\s+(.*)$", text.strip(), re.S)
    if m and norm_mode(m.group(1)):
        return norm_mode(m.group(1)), m.group(2)
    if norm_mode(forced):
        return norm_mode(forced), text
    t = text.lower()
    if (re.search(r"почини|исправь|поправь|отладь|найди ошибк|почему не работает|fix|napraw|popraw|debug", t)
            and re.search(r"код|скрипт|\.py\b|\.js\b|\.ts\b|\.java\b|\.cs\b|\.cpp\b|\.php\b|программ|бот|\[файл: [^\]]+\.(py|js|ts|java|cs|cpp|php|html|css)\]", t)) \
            or re.search(r"\b(сделай|сделать|создай|создать|напиши|написать|разработай|разработать|zrób|stwórz)"
                         r"(?:\s+[\w-]+){0,3}?\s+(приложени|сайт|игр[ауы]?\b|програм|телеграм-?бот|бота?\b|веб-?приложени|аппк|aplikacj|stron)", t):
        return "high", text
    if re.search(CODE_HINTS, t) or re.search(FILE_HINTS, t) or len(text) > 400:
        return "medium", text
    return "low", text
