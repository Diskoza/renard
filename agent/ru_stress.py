"""Russian text -> what Piper should read: the letter ё back, and the stress where espeak-ng guesses it wrong.

Piper does not know Russian stress itself: espeak-ng picks it from its dictionary. Two things went wrong all the time:
  * the model writes «е» for «ё» (нашел, идет, еще, самолет, ее, определенный) and espeak then reads «нашЕл», «идЕт»;
  * a few frequent words espeak stresses wrong (пОтом, стоИт, включат).
espeak-ng honours a combining acute (U+0301) after the stressed vowel, so a fix is just a mark in the text.

With the «ruaccent» package installed (a neural model for stress and ё in every word) it runs in its own process while
Renard speaks; these rules cover the seconds it loads and the words it gets wrong too (пОтом).
"""
import json
import re
import threading
import time

ACUTE = "\u0301"
_W = r"(?<![А-Яа-яЁё\w])"
_E = r"(?![А-Яа-яЁё\w])"


YO_WORDS = """еще ее нее чье чьем твое мое свое твоем моем своем твоей? вдвоем втроем вчетвером вперед причем
самолет самолета самолету самолетом самолете самолеты самолетов самолетах
отчет отчета отчету отчетом отчете отчеты отчетов отчетах учет учета учету учетом учете
расчет расчета расчету расчетом расчете расчеты расчетов полет полета полету полетом полете полеты полетов
объем объема объему объемом объеме объемы объемов подъем подъема подъему подъемом
ребенок ребенка ребенку ребенком ребенке елка елки елку елкой ежик ежика шелк лед счет пес ковер котел орел
береза березы березу березой щетка щетки щетку актер актера актеры актеров партнер партнера партнеры партнеров
режиссер режиссера режиссеры шофер шофера контролер боксер дирижер монтер вахтер гример
щелкни щелкнуть щелкнул щелкнула щелкает щелкаю щелчок щелчка
пришел ушел шел нашел зашел вошел прошел перешел дошел пошел подошел отошел обошел сошел вошел нашелся
придет придешь придем придете придется пришлет пришлешь пошлет отошлет перешлет
поймет поймешь поймем возьмет возьмешь возьмем займет займешь
начнет начнешь начнем начнете начнется начнутся? найдется
живет живешь живем живете проживет поет поешь пьет пьешь льет бьет ждет ждешь ждем подождет подождем дождется
зовет зовешь позовет назовет
все-таки? трех четырех""".split()
YO_WORDS = [w for w in YO_WORDS if not w.endswith("?")]

_END_V = r"(?:ет|ем|ешь|ете|ется)"
YO_RX = [
    rf"{_W}(ид|(?:на|по|у|за|во|про|до|подо|ото|пере|произо|обо|со|разо)йд){_END_V}{_E}",
    rf"{_W}(?:при|про|пере|от|у|до|в|на|за|под|об|раз|с|из)?(?:вед|вез|нес){_END_V}{_E}",
    rf"{_W}(?:за|со|раз|под|от|у|пере|на|при)?бер{_END_V}{_E}",
    rf"{_W}(?:во?зда|соз|раз|пере|за|от|по|при|про|из|у|под|с|пре)?да{_END_V}{_E}",
    rf"{_W}(?:в|за|у|от|до|о|пере|при|на|под|рас|вос|пред)ста{_END_V}{_E}",
]
_PART = ("включ|отключ|подключ|сохран|реш|запрещ|разреш|заверш|обновл|удал|перемещ|измен|определ|соедин|объедин|"
         "отмен|упрощ|освобожд|поврежд|оживл|утомл|увлеч|привлеч|отвлеч|вовлеч|лиш|смущ|приближ")
_ADJ_END = r"(?:ый|ий|ая|яя|ое|ые|ие|ого|его|ому|ему|ым|им|ых|их|ую|юю|ой|ыми|ими)"
_ADJ = "черн|зелен|желт|легк|тяжел|тверд|темн|тепл|четк|весел|жестк|серьезн|учен|пестр"


def _yo(m: re.Match) -> str:
    w = m.group(0)
    i = w.lower().rfind("е")
    return w[:i] + ("Ё" if w[i] == "Е" else "ё") + w[i + 1:]


