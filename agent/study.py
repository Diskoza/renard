"""Study mode: school questions (Polish technikum INF.02/03/04 + matura, Russian) answered like a careful tutor.

Small local models make two kinds of mistakes on homework: arithmetic/algebra slips and invented facts (dates, names,
the "correct" ABCD option). So before the model answers, the question gets checked data:
  * math     -> sympy solves the equation / inequality / expression exactly (calc tool, also callable by the model);
  * ABCD test (INF exams) -> the same question is looked up in the public CKE question banks
               (zawodowe.edu.pl, ee-informatyk.pl, egzaminzawodowy.info), the accepted answer is matched to the options;
  * history, literature, chemistry, facts -> Wikipedia intro of the topic (pl/ru/de/en, in the question's language).
The model gets this as «Справка» and a tutor prompt (explain step by step, final answer line, answer language = question).
"""
import asyncio
import html
import json
import re
from difflib import SequenceMatcher

import httpx

from .tools import S, tool
from .logs import quiet

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}

MCQ = re.compile(r"(?m)^\s*\(?[a-dA-D][.)]\s*\S.*\n\s*\(?[a-dA-D][.)]\s*\S")
SUBJ = [
    ("inf", r"\b(ipv[46]|maska|podsie|adres\w* (ip|sieci|mac)|prefiks|vlan|dhcp|dns|router\w*|switch\w*|cisco|osi\b|tcp|udp|"
            r"ipconfig|ping\b|tracert|netsh|active directory|windows server|serwer\w*|drukark\w*|dysk\w*|raid|bios|uefi|"
            r"płyt\w* główn|procesor\w*|pamię\w* ram|zasilacz|kart\w* graficzn|kabel\w*|skrętk\w*|światłowód|"
            r"html|css|php|javascript|sql|select\b|kwerend|baz\w* danych|tabel\w*|klucz\w* (główn|obc)|inf\.0[234]|egzamin\w* zawodow|"
            r"маск\w* (подсет|сети)|подсет|ip[- ]адрес)"),
    ("math", r"(rozwiąż|oblicz|wyznacz|udowodnij|uprość|pochodn|całk|równani|nierównoś|funkcj\w* (kwadratow|liniow|wykładnicz|logarytm)|"
             r"parabol|wierzchoł|trójkąt|prostokąt|okrąg|pole\b|obwód|logarytm|log[₀-₉0-9]|sin|cos|tg\b|ctg|procent\w*|ciąg\w* (arytm|geom)|"
             r"prawdopodob|liczb\w* (naturaln|pierwsz|doskonał|całkowit)|dzielnik|натуральн\w* числ|делител|реши\w*|вычисли|найди (производн|интеграл|корн|площад|x\b)|производн|интеграл|уравнени|неравенств|"
             r"логарифм|вероятност|процент\w*|синус|косинус|сколько будет|горнер|хорнер|horner|многочлен|wielomian|дискриминант|"
             r"\d\s*[-+*/×·:^]\s*\d|[a-z]\s*[²³]|x\s*[=<>]|[=<>]\s*x)"),
    ("physics", r"(fizyk|prędkoś|przyspiesz|opór|oporn|napięci|natężeni|moc\b|energi\w* (kinet|potenc)|ciepł\w* właściw|"
                r"физик|скорост|ускорени|сопротивлени|напряжени|сила тока|мощност|энерги\w*|теплоёмк|джоул|ньютон\w*|"
                r"\b\d+\s*(m/s|км/ч|km/h|ω|Ω|ом\b|в\b|v\b|w\b|вт\b|дж|j\b|kg|кг)\b)"),
    ("history", r"(histori|истори\w*|powstani|wojn\w*|войн\w*|revolu|револю|bitw\w*|битв\w*|król\w*|корол\w*|cesarstw|импери|"
                r"traktat|pokój \w+|konstytucj|reformac|реформац|w którym roku|в каком году|когда (был|была|было|произошл|началась|"
                r"закончил|провозгл)|kiedy (był|była|wybuchł|uchwalon|zakończ)|\bakt\w* \w+|kto (go |je )?(wydał|ogłosił|założył)|"
                r"столиц\w*|stolic\w*|capital of)"),
    ("lit", r"(lektur|лектур|розправк|rozprawk|prac\w* argumentacyjn|wypracowani|matur\w*|wiersz|poemat|powieś|bohater|cytat|"
            r"сочинени|литератур|kto napisał|кто написал|lalk|dziad|potop|pan tadeusz|wesele|makbet|zbrodni\w* i kar)"),
    ("german", r"(niemieck|немецк|deutsch|perfekt|präteritum|akkusativ|dativ|nominativ|rodzajnik|артикл|stopniowani\w* przymiotnik|"
               r"\b(der|die|das)\s+[A-ZÄÖÜ]\w+|\b(ich|du|er|wir|ihr)\s+\w+(e|st|t|en)\b)"),
    ("english", r"(angielsk|английск|present perfect|past simple|future|conditional|phrasal|translate (to|into) english|"
                r"popraw błędy|исправь ошибки|list (formalny|nieformalny)|e-?mail po angielsku)"),
    ("chem", r"(chemi|хими|wzór (sumaryczn|strukturaln|półstruktur)|nazw\w* systematyczn|alkan|alken|alkin|alkohol|kwas\w*|"
             r"mol\b|masa cząsteczk|молярн|реакци\w*|związ\w* organiczn|\bC\d*H\d+)"),
    ("code", r"(złożonoś\w* obliczeniow|сложност\w* алгоритм|big ?o|rekurencj|рекурси|sortowani|сортиров|wyszukiwani\w* binarn|"
             r"бинарн\w* поиск|co wypisze|что выведет|print\(|algorytm|алгоритм|klas\w* i obiekt|ооп|polimorfizm|dziedziczeni)"),
]
SCHOOL = re.compile(r"(sprawdzian|kartkówk|egzamin|matur|zadani\w*|ćwiczeni|lekcj|szkoł|technikum|nauczyciel|"
                    r"контрольн|самостоятельн|экзамен|домашк|домашн\w* задани|урок|в школе|учител|подготов\w* к)", re.I)
