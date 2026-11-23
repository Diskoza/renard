"""News the owner cares about — no accounts, no API keys:
- new videos of his YouTube channels (public RSS of each channel; the list is imported from Google Takeout
  «subscriptions.csv» or added by name / @handle / link),
- which of his streamers are live on Twitch (decapi.me),
- world / Poland headlines and his topics (Google News RSS).
State: data/news.json {"channels": [{id, name}], "streamers": [...], "topics": [...], "seen": {...}}."""
import asyncio
import csv
import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from ..config import DATA_DIR
from . import I, S, tool

FILE = DATA_DIR / "news.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept-Language": "ru,pl;q=0.8,en;q=0.6"}
COOKIES = {"SOCS": "CAI", "CONSENT": "YES+1"}
DEFAULT = {"channels": [], "streamers": [{"login": "zakvielchannel", "name": "Заквиель"}], "topics": [], "seen": {},
           "edition": "pl"}
EDITIONS = {"pl": "hl=pl&gl=PL&ceid=PL:pl", "ua": "hl=uk&gl=UA&ceid=UA:uk", "uk": "hl=uk&gl=UA&ceid=UA:uk",
            "en": "hl=en-US&gl=US&ceid=US:en", "ru": "hl=ru&gl=PL&ceid=PL:ru"}
ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}


def load() -> dict:
    try:
        return {**DEFAULT, **json.loads(FILE.read_text(encoding="utf-8"))}
    except Exception:
        return json.loads(json.dumps(DEFAULT))