_WORDS_RX = re.compile(_W + "(" + "|".join(sorted(map(re.escape, YO_WORDS), key=len, reverse=True)) + ")" + _E, re.I)
_FAM_RX = [re.compile(rx, re.I) for rx in YO_RX]
_PART_RX = re.compile(rf"{_W}((?:{_PART}))(е)(н(?:н{_ADJ_END})?){_E}", re.I)
_ADJ_RX = re.compile(rf"{_W}(?:{_ADJ}){_ADJ_END}{_E}", re.I)
_VSE_RX = re.compile(_W + r"(все)(?=\s*(?:[.!?;:)\]—–]|,(?!\s*кто)|$)|\s+(?:равно|ещё|еще|это|что|в\s+порядке|готово|понятно|"
                     r"хорошо|правильно|нормально|работает|сделано|получилось|верно|ясно|отлично|сразу|сделал|сделала|"
                     r"сделаю|время|подряд|остальное|то\b|так\b|же\b|прошло|прошел|прошёл|будет|было|зависит|"
                     r"равно|включено|выключено|понял|поняла|сам\b|для\b|про\b|о\b|об\b)"
                     r"|\s+[а-яё]{3,}(?:ю|у|л|ла|ло)(?![а-яё\w]))", re.I)
_PREP_NEM = re.compile(r"(?i)(?<![\w])(о|об|в|во|на|при|по)\s+(нем|чем)(?![\w])")


def restore_yo(text: str) -> str:
    text = _WORDS_RX.sub(_yo, text)
    for rx in _FAM_RX:
        text = rx.sub(_yo, text)
    text = _PART_RX.sub(lambda m: m.group(1) + ("Ё" if m.group(2) == "Е" else "ё") + m.group(3), text)
    text = _ADJ_RX.sub(_yo_first_stem, text)
    text = _VSE_RX.sub(lambda m: m.group(1)[:2] + ("Ё" if m.group(1)[2] == "Е" else "ё"), text)
    text = _PREP_NEM.sub(lambda m: f"{m.group(1)} {m.group(2)[0]}ё{m.group(2)[2]}", text)
    return text


def _yo_first_stem(m: re.Match) -> str:
    """the ё of an adjective is in its stem: «легкий» -> «лёгкий», «серьезный» -> «серьёзный» (last е of the stem)"""
    w = m.group(0)
    stem = re.match(rf"(?i)(?:{_ADJ})", w).group(0)
    i = stem.lower().rfind("е")
    return w[:i] + ("Ё" if w[i] == "Е" else "ё") + w[i + 1:]


STRESS = {"потом": "пото́м", "стоит": "сто́ит", "стоило": "сто́ило", "стоить": "сто́ить", "включат": "включа́т",
          "включатся": "включа́тся", "звонят": "звоня́т", "позвонят": "позвоня́т", "облегчить": "облегчи́ть",
          "углубить": "углуби́ть", "щавель": "щаве́ль", "свекла": "свёкла", "банты": "ба́нты", "торты": "то́рты",
          "каталог": "катало́г", "квартал": "кварта́л", "красивее": "краси́вее", "намерение": "наме́рение",
          "обеспечение": "обеспе́чение", "средства": "сре́дства", "мастерски": "мастерски́", "ходатайство": "хода́тайство",
          "договоры": "догово́ры", "звонишь": "звони́шь", "звоним": "звони́м", "кухонный": "ку́хонный", "сирота": "сирота́",
          "оптовый": "опто́вый", "диспансер": "диспансе́р", "жалюзи": "жалюзи́", "досуг": "досу́г", "добыча": "добы́ча",
          "сливовый": "сли́вовый", "хвоя": "хво́я", "цемент": "цеме́нт", "статуя": "ста́туя", "туфля": "ту́фля"}
_STRESS_RX = re.compile(_W + "(" + "|".join(map(re.escape, STRESS)) + ")" + _E, re.I)
_COST = re.compile(r"(?i)сколько|цен|руб|зл|злот|доллар|евро|грив|дорого|дешев|дешёв|\d")


def _keep_case(src: str, dst: str) -> str:
    return dst[0].upper() + dst[1:] if src[:1].isupper() else dst


