"""Text -> what a voice should actually say.

Chat answers are written for the eyes (markdown, emoji, +12°C, 3 м/с, YouTube, C:\\path). A TTS engine reads all of that
literally or stumbles on it. This module turns it into plain spoken Russian (numbers and units as words with the right
endings, Latin names in Cyrillic, no emoji/markup) and splits it into phrases so speech can start before the whole
answer is synthesized. Non-Russian text (Polish, English, Ukrainian) only gets the markup/emoji cleanup.
"""
import re

try:
    from num2words import num2words as _n2w
except Exception:
    _n2w = None


def detect_lang(text: str) -> str:
    cyr = len(re.findall(r"\b[А-Яа-яЁёІіЇїЄєҐґ]+", text))
    lat = len(re.findall(r"\b[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż]{2,}", text))
    if cyr and cyr * 2 >= lat:
        uk = len(re.findall(r"[ІіЇїЄєҐґ]", text))
        ru = len(re.findall(r"[ЫыЭэЁёЪъ]", text))
        return "uk" if uk >= 2 and uk > ru else "ru"
    low = text.lower()
    if (re.search(r"[ąćęłńśźżó]", low)
            or re.search(r"\b(jest|się|nie|że|czy|oraz|który|która|które|dla|napisz|krótko|ale|czym|jak|jaki|jaka|jakie|"
                         r"działa|zalety|wady|proszę|dlaczego|kiedy|gdzie|może|bardzo|tylko|odpowiedz|zadanie|opisz|wyjaśnij|"
                         r"podaj|oblicz|siema|cześć|dzięki)\b", low)
            or len(re.findall(r"sz|cz|rz|ść|wy|ow", low)) >= 3 and not re.search(r"\b(the|and|is|are|you|what|how)\b", low)):
        return "pl"
    return "en"


EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U00002300-\U000023FF"
                   "\U0000FE00-\U0000FE0F\U0000200D\U000020E3\U0001F1E6-\U0001F1FF✻✶✦✧★☆●○◆◇■□▪▫►▶◀▸▹•\u200b]")