NOT_STUDY = re.compile(r"^(открой|запусти|закрой|включи|выключи|поставь|найди файл|скачай|удали|напомни|сделай скрин)", re.I)


TEACH = re.compile(r"^(?:а\s+|ну\s+|слушай\s+|renard\s+|ренар\s+)?(научи|обучи|объясни|растолкуй|расскажи,?\s+как|покажи,?\s+как\s+(решать|считать|делать)|"
                   r"как\s+(решать|решается|считать|делать)|что\s+такое|naucz|wytłumacz|wyjaśnij|wytlumacz|wyjasnij|jak\s+(rozwiązać|rozwiązywać|obliczyć|liczyć)|"
                   r"co\s+to\s+(jest|są)|teach\s+me|explain|erkl[äa]r)", re.I)


FOLLOW = re.compile(r"^(а|и|но|ещё|еще|теперь|почему|зачем|как так|подробнее|не понял|не понимаю|объясни|поясни|другой|другую|другие|"
                    r"другое|ещё раз|еще раз|сделай|напиши|перепиши|исправь|сократи|короче|длиннее|продолжи|дальше|дай|покажи|"
                    r"проверь|а если|i|a|ale|jeszcze|teraz|dlaczego|czemu|napisz|popraw|skróć|inn[aeyi]|wyjaśnij|dalej|kontynuuj|"
                    r"pokaż|daj|zrób|ok|окей|понял|ясно|and|why|now|another|more|continue)\b", re.I)


def followup(text: str) -> bool:
    """«а напиши ещё одну версию, но используй другие лектуры» after a rozprawka: still the same study task."""
    t = (text or "").strip()
    return 2 <= len(t) <= 400 and bool(FOLLOW.search(t)) and not NOT_STUDY.search(t) and not PERSONAL.search(t.lower()) \
        and not re.search(r"[a-z]:\\|погод|pogod|музык|видео|громк|окн|вкладк|хром|chrome|файл|скрипт|папк|проект|экран|"
                          r"plik|skrypt|ekran|открой|запусти|закрой|включи|выключи", t, re.I)