def mark_stress(text: str) -> str:
    text = _STRESS_RX.sub(lambda m: _keep_case(m.group(0), STRESS[m.group(0).lower()]), text)
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if _COST.search(sent):
            sent = re.sub(_W + r"(с)(то)(ят)" + _E, lambda m: m.group(1) + m.group(2)[0] + "о" + ACUTE + m.group(3), sent, flags=re.I)
        out.append(sent)
    return " ".join(out)


IDLE_S = 300
_RA = {"proc": None, "ready": False, "starting": False, "last": 0.0, "failed": False}
_RA_LOCK = threading.Lock()


def _enabled() -> bool:
    try:
        from .prefs import get as pget
        if pget("voice.ruaccent", True) is False:
            return False
    except Exception:
        pass
    import importlib.util
    return importlib.util.find_spec("ruaccent") is not None


def _start():
    import subprocess
    import sys
    from pathlib import Path
    try:
        p = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("ruaccent_worker.py"))],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             encoding="utf-8", creationflags=0x08000000 if sys.platform == "win32" else 0)
        first = p.stdout.readline()
        if '"ready"' not in first:
            raise RuntimeError(first[:200] or "worker exited")
        with _RA_LOCK:
            _RA.update(proc=p, ready=True, last=time.time())
        threading.Thread(target=_idle_watch, daemon=True).start()
    except Exception as e:
        print("ruaccent:", e)
        _RA["failed"] = True
    finally:
        _RA["starting"] = False


def _idle_watch():
    while True:
        time.sleep(30)
        with _RA_LOCK:
            p = _RA["proc"]
            if p is None:
                return
            if time.time() - _RA["last"] > IDLE_S or p.poll() is not None:
                stop()
                return


def stop():
    """free the RAM (also called by the idle watch)"""
    p, _RA["proc"], _RA["ready"] = _RA["proc"], None, False
    if p is not None:
        try:
            p.stdin.close()
            p.wait(5)
        except Exception:
            p.kill()


def _neural(text: str, wait: bool = False) -> str | None:
    """«з+амок …» from the worker, or None when it is not running (yet). wait: block until it has loaded (voice bake
    texts — no hurry there, and every phrase should get the real stress)"""
    if _RA["failed"] or not _enabled():
        return None
    if not _RA["ready"]:
        if not _RA["starting"]:
            _RA["starting"] = True
            threading.Thread(target=_start, daemon=True).start()
        if not wait:
            return None
        t0 = time.time()
        while not _RA["ready"] and not _RA["failed"] and time.time() - t0 < 180:
            time.sleep(0.3)
        if not _RA["ready"]:
            return None
    with _RA_LOCK:
        p = _RA["proc"]
        if p is None or p.poll() is not None:
            _RA["ready"] = False
            return None
        _RA["last"] = time.time()
        try:
            p.stdin.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            p.stdin.flush()
            r = json.loads(p.stdout.readline() or "{}")
        except Exception:
            _RA["ready"] = False
            return None
    return r.get("text")


_PLUS_WORD = re.compile(r"[А-Яа-яЁё+]+")


def _from_plus(marked: str) -> str:
    """«наш+ёл п+отом» -> «нашёл пото́м»: «+» becomes an acute after the vowel (none on ё: always stressed), and the
    words espeak and ruaccent both get wrong (STRESS) keep our stress"""
    def word(m):
        w = m.group(0)
        plain = w.replace("+", "")
        if plain.lower() in STRESS:
            return _keep_case(plain, STRESS[plain.lower()])
        return re.sub(r"\+([аеёиоуыэюяАЕЁИОУЫЭЮЯ])", lambda x: x.group(1) + ("" if x.group(1) in "ёЁ" else ACUTE), w)
    return _PLUS_WORD.sub(word, marked)


def rules(text: str) -> str:
    """ё + stress by the rules alone (no ruaccent)"""
    return mark_stress(restore_yo(text))


def for_piper(text: str, wait: bool = False) -> str:
    """the text a Russian Piper voice gets: ё restored, stress marked (ruaccent when it runs, the rules otherwise)"""
    marked = _neural(text, wait)
    if marked and marked.replace("+", "").replace("ё", "е").replace("Ё", "Е") == text.replace("ё", "е").replace("Ё", "Е"):
        return _from_plus(marked)
    return rules(text)