def strip_markup(text: str) -> str:
    text = re.sub(r"```.*?```", " Код показан на экране. ", text, flags=re.S)
    text = re.sub(r"<[^>]{1,40}>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\((?:https?://)?[^)]*\)", r"\1", text)
    n_links = len(re.findall(r"https?://|www\.", text))
    text = re.sub(r"(?m)^[^\n]{0,80}:\s*\**\s*\n\s*(?:https?://|www\.)\S+\s*$", "", text)
    text = re.sub(r"\(?\s*(?:https?://|www\.)\S+\s*\)?", " ", text)
    text = re.sub(r"(?i)\b(полные|кликабельные|прямые)?,?\s*(кликабельные\s+)?(url|урл|ссылки)\b(?=[^.!?\n]*:)", "ссылки", text)
    if n_links >= 2:
        text = re.sub(r"(?im)(^|[.!?]\s+)[^.!?\n]*\b(?:вот|ниже)\b[^.!?\n]*ссылк\w*[^.!?\n]*:\s*$", r"\1Ссылки — на экране.", text)
    text = re.sub(r"(?m)\s+(и|или|а также)\s*$", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*(.+)$", r"\1.", text)
    text = re.sub(r"(?m)^\s*(?:[-*+•]|\d{1,2}[.)])\s+", "\n", text)
    text = re.sub(r"(?m)^\s*\|.*\|\s*$", " ", text)
    text = re.sub(r"\*\*|__|~~|\*|(?<!\w)_(?!\w)", "", text)
    text = EMOJI.sub(" ", text)
    text = re.sub(r"(\d)\s*(?:…|\.\.\.?)\s*([+\-−]?\d)", r"\1 – \2", text)
    text = text.replace("…", ".").replace(" · ", ", ").replace("·", ", ")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    lines = [l if re.search(r"[.!?:;,]$", l) else l + "." for l in lines]
    return " ".join(lines)


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def num_ru(n: int, gender: str = "m") -> str:
    if _n2w is None:
        return str(n)
    s = _n2w(n, lang="ru")
    if gender == "f":
        s = re.sub(r"\bодин$", "одна", s)
        s = re.sub(r"\bдва$", "две", s)
    elif gender == "n":
        s = re.sub(r"\bодин$", "одно", s)
    return s


def frac_ru(s: str) -> str:
    """1.5 -> полтора, 2,5 -> два с половиной, 3.25 -> три и двадцать пять сотых (short and natural)."""
    a, b = re.split(r"[.,]", s)
    ia = int(a)
    if b.rstrip("0") == "":
        return num_ru(ia)
    if b.rstrip("0") == "5":
        return "полтора" if ia == 1 else f"{num_ru(ia)} с половиной"
    b = b[:2]
    bi = int(b)
    unit = ("десятая", "десятых", "десятых") if len(b) == 1 else ("сотая", "сотых", "сотых")
    return f"{num_ru(ia, 'f')} и {num_ru(bi, 'f')} {plural(bi, *unit)}" if ia else f"{num_ru(bi, 'f')} {plural(bi, *unit)}"


UNITS = {
    "°c": ("градус", "градуса", "градусов", "m"), "°с": ("градус", "градуса", "градусов", "m"), "°": ("градус", "градуса", "градусов", "m"),
    "%": ("процент", "процента", "процентов", "m"),
    "м/с": ("метр в секунду", "метра в секунду", "метров в секунду", "m"),
    "км/ч": ("километр в час", "километра в час", "километров в час", "m"),
    "гб": ("гигабайт", "гигабайта", "гигабайт", "m"), "gb": ("гигабайт", "гигабайта", "гигабайт", "m"),
    "мб": ("мегабайт", "мегабайта", "мегабайт", "m"), "mb": ("мегабайт", "мегабайта", "мегабайт", "m"),
    "кб": ("килобайт", "килобайта", "килобайт", "m"), "kb": ("килобайт", "килобайта", "килобайт", "m"),
    "тб": ("терабайт", "терабайта", "терабайт", "m"), "tb": ("терабайт", "терабайта", "терабайт", "m"),
    "ггц": ("гигагерц", "гигагерца", "гигагерц", "m"), "ghz": ("гигагерц", "гигагерца", "гигагерц", "m"),
    "мгц": ("мегагерц", "мегагерца", "мегагерц", "m"), "mhz": ("мегагерц", "мегагерца", "мегагерц", "m"),
    "гц": ("герц", "герца", "герц", "m"), "hz": ("герц", "герца", "герц", "m"),
    "мм": ("миллиметр", "миллиметра", "миллиметров", "m"), "см": ("сантиметр", "сантиметра", "сантиметров", "m"),
    "км": ("километр", "километра", "километров", "m"), "кг": ("килограмм", "килограмма", "килограммов", "m"),
    "мс": ("миллисекунда", "миллисекунды", "миллисекунд", "f"), "ms": ("миллисекунда", "миллисекунды", "миллисекунд", "f"),
    "сек": ("секунда", "секунды", "секунд", "f"), "мин": ("минута", "минуты", "минут", "f"),
    "fps": ("кадр в секунду", "кадра в секунду", "кадров в секунду", "m"),
    "вт": ("ватт", "ватта", "ватт", "m"), "w": ("ватт", "ватта", "ватт", "m"),
    "₽": ("рубль", "рубля", "рублей", "m"), "руб": ("рубль", "рубля", "рублей", "m"),
    "zł": ("злотый", "злотых", "злотых", "m"), "zl": ("злотый", "злотых", "злотых", "m"), "зл": ("злотый", "злотых", "злотых", "m"),
    "$": ("доллар", "доллара", "долларов", "m"), "€": ("евро", "евро", "евро", "m"), "₴": ("гривна", "гривны", "гривен", "f"),
    "грн": ("гривна", "гривны", "гривен", "f"), "шт": ("штука", "штуки", "штук", "f"),
    "токенов/с": ("токен в секунду", "токена в секунду", "токенов в секунду", "m"),
    "ток/с": ("токен в секунду", "токена в секунду", "токенов в секунду", "m"),
}
_UNIT_RX = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

ABBR = {
    "т.е.": "то есть", "т. е.": "то есть", "т.д.": "так далее", "т. д.": "так далее", "т.п.": "тому подобное",
    "т. п.": "тому подобное", "напр.": "например", "др.": "другие", "ул.": "улица", "стр.": "страница",
    "мин.": "минут", "сек.": "секунд", "тыс.": "тысяч", "млн": "миллионов", "млрд": "миллиардов",
}
WEEKDAYS = {"пн": "понедельник", "вт": "вторник", "ср": "среда", "чт": "четверг", "пт": "пятница", "сб": "суббота",
            "вс": "воскресенье"}
ACRONYMS_RU = {"ПК": "пэ-ка", "ОЗУ": "о-зэ-у", "ИИ": "и-и", "ОС": "о-эс", "ЦП": "цэ-пэ", "СМС": "эс-эм-эс",
               "США": "сэ-шэ-а", "РФ": "эр-эф", "ЕС": "е-эс", "ЖД": "жэ-дэ", "ВПН": "вэ-пэ-эн", "ТВ": "тэ-вэ"}

LATIN = {
    "renard": "ренар", "discord": "дискорд", "chrome": "хром", "google": "гугл", "youtube": "ютуб", "telegram": "телеграм",
    "steam": "стим", "windows": "виндоус", "python": "пайтон", "javascript": "джаваскрипт", "github": "гитхаб",
    "spotify": "спотифай", "whatsapp": "ватсап", "viber": "вайбер", "excel": "эксель", "word": "ворд", "powerpoint": "пауэрпоинт",
    "onedrive": "уан драйв", "edge": "эдж", "firefox": "файрфокс", "opera": "опера", "ollama": "оллама", "whisper": "виспер",
    "piper": "пайпер", "gemma": "джемма", "qwen": "квен", "mistral": "мистраль", "llama": "лама", "vs": "вэ-эс", "code": "код",
    "visual": "вижуал", "studio": "студио", "notepad": "блокнот", "explorer": "проводник", "minecraft": "майнкрафт",
    "epic": "эпик", "games": "геймс", "war": "вар", "thunder": "тандер", "lethal": "летал", "company": "компани",
    "obs": "о-би-эс", "nvidia": "энвидиа", "intel": "интел", "amd": "эй-эм-ди", "rtx": "эр-тэ-икс", "gtx": "джи-ти-икс",
    "core": "кор", "ryzen": "райзен", "wifi": "вай-фай", "wi-fi": "вай-фай", "bluetooth": "блютус", "usb": "ю-эс-би",
    "ok": "окей", "okay": "окей", "email": "имейл", "e-mail": "имейл", "online": "онлайн", "offline": "офлайн",
    "n8n": "эн-эйт-эн", "supabase": "супабейс", "postgresql": "постгрес", "postgres": "постгрес", "react": "реакт",
    "typescript": "тайпскрипт", "cloudflare": "клаудфлер", "workers": "воркерс", "api": "эй-пи-ай", "json": "джейсон",
    "html": "эйч-ти-эм-эль", "css": "си-эс-эс", "sql": "эс-кью-эль", "pdf": "пэ-дэ-эф", "zip": "зип", "exe": "экзе",
    "cpu": "процессор", "gpu": "видеокарта", "ram": "оперативка", "ssd": "эс-эс-дэ", "hdd": "жёсткий диск", "pc": "пэ-ка",
    "ai": "и-и", "llm": "эл-эл-эм", "tts": "ти-ти-эс", "stt": "эс-ти-ти", "lora": "лора", "vram": "видеопамять",
    "allegro": "аллегро", "netflix": "нетфликс", "twitch": "твич",
    "tiktok": "тикток", "instagram": "инстаграм", "facebook": "фейсбук", "x": "икс", "id": "ай-ди", "url": "ссылка",
    "radio": "радио", "music": "мьюзик", "play": "плей", "store": "стор", "app": "эпп", "apps": "эппс", "mod": "мод",
    "mods": "моды", "warszawa": "варшава", "polska": "польска", "ok.": "окей.",
    "calc": "калькулятор", "mspaint": "пэйнт", "paint": "пэйнт", "cmd": "командную строку", "powershell": "пауэршелл",
    "taskmgr": "диспетчер задач", "winword": "ворд", "weather": "погода", "settings": "параметры", "spotify.exe": "спотифай",
    "dzień": "день", "dobry": "добры", "hello": "хэллоу", "hi": "хай", "thanks": "сэнкс", "sorry": "сорри",
}
LETTERS = {"a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи", "h": "эйч", "i": "ай", "j": "джей",
           "k": "кей", "l": "эл", "m": "эм", "n": "эн", "o": "оу", "p": "пи", "q": "кью", "r": "ар", "s": "эс", "t": "ти",
           "u": "ю", "v": "ви", "w": "дабл-ю", "x": "икс", "y": "уай", "z": "зед"}
_TR = [("sch", "ш"), ("tch", "ч"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("ck", "к"), ("qu", "кв"), ("oo", "у"),
       ("ee", "и"), ("ea", "и"), ("ou", "ау"), ("ow", "оу"), ("ai", "ей"), ("ay", "ей"), ("ey", "ей"), ("oy", "ой"),
       ("kh", "х"), ("zh", "ж"), ("ts", "ц"), ("ya", "я"), ("yu", "ю"), ("yo", "ё"), ("x", "кс"), ("j", "дж"),
       ("w", "в"), ("y", "и"), ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"),
       ("h", "х"), ("i", "и"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("q", "к"),
       ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("v", "в"), ("z", "з")]
PL_CHARS = str.maketrans("ąćęłńóśźż", "acelnoszz")


def latin_word(w: str) -> str:
    low = w.lower()
    if low in LATIN:
        return LATIN[low]
    if w.isupper() and len(w) <= 5:
        return "-".join(LETTERS.get(ch, ch) for ch in low)
    s, out, i = low.translate(PL_CHARS), "", 0
    if s.endswith("e") and len(s) > 3:
        s = s[:-1]
    while i < len(s):
        for a, b in _TR:
            if s.startswith(a, i):
                out += b; i += len(a); break
        else:
            out += s[i]; i += 1
    return out


def _date(m):
    d, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= d <= 31 and 1 <= mo <= 12) or _n2w is None:
        return m.group(0)
    o = _n2w(d, lang="ru", to="ordinal")
    o = re.sub(r"(ий)$", "ье", o) if o.endswith("третий") else re.sub(r"(ый|ой|ий)$", "ое", o)
    return f"{o} {MONTHS[mo - 1]}"


ORD_END = {"gen": ("ого", "его"), "prep": ("ом", "ем"), "f": ("ая", "ья"), "n": ("ое", "ье"), "dat": ("ому", "ему"),
           "pl": ("ые", "ьи"), "plgen": ("ых", "ьих")}


def ordinal(n: int, case: str = "m") -> str:
    """1410, 'prep' -> тысяча четыреста десятом (… году);  3, 'gen' -> третьего."""
    if _n2w is None:
        return str(n)
    o = _n2w(n, lang="ru", to="ordinal")
    if 1000 <= n < 2000:
        o = re.sub(r"^одна\s+", "", o)
    if case == "m":
        return o
    a, b = ORD_END[case]
    if o.endswith("третий"):
        return o[:-2] + b
    return re.sub(r"(ый|ой|ий)$", a, o)


GEN_WORDS = {"ноль": "нуля", "один": "одного", "одна": "одной", "одно": "одного", "два": "двух", "две": "двух",
             "три": "трёх", "четыре": "четырёх", "пять": "пяти", "шесть": "шести", "семь": "семи", "восемь": "восьми",
             "девять": "девяти", "десять": "десяти", "двадцать": "двадцати", "тридцать": "тридцати", "сорок": "сорока",
             "пятьдесят": "пятидесяти", "шестьдесят": "шестидесяти", "семьдесят": "семидесяти", "восемьдесят": "восьмидесяти",
             "девяносто": "девяноста", "сто": "ста", "двести": "двухсот", "триста": "трёхсот", "четыреста": "четырёхсот",
             "пятьсот": "пятисот", "шестьсот": "шестисот", "семьсот": "семисот", "восемьсот": "восьмисот", "девятьсот": "девятисот"}


def num_gen(n: int, gender: str = "m") -> str:
    """12 -> двенадцати, 4 -> четырёх (after «от», «до», «около»)."""
    if n >= 1000:
        return num_ru(n, gender)
    return " ".join(GEN_WORDS.get(w, re.sub(r"надцать$", "надцати", w)) for w in num_ru(n, gender).split())


def unit_gen(n: int, spec) -> str:
    """Genitive of the unit after a number in genitive: до 1 метра, до 4 метров."""
    return spec[1] if (n % 10 == 1 and n % 100 != 11) else spec[2]


def _sign(s: str | None) -> str:
    return "плюс " if s == "+" else "минус " if s in ("-", "−") else ""


def year_gen(n: int) -> str:
    """2026 -> две тысячи двадцать шестого (for «… года»)."""
    return ordinal(n, "gen")


def _time(m):
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return m.group(0)
    if mi == 0:
        return f"{num_ru(h)} {plural(h, 'час', 'часа', 'часов')} ровно"
    return f"{num_ru(h)} {('ноль ' + num_ru(mi, 'f')) if mi < 10 else num_ru(mi, 'f')}"


def say_num(sign: str, num: str, unit: str = "") -> str:
    """'+', '12', '°C' -> 'плюс двенадцать градусов';  '', '1,5', 'ГБ' -> 'полтора гигабайта'."""
    spec = UNITS.get(unit.lower()) if unit else None
    num = re.sub(r"[.,]0+$", "", num)
    if re.search(r"[.,]\d", num):
        words = frac_ru(num)
        u = spec[1] if spec else ""
    else:
        n = int(num)
        words = num_ru(n, spec[3] if spec else "m")
        u = plural(n, *spec[:3]) if spec else ""
    pre = "плюс " if sign == "+" else "минус " if sign in ("-", "−") else ""
    return f"{pre}{words} {u}".strip()


def to_ru_speech(text: str) -> str:
    for k, v in ABBR.items():
        text = re.sub(r"(?<!\w)" + re.escape(k) + r"(?!\w)", v, text)
    for k, v in ACRONYMS_RU.items():
        text = re.sub(rf"(?<!\w){k}(?!\w)", v, text)
    text = re.sub(r"https?://\S+|www\.\S+", "ссылка", text)
    path = r"(?:[A-Za-z]:\\(?:[^\s]*[^\s.,;:!?)])?|(?:~|\.{0,2})/[\w./-]+/[\w-]+(?:\.\w+)?)"
    text = re.sub(r"(?<!\w)(в|во|из)\s+" + path, r"\1 папке на экране", text)
    text = re.sub(path, "путь на экране", text)
    text = re.sub(r"\b[\w.-]+@[\w-]+\.\w+\b", "почта", text)
    text = re.sub(r"\b([\w-]+)\.(py|js|ts|json|md|txt|exe|png|jpg|pdf|docx?|xlsx?|pptx?|zip|html|css|mp3|mp4|wav)\b",
                  lambda m: m.group(1).replace("_", " "), text)
    text = re.sub(r"(\d)[  ](?=\d{3}(?!\d))", r"\1", text)
    text = re.sub(r"(?<!\w)(пн|вт|ср|чт|пт|сб|вс)\.?(?=\s+\d)", lambda m: WEEKDAYS[m.group(1)], text, flags=re.I)
    U = r"\s*(" + _UNIT_RX + r")?(?![A-Za-zА-Яа-яЁё0-9])"

    def _range(m):
        spec = UNITS.get((m.group(5) or "").lower())
        a, b = int(m.group(2)), int(m.group(4))
        g = spec[3] if spec else "m"
        return (f"от {_sign(m.group(1))}{num_gen(a, g)} до {_sign(m.group(3))}{num_gen(b, g)}"
                + (f" {unit_gen(b, spec)}" if spec else ""))
    text = re.sub(r"(?<![\w.,])(?:от\s+)?([+\-−])?(\d{1,3})\s*(?:…|\.\.\.?|–|—|\s+до\s+)\s*([+\-−])?(\d{1,3})" + U, _range, text, flags=re.I)

    def _upto(m):
        spec = UNITS[m.group(3).lower()]
        return f"{m.group(0).split()[0]} {_sign(m.group(1))}{num_gen(int(m.group(2)), spec[3])} {unit_gen(int(m.group(2)), spec)}"
    text = re.sub(r"\b(?:до|около|более|менее|свыше|больше|меньше|из)\s+([+\-−])?(\d{1,3})\s*(" + _UNIT_RX + r")(?![A-Za-zА-Яа-яЁё0-9])",
                  _upto, text, flags=re.I)
    text = re.sub(r"(?<![\w.])([+\-−])?(\d+(?:[.,]\d+)?)\s*(" + _UNIT_RX + r")(?![A-Za-zА-Яа-яЁё0-9])",
                  lambda m: say_num(m.group(1) or "", m.group(2), m.group(3)), text, flags=re.I)
    text = re.sub(r"([$€₴₽])\s*(\d+(?:[.,]\d+)?)", lambda m: say_num("", m.group(2), m.group(1)), text)
    text = re.sub(r"\b(в|во)\s+(\d{3,4})\s*г\.", lambda m: f"{m.group(1)} {ordinal(int(m.group(2)), 'prep')} году", text)
    text = re.sub(r"\b(\d{1,4})(?:-?(?:м|ом))?\s+(году|годом)\b", lambda m: ordinal(int(m.group(1)), "prep") + " " + m.group(2), text)
    text = re.sub(r"\b(\d{1,4})\s*(?:года\b|г\.)", lambda m: ordinal(int(m.group(1)), "gen") + " года", text)
    text = re.sub(r"\b(\d{1,4})\s+(годы|годах|годов)\b", lambda m: ordinal(int(m.group(1)), "pl" if m.group(2) == "годы" else "plgen") + " " + m.group(2), text)
    text = re.sub(r"\b(\d{1,4})-(й|ый|ой|ий|я|ая|е|ое|го|ого|му|ому|м|ом|х|ых)\b",
                  lambda m: ordinal(int(m.group(1)), "pl" if m.group(2) == "е" and int(m.group(1)) % 10 == 0 and int(m.group(1)) >= 10 else
                                    {"й": "m", "ый": "m", "ой": "m", "ий": "m", "я": "f", "ая": "f", "е": "n",
                                     "ое": "n", "го": "gen", "ого": "gen", "му": "dat", "ому": "dat", "м": "prep",
                                     "ом": "prep", "х": "plgen", "ых": "plgen"}[m.group(2)]), text)
    text = re.sub(r"(\d+)\s*(с|ч|г)(\.?)(?=[\s,;)!?]*(?:$|[,;)!?]|\.\s|\.$|назад|спустя))",
                  lambda m: (year_gen(int(m.group(1))) + " года" if m.group(2) == "г" else
                             num_ru(int(m.group(1)), "f" if m.group(2) == "с" else "m") + " " +
                             (plural(int(m.group(1)), "секунда", "секунды", "секунд") if m.group(2) == "с"
                              else plural(int(m.group(1)), "час", "часа", "часов"))) + ("" if m.group(2) == "г" else m.group(3)), text)
    text = re.sub(r"\s*\(([^()]{1,80})\)", r", \1,", text)
    text = re.sub(r"\b(\d{1,2})\.(\d{2})(?:\.\d{2,4})?\b(?![.,]\d)", _date, text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, text)
    text = re.sub(r"(?<![\w])([+\-−])(\d)", lambda m: ("плюс " if m.group(1) == "+" else "минус ") + m.group(2), text)
    text = re.sub(r"(\d+)[.,](\d+)", lambda m: frac_ru(m.group(0)), text)
    text = re.sub(r"\d+", lambda m: num_ru(int(m.group(0))) if len(m.group(0)) < 13 else " ".join(num_ru(int(c)) for c in m.group(0)), text)
    for a, b in (("→", ", "), ("->", ", "), ("=>", ", "), ("×", " на "), ("≈", " примерно "), ("~", " примерно "),
                 ("&", " и "), ("=", " равно "), ("№", " номер "), ("/", " "), ("\\", " "), ("|", ", "), ("+", " плюс "),
                 ("<", " "), (">", " "), ("#", " "), ("@", " "), ("^", " "), ("[", " "), ("]", " "), ("{", " "), ("}", " "),
                 ("«", ""), ("»", ""), ('"', ""), ("“", ""), ("”", "")):
        text = text.replace(a, b)
    text = re.sub(r"[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż][A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż'-]*", lambda m: latin_word(m.group(0)), text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])(?=[^\s\d])", r"\1 ", text)
    text = re.sub(r"[,;:]\s*([.!?])", r"\1", text)
    text = re.sub(r"(,\s*){2,}", ", ", text)
    text = re.sub(r"(^|[.!?]\s+),\s*", r"\1", text)
    text = re.sub(r"\.{2,}", ".", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + ".") + " Остальное на экране."


def for_speech(text: str, lang: str | None = None, limit: int = 700) -> tuple[str, str]:
    """-> (spoken text, language). Long stats/tables are cut to the head."""
    text = strip_markup(text or "")
    lang = lang or detect_lang(text)
    if lang == "ru":
        text = to_ru_speech(text)
    else:
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
    return shorten(text, limit), lang


def phrases(text: str, max_len: int = 220) -> list[str]:
    """Split spoken text into phrases: the first one short (speech starts sooner), the rest up to max_len."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out, cur = [], ""
    for p in parts:
        while len(p) > max_len:
            cut = p.rfind(", ", 0, max_len)
            cut = cut if cut > max_len // 3 else p.rfind(" ", 0, max_len)
            out += [x for x in (cur, p[:cut + 1].strip()) if x]; cur, p = "", p[cut + 1:].strip()
        limit = 90 if not out else max_len
        if cur and len(cur) + len(p) + 1 > limit:
            out.append(cur); cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        out.append(cur)
    return [p for p in out if re.search(r"\w", p)]


EN_RUN = re.compile(r"(?<![\w'’])((?:[A-Za-z][A-Za-z0-9'’-]*[ \t,:;&()\-—–]+){2,}[A-Za-z][A-Za-z0-9'’-]*[.!?]?)")


def speech_segments(text: str, limit: int = 700, english: bool = True) -> tuple[list[tuple[str, str]], str]:
    """-> ([(spoken text, lang), …], main language). In a Russian answer, runs of 3+ English words (a song title,
    a quote, an English sentence) are read by the English voice instead of a Russian «транслит» accent."""
    clean = strip_markup(text or "")
    lang = detect_lang(clean)
    if lang == "en" and len(re.findall(r"\b[А-Яа-яЁё]{2,}", clean)) >= 2:
        lang = "ru"
    if lang != "ru" or not english or not EN_RUN.search(clean):
        spoken, lang = for_speech(text, lang, limit)
        return [(spoken, lang)], lang
    segs, pos, total = [], 0, 0
    for m in EN_RUN.finditer(clean):
        run = m.group(1).strip(" ,;:-")
        if len(re.findall(r"[A-Za-z]{2,}", run)) < 3 or len(run) < 12:
            continue
        before = clean[pos:m.start()]
        if before.strip():
            segs.append((to_ru_speech(before), "ru"))
        segs.append((re.sub(r"\s+", " ", run), "en"))
        pos = m.end()
    if clean[pos:].strip():
        segs.append((to_ru_speech(clean[pos:]), "ru"))
    out = []
    for s, l in segs:
        s = s.strip(" ,")
        if not re.search(r"\w", s):
            continue
        if total + len(s) > limit:
            out.append((shorten(s, max(40, limit - total)), l))
            break
        out.append((s, l))
        total += len(s)
    return out or [(for_speech(text, "ru", limit)[0], "ru")], "ru"