def detect(text: str) -> dict | None:
    """{'subj', 'mcq'} if this is a school / homework / fact question, else None."""
    t = (text or "").strip()
    if len(t) < 8 or NOT_STUDY.search(t) or re.search(r"[a-z]:\\", t, re.I):
        return None
    low = t.lower()
    bare = re.sub(r"['\"«“„][^'\"«»“”„]{3,}['\"»”“]", " ", low)
    if re.search(r"погод|pogod|wetter|weather|прогноз погод|(сколько|который)\s+(сейчас\s+|щас\s+|там\s+)?(времени|час)\b"
                 r"(\s+(сейчас|щас|там))?(\s+(в|во)\s|\s*[?,]|\s+(и|а)\s|$)|która\s+(jest\s+)?godzina|uhrzeit|wie spät", bare):
        return None
    if re.search(r"(мо[яиё]|у меня|какая|какие)\s+(\w+\s+)?(оценк|средн|уроки|урок\w* завтра)|средн\w+ (оценк\w+ )?по |"
                 r"\b(замен\w*|домашк\w*|справдз\w*|kartk[oó]wk\w*)\b.*\b(когда|есть|какие|будет)|"
                 r"(когда|есть ли|какие)\b.*\b(контрольн\w*|справдз\w*|sprawdzian\w*|kartk[oó]wk\w*|замен\w*)|"
                 r"moje oceny|średni\w* (z|ocen)|jakie (mam )?lekcje|первым уроком|какой (у меня )?(завтра )?(первый )?урок", low):
        return None
    t = re.sub(r"(?i)\b(po|по-?)\s?(niemiecku|немецки|angielsku|английски|polsku|польски|rosyjsku|русски)\b|"
               r"auf (deutsch|englisch)|на (немецком|английском|польском)( языке)?", " ", t)
    low = t.lower()
    mcq = bool(MCQ.search(t))
    hits = [name for name, rx in SUBJ if re.search(rx, low if name != "german" else t, re.I)]
    school = bool(SCHOOL.search(t))
    brief = re.search(r"в (двух|трёх|трех|паре|одном|нескольких) (слов|предложени)|в двух словах|коротко|кратко|"
                      r"w (dwóch|kilku) (słowach|zdaniach)|krótko", low)
    if TEACH.search(t) and not (brief and not hits and not school) and not PERSONAL.search(low) and not re.search(
            r"(ренар|renard|себя|тебя|голос|аватар|файл|скрипт|\bкод\w*|проект|папк|ошибк\w* (в|при)|\bэт(от|у|о|и)\b|экран|окн[оае]|"
            r"plik|skrypt|ten |tę |to\b|ekran|okno)", low):
        return {"subj": hits[0] if hits else "general", "mcq": mcq, "all": hits, "teach": True}
    if not hits and not mcq:
        return {"subj": "general", "mcq": False} if school else None
    subj = hits[0] if hits else "inf"
    if mcq and "inf" in hits:
        subj = "inf"
    if mcq or school:
        return {"subj": subj, "mcq": mcq, "all": hits}
    if PERSONAL.search(low):
        return None
    if subj in ("inf", "code") and not re.search(
            r"^(ile|jak\w*|któr\w*|co (to|oznacza|robi|wypisze)|czym|do czego|polecenie|wyjaśnij|сколько|как\w* (маск|команд)|"
            r"что (такое|выведет|делает команда)|чем отлича|для чего|объясни)|złożonoś|сложност", low):
        return None
    if subj == "math" and not re.search(
            r"(rozwiąż|oblicz|wyznacz|wypisz|podaj|znajdź|реши|вычисли|найди|сколько будет|pochodn|производн|uprość|упрост|[=<>]|\?)", low):
        return None
    return {"subj": subj, "mcq": mcq, "all": hits}


PERSONAL = re.compile(r"(мо[йеяи]\w*|у меня|наш\w*|my|mój|moj\w*|nasz\w*)\s+(\w+\s+)?(пк|комп\w*|ноут\w*|видеокарт\w*|сервер\w*|"
                      r"бот\w*|сайт\w*|проект\w*|код\w*|файл\w*|роутер\w*|сет\w*|диск\w*|баз\w*|таблиц\w*|pc|komputer\w*|serwer\w*|"
                      r"projekt\w*|kod\w*|plik\w*|stron\w*|router\w*|sie[cć]\w*|baz\w*|tabel\w*|crm|n8n|supabase)|renard|ренар|"
                      r"supabase|n8n|allegro|coolify|docker")


ALLOWED_NAMES = {"sin", "cos", "tan", "cot", "asin", "acos", "atan", "log", "ln", "sqrt", "exp", "pi", "E", "Abs", "abs",
                 "factorial", "binomial", "x", "y", "z", "m", "n", "k", "a", "b", "c", "t", "p", "q", "oo", "I", "floor", "ceiling",
                 "Rational", "gcd", "lcm", "e"}
SUP = str.maketrans({"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"})
SUB = str.maketrans({"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"})