def save(d: dict):
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _ago(ts: float) -> str:
    m = int((time.time() - ts) // 60)
    return f"{m} мин назад" if m < 60 else f"{m // 60} ч назад" if m < 48 * 60 else f"{m // 1440} дн назад"


async def resolve_channel(q: str, c: httpx.AsyncClient) -> dict | None:
    """@handle / link / channel id / plain name -> {id, name}."""
    q = q.strip()
    m = re.search(r"(UC[\w-]{22})", q)
    if m:
        url = f"https://www.youtube.com/channel/{m.group(1)}"
    elif q.startswith("@") or "youtube.com/" in q:
        url = q if q.startswith("http") else f"https://www.youtube.com/{q}"
    else:
        r = await c.get("https://www.youtube.com/results", params={"search_query": q, "sp": "EgIQAg=="})
        m = re.search(r'"channelRenderer":\{"channelId":"(UC[\w-]{22})".{0,400}?"simpleText":"([^"]+)"', r.text)
        return {"id": m.group(1), "name": html.unescape(m.group(2))} if m else None
    r = await c.get(url)
    cid = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', r.text)
    name = re.search(r'<meta property="og:title" content="([^"]+)"', r.text)
    return {"id": cid.group(1), "name": html.unescape(name.group(1)) if name else q} if cid else None


async def channel_videos(ch: dict, c: httpx.AsyncClient) -> list[dict]:
    try:
        r = await c.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": ch["id"]})
        root = ET.fromstring(r.text)
    except Exception:
        return []
    out = []
    for e in root.findall("a:entry", ATOM)[:5]:
        pub = e.findtext("a:published", "", ATOM)
        try:
            ts = time.mktime(time.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except Exception:
            ts = 0
        out.append({"channel": ch["name"], "title": e.findtext("a:title", "", ATOM),
                    "url": f"https://www.youtube.com/watch?v={e.findtext('yt:videoId', '', ATOM)}", "ts": ts})
    return out


def import_takeout(path: str) -> list[dict]:
    """Google Takeout → YouTube → subscriptions.csv: «Channel Id,Channel Url,Channel Title»."""
    p = Path(path)
    if p.is_dir():
        found = sorted(p.rglob("subscriptions.csv")) or sorted(p.rglob("*подписки*.csv"))
        p = found[0] if found else p
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    out = []
    for r in rows[1:]:
        cid = next((x for x in r if re.fullmatch(r"UC[\w-]{22}", x.strip())), None)
        if cid:
            out.append({"id": cid.strip(), "name": r[-1].strip() or cid})
    return out


def find_takeout() -> Path | None:
    home = Path.home()
    for base in (home / "Downloads", home / "OneDrive" / "Desktop", home / "Desktop"):
        if base.exists():
            hits = sorted(base.rglob("subscriptions.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            if hits:
                return hits[0]
    return None


async def twitch_live(s: dict, c: httpx.AsyncClient) -> dict:
    try:
        up = (await c.get(f"https://decapi.me/twitch/uptime/{s['login']}")).text.strip()
        if "offline" in up.lower() or "error" in up.lower() or "not found" in up.lower():
            return {**s, "live": False}
        title = (await c.get(f"https://decapi.me/twitch/title/{s['login']}")).text.strip()
        game = (await c.get(f"https://decapi.me/twitch/game/{s['login']}")).text.strip()
        return {**s, "live": True, "uptime": up, "title": title, "game": game}
    except Exception as e:
        return {**s, "live": None, "error": str(e)}


async def headlines(query: str, c: httpx.AsyncClient, n: int = 6, lang: str = "pl") -> list[dict]:
    hl = EDITIONS.get(lang, EDITIONS["pl"])
    url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}+when:2d&{hl}" if query
           else f"https://news.google.com/rss?{hl}")
    try:
        root = ET.fromstring((await c.get(url)).text)
    except Exception:
        return []
    out = []
    for it in root.iter("item"):
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate", "")).timestamp()
        except Exception:
            ts = 0
        src = it.findtext("source", "") or ""
        title = re.sub(r"\s+-\s+[^-]+$", "", it.findtext("title", ""))
        out.append({"title": title, "source": src, "ts": ts, "url": it.findtext("link", "")})
        if len(out) >= n:
            break
    return out


@tool("news", "Новости и то, что важно пользователю. action: digest (сводка: новые видео его YouTube-каналов, кто из стримеров "
              "в эфире, главные новости и его темы) | youtube (новые видео подписок; query — канал) | twitch (кто в эфире) | "
              "world (главные новости; query — тема; lang — издание: pl Польша, ua Украина, en мир) | add_channel (query — название/@handle/ссылка канала) | "
              "add_streamer (query — ник на Twitch) | add_topic (query) | remove (query) | import (query — путь к "
              "subscriptions.csv из Google Takeout; пусто — найду в Загрузках) | list. days — за сколько дней (по умолчанию 3).",
      {"action": S, "query": S, "days": I, "lang": S}, ["action"])
async def news(action: str = "digest", query: str = "", days: int = 3, lang: str = "") -> str:
    d = load()
    a = (action or "digest").lower()
    q = (query or "").strip()
    async with httpx.AsyncClient(headers=UA, cookies=COOKIES, timeout=15, follow_redirects=True) as c:
        if a == "list":
            return (f"Каналы YouTube ({len(d['channels'])}): " + (", ".join(x["name"] for x in d["channels"]) or "нет") +
                    "\nСтримеры: " + (", ".join(x["name"] for x in d["streamers"]) or "нет") +
                    "\nТемы: " + (", ".join(d["topics"]) or "нет"))
        if a == "import":
            p = Path(q) if q else find_takeout()
            if not p or not p.exists():
                return ("Не нашёл subscriptions.csv. Скачай подписки: takeout.google.com → «Отменить выбор» → отметь только "
                        "YouTube → «Все данные YouTube» → оставь «подписки» → экспорт. Распакуй архив в Загрузки и скажи «импортируй подписки».")
            chans = import_takeout(str(p))
            known = {x["id"] for x in d["channels"]}
            new = [x for x in chans if x["id"] not in known]
            d["channels"] += new
            save(d)
            return f"Импортировал {len(new)} каналов (всего {len(d['channels'])}). Теперь «что нового на ютубе» покажет их новые видео."
        if a == "add_channel":
            ch = await resolve_channel(q, c)
            if not ch:
                return f"Не нашёл канал «{q}». Пришли ссылку на канал или его @handle."
            if ch["id"] not in {x["id"] for x in d["channels"]}:
                d["channels"].append(ch); save(d)
            return f"Добавил канал «{ch['name']}» в твои подписки для новостей."
        if a == "add_streamer":
            login = re.sub(r"^https?://(www\.)?twitch\.tv/", "", q).strip("/@ ").lower()
            if login and login not in {x["login"] for x in d["streamers"]}:
                d["streamers"].append({"login": login, "name": q}); save(d)
            return f"Буду следить за стримами {q}."
        if a == "add_topic":
            if q and q not in d["topics"]:
                d["topics"].append(q); save(d)
            return f"Добавил тему «{q}» в твои новости."
        if a == "remove":
            ql = q.lower()
            before = len(d["channels"]) + len(d["streamers"]) + len(d["topics"])
            d["channels"] = [x for x in d["channels"] if ql not in x["name"].lower()]
            d["streamers"] = [x for x in d["streamers"] if ql not in (x["login"] + x["name"]).lower()]
            d["topics"] = [x for x in d["topics"] if ql not in x.lower()]
            save(d)
            return f"Убрал {before - len(d['channels']) - len(d['streamers']) - len(d['topics'])} записей с «{q}»."

        parts = []
        if a in ("digest", "youtube"):
            chans = [x for x in d["channels"] if not q or q.lower() in x["name"].lower()] if a == "youtube" else d["channels"]
            if not chans and q:
                ch = await resolve_channel(q, c)
                chans = [ch] if ch else []
            if chans:
                vids = [v for lst in await asyncio.gather(*(channel_videos(x, c) for x in chans[:120])) for v in lst]
                since = time.time() - max(1, int(days or 3)) * 86400
                vids = sorted((v for v in vids if v["ts"] >= since), key=lambda v: -v["ts"])
                seen = set(d["seen"].get("yt", []))
                lines = [f"{'🆕 ' if v['url'] not in seen else ''}{v['channel']} — {v['title']} ({_ago(v['ts'])}) {v['url']}"
                         for v in vids[:15]]
                parts.append("📺 Новые видео на твоих каналах:\n" + ("\n".join(lines) if lines else f"за {days} дн. новых нет"))
                d["seen"]["yt"] = list(seen | {v["url"] for v in vids})[-500:]
            elif a == "youtube":
                parts.append("Я пока не знаю твои подписки. Скажи «импортируй подписки» (нужен subscriptions.csv из Google "
                             "Takeout) или «добавь канал <название>».")
        if a in ("digest", "twitch") and d["streamers"]:
            ss = [s for s in d["streamers"] if not q or a != "twitch" or q.lower() in (s["login"] + s["name"]).lower()] or \
                 [{"login": q.lower().strip("@ "), "name": q}]
            st = await asyncio.gather(*(twitch_live(s, c) for s in ss))
            live = [f"🔴 {s['name']} в эфире {s['uptime']}: {s['title']}" + (f" ({s['game']})" if s.get("game") else "")
                    for s in st if s.get("live")]
            off = [s["name"] for s in st if s.get("live") is False]
            parts.append("🎮 Стримы:\n" + "\n".join(live or ["сейчас никто не в эфире"]) + (f"\nне в эфире: {', '.join(off)}" if off and live else ""))
        if a in ("digest", "world"):
            ed = (lang or d.get("edition") or "pl").lower()
            if a == "world" and lang and lang in EDITIONS:
                d["edition"] = lang.lower()
            news_ = await headlines(q if a == "world" else "", c, 6, ed)
            parts.append("🌍 Главное в мире:\n" + "\n".join(f"• {n['title']} ({n['source']}, {_ago(n['ts'])})" for n in news_)
                         if news_ else "🌍 Новости сейчас не загрузились.")
            if a == "digest":
                for tpc in d["topics"][:5]:
                    hs = await headlines(tpc, c, 3, d.get("edition") or "pl")
                    if hs:
                        parts.append(f"🔎 {tpc}:\n" + "\n".join(f"• {n['title']} ({n['source']})" for n in hs))
        save(d)
        return "\n\n".join(parts) or "Пока нечего показать."
