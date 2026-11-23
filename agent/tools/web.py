"""Basic web search via DuckDuckGo HTML (no API keys) + page fetch."""
import html
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from . import S, tool
from ..logs import quiet

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _ddg_html(t: str) -> list:
    out = []
    for href, title, snip in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                                        r'class="result__snippet"[^>]*>(.*?)</a>', t, re.S):
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        out.append((_clean(title), href, _clean(snip)))
    return out


def _ddg_lite(t: str) -> list:
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]+class=.result-link.[^>]*>(.*?)</a>', t, re.S)
    snips = re.findall(r'class=.result-snippet.[^>]*>(.*?)</td>', t, re.S)
    return [(_clean(ti), unquote(parse_qs(urlparse(h).query).get("uddg", [h])[0]) if "uddg=" in h else h,
             _clean(snips[i]) if i < len(snips) else "") for i, (h, ti) in enumerate(links)]


def _bing(t: str) -> list:
    out = []
    for block in re.findall(r'<li class="b_algo"(.*?)</li>', t, re.S):
        m = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if m:
            sn = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
            out.append((_clean(m.group(2)), _bing_url(m.group(1)), _clean(sn.group(1)) if sn else ""))
    return out


def _bing_url(href: str) -> str:
    """Bing wraps results in a tracking redirect (bing.com/ck/a?…&u=a1<base64url of the real URL>): unwrap it — the
    raw link was useless to the model and broke the site filters (exam bank lookup)."""
    import base64
    import html
    href = html.unescape(href)
    if "bing.com/ck/" not in href:
        return href
    u = parse_qs(urlparse(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        try:
            b = u[2:]
            return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "replace")
        except (ValueError, UnicodeDecodeError):
            pass
    return href


def _region(q: str) -> str:
    if re.search(r"[а-яё]", q, re.I):
        return "ru-ru"
    if re.search(r"[ąćęłńśźż]", q, re.I):
        return "pl-pl"
    if re.search(r"[äöüß]", q, re.I):
        return "de-de"
    return "wt-wt"


def _ddgs(query: str) -> list:
    """ddgs = metasearch (google / yahoo / duckduckgo / brave ... rotated); survives one engine rate-limiting us."""
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
    try:
        res = DDGS(timeout=12).text(query, region=_region(query), max_results=8, backend="auto")
    except DDGSException:
        res = DDGS(timeout=12).text(query, region=_region(query), max_results=8, backend="auto")
    items = [(r.get("title", ""), r.get("href", ""), r.get("body", "")) for r in res if r.get("href")]
    titles = [t for t, _, _ in items if len(t) > 12]
    out = []
    for t, h, b in items:
        cut = min([t.find(o) for o in titles if o != t and t.find(o) > 0] or [len(t)])
        out.append((t[:cut].strip(), h, b))
    return out


@tool("web_search", "Поиск в интернете. Возвращает заголовки, ссылки и описания", {"query": S}, ["query"])
async def web_search(query: str) -> str:
    """ddgs metasearch -> DuckDuckGo html/lite: one engine rate-limiting us must not mean 'nothing found'.
    (Bing without cookies answers only the first word of the query — kept as the very last resort.)"""
    import asyncio
    try:
        items = await asyncio.wait_for(asyncio.to_thread(_ddgs, query), 25)
        if items:
            return "\n".join(f"- {t}\n  {h}\n  {sn}" for t, h, sn in items[:6])
    except Exception:
        quiet()
    engines = [("post", "https://html.duckduckgo.com/html/", {"q": query, "kl": "ru-ru"}, _ddg_html),
               ("post", "https://lite.duckduckgo.com/lite/", {"q": query, "kl": "ru-ru"}, _ddg_lite),
               ("get", "https://www.bing.com/search", {"q": query, "setlang": "ru"}, _bing)]
    errors = []
    async with httpx.AsyncClient(headers={**UA, "Accept-Language": "ru,en;q=0.8"}, timeout=15, follow_redirects=True) as c:
        for method, url, params, parse in engines:
            try:
                r = await (c.post(url, data=params) if method == "post" else c.get(url, params=params))
                items = parse(r.text) if r.status_code == 200 else []
            except Exception as e:
                errors.append(f"{url.split('/')[2]}: {type(e).__name__}")
                continue
            if items:
                return "\n".join(f"- {t}\n  {h}\n  {sn}" for t, h, sn in items[:6])
            errors.append(f"{url.split('/')[2]}: {r.status_code}, 0 результатов")
    return "Поиск не дал результатов (" + "; ".join(errors) + "). Попробуй переформулировать запрос."


RESULT_RX = re.compile(r"^- (.+)\n  (https?://\S+)", re.M)
NOT_VISUAL = re.compile(r"(?i)\b(курс\w*|погод\w*|новост\w*|прогноз\w*|ошибк\w*|error|exception|код\w*|python|javascript|"
                        r"скачать|download|верси\w*|драйвер\w*|расписани\w*|котор\w+ час|время|когда|почему|зачем|"
                        r"как\s+(?:сделать|настро\w*|установ\w*|исправ\w*|включ\w*|удал\w*|подключ\w*|работает)|"
                        r"сколько\s+(?:лет|времени|дней|часов)|перев\w+|translate|закон\w*|налог\w*|статистик\w*|"
                        r"акци\w* компании|stock|api|sql|regex|команд\w*|cmd|powershell|linux|windows)\b")


AD_HOST = re.compile(r"(^|\.)(bing\.com|duckduckgo\.com|doubleclick\.net|googleadservices\.com|google\.com)$")


def sources(results: list[str], answer: str, n: int = 4) -> list[tuple[str, str]]:
    """(title, url) of the search results the answer stood on: the top ones, one per site, minus links the answer
    already gives itself."""
    out, seen = [], set()
    for res in results:
        for title, url in RESULT_RX.findall(res or ""):
            host = urlparse(url).netloc.lower().removeprefix("www.")
            if not host or host in seen or url in (answer or "") or AD_HOST.search(host) or "/aclick" in url:
                continue
            seen.add(host)
            out.append((re.sub(r"\s+", " ", title).strip()[:80] or host, url))
    return out[:n]


def visual(query: str) -> bool:
    return bool(query.strip()) and not NOT_VISUAL.search(query)


def _images(query: str) -> list[dict]:
    from ddgs import DDGS
    res = DDGS(timeout=8).images(query, region=_region(query), safesearch="moderate", max_results=12)
    out, seen = [], set()
    for r in res or []:
        thumb, page = r.get("thumbnail") or "", r.get("url") or ""
        title = _clean(r.get("title") or "")[:80]
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        if thumb.startswith("https://") and (int(r.get("width") or 0) >= 300 or not r.get("width")):
            out.append({"title": title, "src": thumb, "page": page})
    return out


async def images(query: str, n: int = 4) -> list[dict]:
    """Pictures for the answer (the search engine's own thumbnails: they always load, unlike hot-linked originals)."""
    import asyncio
    try:
        return (await asyncio.wait_for(asyncio.to_thread(_images, query), 10))[:n]
    except Exception:
        quiet()
        return []


def sources_md(src: list[tuple[str, str]], pics: list[dict]) -> str:
    """the block under the answer; core strips it again before the history goes back to the model"""
    lines = []
    if pics:
        lines.append(SRC_PICS + " " + " ".join(f"![{p['title'].replace(']', ' ').replace('[', ' ')}]({p['src']})" for p in pics))
    if src:
        lines.append(SRC_HEAD + " " + " · ".join(f"[{t.replace(']', ' ').replace('[', ' ')}]({u})" for t, u in src))
    return "\n\n".join(lines)


SRC_HEAD, SRC_PICS = "**Источники:**", "🖼"
SRC_STRIP = re.compile(r"\n*(?:^🖼 !\[.*$\n*|^\*\*Источники:\*\* .*$\n*)+\Z", re.M)


@tool("fetch_page", "Скачать страницу по ссылке и вернуть её текст (первые ~6000 символов)", {"url": S}, ["url"],
      modes=("medium", "high"))
async def fetch_page(url: str) -> str:
    async with httpx.AsyncClient(headers=UA, timeout=20, follow_redirects=True) as c:
        r = await c.get(url)
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text)
    text = _clean(re.sub(r"\s+", " ", text))
    return text[:6000]