def normalize(expr: str) -> str:
    s = expr.strip().strip("$").replace("−", "-").replace("–", "-").replace("·", "*").replace("×", "*").replace("÷", "/")
    s = s.replace("π", "pi").replace("≤", "<=").replace("≥", ">=").replace("≠", "!=").replace("∞", "oo").replace(":", "/")
    s = re.sub(r"√\s*\(", "sqrt(", s)
    s = re.sub(r"√\s*([0-9a-z.]+)", r"sqrt(\1)", s)
    s = re.sub(r"log([₀-₉]+)\s*\(?\s*([0-9a-z.]+)\s*\)?", lambda m: f"log({m.group(2)},{m.group(1).translate(SUB)})", s)
    s = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "**" + m.group(1).translate(SUP), s)
    s = re.sub(r"\btg\b", "tan", s)
    s = re.sub(r"\bctg\b", "cot", s)
    s = re.sub(r"\bln\b", "log", s)
    s = s.replace("^", "**")
    if not re.search(r"[a-z]\(", s):
        s = re.sub(r"(\d),(\d)", r"\1.\2", s)
    return s


def _safe(s: str) -> bool:
    if re.search(r"[^0-9a-zA-Z_+\-*/().,=<>!\s]", s) or "__" in s:
        return False
    return all(w in ALLOWED_NAMES for w in re.findall(r"[A-Za-z_]+", s))


def _fmt(v) -> str:
    import sympy as sp
    try:
        txt = sp.sstr(v)
    except Exception:
        txt = str(v)
    txt = txt.replace("**", "^").replace("sqrt", "√").replace("pi", "π")
    return txt


def calc_core(expr: str, op: str = "auto", interval: str = "") -> str:
    import sympy as sp
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                            standard_transformations)
    s = normalize(expr)
    if not _safe(s.replace("<=", "<").replace(">=", ">").replace("!=", "=")):
        return f"Не могу безопасно разобрать выражение: {expr!r}. Пиши как в Python: 2*sin(x+pi/3)=1, x**2-5*x+6<0, log(32,2)"
    tr = standard_transformations + (implicit_multiplication_application, convert_xor)
    syms = {n: sp.Symbol(n, real=True) for n in ("x", "y", "z", "m", "n", "k", "a", "b", "c", "t", "p", "q")}
    loc = {**syms, "ln": sp.log, "e": sp.E, "abs": sp.Abs}
    P = lambda z: parse_expr(z, local_dict=loc, transformations=tr)
    rel = re.search(r"(<=|>=|<|>)", s)
    x = syms["x"]
    try:
        if op in ("diff", "derivative"):
            f = P(s.split("=", 1)[-1])
            v = list(f.free_symbols)[0] if f.free_symbols and x not in f.free_symbols else x
            return f"f'({v}) = {_fmt(sp.simplify(sp.diff(f, v)))}"
        if op in ("integrate", "integral"):
            f = P(s.split("=", 1)[-1])
            return f"∫ = {_fmt(sp.integrate(f, x))} + C"
        if rel:
            lhs, rhs = s[:rel.start()], s[rel.end():]
            ine = {"<": sp.Lt, ">": sp.Gt, "<=": sp.Le, ">=": sp.Ge}[rel.group(1)](P(lhs), P(rhs))
            var = x if x in ine.free_symbols else list(ine.free_symbols)[0]
            sol = sp.solveset(ine, var, sp.Reals)
            return f"Решение неравенства: {var} ∈ {_fmt(sol)}"
        if "=" in s and "==" not in s:
            lhs, rhs = s.split("=", 1)
            eq = sp.Eq(P(lhs), P(rhs))
            free = eq.free_symbols
            var = x if x in free else (list(free)[0] if free else x)
            dom = sp.Reals
            if interval:
                a, b = [P(normalize(v)) for v in re.split(r"[;,]", interval.strip("[]()<> "))[:2]]
                dom = sp.Interval(a, b)
            sol = sp.solveset(eq, var, dom)
            out = f"Решение: {var} ∈ {_fmt(sol)}"
            if isinstance(sol, sp.FiniteSet) and all(v.is_real for v in sol):
                out += "  (≈ " + ", ".join(f"{float(v):.6g}" for v in sol) + ")"
            return out
        f = P(s)
        if f.free_symbols:
            return f"Упрощение: {_fmt(sp.simplify(f))}; разложение: {_fmt(sp.factor(f))}"
        exact = sp.nsimplify(f) if op != "numeric" else f
        num = sp.N(f, 12)
        return f"= {_fmt(exact)}" + (f"  (≈ {float(num):.10g})" if exact != num and num.is_real else "")
    except Exception as e:
        return f"Ошибка расчёта ({type(e).__name__}: {e}). Проверь запись выражения."


@tool("calc", "Точный расчёт (sympy) — для ЛЮБОЙ арифметики, уравнений, неравенств, производных, процентов, физических "
      "формул. expr: '17*23*19', '2*sin(x+pi/3)=1', 'x**2-5*x+6<0', 'x**3*ln(x)' (с op=diff), '4200*2*(100-20)'. "
      "op: auto|diff|integrate|numeric. interval для уравнения: '0, 2*pi'",
      {"expr": S, "op": S, "interval": S}, ["expr"], modes=("low", "medium", "high", "study"))
def calc(expr: str, op: str = "auto", interval: str = "") -> str:
    return calc_core(expr, op or "auto", interval or "")


def find_math(text: str) -> tuple[str, str, str] | None:
    """(expr, op, interval) from a homework question, if one clean formula can be cut out of it."""
    t = text.replace("−", "-").replace("–", "-")
    interval = ""
    iv = re.search(r"[<\[(]\s*(-?[0-9.]*\s*π?|-?\d+)\s*[;,]\s*(-?[0-9.]*\s*π|-?\d+)\s*[>\])]", t)
    if iv:
        interval = f"{iv.group(1) or '0'},{iv.group(2)}"
        t = t[:iv.start()] + t[iv.end():]
    op = "diff" if re.search(r"pochodn|производн|derivative", t, re.I) else "auto"
    runs = []
    for r in re.findall(r"[0-9a-zπ√xX()+\-*/^=<>≤≥·×÷.,²³⁴₀-₉ ]{3,}", t):
        for word in re.finditer(r"[a-z]{2,}", r):
            if word.group(0) not in ("sin", "cos", "tan", "tg", "ctg", "cot", "log", "ln", "sqrt", "pi", "exp", "abs"):
                r = r[:word.start()]
                break
        runs.append(r)
    best = ""
    for r in runs:
        r = r.strip(" ,.")
        r = re.sub(r"^(f\s*\(\s*x\s*\)\s*=|y\s*=)\s*", "" if op == "diff" else r"\g<0>", r)
        if re.search(r"[0-9x]", r) and re.search(r"[-+*/^=<>²³·×≤≥]|sin|cos|log", r) and len(r) > len(best):
            best = r
    if not best:
        return None
    if re.match(r"^y\s*=", best):
        return None
    if not re.search(r"[=<>≤≥]", best) and op != "diff" and re.search(r"x", best):
        return None
    if re.fullmatch(r"[\d\s.,]+", best):
        return None
    return best, op, interval


WIKI_UA = {"User-Agent": "Renard-local-assistant/1.0 (personal desktop assistant)"}


async def wiki_snippets(query: str, lang: str = "pl", n: int = 5) -> list[dict]:
    """Search hits with the sentence where the query words occur — often the fact itself («первый коронованный король»)."""
    async with httpx.AsyncClient(headers=WIKI_UA, timeout=10) as c:
        r = await c.get(f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json",
                                "utf8": 1, "srprop": "snippet"})
    return [{"title": h["title"], "snippet": html.unescape(re.sub(r"<[^>]+>", "", h.get("snippet", "")))}
            for h in r.json().get("query", {}).get("search", [])]


async def wiki_lookup(query: str, lang: str = "pl", n: int = 2, chars: int = 900) -> list[dict]:
    api = f"https://{lang}.wikipedia.org/w/api.php"
    async with httpx.AsyncClient(headers=WIKI_UA, timeout=10) as c:
        r = await c.get(api, params={"action": "query", "list": "search", "srsearch": query, "srlimit": n,
                                     "format": "json", "utf8": 1})
        titles = [h["title"] for h in r.json().get("query", {}).get("search", [])]
        if not titles:
            return []
        r = await c.get(api, params={"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                                     "exchars": chars, "titles": "|".join(titles), "format": "json", "redirects": 1})
        pages = r.json().get("query", {}).get("pages", {}).values()
    by = {p.get("title"): p.get("extract", "") for p in pages}
    return [{"title": t, "text": by.get(t, ""), "url": f"https://{lang}.wikipedia.org/wiki/{t.replace(' ', '_')}"}
            for t in titles if by.get(t)]


@tool("wiki", "Проверить факт по Википедии: даты, имена, события, определения, авторы книг. query — коротко, о чём "
      "(«powstanie styczniowe», «Akt supremacji»); lang — pl|ru|en|de (обычно язык вопроса)",
      {"query": S, "lang": S}, ["query"], modes=("low", "medium", "high", "study"))
async def wiki(query: str, lang: str = "") -> str:
    lang = lang if lang in ("pl", "ru", "en", "de", "uk") else ("ru" if re.search(r"[а-яё]", query, re.I) else "pl")
    try:
        hits = await wiki_lookup(query, lang, 2, 1500)
    except Exception as e:
        return f"Википедия недоступна: {type(e).__name__}"
    if not hits:
        return "В Википедии ничего не нашлось — переформулируй запрос (ключевые слова, без вопроса)."
    return "\n\n".join(f"{h['title']} ({h['url']}):\n{h['text']}" for h in hits)


STOP = set(("w którym roku kiedy kto co jak jaki jaka jakie czy podaj wyjaśnij krótko opisz napisz proszę i oraz a to jest "
            "był była było się na do z ze od po za przez o ten ta te tym tego tej "
            "в каком году когда кто что как какой какая какие почему зачем расскажи объясни коротко кратко напиши "
            "был была было и а но на в во с со по за от до о об про это ли же где куда откуда gdzie dokąd skąd go je ich "
            "wydał ogłosił").split())


def keywords(text: str) -> str:
    words = re.findall(r"[\wąćęłńóśźżÄÖÜäöüß-]+", text)
    out = [w for w in words if w.lower() not in STOP and len(w) > 2 and not w.isdigit()]
    return " ".join(out[:8])


EXAM_SITES = ("zawodowe.edu.pl", "ee-informatyk.pl", "egzamin-informatyk.pl", "egzamininformatyk.pl")


def split_mcq(text: str) -> tuple[str, dict]:
    lines = text.strip().splitlines()
    opts, stem = {}, []
    for l in lines:
        m = re.match(r"^\s*\(?([a-dA-D])[.)]\s*(.+)$", l)
        if m:
            opts[m.group(1).upper()] = m.group(2).strip()
        elif not opts:
            stem.append(l)
    stem_txt = re.sub(r"^\s*(\d+\.|Pytanie\s*\d+)\s*", "", " ".join(stem)).strip()
    stem_txt = re.sub(r"\s*(Wybierz jedną odpowiedź|Odpowiedź|\(Баллов: \d+\))\s*:?\s*$", "", stem_txt)
    return stem_txt, opts


def _sim(a: str, b: str) -> float:
    a, b = re.sub(r"\W+", " ", a.lower()).strip(), re.sub(r"\W+", " ", b.lower()).strip()
    return SequenceMatcher(None, a, b).ratio()


def parse_exam_page(page: str) -> tuple[str, str] | None:
    """(question, accepted answer text) from a CKE question-bank page."""
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for it in items if isinstance(items, list) else [items]:
            q = it.get("mainEntity") if isinstance(it, dict) and it.get("@type") == "QAPage" else None
            if q and q.get("acceptedAnswer"):
                return html.unescape(q.get("name", "")), html.unescape(q["acceptedAnswer"].get("text", ""))
    m = re.search(r"--correct'>\s*<b>[A-D]\.</b>\s*(.*?)</div>", page, re.S)
    if m:
        h = re.search(r"<h2>(.*?)</h2>", page, re.S)
        return html.unescape(re.sub(r"<[^>]+>", "", h.group(1) if h else "")), html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    m = re.search(r'data-is-correct=true[^>]*>\s*<div>\s*[A-D]\.\s*(.*?)</div>', page, re.S)
    if m:
        h = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        return html.unescape(re.sub(r"<[^>]+>", "", h.group(1) if h else "")), html.unescape(m.group(1)).strip()
    return None


async def exam_lookup(text: str) -> str:
    stem, opts = split_mcq(text)
    if len(stem) < 15 or len(opts) < 2:
        return ""
    from .tools.web import web_search
    res = await web_search(stem[:200])
    urls = [u for u in re.findall(r"https?://\S+", res) if any(s in u for s in EXAM_SITES)][:3]
    if not urls:
        res = await web_search(stem[:160] + " INF.02 INF.03 INF.04 egzamin")
        urls = [u for u in re.findall(r"https?://\S+", res) if any(s in u for s in EXAM_SITES)][:3]
    for site in ("ee-informatyk.pl", "egzamin-informatyk.pl"):
        if urls:
            break
        res = await web_search(f"{stem[:160]} site:{site}")
        urls = [u for u in re.findall(r"https?://\S+", res) if site in u][:3]
    async with httpx.AsyncClient(headers=UA, timeout=12, follow_redirects=True) as c:
        for u in urls:
            try:
                page = (await c.get(u)).text
            except Exception:
                continue
            got = parse_exam_page(page)
            if not got:
                continue
            q, ans = got
            if _sim(q, stem) < 0.55:
                continue
            letter, best = max(((k, _sim(v, ans)) for k, v in opts.items()), key=lambda kv: kv[1])
            if best < 0.6:
                continue
            site = u.split("/")[2]
            return (f"\n\n(Справка: этот вопрос есть в базе экзаменационных вопросов CKE ({site}). Принятый правильный "
                    f"ответ: {letter}. {opts[letter]}. Ответь этим вариантом и объясни, почему он верный, а остальные нет.)")
    return ""


def answer_lang(text: str) -> str:
    if len(re.findall(r"[а-яё]", text, re.I)) > len(re.findall(r"[a-ząćęłńóśźż]", text, re.I)):
        return "ru"
    if re.search(r"[ąćęłńśźż]|\b(jest|się|który|jaki|oblicz|podaj|czy|w|na)\b", text, re.I):
        return "pl"
    return "en"


async def prepare(text: str, info: dict) -> str:
    """Checked data appended to the question («Справка»). Never raises; empty string if nothing useful."""
    subj, out = info.get("subj"), []
    try:
        if info.get("mcq"):
            hint = await asyncio.wait_for(exam_lookup(text), 25)
            if hint:
                return hint
        if subj == "math" or (subj == "facts" and re.search(r"\d\s*[-+*/×·]\s*\d", text)):
            fm = find_math(text)
            if fm:
                res = await asyncio.wait_for(asyncio.to_thread(calc_core, *fm), 8)
                if res and not res.startswith(("Ошибка", "Не могу")):
                    out.append(f"(Справка: точный расчёт sympy для «{fm[0].strip()}»"
                               f"{' на ' + fm[2] if fm[2] else ''}: {res}. Это проверенный результат — твой ответ должен "
                               f"с ним совпасть; объясни решение по шагам.)")
        if subj in ("history", "lit", "chem", "general") and not info.get("mcq"):
            lang = answer_lang(text)
            lang = lang if lang in ("pl", "ru") else "en"
            kw = keywords(text)
            hits, snips = await asyncio.wait_for(asyncio.gather(wiki_lookup(kw, lang, 2, 700), wiki_snippets(kw, lang, 5)), 10)
            if hits:
                body = "\n".join(f"— {h['title']}: {h['text']}" for h in hits)
                if snips:
                    body += "\nФрагменты статей, где встречаются слова вопроса:\n" + "\n".join(
                        f"  · {s['title']}: …{s['snippet']}…" for s in snips if s["snippet"])
                out.append(f"(Справка из Википедии ({lang}) — проверенные факты, опирайся на них; если вопрос содержит "
                           f"ложную предпосылку, скажи об этом:\n{body})")
    except Exception:
        quiet()
    return ("\n\n" + "\n\n".join(out)) if out else ""


def _base() -> dict:
    global _BASE
    if _BASE is None:
        import copy
        from .config import SETTINGS
        _BASE = copy.deepcopy(SETTINGS.get("modes", {}).get("study", {}))
    return _BASE


_BASE = None


def profile(modes: dict, info: dict) -> dict:
    """Model settings for this subject: settings.json modes.study + modes.study.subjects[subj] (chosen by eval/study_bench)."""
    base = {k: v for k, v in _base().items() if k != "subjects"}
    sub = (_base().get("subjects") or {}).get(info.get("subj"), {})
    if info.get("mcq"):
        sub = {**sub, **((_base().get("subjects") or {}).get("mcq", {}))}
    return {**base, **sub, "subjects": _base().get("subjects", {})}


STUDY_PROMPT = """РЕЖИМ УЧЁБЫ. Сейчас вопрос по учёбе (польский технікум «technik informatyk», матура, экзамены INF.02/INF.03/INF.04,
или просто вопрос на знание). Ты — внимательный репетитор, а не болтун:
- ЯЗЫК: отвечай на языке вопроса. Польское задание — ответ по-польски (термины как в польской школе). Русский вопрос — по-русски.
- ТОЧНОСТЬ ВАЖНЕЕ СКОРОСТИ. Любой расчёт сложнее устного (умножение многозначных, корни, тригонометрия, уравнения,
  проценты, физические формулы) — через инструмент calc, не в уме. Если в сообщении есть «Справка» — она проверена:
  твой итог обязан с ней совпасть.
- ФАКТЫ (даты, имена, авторы, события): опирайся на «Справку»; если её нет или в ней нет ответа на какую-то часть
  вопроса — вызови wiki с точным запросом («Akt supremacji», «Bolesław Chrobry koronacja»). Никогда не выдумывай.
  Если в вопросе ложная предпосылка («Мицкевич написал Lalkę») — сразу поправь.
- ОТВЕЧАЙ НА КАЖДУЮ ЧАСТЬ ВОПРОСА: «когда и где» — и дата, и место; «кто и когда» — и имя, и год. Проверь перед концом.
- ИНОСТРАННЫЙ ЯЗЫК КАК ПРЕДМЕТ: формы, слова и примеры — на изучаемом языке (Perfekt: «ist gegangen», артикли «das Auto»),
  пояснения — на языке вопроса. Никогда не переводи сами немецкие/английские формы на польский или русский.
- ФОРМАТ: по шагам; формулы в LaTeX ($\\frac{-b\\pm\\sqrt{\\Delta}}{2a}$ в строке, $$…$$ отдельной строкой — окно их
  рисует), простое — юникодом (x², π/2). Схемы и таблицы (схема Горнера, таблица истинности, sortowanie) — markdown-таблицей.
  В конце ЗАДАЧИ (расчёт, тест, вопрос с одним ответом) — отдельная строка «Odpowiedź: …» (по-русски «Ответ: …»);
  у сочинений, объяснений и конспектов такой строки нет.
- «НАУЧИ / ОБЪЯСНИ / naucz / wytłumacz»: 1) идея простыми словами, 2) когда применяется, 3) полный пример по шагам
  (с таблицей, если это схема), 4) типичные ошибки, 5) 2–3 задачи для самопроверки с ответами в конце. Не обрывай.
- НЕ ПЕРЕСПРАШИВАЙ то, что можешь выбрать сам: «другую версию с другими лектурами» — сам возьми другие лектуры
  из списка обязательных — ВСЕ другие, ни одной из прошлой версии (посмотри её выше); «другой пример» — придумай сам.
  Lektury obowiązkowe (matura, wybór): Biblia (Księga Hioba, Apokalipsa), Mitologia, Sofokles «Antygona», Bogurodzica,
  «Lament świętokrzyski», Kochanowski «Treny» i «Odprawa posłów greckich», Szekspir «Makbet» i «Romeo i Julia», Molier «Skąpiec»,
  Krasicki (satyry, bajki), Mickiewicz «Dziady cz. II» i «cz. III», «Pan Tadeusz», ballady, Słowacki «Kordian», Prus «Lalka»,
  Orzeszkowa «Gloria victis», Dostojewski «Zbrodnia i kara», Wyspiański «Wesele», Reymont «Chłopi» (t. I), Żeromski
  «Przedwiośnie», Gombrowicz «Ferdydurke», Bułhakow «Mistrz i Małgorzata», Borowski (opowiadania obozowe),
  Herling-Grudziński «Inny świat», Krall «Zdążyć przed Panem Bogiem», Camus «Dżuma», Orwell «Rok 1984», Mrożek «Tango»,
  Tokarczuk «Profesor Andrews w Warszawie». Пиши только то, что точно есть в произведении (герои, сцены); не уверен — бери другую.
- ТЕСТ ABCD: первая строка — «Odpowiedź: <буква>. <текст варианта>», затем 1–3 предложения, почему верно и почему не другие.
- ЯЗЫКИ (немецкий, английский): правильные формы, артикли, Perfekt с haben/sein, коротко объясни правило.
- СОЧИНЕНИЯ (rozprawka, praca argumentacyjna): по-польски, простым языком ученика: wstęp z tezą, 2–3 argumenty
  с конкретными odwołaniami do lektur (bohaterowie, sceny), kontekst, zakończenie; не меньше требуемого числа слов.
- ПОДГОТОВКА К КОНТРОЛЬНОЙ: короткий конспект по пунктам + 5–10 вопросов для самопроверки с ответами в конце."""
